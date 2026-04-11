"""
重试引擎 - 管理 LLM 调用失败时的重试机制。

职责：
- 执行带重试的生成操作
- 动态调整生成参数（温度等）
- 记录重试历史用于分析

重试策略：
- 指数退避：每次重试增加延迟
- 温度调整：根据失败类型调整温度
- 参数注入：将失败信息注入下一轮提示

使用方式：
    engine = RetryEngine(config)

    result = await engine.execute_with_retry(
        generate_func=lambda temp, hint: generate(temp, hint),
        validate_func=lambda text: validate(text),
        context=context,
    )
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.drafting_core.retry.parameter_adjuster import ParameterAdjuster

if TYPE_CHECKING:
    from backend.schemas import DraftingFeatureFlags

logger = logging.getLogger(__name__)


@dataclass
class RetryState:
    """
    重试状态数据类。

    业务含义：
    - 封装重试过程中的所有状态
    - 便于在重试循环中追踪进度

    字段说明：
    - attempt: 当前尝试次数
    - current_temp: 当前温度参数
    - pending_hint: 追加到下一轮的修正提示
    - prompts_history: 所有尝试的 prompt 记录
    - chunk: 当前生成的文本片段
    - is_valid: 是否通过验证
    """
    attempt: int = 0
    current_temp: float = 0.7
    pending_hint: str = ""
    prompts_history: List[dict] = field(default_factory=list)
    chunk: str = ""
    is_valid: bool = False
    fail_reason: str = ""
    fail_categories: List[str] = field(default_factory=list)

    def reset(self) -> None:
        """重置状态用于新一次重试"""
        self.attempt = 0
        self.chunk = ""
        self.is_valid = False
        self.fail_reason = ""
        self.fail_categories = []


@dataclass
class RetryResult:
    """
    重试结果数据类。

    业务含义：
    - 统一重试操作的返回格式
    - 包含最终文本和元数据
    """
    text: str
    success: bool
    attempts: int
    final_temperature: float
    prompts_history: List[dict]
    fail_reason: Optional[str] = None


class RetryEngine:
    """
    重试引擎。

    职责：
    - 封装重试逻辑，提供简洁的接口
    - 管理重试参数（温度、提示词）
    - 处理验证失败和异常情况

    设计决策：
    - 使用指数退避避免对 LLM 服务造成压力
    - 每次重试增加 0.1 温度以增加多样性
    - 最终失败时返回部分结果而非抛出异常
    """

    DEFAULT_MAX_ATTEMPTS = 3
    DEFAULT_INITIAL_TEMPERATURE = 0.7
    DEFAULT_TEMPERATURE_STEP = 0.1

    def __init__(
        self,
        config: Dict[str, Any],
        max_attempts: Optional[int] = None,
        initial_temperature: float = DEFAULT_INITIAL_TEMPERATURE,
        temperature_step: float = DEFAULT_TEMPERATURE_STEP,
    ):
        """
        初始化重试引擎。

        Args:
            config: 配置对象，包含 feature_flags
            max_attempts: 最大尝试次数（默认从配置读取）
            initial_temperature: 初始温度
            temperature_step: 每次重试的温度增量
        """
        self._config = config
        self._max_attempts = max_attempts or self._get_max_attempts()
        self._initial_temp = initial_temperature
        self._temp_step = temperature_step
        self._parameter_adjuster = ParameterAdjuster(config)

    def _get_max_attempts(self) -> int:
        """从配置获取最大尝试次数"""
        feature_flags = self._config.get("feature_flags", {})
        if isinstance(feature_flags, dict):
            return feature_flags.get("fail_fast_max_attempts", self.DEFAULT_MAX_ATTEMPTS)
        return getattr(feature_flags, "fail_fast_max_attempts", self.DEFAULT_MAX_ATTEMPTS)

    async def execute_with_retry(
        self,
        generate_func: Callable[[float, str], Tuple[str, str, str]],
        validate_func: Optional[Callable[[str], Tuple[bool, str, List[str]]]] = None,
        enable_fail_fast: bool = True,
        on_attempt: Optional[Callable[[int, str], None]] = None,
    ) -> RetryResult:
        """
        执行带重试的生成操作。

        职责：这是重试引擎的核心方法，封装完整的重试流程。

        业务场景：
        - LLM 服务暂时不可用时自动重试
        - 验证失败时根据失败原因调整参数重试
        - 超过最大重试次数后返回降级结果

        Args:
            generate_func: 生成函数，接收 (temperature, pending_hint)，
                          返回 (text, system_prompt, user_prompt)
            validate_func: 验证函数，接收 text，
                          返回 (is_valid, fail_reason, fail_categories)
            enable_fail_fast: 是否启用即时断言检查
            on_attempt: 每次尝试的回调函数，接收 (attempt, chunk)

        Returns:
            RetryResult: 包含最终文本和重试信息的结果

        Raises:
            无异常，最终失败时返回 RetryResult with success=False
        """
        state = RetryState(current_temp=self._initial_temp)
        max_attempts = self._max_attempts if enable_fail_fast else 1

        logger.info(f"[RetryEngine] 开始执行，最多 {max_attempts} 次尝试")

        while state.attempt < max_attempts and not state.is_valid:
            state.attempt += 1

            try:
                # 执行单次生成
                chunk, sys_p, usr_p = await self._safe_generate(
                    generate_func, state.current_temp, state.pending_hint
                )
                state.chunk = chunk

                # 记录 prompt
                state.prompts_history.append({
                    "stage": f"ATTEMPT_{state.attempt}",
                    "temperature": state.current_temp,
                    "system_prompt": sys_p,
                    "user_prompt": usr_p,
                })

                # 回调通知
                if on_attempt:
                    on_attempt(state.attempt, chunk)

                # 处理空响应
                if not chunk:
                    logger.warning(f"[RetryEngine] 第 {state.attempt} 次返回空文本")
                    if state.attempt < max_attempts:
                        state.current_temp = min(1.0, state.current_temp + 0.1)
                        continue

                # 验证（如果启用）
                if validate_func and enable_fail_fast and state.attempt < max_attempts:
                    is_valid, fail_reason, fail_categories = await self._safe_validate(
                        validate_func, chunk
                    )

                    if not is_valid:
                        logger.warning(
                            f"[RetryEngine] 第 {state.attempt} 次验证失败: {fail_reason}"
                        )
                        state.is_valid = False
                        state.fail_reason = fail_reason
                        state.fail_categories = fail_categories

                        # 根据失败原因调整参数
                        state.current_temp, state.pending_hint = \
                            self._parameter_adjuster.adjust(
                                current_temp=state.current_temp,
                                fail_categories=fail_categories,
                                fail_reason=fail_reason,
                            )
                    else:
                        state.is_valid = True
                else:
                    state.is_valid = True

            except Exception as e:
                logger.error(
                    f"[RetryEngine] 第 {state.attempt} 次异常: {type(e).__name__}: {e}"
                )
                if state.attempt >= max_attempts:
                    break
                # 指数退避
                await asyncio.sleep(min(2 ** state.attempt, 10))

        logger.info(
            f"[RetryEngine] 完成，尝试次数={state.attempt}, "
            f"有效={state.is_valid}, 字数={len(state.chunk)}"
        )

        return RetryResult(
            text=state.chunk,
            success=state.is_valid or state.attempt > 0,
            attempts=state.attempt,
            final_temperature=state.current_temp,
            prompts_history=state.prompts_history,
            fail_reason=state.fail_reason if not state.is_valid else None,
        )

    async def _safe_generate(
        self,
        generate_func: Callable,
        temperature: float,
        pending_hint: str,
    ) -> Tuple[str, str, str]:
        """
        安全执行生成函数。

        捕获异常并记录日志。

        Args:
            generate_func: 生成函数
            temperature: 温度参数
            pending_hint: 修正提示

        Returns:
            Tuple[str, str, str]: (text, system_prompt, user_prompt)
        """
        try:
            return await generate_func(temperature, pending_hint)
        except Exception as e:
            logger.error(f"[RetryEngine] 生成异常: {e}")
            return "", "", ""

    async def _safe_validate(
        self,
        validate_func: Callable,
        text: str,
    ) -> Tuple[bool, str, List[str]]:
        """
        安全执行验证函数。

        捕获异常并返回默认值。

        Args:
            validate_func: 验证函数
            text: 待验证文本

        Returns:
            Tuple[bool, str, List[str]]: (is_valid, fail_reason, fail_categories)
        """
        try:
            return await validate_func(text)
        except Exception as e:
            logger.warning(f"[RetryEngine] 验证异常: {e}")
            return True, "", []

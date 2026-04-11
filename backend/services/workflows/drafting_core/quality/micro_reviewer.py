"""
微观审阅器 - 检查生成文本的角色一致性和逻辑正确性。

职责：
- 调用 LLM 执行角色扮演审阅
- 检查 OOC、物理幻觉、关系状态等问题
- 与代码级校验（DraftValidatorPipeline）配合使用

审阅维度：
- 角色一致性 (OOC)
- 物理状态一致性
- 关系状态一致性
- 红线合规性

使用方式：
    reviewer = MicroReviewer(config)
    is_valid, reason, categories = await reviewer.review(
        chunk_text=chunk,
        context=context,
    )
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.prompts import build_micro_review_prompt
from backend.services.workflows.drafting_thinking import _call_llm_with_stats
from backend.services.workflows.utils import clean_llm_output
from backend.schemas import MicroReviewResult

if TYPE_CHECKING:
    from backend.services.llm import LLMClient

logger = logging.getLogger(__name__)


class MicroReviewer:
    """
    微观审阅器。

    职责：
    - 调用 LLM 执行角色扮演审阅
    - 检查生成文本是否符合角色设定和世界观

    设计决策：
    - 使用专门的 LLM 调用进行审阅（而非在生成 Prompt 中混入）
    - 支持代码级校验作为前置过滤
    - 失败时返回具体原因供重试使用
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client: Optional["LLMClient"] = None,
    ):
        """
        初始化微观审阅器。

        Args:
            config: 配置对象
            llm_client: LLM 客户端（可选）
        """
        self._config = config
        self._llm_client = llm_client
        self._feature_flags = config.get("feature_flags", {})

    async def review(
        self,
        chunk_text: str,
        context: Dict[str, Any],
        beat: Optional[dict] = None,
    ) -> Tuple[bool, str, List[str]]:
        """
        执行微观审阅。

        Args:
            chunk_text: 待审阅的文本
            context: 上下文，包含：
                - dynamic_context: 动态上下文
                - pov_character: POV 角色名
                - entity_spatial_ledger: 实体空间台账
            beat: 节拍数据（可选，包含 red_lines 等）

        Returns:
            Tuple[bool, str, List[str]]: (是否通过, 失败原因, 失败类别)
        """
        try:
            # 1. 代码级校验（前置过滤）
            validation_result = await self._code_level_validation(chunk_text, context, beat)
            if not validation_result.is_valid:
                return False, validation_result.errors[0], validation_result.categories

            # 2. LLM 审阅
            return await self._llm_review(chunk_text, context, beat)

        except json.JSONDecodeError as e:
            logger.warning(f"[MicroReviewer] JSON 解析失败: {e}")
            return True, "", []
        except Exception as e:
            logger.warning(f"[MicroReviewer] 审阅异常: {e}")
            return True, "", []

    async def _code_level_validation(
        self,
        chunk_text: str,
        context: Dict[str, Any],
        beat: Optional[dict],
    ) -> "ValidationResult":
        """
        执行代码级校验。

        这是前置过滤，用于快速检测明显的错误。

        Args:
            chunk_text: 待校验文本
            context: 上下文
            beat: 节拍数据

        Returns:
            ValidationResult: 校验结果
        """
        # 导入校验管道
        try:
            from backend.services.workflows.validators import DraftValidatorPipeline

            validator = DraftValidatorPipeline()

            val_context = {
                "pacing_type": beat.get("pacing_type", "medium") if beat else "medium",
                "red_lines": beat.get("red_lines", []) if beat else [],
                "required_entities": beat.get("required_entities", []) if beat else [],
                "forbidden_locations": beat.get("forbidden_locations", []) if beat else [],
                "entities": context.get("entities", []),
            }

            result = await validator.validate_draft(chunk_text, val_context)

            if not result.is_valid:
                return ValidationResult(
                    is_valid=False,
                    errors=result.errors,
                    categories=["代码校验"] + result.categories,
                )

            return ValidationResult(is_valid=True, errors=[], categories=[])

        except ImportError:
            # 如果校验管道不存在，跳过代码级校验
            return ValidationResult(is_valid=True, errors=[], categories=[])
        except Exception as e:
            logger.warning(f"[MicroReviewer] 代码级校验异常: {e}")
            return ValidationResult(is_valid=True, errors=[], categories=[])

    async def _llm_review(
        self,
        chunk_text: str,
        context: Dict[str, Any],
        beat: Optional[dict],
    ) -> Tuple[bool, str, List[str]]:
        """
        执行 LLM 审阅。

        Args:
            chunk_text: 待审阅文本
            context: 上下文
            beat: 节拍数据

        Returns:
            Tuple[bool, str, List[str]]: (是否通过, 失败原因, 失败类别)
        """
        # 提取上下文信息
        dynamic_context = context.get("dynamic_context")
        pov_character = context.get("pov_character", "")
        entity_spatial_ledger = context.get("entity_spatial_ledger")

        # 构建物理状态锁
        effective_physical_lock = dynamic_context.physical_state_lock if dynamic_context else ""
        if entity_spatial_ledger:
            from backend.services.prompts.draft_prompts import _format_entity_spatial_ledger
            spatial_info = _format_entity_spatial_ledger(entity_spatial_ledger)
            if spatial_info:
                effective_physical_lock = f"{effective_physical_lock}\n\n【角色空间绑定】:\n{spatial_info}"

        # 构建 prompt
        system_prompt, user_prompt = build_micro_review_prompt(
            chunk_text=chunk_text,
            physical_state_lock=effective_physical_lock,
            pov_character=pov_character,
            red_lines=beat.get("red_lines") if beat else None,
            relational_state_lock=dynamic_context.relational_state_lock if dynamic_context else "",
        )

        # 调用 LLM
        model = self._config.get("reasoning_model", "")
        response = await _call_llm_with_stats(
            stage="micro_review",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=self._config.get("api_key", ""),
            base_url=self._config.get("base_url", ""),
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=200,
        )

        # 解析结果
        result_text = clean_llm_output(response).strip()
        result = json.loads(result_text)
        review_result = MicroReviewResult(**result)

        # 构建失败原因
        failed_reason = review_result.reason or "未知逻辑错误"
        if review_result.failed_checks:
            failed_reason = f"[检查项 {', '.join(review_result.failed_checks)}] {failed_reason}"

        # 推断失败类别
        fail_categories = self._infer_categories(
            failed_reason, review_result.failed_checks or []
        )

        if review_result.pass_check:
            return True, "", []
        else:
            return False, failed_reason, fail_categories

    def _infer_categories(
        self,
        fail_reason: str,
        failed_checks: List[str],
    ) -> List[str]:
        """
        从失败原因推断失败类别。

        Args:
            fail_reason: 失败原因
            failed_checks: 检查项列表

        Returns:
            List[str]: 失败类别列表
        """
        from backend.services.workflows.drafting_core.retry.parameter_adjuster import ParameterAdjuster

        adjuster = ParameterAdjuster(self._config)
        return adjuster.infer_fail_categories(fail_reason, failed_checks)


@dataclass
class ValidationResult:
    """代码级校验结果"""
    is_valid: bool
    errors: List[str]
    categories: List[str]


# 添加 dataclass 装饰器支持
from dataclasses import dataclass

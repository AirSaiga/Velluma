"""
串行滑动窗口策略 - 保持完整上下文连贯性。

特点：
- Beat 1 → Beat 2 → ... → Beat N 串行生成
- 每个 Beat 使用上一 Beat 的真实尾部作为 previous_tail
- 保持完整的 Rolling Prefix 连贯性
- 速度较慢但质量最高

使用方式：
    strategy = SerialStrategy(config, llm_client)
    results = await strategy.execute(beats, scene_intents, subcons, context)
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy, GenerationResult, BeatContext
from backend.services.workflows.drafting_core.context.context_manager import ContextManager
from backend.services.workflows.drafting_core.context.state_updater import StateUpdater
from backend.services.workflows.drafting_core.retry.retry_engine import RetryEngine
from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker
from backend.services.workflows.beat_utils import safe_get_from_list, clamp_tokens
from backend.services.prompts import build_prose_draft_prompt_v25
from backend.services.workflows.drafting_thinking import _call_llm_with_stats
from backend.services.workflows.utils import clean_llm_output

if TYPE_CHECKING:
    from backend.services.llm import LLMClient

logger = logging.getLogger(__name__)


class SerialStrategy(GenerationStrategy):
    """
    串行滑动窗口策略。

    职责：
    - 实现串行生成的核心逻辑
    - 管理 Rolling Prefix
    - 协调上下文更新

    设计决策：
    - 每个 Beat 完成后立即更新上下文
    - previous_tail 包含真实文本尾部，保证衔接
    - 失败时整个流程终止（不适合长序列）
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client: Optional["LLMClient"] = None,
        quality_checker: Optional[QualityChecker] = None,
        retry_engine: Optional[RetryEngine] = None,
    ):
        super().__init__(config, llm_client, quality_checker, retry_engine)
        self._context_manager = ContextManager(config)
        self._state_updater = StateUpdater(config, llm_client)

    async def execute(
        self,
        beats: List[dict],
        scene_intent_results: List[dict],
        subconscious_results: List[str],
        context: Dict[str, Any],
    ) -> List[GenerationResult]:
        """
        执行串行生成。

        流程：
        1. 初始化动态上下文
        2. 遍历每个 Beat：
           a. 构建 Beat 上下文
           b. 执行生成（带重试）
           c. 执行质量检查
           d. 更新动态上下文
        3. 返回所有结果

        Args:
            beats: 故事节拍列表
            scene_intent_results: 场景意图结果
            subconscious_results: 潜意识思考结果
            context: 生成上下文

        Returns:
            List[GenerationResult]: 每个节拍的生成结果
        """
        n = len(beats)
        word_count = context.get("word_count", 2000)

        logger.info(f"[SerialStrategy] 开始串行生成，Beats={n}")

        # 1. 初始化动态上下文
        dynamic_context = self._context_manager.create_serial_context(
            beats=beats,
            entities=context.get("entities", []),
            relationships=context.get("relationships", []),
            physical_state_lock=context.get("physical_state_lock"),
            entity_spatial_ledger=context.get("entity_spatial_ledger"),
        )

        # 2. 逐个 Beat 生成
        all_results = []
        total_start = time.perf_counter()

        for beat_idx, beat in enumerate(beats):
            beat_start = time.perf_counter()

            # 构建 Beat 上下文
            target_words = self._calculate_target_words(beat, word_count, n)
            beat_context = self._create_beat_context(
                beat=beat,
                beat_index=beat_idx,
                total_beats=n,
                scene_intent=safe_get_from_list(
                    scene_intent_results, beat_idx,
                    {"intent_label": "默认", "goal": beat.get("summary", "")}
                ),
                subconscious=safe_get_from_list(subconscious_results, beat_idx, ""),
                target_words=target_words,
            )

            # 生成单个 Beat
            result = await self._generate_single_beat(
                beat_context=beat_context,
                dynamic_context=dynamic_context,
                context=context,
            )

            beat_time = time.perf_counter() - beat_start
            result.generation_time = beat_time
            all_results.append(result)

            logger.info(
                f"[SerialStrategy] Beat {beat_idx + 1}/{n} 完成，"
                f"字数={len(result.text)}, 耗时={beat_time:.2f}s"
            )

            # 更新动态上下文
            await self._update_context(
                dynamic_context=dynamic_context,
                beat=beat,
                beat_idx=beat_idx,
                beats=beats,
                result=result,
                context=context,
            )

        total_time = time.perf_counter() - total_start
        logger.info(f"[SerialStrategy] 串行生成完成，总耗时={total_time:.2f}s")

        return all_results

    async def _generate_single_beat(
        self,
        beat_context: BeatContext,
        dynamic_context: Any,
        context: Dict[str, Any],
    ) -> GenerationResult:
        """
        生成单个 Beat 的正文。

        Args:
            beat_context: Beat 上下文
            dynamic_context: 动态上下文
            context: 生成上下文

        Returns:
            GenerationResult: 生成结果
        """
        beat = beat_context.beat
        beat_number = beat_context.beat_number
        pov_profile = self._get_pov_profile(
            beat_context.beat.get("pov_character", ""),
            context.get("entities", [])
        )

        # 定义生成函数
        async def generate_once(
            temperature: float,
            pending_hint: str,
        ) -> Tuple[str, str, str]:
            sys_p, usr_p = build_prose_draft_prompt_v25(
                chapter=context.get("chapter"),
                book=context.get("book"),
                beat=beat,
                scene_intent=beat_context.scene_intent,
                subconscious_thought=beat_context.subconscious,
                previous_tail=dynamic_context.previous_tail,
                target_words=beat_context.target_words,
                physical_state_lock=dynamic_context.physical_state_lock,
                current_emotional_state=dynamic_context.current_emotional_state,
                accumulated_summary=dynamic_context.accumulated_summary,
                relational_state_lock=dynamic_context.relational_state_lock,
                red_lines=beat.get("red_lines"),
                entity_spatial_ledger=dynamic_context.entity_spatial_ledger or None,
                chapter_assets_schema=context.get("chapter_assets_schema", ""),
                pov_perception_state=beat_context.beat.get("pov_perception_state"),
                pov_character_profile=pov_profile,
                is_first_beat=beat_context.is_first,
            )

            if pending_hint:
                usr_p = usr_p + pending_hint

            response = await _call_llm_with_stats(
                stage="prose_draft_serial",
                system_prompt=sys_p,
                user_prompt=usr_p,
                api_key=self._config.get("api_key", ""),
                base_url=self._config.get("base_url", ""),
                model=self._config.get("creative_model", ""),
                temperature=temperature,
                max_tokens=clamp_tokens(beat_context.target_words),
                beat_index=beat_number,
            )

            chunk = clean_llm_output(response).strip()
            return chunk, sys_p, usr_p

        # 定义验证函数
        async def validate(text: str) -> Tuple[bool, str, List[str]]:
            return await self._quality_checker.micro_review(
                chunk_text=text,
                context={
                    "dynamic_context": dynamic_context,
                    "pov_character": beat_context.beat.get("pov_character", ""),
                    "entities": context.get("entities", []),
                },
                beat=beat,
            )

        # 执行带重试的生成
        retry_result = await self._retry_engine.execute_with_retry(
            generate_func=generate_once,
            validate_func=validate,
            enable_fail_fast=self._feature_flags.enable_fail_fast,
        )

        return GenerationResult(
            text=retry_result.text,
            prompts=retry_result.prompts_history,
            beat_index=beat_context.beat_index,
            generation_time=0.0,  # 已在外部计算
            success=retry_result.success,
            error_message=retry_result.fail_reason,
        )

    async def _update_context(
        self,
        dynamic_context: Any,
        beat: dict,
        beat_idx: int,
        beats: List[dict],
        result: GenerationResult,
        context: Dict[str, Any],
    ) -> None:
        """
        更新动态上下文。

        Args:
            dynamic_context: 动态上下文（会被修改）
            beat: 当前 Beat
            beat_idx: 当前索引
            beats: 所有 Beats
            result: 生成结果
            context: 生成上下文
        """
        # 更新 Rolling Prefix
        self._context_manager.update_rolling_prefix(
            context=dynamic_context,
            chunk=result.text,
            beat=beat,
            beat_idx=beat_idx,
            beats=beats,
        )

        # 更新物理状态
        self._context_manager.update_physical_state(
            context=dynamic_context,
            beat=beat,
            beat_idx=beat_idx,
        )

        # 更新情感/关系状态
        if self._feature_flags.enable_emotional_scratchpad:
            try:
                state_update = await self._state_updater.update_dynamic_state(
                    context={},
                    chunk=result.text,
                    current_emotional_state=dynamic_context.current_emotional_state,
                    pov_character=beat.get("pov_character", "主角"),
                    relational_state_lock=dynamic_context.relational_state_lock,
                    beat_context=beat,
                    book_genre=context.get("book", {}).get("genre", "通用小说"),
                )

                dynamic_context.current_emotional_state = state_update.new_emotional_state

                if state_update.relational_delta:
                    dynamic_context.relational_state_lock = (
                        self._state_updater.merge_relational_delta(
                            dynamic_context.relational_state_lock,
                            state_update.relational_delta,
                        )
                    )

                if state_update.beat_summary:
                    dynamic_context.update_summary(state_update.beat_summary)

            except Exception as e:
                logger.warning(f"[SerialStrategy] 状态更新失败: {e}")

    def _get_pov_profile(self, pov_character: str, entities: List[Any]) -> dict:
        """获取 POV 角色配置"""
        from backend.services.workflows.beat_utils import get_pov_profile
        return get_pov_profile(pov_character, entities)

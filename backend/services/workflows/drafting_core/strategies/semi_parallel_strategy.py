"""
半并行策略 (Cascade) - 平衡速度与连贯性。

特点：
- Beat 数量少时（<=2）降级为串行
- Beat 数量多时串行执行但保持完整 Rolling Prefix
- 与串行策略相同的连贯性保证
- 适合中等长度章节

使用方式：
    strategy = SemiParallelStrategy(config, llm_client)
    results = await strategy.execute(beats, scene_intents, subcons, context)
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy, GenerationResult
from backend.services.workflows.drafting_types import BeatContext
from backend.services.workflows.drafting_core.strategies.serial_strategy import SerialStrategy
from backend.services.workflows.drafting_core.context.context_manager import ContextManager
from backend.services.workflows.drafting_core.context.state_updater import StateUpdater
from backend.services.workflows.drafting_core.retry.retry_engine import RetryEngine
from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker
from backend.services.workflows.beat_utils import safe_get_from_list, clamp_tokens, get_pov_profile
from backend.services.prompts import build_prose_draft_prompt_v25
from backend.services.workflows.drafting_thinking import _call_llm_with_stats
from backend.services.workflows.utils import clean_llm_output

if TYPE_CHECKING:
    from backend.services.llm import LLMClient

logger = logging.getLogger(__name__)


class SemiParallelStrategy(GenerationStrategy):
    """
    半并行策略 (Cascade)。

    职责：
    - 实现平衡速度与连贯性的生成策略
    - Beat 数量少时降级为串行
    - Beat 数量多时串行执行

    设计决策：
    - 使用降级阈值决定是否降级
    - 与串行策略共享大部分逻辑
    - 适合中等长度的章节（3-10 Beats）
    """

    # 降级阈值：Beat 数量 <= 此值时降级为串行
    FALLBACK_THRESHOLD = 2

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
        执行半并行生成。

        流程：
        1. 检查是否需要降级
        2. 如果降级，使用串行策略
        3. 否则，执行标准的串行流程

        Args:
            beats: 故事节拍列表
            scene_intent_results: 场景意图结果
            subconscious_results: 潜意识思考结果
            context: 生成上下文

        Returns:
            List[GenerationResult]: 每个节拍的生成结果
        """
        n = len(beats)

        # 降级检查
        if n <= self.FALLBACK_THRESHOLD:
            logger.warning(
                f"[SemiParallelStrategy] Beats={n} <= {self.FALLBACK_THRESHOLD}，"
                f"降级为串行策略"
            )
            return await self._execute_as_serial(
                beats, scene_intent_results, subconscious_results, context
            )

        # 标准半并行执行
        return await self._execute_cascade(
            beats, scene_intent_results, subconscious_results, context
        )

    async def _execute_as_serial(
        self,
        beats: List[dict],
        scene_intent_results: List[dict],
        subconscious_results: List[str],
        context: Dict[str, Any],
    ) -> List[GenerationResult]:
        """
        降级为串行执行。

        复用 SerialStrategy 的逻辑。

        Args:
            beats: 故事节拍列表
            scene_intent_results: 场景意图结果
            subconscious_results: 潜意识思考结果
            context: 生成上下文

        Returns:
            List[GenerationResult]: 生成结果
        """
        # 创建串行策略实例
        serial_strategy = SerialStrategy(
            config=self._config,
            llm_client=self._llm_client,
            quality_checker=self._quality_checker,
            retry_engine=self._retry_engine,
        )

        return await serial_strategy.execute(
            beats=beats,
            scene_intent_results=scene_intent_results,
            subconscious_results=subconscious_results,
            context=context,
        )

    async def _execute_cascade(
        self,
        beats: List[dict],
        scene_intent_results: List[dict],
        subconscious_results: List[str],
        context: Dict[str, Any],
    ) -> List[GenerationResult]:
        """
        执行 Cascade 生成。

        Cascade 与 Serial 的区别：
        - 使用不同的上下文初始化方法
        - 状态更新时传递 book_genre

        Args:
            beats: 故事节拍列表
            scene_intent_results: 场景意图结果
            subconscious_results: 潜意识思考结果
            context: 生成上下文

        Returns:
            List[GenerationResult]: 生成结果
        """
        n = len(beats)
        word_count = context.get("word_count", 2000)

        logger.info(f"[SemiParallelStrategy] 执行 Cascade，Beats={n}")

        # 初始化上下文
        dynamic_context = self._context_manager.create_serial_context(
            beats=beats,
            entities=context.get("entities", []),
            relationships=context.get("relationships", []),
            physical_state_lock=context.get("physical_state_lock"),
            entity_spatial_ledger=context.get("entity_spatial_ledger"),
        )

        all_results = []
        total_start = time.perf_counter()
        book_genre = getattr(context.get("book"), "genre", "通用小说")

        for beat_idx, beat in enumerate(beats):
            beat_start = time.perf_counter()

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

            # 生成
            result = await self._generate_single_beat(
                beat_context=beat_context,
                dynamic_context=dynamic_context,
                context=context,
            )

            beat_time = time.perf_counter() - beat_start
            result.generation_time = beat_time
            all_results.append(result)

            logger.info(
                f"[SemiParallelStrategy] Beat {beat_idx + 1}/{n} 完成，"
                f"字数={len(result.text)}, 耗时={beat_time:.2f}s"
            )

            # 更新上下文
            await self._update_context(
                dynamic_context=dynamic_context,
                beat=beat,
                beat_idx=beat_idx,
                beats=beats,
                result=result,
                context=context,
                book_genre=book_genre,
            )

        total_time = time.perf_counter() - total_start
        logger.info(
            f"[SemiParallelStrategy] Cascade 完成，总耗时={total_time:.2f}s"
        )

        return all_results

    async def _generate_single_beat(
        self,
        beat_context: BeatContext,
        dynamic_context: Any,
        context: Dict[str, Any],
    ) -> GenerationResult:
        """
        生成单个 Beat。

        与 SerialStrategy 类似，但使用 Cascade 特定的参数。

        Args:
            beat_context: Beat 上下文
            dynamic_context: 动态上下文
            context: 生成上下文

        Returns:
            GenerationResult: 生成结果
        """
        beat = beat_context.beat
        beat_number = beat_context.beat_number
        pov_profile = get_pov_profile(
            beat_context.beat.get("pov_character", ""),
            context.get("entities", [])
        )

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
                stage="prose_draft_cascade",
                system_prompt=sys_p,
                user_prompt=usr_p,
                temperature=temperature,
                max_tokens=clamp_tokens(beat_context.target_words),
                beat_index=beat_number,
            )

            chunk = clean_llm_output(response).strip()
            return chunk, sys_p, usr_p

        async def validate(text: str) -> Tuple[bool, str, List[str]]:
            result = await self._quality_checker.micro_review(
                chunk_text=text,
                context={
                    "dynamic_context": dynamic_context,
                    "pov_character": beat_context.beat.get("pov_character", ""),
                    "entities": context.get("entities", []),
                },
                beat=beat,
            )
            return result.is_valid, result.reason, result.fail_categories

        retry_result = await self._retry_engine.execute_with_retry(
            generate_func=generate_once,
            validate_func=validate,
            enable_fail_fast=self._feature_flags.enable_fail_fast,
        )

        return GenerationResult(
            text=retry_result.text,
            prompts=retry_result.prompts_history,
            beat_index=beat_context.beat_index,
            generation_time=0.0,
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
        book_genre: str,
    ) -> None:
        """
        更新动态上下文。

        Cascade 与 Serial 的区别：
        - 调用 _state_updater.update_dynamic_state 时传递 beat_context

        Args:
            dynamic_context: 动态上下文（会被修改）
            beat: 当前 Beat
            beat_idx: 当前索引
            beats: 所有 Beats
            result: 生成结果
            context: 生成上下文
            book_genre: 书籍类型
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
                    beat_context=beat,  # Cascade 传递 beat_context
                    book_genre=book_genre,
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
                logger.warning(f"[SemiParallelStrategy] 状态更新失败: {e}")

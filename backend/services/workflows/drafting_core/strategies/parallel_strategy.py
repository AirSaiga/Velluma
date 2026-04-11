"""
并行策略 - 极速生成但可能损失连贯性。

特点：
- 所有 Beat 同时生成
- 不使用 previous_tail
- 所有 Beat 共享初始状态
- 速度最快但连贯性最差

使用方式：
    strategy = ParallelStrategy(config, llm_client)
    results = await strategy.execute(beats, scene_intents, subcons, context)
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from backend.services.workflows.drafting_core.strategies.base import GenerationStrategy, GenerationResult
from backend.services.workflows.drafting_types import BeatContext
from backend.services.workflows.drafting_core.context.context_manager import ContextManager
from backend.services.workflows.drafting_core.retry.retry_engine import RetryEngine
from backend.services.workflows.drafting_core.quality.quality_checker import QualityChecker
from backend.services.workflows.beat_utils import safe_get_from_list, clamp_tokens, get_pov_profile
from backend.services.prompts import build_prose_draft_prompt_v25
from backend.services.workflows.drafting_thinking import _call_llm_with_stats
from backend.services.workflows.utils import clean_llm_output

if TYPE_CHECKING:
    from backend.services.llm import LLMClient

logger = logging.getLogger(__name__)


class ParallelStrategy(GenerationStrategy):
    """
    并行策略。

    职责：
    - 实现完全并行的 Beat 生成
    - 管理共享的初始状态
    - 处理并行任务的结果收集

    设计决策：
    - 使用 asyncio.gather 并行执行所有 Beat
    - 所有 Beat 共享初始状态
    - 不更新 Rolling Prefix
    - 使用 return_exceptions 避免单个失败影响整体
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

    async def execute(
        self,
        beats: List[dict],
        scene_intent_results: List[dict],
        subconscious_results: List[str],
        context: Dict[str, Any],
    ) -> List[GenerationResult]:
        """
        执行并行生成。

        流程：
        1. 初始化共享的初始状态
        2. 并行创建所有 Beat 的生成任务
        3. 使用 asyncio.gather 执行所有任务
        4. 处理异常并规范化结果

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

        logger.info(f"[ParallelStrategy] 开始并行生成，Beats={n}")

        # 1. 初始化共享状态
        initial_context = self._context_manager.create_parallel_context(
            beats=beats,
            entities=context.get("entities", []),
            relationships=context.get("relationships", []),
            physical_state_lock=context.get("physical_state_lock"),
        )

        # 共享的初始状态
        initial_states = {
            "emotional_state": initial_context.current_emotional_state,
            "relational_state": initial_context.relational_state_lock,
            "physical_state_lock": initial_context.physical_state_lock,
        }

        # 2. 创建并行任务
        tasks = [
            self._generate_single_beat(
                beat_context=self._create_beat_context(
                    beat=beat,
                    beat_index=i,
                    total_beats=n,
                    scene_intent=safe_get_from_list(
                        scene_intent_results, i,
                        {"intent_label": "默认", "goal": beat.get("summary", "")}
                    ),
                    subconscious=safe_get_from_list(subconscious_results, i, ""),
                    target_words=self._calculate_target_words(beat, word_count, n),
                ),
                initial_states=initial_states,
                context=context,
            )
            for i, beat in enumerate(beats)
        ]

        # 3. 并行执行
        total_start = time.perf_counter()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.perf_counter() - total_start

        # 4. 规范化结果
        normalized_results = [
            self._finalize_result(r, i + 1)
            for i, r in enumerate(results)
        ]

        logger.info(
            f"[ParallelStrategy] 并行生成完成，总耗时={total_time:.2f}s"
        )

        return normalized_results

    async def _generate_single_beat(
        self,
        beat_context: BeatContext,
        initial_states: Dict[str, str],
        context: Dict[str, Any],
    ) -> GenerationResult:
        """
        生成单个 Beat（并行模式）。

        Args:
            beat_context: Beat 上下文
            initial_states: 共享的初始状态
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

        # 解包初始状态
        initial_emotional_state = initial_states.get("emotional_state", "初始状态：未知")
        initial_relational_state = initial_states.get("relational_state", "")
        physical_state_lock = initial_states.get("physical_state_lock", "")

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
                previous_tail="",  # 并行模式下不使用
                target_words=beat_context.target_words,
                physical_state_lock=physical_state_lock,
                current_emotional_state=initial_emotional_state,
                accumulated_summary="",  # 并行模式下不使用
                relational_state_lock=initial_relational_state,
                red_lines=beat.get("red_lines"),
                entity_spatial_ledger=None,  # 并行模式下不使用
                chapter_assets_schema=context.get("chapter_assets_schema", ""),
                pov_perception_state=beat_context.beat.get("pov_perception_state"),
                pov_character_profile=pov_profile,
                is_first_beat=beat_context.is_first,
            )

            if pending_hint:
                usr_p = usr_p + pending_hint

            response = await _call_llm_with_stats(
                stage="prose_draft_parallel",
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
            # 并行模式下使用临时上下文
            temp_context = {
                "dynamic_context": {
                    "previous_tail": "",
                    "current_emotional_state": initial_emotional_state,
                    "physical_state_lock": physical_state_lock,
                    "relational_state_lock": initial_relational_state,
                    "entity_spatial_ledger": {},
                },
                "pov_character": beat_context.beat.get("pov_character", ""),
                "entities": context.get("entities", []),
            }
            result = await self._quality_checker.micro_review(
                chunk_text=text,
                context=temp_context,
                beat=beat,
            )
            return result.is_valid, result.reason, result.fail_categories

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
            generation_time=0.0,
            success=retry_result.success,
            error_message=retry_result.fail_reason,
        )

    def _finalize_result(self, result: Any, beat_index: int) -> GenerationResult:
        """
        规范化并行任务结果。

        Args:
            result: 任务结果或异常
            beat_index: Beat 索引

        Returns:
            GenerationResult: 规范化后的结果
        """
        if isinstance(result, Exception):
            logger.error(f"[ParallelStrategy] Beat {beat_index}: {result}")
            return GenerationResult(
                text="",
                prompts=[],
                beat_index=beat_index - 1,
                generation_time=0.0,
                success=False,
                error_message=str(result),
            )
        return result

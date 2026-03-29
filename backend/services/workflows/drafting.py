# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
起草模块 - 统一导出入口。

职责：作为起草模块的 Facade 层，从子模块重新导出所有公开 API，确保外部调用方无需修改导入路径。

子模块分工：
- drafting_router.py: V3.0 智能路由（三档执行路径）+ BeatDraftResult 数据结构
- drafting_thinking.py: 思考层生成（Scene Intent + Subconscious + 轻量级 Subconscious）
- drafting_prose.py: 正文生成（三种并发策略 + 状态管理 + QC）
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Callable

logger = logging.getLogger(__name__)

from backend.services.workflows.drafting_router import (
    BeatDraftResult,
    execute_draft_stage,
    _execute_fast_path,
    _execute_standard_path,
    _execute_fortress_path,
    build_fast_path_prompt,
    build_standard_path_prompt,
)
from backend.services.workflows.drafting_thinking import (
    _call_llm_with_stats,
    _generate_scene_intent_batch,
    _generate_subconscious_batch,
    _generate_lightweight_subconscious,
    _build_beat_hooks,
)
from backend.services.workflows.drafting_prose import (
    _generate_prose_serial_v25,
    _generate_prose_parallel_v25,
    _generate_prose_semi_parallel_v25,
    _micro_review_assertion,
    _infer_fail_categories,
    _quick_qc,
    _update_dynamic_state,
    _update_emotional_state,
    _extract_tail,
    _clamp_tokens,
    _extract_fallback_summary,
    _build_initial_relational_state,
    _merge_relational_delta,
    _extract_character_prompts_for_beat,
)

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]

from backend.services.llm_client import call_llm
from backend.services.prompts import (
    build_scene_intent_prompt,
    parse_scene_intent_result,
    build_chunk_draft_prompt,
)
from backend.services.workflows.utils import clean_llm_output


async def generate_chunks_parallel(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    story_beats: List[Any],
    open_hooks: List[dict],
    previous_summary: Optional[str],
    relevant_memories: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    word_count: int,
) -> List[str]:
    """
    【兼容性保留】并行生成多个故事节拍的正文片段。

    警告：此函数为旧版实现，使用完全并行的方式生成，可能导致 Beat 间语气不连贯。
    新项目请使用 execute_draft_stage。
    """
    async def process_single_beat(beat_index: int, beat: dict, story_beat: Any) -> tuple[int, str]:
        try:
            beat_hooks = _build_beat_hooks(beat, open_hooks, beat_index)

            scene_system_prompt, scene_user_prompt = build_scene_intent_prompt(
                chapter=chapter, beat=beat, open_hooks=beat_hooks,
            )
            scene_intent_raw = await call_llm(
                system_prompt=scene_system_prompt, user_prompt=scene_user_prompt,
                api_key=api_key, base_url=base_url, model=model,
                temperature=0.2, response_format={"type": "json_object"},
            )
            scene_intent_data = parse_scene_intent_result(scene_intent_raw, beat.get("summary", ""))

            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))

            context_summaries = _build_context_summaries(beat_index, beats, len(beats))

            chunk_system_prompt, chunk_user_prompt = build_chunk_draft_prompt(
                chapter=chapter, book=book, entities=entities,
                relationships=relationships, beat=beat,
                scene_intent=scene_intent_data, target_words=target_words,
                previous_chunks=[], previous_summary=previous_summary,
                relevant_memories=relevant_memories, hook_contexts=beat_hooks,
                context_beat_summaries=context_summaries,
            )

            chunk_text = await call_llm(
                system_prompt=chunk_system_prompt, user_prompt=chunk_user_prompt,
                api_key=api_key, base_url=base_url, model=model, temperature=0.7,
            )
            return beat_index - 1, clean_llm_output(chunk_text)
        except Exception as e:
            logger.error(f"[Beat] Beat {beat_index} failed: {e}")
            return beat_index - 1, ""

    def _build_context_summaries(beat_index: int, beats: List[dict], total_beats: int) -> dict:
        summaries = {}
        if beat_index > 1:
            summaries["prev"] = beats[beat_index - 2].get("summary", "")
        if beat_index < total_beats:
            summaries["next"] = beats[beat_index].get("summary", "")
        return summaries

    sem = asyncio.Semaphore(5)

    async def sem_task(task):
        async with sem:
            return await task

    tasks = [
        sem_task(process_single_beat(i, b, sb))
        for i, b, sb in zip(range(1, len(beats) + 1), beats, story_beats)
    ]

    results = await asyncio.gather(*tasks)

    generated_chunks = [""] * len(beats)
    for idx, text in results:
        generated_chunks[idx] = text

    return generated_chunks

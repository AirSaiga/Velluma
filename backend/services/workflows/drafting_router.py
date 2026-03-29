"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
起草路由模块 - V3.0 智能路由三档执行路径。

职责：根据 workflow_tier 动态选择执行路径（疾速/均衡/堡垒）。

主要功能：
- execute_draft_stage: 主入口，根据 tier 路由到三档路径
- _execute_fast_path: Tier 1 疾速流
- _execute_standard_path: Tier 2 均衡流
- _execute_fortress_path: Tier 3 堡垒流
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

from backend.schemas import (
    DynamicContext,
    DraftingFeatureFlags,
    WorkflowTier,
)
from backend.services.orchestration.tier_mapper import map_tension_to_workflow_tier
from backend.services.workflows.utils import clean_llm_output
from backend.services.workflows.drafting_thinking import (
    _call_llm_with_stats,
    _generate_scene_intent_batch,
    _generate_subconscious_batch,
    _generate_lightweight_subconscious,
    _build_beat_hooks,
)
from backend.services.workflows.drafting_prose import (
    _extract_tail,
    _clamp_tokens,
    _quick_qc,
    _generate_prose_serial_v25,
    _micro_review_assertion,
    _infer_fail_categories,
    _update_dynamic_state,
    _update_emotional_state,
    _extract_fallback_summary,
    _build_initial_relational_state,
    _merge_relational_delta,
    _extract_character_prompts_for_beat,
)

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


class BeatDraftResult(BaseModel):
    """
    Beat 生成结果数据结构。

    Attributes:
        beat_id: Beat 唯一标识
        beat_index: Beat 在章节中的位置索引（从1开始）
        scene_intent: Scene Intent 分析结果
        subconscious_thought: 角色潜意识/内心独白
        draft_chunk: 生成的小说正文
        prompts: 调试用的提示词历史列表
        mcts_rollout: MCTS 三分支推演记录
    """
    beat_id: str
    beat_index: int
    scene_intent: dict
    subconscious_thought: str
    draft_chunk: str
    prompts: List[dict] = []
    mcts_rollout: Optional[list] = None


async def execute_draft_stage(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    workflow_tier: Optional[WorkflowTier] = None,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
) -> List[BeatDraftResult]:
    """
    V3.0 智能路由起草阶段主入口。

    V3.0 路由策略：
    - TIER_1_FAST (Level 1-2): 疾速流，跳过复杂思考层，直接生成
    - TIER_2_STANDARD (Level 3): 均衡流，轻量级思考 + 串行生成
    - TIER_3_FORTRESS (Level 4-5): 堡垒流，算力全开，保持 V2.5 完整流程
    """
    if not beats:
        return []

    flags = feature_flags or DraftingFeatureFlags()

    effective_tier = workflow_tier

    if not effective_tier and chapter:
        tension_level = getattr(chapter, 'tension_level', None)
        if tension_level and isinstance(tension_level, int) and 1 <= tension_level <= 5:
            effective_tier = map_tension_to_workflow_tier(tension_level)
            logger.info(f"[Draft Stage] 从 chapter.tension_level={tension_level} 映射到 {effective_tier}")

    if not effective_tier and beats:
        effective_tier = beats[0].get("workflow_tier")

    if not effective_tier:
        effective_tier = flags.workflow_tier

    logger.info(f"[Draft Stage] V3.0 智能路由启动，工作流层级: {effective_tier}，共 {len(beats)} 个 Beats")

    if effective_tier == "TIER_1_FAST":
        return await _execute_fast_path(
            chapter=chapter, book=book, entities=entities, relationships=relationships,
            beats=beats, open_hooks=open_hooks, api_key=api_key, base_url=base_url,
            reasoning_model=reasoning_model, creative_model=creative_model,
            word_count=word_count, previous_summary=previous_summary,
            stats_callback=stats_callback,
        )
    elif effective_tier == "TIER_2_STANDARD":
        return await _execute_standard_path(
            chapter=chapter, book=book, entities=entities, relationships=relationships,
            beats=beats, open_hooks=open_hooks, api_key=api_key, base_url=base_url,
            reasoning_model=reasoning_model, creative_model=creative_model,
            word_count=word_count, previous_summary=previous_summary,
            relevant_memories=relevant_memories, locations=locations,
            enable_qc=enable_qc, feature_flags=flags,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            stats_callback=stats_callback, reasoning_config=reasoning_config,
        )
    else:
        return await _execute_fortress_path(
            chapter=chapter, book=book, entities=entities, relationships=relationships,
            beats=beats, open_hooks=open_hooks, api_key=api_key, base_url=base_url,
            reasoning_model=reasoning_model, creative_model=creative_model,
            word_count=word_count, previous_summary=previous_summary,
            relevant_memories=relevant_memories, locations=locations,
            enable_qc=enable_qc, feature_flags=flags,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            stats_callback=stats_callback, reasoning_config=reasoning_config,
        )


async def _execute_fast_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    stats_callback: LLMStatsCallback = None,
) -> List[BeatDraftResult]:
    """
    V3.0 Tier 1: 疾速流 (Fast-Path) - 完全并发版本。

    特点: 跳过 Scene Intent/Subconscious，完全并发生成，单次调用 creative_model。
    适用场景: 低张力日常剧情 (tension_level 1-2)。
    """
    logger.info("[Fast Path] 启动疾速流生成（完全并发）...")

    async def _single_fast_beat(beat_index: int, beat: dict) -> BeatDraftResult:
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        target_words = beat.get("word_count_target") or beat.get("target_words", max(200, word_count // max(1, len(beats))))

        try:
            system_prompt, user_prompt = build_fast_path_prompt(
                chapter=chapter, book=book, beat=beat,
                previous_tail="", target_words=target_words,
                previous_summary=previous_summary,
            )

            response = await _call_llm_with_stats(
                stage="fast_path_prose",
                system_prompt=system_prompt, user_prompt=user_prompt,
                api_key=api_key, base_url=base_url, model=creative_model,
                temperature=0.75, max_tokens=_clamp_tokens(target_words),
                beat_index=beat_index, stats_callback=stats_callback,
            )

            chunk_text = clean_llm_output(response).strip()

            return BeatDraftResult(
                beat_id=beat_id, beat_index=beat_index,
                scene_intent={"intent_label": "疾速流", "goal": beat.get("summary", "")},
                subconscious_thought="", draft_chunk=chunk_text,
                prompts=[{"stage": "FAST_PATH", "system_prompt": system_prompt, "user_prompt": user_prompt}],
                mcts_rollout=None,
            )
        except Exception as e:
            logger.error(f"[Fast Path] Beat {beat_index} 生成失败: {e}")
            return BeatDraftResult(
                beat_id=beat_id, beat_index=beat_index,
                scene_intent={"intent_label": "疾速流", "goal": beat.get("summary", "")},
                subconscious_thought="", draft_chunk="", prompts=[], mcts_rollout=None,
            )

    tasks = [_single_fast_beat(beat_index=i + 1, beat=beat) for i, beat in enumerate(beats)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results: List[BeatDraftResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"[Fast Path] Beat {i+1} 发生异常: {result}")
            beat = beats[i]
            beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
            processed_results.append(BeatDraftResult(
                beat_id=beat_id, beat_index=i + 1,
                scene_intent={"intent_label": "疾速流", "goal": beat.get("summary", "")},
                subconscious_thought="", draft_chunk="", prompts=[], mcts_rollout=None,
            ))
        else:
            processed_results.append(result)

    logger.info(f"[Fast Path] 疾速流生成完成，共 {len(processed_results)} 个 Beats")
    return processed_results


async def _execute_standard_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
) -> List[BeatDraftResult]:
    """
    V3.0 Tier 2: 均衡流 (Standard-Path)。

    特点: 轻量级 Subconscious（无 MCTS），CoreDynamicContext，串行调用 creative_model。
    适用场景: 中等张力剧情 (tension_level 3)。
    """
    logger.info("[Standard Path] 启动均衡流生成...")
    flags = feature_flags or DraftingFeatureFlags()

    scene_intent_results, scene_intent_prompts_list = await _generate_scene_intent_batch(
        beats=beats, chapter=chapter, open_hooks=open_hooks,
        api_key=api_key, base_url=base_url, model=reasoning_model,
        stats_callback=stats_callback, reasoning_config=reasoning_config,
    )

    subconscious_results = await _generate_lightweight_subconscious(
        beats=beats, scene_intent_results=scene_intent_results,
        chapter=chapter, api_key=api_key, base_url=base_url,
        model=reasoning_model, stats_callback=stats_callback,
    )

    results: List[BeatDraftResult] = []
    previous_tail = ""
    current_physical_lock = physical_state_lock or ""

    for i, beat in enumerate(beats):
        beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
        target_words = beat.get("word_count_target") or beat.get("target_words", max(200, word_count // max(1, len(beats))))

        system_prompt, user_prompt = build_standard_path_prompt(
            chapter=chapter, book=book, beat=beat,
            scene_intent=scene_intent_results[i],
            subconscious=subconscious_results[i],
            previous_tail=previous_tail,
            physical_state_lock=current_physical_lock,
            target_words=target_words,
        )

        response = await _call_llm_with_stats(
            stage="standard_path_prose",
            system_prompt=system_prompt, user_prompt=user_prompt,
            api_key=api_key, base_url=base_url, model=creative_model,
            temperature=0.75, max_tokens=_clamp_tokens(target_words),
            beat_index=i + 1, stats_callback=stats_callback,
        )

        chunk_text = clean_llm_output(response).strip()

        if enable_qc:
            chunk_text, _ = await _quick_qc(
                prose_text=chunk_text, beat=beat, beat_index=i + 1,
                chapter=chapter, book=book, entities=entities,
                relationships=relationships, api_key=api_key,
                base_url=base_url, model=creative_model,
                target_words=target_words,
            )

        previous_tail = _extract_tail(chunk_text, max_chars=300)

        prompts_history = [{
            "stage": "STANDARD_PATH", "beat_index": i + 1,
            "system_prompt": system_prompt, "user_prompt": user_prompt,
        }]

        results.append(BeatDraftResult(
            beat_id=beat_id, beat_index=i + 1,
            scene_intent=scene_intent_results[i],
            subconscious_thought=subconscious_results[i],
            draft_chunk=chunk_text, prompts=prompts_history, mcts_rollout=None,
        ))

    logger.info(f"[Standard Path] 均衡流生成完成，共 {len(results)} 个 Beats")
    return results


async def _execute_fortress_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
) -> List[BeatDraftResult]:
    """
    V3.0 Tier 3: 堡垒流 (Fortress-Path)。

    特点: MCTS 三分支 Subconscious 搜索，全部 5 维 DynamicContext，Fail-Fast 断言检查。
    适用场景: 高张力关键剧情 (tension_level 4-5)。
    """
    logger.info("[Fortress Path] 启动堡垒流生成（V2.5 完整管线）...")
    flags = feature_flags or DraftingFeatureFlags()
    stage_start = time.perf_counter()

    logger.info("[Draft Stage] 步骤 A: 并行生成 Scene Intent + Subconscious...")
    step_a_start = time.perf_counter()

    scene_intent_results, scene_intent_prompts_list = await _generate_scene_intent_batch(
        beats=beats, chapter=chapter, open_hooks=open_hooks,
        api_key=api_key, base_url=base_url, model=reasoning_model,
        stats_callback=stats_callback, reasoning_config=reasoning_config,
    )

    subconscious_results, mcts_rollout_results, subconscious_prompts_list = await _generate_subconscious_batch(
        beats=beats, scene_intent_results=scene_intent_results,
        chapter=chapter, entities=entities,
        api_key=api_key, base_url=base_url, model=reasoning_model,
        stats_callback=stats_callback, reasoning_config=reasoning_config,
    )

    logger.info(f"[Draft Stage] 步骤 A 完成，耗时 {time.perf_counter() - step_a_start:.2f}s")

    logger.info("[Draft Stage] 步骤 B-V25: 串行生成正文（Rolling Prefix + 认知组件）...")
    step_b_start = time.perf_counter()

    prose_results = await _generate_prose_serial_v25(
        beats=beats, scene_intent_results=scene_intent_results,
        subconscious_results=subconscious_results,
        chapter=chapter, book=book, entities=entities,
        relationships=relationships, api_key=api_key, base_url=base_url,
        creative_model=creative_model, reasoning_model=reasoning_model,
        word_count=word_count, previous_summary=previous_summary,
        relevant_memories=relevant_memories, locations=locations,
        enable_qc=enable_qc, feature_flags=flags,
        physical_state_lock=physical_state_lock,
        entity_spatial_ledger=entity_spatial_ledger,
        chapter_assets_schema=chapter_assets_schema,
        stats_callback=stats_callback,
    )

    logger.info(f"[Draft Stage] 步骤 B-V25 完成，耗时 {time.perf_counter() - step_b_start:.2f}s")

    results: List[BeatDraftResult] = []
    for i, beat in enumerate(beats):
        beat_id = str(beat.get("beat_id", f"beat-{i+1}"))

        all_prompts = []
        all_prompts.extend(scene_intent_prompts_list[i])
        all_prompts.extend(subconscious_prompts_list[i])
        all_prompts.extend(prose_results[i]["prompts"])

        result = BeatDraftResult(
            beat_id=beat_id, beat_index=i + 1,
            scene_intent=scene_intent_results[i],
            subconscious_thought=subconscious_results[i],
            draft_chunk=prose_results[i]["text"],
            prompts=all_prompts, mcts_rollout=mcts_rollout_results[i],
        )
        results.append(result)

    logger.info(f"[Fortress Path] 堡垒流完成，总耗时 {time.perf_counter() - stage_start:.2f}s")
    return results


def build_fast_path_prompt(
    chapter: Any,
    book: Any,
    beat: dict,
    previous_tail: str,
    target_words: int,
    previous_summary: Optional[str] = None,
) -> tuple[str, str]:
    """V3.0 Fast-Path: 构建疾速流的简化 Prompt"""
    pov_character = beat.get("pov_character", "主角")
    location = beat.get("location", "未指定")
    summary = beat.get("summary", "")
    red_lines = beat.get("red_lines", [])

    continuity = ""
    if previous_tail:
        continuity = f"\n【前文衔接】必须无缝衔接：{previous_tail}\n"

    previous_context = ""
    if previous_summary:
        previous_context = f"\n【前情回顾】{previous_summary}\n"

    red_lines_text = ""
    if red_lines:
        red_lines_text = f"\n【红线约束】{', '.join(red_lines)}"

    system_prompt = f"""你是专业小说写手。请根据以下信息直接生成小说正文。

【章节背景】{getattr(chapter, 'chapter_name', f'第{getattr(chapter, "chapter_number", 1)}章')}
【角色视角】{pov_character}
【场景地点】{location}{previous_context}{continuity}{red_lines_text}

要求：
1. 直接输出小说正文，不要解释、不要总结
2. 紧扣剧情目标，不偏离红线约束
3. 字数约 {target_words} 字，允许适度超出
4. 保持叙事连贯性，与前文无缝衔接
5. 使用自然流畅的文学语言，避免AI腔
"""

    user_prompt = f"【剧情目标】{summary}\n\n请生成以上内容的小说正文："

    return system_prompt, user_prompt


def build_standard_path_prompt(
    chapter: Any,
    book: Any,
    beat: dict,
    scene_intent: dict,
    subconscious: str,
    previous_tail: str,
    physical_state_lock: str,
    target_words: int,
) -> tuple[str, str]:
    """V3.0 Standard-Path: 构建均衡流的 Prompt"""
    pov_character = beat.get("pov_character", "主角")
    location = beat.get("location", "未指定")
    summary = beat.get("summary", "")

    continuity = ""
    if previous_tail:
        continuity = f"\n【前文衔接】必须无缝衔接：{previous_tail}\n"

    physical_context = ""
    if physical_state_lock:
        physical_context = f"\n【物理状态锁】{physical_state_lock}\n"

    system_prompt = f"""你是专业小说写手。请根据以下信息生成小说正文。

【章节背景】{getattr(chapter, 'chapter_name', f'第{getattr(chapter, "chapter_number", 1)}章')}
【角色视角】{pov_character}
【场景地点】{location}{continuity}{physical_context}

【场景意图】{scene_intent.get('goal', summary)}
【内心独白】{subconscious}

要求：
1. 将内心独白转化为具象化的动作、对话和环境描写
2. 直接输出小说正文，不要解释
3. 字数约 {target_words} 字
4. 保持叙事连贯性
"""

    user_prompt = f"【剧情目标】{summary}\n\n请生成以上内容的小说正文："

    return system_prompt, user_prompt

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
规划阶段工作流 - 章节结构规划和大纲生成。

职责：
- 调用 Planner Agent 生成章节大纲
- 将大纲拆分为 StoryBeat 列表
- 分配 POV 视角和叙事光圈
- 计算字数分配策略

业务场景：
- 章节生成的第一阶段
- 基于前文摘要和伏笔约束生成章节规划
- 为 Drafting 阶段提供输入

主要功能：
- POV 视角分配
- 叙事光圈（POV Aperture）智能推断
- Beat 结构化输出

依赖项：
- backend.services.prompts: Planner Prompt 模板
- backend.services.llm: LLM 调用接口
- backend.models: 数据模型

使用方式：
    beats = await execute_planning_stage(chapter, book, ...)
"""

from typing import Any, Optional
import logging

from backend.services.prompts import (
    build_planner_agent_prompt,
    parse_planner_result,
    build_pov_assignment_prompt,
    parse_pov_assignment_result,
    build_anchor_pov_prompt,
    parse_anchor_pov_result,
)
import json
from backend.services.llm import call_llm
from backend.models import Chapter, Book, Character, CharacterRelationship, StoryBeat
from backend.schemas import PovAperture
from backend.services.utils.logging import get_runtime_logger
from backend.services.workflows.state_validator import validate_beats_world_state_consistency
from backend.world_state_schemas import WorldTerminalState

logger = get_runtime_logger(__name__)


def infer_pov_aperture(beat: dict, tension_level: int) -> str:
    """
    基于 Scene Intent 和 Tension Level 推断 POV Aperture。
    
    V4.0: 智能光圈推断算法
    - 优先使用 Planner 已提供的 pov_aperture
    - 基于 tension_level 和 pacing_type 进行推断
    
    规则：
    - INTERNAL_ONLY: 深度心理描写、独处的内省场景 (Slow pacing, 低张力独白)
    - SYSTEMIC_SENSE: 高张力动作场景、需要全局感知的战斗场面 (Fast pacing + 高张力)
    - SUBJECTIVE_OBSERVATION: 默认，常规场景
    
    Args:
        beat: Beat 数据字典，包含 pacing_type 和可能的 pov_aperture
        tension_level: 章节张力等级 (1-5)
    
    Returns:
        str: 推断的 pov_aperture 值
    """
    # 如果 Planner 已提供有效值，直接使用
    existing = beat.get("pov_aperture")
    if existing in ["internal_only", "subjective_observation", "systemic_sense"]:
        return existing
    
    pacing_type = beat.get("pacing_type", "Medium")
    
    # 高张力 + 快节奏 = 全景感知
    if tension_level >= 4 and pacing_type == "Fast":
        return "systemic_sense"
    
    # 低张力 + 慢节奏 = 内心独白
    if tension_level <= 2 and pacing_type == "Slow":
        return "internal_only"
    
    # 默认：主观观察
    return "subjective_observation"


async def generate_beats(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    word_count: int,
    open_hooks: list[Any],
    api_key: str,
    base_url: str,
    model: str,
    previous_chapter_summary: Optional[str] = None,
    previous_world_state: Optional[WorldTerminalState] = None,
) -> tuple[list[dict], list[StoryBeat]]:
    """生成章节故事节拍 (Story Beats)。

    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        word_count: 目标字数
        open_hooks: 开放伏笔列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        previous_chapter_summary: 上一章摘要
        previous_world_state: 上一章世界终端状态

    Returns:
        tuple[list[dict], list[StoryBeat]]: (beats 字典列表, StoryBeat 实体列表)
    """
    logger.info(f"[Planning] 开始生成章节节拍, 目标字数: {word_count}")
    planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=word_count,
        open_hooks=open_hooks,
        previous_chapter_summary=previous_chapter_summary,
    )
    
    planner_result_raw = await call_llm(
        system_prompt=planner_system_prompt,
        user_prompt=planner_user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    
    beats = parse_planner_result(planner_result_raw, chapter.outline_text or "", word_count)

    # 引入状态校验 (V4.0)
    if previous_world_state:
        validation_result = validate_beats_world_state_consistency(
            beats=beats, 
            world_state=previous_world_state,
            strict_mode=False
        )
        
        if not validation_result.passed:
            for violation in validation_result.violations:
                logger.error(f"Beat生成违反物理约束: {violation.message}")
            
            # 如果存在 Error 级别的冲突，可以考虑抛出异常或记录严重警告
            logger.warning("生成的节拍与世界状态存在严重冲突，请注意人工核查。")
            
        for warning in validation_result.warnings:
            logger.warning(f"Beat生成逻辑警告: {warning.message}")
    
    story_beats = []
    tension_level = getattr(chapter, "tension_level", 3) or 3
    
    for beat_index, beat in enumerate(beats, start=1):
        # V4.0: 推断或使用 pov_aperture
        pov_aperture = infer_pov_aperture(beat, tension_level)
        
        # V4.0: 获取持久状态锚点
        persistent_state_anchors = beat.get("persistent_state_anchors", [])
        
        story_beat = StoryBeat(
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            beat_id=beat.get("beat_id"),
            beat_type="progression",
            position=beat.get("position", beat_index),
            location=beat.get("location"),
            pov_character=beat.get("pov_character"),
            pov_aperture=pov_aperture,  # V4.0: 叙事光圈
            persistent_state_anchors=persistent_state_anchors,  # V4.0: 持久状态锚点
            pov_perception_state=beat.get("pov_perception_state", "正常"),
            anchor_pov=None,
            original_actor=beat.get("pov_character"),
            action_summary=beat.get("action_summary"),
            worldbuilding_instruction=beat.get("worldbuilding_instruction"),
            entry_state=beat.get("entry_state"),
            exit_state=beat.get("exit_state"),
            red_lines=beat.get("red_lines", []),
            word_count_target=beat.get("word_count_target", beat.get("target_words", 0)),
            summary=beat.get("summary", ""),
            meta={
                "target_words": beat.get("target_words", 0),
                "pov_aperture": pov_aperture,  # V4.0: 也存入 meta 方便调试
                "persistent_state_anchors_count": len(persistent_state_anchors),
            },
            status="planned",
        )
        story_beats.append(story_beat)
    
    logger.info(f"[Planning] 节拍生成完成: 共 {len(story_beats)} 个节拍")
    return beats, story_beats


async def assign_pov_to_beats(
    beats: list[dict],
    characters: list[dict],
    story_premise: str,
    api_key: str,
    base_url: str,
    model: str,
    previous_chapter_summary: Optional[str] = None,
    prompt_logger = None,
    chapter_narrative_anchor: str = "",
) -> tuple[list[dict], dict[str, str]]:
    """为节拍分配 POV 角色。

    Args:
        beats: 节拍列表 (list[dict])
        characters: 角色列表 (list[dict], 每个包含 name, role, description)
        story_premise: 故事概要
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        previous_chapter_summary: 上一章摘要 (可选)

    Returns:
        tuple[list[dict], dict[str, str]]: (更新后的节拍列表, prompt_debug_info 包含 anchor_pov)
    """
    anchor_pov = await determine_chapter_anchor_pov(
        beats=beats,
        characters=characters,
        story_premise=story_premise,
        previous_chapter_summary=previous_chapter_summary,
        api_key=api_key,
        base_url=base_url,
        model=model,
        prompt_logger=prompt_logger,
        chapter_narrative_anchor_hint=chapter_narrative_anchor,
    )

    for beat in beats:
        original_pov = None
        # V4.0: ensemble/omniscient beats 保留 Planner 分配的多视角，不参与 anchor 覆盖
        if isinstance(beat, dict):
            beat_pov_mode = beat.get("pov_mode", "single") or "single"
            if beat_pov_mode in ("ensemble", "omniscient"):
                beat["anchor_pov"] = anchor_pov  # 仅记录 anchor但不覆盖
                continue
            original_pov = beat.get("pov_character")
            beat["original_actor"] = original_pov
            beat["pov_character"] = anchor_pov
            beat["anchor_pov"] = anchor_pov
        elif hasattr(beat, "pov_character"):
            beat_pov_mode = getattr(beat, "pov_mode", "single") or "single"
            if beat_pov_mode in ("ensemble", "omniscient"):
                beat.anchor_pov = anchor_pov
                continue
            original_pov = getattr(beat, "pov_character", None)
            beat.original_actor = original_pov
            beat.pov_character = anchor_pov
            beat.anchor_pov = anchor_pov
    # 转换 beats 为 dict 列表供 prompt 使用
    beats_for_prompt = []
    for beat in beats:
        if isinstance(beat, dict):
            beats_for_prompt.append(beat)
        elif hasattr(beat, "beat_id") and hasattr(beat, "summary"): # StoryBeat object
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None) or getattr(beat, "id", None),
                "position": getattr(beat, "position", None),
                "summary": getattr(beat, "summary", ""),
            }
            beats_for_prompt.append(beat_dict)
        else:
             # Fallback
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None),
                "position": getattr(beat, "position", None),
                "summary": getattr(beat, "summary", ""),
            }
            beats_for_prompt.append(beat_dict)
            
    # ============================================================
    # [注释] 原有 LLM POV 分配逻辑已禁用，改用 Anchor POV 机制
    # 保留代码以便后续可能的对比测试
    # ============================================================
    # system_prompt, user_prompt = build_pov_assignment_prompt(
    #     story_premise=story_premise,
    #     characters=characters,
    #     beats=beats_for_prompt,
    # )
    #
    # llm_result_raw = await call_llm(
    #     system_prompt=system_prompt,
    #     user_prompt=user_prompt,
    #     api_key=api_key,
    #     base_url=base_url,
    #     model=model,
    #     response_format={"type": "json_object"},
    # )
    #
    # try:
    #     llm_result = json.loads(llm_result_raw)
    #     assignments = parse_pov_assignment_result(llm_result)
    #
    #     # 应用结果到原始 beats 对象
    #     for beat in beats:
    #         # 确定 beat 的标识符
    #         beat_id = None
    #         if isinstance(beat, dict):
    #             beat_id = str(beat.get("beat_id", beat.get("position")))
    #         else:
    #             beat_id = str(getattr(beat, "beat_id", getattr(beat, "position", None)))
    #
    #         if beat_id and beat_id in assignments:
    #             pov_char = assignments[beat_id]
    #             if isinstance(beat, dict):
    #                 beat["pov_character"] = pov_char
    #             else:
    #                 setattr(beat, "pov_character", pov_char)
    #
    # except json.JSONDecodeError:
    #     pass

    # 获取 anchor_pov 的推断提示词信息用于调试显示
    anchor_pov_system_prompt, anchor_pov_user_prompt = build_anchor_pov_prompt(
        story_premise=story_premise,
        characters=characters,
        beats=beats_for_prompt,
        previous_chapter_summary=previous_chapter_summary,
    )

    debug_info = {
        "anchor_pov": anchor_pov,
        "system_prompt": anchor_pov_system_prompt,
        "user_prompt": anchor_pov_user_prompt,
    }
        
    return beats, debug_info


async def determine_chapter_anchor_pov(
    beats: list[dict],
    characters: list[dict],
    story_premise: str,
    previous_chapter_summary: Optional[str] = None,
    api_key: str = None,
    base_url: str = None,
    model: str = None,
    prompt_logger = None,
    chapter_narrative_anchor_hint: str = "",
) -> str:
    """确定章节的核心主角 (Anchor POV)。

    Args:
        beats: 节拍列表 (list[dict]), 每个包含 summary 和 action_summary
        characters: 角色列表 (list[dict], 每个包含 name, role, description)
        story_premise: 故事概要
        previous_chapter_summary: 上一章摘要 (可选)
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        chapter_narrative_anchor_hint: Planner 已声明的叙事核心角色（可选）。
            若非空且合法（存在于角色列表中），将直接作为快速路径返回，跳过 LLM 调用。
            同时作为高优先级提示注入 Anchor POV prompt，防止 LLM 因 Beat 出现频次
            误判叙事核心（尤其适用于主角昏迷/幕后等场景）。

    Returns:
        str: 核心主角的名字，如果无法确定返回空字符串
    """
    # ── 快速路径：Planner 已声明且合法，直接使用，跳过 LLM ──────────────
    if chapter_narrative_anchor_hint:
        valid_names = {c.get("name", "") for c in characters}
        if chapter_narrative_anchor_hint in valid_names:
            logger.info(
                f"[AnchorPOV] 使用 Planner 声明的叙事核心: {chapter_narrative_anchor_hint}（跳过 LLM）"
            )
            if prompt_logger:
                prompt_logger.start_stage("POV_ASSIGNMENT", iteration=1)
                prompt_logger.log_inputs(
                    pov_candidates_count=len(characters),
                    has_previous_summary=bool(previous_chapter_summary),
                    fast_path=True,
                    planner_hint=chapter_narrative_anchor_hint,
                )
                prompt_logger.log_prompts(
                    system_prompt="[快速路径] Planner 已声明叙事核心，跳过 LLM 调用",
                    user_prompt=f"chapter_narrative_anchor_hint = {chapter_narrative_anchor_hint}",
                    model="(skipped)",
                    prompt_label="ANCHOR_POV_FAST_PATH",
                )
                prompt_logger.log_outputs(anchor_pov=chapter_narrative_anchor_hint)
                prompt_logger.end_stage(success=True)
            return chapter_narrative_anchor_hint
    beats_for_prompt = []
    for beat in beats:
        if isinstance(beat, dict):
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None) or beat.get("position"),
                "position": beat.get("position"),
                "summary": beat.get("summary", ""),
                "action_summary": beat.get("action_summary", ""),
            }
            beats_for_prompt.append(beat_dict)
        elif hasattr(beat, "summary"):
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None) or getattr(beat, "id", None),
                "position": getattr(beat, "position", None),
                "summary": getattr(beat, "summary", ""),
                "action_summary": getattr(beat, "action_summary", ""),
            }
            beats_for_prompt.append(beat_dict)
        else:
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None),
                "position": getattr(beat, "position", None),
                "summary": str(beat),
                "action_summary": "",
            }
            beats_for_prompt.append(beat_dict)

    system_prompt, user_prompt = build_anchor_pov_prompt(
        story_premise=story_premise,
        characters=characters,
        beats=beats_for_prompt,
        previous_chapter_summary=previous_chapter_summary,
        chapter_narrative_anchor_hint=chapter_narrative_anchor_hint,
    )

    # 记录 Prompt 到 logger（如果提供）
    if prompt_logger:
        prompt_logger.start_stage("POV_ASSIGNMENT", iteration=1)
        prompt_logger.log_inputs(
            pov_candidates_count=len(characters),
            has_previous_summary=bool(previous_chapter_summary),
        )
        prompt_logger.log_prompts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            prompt_label="ANCHOR_POV",
        )

    llm_result_raw = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        response_format={"type": "json_object"},
    )

    try:
        llm_result = json.loads(llm_result_raw)
        anchor_pov = parse_anchor_pov_result(llm_result)
        
        # 记录输出到 logger
        if prompt_logger:
            prompt_logger.log_outputs(anchor_pov=anchor_pov)
            prompt_logger.end_stage(success=True)
        
        return anchor_pov
    except json.JSONDecodeError:
        if prompt_logger:
            prompt_logger.end_stage(success=False)
        return ""

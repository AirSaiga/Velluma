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

from typing import Any, Optional

from backend.services.prompts import (
    build_planner_agent_prompt,
    parse_planner_result,
    build_pov_assignment_prompt,
    parse_pov_assignment_result,
    build_anchor_pov_prompt,
    parse_anchor_pov_result,
)
import json
from backend.services.llm_client import call_llm
from backend.models import Chapter, Book, Character, CharacterRelationship, StoryBeat


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

    Returns:
        tuple[list[dict], list[StoryBeat]]: (beats 字典列表, StoryBeat 实体列表)
    """
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
    
    story_beats = []
    for beat_index, beat in enumerate(beats, start=1):
        story_beat = StoryBeat(
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            beat_id=beat.get("beat_id"),
            beat_type="progression",
            position=beat.get("position", beat_index),
            location=beat.get("location"),
            pov_character=beat.get("pov_character"),
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
            meta={"target_words": beat.get("target_words", 0)},
            status="planned",
        )
        story_beats.append(story_beat)
    
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
        if isinstance(beat, dict):
            original_pov = beat.get("pov_character")
            beat["original_actor"] = original_pov
            beat["pov_character"] = anchor_pov
            beat["anchor_pov"] = anchor_pov
        elif hasattr(beat, "pov_character"):
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
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    # ── 快速路径：Planner 已声明且合法，直接使用，跳过 LLM ──────────────
    if chapter_narrative_anchor_hint:
        valid_names = {c.get("name", "") for c in characters}
        if chapter_narrative_anchor_hint in valid_names:
            _logger.info(
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

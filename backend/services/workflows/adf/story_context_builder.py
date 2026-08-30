# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
Phase 1: 脉络轨构建器（Spine Track Builder，V3.2 §4.1）。

职责：
- 把章节从孤岛接回全书脉络
- 纯算法为主，必要时 1 次 reasoning LLM 补全入口画面

设计意图：
- entry_state 从前章 summary + rolling_summary 抽取
- must_plant_hooks / must_resolve_hooks 从 PlotLedger 读取
- 失败空值填充，不阻塞主流程

业务场景：
- workflows/adf/adf_workflow.py Phase 1 调用
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.workflows.adf.types import (
    StoryContext,
    EntryState,
    ExitExpectation,
    ChapterPosition,
)

logger = logging.getLogger(__name__)


def _format_previous_summary(previous_summary: Any) -> str:
    """把 previous_summary（可能是 str/dict/object）格式化为画面文本。"""
    if previous_summary is None:
        return ""
    if isinstance(previous_summary, str):
        return previous_summary[:500]
    if isinstance(previous_summary, dict):
        # 可能有 last_scene / summary / text 字段
        for key in ("last_scene", "summary", "text", "content"):
            if previous_summary.get(key):
                return str(previous_summary[key])[:500]
        return str(previous_summary)[:500]
    # 对象
    for attr in ("last_scene", "summary", "text", "content"):
        val = getattr(previous_summary, attr, None)
        if val:
            return str(val)[:500]
    return str(previous_summary)[:500]


def _extract_open_hooks(open_hooks: Any) -> List[str]:
    """把开放伏笔列表（可能是 dict/object 混合）抽取为字符串列表。"""
    result: List[str] = []
    for h in (open_hooks or [])[:10]:
        if isinstance(h, str):
            result.append(h[:120])
        elif isinstance(h, dict):
            content = h.get("content") or h.get("hook_id") or ""
            if content:
                result.append(str(content)[:120])
        else:
            content = getattr(h, "content", None) or getattr(h, "hook_id", None)
            if content:
                result.append(str(content)[:120])
    return result


def _extract_character_positions(entities: Any) -> Dict[str, str]:
    """从本章角色抽取 {名字: 位置}。位置未知填"本章可涉及"。"""
    positions: Dict[str, str] = {}
    for ent in (entities or [])[:10]:
        char = getattr(ent, "character", None) if not isinstance(ent, dict) else ent.get("character")
        if char is None:
            continue
        name = getattr(char, "name", None) or (char.get("name") if isinstance(char, dict) else None)
        if name:
            positions[str(name)] = "本章可涉及"
    return positions


def _extract_character_arc_advances(
    entities: Any,
    chapter_card: Any,
) -> Dict[str, str]:
    """从角色静态卡 + 章节卡抽取本章角色弧推进要求。"""
    advances: Dict[str, str] = {}
    # 优先从章节卡 purpose / must_hit_events 推断
    purpose = ""
    if chapter_card is not None:
        purpose = (getattr(chapter_card, "purpose", "") or "").strip()
    if not purpose:
        return advances

    for ent in (entities or [])[:6]:
        char = getattr(ent, "character", None) if not isinstance(ent, dict) else ent.get("character")
        if char is None:
            continue
        name = getattr(char, "name", None) or (char.get("name") if isinstance(char, dict) else None)
        if name:
            advances[str(name)] = f"呼应章节主旨：{purpose[:60]}"
    return advances


def _derive_chapter_position(
    chapter: Any,
    book: Any,
) -> ChapterPosition:
    """从章节序号 + 卷信息推断章节位置。"""
    chapter_number = getattr(chapter, "chapter_number", None) or 1
    volume_arc = ""
    if book is not None:
        volume_arc = (getattr(book, "rolling_summary", "") or "")[:200]

    # 简易推断：每 12 章为一卷，卷末前 2 章为"近卷高潮"
    volume_size = 12
    offset_in_volume = (chapter_number - 1) % volume_size
    offset_from_climax = volume_size - 1 - offset_in_volume  # 距卷高潮的章数

    if offset_from_climax <= 1:
        pacing_tempo = "fast_paced"
    elif offset_from_climax <= 4:
        pacing_tempo = "balanced"
    else:
        pacing_tempo = "slow_burn"

    return ChapterPosition(
        volume_arc=volume_arc or "（未指定）",
        offset_from_volume_climax=offset_from_climax,
        pacing_tempo=pacing_tempo,
    )


def _split_must_hooks(open_hooks: List[str]) -> tuple[List[str], List[str]]:
    """把 open_hooks 拆分为 must_plant / must_resolve。

    启发式：
    - hook_id 含 "resolve" / "payoff" / "answer" → must_resolve
    - 其余 → must_plant（本章可埋呼应）
    """
    plant: List[str] = []
    resolve: List[str] = []
    for h in open_hooks:
        h_lower = h.lower()
        if any(kw in h_lower for kw in ["resolve", "payoff", "answer", "回收", "揭晓", "揭盅"]):
            resolve.append(h)
        else:
            plant.append(h)
    return plant, resolve


async def build_story_context(
    chapter: Any,
    book: Any,
    chapter_card: Any,
    entities: Any,
    previous_summary: Any,
    rolling_summary: Any,
    open_hooks: Any,
) -> StoryContext:
    """构建脉络轨（Phase 1）。

    纯算法，不调 LLM。所有失败空值填充，不抛异常。

    Args:
        chapter: Chapter ORM
        book: Book ORM
        chapter_card: ChapterCard ORM
        entities: 本章角色列表
        previous_summary: 前章摘要
        rolling_summary: 全书滚动摘要
        open_hooks: 开放伏笔列表

    Returns:
        StoryContext
    """
    try:
        # 入口状态
        last_scene = _format_previous_summary(previous_summary)
        hook_list = _extract_open_hooks(open_hooks)
        character_positions = _extract_character_positions(entities)

        emotional_register = ""
        if chapter_card is not None:
            purpose = (getattr(chapter_card, "purpose", "") or "").strip()
            emotional_register = purpose[:80] if purpose else ""

        entry_state = EntryState(
            character_positions=character_positions,
            emotional_register=emotional_register,
            open_hooks=hook_list,
            last_scene_image=last_scene,
            time_of_day=None,
        )

        # 出口预期
        exit_expectation = ExitExpectation(
            next_chapter_setup="",
            open_question_to_keep=[],
        )

        # 章节位置
        chapter_position = _derive_chapter_position(chapter, book)

        # must_plant / must_resolve
        must_plant, must_resolve = _split_must_hooks(hook_list)

        # 角色弧推进
        character_arc = _extract_character_arc_advances(entities, chapter_card)

        return StoryContext(
            entry_state=entry_state,
            exit_expectation=exit_expectation,
            chapter_position=chapter_position,
            must_plant_hooks=must_plant,
            must_resolve_hooks=must_resolve,
            character_arc_advances=character_arc,
        )
    except Exception as e:
        logger.warning(f"[ADF] 脉络轨构建失败，降级空 spine: {e}")
        return StoryContext()


def format_entry_state_for_prompt(spine: StoryContext) -> str:
    """把 EntryState 格式化为 prompt 可读文本。

    注意：character_positions 列出的是"本章涉及角色"（全章），不是"开场同场角色"——
    若标注为"在场角色"会诱导模型从全员同场的场景开场（真实故障：开场段把所有
    角色塞进同一场景，后续段被迫重演以修正站位，形成剧情回路）。
    """
    e = spine.entry_state
    parts = []
    if e.emotional_register:
        parts.append(f"情绪基调：{e.emotional_register}")
    if e.last_scene_image:
        parts.append(f"前章结尾画面：{e.last_scene_image[:200]}")
    if e.character_positions:
        chars_text = "、".join(e.character_positions.keys())
        parts.append(f"本章涉及角色（未必同场）：{chars_text}")
    if e.open_hooks:
        parts.append("悬挂伏笔：" + "；".join(e.open_hooks[:3]))
    return "；".join(parts) if parts else "（本章是第一章或无前文）"


def format_exit_expectation_for_prompt(spine: StoryContext) -> str:
    """把 ExitExpectation 格式化为 prompt 可读文本。"""
    e = spine.exit_expectation
    parts = []
    if e.next_chapter_setup:
        parts.append(f"为下章铺设：{e.next_chapter_setup}")
    if e.open_question_to_keep:
        parts.append("留开的悬念：" + "；".join(e.open_question_to_keep))
    return "；".join(parts) if parts else "（未指定）"


def format_chapter_position_for_prompt(spine: StoryContext) -> str:
    """把 ChapterPosition 格式化为 prompt 可读文本。"""
    c = spine.chapter_position
    parts = []
    if c.volume_arc:
        parts.append(f"本卷主题：{c.volume_arc[:80]}")
    parts.append(f"距卷高潮：{c.offset_from_volume_climax} 章")
    parts.append(f"节奏：{c.pacing_tempo}")
    return "；".join(parts)

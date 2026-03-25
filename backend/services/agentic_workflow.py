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

import logging
from typing import Union, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, PlotLedger, ChapterMapLocation
from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.services.llm_client import call_llm
from backend.services.prompts import (
    build_planner_agent_prompt,
    parse_planner_result,
)

# 配置模块级日志记录器
logger = logging.getLogger(__name__)


def _calculate_beat_word_counts(beats: list[dict], total_chapter_words: int) -> dict[str, int]:
    """
    Calculate target word count for each beat based on pacing and weight.
    Multipliers: Fast=0.8, Medium=1.0, Slow=1.2
    Formula: score = weight * multiplier
    Result: (score / total_score) * total_chapter_words
    """
    multipliers = {
        "Fast": 0.8,
        "Medium": 1.0,
        "Slow": 1.2,
    }

    # 1. Calculate scores
    beat_data = []
    total_score = 0.0

    for beat in beats:
        beat_id = str(beat.get("beat_id") or "").strip()

        val = beat.get("weight", 1.0)
        try:
            weight = float(val)
        except (ValueError, TypeError):
            weight = 1.0

        pacing_raw = str(beat.get("pacing_type", "")).strip()
        pacing_title = pacing_raw.title()
        if pacing_title in multipliers:
            multiplier = multipliers[pacing_title]
        else:
            multiplier = multipliers["Medium"]

        score = weight * multiplier
        beat_data.append({"beat_id": beat_id, "score": score})
        total_score += score

    # 2. Distribute words
    result = {}
    if total_score <= 0:
        count = total_chapter_words // max(1, len(beats))
        for item in beat_data:
            if item["beat_id"]:
                result[item["beat_id"]] = count
        return result

    current_allocated = 0
    for i, item in enumerate(beat_data):
        b_id = item["beat_id"]
        if not b_id:
            continue

        if i == len(beat_data) - 1:
            count = max(0, total_chapter_words - current_allocated)
        else:
            count = int((item["score"] / total_score) * total_chapter_words)
            current_allocated += count

        result[b_id] = count

    return result


def _normalize_confirmed_beats(beats: Union[list[dict], list[ConfirmedStoryBeat]], word_count: int) -> list[dict]:
    raw_beats: list[dict] = []
    for idx, beat in enumerate(beats, start=1):
        if isinstance(beat, ConfirmedStoryBeat):
            b_dict = beat.model_dump()
        else:
            b_dict = dict(beat or {})

        if not b_dict.get("beat_id"):
            b_dict["beat_id"] = f"beat-{idx}"
        raw_beats.append(b_dict)

    word_count_map = _calculate_beat_word_counts(raw_beats, word_count)

    normalized: list[dict] = []
    for idx, beat_dict in enumerate(raw_beats, start=1):
        summary = str(beat_dict.get("summary") or "").strip()
        if not summary:
            continue

        position = beat_dict.get("position")
        if not isinstance(position, int) or position <= 0:
            position = idx

        beat_id = str(beat_dict.get("beat_id")).strip()
        final_word_count = word_count_map.get(beat_id, 0)

        hook_ids = beat_dict.get("hook_ids") if isinstance(beat_dict.get("hook_ids"), list) else []
        red_lines = beat_dict.get("red_lines") if isinstance(beat_dict.get("red_lines"), list) else []

        pov_character = str(beat_dict.get("pov_character") or "").strip()
        location = str(beat_dict.get("location") or "").strip()
        worldbuilding_instruction = str(beat_dict.get("worldbuilding_instruction") or "").strip()
        entry_state = str(beat_dict.get("entry_state") or "").strip()
        exit_state = str(beat_dict.get("exit_state") or "").strip()

        normalized.append(
            {
                "position": position,
                "beat_id": beat_id,
                "summary": summary,
                "location": location if location else None,
                "pov_character": pov_character if pov_character else None,
                "action_summary": str(beat_dict.get("action_summary") or "").strip() or summary,
                "worldbuilding_instruction": worldbuilding_instruction if worldbuilding_instruction else None,
                "entry_state": entry_state if entry_state else None,
                "exit_state": exit_state if exit_state else None,
                "red_lines": [str(item).strip() for item in red_lines if str(item).strip()],
                "word_count_target": final_word_count,
                "target_words": final_word_count,
                "hook_ids": [str(item).strip() for item in hook_ids if str(item).strip()],
            }
        )
    return normalized


async def preview_agentic_beats(request: GenerateChapterAgenticRequest, db: AsyncSession) -> dict:
    chapter_result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.story_beats))
        .where(Chapter.id == request.chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        return {"beats": [], "debug_prompt": None}

    # Update chapter settings from request for preview
    if request.tension_level is not None:
        chapter.tension_level = request.tension_level
    if request.pacing_style:
        chapter.pacing_style = request.pacing_style

    word_count = request.word_count or 2000
    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()
    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == request.chapter_id)
    )
    entities = entities_result.scalars().all()
    character_ids = [e.entity_id for e in entities]
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    relationships = relationships_result.scalars().all()

    # 加载章节地图位置
    locations_result = await db.execute(
        select(ChapterMapLocation)
        .options(selectinload(ChapterMapLocation.location))
        .where(ChapterMapLocation.chapter_id == request.chapter_id)
    )
    locations = locations_result.scalars().all()

    hook_max_chapter_number = chapter.chapter_number - 1
    historical_chapter_exists = (
        select(Chapter.id)
        .where(
            Chapter.id == PlotLedger.chapter_id,
            Chapter.chapter_number <= hook_max_chapter_number,
        )
        .exists()
    )
    open_hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            or_(
                PlotLedger.created_at_chapter <= hook_max_chapter_number,
                and_(
                    PlotLedger.created_at_chapter.is_(None),
                    or_(PlotLedger.chapter_id.is_(None), historical_chapter_exists),
                ),
            ),
        )
    )
    open_hook_rows = open_hook_result.scalars().all()
    open_hooks = []
    for row in open_hook_rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        open_hooks.append(
            {
                "hook_id": hook_id,
                "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
                "content": content,
            }
        )

    # 获取上一章摘要 + 世界状态快照
    prev_chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    previous_summary = None
    previous_chapter_snapshot = None
    if prev_chapter:
        if prev_chapter.summary:
            previous_summary = prev_chapter.summary
        elif prev_chapter.draft_text:
            previous_summary = f"（上一章末尾原文）...{prev_chapter.draft_text[-1000:]}"
        # 世界状态快照：跨章物理连续性约束（P0 级 - 不可跳过）
        if prev_chapter.world_snapshot:
            previous_chapter_snapshot = prev_chapter.world_snapshot

    planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=word_count,
        open_hooks=open_hooks,
        previous_chapter_summary=previous_summary,
        locations=locations,
        global_taboos=book.core_motifs_taboos if book else None,
        author_intent=request.author_intent,
        previous_chapter_snapshot=previous_chapter_snapshot,
    )
    planning_model = getattr(request, "reasoning_model", None) or request.model
    planner_result_raw = await call_llm(
        system_prompt=planner_system_prompt,
        user_prompt=planner_user_prompt,
        api_key=request.api_key,
        base_url=request.base_url,
        model=planning_model,
        temperature=0.2,
        response_format={"type": "json_object"},
        max_tokens=6000,  # V3.6: 扩大上限，支持3-6个完整beat输出（原1800导致JSON截断→fallback）
    )
    beats = parse_planner_result(planner_result_raw, chapter.outline_text or "", word_count)
    return {
        "beats": _normalize_confirmed_beats(beats, word_count),
        "debug_prompt": {
            "system_prompt": planner_system_prompt,
            "user_prompt": planner_user_prompt
        }
    }

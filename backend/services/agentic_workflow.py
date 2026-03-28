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
from backend.schemas import (
    GenerateChapterAgenticRequest,
    ConfirmedStoryBeat,
    AGENTIC_DEFAULT_MAX_ITERATIONS,
    AGENTIC_DEFAULT_RAG_TOP_K,
    AGENTIC_DEFAULT_RAG_ALPHA,
)
from backend.services.llm_client import call_llm
from backend.services.prompts import (
    build_planner_agent_prompt,
    parse_planner_result,
)

# V3.8: 增强型 RAG 系统集成
try:
    from backend.services.rag import (
        WorkflowRetrievalIntegrator,
        WorkflowStage,
        WorkflowIntegrationConfig,
        RetrievalStrategy,
        MemoryType,
    )
    from backend.services.workflows import (
        load_chapter_context_v3,
        get_context_for_stage,
    )
    # 统一从 config 模块导入参数映射，避免重复定义
    from backend.config import (
        MEMORY_STRATEGY_PRESETS,
        CREATIVITY_TO_PARALLEL_RULE,
        REFINEMENT_TO_THRESHOLD_RULE,
    )
    ENHANCED_RAG_AVAILABLE = True
except ImportError:
    ENHANCED_RAG_AVAILABLE = False

# 配置模块级日志记录器
logger = logging.getLogger(__name__)


# ============================================================
# V3.8 高层语义参数推导适配器
# ============================================================

def resolve_high_level_params(request: GenerateChapterAgenticRequest) -> dict:
    """
    V3.8 高层语义参数推导适配器
    
    根据编辑模式，将高层语义参数转换为底层技术参数。
    基础模式：使用高层参数推导 RAG 参数
    专家模式：使用传入的技术参数
    
    注意：此函数保留用于向后兼容，新代码应直接使用 HighLevelParameterProcessor
    或 DerivationEngine 进行参数推导。
    
    Args:
        request: 生成请求
        
    Returns:
        dict: 推导后的技术参数字典
    """
    # 如果是专家模式，直接使用传入的技术参数
    if not request.is_basic_mode():
        return {
            "max_iterations": request.max_iterations,
            "rag_top_k": request.rag_top_k,
            "rag_alpha": request.rag_alpha,
            "rag_beta": request.rag_beta,
            "rag_gamma": request.rag_gamma,
        }
    
    # 基础模式/意图模式：使用统一的 DerivationEngine 进行推导
    # 避免重复实现推导逻辑
    try:
        from backend.config import DerivationEngine, GenerationConfig
        from backend.config.adapter import adapt_request_to_config
        
        # 使用适配器构建配置，自动执行推导
        config = adapt_request_to_config(request)
        
        return {
            "max_iterations": config.workflow.max_iterations,
            "rag_top_k": config.rag.top_k,
            "rag_alpha": config.rag.semantic_weight,
            "rag_beta": config.rag.time_decay_weight,
            "rag_gamma": config.rag.foreshadowing_weight,
        }
    except Exception as e:
        logger.warning(f"[resolve_high_level_params] 使用 DerivationEngine 失败，回退到默认值: {e}")
        # 回退到默认值
        return {
            "max_iterations": AGENTIC_DEFAULT_MAX_ITERATIONS,
            "rag_top_k": AGENTIC_DEFAULT_RAG_TOP_K,
            "rag_alpha": AGENTIC_DEFAULT_RAG_ALPHA,
            "rag_beta": 0.2,
            "rag_gamma": 0.2,
        }


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

        # V3.6: POV 模式字段
        pov_mode = str(beat_dict.get("pov_mode") or "single").strip()
        if pov_mode not in ("single", "ensemble", "omniscient"):
            pov_mode = "single"
        raw_pov_characters = beat_dict.get("pov_characters")
        pov_characters = [str(c).strip() for c in raw_pov_characters if str(c).strip()] if isinstance(raw_pov_characters, list) else []
        pov_aperture = str(beat_dict.get("pov_aperture") or "").strip() or None
        pov_perception_state = str(beat_dict.get("pov_perception_state") or "正常").strip()

        normalized.append(
            {
                "position": position,
                "beat_id": beat_id,
                "summary": summary,
                "location": location if location else None,
                "pov_character": pov_character if pov_character else None,
                "pov_mode": pov_mode,                          # V3.6
                "pov_characters": pov_characters,             # V3.6
                "pov_aperture": pov_aperture,                 # V3.5
                "pov_perception_state": pov_perception_state, # V3.5
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
    """
    预览生成的故事节拍
    
    V3.8 更新：使用 RuntimeContextBuilder 统一加载上下文，简化代码结构
    
    Args:
        request: 生成请求
        db: 数据库会话
        
    Returns:
        dict: 包含 beats 和 debug_prompt 的字典
    """
    from backend.config.adapter import RuntimeContextBuilder, adapt_request_to_config
    
    # 加载章节
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
    
    # === 使用统一配置和上下文构建器加载上下文 ===
    # 构建配置（自动执行参数推导）
    config = adapt_request_to_config(request, chapter, book)
    
    # 使用 RuntimeContextBuilder 加载上下文
    context = await RuntimeContextBuilder.build(db, config)
    
    # 提取上下文数据
    entities = context.get("characters", [])
    relationships = context.get("relationships", [])
    open_hooks = context.get("open_hooks", [])
    locations = context.get("locations", [])
    previous_summary = context.get("previous_summary")
    
    # 获取世界状态快照（跨章物理连续性约束）
    previous_chapter_snapshot = None
    if chapter.chapter_number > 1:
        prev_chapter_result = await db.execute(
            select(Chapter)
            .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
        )
        prev_chapter = prev_chapter_result.scalar_one_or_none()
        if prev_chapter and prev_chapter.world_snapshot:
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

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
Agentic 工作流编排模块 - 章节生成的核心编排器。

职责：
- 编排多轮迭代的 Agentic 工作流（规划→起草→统稿→审阅→精修）
- 管理 RAG 上下文组装和记忆检索
- 控制迭代收敛和错误处理

业务场景：
- 章节生成请求的完整流程编排
- 多 Agent 协作的结果汇总和质量控制
- 章节发布前的最终确认

主要功能：
- 工作流阶段状态机管理
- RAG 检索策略集成（V3.8 增强）
- 并发控制和资源管理
- 异常恢复和降级策略

依赖项：
- backend.services.workflows: 各阶段工作流实现
- backend.services.rag: RAG 检索系统
- backend.services.prompts: Prompt 模板

使用方式：
    result = await execute_agentic_workflow(
        chapter=chapter,
        book=book,
        request=request
    )
"""

import logging
from typing import Union, Optional, Dict, Any

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
from backend.services.llm import call_llm
from backend.services.prompts import (
    build_planner_agent_prompt,
    parse_planner_result,
)
from backend.services.utils.logging import get_runtime_logger

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
from backend.config import (
    MEMORY_STRATEGY_PRESETS,
    CREATIVITY_TO_PARALLEL_RULE,
    REFINEMENT_TO_THRESHOLD_RULE,
)

# 配置模块级日志记录器
logger = get_runtime_logger(__name__)


def _clamp_int(value: int, low: int, high: int, default: int) -> int:
    try:
        parsed = int(value)
    except (ValueError, TypeError):
        return default
    return max(low, min(high, parsed))


def _normalize_rag_weights(alpha: float, beta: float, gamma: float) -> tuple[float, float, float]:
    def _safe(v: float) -> float:
        try:
            return max(0.0, min(1.0, float(v)))
        except (ValueError, TypeError):
            return 0.0

    a = _safe(alpha)
    b = _safe(beta)
    g = _safe(gamma)
    total = a + b + g
    if total <= 0:
        return AGENTIC_DEFAULT_RAG_ALPHA, 0.2, 0.2
    return a / total, b / total, g / total


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
        rag_alpha, rag_beta, rag_gamma = _normalize_rag_weights(
            request.rag_alpha, request.rag_beta, request.rag_gamma
        )
        return {
            "max_iterations": _clamp_int(request.max_iterations, 1, 5, AGENTIC_DEFAULT_MAX_ITERATIONS),
            "rag_top_k": _clamp_int(request.rag_top_k, 1, 20, AGENTIC_DEFAULT_RAG_TOP_K),
            "rag_alpha": rag_alpha,
            "rag_beta": rag_beta,
            "rag_gamma": rag_gamma,
        }
    
    # 基础模式/意图模式：使用统一的 DerivationEngine 进行推导
    # 避免重复实现推导逻辑
    try:
        from backend.config import DerivationEngine, GenerationConfig
        from backend.config.adapter import adapt_request_to_config

        logger.info("[resolve_high_level_params] 开始调用 adapt_request_to_config")
        # 使用适配器构建配置，自动执行推导
        config = adapt_request_to_config(request)
        logger.info("[resolve_high_level_params] adapt_request_to_config 完成")
        
        rag_alpha, rag_beta, rag_gamma = _normalize_rag_weights(
            config.rag.semantic_weight,
            config.rag.time_decay_weight,
            config.rag.foreshadowing_weight,
        )
        return {
            "max_iterations": _clamp_int(config.workflow.max_iterations, 1, 5, AGENTIC_DEFAULT_MAX_ITERATIONS),
            "rag_top_k": _clamp_int(config.rag.top_k, 1, 20, AGENTIC_DEFAULT_RAG_TOP_K),
            "rag_alpha": rag_alpha,
            "rag_beta": rag_beta,
            "rag_gamma": rag_gamma,
        }
    except Exception as e:
        logger.error(f"[resolve_high_level_params] 使用 DerivationEngine 失败: {type(e).__name__}: {e}", exc_info=True)
        # 回退到默认值
        rag_alpha, rag_beta, rag_gamma = _normalize_rag_weights(
            AGENTIC_DEFAULT_RAG_ALPHA, 0.2, 0.2
        )
        return {
            "max_iterations": AGENTIC_DEFAULT_MAX_ITERATIONS,
            "rag_top_k": AGENTIC_DEFAULT_RAG_TOP_K,
            "rag_alpha": rag_alpha,
            "rag_beta": rag_beta,
            "rag_gamma": rag_gamma,
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


def normalize_confirmed_beats(beats: Union[list[dict], list[ConfirmedStoryBeat]], word_count: int) -> list[dict]:
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


async def preview_agentic_beats(request: GenerateChapterAgenticRequest, repositories: Dict[str, Any]) -> dict:
    """
    预览生成的故事节拍
    
    迁移说明 (2026-03-30)：
    - 已迁移到使用 repositories 参数
    - 所有数据库操作通过 Repository 执行
    
    Args:
        request: 生成请求
        repositories: Repository 字典
        
    Returns:
        dict: 包含 beats 和 debug_prompt 的字典
    """
    from backend.config.adapter import RuntimeContextBuilder, adapt_request_to_config
    
    chapter_repo = repositories.get("chapter")
    book_repo = repositories.get("book")
    
    chapter = await chapter_repo.get_by_id(request.chapter_id) if chapter_repo else None
    if not chapter:
        return {"beats": [], "debug_prompt": None}

    if request.tension_level is not None:
        chapter.tension_level = request.tension_level
    if request.pacing_style:
        chapter.pacing_style = request.pacing_style

    word_count = request.word_count or 2000
    book = await book_repo.get_by_id(chapter.book_id) if book_repo else None
    
    logger.info(f"[Agentic] 正在预览生成节拍: chapter_id={request.chapter_id}")
    config = adapt_request_to_config(request, chapter, book)
    context = await RuntimeContextBuilder.build(repositories, config)
    
    entities = context.get("characters", [])
    relationships = context.get("relationships", [])
    open_hooks = context.get("open_hooks", [])
    locations = context.get("locations", [])
    previous_summary = context.get("previous_summary")
    
    previous_chapter_snapshot = None
    if chapter.chapter_number > 1 and chapter_repo:
        from backend.models import Chapter
        prev_chapter = await chapter_repo.find_one(
            conditions=[
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1,
            ]
        )
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
        "beats": normalize_confirmed_beats(beats, word_count),
        "debug_prompt": {
            "system_prompt": planner_system_prompt,
            "user_prompt": planner_user_prompt
        }
    }

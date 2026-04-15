"""
双轨生成路由 (Dual Track Routes) - V4.0。

职责：提供基于双轨对抗架构的章节生成 API。

API 端点：
- POST /api/chapters/{chapter_id}/generate-dual-track
- POST /api/chapters/{chapter_id}/generate-dual-track-simple

模块结构：
- dual_track.py: 路由定义（主入口）
- stream_handler.py: SSE 流处理器
- progress_tracker.py: 进度跟踪器
- checkpoint_manager.py: 检查点管理器

依赖项：
- backend.services.workflows.dual_track: 双轨工作流
- backend.routes.chapter_generation.stream_handler: 流处理器

使用方式：
    from backend.routes.chapter_generation import router

    app.include_router(router)
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.repositories import (
    ChapterRepository, BookRepository, MemoryRepository,
    PlotLedgerRepository, MapLocationRepository, RelationshipRepository,
)
from backend.services.utils.logging import get_runtime_logger
from backend.routes.chapter_generation.stream_handler import (
    DualTrackGenerationRequest,
    DualTrackStreamHandler,
)

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-dual-track"])


@router.post("/{chapter_id}/generate-dual-track")
async def generate_chapter_dual_track(
    chapter_id: str,
    request: DualTrackGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    使用双轨架构生成章节正文（流式）。

    职责边界：本接口只负责【生成】，不做规划。
    调用方必须先通过 /generate_chapter_agentic_preview_beats 获取节拍，
    经用户确认后将 beats 附在请求体中发给本接口。

    Args:
        chapter_id: 章节 ID
        request: 双轨生成请求，request.beats 不得为空

    Returns:
        流式 SSE 响应，包含生成进度和最终结果

    SSE 事件：
    - ASSEMBLING_CONTEXT: 正在加载上下文
    - GENERATION_RUN: 生成任务已初始化
    - CONTEXT_LOADED: 上下文加载完成
    - BEATS_CONFIRMED: 节拍已确认
    - DRAFTING: 正在生成正文
    - TRACK_A_DONE: Track A 完成
    - TRACK_B_DONE: Track B 完成
    - STITCHING: 正在统稿
    - REVIEWING: 审阅完成
    - FINAL_TEXT_STREAM: 正在输出最终文本
    - TEXT_CHUNK: 文本块
    - DONE: 生成完成
    - ERROR: 发生错误
    - HEARTBEAT: 心跳
    """
    if str(request.chapter_id) != chapter_id:
        raise HTTPException(status_code=422, detail="path chapter_id 与请求体 chapter_id 不一致")

    if not request.beats and not request.resume_from_checkpoint:
        raise HTTPException(
            status_code=422,
            detail=(
                "beats 不能为空。"
                "请先通过 /generate_chapter_agentic_preview_beats 获取节拍，"
                "经用户确认后再调用本接口。"
            ),
        )

    # 构建 Repository 字典
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "memory": MemoryRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "map_location": MapLocationRepository(db),
        "relationship": RelationshipRepository(db),
    }

    # 创建流处理器
    handler = DualTrackStreamHandler(
        chapter_id=chapter_id,
        request=request,
        db=db,
        repos=repos,
    )

    from fastapi.responses import StreamingResponse
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


@router.post("/{chapter_id}/generate-dual-track-simple")
async def generate_chapter_dual_track_simple(
    chapter_id: str,
    request: DualTrackGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    使用双轨架构生成章节正文（非流式）。

    适用于不需要实时进度反馈的场景。

    Args:
        chapter_id: 章节 ID
        request: 双轨生成请求

    Returns:
        包含生成结果的 JSON 响应
    """
    if str(request.chapter_id) != chapter_id:
        raise HTTPException(status_code=422, detail="path chapter_id 与请求体 chapter_id 不一致")

    # 构建 Repository 字典
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "memory": MemoryRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "map_location": MapLocationRepository(db),
        "relationship": RelationshipRepository(db),
    }

    from backend.services.orchestration import resolve_high_level_params, normalize_confirmed_beats
    from backend.services.workflows.dual_track import DualTrackWorkflow, DualTrackConfig
    from backend.services.workflows.sketch_generator import SketchGeneratorConfig
    from backend.services.workflows.adversarial_aligner import AdversarialAlignerConfig
    from backend.services.context import load_full_chapter_context, save_story_beats, build_physical_state_lock
    from backend.services.workflows.planning import assign_pov_to_beats
    from datetime import datetime, timezone

    resolved_params = resolve_high_level_params(request)
    effective_word_count = request.word_count or 2000

    # 加载上下文
    context = await load_full_chapter_context(chapter_id, repos)
    if not context:
        raise HTTPException(status_code=404, detail="章节不存在")

    chapter = context.chapter
    book = context.book

    # 获取节拍
    beats = []
    if request.beats and len(request.beats) > 0:
        beats = normalize_confirmed_beats(request.beats, effective_word_count)
    else:
        from backend.services.workflows.planning import generate_beats
        from backend.world_state_schemas import WorldTerminalState
        
        previous_world_state = None
        if context.previous_world_snapshot:
            try:
                previous_world_state = WorldTerminalState.from_chapter_snapshot(context.previous_world_snapshot)
            except Exception as e:
                logger.warning(f"Failed to parse previous world snapshot: {e}")

        beats, _ = await generate_beats(
            chapter=chapter,
            book=book,
            entities=context.entities,
            relationships=context.relationships,
            word_count=effective_word_count,
            open_hooks=context.open_hooks,
            previous_chapter_summary=context.previous_summary,
            previous_world_state=previous_world_state,
        )

    # POV 分配
    seen_char_ids: set = set()
    pov_candidates = []
    for e in context.entities:
        if e.character and str(e.character.id) not in seen_char_ids:
            seen_char_ids.add(str(e.character.id))
            pov_candidates.append({
                "name": e.character.name,
                "role": "Main" if e.character.importance_level >= 8 else "Supporting",
                "description": e.character.static_prompt or "",
            })

    book_title = book.title if book else "Unknown Book"
    story_premise = f"Title: {book_title}\nChapter Outline: {chapter.outline_text or ''}"
    anchor_pov = beats[0].get("pov_character") if beats else None

    try:
        beats, _ = await assign_pov_to_beats(
            beats=beats,
            characters=pov_candidates,
            story_premise=story_premise,
            previous_chapter_summary=context.previous_summary,
            chapter_narrative_anchor=anchor_pov,
        )
        anchor_pov = beats[0].get("pov_character") if beats else None
    except Exception:
        pass

    # 保存节拍
    await save_story_beats(db, chapter, beats)

    # 构建配置
    config = DualTrackConfig(
        enable_sketch_track=request.enable_sketch_track,
        enable_adversarial_alignment=request.enable_adversarial_alignment,
        use_sketch_for_refinement=request.use_sketch_for_refinement,
        alignment_threshold=request.alignment_threshold,
        sketch_config=SketchGeneratorConfig(
            sketch_ratio=request.sketch_ratio,
        ),
        aligner_config=AdversarialAlignerConfig(
            min_acceptable_score=request.alignment_threshold,
        ),
    )

    # 创建工作流
    workflow = DualTrackWorkflow(
        config=config,
    )

    # 执行工作流
    result = await workflow.execute(
        chapter=chapter,
        book=book,
        beats=beats,
        entities=context.entities,
        relationships=context.relationships,
        word_count=effective_word_count,
        previous_summary=context.previous_summary,
        relevant_memories=context.relevant_memories,
        locations=context.locations,
        physical_state_lock=build_physical_state_lock(beats),
        chapter_assets_schema=chapter.chapter_assets_schema or "",
        anchor_pov=anchor_pov,
    )

    # 保存结果
    chapter.draft_text = result.final_text
    chapter.review_feedback = {
        "generation_run_id": None,
        "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
        "needs_adjustment": result.adjustment_plan.needs_adjustment if result.adjustment_plan else False,
        "stats": result.stats,
    }
    chapter.generation_status = {
        "status": "completed",
        "stage": "DONE",
        "passed": not (result.adjustment_plan.needs_adjustment if result.adjustment_plan else False),
        "stats": result.stats,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    await db.commit()

    return {
        "text": result.final_text,
        "stats": result.stats,
        "alignment_score": result.adjustment_plan.alignment_score if result.adjustment_plan else None,
        "passed": not (result.adjustment_plan.needs_adjustment if result.adjustment_plan else False),
    }

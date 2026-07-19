"""
章节生成路由 (Chapter Generation Routes)。

职责：提供章节生成的 API（CP4.5 重命名后）。

API 端点：
- POST /api/chapters/{chapter_id}/generate-chapter  （CP4.5：原 /generate-dual-track，流式 SSE 主入口）
- POST /api/chapters/{chapter_id}/plan              （合并闸门：章节卡 + 节拍联合预览）
- POST /api/chapters/{chapter_id}/plan/confirm      （合并闸门：确认章节卡 + 节拍）

CP4.5 deprecation 记录：
- /generate-dual-track → 重命名为 /generate-chapter（反映"章节流式生成入口"语义，
  不再绑定"双轨"实现细节；双轨架构仍在内部使用）
- /generate-dual-track-simple → 已删除（Phase 3 CP4.5 第一阶段）
- /generate_chapter_agentic_preview_beats → 已删除（合并闸门 /plan 取代）

模块结构：
- dual_track.py: 路由定义（主入口；文件名保留向后兼容 import 路径）
- stream_handler.py: SSE 流处理器
- progress_tracker.py: 进度跟踪器
- checkpoint_manager.py: 检查点管理器

依赖项：
- backend.services.workflows.dual_track: 双轨工作流（内部实现）
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
from backend.schemas import (
    GenerateChapterAgenticRequest,
    ConfirmedStoryBeat,
    PlanPreviewRequest,    # CP2.3d
    PlanConfirmRequest,    # CP2.3d
)
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


@router.post("/{chapter_id}/generate-chapter")
async def generate_chapter_stream(
    chapter_id: str,
    request: DualTrackGenerationRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    章节生成主入口（流式 SSE）。

    CP4.5 重命名：原 /generate-dual-track → /generate-chapter。
    该端点是当前活跃的章节流式生成入口（双轨架构在内部实现，
    端点名不再绑定"双轨"实现细节，便于未来架构演进）。

    职责边界：本接口只负责【生成】，不做规划。
    调用方必须先通过 /plan + /plan/confirm（合并闸门）确认章节卡 + 节拍，
    然后将 beats 附在请求体中发给本接口。

    Args:
        chapter_id: 章节 ID
        request: 生成请求，request.beats 不得为空（除非 resume_from_checkpoint）

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
                "请先通过 /plan 获取节拍预览，经 /plan/confirm 确认后"
                "再调用本接口。"
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


# ============================================================
# CP4.5：generate-dual-track-simple 已下线（Phase 3 deprecation）
# ============================================================
# 该端点无任何前端调用方（generateApi.generateDualTrackSimple 已废弃）。
# 流式生成走 /generate-chapter（CP4.5 重命名后的活跃入口）。
# 非流式场景可由前端直接调用 /generate-chapter 并忽略 SSE 事件实现。


# ============================================================
# CP2.3d：合并闸门（章节卡 + 节拍联合预览 + 单次确认）
# ============================================================

@router.post("/{chapter_id}/plan")
async def preview_chapter_plan(
    chapter_id: str,
    payload: Optional[PlanPreviewRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """联合预览：生成章节卡 + 节拍（蓝图 §4.4.2 + decisions §2.3）。

    业务流程：
    - 首次调用：payload 为空或 edited_card_fields 为空 → AI 生成 chapter_card + beats（2 次 LLM，5-15s）
    - 重规划：payload.edited_card_fields 非空 → 用用户版本生成新 beats（1 次 LLM）

    响应：{
        chapter_card: {purpose, must_hit_events, ...},
        beats: List[ConfirmedStoryBeat],
        degraded: Optional[dict],
        debug_prompt: Optional[dict],
    }
    """
    from backend.repositories import (
        ChapterRepository, BookRepository, PlotLedgerRepository,
        ChapterAssetRepository, AssetRepository, MapLocationRepository,
        MemoryRepository, RelationshipRepository,
    )
    from backend.services.orchestration.agentic import preview_plan as preview_plan_service

    chapter = await db.get(Chapter, chapter_id) if False else None
    chapter_repo = ChapterRepository(db)
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    repositories = {
        "chapter": chapter_repo,
        "book": BookRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "chapter_entity": None,  # ContextBuilder 内部会按需用
        "chapter_asset": ChapterAssetRepository(db),
        "asset": AssetRepository(db),
        "map_location": MapLocationRepository(db),
        "memory": MemoryRepository(db),
        "relationship": RelationshipRepository(db),
    }

    edited_card = payload.edited_card_fields if payload else None
    result = await preview_plan_service(
        chapter_id=chapter_id,
        repositories=repositories,
        edited_card_fields=edited_card,
    )
    return result


@router.post("/{chapter_id}/plan/confirm")
async def confirm_chapter_plan(
    chapter_id: str,
    payload: PlanConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """单次确认：写 chapter_card + beats 到 DB，status=confirmed。

    业务流程：
    1. upsert ChapterCard（含用户编辑后的字段），status="confirmed"
    2. 调 save_story_beats 写入 StoryBeat 表（先删后插）
    3. 返回 confirmed chapter_card

    警示：本端点会覆盖现有 chapter_card 与 beats 数据（先删后插语义）。
    """
    from backend.repositories import ChapterCardRepository, ChapterRepository
    from backend.models import ChapterCard as ChapterCardModel, Chapter
    from backend.services.orchestration.beat_manager import save_story_beats

    chapter_repo = ChapterRepository(db)
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    # 1. upsert chapter_card
    cc_repo = ChapterCardRepository(db)
    existing = await cc_repo.get_by_chapter(chapter.id)
    fields = dict(payload.chapter_card_fields)
    # 强制 status=confirmed，绑定 chapter_id/book_id/chapter_number
    fields["status"] = "confirmed"
    fields["chapter_id"] = chapter.id
    fields["book_id"] = chapter.book_id
    fields["chapter_number"] = chapter.chapter_number

    if existing:
        # 更新（白名单字段）
        editable = [
            "purpose", "must_hit_events", "involved_characters",
            "foreshadow_ops", "continuity", "word_target", "pacing",
            "tension", "style_override_id", "status",
        ]
        for k in editable:
            if k in fields:
                setattr(existing, k, fields[k])
        card = existing
    else:
        # 新建（只取合法字段）
        valid_fields = {k: v for k, v in fields.items()
                        if k in {"book_id", "chapter_id", "chapter_number",
                                 "purpose", "must_hit_events", "involved_characters",
                                 "foreshadow_ops", "continuity", "word_target",
                                 "pacing", "tension", "style_override_id", "status"}}
        card = ChapterCardModel(**valid_fields)
        db.add(card)
    await db.flush()

    # 2. 保存 beats（先删后插）
    beats_dicts = [b.model_dump() if hasattr(b, "model_dump") else dict(b)
                   for b in payload.beats]
    await save_story_beats(db, chapter, beats_dicts)

    await db.commit()
    await db.refresh(card)

    # 返回 dict 形式（避免 ORM 序列化问题）
    return {
        "id": str(card.id),
        "book_id": str(card.book_id),
        "chapter_id": str(card.chapter_id) if card.chapter_id else None,
        "chapter_number": card.chapter_number,
        "purpose": card.purpose,
        "must_hit_events": card.must_hit_events,
        "involved_characters": card.involved_characters,
        "foreshadow_ops": card.foreshadow_ops,
        "continuity": card.continuity,
        "word_target": card.word_target,
        "pacing": card.pacing,
        "tension": card.tension,
        "status": card.status,
        "beats_count": len(beats_dicts),
    }

"""
后台生成路由 - 极简版
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.core.dependencies import get_db
from backend.services.generation.background_manager import background_manager
from backend.repositories import ChapterRepository, BookRepository

router = APIRouter(prefix="/api/generation", tags=["generation"])
logger = logging.getLogger(__name__)


class SubmitRequest(BaseModel):
    chapter_id: str
    word_count: int = 2000
    model: Optional[str] = None
    reasoning_model: Optional[str] = None
    creative_model: Optional[str] = None
    beats: list = []
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class StatusResponse(BaseModel):
    chapter_id: str
    status: str  # pending/running/success/failed/cancelled/idle
    progress: int
    current_stage: Optional[str] = None
    partial_result: Optional[str] = None
    final_result: Optional[str] = None
    error: Optional[str] = None


@router.post("/submit")
async def submit(request: SubmitRequest, db: AsyncSession = Depends(get_db)):
    """提交后台生成任务"""
    # 验证章节
    chapter = await ChapterRepository(db).get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    # 定义生成函数
    async def generate_with_progress(progress_callback, **kwargs):
        from backend.services.workflows.dual_track import DualTrackWorkflow, DualTrackConfig
        from backend.services.context import load_full_chapter_context
        from backend.services.orchestration import normalize_confirmed_beats
        
        progress_callback("assembling_context", 5)
        
        context = await load_full_chapter_context(
            request.chapter_id,
            {"chapter": ChapterRepository(db), "book": BookRepository(db)},
            api_key=request.api_key,
            base_url=request.base_url,
        )
        if not context:
            raise ValueError("无法加载章节上下文")
        
        beats = normalize_confirmed_beats(request.beats or [], request.word_count)
        if not beats:
            raise ValueError("没有可用的 beats")
        
        progress_callback("drafting", 30)
        
        workflow = DualTrackWorkflow(
            api_key=request.api_key or "",
            base_url=request.base_url or "",
            reasoning_model=request.reasoning_model or request.model or "gpt-4o-mini",
            creative_model=request.creative_model or request.model or "gpt-4o-mini",
            config=DualTrackConfig(),
        )
        
        result = await workflow.execute(
            chapter=context.chapter,
            book=context.book,
            beats=beats,
            entities=context.entities,
            relationships=context.relationships,
            word_count=request.word_count,
            previous_summary=context.previous_summary,
            relevant_memories=context.relevant_memories,
            locations=context.locations,
            chapter_assets_schema=context.chapter.chapter_assets_schema or "",
        )
        
        progress_callback("completed", 100)
        return result.final_text
    
    # 启动后台生成
    task_info = await background_manager.start_generation(
        chapter_id=request.chapter_id,
        generate_func=generate_with_progress,
    )
    
    return StatusResponse(
        chapter_id=task_info.chapter_id,
        status=task_info.status,
        progress=task_info.progress,
        current_stage=task_info.current_stage,
    )


@router.get("/status/{chapter_id}")
async def get_status(chapter_id: str):
    """查询生成状态"""
    status = background_manager.get_status(chapter_id)
    if not status:
        return StatusResponse(chapter_id=chapter_id, status="idle", progress=0)
    return StatusResponse(**status)


@router.post("/cancel/{chapter_id}")
async def cancel(chapter_id: str):
    """取消生成任务"""
    cancelled = await background_manager.cancel_generation(chapter_id)
    return {"cancelled": cancelled}

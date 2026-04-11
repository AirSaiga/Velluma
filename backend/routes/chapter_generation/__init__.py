"""
章节生成路由模块 - 提供双轨章节生成的 API 路由。

职责：
- 定义双轨生成的 API 端点
- 处理 SSE 流式响应
- 管理生成进度和检查点

模块结构：
- dual_track.py: API 路由定义（主入口）
- stream_handler.py: SSE 流处理器
- progress_tracker.py: 进度跟踪器
- checkpoint_manager.py: 检查点管理器

使用方式：
    from backend.routes.chapter_generation import router

    app.include_router(router)
"""

from fastapi import APIRouter, Depends, HTTPException
from backend.core.dependencies import get_chapter_repository, get_book_repository
from backend.repositories import ChapterRepository, BookRepository
from backend.schemas import (
    GenerateChapterAgenticRequest,
    GenerateChapterAgenticPreviewResponse,
)
from backend.services.generation.chapter import preview_agentic_beats
from backend.services.utils.logging import get_runtime_logger

# 主路由（来自 dual_track.py）
from backend.routes.chapter_generation.dual_track import router as dual_track_router

# 创建额外的路由（用于节拍预览等）
extra_router = APIRouter(prefix="/api", tags=["chapter_generation"])
logger = get_runtime_logger(__name__)


@extra_router.post("/generate_chapter_agentic_preview_beats", response_model=GenerateChapterAgenticPreviewResponse)
async def generate_chapter_agentic_preview_beats(
    request: GenerateChapterAgenticRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    """节拍预览端点 - 根据意图生成章节节拍规划"""
    logger.info(f"[PreviewBeats] 收到节拍预览请求: chapter_id={request.chapter_id}")
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    repositories = {
        "chapter": chapter_repo,
        "book": book_repo,
    }
    result = await preview_agentic_beats(request, repositories)
    logger.info(f"[PreviewBeats] 节拍预览完成: chapter_id={request.chapter_id}, beat_count={len(result.get('beats', []))}")
    return result


# 合并路由
router = APIRouter()
router.include_router(dual_track_router)
router.include_router(extra_router)

# 导出子模块供其他模块使用
from backend.routes.chapter_generation.checkpoint_manager import CheckpointManager
from backend.routes.chapter_generation.progress_tracker import ProgressTracker, StreamEventBuilder

__all__ = [
    "router",
    "CheckpointManager",
    "ProgressTracker",
    "StreamEventBuilder",
]

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

from backend.routes.chapter_generation.dual_track import router

# 导出子模块供其他模块使用
from backend.routes.chapter_generation.checkpoint_manager import CheckpointManager
from backend.routes.chapter_generation.progress_tracker import ProgressTracker, StreamEventBuilder

__all__ = [
    "router",
    "CheckpointManager",
    "ProgressTracker",
    "StreamEventBuilder",
]

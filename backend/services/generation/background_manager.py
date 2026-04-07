"""
后台生成管理器 - 极简版
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class GenerationTask:
    """生成任务信息"""
    chapter_id: str
    status: str  # pending/running/success/failed/cancelled
    created_at: datetime
    progress: int = 0
    current_stage: str = ""
    partial_result: str = ""
    final_result: str = ""
    error_message: str = ""
    asyncio_task: Optional[asyncio.Task] = None


class BackgroundGenerationManager:
    """后台生成管理器（单用户）"""
    
    def __init__(self):
        self._tasks: Dict[str, GenerationTask] = {}
    
    async def start_generation(
        self,
        chapter_id: str,
        generate_func: Callable,
        **kwargs
    ) -> GenerationTask:
        """启动后台生成任务"""
        # 取消已有任务
        await self.cancel_generation(chapter_id)
        
        task_info = GenerationTask(
            chapter_id=chapter_id,
            status="pending",
            created_at=datetime.now(),
        )
        self._tasks[chapter_id] = task_info
        
        def progress_callback(stage: str, percent: int, message: str = ""):
            task_info.current_stage = stage
            task_info.progress = percent
            if message:
                task_info.partial_result = message
        
        async def wrapper():
            task_info.status = "running"
            try:
                result = await generate_func(
                    progress_callback=progress_callback,
                    **kwargs
                )
                task_info.final_result = result
                task_info.status = "success"
                task_info.progress = 100
                logger.info(f"Task {chapter_id} completed")
            except asyncio.CancelledError:
                task_info.status = "cancelled"
                logger.info(f"Task {chapter_id} cancelled")
            except Exception as e:
                task_info.status = "failed"
                task_info.error_message = str(e)
                logger.error(f"Task {chapter_id} failed: {e}")
        
        task_info.asyncio_task = asyncio.create_task(wrapper())
        return task_info
    
    async def cancel_generation(self, chapter_id: str) -> bool:
        """取消生成任务"""
        task = self._tasks.get(chapter_id)
        if not task or not task.asyncio_task:
            return False
        
        if task.status in ["pending", "running"]:
            task.asyncio_task.cancel()
            try:
                await task.asyncio_task
            except asyncio.CancelledError:
                pass
            task.status = "cancelled"
            return True
        return False
    
    def get_status(self, chapter_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        task = self._tasks.get(chapter_id)
        if not task:
            return None
        
        return {
            "chapter_id": task.chapter_id,
            "status": task.status,
            "progress": task.progress,
            "current_stage": task.current_stage,
            "partial_result": task.partial_result if task.status == "running" else None,
            "final_result": task.final_result if task.status == "success" else None,
            "error": task.error_message if task.status == "failed" else None,
        }


# 全局单例
background_manager = BackgroundGenerationManager()

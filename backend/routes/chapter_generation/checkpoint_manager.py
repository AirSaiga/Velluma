"""
检查点管理器 (Checkpoint Manager) - 双轨生成路由的持久化管理。

职责：
- 管理章节生成过程中的检查点持久化
- 记录运行状态和阶段进度
- 支持从检查点恢复生成

主要功能：
- 保存检查点到章节的 generation_checkpoints 字段
- 更新章节的 generation_status 状态
- 维护运行 ID 和时间戳

依赖项：
- backend.models.Chapter: 章节模型

使用方式：
    from backend.routes.chapter_generation.checkpoint_manager import CheckpointManager

    manager = CheckpointManager(db)
    await manager.persist(chapter, run_id, stage, status, payload)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.models import Chapter

logger = logging.getLogger(__name__)

# 检查点最大保留数量
MAX_CHECKPOINTS = 20


class CheckpointManager:
    """
    检查点管理器。

    职责：
    - 持久化生成过程中的检查点
    - 管理章节的运行状态
    - 提供恢复支持

    设计决策：
    - 检查点存储在 chapter.generation_checkpoints 列表中
    - 运行状态存储在 chapter.generation_status 字典中
    - 最多保留最近 MAX_CHECKPOINTS 个检查点
    """

    def __init__(self, db: AsyncSession):
        """
        初始化检查点管理器。

        Args:
            db: 数据库会话
        """
        self.db = db

    async def persist(
        self,
        chapter: Chapter,
        run_id: str,
        stage: str,
        status: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        持久化检查点。

        Args:
            chapter: 章节对象
            run_id: 运行 ID
            stage: 当前阶段
            status: 状态 (running/completed/failed/cancelled)
            payload: 附加数据
        """
        checkpoints = list(chapter.generation_checkpoints or [])
        checkpoint = {
            "stage": stage,
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }
        checkpoints.append(checkpoint)

        # 更新章节运行 ID
        chapter.generation_run_id = run_id

        # 限制检查点数量，只保留最新的
        chapter.generation_checkpoints = checkpoints[-MAX_CHECKPOINTS:]

        # 更新运行状态
        chapter.generation_status = {
            **(chapter.generation_status or {}),
            "run_id": run_id,
            "stage": stage,
            "status": status,
            "updated_at": checkpoint["timestamp"],
        }

        await self.db.commit()
        logger.info(f"[CheckpointManager] 保存检查点 stage={stage}, status={status}, run_id={run_id}")

    async def get_latest_checkpoint(
        self,
        chapter: Chapter,
        stage_filter: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        获取最新的检查点。

        Args:
            chapter: 章节对象
            stage_filter: 可选的阶段过滤

        Returns:
            最新的检查点，如果没有则返回 None
        """
        checkpoints = list(chapter.generation_checkpoints or [])
        if not checkpoints:
            return None

        if stage_filter:
            for checkpoint in reversed(checkpoints):
                if checkpoint.get("stage") == stage_filter:
                    return checkpoint
            return None

        return checkpoints[-1]

    async def get_beats_from_checkpoint(
        self,
        chapter: Chapter,
        run_id: Optional[str] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        从检查点恢复节拍列表。

        Args:
            chapter: 章节对象
            run_id: 可选的运行 ID 过滤

        Returns:
            节拍列表，如果没有则返回 None
        """
        checkpoints = list(chapter.generation_checkpoints or [])

        for checkpoint in reversed(checkpoints):
            if run_id and checkpoint.get("payload", {}).get("run_id") != run_id:
                continue

            if checkpoint.get("stage") == "BEATS_CONFIRMED":
                payload = checkpoint.get("payload", {})
                beats = payload.get("beats", [])
                if beats:
                    return beats

        return None

    async def update_status(
        self,
        chapter: Chapter,
        status_updates: Dict[str, Any],
    ) -> None:
        """
        更新章节状态。

        Args:
            chapter: 章节对象
            status_updates: 状态更新字典
        """
        chapter.generation_status = {
            **(chapter.generation_status or {}),
            **status_updates,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.commit()

    async def mark_completed(
        self,
        chapter: Chapter,
        run_id: str,
        stats: Dict[str, Any],
        final_text: str,
        passed: bool = True,
        alignment_score: Optional[float] = None,
        revision_count: int = 0,
    ) -> None:
        """
        标记章节生成为已完成。

        Args:
            chapter: 章节对象
            run_id: 运行 ID
            stats: 统计信息
            final_text: 最终文本
            passed: 是否通过审阅
            alignment_score: 对齐分数
            revision_count: 修订次数
        """
        chapter.generation_status = {
            **(chapter.generation_status or {}),
            "run_id": run_id,
            "status": "completed",
            "stage": "DONE",
            "passed": passed,
            "revision_count": revision_count,
            "alignment_score": alignment_score,
            "stats": stats,
            "final_text": final_text,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # 保存最终文本
        chapter.draft_text = final_text

        # 保存审阅反馈
        chapter.review_feedback = {
            **(chapter.review_feedback or {}),
            "generation_run_id": run_id,
            "alignment_score": alignment_score,
            "needs_adjustment": not passed,
            "stats": stats,
        }

        chapter.revision_count = revision_count

        await self.persist(
            chapter=chapter,
            run_id=run_id,
            stage="DONE",
            status="completed",
            payload={
                "alignment_score": alignment_score,
                "final_length": len(final_text),
                "stats": stats,
            },
        )

    async def mark_failed(
        self,
        chapter: Chapter,
        run_id: str,
        error: str,
        exception_type: str,
        stage: str = "FAILED",
    ) -> None:
        """
        标记章节生成为失败。

        Args:
            chapter: 章节对象
            run_id: 运行 ID
            error: 错误信息
            exception_type: 异常类型
            stage: 失败阶段
        """
        chapter.generation_status = {
            **(chapter.generation_status or {}),
            "run_id": run_id,
            "status": "failed",
            "stage": stage,
            "error": error,
            "exception_type": exception_type,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.persist(
            chapter=chapter,
            run_id=run_id,
            stage=stage,
            status="failed",
            payload={"error": error, "exception_type": exception_type},
        )

    async def mark_cancelled(
        self,
        chapter: Chapter,
        run_id: str,
        partial_text: Optional[str] = None,
        reason: str = "client_disconnected",
    ) -> None:
        """
        标记章节生成为已取消。

        Args:
            chapter: 章节对象
            run_id: 运行 ID
            partial_text: 部分文本
            reason: 取消原因
        """
        if partial_text:
            chapter.draft_text = partial_text

        chapter.generation_status = {
            **(chapter.generation_status or {}),
            "run_id": run_id,
            "status": "cancelled",
            "stage": "CANCELLED",
            "partial_text_length": len(partial_text) if partial_text else 0,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.persist(
            chapter=chapter,
            run_id=run_id,
            stage="CANCELLED",
            status="cancelled",
            payload={
                "reason": reason,
                "partial_text_length": len(partial_text) if partial_text else 0,
            },
        )

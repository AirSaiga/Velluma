import math
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select

from backend.models import MemoryChunk, PlotLedger
from backend.repositories.base import BaseRepository, QuerySpec


def compute_memory_score(
    cosine_similarity: float,
    delta_days: float,
    plot_weight: float,
    alpha: float = 0.6,
    beta: float = 0.2,
    gamma: float = 0.2,
    lambda_decay: float = 0.1,
) -> float:
    safe_cosine = max(0.0, min(1.0, cosine_similarity))
    safe_delta_days = max(0.0, delta_days)
    safe_plot_weight = max(0.0, min(1.0, plot_weight))
    time_score = math.exp(-lambda_decay * safe_delta_days)
    return alpha * safe_cosine + beta * time_score + gamma * safe_plot_weight


class MemoryRepository(BaseRepository[MemoryChunk]):
    """
    记忆块仓储：管理 AI 上下文记忆数据。

    业务边界：记忆块可全局可按书籍/章节隔离，支持多级检索粒度。
    设计意图：created_at.desc() 排序使最新记忆优先，用于"记忆检索"场景下返回最新相关内容。
    """
    model = MemoryChunk

    async def list(self, book_id: Optional[UUID] = None, chapter_id: Optional[UUID] = None):
        """
        条件查询记忆块：支持三种粒度 - 全局、书籍级、章节级。

        逻辑分块：
        1. 初始化空 QuerySpec
        2. 依次添加 book_id 过滤（若提供）
        3. 添加 chapter_id 过滤（若提供）
        4. 按创建时间倒序排列

        关键数据流：
        - book_id + chapter_id 同时存在时：AND 关系，两个条件都满足
        - 两者都为空时：返回全局记忆（跨书籍）
        """
        spec = QuerySpec.create()
        if book_id:
            spec.where(MemoryChunk.book_id == book_id)
        if chapter_id:
            spec.where(MemoryChunk.chapter_id == chapter_id)
        spec.order(MemoryChunk.created_at.desc())
        return await self.find_all(
            spec=spec
        )

    async def search_similar(
        self,
        embedding: List[float],
        book_id: UUID,
        limit: int = 5,
        alpha: float = 0.6,
        beta: float = 0.2,
        gamma: float = 0.2,
        lambda_decay: float = 0.1,
        exclude_chapter_id: Optional[UUID] = None,
    ):
        candidate_limit = max(limit * 3, limit)
        distance_expr = MemoryChunk.embedding.cosine_distance(embedding)
        
        query = select(MemoryChunk, distance_expr.label("distance")).where(
            MemoryChunk.book_id == book_id, 
            MemoryChunk.embedding.is_not(None)
        )
        
        if exclude_chapter_id:
            query = query.where(MemoryChunk.chapter_id != exclude_chapter_id)
            
        stmt = query.order_by(distance_expr).limit(candidate_limit)
        
        result = await self.db.execute(stmt)
        rows = result.all()
        if not rows:
            return []

        chapter_ids = {chunk.chapter_id for chunk, _ in rows if chunk.chapter_id}
        unresolved_ledger_chapter_ids = set()
        if chapter_ids:
            plot_stmt = select(PlotLedger.chapter_id).where(
                PlotLedger.book_id == book_id,
                PlotLedger.chapter_id.in_(chapter_ids),
                PlotLedger.status == "open",
            )
            plot_result = await self.db.execute(plot_stmt)
            unresolved_ledger_chapter_ids = set(plot_result.scalars().all())

        now = datetime.now(timezone.utc)
        ranked = []
        for chunk, distance in rows:
            created_at = chunk.created_at or now
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            delta_days = (now - created_at).total_seconds() / 86400
            cosine_similarity = 1 - float(distance)
            plot_weight = 1.0 if chunk.chapter_id in unresolved_ledger_chapter_ids else 0.0
            score = compute_memory_score(
                cosine_similarity=cosine_similarity,
                delta_days=delta_days,
                plot_weight=plot_weight,
                alpha=alpha,
                beta=beta,
                gamma=gamma,
                lambda_decay=lambda_decay,
            )
            ranked.append((score, cosine_similarity, chunk.created_at or datetime.min, chunk))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in ranked[:limit]]

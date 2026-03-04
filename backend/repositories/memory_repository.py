from typing import List, Optional
from uuid import UUID

from backend.models import MemoryChunk
from backend.repositories.base import BaseRepository, QuerySpec


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

    async def search_similar(self, embedding: List[float], book_id: UUID, limit: int = 5):
        """
        向量相似度检索。
        """
        from sqlalchemy import select

        stmt = select(MemoryChunk).where(MemoryChunk.book_id == book_id)
        # 使用 cosine distance (<=>) 进行排序
        stmt = stmt.order_by(MemoryChunk.embedding.cosine_distance(embedding)).limit(limit)

        result = await self.db.execute(stmt)
        return result.scalars().all()


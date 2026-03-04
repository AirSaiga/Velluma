from typing import Optional
from uuid import UUID

from backend.models import MemoryChunk
from backend.repositories.base import BaseRepository, QuerySpec


class MemoryRepository(BaseRepository[MemoryChunk]):
    model = MemoryChunk

    async def list(self, book_id: Optional[UUID] = None, chapter_id: Optional[UUID] = None):
        spec = QuerySpec.create()
        if book_id:
            spec.where(MemoryChunk.book_id == book_id)
        if chapter_id:
            spec.where(MemoryChunk.chapter_id == chapter_id)
        spec.order(MemoryChunk.created_at.desc())
        return await self.find_all(
            spec=spec
        )

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from backend.models import Asset, ChapterAsset
from backend.repositories.base import BaseRepository

class AssetRepository(BaseRepository[Asset]):
    def __init__(self):
        super().__init__(Asset)

    async def list_by_book(self, book_id: UUID) -> List[Asset]:
        result = await self._db.execute(
            select(Asset)
            .filter(Asset.book_id == book_id)
            .order_by(Asset.importance_level.desc(), Asset.created_at.desc())
        )
        return list(result.scalars().all())

class ChapterAssetRepository(BaseRepository[ChapterAsset]):
    def __init__(self):
        super().__init__(ChapterAsset)

    async def list_by_chapter(self, chapter_id: UUID) -> List[ChapterAsset]:
        result = await self._db.execute(
            select(ChapterAsset)
            .options(joinedload(ChapterAsset.asset))
            .filter(ChapterAsset.chapter_id == chapter_id)
        )
        return list(result.scalars().all())

    async def delete_by_chapter(self, chapter_id: UUID):
        await self._db.execute(
            select(ChapterAsset)
            .filter(ChapterAsset.chapter_id == chapter_id)
        )
        result = await self._db.execute(
            select(ChapterAsset).filter(ChapterAsset.chapter_id == chapter_id)
        )
        for item in result.scalars().all():
            await self._db.delete(item)

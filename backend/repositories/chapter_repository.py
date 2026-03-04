from uuid import UUID

from sqlalchemy.orm import selectinload

from backend.models import Chapter, ChapterEntity
from backend.repositories.base import BaseRepository, QuerySpec


class ChapterRepository(BaseRepository[Chapter]):
    model = Chapter

    async def list_entities(self, chapter_id: UUID):
        spec = QuerySpec.create(ChapterEntity).where(ChapterEntity.chapter_id == chapter_id)
        return await self.find_all(
            spec=spec
        )

    async def list_entities_with_character(self, chapter_id: UUID):
        spec = (
            QuerySpec.create(ChapterEntity)
            .where(ChapterEntity.chapter_id == chapter_id)
            .with_options(selectinload(ChapterEntity.character))
        )
        return await self.find_all(
            spec=spec
        )

    async def add_entity(self, chapter_id: UUID, entity_id: UUID, entity_type: str = "character"):
        chapter_entity = ChapterEntity(chapter_id=chapter_id, entity_id=entity_id, entity_type=entity_type)
        self.db.add(chapter_entity)
        await self.db.commit()

    async def delete_entity(self, entity: ChapterEntity):
        await self.db.delete(entity)

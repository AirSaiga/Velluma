from uuid import UUID

from backend.models import Character
from backend.repositories.base import BaseRepository, QuerySpec


class CharacterRepository(BaseRepository[Character]):
    model = Character

    async def list_by_book(self, book_id: UUID):
        spec = QuerySpec.create().where(Character.book_id == book_id).order(Character.importance_level.desc())
        return await self.find_all(
            spec=spec
        )

    async def list_by_ids(self, ids):
        if not ids:
            return []
        return await self.find_all(spec=QuerySpec.create().where(Character.id.in_(ids)))

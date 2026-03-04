from typing import Optional
from uuid import UUID

from backend.models import Character, CharacterRelationship
from backend.repositories.base import BaseRepository, QuerySpec


class RelationshipRepository(BaseRepository[CharacterRelationship]):
    model = CharacterRelationship

    async def list(self, book_id: Optional[UUID] = None):
        if book_id:
            spec = QuerySpec.create().where(Character.book_id == book_id).join_on(
                Character,
                CharacterRelationship.source_char_id == Character.id,
            )
            return await self.find_all(
                spec=spec
            )
        return await self.find_all()

    async def get_by_pair(self, source_char_id: UUID, target_char_id: UUID) -> Optional[CharacterRelationship]:
        spec = QuerySpec.create().where(
            CharacterRelationship.source_char_id == source_char_id,
            CharacterRelationship.target_char_id == target_char_id,
        )
        return await self.find_one(
            spec=spec
        )

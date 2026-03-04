from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.repositories import (
    BookRepository,
    ChapterRepository,
    CharacterRepository,
    RelationshipRepository,
    MemoryRepository,
)


def get_book_repository(db: AsyncSession = Depends(get_db)) -> BookRepository:
    return BookRepository(db)


def get_chapter_repository(db: AsyncSession = Depends(get_db)) -> ChapterRepository:
    return ChapterRepository(db)


def get_character_repository(db: AsyncSession = Depends(get_db)) -> CharacterRepository:
    return CharacterRepository(db)


def get_relationship_repository(db: AsyncSession = Depends(get_db)) -> RelationshipRepository:
    return RelationshipRepository(db)


def get_memory_repository(db: AsyncSession = Depends(get_db)) -> MemoryRepository:
    return MemoryRepository(db)

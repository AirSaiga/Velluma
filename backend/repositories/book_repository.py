from uuid import UUID

from backend.models import Book, Chapter
from backend.repositories.base import BaseRepository, QuerySpec


class BookRepository(BaseRepository[Book]):
    model = Book

    async def list_chapters(self, book_id: UUID):
        spec = QuerySpec.create(Chapter).where(Chapter.book_id == book_id).order(Chapter.chapter_number)
        return await self.find_all(
            spec=spec
        )

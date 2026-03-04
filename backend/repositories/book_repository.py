from uuid import UUID

from backend.models import Book, Chapter
from backend.repositories.base import BaseRepository, QuerySpec


class BookRepository(BaseRepository[Book]):
    """
    书籍仓储：管理书籍实体及其关联数据。

    业务边界：仅处理 Book 核心实体，关联数据（章节、角色）由专门仓储负责。
    事务边界：继承基类的自动提交策略，单操作事务。
    """
    model = Book

    async def list_chapters(self, book_id: UUID):
        """
        获取某书籍的所有章节：用于目录展示或全量导出场景。

        数据流：book_id → WHERE book_id = ? → 按 chapter_number 排序 → List[Chapter]
        关键点：按章节号排序而非创建时间，确保阅读顺序正确。
        """
        spec = QuerySpec.create(Chapter).where(Chapter.book_id == book_id).order(Chapter.chapter_number)
        return await self.find_all(
            spec=spec
        )

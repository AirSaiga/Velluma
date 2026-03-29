"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from typing import List

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

    async def list_chapters(self, book_id: UUID) -> List[Chapter]:
        """获取某书籍的所有章节：用于目录展示或全量导出场景。

        数据流：book_id → WHERE book_id = ? → 按 chapter_number 排序 → List[Chapter]
        关键点：按章节号排序而非创建时间，确保阅读顺序正确。

        Args:
            book_id: 书籍 UUID

        Returns:
            List[Chapter]: 按章节号排序的章节列表
        """
        spec = QuerySpec.create(Chapter).where(Chapter.book_id == book_id).order(Chapter.chapter_number)
        return await self.find_all(
            spec=spec
        )

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

"""
章节卡仓储（Phase 1 CP2.1b 新建）。

职责：ChapterCard 表的数据访问层，供 CP2.3 合并闸门与上下文引擎调用。

业务场景：
- CP2.3 合并闸门：生成 / 获取 / 更新 / 确认章节卡
- ContextEngine P1 章级块：读取 chapter_card.purpose / must_hit_events
- 章节卡链：按 book_id + chapter_number 排序查询，支持"上一章卡"回溯
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ChapterCard
from backend.repositories.base import BaseRepository, QuerySpec


class ChapterCardRepository(BaseRepository[ChapterCard]):
    """章节卡仓储。"""

    model = ChapterCard

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_by_chapter(self, chapter_id: UUID) -> Optional[ChapterCard]:
        """获取章节关联的章节卡（一个章节至多一张卡）。"""
        spec = QuerySpec.create().where(ChapterCard.chapter_id == chapter_id)
        return await self.find_one(spec=spec)

    async def list_by_book(
        self,
        book_id: UUID,
        status: Optional[str] = None,
    ) -> List[ChapterCard]:
        """列出书籍的所有章节卡，按 chapter_number 升序（形成章节卡链）。"""
        spec = QuerySpec.create().where(ChapterCard.book_id == book_id)
        if status:
            spec.where(ChapterCard.status == status)
        spec.order(ChapterCard.chapter_number.asc())
        return await self.find_all(spec=spec)

    async def get_previous_card(
        self,
        book_id: UUID,
        before_chapter_number: int,
    ) -> Optional[ChapterCard]:
        """获取指定章节之前最近的一张卡（章节卡链回溯）。"""
        spec = QuerySpec.create().where(
            ChapterCard.book_id == book_id,
            ChapterCard.chapter_number < before_chapter_number,
        )
        spec.order(ChapterCard.chapter_number.desc())
        return await self.find_one(spec=spec)

    async def get_or_create_for_chapter(
        self,
        book_id: UUID,
        chapter_id: UUID,
        chapter_number: int,
    ) -> ChapterCard:
        """获取或创建章节卡（首次访问时创建草稿）。"""
        existing = await self.get_by_chapter(chapter_id)
        if existing:
            return existing
        card = ChapterCard(
            book_id=book_id,
            chapter_id=chapter_id,
            chapter_number=chapter_number,
            status="draft",
        )
        return await self.create(card)

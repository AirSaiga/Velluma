# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
文风卡仓储（Phase 1 CP2.1b 新建）。

职责：StyleCard 表的数据访问层。

业务场景：
- 书级 StyleCard：chapter_id=null，一本书一张
- 章级覆盖：chapter_id 非 null，覆盖书级（Sudowrite "每章可微调 Style"）
- ContextEngine P0 静态前缀消费 positive_profile + negative_list
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import StyleCard
from backend.repositories.base import BaseRepository, QuerySpec

# 可空清除字段：显式传 None = 清除该值（如对话旋钮拨回「自动」档）。
# 若无此白名单，v is not None 守卫会把清除语义拦下，DB 旧值复活。
# 其余可空字段（style_knobs/locked_keys）的契约是「None=不改，{}=清空」，不走 null 清除。
_NULLABLE_CLEAR = {"dialogue_ratio_target", "paragraph_rhythm"}


class StyleCardRepository(BaseRepository[StyleCard]):
    """文风卡仓储。"""

    model = StyleCard

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_book_card(self, book_id: UUID) -> Optional[StyleCard]:
        """获取书级文风卡（chapter_id=null）。"""
        spec = QuerySpec.create().where(
            StyleCard.book_id == book_id,
            StyleCard.chapter_id.is_(None),
        )
        return await self.find_one(spec=spec)

    async def get_chapter_override(self, chapter_id: UUID) -> Optional[StyleCard]:
        """获取章级文风卡覆盖。"""
        spec = QuerySpec.create().where(StyleCard.chapter_id == chapter_id)
        return await self.find_one(spec=spec)

    async def get_effective_card(
        self,
        book_id: UUID,
        chapter_id: Optional[UUID] = None,
    ) -> Optional[StyleCard]:
        """获取生效的文风卡（章级覆盖优先，回退到书级）。

        蓝图 §4.4：每章可微调 Style，章级非空时覆盖书级。
        """
        if chapter_id:
            override = await self.get_chapter_override(chapter_id)
            if override:
                return override
        return await self.get_book_card(book_id)

    async def list_by_book(self, book_id: UUID) -> List[StyleCard]:
        """列出书籍的所有文风卡（书级 + 所有章级覆盖）。"""
        spec = QuerySpec.create().where(StyleCard.book_id == book_id)
        spec.order(StyleCard.created_at.desc())
        return await self.find_all(spec=spec)

    async def upsert_book_card(self, book_id: UUID, **fields) -> StyleCard:
        """创建或更新书级文风卡。"""
        existing = await self.get_book_card(book_id)
        if existing:
            for k, v in fields.items():
                if hasattr(existing, k) and (v is not None or k in _NULLABLE_CLEAR):
                    setattr(existing, k, v)
            # 设计意图：existing 已在 session 内，setattr 后直接提交即可——
            # BaseRepository.update(item, payload) 需要第二参 payload，传 ORM 实例必 TypeError
            await self._db.commit()
            await self._db.refresh(existing)
            return existing
        # 设计意图：BaseRepository.create(payload: dict) 内部 model(**payload)——
        # 必须传 dict（与 ae2f0c3 修 AuthorSampleRepository 同款），传 ORM 实例必 TypeError
        return await self.create({"book_id": book_id, **fields})

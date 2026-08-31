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
伏笔账本仓储 - 管理伏笔/钩子的生命周期。

职责：
- 管理 PlotLedger 模型的数据库访问
- 提供伏笔的 CRUD 操作
- 支持按书籍、章节、状态等条件查询

业务场景：
- 章节生成时加载相关伏笔
- 伏笔创建、闭合、废弃
- 跨章节伏笔追踪

设计说明：
- 继承 BaseRepository 提供通用 CRUD
- 提供伏笔特有的查询方法（如 get_open_hooks）
- 支持与 MemoryChunk 的关联查询

依赖项：
- backend.models: PlotLedger 模型
"""

from typing import List, Optional, Sequence
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PlotLedger
from backend.repositories.base import BaseRepository, QuerySpec


class PlotLedgerRepository(BaseRepository[PlotLedger]):
    """
    伏笔账本仓储：管理伏笔的生命周期。

    核心方法：
    - get_open_hooks: 获取开放状态的伏笔
    - get_by_book: 获取书籍的所有伏笔
    - get_by_chapter: 获取章节关联的伏笔

    使用示例：
        repo = PlotLedgerRepository(db)
        open_hooks = await repo.get_open_hooks(book_id, before_chapter=10)
    """
    model = PlotLedger

    async def get_open_hooks(
        self,
        book_id: UUID,
        before_chapter: Optional[int] = None,
        include_addressed: bool = False,
        limit: Optional[int] = None,
    ) -> List[PlotLedger]:
        """
        获取开放状态的伏笔。

        Args:
            book_id: 书籍 ID
            before_chapter: 仅返回在该章节之前创建的伏笔
            include_addressed: 是否包含已处理的伏笔（status='addressed'）
            limit: 返回数量限制

        Returns:
            List[PlotLedger]: 符合条件的伏笔列表，按创建章节倒序
        """
        spec = QuerySpec.create().where(
            PlotLedger.book_id == book_id,
            *([PlotLedger.status.in_(["open", "addressed"])] if include_addressed else [PlotLedger.status == "open"])
        )

        if before_chapter is not None:
            spec.where(PlotLedger.created_at_chapter < before_chapter)

        spec.order(PlotLedger.created_at_chapter.desc())

        if limit:
            spec.paginate(limit=limit)

        return await self.find_all(spec=spec)

    async def get_by_book(
        self,
        book_id: UUID,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> List[PlotLedger]:
        """
        获取书籍的所有伏笔。

        Args:
            book_id: 书籍 ID
            status: 按状态过滤（open/closed/dropped）
            skip: 分页偏移
            limit: 分页限制

        Returns:
            List[PlotLedger]: 伏笔列表
        """
        spec = QuerySpec.create(PlotLedger).where(PlotLedger.book_id == book_id)

        if status:
            spec.where(PlotLedger.status == status)

        spec.order(PlotLedger.created_at.desc())
        spec.paginate(skip=skip, limit=limit)

        return await self.find_all(spec=spec)

    async def get_by_chapter(
        self,
        chapter_id: UUID,
    ) -> List[PlotLedger]:
        """
        获取章节关联的伏笔。

        Args:
            chapter_id: 章节 ID

        Returns:
            List[PlotLedger]: 关联的伏笔列表
        """
        spec = QuerySpec.create(PlotLedger).where(
            PlotLedger.chapter_id == chapter_id
        )
        return await self.find_all(spec=spec)

    async def get_by_story_beat(
        self,
        story_beat_id: UUID,
    ) -> List[PlotLedger]:
        """
        获取故事节拍关联的伏笔。

        Args:
            story_beat_id: 故事节拍 ID

        Returns:
            List[PlotLedger]: 关联的伏笔列表
        """
        spec = QuerySpec.create(PlotLedger).where(
            PlotLedger.story_beat_id == story_beat_id
        )
        return await self.find_all(spec=spec)

    async def count_by_status(
        self,
        book_id: UUID,
    ) -> dict[str, int]:
        """
        按状态统计伏笔数量。

        Args:
            book_id: 书籍 ID

        Returns:
            dict[str, int]: 状态到数量的映射
        """
        stmt = (
            select(PlotLedger.status, func.count(PlotLedger.id))
            .where(PlotLedger.book_id == book_id)
            .group_by(PlotLedger.status)
        )
        result = await self.execute(stmt)
        rows = result.all()
        return {status: count for status, count in rows}

    async def get_unresolved_ledger_keys(
        self,
        book_id: UUID,
        chapter_ids: Sequence[UUID],
    ) -> List[str]:
        """
        获取未解决的伏笔 ledger_key 列表（用于检查重复）。

        Args:
            book_id: 书籍 ID
            chapter_ids: 章节 ID 列表

        Returns:
            List[str]: 未解决的 ledger_key 列表
        """
        stmt = (
            select(PlotLedger.ledger_key)
            .where(
                PlotLedger.book_id == book_id,
                PlotLedger.status == "open",
                PlotLedger.chapter_id.in_(chapter_ids),
            )
        )
        result = await self.execute(stmt)
        return list(result.scalars().all())

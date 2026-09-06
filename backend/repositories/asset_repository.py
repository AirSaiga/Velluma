# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""资产与章级绑定旧表的 Repository（Asset/ChapterAsset）——世界设定层 world_* 接管生成上下文后保留维护。"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from backend.models import Asset, ChapterAsset
from backend.repositories.base import BaseRepository

class AssetRepository(BaseRepository[Asset]):
    model = Asset

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_by_book(self, book_id: UUID) -> List[Asset]:
        result = await self._db.execute(
            select(Asset)
            .filter(Asset.book_id == book_id)
            .order_by(Asset.importance_level.desc(), Asset.created_at.desc())
        )
        return list(result.scalars().all())

class ChapterAssetRepository(BaseRepository[ChapterAsset]):
    model = ChapterAsset

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_by_chapter(self, chapter_id: UUID) -> List[ChapterAsset]:
        result = await self._db.execute(
            select(ChapterAsset)
            .options(joinedload(ChapterAsset.asset))
            .filter(ChapterAsset.chapter_id == chapter_id)
        )
        return list(result.scalars().all())

    async def delete_by_chapter(self, chapter_id: UUID) -> int:
        """清空章节的全部资产关联（PUT /chapters/{id}/assets 空列表 = 清空语义）。

        警示（2026-09-01 审计修复）：旧实现只做 ORM delete 标记、从不 commit——
        非空列表靠路由后续 create() 的 commit 顺带冲刷侥幸生效；空列表（清空
        全部）则无任何提交，请求结束即回滚、静默失效。改单条 bulk DELETE +
        显式 commit（与 BaseRepository 单操作事务惯例一致）。
        """
        from sqlalchemy import delete

        result = await self._db.execute(
            delete(ChapterAsset).where(ChapterAsset.chapter_id == chapter_id)
        )
        await self._db.commit()
        return int(result.rowcount or 0)

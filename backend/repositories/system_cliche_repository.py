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
系统禁词表仓储（Phase 1 CP2.1b 新建）。

职责：SystemCliche 表的数据访问 + 启动时种子化。

业务场景：
- validators.StyleClicheValidator 通过 cliche_provider 读此表（带内存缓存）
- 与 book.style_blacklist（书级）+ style_card.negative_list（书级 StyleCard）三层合并
- severity=blocker 的硬阻断 fail-fast；warning 的仅记日志
"""

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemCliche
from backend.repositories.base import BaseRepository, QuerySpec

logger = logging.getLogger(__name__)


class SystemClicheRepository(BaseRepository[SystemCliche]):
    """系统禁词表仓储。"""

    model = SystemCliche

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_active_patterns(
        self,
        language: Optional[str] = None,
        severity: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[SystemCliche]:
        """获取启用的禁词模式（供 cliche_provider 缓存使用）。

        Args:
            language: 可选语言过滤（zh/en）
            severity: 可选严重性过滤（warning/blocker）
            category: 可选类别过滤（cliche/house_voice/transition）
        """
        spec = QuerySpec.create().where(SystemCliche.enabled.is_(True))
        if language:
            spec.where(SystemCliche.language == language)
        if severity:
            spec.where(SystemCliche.severity == severity)
        if category:
            spec.where(SystemCliche.category == category)
        spec.order(SystemCliche.created_at.asc())
        return await self.find_all(spec=spec)

    async def count_all(self) -> int:
        """统计总数（启动时判断是否需要种子化）。"""
        result = await self._db.execute(
            select(func.count(SystemCliche.id))
        )
        return int(result.scalar() or 0)

    async def seed_if_empty(self, seed_data: List[dict]) -> int:
        """若表为空，从 seed_data 种子化。

        Args:
            seed_data: 种子数据列表，每项是 SystemCliche 字段 dict

        Returns:
            插入的记录数
        """
        count = await self.count_all()
        if count > 0:
            logger.info(f"[SystemCliche] 表已有 {count} 条记录，跳过种子化")
            return 0

        inserted = 0
        for item in seed_data:
            try:
                cliche = SystemCliche(**item)
                self._db.add(cliche)
                inserted += 1
            except Exception as e:
                logger.warning(f"[SystemCliche] 种子化失败 pattern={item.get('pattern')}: {e}")
        if inserted > 0:
            await self._db.commit()
            logger.info(f"[SystemCliche] 已种子化 {inserted} 条默认禁词")
        return inserted

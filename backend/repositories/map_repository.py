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
地图位置仓储模块。

职责：管理书籍中的地点/地图数据，提供 CRUD 操作接口。

业务边界：
- MapLocation: 地点实体（如"长安城"、"新手村"）
- ChapterMapLocation: 章节与地点的关联（一个章节可以涉及多个地点）

设计意图：
- 地点从属于书籍，通过 book_id 关联
- 章节与地点的关联支持"同一章多地点"场景
"""

from typing import List

from uuid import UUID

from backend.models import MapLocation
from backend.repositories.base import BaseRepository, QuerySpec


class MapLocationRepository(BaseRepository[MapLocation]):
    """
    地图位置仓储：管理书籍中的地点实体。

    业务边界：
    - 负责 MapLocation 核心实体的 CRUD
    - 章节-地点关联由 ChapterRepository 或专门服务处理

    事务策略：继承 BaseRepository 的自动提交策略。
    """
    model = MapLocation

    async def list_by_book(self, book_id: UUID) -> List[MapLocation]:
        """查询书籍下所有地点：用于地图管理界面或地点选择器。

        数据流：book_id → WHERE book_id = ? → 按名称排序 → List[MapLocation]
        设计意图：name 排序符合地点列表的常规展示顺序（字母/拼音序）。

        Args:
            book_id: 书籍 UUID

        Returns:
            List[MapLocation]: 按名称排序的地点列表
        """
        spec = QuerySpec.create(MapLocation).where(MapLocation.book_id == book_id).order(MapLocation.name)
        return await self.find_all(spec=spec)

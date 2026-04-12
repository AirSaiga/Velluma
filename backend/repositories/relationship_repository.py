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

from typing import List, Optional

from uuid import UUID

from backend.models import Character, CharacterRelationship
from backend.repositories.base import BaseRepository, QuerySpec


class RelationshipRepository(BaseRepository[CharacterRelationship]):
    """
    角色关系仓储：管理角色之间的关系数据。

    业务边界：关系从属于书籍，通过 source_char_id / target_char_id 关联角色。
    数据模型：有向边设计（A → B），需双向查询获得完整关系图。
    """
    model = CharacterRelationship

    async def list(self, book_id: Optional[UUID] = None) -> List[CharacterRelationship]:
        """查询角色关系列表：支持全局或按书籍过滤。

        逻辑分块：
        - 有 book_id：先 JOIN Character 表过滤书籍，再获取该书所有关系
        - 无 book_id：直接查询所有关系（跨书籍）

        关键数据流：
        book_id → JOIN Character ON source_char_id = Character.id → WHERE Character.book_id = ?
        这确保了"只返回指定书籍内的角色关系"，避免跨书籍数据泄露。

        Args:
            book_id: 可选的书籍 UUID

        Returns:
            List[CharacterRelationship]: 角色关系列表
        """
        if book_id:
            spec = QuerySpec.create().where(Character.book_id == book_id).join_on(
                Character,
                CharacterRelationship.source_char_id == Character.id,
            )
            return await self.find_all(spec=spec)
        return await self.find_all()

    async def list_by_book(self, book_id: UUID) -> List[CharacterRelationship]:
        """按书籍查询角色关系列表。
        
        这是 list 方法的别名，提供更明确的语义。
        
        Args:
            book_id: 书籍 UUID
            
        Returns:
            List[CharacterRelationship]: 角色关系列表
        """
        return await self.list(book_id=book_id)

    async def get_by_pair(self, source_char_id: UUID, target_char_id: UUID) -> Optional[CharacterRelationship]:
        """按角色对查询关系：用于检查两个角色之间是否已存在关系。

        数据流：(source_char_id, target_char_id) → WHERE source=? AND target=? → 0/1 条记录
        警示：这是有向查询，A→B 和 B→A 被视为不同关系；业务层需根据场景确定查询方向。

        Args:
            source_char_id: 源角色 UUID
            target_char_id: 目标角色 UUID

        Returns:
            Optional[CharacterRelationship]: 查询到的关系，不存在则返回 None
        """
        spec = QuerySpec.create().where(
            CharacterRelationship.source_char_id == source_char_id,
            CharacterRelationship.target_char_id == target_char_id,
        )
        return await self.find_one(
            spec=spec
        )

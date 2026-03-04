from uuid import UUID

from backend.models import Character
from backend.repositories.base import BaseRepository, QuerySpec


class CharacterRepository(BaseRepository[Character]):
    """
    角色仓储：管理书籍中的角色实体。

    业务边界：角色从属于书籍，通过 book_id 关联。
    重要字段：importance_level 用于排序，支撑"重要角色优先展示"的产品需求。
    """
    model = Character

    async def list_by_book(self, book_id: UUID):
        """
        按书籍查询角色列表：用于书籍详情页或角色管理界面。

        数据流：book_id → WHERE book_id = ? → 按 importance_level 降序 → List[Character]
        设计意图：importance_level.desc() 确保主角/重要角色排在前面，符合阅读习惯。
        """
        spec = QuerySpec.create().where(Character.book_id == book_id).order(Character.importance_level.desc())
        return await self.find_all(
            spec=spec
        )

    async def list_by_ids(self, ids):
        """
        批量查询角色：用于"已知角色 ID 列表，获取角色详情"场景。

        数据流：ids (list) → WHERE id IN (?, ?, ...) → List[Character]
        边界处理：空列表直接返回空数组，避免无效查询。
        性能考量：IN 查询在大批量（>1000）时可能需分批处理。
        """
        if not ids:
            return []
        return await self.find_all(spec=QuerySpec.create().where(Character.id.in_(ids)))

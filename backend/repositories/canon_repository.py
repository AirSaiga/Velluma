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
Canon 仓储层（V4.0 新建）。

职责：
- CanonNode / CanonEdge 的 CRUD
- 图查询（邻居、路径、悬空 HOOK、按章节筛、按类型筛）
- 软删除现有实体的 ref 关联（通过 metadata.ref_id）

设计依据：docs/generation-v4.0-canon.md §2

业务场景：
- routes/canon.py 的 REST API
- services/canon/ 的提取器、一致性引擎、连锁分析
- workflows/adf/ 的 Phase 0 加载 Canon

使用方式：
    repo = CanonRepository(db)
    nodes = await repo.list_nodes(book_id)
    neighbors = await repo.find_neighbors(node_id, max_depth=2)
"""

import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    CanonNode,
    CanonEdge,
    NODE_TYPE_HOOK,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    VISIBILITY_PARTIAL,
)
from backend.repositories.base import BaseRepository, QuerySpec


class CanonNodeRepository(BaseRepository[CanonNode]):
    """Canon 节点仓储。

    警示：图查询方法（find_neighbors / find_paths）用 SQL 递归 CTE 实现，
    受 PostgreSQL 版本限制（需 PG 8.4+，当前 14+ 满足）。
    """

    model = CanonNode

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_by_book(
        self,
        book_id: UUID,
        node_type: Optional[str] = None,
        visibility: Optional[str] = None,
        tag: Optional[str] = None,
        skip: int = 0,
        limit: int = 500,
    ) -> List[CanonNode]:
        """按书籍列出节点（支持类型/可见性/标签过滤）。"""
        conditions: list = [CanonNode.book_id == book_id]
        if node_type:
            conditions.append(CanonNode.type == node_type)
        if visibility:
            conditions.append(CanonNode.visibility == visibility)
        if tag:
            # JSONB ? 操作符（检查 key 是否存在）。text 参数需显式 cast 避免类型推断错误
            conditions.append(text("tags ? CAST(:tag AS text)").bindparams(tag=tag))
        spec = QuerySpec.create().where(and_(*conditions))
        spec.order(CanonNode.updated_at.desc())
        spec.paginate(skip=skip, limit=limit)
        return await self.find_all(spec=spec)

    async def find_by_label(self, book_id: UUID, label: str) -> Optional[CanonNode]:
        """按 label 精确查找（用于避免重复创建同名节点）。"""
        spec = QuerySpec.create().where(
            and_(
                CanonNode.book_id == book_id,
                CanonNode.label == label,
            )
        )
        spec.paginate(limit=1)
        results = await self.find_all(spec=spec)
        return results[0] if results else None

    async def find_hooks(
        self,
        book_id: UUID,
        status: Optional[str] = None,
        only_open: bool = False,
    ) -> List[CanonNode]:
        """查找伏笔节点（HOOK 类型）。

        Args:
            book_id: 书籍 ID
            status: 限定 status（open/callback/echoed/subverted）
            only_open: 只返回 status=open 的悬空伏笔
        """
        conditions = [
            CanonNode.book_id == book_id,
            CanonNode.type == NODE_TYPE_HOOK,
        ]
        spec = QuerySpec.create().where(and_(*conditions))
        if only_open or status == "open":
            # JSONB 字段查询：metadata->>'status' = 'open'
            spec = spec.where(text("metadata->>'status' = 'open'"))
        elif status:
            spec = spec.where(text("metadata->>'status' = :status").bindparams(status=status))
        spec.order(CanonNode.updated_at.desc())
        return await self.find_all(spec=spec)

    async def find_private_nodes(self, book_id: UUID) -> List[CanonNode]:
        """查找所有 private 节点（一致性检查用：这些不许泄露到正文）。"""
        spec = QuerySpec.create().where(
            and_(
                CanonNode.book_id == book_id,
                CanonNode.visibility == VISIBILITY_PRIVATE,
            )
        )
        return await self.find_all(spec=spec)

    async def find_related_to_chapter(
        self,
        book_id: UUID,
        chapter_number: int,
    ) -> List[CanonNode]:
        """查找与某章相关的节点（appeared_in 包含该章号）。"""
        # JSONB 数组包含整数
        # 警示：asyncpg 会把字符串参数推断为 VARCHAR，导致 `@>` 类型不匹配。
        # 必须用 ::jsonb 显式转换。
        stmt = (
            select(CanonNode)
            .where(
                and_(
                    CanonNode.book_id == book_id,
                    text("appeared_in @> CAST(:chap AS jsonb)").bindparams(
                        chap=json.dumps([chapter_number])
                    ),
                )
            )
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_node_with_edges(self, node_id: UUID) -> Dict[str, Any]:
        """取节点 + 所有相连的边和邻居节点（图谱可视化的核心查询）。"""
        node = await self.get_by_id(node_id)
        if not node:
            return None

        # 取所有相连边
        edge_repo = CanonEdgeRepository(self._db)
        edges = await edge_repo.find_by_node(node_id)
        # 取邻居节点
        neighbor_ids = set()
        for e in edges:
            neighbor_ids.add(e.source_id)
            neighbor_ids.add(e.target_id)
        neighbor_ids.discard(node_id)

        neighbors = []
        if neighbor_ids:
            spec = QuerySpec.create().where(CanonNode.id.in_(list(neighbor_ids)))
            neighbors = await self.find_all(spec=spec)

        return {
            "node": node,
            "edges": edges,
            "neighbors": neighbors,
        }


class CanonEdgeRepository(BaseRepository[CanonEdge]):
    """Canon 边仓储。"""

    model = CanonEdge

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_by_book(
        self,
        book_id: UUID,
        edge_type: Optional[str] = None,
        skip: int = 0,
        limit: int = 1000,
    ) -> List[CanonEdge]:
        """按书籍列出边。"""
        conditions = [CanonEdge.book_id == book_id]
        if edge_type:
            conditions.append(CanonEdge.type == edge_type)
        spec = QuerySpec.create().where(and_(*conditions))
        spec.paginate(skip=skip, limit=limit)
        return await self.find_all(spec=spec)

    async def find_by_node(
        self,
        node_id: UUID,
        edge_type: Optional[str] = None,
    ) -> List[CanonEdge]:
        """取与某节点相关的所有边（出+入）。"""
        conditions = [
            or_(
                CanonEdge.source_id == node_id,
                CanonEdge.target_id == node_id,
            )
        ]
        if edge_type:
            conditions.append(CanonEdge.type == edge_type)
        spec = QuerySpec.create().where(and_(*conditions))
        return await self.find_all(spec=spec)

    async def find_between(
        self,
        source_id: UUID,
        target_id: UUID,
    ) -> List[CanonEdge]:
        """取两节点之间的所有边（不分方向）。"""
        spec = QuerySpec.create().where(
            or_(
                and_(CanonEdge.source_id == source_id, CanonEdge.target_id == target_id),
                and_(CanonEdge.source_id == target_id, CanonEdge.target_id == source_id),
            )
        )
        return await self.find_all(spec=spec)


class CanonRepository:
    """Canon 联合仓储（封装节点 + 边操作）。

    使用场景：业务层不关心节点/边的拆分时，用这个统一入口。
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.nodes = CanonNodeRepository(db)
        self.edges = CanonEdgeRepository(db)

    async def get_book_graph(
        self,
        book_id: UUID,
        node_type: Optional[str] = None,
        visibility: Optional[str] = None,
    ) -> Dict[str, Any]:
        """取整本书的完整图谱（前端可视化的主查询）。

        Returns:
            {"nodes": [...], "edges": [...]}
        """
        nodes = await self.nodes.list_by_book(
            book_id, node_type=node_type, visibility=visibility, limit=2000,
        )
        edges = await self.edges.list_by_book(book_id, limit=5000)
        return {"nodes": nodes, "edges": edges}

    async def find_neighbors(
        self,
        node_id: UUID,
        max_depth: int = 2,
    ) -> Dict[str, Any]:
        """BFS 找邻居（变更连锁分析的核心）。

        Args:
            node_id: 起始节点
            max_depth: 最大跳数（1=直接邻居，2=二阶邻居）

        Returns:
            {"center": node, "nodes": [...], "edges": [...]}
        """
        from collections import deque

        center = await self.nodes.get_by_id(node_id)
        if not center:
            return None

        # BFS
        visited_nodes = {node_id}
        visited_edges = set()
        collected_nodes = []
        collected_edges = []
        queue = deque([(node_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue
            # 取所有相连边
            edges = await self.edges.find_by_node(current_id)
            for e in edges:
                if e.id in visited_edges:
                    continue
                visited_edges.add(e.id)
                collected_edges.append(e)
                # 把邻居加入队列
                neighbor_id = e.target_id if e.source_id == current_id else e.source_id
                if neighbor_id not in visited_nodes:
                    visited_nodes.add(neighbor_id)
                    neighbor = await self.nodes.get_by_id(neighbor_id)
                    if neighbor:
                        collected_nodes.append(neighbor)
                        queue.append((neighbor_id, depth + 1))

        return {
            "center": center,
            "nodes": collected_nodes,
            "edges": collected_edges,
        }

    async def create_node_if_not_exists(
        self,
        book_id: UUID,
        label: str,
        node_type: str,
        canon_text: str = "",
        public_text: str = "",
        visibility: str = VISIBILITY_PUBLIC,
        source: str = "author",
        confidence: str = "confirmed",
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> CanonNode:
        """如果同名节点不存在则创建，否则返回现有节点。

        用于自动提取时避免重复。
        """
        existing = await self.nodes.find_by_label(book_id, label)
        if existing:
            return existing

        payload = {
            "book_id": book_id,
            "type": node_type,
            "label": label,
            "canon_text": canon_text,
            "public_text": public_text,
            "visibility": visibility,
            "source": source,
            "confidence": confidence,
            "metadata_": metadata or {},
            "tags": tags or [],
        }
        return await self.nodes.create(payload)

    async def upsert_edge(
        self,
        book_id: UUID,
        source_id: UUID,
        target_id: UUID,
        edge_type: str,
        strength: int = 5,
        visibility: str = VISIBILITY_PUBLIC,
        note: str = "",
        established_in: Optional[List[int]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CanonEdge:
        """插入或更新边（按 source_id+target_id+type 唯一约束）。

        如果已存在则更新 strength/note，否则新建。
        """
        # 检查是否已存在
        stmt = select(CanonEdge).where(
            and_(
                CanonEdge.source_id == source_id,
                CanonEdge.target_id == target_id,
                CanonEdge.type == edge_type,
            )
        )
        result = await self.db.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            return await self.edges.update(existing, {
                "strength": strength,
                "visibility": visibility,
                "note": note,
                "established_in": established_in or [],
                "metadata_": metadata or {},
            })

        payload = {
            "book_id": book_id,
            "source_id": source_id,
            "target_id": target_id,
            "type": edge_type,
            "strength": strength,
            "visibility": visibility,
            "note": note,
            "established_in": established_in or [],
            "metadata_": metadata or {},
        }
        return await self.edges.create(payload)

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
作者样本仓储（Phase 1 CP2.1b 新建）。

职责：AuthorSample 表的数据访问 + 风格向量检索。

业务场景：
- ContextEngine P0 静态前缀：用本章 outline 做 embedding → 检索 top-k 风格相近样本
- 与 MemoryChunk 的区别：本表是"写作风格检索"，无时间衰减、无 PlotLedger 权重

设计依据：
- 调研报告 §4.3：作者样本 few-shot 是单一最有效去味手段
- 蓝图 §4.3.2 P0 候选 + §5.1 独立表设计
"""

import logging
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AuthorSample
from backend.repositories.base import BaseRepository, QuerySpec

logger = logging.getLogger(__name__)


class AuthorSampleRepository(BaseRepository[AuthorSample]):
    """作者样本仓储。"""

    model = AuthorSample

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_by_book(
        self,
        book_id: UUID,
        scene_type: Optional[str] = None,
    ) -> List[AuthorSample]:
        """列出书籍的所有作者样本。

        Args:
            book_id: 书籍 ID
            scene_type: 可选场景类型过滤（dialogue/action/lyrical/suspense/general）
        """
        spec = QuerySpec.create().where(AuthorSample.book_id == book_id)
        if scene_type:
            spec.where(AuthorSample.scene_type == scene_type)
        spec.order(AuthorSample.created_at.desc())
        return await self.find_all(spec=spec)

    async def search_by_style(
        self,
        embedding: List[float],
        book_id: UUID,
        scene_type: Optional[str] = None,
        limit: int = 3,
    ) -> List[Tuple[AuthorSample, float]]:
        """按风格向量检索相似样本（全局笔迹库批：补位不抢位）。

        复用 MemoryChunk.cosine_distance 模式，但去掉时间衰减与 PlotLedger 权重
        （作者样本是固定样本集，不应受时间影响）。

        候选池 = 本书样本（book_id == X）∪ 全局样本（scope == 'global'，
        含其它书挂进「我的笔迹库」的样本）。排序铁律「本书样本绝对优先」：
        先按归属档（本书=0 / global=1）再按 cosine_distance 升序——本书样本
        再不相似也排在 global 之前，global 只在本书候选不足时补位。
        scene_type 过滤对两档同样生效（与旧口径一致）。

        Args:
            embedding: 查询文本的向量
            book_id: 书籍 ID
            scene_type: 可选场景类型过滤
            limit: 返回数量（默认 3，对应蓝图 P0 候选"作者样本 2-3 段"）

        Returns:
            List[Tuple[AuthorSample, float]]: [(样本, cosine_distance), ...]
            按（归属档, distance）升序
        """
        if not embedding:
            return []

        distance_expr = AuthorSample.embedding.cosine_distance(embedding)
        tier_expr = case((AuthorSample.book_id == book_id, 0), else_=1).label("tier")
        query = (
            select(AuthorSample, distance_expr.label("distance"))
            .where(
                or_(
                    AuthorSample.book_id == book_id,
                    AuthorSample.scope == "global",
                ),
                AuthorSample.embedding.is_not(None),
            )
        )
        if scene_type:
            query = query.where(AuthorSample.scene_type == scene_type)

        query = query.order_by(tier_expr.asc(), distance_expr.asc()).limit(limit)
        result = await self._db.execute(query)
        rows = result.all()
        return [(row[0], float(row[1])) for row in rows]

    async def list_global(
        self,
        exclude_book_id: Optional[UUID | str] = None,
        limit: Optional[int] = None,
    ) -> List[AuthorSample]:
        """列出「我的笔迹库」全局样本（scope == 'global'，全局笔迹库批）。

        取代退役的 list_golden_across_books（旧门票语义：favorite/golden 特权
        已被显式 scope 维度收编——作者标 global 才全库可用）。排除本书行
        （exclude_book_id）：本书自己的样本在 list_by_book 里已出现，合并
        展示/检索候选时不重复计数。
        """
        query = select(AuthorSample).where(AuthorSample.scope == "global")
        if exclude_book_id is not None:
            query = query.where(AuthorSample.book_id != UUID(str(exclude_book_id)))
        query = query.order_by(AuthorSample.created_at.desc())
        if limit is not None:
            query = query.limit(limit)
        result = await self._db.execute(query)
        return list(result.scalars().all())

    async def create_with_embedding(
        self,
        book_id: UUID,
        content: str,
        scene_type: str = "general",
        chapter_id: Optional[UUID] = None,
        source: str = "manual",
        embedding: Optional[List[float]] = None,
        era: str = "recent",
        favorite: bool = False,
        scope: str = "book",
    ) -> AuthorSample:
        """创建作者样本（含可选 embedding）。

        scope：book=仅本书（默认）/ global=我的笔迹库（全库可用）。
        ⚠ adopted_ghost 样本禁止 global——该红线在路由层校验（422），
        仓储层不做重复拦截（内部测试/fixtures 可直接构造）。

        警示：BaseRepository.create 接受 dict payload（内部 commit + refresh），
        直接传 ORM 实例会 TypeError（** 解包要求 mapping）。
        """
        return await self.create({
            "book_id": book_id,
            "chapter_id": chapter_id,
            "scene_type": scene_type,
            "content": content,
            "embedding": embedding,
            "word_count": len(content),
            "source": source,
            "era": era,
            "favorite": favorite,
            "scope": scope,
        })

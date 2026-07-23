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
引爆链仓储（V3.0 新建）。

职责：
- DetonationChain 表的数据访问层
- 供 routes/chapter_generation/detonation.py 的闸门端点调用
- 支持章节→链的一对一查询（含版本回溯）
- Slice B 将在此扩展 PlotLedger 自动落账辅助方法

业务场景：
- 闸门 2（树生长/编辑/确认）：读写 chain 的 payload/nodes/reading_order
- 闸门 3（引爆点写作）：更新 chain.payload.text 与 approved
- SSE 生成：读取已确认的 chain 驱动引线写作

设计说明：
- 继承 BaseRepository 享通用 CRUD
- 一个 chapter 至多一条活跃链（status != done），按 version 降序取最新
- 软删除语义：换引爆点局部重长时 version+1 新建，旧版本保留
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import DetonationChain
from backend.repositories.base import BaseRepository, QuerySpec


class DetonationChainRepository(BaseRepository[DetonationChain]):
    """引爆链仓储。

    核心方法：
    - get_active_by_chapter: 获取章节当前活跃链（status != done 的最新版本）
    - get_latest_by_chapter: 获取章节最新链（含 done）
    - list_versions_by_chapter: 获取章节所有版本（按 version 降序）
    - create_for_chapter: 为章节新建链
    - update_payload / update_tree / update_status: 局部更新

    使用示例：
        repo = DetonationChainRepository(db)
        chain = await repo.get_active_by_chapter(chapter_id)
    """

    model = DetonationChain

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_active_by_chapter(
        self,
        chapter_id: UUID,
    ) -> Optional[DetonationChain]:
        """获取章节当前活跃链（status != done 的最新版本）。

        Args:
            chapter_id: 章节 ID

        Returns:
            DetonationChain 或 None（无活跃链）

        警示：用 find_all(limit=1) 而非 find_one，因为一个章节可能累积
        多条非 done 链（如版本切换中途），find_one 的 scalar_one_or_none
        会因多行抛 MultipleResultsFound。
        """
        spec = QuerySpec.create().where(
            DetonationChain.chapter_id == chapter_id,
            DetonationChain.status != "done",
        )
        spec.order(DetonationChain.version.desc())
        spec.paginate(limit=1)
        results = await self.find_all(spec=spec)
        return results[0] if results else None

    async def get_latest_by_chapter(
        self,
        chapter_id: UUID,
    ) -> Optional[DetonationChain]:
        """获取章节最新链（含 done，按 version 降序取第一条）。

        警示：同 get_active_by_chapter，用 limit(1) 避免多行异常。
        一个章节正常会有多条版本（每次重置/换引爆点 +1），这是预期。
        """
        spec = QuerySpec.create().where(
            DetonationChain.chapter_id == chapter_id,
        )
        spec.order(DetonationChain.version.desc())
        spec.paginate(limit=1)
        results = await self.find_all(spec=spec)
        return results[0] if results else None

    async def list_versions_by_chapter(
        self,
        chapter_id: UUID,
    ) -> List[DetonationChain]:
        """获取章节所有版本（按 version 降序）。"""
        spec = QuerySpec.create().where(
            DetonationChain.chapter_id == chapter_id,
        )
        spec.order(DetonationChain.version.desc())
        return await self.find_all(spec=spec)

    async def create_for_chapter(
        self,
        book_id: UUID,
        chapter_id: UUID,
        payload: dict,
        nodes: Optional[list] = None,
        reading_order: Optional[list] = None,
        status: str = "draft",
        confirmed_by: Optional[str] = None,
        version: int = 1,
        tier: Optional[str] = None,
        tier_reason: Optional[str] = None,
        zones: Optional[dict] = None,
    ) -> DetonationChain:
        """为章节新建引爆链。

        Args:
            book_id: 书籍 ID
            chapter_id: 章节 ID
            payload: PayloadMoment dict
            nodes: SetupNode 列表（首次创建时通常为空，待树生长填充）
            reading_order: 阅读序（同上）
            status: 初始状态
            confirmed_by: 确认方
            version: 版本号（换引爆点局部重长时 +1）
            tier: V3.1 章节定档（climax/turn/progress/transition）
            tier_reason: V3.1 定档理由
            zones: V3.1 三分区映射

        Returns:
            新建的 DetonationChain
        """
        chain = DetonationChain(
            book_id=book_id,
            chapter_id=chapter_id,
            version=version,
            payload=payload,
            nodes=nodes or [],
            reading_order=reading_order or [],
            status=status,
            confirmed_by=confirmed_by,
            tier=tier,
            tier_reason=tier_reason,
            zones=zones or {},
        )
        self._db.add(chain)
        await self._db.commit()
        await self._db.refresh(chain)
        return chain

    async def update_payload(
        self,
        chain: DetonationChain,
        payload: dict,
    ) -> DetonationChain:
        """更新引爆点（PayloadMoment）。"""
        return await self.update(chain, {"payload": payload})

    async def update_tree(
        self,
        chain: DetonationChain,
        nodes: list,
        reading_order: list,
        payload: Optional[dict] = None,
    ) -> DetonationChain:
        """更新铺垫树（节点列表 + 阅读序，可选更新 payload）。"""
        update_fields: dict = {"nodes": nodes, "reading_order": reading_order}
        if payload is not None:
            update_fields["payload"] = payload
        return await self.update(chain, update_fields)

    async def update_status(
        self,
        chain: DetonationChain,
        status: str,
        confirmed_by: Optional[str] = None,
    ) -> DetonationChain:
        """更新链状态。"""
        update_fields: dict = {"status": status}
        if confirmed_by is not None:
            update_fields["confirmed_by"] = confirmed_by
        return await self.update(chain, update_fields)

    async def update_tier(
        self,
        chain: DetonationChain,
        tier: str,
        tier_reason: Optional[str] = None,
    ) -> DetonationChain:
        """更新章节定档（V3.1）。

        业务场景：
        - tier_classifier 决策后写入
        - 用户强制改档时更新
        - 中途升档时调用
        """
        update_fields: dict = {"tier": tier}
        if tier_reason is not None:
            update_fields["tier_reason"] = tier_reason
        return await self.update(chain, update_fields)

    async def update_zones(
        self,
        chain: DetonationChain,
        zones: dict,
    ) -> DetonationChain:
        """更新三分区映射（V3.1）。

        警示：zones 是 JSONB，直接赋值整个 dict 触发 SQLAlchemy 变更检测。
        """
        return await self.update(chain, {"zones": zones})

    async def save_payload_text(
        self,
        chain: DetonationChain,
        text: str,
        approved: bool = True,
    ) -> DetonationChain:
        """保存引爆段成文到 payload.text（闸门 3 冻结）。

        警示：直接修改 chain.payload（JSONB）需要重新赋值整个 dict，
        否则 SQLAlchemy 不会检测到 JSONB 内部变更（mutable 不可追踪）。
        """
        payload_dict = dict(chain.payload or {})
        payload_dict["text"] = text
        payload_dict["approved"] = approved
        return await self.update(chain, {"payload": payload_dict})

    async def save_audit_meta(
        self,
        chain: DetonationChain,
        meta: dict,
    ) -> DetonationChain:
        """保存审计结论到 chain.meta（Slice B 有锚审计用）。"""
        existing_meta = dict(chain.meta or {})
        existing_meta.update(meta)
        return await self.update(chain, {"meta": existing_meta})

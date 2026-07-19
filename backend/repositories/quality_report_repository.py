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
质量报告仓储（Phase 2 CP3.1a 新建）。

职责：QualityReport 表的数据访问层，供双层审计写入与质量报告 API 读取。

业务场景：
- CP3.1b/CP3.1c 审计流程通过本仓储写入 metrics / findings / verdict
- CP3.1c GET /api/chapters/{id}/quality-report 通过 get_by_chapter_run / get_latest 读取
- CP3.2 精修阶段通过 get_latest 读取 findings 作为证据驱动输入

设计说明：
- 一章一次生成 run 至多一份报告（chapter_id + run_id 唯一定位）
- 同一章可能存在多份历史报告（多次审计/rerun），get_latest 返回最新一份
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import QualityReport
from backend.repositories.base import BaseRepository, QuerySpec


class QualityReportRepository(BaseRepository[QualityReport]):
    """质量报告仓储。"""

    model = QualityReport

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def get_by_id(self, report_id: UUID) -> Optional[QualityReport]:
        """按主键查询（重写以去除 BaseRepository 的 getattr 警告语义差异）。"""
        spec = QuerySpec.create().where(QualityReport.id == report_id)
        return await self.find_one(spec=spec)

    async def get_by_chapter_run(
        self,
        chapter_id: UUID,
        run_id: Optional[str] = None,
    ) -> Optional[QualityReport]:
        """按章节 + run 定位审计报告。

        Args:
            chapter_id: 被审计章节 ID
            run_id: 生成 run ID（与 Chapter.generation_run_id 对齐）。
                    传 None 时退化为"该章任意 run 的最新报告"。

        Returns:
            QualityReport 或 None（无报告时）
        """
        spec = QuerySpec.create().where(QualityReport.chapter_id == chapter_id)
        if run_id:
            spec.where(QualityReport.run_id == run_id)
        spec.order(QualityReport.created_at.desc())
        return await self.find_one(spec=spec)

    async def get_latest(self, chapter_id: UUID) -> Optional[QualityReport]:
        """获取该章最新一份质量报告（跨所有 run）。

        典型用途：GET /api/chapters/{id}/quality-report 端点、CP3.2 精修证据加载。
        """
        spec = (
            QuerySpec.create()
            .where(QualityReport.chapter_id == chapter_id)
            .order(QualityReport.created_at.desc())
        )
        return await self.find_one(spec=spec)

    async def list_by_chapter(
        self,
        chapter_id: UUID,
        limit: int = 20,
    ) -> list[QualityReport]:
        """列出该章的历史质量报告（最新在前），供 rerun 历史回溯。"""
        spec = (
            QuerySpec.create()
            .where(QualityReport.chapter_id == chapter_id)
            .order(QualityReport.created_at.desc())
        )
        spec.paginate(limit=limit)
        return await self.find_all(spec=spec)

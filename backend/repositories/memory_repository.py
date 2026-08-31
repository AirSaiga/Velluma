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

import math
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import or_, select

from backend.models import Chapter, MemoryChunk, PlotLedger
from backend.repositories.base import BaseRepository, QuerySpec


def _as_utc(dt: Optional[datetime]) -> datetime:
    """排序键安全归一（2026-09-01 审计修复）：None → tz 感知 epoch 下界；naive → 补 UTC。

    背景：PG/asyncpg 返回 aware datetime、SQLite 返回 naive，排序键里裸用
    `created_at or datetime.min`（naive）会与 aware 值混比较 TypeError——
    单条 NULL created_at 行即触发整次检索 500。归一后两侧路径一致可比。
    """
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class MemoryRepository(BaseRepository[MemoryChunk]):
    """
    记忆块仓储：管理 AI 上下文记忆数据。

    业务边界：记忆块可全局可按书籍/章节隔离，支持多级检索粒度。
    设计意图：created_at.desc() 排序使最新记忆优先，用于"记忆检索"场景下返回最新相关内容。
    """
    model = MemoryChunk

    async def list(self, book_id: Optional[UUID] = None, chapter_id: Optional[UUID] = None):
        """
        条件查询记忆块：支持三种粒度 - 全局、书籍级、章节级。

        逻辑分块：
        1. 初始化空 QuerySpec
        2. 依次添加 book_id 过滤（若提供）
        3. 添加 chapter_id 过滤（若提供）
        4. 按创建时间倒序排列

        关键数据流：
        - book_id + chapter_id 同时存在时：AND 关系，两个条件都满足
        - 两者都为空时：返回全局记忆（跨书籍）
        """
        spec = QuerySpec.create()
        if book_id:
            spec.where(MemoryChunk.book_id == book_id)
        if chapter_id:
            spec.where(MemoryChunk.chapter_id == chapter_id)
        spec.order(MemoryChunk.created_at.desc())
        return await self.find_all(
            spec=spec
        )

    async def search_lexical(
        self,
        book_id: UUID,
        keywords: List[str],
        limit: int = 3,
        exclude_chapter_id: Optional[UUID] = None,
        max_chapter_number: Optional[int] = None,
        candidate_limit: int = 60,
    ):
        """词法检索（默认记忆流，无需 embedding）。

        SQL 预筛：任一关键词 ILIKE 命中 + 防剧透章节过滤（与 search_similar
        同规则，含 chapter_id 为空的旧全局块）；Python 重排：关键词覆盖分
        （lexical.keyword_coverage，单关键词命中封顶）+ 开放伏笔章 +1 加权
        + 新近 tiebreak。embedding 为空的块照常参与（写路径未配置时块文本
        仍落库）。
        """
        from backend.services.rag.lexical import keyword_coverage

        like_conds = [
            MemoryChunk.chunk_text.ilike(f"%{kw}%") for kw in keywords if kw
        ]
        if not like_conds:
            return []

        query = select(MemoryChunk).where(
            MemoryChunk.book_id == book_id,
            or_(*like_conds),
        )
        if max_chapter_number is not None:
            query = query.outerjoin(Chapter, Chapter.id == MemoryChunk.chapter_id).where(
                or_(
                    MemoryChunk.chapter_id.is_(None),
                    Chapter.chapter_number <= max_chapter_number,
                )
            )
        if exclude_chapter_id:
            query = query.where(MemoryChunk.chapter_id != exclude_chapter_id)

        result = await self.execute(query.limit(candidate_limit))
        chunks = list(result.scalars().all())
        if not chunks:
            return []

        # 开放伏笔所在章加权（与向量路径同语义：读者在等的章优先唤醒）
        chapter_ids = {c.chapter_id for c in chunks if c.chapter_id}
        ledger_chapter_ids: set = set()
        if chapter_ids:
            plot_stmt = select(PlotLedger.chapter_id).where(
                PlotLedger.book_id == book_id,
                PlotLedger.chapter_id.in_(chapter_ids),
                PlotLedger.status == "open",
            )
            ledger_chapter_ids = set((await self.execute(plot_stmt)).scalars().all())

        def _rank_key(chunk: MemoryChunk):
            score = keyword_coverage(chunk.chunk_text or "", keywords)
            if chunk.chapter_id in ledger_chapter_ids:
                score += 1.0
            return (score, _as_utc(chunk.created_at))

        return sorted(chunks, key=_rank_key, reverse=True)[:limit]

    async def search_similar(
        self,
        embedding: List[float],
        book_id: UUID,
        limit: int = 5,
        alpha: float = 0.6,
        beta: float = 0.2,
        gamma: float = 0.2,
        lambda_decay: float = 0.1,
        exclude_chapter_id: Optional[UUID] = None,
        max_chapter_number: Optional[int] = None,
    ):
        from backend.services.generation.memory_scorer import compute_memory_score

        candidate_limit = max(limit * 3, limit)
        distance_expr = MemoryChunk.embedding.cosine_distance(embedding)
        
        query = select(MemoryChunk, distance_expr.label("distance")).where(
            MemoryChunk.book_id == book_id, 
            MemoryChunk.embedding.is_not(None)
        )

        if max_chapter_number is not None:
            query = query.outerjoin(Chapter, Chapter.id == MemoryChunk.chapter_id).where(
                or_(
                    MemoryChunk.chapter_id.is_(None),
                    Chapter.chapter_number <= max_chapter_number,
                )
            )
        
        if exclude_chapter_id:
            query = query.where(MemoryChunk.chapter_id != exclude_chapter_id)
            
        stmt = query.order_by(distance_expr).limit(candidate_limit)
        
        result = await self.execute(stmt)
        rows = result.all()
        if not rows:
            return []

        chapter_ids = {chunk.chapter_id for chunk, _ in rows if chunk.chapter_id}
        unresolved_ledger_chapter_ids = set()
        if chapter_ids:
            plot_stmt = select(PlotLedger.chapter_id).where(
                PlotLedger.book_id == book_id,
                PlotLedger.chapter_id.in_(chapter_ids),
                PlotLedger.status == "open",
            )
            plot_result = await self.execute(plot_stmt)
            unresolved_ledger_chapter_ids = set(plot_result.scalars().all())

        now = datetime.now(timezone.utc)
        ranked = []
        for chunk, distance in rows:
            created_at = chunk.created_at or now
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            delta_days = (now - created_at).total_seconds() / 86400
            cosine_similarity = 1 - float(distance)
            plot_weight = 1.0 if chunk.chapter_id in unresolved_ledger_chapter_ids else 0.0
            score = compute_memory_score(
                cosine_similarity=cosine_similarity,
                delta_days=delta_days,
                plot_weight=plot_weight,
                alpha=alpha,
                beta=beta,
                gamma=gamma,
                lambda_decay=lambda_decay,
            )
            ranked.append((score, cosine_similarity, _as_utc(chunk.created_at), chunk))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in ranked[:limit]]

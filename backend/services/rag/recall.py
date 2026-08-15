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
前情向量召回（NLE-ADF 3.0 记忆倒灌·检索侧）。

供续写/连写/点火/零件生发注入"前情回响"：以当前写作上下文为 query，
检索本书更早章节的正文片段。防剧透由 search_similar 的
max_chapter_number=本章-1 + 排除本章保证。

全部失败路径降级为空列表——记忆是增强，不是依赖，绝不阻塞生成。
"""

import logging
from typing import List
from uuid import UUID

from backend.repositories.memory_repository import MemoryRepository
from backend.services.llm.embedding import get_embedding

logger = logging.getLogger(__name__)


async def recall_memories(
    db,
    *,
    book_id: str,
    chapter_id: str,
    chapter_number: int | None,
    query_text: str,
    k: int = 3,
) -> List[str]:
    """召回与当前写作上下文最相关的前情片段（每段截 160 字）。

    Args:
        query_text: 当前写作上下文（当前段落尾部/衔接前缀/大纲等）
        k: 返回条数上限
    """
    query = (query_text or "").strip()
    if len(query) < 8 or not book_id:
        return []
    try:
        embedding = await get_embedding(query[:500])
        if not embedding:
            return []
        repo = MemoryRepository(db)
        chunks = await repo.search_similar(
            embedding,
            UUID(book_id),
            limit=k,
            exclude_chapter_id=UUID(chapter_id) if chapter_id else None,
            max_chapter_number=(chapter_number - 1) if chapter_number else None,
        )
        return [(c.chunk_text or "")[:160] for c in chunks if c.chunk_text]
    except Exception as e:
        logger.warning(f"[recall] 前情召回失败（降级为空）: {e}")
        return []

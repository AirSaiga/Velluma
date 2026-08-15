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
章级记忆索引（NLE-ADF 3.0 记忆倒灌·写入侧）。

设计要点：
- 章级替换语义：先删该章全部旧块，再从画布正文重切重写——幂等，
  重复完稿/修改后重索引不产生重复块，画布即事实源。
- 索引只挂在章级时刻（完稿/发布）：检索侧有防剧透过滤（max_chapter_number=本章-1），
  本章记忆在本章写作中永不被检索，段落级索引没有价值。
- 降级：embedding 未配置/失败时跳过该片（记日志），绝不让完稿流程失败。
"""

import logging
import re
from typing import Optional
from uuid import UUID

from sqlalchemy import delete

from backend.models import MemoryChunk
from backend.services.llm.embedding import get_embedding, is_embedding_configured

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1000


def _html_to_plain(text: str) -> str:
    """画布正文是 HTML（编辑器 getHTML 落库），索引前转纯文本。"""
    plain = re.sub(r"<[^>]+>", "\n", text)
    # 折叠多余空行（每段之间至多一个空行）
    return re.sub(r"\n{3,}", "\n\n", plain).strip()


async def index_chapter_memories(
    db,
    *,
    book_id: str,
    chapter_id: str,
    chapter_number: Optional[int],
    text: str,
) -> int:
    """把一章正文切片写入向量记忆（章级替换）。返回写入块数。

    Args:
        db: AsyncSession
        book_id / chapter_id: 字符串形式 UUID
        chapter_number: 章号（仅用于块文本前缀，可空）
        text: 章节正文（HTML 或纯文本均可，内部转纯文本）
    """
    plain = _html_to_plain(text or "")
    if not plain:
        return 0

    # 章级替换：清空旧块（含 BS-ADF Loop 3 可能写过的旧块）
    await db.execute(delete(MemoryChunk).where(MemoryChunk.chapter_id == UUID(chapter_id)))

    chunks = [
        plain[i:i + _CHUNK_SIZE]
        for i in range(0, len(plain), _CHUNK_SIZE)
        if plain[i:i + _CHUNK_SIZE].strip()
    ]
    label = f"第{chapter_number}章" if chapter_number else "未名章"
    created = 0
    # embedding 未配置 → 跳过向量化调用（块文本照存，喂词法默认流）
    embedding_enabled = is_embedding_configured()
    for idx, chunk in enumerate(chunks):
        try:
            embedding = await get_embedding(chunk[:2000]) if embedding_enabled else None
            db.add(MemoryChunk(
                book_id=UUID(book_id),
                chapter_id=UUID(chapter_id),
                chunk_text=f"【{label} 片段{idx + 1}】{chunk}",
                embedding=embedding if embedding else None,
            ))
            created += 1
        except Exception as e:
            logger.warning(f"[memory_indexing] 片段 {idx + 1} 索引失败（跳过）: {e}")
    await db.commit()
    return created

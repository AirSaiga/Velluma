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
前情召回（NLE-ADF 3.0 记忆倒灌·检索侧）——默认流始终打底 + 向量流增强叠加。

供续写/连写/点火/细纲扩写/零件生发注入"前情回响"。防剧透统一由
chapter 过滤保证（max_chapter_number=本章-1 + 排除本章）。

三层按质量序合并（merge_echoes 去重截 k）：
- A 结构化前情（默认流·始终）：世界事件 × 叙事时刻 × 查询中在场实体，
  零依赖精确召回，格式化为【前情事件】
- V 向量增强（专业级，embedding 已配置时叠加）：DashScope 向量召回
  （余弦 + PlotLedger 加权 + 新近度）
- B 词法检索（默认流·始终补足）：jieba 关键词 × memory_chunks 纯文本
  （块文本在未配置 embedding 时也落库）

设计约束：配置 embedding **不替换**默认流——A/B 恒在，向量只是增强层
（配置用户同样吃到结构化前情与词法兜底）。
全部失败路径降级为空列表——记忆是增强，不是依赖，绝不阻塞生成。
"""

import logging
from typing import List, Sequence
from uuid import UUID

from backend.repositories.memory_repository import MemoryRepository
from backend.services.llm.embedding import get_embedding, is_embedding_configured
from backend.services.rag.lexical import extract_keywords, format_event_echo

logger = logging.getLogger(__name__)

# 结构化前情（世界事件）最多注入条数——精确但更"干"，少量即可
_WORLD_ECHO_LIMIT = 3
# 查询中匹配的世界实体上限（防长文本全员命中）
_MATCHED_ENTITY_LIMIT = 4


def merge_echoes(groups: Sequence[List[str]], k: int) -> List[str]:
    """按组序合并召回结果：保序去重（组间质量序 A→V→B），过滤空串，截 k。"""
    seen: set = set()
    out: List[str] = []
    for group in groups:
        for e in group:
            if e and e not in seen:
                seen.add(e)
                out.append(e)
    return out[:k]


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

    # ---- A 结构化前情（默认流·始终）：世界页事件按叙事时刻精确召回 ----
    a_echoes: List[str] = []
    try:
        a_echoes = await _world_echoes(
            db, book_id=book_id, chapter_id=chapter_id,
            query_text=query, limit=min(_WORLD_ECHO_LIMIT, k),
        )
    except Exception as e:
        logger.warning(f"[recall] 世界事件前情失败（跳过）: {e}")

    # ---- V 向量增强（专业级：embedding 已配置时叠加，不替换默认流）----
    v_echoes: List[str] = []
    try:
        if is_embedding_configured():
            v_echoes = await _vector_echoes(
                db, query=query, book_id=book_id, chapter_id=chapter_id,
                chapter_number=chapter_number, k=k,
            )
    except Exception as e:
        logger.warning(f"[recall] 向量召回失败（跳过）: {e}")

    # ---- B 词法检索（默认流·始终补足）：关键词命中 memory_chunks 纯文本 ----
    b_echoes: List[str] = []
    keywords = extract_keywords(query, top_k=8)
    if keywords:
        try:
            chunks = await MemoryRepository(db).search_lexical(
                UUID(book_id),
                keywords,
                limit=k,
                exclude_chapter_id=UUID(chapter_id) if chapter_id else None,
                max_chapter_number=(chapter_number - 1) if chapter_number else None,
            )
            b_echoes = [(c.chunk_text or "")[:160] for c in chunks if c.chunk_text]
        except Exception as e:
            logger.warning(f"[recall] 词法召回失败（跳过）: {e}")

    return merge_echoes([a_echoes, v_echoes, b_echoes], k)


async def _vector_echoes(db, *, query, book_id, chapter_id, chapter_number, k) -> List[str]:
    """向量召回（专业级增强层）：query 向量化 → search_similar 加权排序。"""
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


async def _world_echoes(db, *, book_id, chapter_id, query_text, limit) -> List[str]:
    """结构化前情：查询中出现的世界实体，其叙事时刻之前的事件（倒序取近）。"""
    from backend.models import Chapter
    from backend.repositories.world_repository import WorldRepository
    from backend.services.context.world_bridge import resolve_narrative_time

    if not chapter_id:
        return []
    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    if not entities:
        return []

    # 查询中出现的实体（名/别名子串匹配；封顶防长文本全员命中）
    matched = []
    for ent in entities:
        names = [ent.name or ""] + [str(a) for a in (getattr(ent, "aliases", None) or [])]
        if any(n and n in query_text for n in names):
            matched.append(ent)
            if len(matched) >= _MATCHED_ENTITY_LIMIT:
                break
    if not matched:
        return []

    chapter = await db.get(Chapter, UUID(chapter_id))
    if chapter is None:
        return []
    t = await resolve_narrative_time(db, chapter)

    events = await repo.events.list_all_by_book(book_id)
    matched_ids = {str(e.id) for e in matched}
    name_by_id = {str(e.id): (e.name or "") for e in matched}
    relevant = []
    for ev in events:
        if ev.time_start is None or ev.time_start > t:
            continue
        hit = matched_ids & {str(p) for p in (ev.participant_ids or [])}
        if hit:
            relevant.append((ev, hit))
    relevant.sort(key=lambda x: (x[0].time_start or 0), reverse=True)

    out = []
    for ev, hit in relevant[:limit]:
        names = [name_by_id[i] for i in sorted(hit) if i in name_by_id]
        out.append(format_event_echo(ev.event_type, names, ev.note or "", ev.time_start))
    return out

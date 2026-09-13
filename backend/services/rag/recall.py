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

# A3a 截断常量收敛（docs/foundation-hardening.md §4.1）：回响剂量改引 budget 表
# （原模块内私有常量 _WORLD_ECHO_LIMIT / _MATCHED_ENTITY_LIMIT 收编为
#  ECHOES_WORLD_MAX_ENTRIES / ECHOES_MATCHED_ENTITY_MAX，值不变）
from backend.services.context.budget import (
    ECHOES_EMBED_QUERY_MAX_CHARS,
    ECHOES_K_STITCH,
    ECHOES_MATCHED_ENTITY_MAX,
    ECHOES_MAX_CHARS,
    ECHOES_WORLD_MAX_ENTRIES,
)

logger = logging.getLogger(__name__)


# ---- A 流相关性门（2026-09-11 排毒批「前情强买强卖」）----
# 结构化前情按实体名命中召回，天然只保证「同一人」不保证「同一件事」——
# 全书仅一条玄幻黑历史时，温馨做饭段落也会被注入 + prompt 又要求呼应件，
# 逼模型硬塞。门阀：事件与当前段落的 jieba 共享词（≥2 字）≥2 个，或占比
# ≥0.3——实体名单命中天然贡献 1 个共享词，门槛实际要求**事件词面上还有
# 第二个当下语境的词**（发电机坏了 vs 正在修发电机 ✓；血噬融合坠落 vs
# 洗脸做饭 ✗）。纯确定性，jieba 缺失时退「不过滤」（保底供给不误杀）。
_ECHO_SHARED_TOKEN_MIN = 2
_ECHO_SHARED_RATIO = 0.3

# ---- B3 检索分流去敏（2026-09-13 深水区批）----
# 高频主角名在向量/词法空间霸屏：query 里「林尘」的字面权重把检索拽向
# 「所有含此名的远古段落」（实测「血噬融合」类远古创伤在生活流段落反复
# 霸屏），动作/场景语境词权重被稀释。去敏**只作用于 V/B 流**——A 流
# （结构化事件）的召回机制恰是「实体名子串命中」，抹名=全灭，A 流吃原文
# 是红线；实体驱动的召回由 A 流独占，V/B 转向动作/场景语境。
# 相似度阈值先行 shadow：只记录分布不拦截（0.70 占位——语义扫描 0.78
# 未校准的前车之鉴），攒真实分布后再转 live。
MEMORY_SIM_THRESHOLD_SHADOW = 0.70


def mask_entity_names(text: str, names) -> str:
    """检索 query 去实体化（纯函数）：最长优先子串替换（同长按集合序稳定）。

    红队 Q3 曾建议 jieba token 边界防「流光石」嵌词误伤——实测 token 方案
    会漏掉粘连名（「明兰叹了口气」切不出独立的「明兰」token，霸屏治不了），
    而嵌词过抹只损一个检索词且不进 prompt（只喂向量/关键词），两害相权取
    彻底抹除：确定性、零依赖、逐字可测。"""
    ns = sorted(
        {str(n).strip() for n in (names or []) if len(str(n).strip()) >= 2},
        key=len,
        reverse=True,
    )
    if not ns or not (text or "").strip():
        return text
    masked = text
    for n in ns:
        masked = masked.replace(n, "")
    return masked


def bundle_mask_names(bundle) -> List[str]:
    """去敏名单收集（B3）：书级专名表 + 实体/资产注册别名（≥2 字；world
    桥适配器的 aliases 挂在 character 命名空间，legacy 对象在顶层）。名单
    宁全勿缺——query 里不出现的名抹除是零操作。"""
    names: List[str] = []
    try:
        pn = bundle.proper_nouns()
        names += [str(n) for n in (pn or [])]
    except Exception:
        pass

    def _aliases(e) -> List[str]:
        al = getattr(e, "aliases", None)
        if al is None:
            ch = getattr(e, "character", None)
            al = getattr(ch, "aliases", None) if ch is not None else None
        if al is None and isinstance(e, dict):
            al = e.get("aliases")
        return [str(a).strip() for a in (al or []) if len(str(a).strip()) >= 2]

    for src in (getattr(bundle, "entities", None) or [], getattr(bundle, "assets", None) or []):
        for e in src:
            names.extend(_aliases(e))
    return names


def echo_is_relevant(event_text: str, query_text: str) -> bool:
    """A 流回响相关性判据（纯函数，测试对拍口径）。"""
    ev = (event_text or "").strip()
    q = (query_text or "").strip()
    if not ev or not q:
        return False
    try:
        import jieba

        ev_tokens = {t for t in jieba.lcut(ev) if len(t) >= 2}
        q_tokens = {t for t in jieba.lcut(q) if len(t) >= 2}
    except Exception:
        return True  # 分词器缺席：宁多勿漏（记忆是增强不是依赖）
    shared = ev_tokens & q_tokens
    if not ev_tokens:
        return True
    return len(shared) >= _ECHO_SHARED_TOKEN_MIN or (
        len(shared) / len(ev_tokens)
    ) >= _ECHO_SHARED_RATIO


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
    k: int = ECHOES_K_STITCH,
    mask_names: Sequence[str] | None = None,
) -> List[str]:
    """召回与当前写作上下文最相关的前情片段（每段截 160 字）。

    Args:
        query_text: 当前写作上下文（当前段落尾部/衔接前缀/大纲等）
        k: 返回条数上限
        mask_names: 在场实体名+别名（B3 去敏名单）——**只抹 V/B 流**，
            A 流（结构化事件）吃原文：实体名子串命中是它的召回机制（红线）。
    """
    query = (query_text or "").strip()
    if len(query) < 8 or not book_id:
        return []
    # B3 分流去敏：V/B 吃去敏 query（防高频主角名霸屏向量/词法检索）
    masked_query = mask_entity_names(query, mask_names) if mask_names else query

    # ---- A 结构化前情（默认流·始终）：世界页事件按叙事时刻精确召回 ----
    # 相关性门（2026-09-11）：实体名命中≠语境相关，不相关事件进 prompt 会
    # 逼模型硬塞呼应（强买强卖事故）；无及格事件允许 A 流为空
    a_echoes: List[str] = []
    try:
        a_raw = await _world_echoes(
            db, book_id=book_id, chapter_id=chapter_id,
            query_text=query, limit=min(ECHOES_WORLD_MAX_ENTRIES, k),
        )
        a_echoes = [e for e in a_raw if echo_is_relevant(e, query)]
    except Exception as e:
        logger.warning(f"[recall] 世界事件前情失败（跳过）: {e}")

    # ---- V 向量增强（专业级：embedding 已配置时叠加，不替换默认流）----
    v_echoes: List[str] = []
    try:
        if is_embedding_configured():
            v_echoes = await _vector_echoes(
                db, query=masked_query, book_id=book_id, chapter_id=chapter_id,
                chapter_number=chapter_number, k=k,
            )
    except Exception as e:
        logger.warning(f"[recall] 向量召回失败（跳过）: {e}")

    # ---- B 词法检索（默认流·始终补足）：关键词命中 memory_chunks 纯文本 ----
    b_echoes: List[str] = []
    keywords = extract_keywords(masked_query, top_k=8)
    if keywords:
        try:
            chunks = await MemoryRepository(db).search_lexical(
                UUID(book_id),
                keywords,
                limit=k,
                exclude_chapter_id=UUID(chapter_id) if chapter_id else None,
                max_chapter_number=(chapter_number - 1) if chapter_number else None,
            )
            b_echoes = [(c.chunk_text or "")[:ECHOES_MAX_CHARS] for c in chunks if c.chunk_text]
        except Exception as e:
            logger.warning(f"[recall] 词法召回失败（跳过）: {e}")

    return merge_echoes([a_echoes, v_echoes, b_echoes], k)


async def _vector_echoes(db, *, query, book_id, chapter_id, chapter_number, k) -> List[str]:
    """向量召回（专业级增强层）：query 向量化 → search_similar 加权排序。

    B3 shadow（2026-09-13）：记录 top-k 余弦分布与假设阈值下的幸存数，
    不拦截——转 live 时把 shadow 日志换成过滤即可（挂点已在此）。"""
    embedding = await get_embedding(query[:ECHOES_EMBED_QUERY_MAX_CHARS])
    if not embedding:
        return []
    repo = MemoryRepository(db)
    scored = await repo.search_similar(
        embedding,
        UUID(book_id),
        limit=k,
        exclude_chapter_id=UUID(chapter_id) if chapter_id else None,
        max_chapter_number=(chapter_number - 1) if chapter_number else None,
        return_scores=True,
    )
    if scored:
        sims = [round(sim, 3) for _c, _sc, sim in scored]
        survive = sum(1 for s in sims if s >= MEMORY_SIM_THRESHOLD_SHADOW)
        logger.info(
            "[recall-shadow] v-flow top%d sims=%s survivors@%.2f=%d/%d"
            "（shadow 不拦截，攒校准分布）",
            len(sims), sims, MEMORY_SIM_THRESHOLD_SHADOW, survive, len(sims),
        )
    return [(c.chunk_text or "")[:ECHOES_MAX_CHARS] for c, _sc, _sim in scored if c.chunk_text]


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
            if len(matched) >= ECHOES_MATCHED_ENTITY_MAX:
                break
    if not matched:
        return []

    chapter = await db.get(Chapter, UUID(chapter_id))
    if chapter is None:
        return []
    t = (await resolve_narrative_time(db, chapter)).t

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

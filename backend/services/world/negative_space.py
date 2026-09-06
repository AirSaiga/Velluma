# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - reader 域折叠与负空间引擎（B4 · docs/world-kernel-foundation.md §3）
"""读者认知折叠 + 可揭示戏剧资本（Iser Leerstellen 的第一个引擎实现）。

- fold_reader(depictions)：confirmed 呈现关系 → 读者已知主体集合；
  诚实降级（不变量 9）：未回填章节/无呈现证据的主体 = unknown，不猜；
- dramatic_capital(...)：世界真相（私有命题 + 已发生事件） − 读者已知
  − 已排期揭示（reveal 意图）——「此刻可揭示/可暗示的戏剧资本」清单，
  B9 认知浮现三时机之一的数据源。

副作用：无（纯查询/纯函数）。
"""
from __future__ import annotations

from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import WorldDepiction


def fold_reader(depictions: List[Any]) -> Dict[str, Any]:
    """confirmed 呈现 → 读者认知（集体单一心智：读者是一个人）。

    Returns:
        {known_subjects: [f"{type}:{id}"...], by_chapter: {chapter_id: n},
         coverage_note: 回填覆盖说明（诚实降级口径）}
    """
    known: List[str] = []
    by_chapter: Dict[str, int] = {}
    for d in depictions:
        if (getattr(d, "status", "") or "") != "confirmed":
            continue
        key = f"{getattr(d, 'subject_type', '')}:{getattr(d, 'subject_id', '')}"
        if key not in known:
            known.append(key)
        ch = str(getattr(d, "chapter_id", "") or "")
        by_chapter[ch] = by_chapter.get(ch, 0) + 1
    return {
        "known_subjects": known,
        "by_chapter": by_chapter,
        "coverage_note": (
            f"已回填 {len(by_chapter)} 章的呈现关系" if by_chapter
            else "未回填：读者认知为 unknown（呈现关系回填后本域才有内容）"
        ),
    }


async def dramatic_capital(
    db: AsyncSession,
    book_id: UUID | str,
    *,
    t: int,
    perspective_note: str = "",
) -> List[Dict[str, Any]]:
    """可揭示戏剧资本：私有命题 − 读者已知 − 已排期揭示。

    数据面：canon 私有/partial 命题（作者真相，读者未知即资本）；
    已排期揭示（Intent kind=reveal 的 target_ref）排除——已计划的不算
    「可顺手暗示」的自由资本。
    """
    from backend.models import CanonNode
    from backend.repositories.intent_repository import IntentRepository

    bid = book_id if isinstance(book_id, UUID) else UUID(str(book_id))

    # 读者已知（confirmed depictions）
    depictions = (await db.execute(
        select(WorldDepiction).where(
            WorldDepiction.book_id == bid,
            WorldDepiction.status == "confirmed",
        )
    )).scalars().all()
    reader = fold_reader(list(depictions))
    known = set(reader["known_subjects"])

    # 已排期揭示
    scheduled = {
        str(r.get("canon_node_id"))
        for r in await IntentRepository(db).read_merge_reveals(bid)
        if r.get("canon_node_id")
    }

    capital: List[Dict[str, Any]] = []
    nodes = (await db.execute(
        select(CanonNode).where(
            CanonNode.book_id == bid,
            CanonNode.visibility.in_(["private", "partial"]),
        )
    )).scalars().all()
    for node in nodes:
        nid = str(node.id)
        if f"proposition:{nid}" in known:
            continue  # 读者已知，不是资本
        if nid in scheduled:
            continue  # 已排期揭示（reveal 意图管它）
        capital.append({
            "kind": "proposition",
            "canon_node_id": nid,
            "label": node.label or "",
            "hint": (node.reveal_plan or node.public_text or "")[:60],
            "note": perspective_note,
        })
    return capital


async def irony_opportunities(
    db: AsyncSession,
    book_id: UUID | str,
    t: int,
    perspective_entity_ids: List[str],
) -> List[Dict[str, Any]]:
    """反讽机会（B9 三时机之二）：读者已知而视角角色未知的命题清单。

    戏剧反讽的可计算形态——读者知道（Depiction confirmed）、在场者不知道
    （belief 域四值=unknown/unaware），差集即「此刻写出来就是反讽」的原料。
    诚实降级：任一侧数据缺失（无回填/无认知事件）返回空（不猜）。
    """
    from backend.services.world.fold import fold
    from backend.services.world.belief import proposition_status

    bid = book_id if isinstance(book_id, UUID) else UUID(str(book_id))
    out = await fold(db, bid, t=t, domains=("belief", "reader"),
                     perspective_set=perspective_entity_ids)
    reader_known = {
        k.split(":", 1)[1]
        for k in (out["reader"].get("known_subjects") or [])
        if k.startswith("proposition:")
    }
    if not reader_known:
        return []  # 读者侧未回填：诚实降级
    belief_states = out["belief"].get("states") or {}
    if not belief_states:
        return []  # 认知事件未录：差集无意义（全员 unknown 会误报全量反讽）
    opportunities = []
    for prop in reader_known:
        status = proposition_status(prop, perspective_entity_ids, belief_states)
        if status == "unknown":
            opportunities.append({
                "kind": "irony",
                "canon_node_id": prop,
                "note": "读者已知、在场角色不知——此刻的言行可构成反讽",
            })
    return opportunities[:10]

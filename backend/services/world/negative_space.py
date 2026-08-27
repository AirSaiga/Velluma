# Velluma - reader 域折叠与负空间引擎（B4 · docs/world-kernel-foundation.md §3）
# AGPL-3.0
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

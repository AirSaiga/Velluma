# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
存量事件参与者回填工具（约束治理一期 · 数据缺口 B6，2026-09-02）。

背景：历史事件的 participant_ids 常为空（事件先于实体建、或速记时名册为空）
——在场推演因此恒空（词法兜底只能救读面，救不了事实源）。本工具扫全部
世界事件，对 participant_ids 为空的事件用与 event_parser 同源的词法匹配
从 note 里找实体名，产出回填建议。

用法：
    python scripts/backfill_event_participants.py            # dry-run：只打印建议
    python scripts/backfill_event_participants.py --apply    # 显式写入（幂等：已非空的事件跳过）

红线：dry-run 是默认——append-only 事实源的写入永远显式。写入只补
participant_ids，不动 note/payload/时间。每条建议打印来源 note 原文供人工
过目（这就是 B6 验收闸的人工过目面）。

运行：.venv/Scripts/python.exe scripts/backfill_event_participants.py [--apply]
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


async def _main(apply: bool) -> int:
    from backend.database import AsyncSessionLocal
    from backend.models import WorldEntity, WorldEvent
    from backend.services.world.lexical_presence import _norm_note
    from sqlalchemy import select

    changed = scanned = 0
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(WorldEvent))
        events = list(result.scalars().all())
        ents = list((await session.execute(select(WorldEntity))).scalars().all())
        by_book: dict = {}
        for e in ents:
            by_book.setdefault(str(e.book_id), []).append(e)

        for ev in events:
            scanned += 1
            if ev.participant_ids:
                continue
            loc_id = getattr(ev, "location_id", None)
            note = _norm_note(getattr(ev, "note", ""))
            if not loc_id or not note:
                continue
            by_name: dict = {}
            for ent in by_book.get(str(ev.book_id), []):
                names = [str(ent.name or "").strip()]
                names += [str(a).strip() for a in (getattr(ent, "aliases", None) or []) if str(a).strip()]
                for name in names:
                    if len(name) >= 2 and name in note:
                        by_name.setdefault(name, []).append(ent)
            if not by_name:
                continue
            print(f"事件 {ev.id}（seq={ev.sequence_num}）note={str(ev.note)[:60]}")
            hits = []
            ambiguous = False
            for name, cands in by_name.items():
                if len(cands) > 1:
                    # 歧义护栏（P2-7）：同名双实体（如机甲与持有者都叫「流光」）
                    # --apply 也不写，必须先在 world 页改名消歧
                    ambiguous = True
                    print(f"  ⚠ 「{name}」命中 {len(cands)} 个实体（歧义）——跳过，请先在世界页改名消歧")
                    continue
                ent = cands[0]
                print(f"  建议 + participant: {ent.name} ({ent.entity_type}, id={ent.id})")
                hits.append(ent)
            if apply and hits and not ambiguous:
                ev.participant_ids = [str(h.id) for h in hits]
                changed += 1
        if apply:
            await session.commit()
    print(f"\n扫描 {scanned} 条事件；{'已回填' if apply else '建议回填'} {changed} 条。")
    if not apply:
        print("（dry-run 未写库——确认无误后加 --apply 显式写入）")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main("--apply" in sys.argv)))

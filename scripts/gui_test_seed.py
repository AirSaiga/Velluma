# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""GUI 测试造数（web-gui-tester Phase Two 环境准备，一次性脚本）。

在真实 data/velluma.db 里建两本「GUI测试·」前缀的书（与用户书区分，测后可删）：
- 书A 开章卡：无实体；第1/2章有内容（伏笔埋设+哈希预锚），第3章空章（测试目标）
- 书B 问书+裁决：实体/地点/比例尺/事件/真相 + 第1章正文（含轮渡时刻表，哈希预锚）
  + 第2章空章挂 3 条带 evidence 的 pending 候选（键盘裁决测试目标）

哈希预锚 = auto_read_state.hash 与正文指纹一致 → 进章 auto-read 走 unchanged 零 LLM
（第一档测试不烧模型）。运行前提：backend 可并发（WAL），单事务快进快出。
"""
import asyncio
import uuid

import backend.models as m
from backend.db_sqlite import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.adaptive.read_budget import content_fingerprint
from backend.services.rag.memory_indexing import _html_to_plain


def anchor_state(content_html: str) -> dict:
    plain = _html_to_plain(content_html or "").strip()
    return {"hash": content_fingerprint(plain), "last_run_at": "2026-09-18T00:00:00+00:00"}


async def main() -> None:
    engine = build_sqlite_engine("data/velluma.db")
    maker = build_sqlite_sessionmaker(engine)
    await init_db_sqlite(engine, maker)  # 幂等（只补列，不动数据）
    async with maker() as s:
        # ---------- 书A：开章卡 ----------
        book_a = str(uuid.UUID("fe100000-0000-4000-8000-00000000000a"))
        s.add(m.Book(id=book_a, title="GUI测试·开章卡"))
        ch_a1 = str(uuid.UUID("fe100000-0000-4000-8000-00000000a001"))
        ch_a2 = str(uuid.UUID("fe100000-0000-4000-8000-00000000a002"))
        ch_a3 = str(uuid.UUID("fe100000-0000-4000-8000-00000000a003"))
        html_a1 = "<p>第一章程。</p>" + "<p>雪下了一整夜。</p>" * 8
        html_a2 = "<p>第二章。</p>" + "<p>队伍在黎明前出发。</p>" * 8
        s.add(m.Chapter(id=ch_a1, book_id=book_a, chapter_number=1, title="风雪",
                        content_text=html_a1, narrative_time=100, auto_read_state=anchor_state(html_a1)))
        s.add(m.Chapter(id=ch_a2, book_id=book_a, chapter_number=2, title="启程",
                        content_text=html_a2, narrative_time=300, auto_read_state=anchor_state(html_a2)))
        s.add(m.Chapter(id=ch_a3, book_id=book_a, chapter_number=3, title="对峙",
                        content_text="", narrative_time=700))
        for label, exp, pub, canon, plan in [
            ("身世真相", 3, "普通厨娘", "明姐是要塞旧主之女", "审讯时自己说出来"),
            ("凶手身份", 5, "不明", "真凶是副官", "第5章揭露"),
            ("宝藏地点", 7, "传说而已", "宝藏在渡口沉船里", "第7章揭"),
        ]:
            s.add(m.CanonNode(book_id=book_a, type="event", label=label,
                              canon_text=canon, public_text=pub, reveal_plan=plan,
                              visibility="private", source="manual", confidence="settled",
                              expected_reveal_chapter=exp))
        s.add(m.PlotLedger(book_id=book_a, content="北岸的旧钟没有敲响", ledger_key="gui-fs-1",
                           status="open", created_at_chapter=1))
        s.add(m.PlotLedger(book_id=book_a, content="渡口船夫的旧伤", ledger_key="gui-fs-2",
                           status="open", created_at_chapter=2))

        # ---------- 书B：问书 + 键盘裁决 ----------
        book_b = str(uuid.UUID("fe100000-0000-4000-8000-00000000000b"))
        s.add(m.Book(id=book_b, title="GUI测试·问书与裁决", map_scale={
            "refs": [{"ax": 0, "ay": 0, "bx": 100, "by": 0, "days_foot": 2}],  # 50px/天
        }))
        ent_mj = str(uuid.UUID("fe100000-0000-4000-8000-0000000000e1"))
        ent_lc = str(uuid.UUID("fe100000-0000-4000-8000-0000000000e2"))
        loc_a = str(uuid.UUID("fe100000-0000-4000-8000-0000000000c1"))
        loc_b = str(uuid.UUID("fe100000-0000-4000-8000-0000000000c2"))
        ch_b1 = str(uuid.UUID("fe100000-0000-4000-8000-00000000b001"))
        ch_b2 = str(uuid.UUID("fe100000-0000-4000-8000-00000000b002"))
        s.add(m.WorldEntity(id=ent_mj, book_id=book_b, name="明姐", entity_type="character"))
        s.add(m.WorldEntity(id=ent_lc, book_id=book_b, name="林尘", entity_type="character"))
        s.add(m.WorldLocation(id=loc_a, book_id=book_b, name="北岸要塞", coord_x=0, coord_y=0))
        s.add(m.WorldLocation(id=loc_b, book_id=book_b, name="渡口", coord_x=100, coord_y=0))
        html_b1 = ("<p>第一章。明姐把轮渡时刻表钉在了码头的木柱上，纸角被江风掀得直响。</p>"
                   + "<p>她数着船期，等一个不会再来的人。</p>" * 6)
        s.add(m.Chapter(id=ch_b1, book_id=book_b, chapter_number=1, title="码头",
                        content_text=html_b1, narrative_time=650, auto_read_state=anchor_state(html_b1)))
        s.add(m.Chapter(id=ch_b2, book_id=book_b, chapter_number=2, title="夜航",
                        content_text="", narrative_time=700))
        node_b = m.CanonNode(book_id=book_b, type="event", label="明姐的身世",
                             canon_text="明姐是船帮遗孤", public_text="普通厨娘",
                             reveal_plan="", visibility="private", source="manual",
                             confidence="settled", expected_reveal_chapter=6)
        s.add(node_b)
        await s.flush()
        s.add(m.WorldEvent(book_id=book_b, event_type="move", time_start=650, time_end=650,
                           participant_ids=[ent_mj], location_id=loc_a, payload={},
                           note="明姐押粮北上，进驻北岸要塞", sequence_num=1))
        s.add(m.WorldEvent(book_id=book_b, event_type="told", time_start=600, time_end=600,
                           participant_ids=[ent_lc], location_id=None,
                           payload={"subject": ent_lc, "proposition_ref": str(node_b.id)},
                           note="老王把明姐的身世告诉了林尘", sequence_num=2))
        s.add(m.PlotLedger(book_id=book_b, content="不会再来的人是谁", ledger_key="gui-fs-3",
                           status="open", created_at_chapter=1))
        # 键盘裁决目标：第2章挂 3 条带 evidence 的 pending 候选
        for i, (summ, ev) in enumerate([
            ("明姐进驻北岸要塞", "明姐押粮北上，进驻北岸要塞"),
            ("林尘得知身世真相", "老王把明姐的身世告诉了林尘"),
            ("轮渡时刻表钉上木柱", "明姐把轮渡时刻表钉在了码头的木柱上"),
        ]):
            s.add(m.WorldEventCandidate(
                book_id=book_b, chapter_id=ch_b2, source="auto_read", status="pending",
                draft={"event_type": "move", "summary": summ, "time_start": 650,
                       "time_end": 650, "participant_ids": [], "participant_names": [],
                       "unresolved_names": [], "location_id": None, "location_name": "",
                       "note": "正文提及", "evidence": ev},
            ))
        await s.commit()
    await engine.dispose()
    print("seeded: book_a=%s ch_a3=%s | book_b=%s ch_b2=%s" % (book_a, ch_a3, book_b, ch_b2))


asyncio.run(main())

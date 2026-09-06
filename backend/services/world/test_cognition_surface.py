# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 认知浮现三时机测试（B9 · 可见性悖论纪律）
"""反讽差集（读者知/角色不知）+ 诚实降级 + 总开关。"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.world.negative_space import irony_opportunities

BOOK = uuid.UUID("b7000000-0000-4000-8000-0000000000b1")
CH1 = uuid.UUID("b7000000-0000-4000-8000-0000000000c1")
ALICE = "b7000000-0000-4000-8000-0000000000e1"
BOB = "b7000000-0000-4000-8000-0000000000e2"
PROP_KNOWN = "b7000000-0000-4000-8000-0000000000a1"   # 读者知、ALICE 知
PROP_IRONY = "b7000000-0000-4000-8000-0000000000a2"   # 读者知、无人知 → 反讽


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(s, with_reader=True, with_belief=True):
    s.add(m.Book(id=BOOK, title="认知面书"))
    s.add(m.Chapter(id=CH1, book_id=BOOK, chapter_number=1, title="一", narrative_time=10))
    if with_belief:
        s.add(m.WorldEvent(
            book_id=BOOK, sequence_num=1, event_type="told",
            time_start=1, time_end=1,
            payload={"subject": ALICE, "proposition_ref": PROP_KNOWN},
            participant_ids=[ALICE],
        ))
    if with_reader:
        for prop in (PROP_KNOWN, PROP_IRONY):
            s.add(m.WorldDepiction(
                book_id=BOOK, subject_type="proposition", subject_id=prop,
                chapter_id=CH1, mode="told", status="confirmed", source="author",
            ))


class TestIrony(unittest.TestCase):
    def test_irony_diff(self):
        """读者知两命题、ALICE 只知其一 → 差集恰好是反讽命题。"""
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "ir.db")
            try:
                async def run():
                    async with maker() as s:
                        _seed(s)
                        await s.flush()
                        out = await irony_opportunities(s, BOOK, 10, [ALICE, BOB])
                        ids = {o["canon_node_id"] for o in out}
                        self.assertIn(PROP_IRONY, ids)
                        self.assertNotIn(PROP_KNOWN, ids)  # ALICE 知 → 非反讽
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_honest_degradation_without_backfill_or_belief(self):
        """两侧数据各自缺席 → 空且不猜（分开两个库验证）。"""
        for name, kw in (("ir2.db", dict(with_reader=False, with_belief=True)),
                         ("ir3.db", dict(with_reader=True, with_belief=False))):
            with tempfile.TemporaryDirectory() as td:
                engine, maker = _make_stack(Path(td), name)
                try:
                    async def run():
                        async with maker() as s:
                            _seed(s, **kw)
                            await s.flush()
                            self.assertEqual(
                                await irony_opportunities(s, BOOK, 10, [ALICE]), [])
                    asyncio.run(run())
                finally:
                    asyncio.run(engine.dispose())


if __name__ == "__main__":
    unittest.main()

# Velluma - reader 域与负空间测试（B4 · docs/world-kernel-foundation.md §4 不变量 9/11）
# AGPL-3.0
"""读者折叠诚实降级 + 戏剧资本差集 + 启发式回填幂等。"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.world.negative_space import dramatic_capital, fold_reader

BOOK = uuid.UUID("b4000000-0000-4000-8000-0000000000b1")
CH1 = uuid.UUID("b4000000-0000-4000-8000-0000000000c1")
CH2 = uuid.UUID("b4000000-0000-4000-8000-0000000000c2")
N1 = uuid.UUID("b4000000-0000-4000-8000-0000000000a1")  # 私有：守塔人身份
N2 = uuid.UUID("b4000000-0000-4000-8000-0000000000a2")  # 私有：地下金库
N3 = uuid.UUID("b4000000-0000-4000-8000-0000000000a3")  # 已排期揭示


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(s):
    s.add(m.Book(id=BOOK, title="负空间测试书"))
    s.add_all([
        m.Chapter(id=CH1, book_id=BOOK, chapter_number=1, title="一", narrative_time=10),
        m.Chapter(id=CH2, book_id=BOOK, chapter_number=2, title="二", narrative_time=20),
    ])
    s.add_all([
        m.CanonNode(id=N1, book_id=BOOK, type="event", label="守塔人身份",
                    canon_text="守塔人是主角生父", visibility="private"),
        m.CanonNode(id=N2, book_id=BOOK, type="event", label="地下金库",
                    canon_text="灯塔下有金库", visibility="private"),
        m.CanonNode(id=N3, book_id=BOOK, type="event", label="旧约定",
                    canon_text="十年前的约定", visibility="private",
                    expected_reveal_chapter=3, reveal_plan="对峙时坦白"),
    ])
    # N1 在第 1 章被写给读者（confirmed）；candidate 不算
    s.add(m.WorldDepiction(
        book_id=BOOK, subject_type="proposition", subject_id=str(N1),
        chapter_id=CH1, mode="shown", status="confirmed", source="author",
    ))
    s.add(m.WorldDepiction(
        book_id=BOOK, subject_type="proposition", subject_id=str(N2),
        chapter_id=CH1, mode="hinted", status="candidate", source="heuristic",
    ))


class TestNegativeSpace(unittest.TestCase):
    def test_reader_fold_honest_degradation(self):
        depictions = [
            m.WorldDepiction(subject_type="proposition", subject_id="x",
                             chapter_id=CH1, status="confirmed"),
            m.WorldDepiction(subject_type="proposition", subject_id="y",
                             chapter_id=CH1, status="candidate"),
        ]
        reader = fold_reader(depictions)
        self.assertEqual(reader["known_subjects"], ["proposition:x"])  # candidate 不算

    def test_capital_excludes_known_and_scheduled(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "ns.db")
            try:
                async def run():
                    async with maker() as s:
                        _seed(s)
                        await s.flush()
                        capital = await dramatic_capital(s, BOOK, t=20)
                        labels = sorted(c["label"] for c in capital)
                        # N1 已写给读者（known）；N3 已排期揭示（reveal 意图经
                        # read_merge_reveals 的 canon 兜底可见）——只剩 N2
                        self.assertEqual(labels, ["地下金库"])
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_fold_reader_domain_and_idempotent_backfill(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "rd.db")
            try:
                async def run():
                    from sqlalchemy import select as _sel

                    from backend.services.world.fold import fold
                    async with maker() as s:
                        _seed(s)
                        await s.flush()
                        out = await fold(s, str(BOOK), t=20, domains=("reader",), perspective_set=())
                        self.assertIn("proposition:" + str(N1), out["reader"]["known_subjects"])
                        self.assertNotIn("proposition:" + str(N2), out["reader"]["known_subjects"])
                        # 幂等（不变量 11）：同章重复行不产生重复主体
                        s.add(m.WorldDepiction(
                            book_id=BOOK, subject_type="proposition", subject_id=str(N1),
                            chapter_id=CH2, mode="told", status="confirmed", source="author",
                        ))
                        await s.flush()
                        out2 = await fold(s, str(BOOK), t=20, domains=("reader",), perspective_set=())
                        self.assertEqual(
                            out2["reader"]["known_subjects"].count("proposition:" + str(N1)), 1)
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


if __name__ == "__main__":
    unittest.main()

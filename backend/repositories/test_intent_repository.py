# Velluma - Intent 双读往返测试（B2 · docs/world-kernel-construction-plan.md §3）
# AGPL-3.0
"""往返等价 + 幂等迁移 + 去重合并的锁定（迁移风险最高步的护栏）。

配方与 test_world_bridge_presence 同款（内存 SQLite 栈；UUID 带字母防
全数字坑）。等价口径：迁移后 read_merge_hooks 的内容集合 ⊇ 旧表 open 行
内容集合（去重后逐内容相等）；重跑迁移零新增（幂等）。
"""
import asyncio
import unittest
import uuid
from pathlib import Path
import tempfile

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.intent_repository import (
    IntentRepository,
    migrate_legacy_to_intents,
)

BOOK = uuid.UUID("b2000000-0000-4000-8000-0000000000b1")
CH1 = uuid.UUID("b2000000-0000-4000-8000-0000000000c1")


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


def _seed(session):
    session.add(m.Book(id=BOOK, title="意图测试书"))
    session.add(m.Chapter(id=CH1, book_id=BOOK, chapter_number=3, title="第三章"))
    session.add_all([
        m.PlotLedger(
            book_id=BOOK, ledger_key="world-fs-1", entry_type="foreshadow",
            content="北岸的旧灯塔里藏着什么", status="open", created_at_chapter=1,
        ),
        m.PlotLedger(
            book_id=BOOK, ledger_key="world-fs-2", entry_type="expectation",
            content="读者在等主角反击", status="open", created_at_chapter=1,
        ),
        m.PlotLedger(  # 已回收的不迁
            book_id=BOOK, ledger_key="world-fs-3", entry_type="foreshadow",
            content="已回收的伏笔", status="closed", created_at_chapter=1,
        ),
    ])
    session.add(m.CanonNode(
        id=uuid.UUID("b2000000-0000-4000-8000-0000000000a1"),
        book_id=BOOK, type="event", label="守塔人身份",
        canon_text="守塔人是主角生父", visibility="private",
        expected_reveal_chapter=4, reveal_plan="临终坦白",
    ))
    session.add(m.Book(
        id=uuid.UUID("b2000000-0000-4000-8000-0000000000b2"),
        title="期待账本书",
        reader_mirror={"expectations": [
            {"id": "EXP_1", "type": "revenge", "description": "仇人必须付出代价",
             "status": "setup", "current_tension": 8},
        ]},
    ))


class TestIntentMigration(unittest.TestCase):
    def test_roundtrip_idempotent_and_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "intent.db")
            try:
                async def run():
                    async with maker() as s:
                        _seed(s)
                        await s.flush()
                        # 迁移前：双读 = 旧表兜底
                        repo = IntentRepository(s)
                        before = await repo.read_merge_hooks(BOOK)
                        self.assertEqual(
                            sorted(h["content"] for h in before),
                            ["北岸的旧灯塔里藏着什么", "读者在等主角反击"],
                        )
                        # 迁移
                        counts = await migrate_legacy_to_intents(s)
                        self.assertEqual(counts["plot_ledgers"], 2)
                        self.assertEqual(counts["canon_reveal"], 1)
                        self.assertEqual(counts["reader_mirror"], 1)
                        # 迁移后：双读内容集合不变（新表行与旧表行按内容去重）
                        after = await repo.read_merge_hooks(BOOK)
                        self.assertEqual(
                            sorted(h["content"] for h in after),
                            ["北岸的旧灯塔里藏着什么", "读者在等主角反击"],
                        )
                        # 幂等：重跑零新增
                        counts2 = await migrate_legacy_to_intents(s)
                        self.assertEqual(counts2, {"plot_ledgers": 0, "canon_reveal": 0, "reader_mirror": 0})
                        # 揭示合并：距第 3 章 ≤2 的 reveal 可见（canon 兜底 + 新表去重）
                        reveals = await repo.read_merge_reveals(BOOK, chapter_number=3)
                        self.assertEqual(len(reveals), 1)
                        self.assertEqual(reveals[0]["expected_reveal_chapter"], 4)
                        # before_chapter 过滤：第 3 章前埋的可见（created_at_chapter=1）
                        hooks3 = await repo.read_merge_hooks(BOOK, before_chapter=3)
                        self.assertEqual(len(hooks3), 2)
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_fold_intent_domain_wired(self):
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "fold2.db")
            try:
                async def run():
                    from backend.services.world.fold import fold
                    async with maker() as s:
                        _seed(s)
                        await s.flush()
                        await migrate_legacy_to_intents(s)
                        out = await fold(s, str(BOOK), t=10, domains=("intent",), perspective_set=())
                        self.assertIn("hooks", out["intent"])
                        self.assertTrue(any("灯塔" in h["content"] for h in out["intent"]["hooks"]))
                        self.assertEqual(len(out["intent"]["reveals"]), 1)
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


if __name__ == "__main__":
    unittest.main()

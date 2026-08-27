# Velluma - Fold API 内核不变量测试（B1 · docs/world-kernel-foundation.md §4）
# AGPL-3.0
"""不变量 2（折叠纯度）/ 3（模态封闭）/ 4（三轴无默认值）的检验。

用内存 SQLite 栈（与 test_world_bridge_presence 同款配方）跑真实仓储路径；
认知事件家族（told/discover/misbelieve/witness）的存取与往返在 B3 扩展语义
测试，本批锁定 schema 与入口纪律。
"""
import asyncio
import inspect
import unittest
import uuid

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.world.fold import EPISTEMIC_EVENT_TYPES, FOLD_DOMAINS, fold

BOOK = uuid.UUID("e1000000-0000-4000-8000-000000000001")
ENT1 = uuid.UUID("e1000000-0000-4000-8000-0000000000e1")
ENT2 = uuid.UUID("e1000000-0000-4000-8000-0000000000e2")


def _make_stack(tmp_path, name):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


class TestFoldInvariants(unittest.TestCase):
    def test_invariant_4_axes_have_no_defaults(self):
        """不变量 4：叙事 t / domains / perspective_set 显式无默认（签名级检查）。"""
        sig = inspect.signature(fold)
        for name in ("t", "domains", "perspective_set"):
            self.assertIsNotNone(sig.parameters[name].default,
                                 msg=f"{name} 应为必填")
            self.assertTrue(sig.parameters[name].default is inspect.Parameter.empty
                            or sig.parameters[name].default is None and name == "tx_head")
        # t / domains / perspective_set 必须无默认
        for name in ("t", "domains", "perspective_set"):
            self.assertEqual(sig.parameters[name].default, inspect.Parameter.empty,
                             msg=f"{name} 不得有默认值（三轴显式纪律）")

    def test_invariant_3_modal_closure_rejects_unknown_domain(self):
        """模态封闭第一道：非法域名抛错；空 domains 抛错。"""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "a.db")
            try:
                async def run():
                    async with maker() as s:
                        with self.assertRaises(ValueError):
                            await fold(s, str(BOOK), t=10, domains=("dream",), perspective_set=())
                        with self.assertRaises(ValueError):
                            await fold(s, str(BOOK), t=10, domains=(), perspective_set=())
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_invariant_3_actual_only_fold_has_no_other_domains(self):
        """模态封闭第二道：只请求 truth 时，结果不含 belief/intent/reader 键。"""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "b.db")
            try:
                async def run():
                    async with maker() as s:
                        s.add(m.Book(id=BOOK, title="内核测试书"))
                        await s.flush()
                        out = await fold(s, str(BOOK), t=10, domains=("truth",), perspective_set=())
                        self.assertEqual(set(out), {"truth"})
                        self.assertIsInstance(out["truth"], dict)
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_invariant_2_purity_same_input_same_output(self):
        """纯度：同书同 t 连续两次折叠，输出逐字节一致（零时钟/零随机）。"""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _make_stack(Path(td), "c.db")
            try:
                async def run():
                    async with maker() as s:
                        s.add(m.Book(id=BOOK, title="内核测试书"))
                        s.add(m.WorldEntity(id=ENT1, book_id=BOOK, name="林尘", entity_type="character"))
                        s.add(m.WorldEvent(
                            book_id=BOOK, sequence_num=1, event_type="move",
                            time_start=1, time_end=30,
                            payload={"path": [None, str(uuid.uuid4())]},
                            participant_ids=[str(ENT1)],
                        ))
                        await s.flush()
                        a = await fold(s, str(BOOK), t=20, domains=("truth",), perspective_set=())
                        b = await fold(s, str(BOOK), t=20, domains=("truth",), perspective_set=())
                        self.assertEqual(a, b)
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())

    def test_event_v2_columns_present(self):
        """Event v2：time_precision / supersedes 列存在（内存库建表即验证）。"""
        cols = {c.name for c in m.WorldEvent.__table__.columns}
        self.assertIn("time_precision", cols)
        self.assertIn("supersedes", cols)
        edge_cols = {c.name for c in m.WorldEventEdge.__table__.columns}
        self.assertIn("subject_event_id", edge_cols)
        self.assertIn("kind", edge_cols)

    def test_epistemic_family_registered(self):
        self.assertEqual(
            EPISTEMIC_EVENT_TYPES,
            frozenset({"told", "discover", "misbelieve", "witness"}),
        )
        self.assertEqual(FOLD_DOMAINS, ("truth", "belief", "intent", "reader"))


if __name__ == "__main__":
    unittest.main()

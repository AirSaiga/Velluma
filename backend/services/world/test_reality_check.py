# Velluma - provenance 与现实校验测试（B5 · 不变量 5/10）
# AGPL-3.0
"""信封确定性（同参同哈希）+ 脏派生物必须被抓到（注入谎言回查 fold）。"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.world.reality_check import (
    check_entity_claims, envelope, run_reality_check,
)

BOOK = uuid.UUID("b5000000-0000-4000-8000-0000000000b1")
ENT_ALIVE = uuid.UUID("b5000000-0000-4000-8000-0000000000e1")
ENT_DEAD = uuid.UUID("b5000000-0000-4000-8000-0000000000e2")


class TestEnvelope(unittest.TestCase):
    def test_same_params_same_hash_and_versions_stamped(self):
        a = envelope("knowledge_view", ["entity:林尘"], {"t": 10, "s": "x"})
        b = envelope("knowledge_view", ["entity:林尘"], {"s": "x", "t": 10})
        self.assertEqual(a["params_hash"], b["params_hash"])  # 键序无关
        self.assertTrue(a["fold_version"] and a["compiler_version"])
        c = envelope("knowledge_view", ["entity:林尘"], {"t": 11, "s": "x"})
        self.assertNotEqual(a["params_hash"], c["params_hash"])


class TestRealityCheck(unittest.TestCase):
    def test_dirty_derived_view_caught(self):
        """不变量 10：派生物宣称死者在场 → 必须抓到（不沉默）。"""
        truth = {
            "character_states": [
                {"entity_id": str(ENT_ALIVE), "alive": True, "location_id": "L1"},
                {"entity_id": str(ENT_DEAD), "alive": False, "location_id": "L1"},
            ]
        }
        mismatches = check_entity_claims(
            dead_claims=[str(ENT_ALIVE)],   # 谎言：活人标死
            present_claims=[str(ENT_DEAD)],  # 谎言：死者标在场
            world_state=truth,
            names_by_entity_id={str(ENT_ALIVE): [str(ENT_ALIVE)],
                                str(ENT_DEAD): [str(ENT_DEAD)]},
        )
        kinds = {mm["kind"] for mm in mismatches}
        self.assertIn("dead_but_alive", kinds)
        self.assertIn("alive_but_dead", kinds)

    def test_clean_view_no_mismatch_and_unknown_not_lie(self):
        truth = {"character_states": [
            {"entity_id": str(ENT_DEAD), "alive": False, "location_id": "L1"}]}
        mismatches = check_entity_claims(
            dead_claims=[str(ENT_DEAD)],
            present_claims=["查无此人"],  # unknown：诚实降级不判谎
            world_state=truth,
            names_by_entity_id={str(ENT_DEAD): [str(ENT_DEAD)]},
        )
        self.assertEqual(mismatches, [])

    def test_run_reality_check_against_real_fold(self):
        with tempfile.TemporaryDirectory() as td:
            engine = build_sqlite_engine(Path(td) / "rc.db")
            maker = build_sqlite_sessionmaker(engine)
            asyncio.run(init_db_sqlite(engine, maker))
            try:
                async def run():
                    async with maker() as s:
                        s.add(m.Book(id=BOOK, title="校验书"))
                        s.add_all([
                            m.WorldEntity(id=ENT_ALIVE, book_id=BOOK, name="林尘",
                                          entity_type="character"),
                            m.WorldEntity(id=ENT_DEAD, book_id=BOOK, name="红月",
                                          entity_type="character"),
                        ])
                        # 折叠语义：death 只翻转既有状态——先 move 建态再 death
                        s.add(m.WorldEvent(
                            book_id=BOOK, sequence_num=1, event_type="move",
                            time_start=1, time_end=1,
                            payload={"character_ids": [str(ENT_DEAD)]},
                        ))
                        s.add(m.WorldEvent(
                            book_id=BOOK, sequence_num=2, event_type="death",
                            time_start=2, time_end=2,
                            payload={"character_id": str(ENT_DEAD)},
                        ))
                        await s.flush()
                        # 脏视图：把死者标成在场
                        dirty = type("KV", (), {"dead_names": [], "present_names": ["红月", "林尘"]})()
                        out = await run_reality_check(s, str(BOOK), 10, dirty)
                        self.assertGreaterEqual(out["checked"], 2)
                        kinds = {mm["kind"] for mm in out["mismatches"]}
                        self.assertIn("alive_but_dead", kinds)
                        # 干净视图：死者如实标死
                        clean = type("KV", (), {"dead_names": ["红月"], "present_names": ["林尘"]})()
                        out2 = await run_reality_check(s, str(BOOK), 10, clean)
                        self.assertEqual(out2["mismatches"], [])
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


if __name__ == "__main__":
    unittest.main()

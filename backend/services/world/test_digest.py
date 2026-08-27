# Velluma - 冷层 digest 测试（B8 · 门控关闭下机件直测）
# AGPL-3.0
"""事实节纯代码渲染 / ops 解析（宁缺勿残）/ 门控与预算纪律。"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.services.world import digest as dg

BOOK = uuid.UUID("b6000000-0000-4000-8000-0000000000b1")
ENT1 = uuid.UUID("b6000000-0000-4000-8000-0000000000e1")


class TestFactSections(unittest.TestCase):
    def test_render_from_fold_truth(self):
        truth = {"character_states": [
            {"entity_id": str(ENT1), "alive": True, "location_id": "L9"},
        ]}
        sections = dg.render_fact_sections(
            truth,
            entity_names={str(ENT1): "林尘", "L9": "北岸要塞"},
            entity_archives={str(ENT1): "出身车间，认死理，手里总有一本翻旧的书。"},
        )
        self.assertEqual(len(sections), 1)
        sec = sections[0]
        self.assertEqual(sec["section_key"], "entity:林尘")
        self.assertIn("位于北岸要塞", sec["text"])
        self.assertIn("翻旧的书", sec["text"])     # 档案摘录进节
        self.assertEqual(sec["derived"], "code")

    def test_dead_state_and_line_cap(self):
        truth = {"character_states": [
            {"entity_id": str(ENT1), "alive": False, "location_id": ""},
        ]}
        sections = dg.render_fact_sections(truth, {str(ENT1): "红月"}, {})
        self.assertIn("已死亡", sections[0]["text"])


class TestOpsParsing(unittest.TestCase):
    def test_valid_ops_and_noise_dropped(self):
        raw = '{"ops": [{"op": "ADD", "section_key": "suspended", "text": "灯塔之谜未解"}, {"op": "NOOP", "section_key": "tone"}, {"op": "DELETE", "section_key": "arc:旧线"}, {"bad": 1}, {"op": "UPDATE", "section_key": "", "text": "无键丢弃"}]}'
        ops = dg.parse_ops(raw)
        self.assertEqual([o["op"] for o in ops], ["ADD", "NOOP", "DELETE"])

    def test_garbage_returns_empty(self):
        self.assertEqual(dg.parse_ops("模型自由发挥的散文"), [])
        self.assertEqual(dg.parse_ops('{"ops": "不是列表"}'), [])


class TestGateDiscipline(unittest.TestCase):
    def test_disabled_gate_skips_synthesis(self):
        """门控关闭：事实节照常产出，综合节 skipped 带人话原因（kill-safe）。"""
        with tempfile.TemporaryDirectory() as td:
            engine = build_sqlite_engine(Path(td) / "dg.db")
            maker = build_sqlite_sessionmaker(engine)
            asyncio.run(init_db_sqlite(engine, maker))
            try:
                async def run():
                    async with maker() as s:
                        s.add(m.Book(id=BOOK, title="digest 书"))
                        s.add(m.WorldEntity(id=ENT1, book_id=BOOK, name="林尘",
                                            entity_type="character",
                                            props={"background": "车间出身"}))
                        s.add(m.WorldEvent(
                            book_id=BOOK, sequence_num=1, event_type="move",
                            time_start=1, time_end=1,
                            payload={"character_ids": [str(ENT1)]},
                        ))
                        await s.flush()
                        out = await dg.compile_digest(s, BOOK, t=10)
                        self.assertTrue(out["sections"])          # 事实节零 LLM 恒产出
                        self.assertEqual(out["ops_applied"], [])   # 综合节被门挡下
                        self.assertTrue(any("门控未开" in sk for sk in out["skipped"]))
                asyncio.run(run())
            finally:
                asyncio.run(engine.dispose())


if __name__ == "__main__":
    unittest.main()

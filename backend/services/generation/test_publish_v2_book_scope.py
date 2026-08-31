# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""activate_plot_ledgers 书级作用域锁（2026-09-01 全量复审轮）。

背景：ledger_key 的唯一约束是「书内唯一」（uq_plot_ledger_book_key =
book_id + ledger_key），旧实现按 ledger_key 裸查不带书过滤——多书用户
跨书同 key（如 world-fs-1 风格）时发布一章可能误关另一本书的伏笔。
本锁断言：传 book_id 时 find_one 条件必须含书过滤；chapter_publishing
路由侧必须传 book_id。
"""
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace as _Sns
from unittest.mock import patch

import backend.services.generation.publish_v2 as pv


class _FakeRepo:
    def __init__(self, record):
        self.record = record
        self.captured_conditions = []

    async def find_one(self, conditions=None, **kw):
        self.captured_conditions.append(list(conditions or []))
        return self.record

    async def commit(self):
        pass


def _conds_reprs(conds):
    """把 SQLAlchemy BinaryExpression 转成可断言的 (左操作数, 右值) 形式。"""
    out = []
    for c in conds:
        out.append((str(getattr(c, "left", "")), getattr(c, "right", None).value if getattr(c, "right", None) is not None else None))
    return out


class TestPlotLedgerBookScope(unittest.TestCase):
    def test_find_one_carries_book_filter(self):
        async def run():
            fake_llm_json = (
                '{"statuses": [{"ledger_id": "world-fs-1", "status": "executed",'
                ' "evidence_quote": "灯塔里藏着钥匙", "note": "ok"}]}'
            )
            book_id = "b1000000-0000-4000-8000-00000000000b"
            repo = _FakeRepo(_Sns(
                status="open", resolved_in_chapter_id=None, meta={},
                ledger_key="world-fs-1",
            ))
            with patch.object(pv, "call_llm", new=_llm_returning(fake_llm_json)):
                statuses = await pv.activate_plot_ledgers(
                    foreshadow_ops=[{"ledger_id": "world-fs-1", "action": "close", "note": "灯塔，钥匙"}],
                    chapter_text="灯塔的旧日志里藏着一把钥匙，他终于拿到了。",
                    plot_ledger_repository=repo,
                    chapter_id="c1000000-0000-4000-8000-00000000000c",
                    chapter_number=3,
                    book_id=book_id,
                )
            self.assertEqual(statuses[0].status, "executed")
            self.assertTrue(repo.captured_conditions, "应至少发生一次 find_one")
            for conds in repo.captured_conditions:
                pairs = _conds_reprs(conds)
                keys = [p[0] for p in pairs]
                self.assertIn("plot_ledgers.ledger_key", keys, f"条件缺 ledger_key: {pairs}")
                self.assertIn("plot_ledgers.book_id", keys, f"条件缺 book_id 书过滤: {pairs}")
                book_vals = [p[1] for p in pairs if p[0] == "plot_ledgers.book_id"]
                self.assertTrue(all(str(v) == str(book_id) for v in book_vals), f"book_id 值不对: {pairs}")

        asyncio.run(run())

    def test_route_passes_book_id(self):
        """路由侧必须把 chapter.book_id 传进去（静态断言，防接线回退）。"""
        src = (Path(__file__).parents[2] / "routes" / "chapter_publishing.py").read_text(encoding="utf-8")
        self.assertIn("book_id=chapter.book_id", src, "chapter_publishing 未传 book_id 给 activate_plot_ledgers")


def _llm_returning(value):
    """call_llm 替身：调用返回协程（直接给 lambda 会返回非 awaitable 的工厂）。"""
    async def _fn(**kw):
        return value
    return _fn


if __name__ == "__main__":
    unittest.main()

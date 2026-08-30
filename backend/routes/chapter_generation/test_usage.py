# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""B3 · 用量可见单测：generation_runs 聚合（纯函数 + 端点级 stub db）。

覆盖：
- by_stage 拆账正确性（多 stage / None token 降级行按 0 计 / 降序）
- stage 标签映射（登记名 / sentence_fix 前缀 / 未登记原样返回）
- by_date 分桶（UTC 日期 / created_at 为 None 跳过日期桶 / 升序）
- 两端点空数据返回零值结构不 500
- 路由注册路径正确（防手滑改错路径静默 404）
"""
# Velluma - usage route tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
from datetime import datetime
from types import SimpleNamespace

from backend.routes.chapter_generation.usage import (
    aggregate_by_date,
    aggregate_by_stage,
    get_book_adaptive_usage,
    get_chapter_adaptive_usage,
    router as usage_router,
)


def _run(coro):
    """独立 event loop 跑异步（不用 asyncio.run——事件循环策略 _set_called
    污染问题见 workflows/conftest.py 注释，此处同款防御）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _row(stage, prompt=None, completion=None, thinking=None, created_at=None):
    """构造 generation_runs 形状的行（鸭子类型，无需 ORM 实例）。"""
    return SimpleNamespace(
        stage=stage,
        prompt_tokens=prompt,
        completion_tokens=completion,
        thinking_tokens=thinking,
        created_at=created_at,
    )


class _StubResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _StubDb:
    """只实现 execute 的最小 AsyncSession 替身（端点只做 SELECT）。"""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, stmt):
        return _StubResult(self._rows)


class TestAggregateByStage:
    def test_multi_stage_split_and_order(self):
        """多 stage 拆账：total = prompt+completion+thinking，按 total 降序。"""
        rows = [
            _row("adaptive.stitch_ghost.continue", prompt=1000, completion=500, thinking=0),
            _row("adaptive.stitch_ghost.continue", prompt=200, completion=100, thinking=0),
            _row("adaptive.intent_inference", prompt=800, completion=120, thinking=300),
            _row("loop3.emergent_facts", prompt=50, completion=None, thinking=None),
        ]
        totals, by_stage = aggregate_by_stage(rows)

        assert totals["calls"] == 4
        assert totals["prompt_tokens"] == 2050
        assert totals["completion_tokens"] == 720
        assert totals["thinking_tokens"] == 300
        assert totals["total_tokens"] == 2050 + 720 + 300

        # 降序：续写 1800 > 意图反推 1220 > 涌现抽取 50
        assert [e["stage"] for e in by_stage] == [
            "adaptive.stitch_ghost.continue",
            "adaptive.intent_inference",
            "loop3.emergent_facts",
        ]
        stitch = by_stage[0]
        assert stitch["calls"] == 2
        assert stitch["total_tokens"] == 1800

    def test_none_tokens_counted_as_zero(self):
        """降级行（record_degraded 只记 stage 不记用量）token 计 0、calls 计 1。"""
        totals, by_stage = aggregate_by_stage([
            _row("adaptive.dock_generator", prompt=None, completion=None, thinking=None),
        ])
        assert totals == {
            "calls": 1, "prompt_tokens": 0, "completion_tokens": 0,
            "thinking_tokens": 0, "total_tokens": 0,
        }
        assert by_stage[0]["calls"] == 1

    def test_stage_labels(self):
        """登记名 → 中文标签；sentence_fix 前缀 → 残句修复；未登记原样返回。"""
        _, by_stage = aggregate_by_stage([
            _row("adaptive.spine_suggest"),
            _row("sentence_fix.3"),
            _row("some.future_stage"),
        ])
        labels = {e["stage"]: e["label"] for e in by_stage}
        assert labels["adaptive.spine_suggest"] == "谋篇建议"
        assert labels["sentence_fix.3"] == "残句修复"
        assert labels["some.future_stage"] == "some.future_stage"


class TestAggregateByDate:
    def test_daily_buckets_ascending_and_none_skipped(self):
        """UTC 日期分桶升序；created_at 为 None 的行不进日期桶。"""
        rows = [
            _row("a", prompt=10, created_at=datetime(2026, 8, 19, 23, 30)),
            _row("b", prompt=20, created_at=datetime(2026, 8, 20, 1, 0)),
            _row("c", prompt=30, created_at=datetime(2026, 8, 19, 5, 0)),
            _row("d", prompt=40, created_at=None),
        ]
        by_date = aggregate_by_date(rows)
        assert [d["date"] for d in by_date] == ["2026-08-19", "2026-08-20"]
        assert by_date[0]["calls"] == 2
        assert by_date[0]["total_tokens"] == 40
        assert by_date[1]["calls"] == 1
        assert by_date[1]["total_tokens"] == 20

    def test_empty_rows(self):
        assert aggregate_by_date([]) == []


class TestChapterEndpoint:
    def test_aggregates_rows(self):
        rows = [
            _row("adaptive.stitch_ghost.burst", prompt=500, completion=300,
                 created_at=datetime(2026, 8, 19, 10, 0)),
            _row("adaptive.event_scout.settle", prompt=100, completion=50,
                 created_at=datetime(2026, 8, 19, 11, 0)),
        ]
        data = _run(get_chapter_adaptive_usage("ch-1", db=_StubDb(rows)))
        assert data["chapter_id"] == "ch-1"
        assert data["totals"]["calls"] == 2
        assert data["totals"]["total_tokens"] == 950
        assert len(data["by_stage"]) == 2
        assert data["by_stage"][0]["stage"] == "adaptive.stitch_ghost.burst"

    def test_empty_returns_zero_not_500(self):
        """空数据：零值结构，不抛异常（用量视图是镜子不是闸门）。"""
        data = _run(get_chapter_adaptive_usage("no-such-chapter", db=_StubDb([])))
        assert data["totals"] == {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "thinking_tokens": 0, "total_tokens": 0,
        }
        assert data["by_stage"] == []


class TestBookEndpoint:
    def test_daily_trend_and_stage_summary(self):
        rows = [
            _row("adaptive.stitch_ghost.outline", prompt=1000, completion=600,
                 created_at=datetime(2026, 8, 18, 9, 0)),
            _row("adaptive.post_process.critique", prompt=400, completion=100,
                 created_at=datetime(2026, 8, 19, 9, 0)),
            _row("adaptive.post_process.critique", prompt=410, completion=110,
                 created_at=datetime(2026, 8, 19, 15, 0)),
        ]
        data = _run(get_book_adaptive_usage("bk-1", db=_StubDb(rows)))
        assert data["book_id"] == "bk-1"
        assert data["totals"]["calls"] == 3
        assert data["totals"]["prompt_tokens"] == 1810

        critique = next(e for e in data["by_stage"] if e["stage"] == "adaptive.post_process.critique")
        assert critique["label"] == "完稿审阅"
        assert critique["calls"] == 2

        assert [d["date"] for d in data["by_date"]] == ["2026-08-18", "2026-08-19"]
        assert data["by_date"][1]["calls"] == 2
        assert data["by_date"][1]["total_tokens"] == 1020

    def test_empty_returns_zero_not_500(self):
        data = _run(get_book_adaptive_usage("no-such-book", db=_StubDb([])))
        assert data["totals"]["calls"] == 0
        assert data["by_stage"] == []
        assert data["by_date"] == []


class TestRouterWiring:
    def test_paths_registered(self):
        """两端点以 GET 注册在预期路径（防手滑改错路径静默 404；
        APIRoute.path 含 router prefix /api）。"""
        registered = {
            (r.path, frozenset(r.methods or ()))
            for r in usage_router.routes
        }
        assert ("/api/chapters/{chapter_id}/adaptive/usage", frozenset({"GET"})) in registered
        assert ("/api/books/{book_id}/adaptive/usage", frozenset({"GET"})) in registered

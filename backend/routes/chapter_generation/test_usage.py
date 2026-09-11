# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""B3 · 用量可见单测：generation_runs 聚合（纯函数 + 端点级 stub db）。

覆盖：
- by_stage 拆账正确性（多 stage / None token 降级行按 0 计 / 降序）
- stage 标签映射（登记名 / sentence_fix 前缀 / 未登记原样返回）
- stage → 链路（lane）分组与 by_lane 汇总（2026-09-10 真实调用流程对齐）
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
    _STAGE_LABELS,
    _stage_lane,
    aggregate_by_date,
    aggregate_by_lane,
    aggregate_by_model,
    aggregate_by_stage,
    get_book_adaptive_usage,
    get_chapter_adaptive_usage,
    reset_chapter_adaptive_usage,
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


def _row(stage, prompt=None, completion=None, thinking=None, created_at=None,
         model_name=None, cached_tokens=None):
    """构造 generation_runs 形状的行（鸭子类型，无需 ORM 实例）。"""
    return SimpleNamespace(
        stage=stage,
        prompt_tokens=prompt,
        completion_tokens=completion,
        thinking_tokens=thinking,
        cached_tokens=cached_tokens,
        model_name=model_name,
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


class _StubDeleteResult:
    """DELETE 语句的结果替身（只有 rowcount 被消费）。"""

    def __init__(self, rowcount):
        self.rowcount = rowcount


class _StubDeleteDb:
    """DELETE 端点替身：记录收到的语句供断言过滤条件。"""

    def __init__(self, rowcount=0):
        self.rowcount = rowcount
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _StubDeleteResult(self.rowcount)

    async def commit(self):
        pass


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
            "cost": 0.0, "unpriced_tokens": 0,
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

    def test_real_flow_stage_labels(self):
        """真实调用流程全 stage 标签覆盖（2026-09-10 对齐：此前 auto_read
        等未登记 stage 在面板显示原始 id 截断串）。"""
        _, by_stage = aggregate_by_stage([
            _row("adaptive.event_scout.auto_read"),
            _row("adaptive.read_entities"),
            _row("adaptive.spine_suggest.retry"),
            _row("adaptive.canon_watch"),
            _row("loop3.emergent_facts"),
        ])
        labels = {e["stage"]: e["label"] for e in by_stage}
        assert labels["adaptive.event_scout.auto_read"] == "自动阅读·记事"
        assert labels["adaptive.read_entities"] == "自动阅读·认人"
        assert labels["adaptive.spine_suggest.retry"] == "谋篇建议（重试）"
        assert labels["adaptive.canon_watch"] == "矛盾检测"
        assert labels["loop3.emergent_facts"] == "涌现抽取（沉淀）"


class TestAggregateByLane:
    def test_lane_assignment(self):
        """stage → 链路分组：感知/续写/沉淀完稿/自动阅读/其他各归其位。"""
        _, by_stage = aggregate_by_stage([
            _row("adaptive.dock_generator", prompt=10),
            _row("adaptive.stitch_ghost.stitch", prompt=10),
            _row("adaptive.stitch_ghost.compress", prompt=10),
            _row("adaptive.event_scout.settle", prompt=10),
            _row("sentence_fix.0", prompt=10),
            _row("adaptive.spine_suggest", prompt=10),
            _row("adaptive.spine_suggest.retry", prompt=10),
            _row("adaptive.event_scout.auto_read", prompt=10),
            _row("adaptive.read_entities", prompt=10),
            _row("mystery.stage", prompt=10),
        ])
        lanes = {e["stage"]: e["lane"] for e in by_stage}
        assert lanes["adaptive.dock_generator"] == "perceive"
        assert lanes["adaptive.stitch_ghost.stitch"] == "ghost"
        assert lanes["adaptive.stitch_ghost.compress"] == "ghost"
        assert lanes["adaptive.event_scout.settle"] == "settle"
        # 谋篇建议本名与 .retry 后缀都必须归沉淀组（前缀规则带尾点，本名靠 exact——
        # 2026-09-10 真实数据冒烟曾漏 exact 落进「其他」组）
        assert lanes["adaptive.spine_suggest"] == "settle"
        assert lanes["sentence_fix.0"] == "settle"
        assert lanes["adaptive.spine_suggest.retry"] == "settle"
        assert lanes["adaptive.event_scout.auto_read"] == "auto_read"
        assert lanes["adaptive.read_entities"] == "auto_read"
        assert lanes["mystery.stage"] == "other"
        # lane_label 一并携带（前端分组标题直接可用）
        assert next(e for e in by_stage if e["stage"] == "mystery.stage")["lane_label"] == "其他"

    def test_registered_labels_all_have_real_lane(self):
        """两册对齐不变量：凡登记了作者可读标签的 stage，必归入真实链路
        （不留 other）——防「补了标签漏补 lane」的映射漂移。"""
        for stage in _STAGE_LABELS:
            assert _stage_lane(stage) != "other", f"{stage} 有标签但无链路归属"

    def test_by_lane_subtotal_share_and_flow_order(self):
        """by_lane：小计 + 占比；lane 序 = 流程序（感知→续写→沉淀→自动阅读）。"""
        rows = [
            _row("adaptive.dock_generator", prompt=700),          # 感知 700
            _row("adaptive.future_projection", prompt=300),       # 感知 300
            _row("adaptive.stitch_ghost.stitch", prompt=200),     # 续写 200
            _row("adaptive.event_scout.auto_read", prompt=800),   # 自动阅读 800
        ]
        totals, by_stage = aggregate_by_stage(rows)
        by_lane = aggregate_by_lane(by_stage, totals)

        assert [l["lane"] for l in by_lane] == [
            "perceive", "ghost", "auto_read",
        ]  # 流程序而非量序（自动阅读 800 最大仍居末位）
        by_key = {l["lane"]: l for l in by_lane}
        assert by_key["perceive"]["total_tokens"] == 1000
        assert by_key["perceive"]["calls"] == 2
        assert by_key["perceive"]["share"] == 50.0   # 1000/2000
        assert by_key["ghost"]["share"] == 10.0      # 200/2000
        assert by_key["auto_read"]["share"] == 40.0  # 800/2000

    def test_by_lane_empty_and_zero_total(self):
        """空 by_stage → 空 by_lane；total=0 → share=0 不除零。"""
        assert aggregate_by_lane([], {"total_tokens": 0, "calls": 0}) == []
        totals, by_stage = aggregate_by_stage([_row("adaptive.dock_generator")])
        by_lane = aggregate_by_lane(by_stage, totals)
        assert by_lane == [{
            "lane": "perceive", "label": "写作中感知",
            "calls": 1, "total_tokens": 0, "share": 0,
            "cost": 0.0, "unpriced_tokens": 0,
        }]


class TestCostAggregation:
    """成本核算（2026-09-11）：token × 价目表 → 元，含缓存折扣与未计价口径。"""

    PRICES = {
        "model-a": {"input": 2.0, "cached_input": 0.2, "output": 8.0},
        "model-b": {"input": 1.0, "output": 4.0},  # 无 cached_input：命中按全价
    }

    def test_cost_with_cache_discount(self):
        """(prompt−cached)×input + cached×cached_input + (completion+thinking)×output。"""
        _, by_stage = aggregate_by_stage([
            # 1M 输入其中 0.5M 命中 + 0.25M 输出（含思考）
            _row("adaptive.dock_generator", prompt=1_000_000, completion=200_000,
                 thinking=50_000, cached_tokens=500_000, model_name="model-a"),
        ], prices=self.PRICES)
        row = by_stage[0]
        # 0.5×2 + 0.5×0.2 + 0.25×8 = 1 + 0.1 + 2 = 3.1 元
        assert row["cost"] == 3.1
        assert row["unpriced_tokens"] == 0

    def test_unpriced_model_counts_tokens_not_cost(self):
        """未配价模型：cost=0、token 全部计入 unpriced（不冒充零成本）。"""
        totals, by_stage = aggregate_by_stage([
            _row("adaptive.dock_generator", prompt=1000, completion=500, model_name="mystery"),
        ], prices=self.PRICES)
        assert by_stage[0]["cost"] == 0.0
        assert by_stage[0]["unpriced_tokens"] == 1500
        assert totals["cost"] == 0.0
        assert totals["unpriced_tokens"] == 1500

    def test_cached_none_charged_full_price(self):
        """cached_tokens=None（厂商未回报/历史行）→ 按未命中全价（保守）。"""
        _, by_stage = aggregate_by_stage([
            _row("adaptive.dock_generator", prompt=1_000_000, completion=0,
                 cached_tokens=None, model_name="model-a"),
        ], prices=self.PRICES)
        assert by_stage[0]["cost"] == 2.0  # 1M × input 2 元/M，无缓存折扣

    def test_no_cached_price_entry_uses_input(self):
        """价目缺 cached_input → 命中部分按 input 价（model-b）。"""
        _, by_stage = aggregate_by_stage([
            _row("adaptive.dock_generator", prompt=1_000_000, completion=0,
                 cached_tokens=400_000, model_name="model-b"),
        ], prices=self.PRICES)
        assert by_stage[0]["cost"] == 1.0  # 全部按 input 1 元/M

    def test_by_lane_and_by_model_carry_cost(self):
        """by_lane 组头与 by_model 行均带成本；by_model 标 priced。"""
        rows = [
            _row("adaptive.dock_generator", prompt=1_000_000, model_name="model-a"),
            _row("adaptive.stitch_ghost.stitch", prompt=500_000, model_name="mystery"),
        ]
        totals, by_stage = aggregate_by_stage(rows, prices=self.PRICES)
        by_lane = aggregate_by_lane(by_stage, totals)
        perceive = next(l for l in by_lane if l["lane"] == "perceive")
        assert perceive["cost"] == 2.0
        ghost = next(l for l in by_lane if l["lane"] == "ghost")
        assert ghost["cost"] == 0.0
        assert ghost["unpriced_tokens"] == 500_000

        by_model = aggregate_by_model(rows, prices=self.PRICES)
        assert [m["model"] for m in by_model] == ["model-a", "mystery"]
        assert by_model[0]["priced"] is True
        assert by_model[0]["cost"] == 2.0
        assert by_model[1]["priced"] is False
        assert by_model[1]["unpriced_tokens"] == 500_000

    def test_endpoint_cost_with_monkeypatched_prices(self, monkeypatch):
        """端点侧 get_model_prices 实读 model_config.json——测试打桩替换。"""
        import backend.routes.chapter_generation.usage as usage_mod
        monkeypatch.setattr(usage_mod, "get_model_prices", lambda: self.PRICES)
        rows = [
            _row("adaptive.dock_generator", prompt=1_000_000, completion=0,
                 cached_tokens=None, model_name="model-a",
                 created_at=datetime(2026, 9, 11, 10, 0)),
        ]
        data = _run(get_book_adaptive_usage("bk-x", db=_StubDb(rows)))
        assert data["totals"]["cost"] == 2.0
        assert data["by_date"][0]["cost"] == 2.0
        assert data["by_model"][0]["model"] == "model-a"


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
        # 端点带 by_lane（链路汇总）
        assert [l["lane"] for l in data["by_lane"]] == ["ghost", "settle"]

    def test_empty_returns_zero_not_500(self):
        """空数据：零值结构，不抛异常（用量视图是镜子不是闸门）。"""
        data = _run(get_chapter_adaptive_usage("no-such-chapter", db=_StubDb([])))
        assert data["totals"] == {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "thinking_tokens": 0, "total_tokens": 0,
            "cost": 0.0, "unpriced_tokens": 0,
        }
        assert data["by_stage"] == []
        assert data["by_lane"] == []
        assert data["by_model"] == []


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
        assert data["by_lane"] == []
        assert data["by_model"] == []
        assert data["by_date"] == []


class TestResetChapterUsage:
    """DELETE /chapters/{id}/adaptive/usage（测试用清空台账，2026-09-11）。"""

    def test_reset_returns_deleted_count_and_zeroed_shape(self, monkeypatch):
        import backend.services.adaptive.observing as obs

        async def _noop_flush(cid):
            return 0

        monkeypatch.setattr(obs, "flush_adaptive_records", _noop_flush)
        db = _StubDeleteDb(rowcount=7)
        data = _run(reset_chapter_adaptive_usage("ch-9", db=db))
        assert data["chapter_id"] == "ch-9"
        assert data["deleted"] == 7
        assert data["totals"] == {
            "calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
            "thinking_tokens": 0, "total_tokens": 0,
            "cost": 0.0, "unpriced_tokens": 0,
        }
        assert data["by_stage"] == [] and data["by_lane"] == [] and data["by_model"] == []
        # DELETE 过滤条件钉死：只删本章 adaptive 行（防误删其他引擎/其他章）
        stmt = db.statements[0]
        stmt_sql = str(stmt)
        assert "generation_runs" in stmt_sql
        assert "chapter_id" in stmt_sql and "run_id" in stmt_sql
        params = dict(stmt.compile().params)
        assert "adaptive_ch-9" in params.values()

    def test_reset_drains_pending_recorder(self, monkeypatch):
        """内存 recorder 的 pending 记录随清空丢弃——不 drain 的话下次
        heartbeat/settle 的 flush 会把旧账塞回来（复活）。"""
        import backend.services.adaptive.observing as obs
        from backend.services.observability.run_recorder import RunRecorder

        async def _noop_flush(cid):
            return 0

        monkeypatch.setattr(obs, "flush_adaptive_records", _noop_flush)
        ch = "reset-drain-test"
        rec = RunRecorder(chapter_id=ch, run_id=f"adaptive_{ch}")
        rec.record_degraded("adaptive.dock_generator", "test", "skipped")
        assert len(rec.snapshot()) == 1
        obs._RECORDERS[ch] = rec
        try:
            data = _run(reset_chapter_adaptive_usage(ch, db=_StubDeleteDb(rowcount=0)))
            assert data["deleted"] == 0
            assert rec.snapshot() == []  # pending 已被 drain
        finally:
            obs._RECORDERS.pop(ch, None)


class TestRouterWiring:
    def test_paths_registered(self):
        """端点以预期方法注册在预期路径（防手滑改错路径静默 404；
        APIRoute.path 含 router prefix /api）。"""
        registered = {
            (r.path, frozenset(r.methods or ()))
            for r in usage_router.routes
        }
        assert ("/api/chapters/{chapter_id}/adaptive/usage", frozenset({"GET"})) in registered
        assert ("/api/books/{book_id}/adaptive/usage", frozenset({"GET"})) in registered
        assert ("/api/chapters/{chapter_id}/adaptive/usage", frozenset({"DELETE"})) in registered

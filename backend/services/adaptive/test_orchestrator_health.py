# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 调度器健康观测单测（P3 治理，2026-08-25）
"""docs/reports/adaptive-assist-hardening.md P3 · C4/C5 的对拍：

- P3-1（C5）组件失败可见化：异步/同步激活失败记 last_component_errors
  （组件名 + 秒级时间戳 + 一行摘要，不带堆栈），成功即清；
- P3-2（C4）双跑去重：_activate_sync await 到在跑异步任务后，入参签名
  等效（recent_text 签名 + budget 档）→ 复用产出不重跑；不等效 → 维持重跑。

配方同 test_projection_freshness.py：独立 asyncio.run、UUID 带字母、
monkeypatch world_model.WorldRepository（_activate/_activate_sync 的局部
导入按调用时刻取模块属性，patch 模块属性即生效）。
运行：python -m pytest backend/services/adaptive/test_orchestrator_health.py -v
"""

import asyncio
import time
import uuid

import backend.services.adaptive.world_model as wm
from backend.services.adaptive.orchestrator import Activation, AdaptiveOrchestrator

CH_ID = str(uuid.UUID("bb260000-0000-4000-8000-0000000000c1"))


class _FakeRepo:
    """替身 repo：snapshot 恒空 dict（决策/激活路径只透传快照）。"""

    def __init__(self, db):
        pass

    async def snapshot(self, chapter_id):
        return {}


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def commit(self):
        pass


def _orch():
    return AdaptiveOrchestrator(db_factory=lambda: _FakeSession(), chapter_id=CH_ID)


# ============================================================
# P3-1（C5）：失败记录 + 成功清除
# ============================================================

def test_async_failure_recorded_without_traceback(monkeypatch):
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)

    async def boom(chapter_id, db, snap, budget):
        raise RuntimeError("连接超时\nTraceback 行2\nTraceback 行3")

    orch = _orch()
    orch.register_component("dock_generator", boom)

    async def scenario():
        await orch._activate(Activation("dock_generator", "low", 1500))
        await orch._active_tasks["dock_generator"]

    asyncio.run(scenario())
    errs = orch.last_component_errors()
    assert "dock_generator" in errs
    entry = errs["dock_generator"]
    assert "\n" not in entry["error"]          # 单行摘要，堆栈不给作者看
    assert "连接超时" in entry["error"]
    assert abs(entry["ts"] - int(time.time())) < 5   # 秒级时间戳


def test_async_success_clears_prior_error(monkeypatch):
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)

    async def boom(chapter_id, db, snap, budget):
        raise RuntimeError("挂了")

    async def ok(chapter_id, db, snap, budget):
        return {}

    orch = _orch()
    act = Activation("future_projection", "low", 1500)

    async def fail_round():
        orch.register_component("future_projection", boom)
        await orch._activate(act)
        await orch._active_tasks["future_projection"]

    async def ok_round():
        orch.register_component("future_projection", ok)
        await orch._activate(act)
        await orch._active_tasks["future_projection"]

    asyncio.run(fail_round())
    assert "future_projection" in orch.last_component_errors()
    asyncio.run(ok_round())
    assert "future_projection" not in orch.last_component_errors()  # 成功即清


def test_sync_failure_recorded(monkeypatch):
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)

    async def boom(chapter_id, db, snap, budget, **kw):
        raise ValueError("bad input")

    orch = _orch()
    orch.register_component("canon_watch", boom)
    asyncio.run(orch._activate_sync(
        Activation("canon_watch", "low", 0), _FakeSession(),
    ))
    errs = orch.last_component_errors()
    assert errs["canon_watch"]["error"] == "bad input"


def test_last_component_errors_is_copy(monkeypatch):
    """透出的是拷贝——外部改动不污染 per-orchestrator 内存态。"""
    orch = _orch()
    orch._note_component_error("sediment", RuntimeError("x"))
    out = orch.last_component_errors()
    out.clear()
    assert orch.last_component_errors() != out
    assert "sediment" in orch.last_component_errors()


# ============================================================
# P3-2（C4）：_activate_sync 双跑去重
# ============================================================

def test_activate_records_input_signature(monkeypatch):
    """_activate 记录入参签名（recent_text 签名 + budget 档），任务收尾清理。"""
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)
    orch = _orch()
    seen = {}

    async def runner(chapter_id, db, snap, budget, **kw):
        seen["sig"] = orch._active_task_sigs.get("dock_generator")

    orch.register_component("dock_generator", runner)

    async def scenario():
        await orch._activate(Activation("dock_generator", "low", 1500), recent_text="某段文字。")
        await orch._active_tasks["dock_generator"]

    asyncio.run(scenario())
    assert seen["sig"] == orch._component_input_sig("某段文字。", 1500)
    assert "dock_generator" not in orch._active_task_sigs   # 收尾清理


def test_activate_sync_reuses_equivalent_async_run(monkeypatch):
    """await 到的异步任务入参等效 → 复用产出，不重跑（同参数 LLM 双调用消除）。"""
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)
    calls = []

    async def runner(chapter_id, db, snap, budget, **kw):
        calls.append(kw.get("recent_text"))
        return {}

    orch = _orch()
    orch.register_component("dock_generator", runner)
    act = Activation("dock_generator", "low", 1500)

    async def scenario():
        # 在跑异步任务：入参签名 = 同段落 + 同 budget
        orch._active_task_sigs["dock_generator"] = orch._component_input_sig("同一段文字。", 1500)
        orch._active_tasks["dock_generator"] = asyncio.create_task(asyncio.sleep(0.02))
        await orch._activate_sync(
            act, _FakeSession(), extra_context={"recent_text": "同一段文字。"},
        )
        assert calls == []                     # 等效 → 复用，未重跑

        # 签名不等效（段落变了）→ 维持重跑（现状兜底）
        orch._active_task_sigs["dock_generator"] = orch._component_input_sig("旧段落。", 1500)
        orch._active_tasks["dock_generator"] = asyncio.create_task(asyncio.sleep(0.02))
        await orch._activate_sync(
            act, _FakeSession(), extra_context={"recent_text": "新段落。"},
        )
        assert calls == ["新段落。"]

        # budget 档不同 → 同样维持重跑
        orch._active_task_sigs["dock_generator"] = orch._component_input_sig("新段落。", 999)
        orch._active_tasks["dock_generator"] = asyncio.create_task(asyncio.sleep(0.02))
        await orch._activate_sync(
            act, _FakeSession(), extra_context={"recent_text": "新段落。"},
        )
        assert calls == ["新段落。", "新段落。"]

    asyncio.run(scenario())


def test_activate_sync_without_existing_task_runs_once(monkeypatch):
    """无在跑任务（常态路径）→ 照常执行一次，行为不变。"""
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)
    calls = []

    async def runner(chapter_id, db, snap, budget, **kw):
        calls.append(1)
        return {}

    orch = _orch()
    orch.register_component("canon_watch", runner)
    asyncio.run(orch._activate_sync(
        Activation("canon_watch", "low", 0), _FakeSession(),
        extra_context={"recent_text": "任意。"},
    ))
    assert calls == [1]

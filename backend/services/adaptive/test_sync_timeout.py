# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 停顿档同步超时钳制单测
"""
2026-08-27 自动唤醒断掉修复的对拍。

trace 实证：慢端点下推测 70s/挂件 104s（串行同步），停顿心跳响应被拖到
几分钟——前端自动弹舱守卫（响应落地时作者须未动笔）永不满足，卡片舱
「只剩 Tab 活着」。

- 同步组件超时：runner 卡死超过 SYNC_COMPONENT_TIMEOUT_S → 放弃本轮产出
  （不抛 500），记「同步超时」组件错误（AI 视角可见）；
- 快 runner 不受影响、成功即清错误。
配方同 test_orchestrator_health.py：独立 asyncio.run + FakeRepo/FakeSession。
"""
import asyncio
import uuid

import backend.services.adaptive.world_model as wm
import backend.services.adaptive.orchestrator as orch_mod
from backend.services.adaptive.orchestrator import Activation, AdaptiveOrchestrator

CH_ID = str(uuid.UUID("bb260000-0000-4000-8000-0000000000d1"))


class _FakeRepo:
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


def test_sync_timeout_gives_up_and_records(monkeypatch):
    """runner 卡死超过钳制 → 放弃不抛、记「同步超时」组件错误。"""
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)
    monkeypatch.setattr(orch_mod, "SYNC_COMPONENT_TIMEOUT_S", 0.05)  # 缩短钳制，测试不必等 12s

    async def slow_runner(chapter_id, db, snap, budget, **kw):
        await asyncio.sleep(5)  # 远超钳制

    orch = _orch()
    orch.register_component("dock_generator", slow_runner)

    async def scenario():
        await orch._activate_sync(Activation("dock_generator", "low", 1500), _FakeSession())

    asyncio.run(scenario())
    errs = orch.last_component_errors()
    assert "dock_generator" in errs
    assert "同步超时" in errs["dock_generator"]["error"]


def test_sync_fast_runner_unaffected(monkeypatch):
    """正常时长的 runner 照常完成，无错误记录。"""
    monkeypatch.setattr(wm, "WorldModelRepository", _FakeRepo)
    monkeypatch.setattr(orch_mod, "SYNC_COMPONENT_TIMEOUT_S", 0.05)

    ran = {}

    async def fast_runner(chapter_id, db, snap, budget, **kw):
        await asyncio.sleep(0.001)
        ran["ok"] = True

    orch = _orch()
    orch.register_component("dock_generator", fast_runner)

    async def scenario():
        await orch._activate_sync(Activation("dock_generator", "low", 1500), _FakeSession())

    asyncio.run(scenario())
    assert ran.get("ok")
    assert "dock_generator" not in orch.last_component_errors()

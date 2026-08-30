# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""A5c · 收件箱积压提醒单测（P5 docs/foundation-hardening.md §3.2）。

覆盖：
- build_world_inbox_hint 纯判定：空池/阈值内不提示、>5 提示、文案计数正确
- _world_inbox_hint_for_heartbeat：stub db 计数通路 + TTL 缓存命中 + 查询失败静默 None
（finish 端点的 candidates_pending 字段由同一 _pending_candidates_count 供数，
 判定逻辑在此锁死；端点级装配走既有 GUI 手动验证路径。）
"""
# Velluma - world inbox hint tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
import uuid
from types import SimpleNamespace

from backend.routes.chapter_generation.adaptive import (
    WORLD_INBOX_HINT_THRESHOLD,
    _WORLD_INBOX_CACHE,
    _world_inbox_hint_for_heartbeat,
    build_world_inbox_hint,
)


def _run(coro):
    """独立 event loop 跑异步（workflows/conftest.py 注释的同款防御，不依赖该 conftest）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


# ---- 纯判定函数 ----

def test_empty_pool_no_hint():
    assert build_world_inbox_hint(0) is None


def test_at_threshold_no_hint():
    """阈值语义是「>5 才提示」——恰好 5 条属正常工作区，宁静默勿刷屏。"""
    assert build_world_inbox_hint(WORLD_INBOX_HINT_THRESHOLD) is None
    assert build_world_inbox_hint(5) is None


def test_over_threshold_hint_with_count():
    hint = build_world_inbox_hint(6)
    assert hint is not None
    assert hint["kind"] == "world_inbox"
    assert "6 条世界变化待确认" in hint["detail"]
    assert hint["severity"] == "info"


def test_large_count_in_message():
    hint = build_world_inbox_hint(23)
    assert hint is not None
    assert "23 条" in hint["detail"]


# ---- 心跳通路（stub db）----

class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _StubDB:
    def __init__(self, value=None, raise_exc=None):
        self._value = value
        self._raise = raise_exc
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        if self._raise:
            raise self._raise
        return _FakeResult(self._value)


def _chapter():
    return SimpleNamespace(id=uuid.uuid4(), book_id=uuid.uuid4())


def _reset_cache():
    _WORLD_INBOX_CACHE.clear()


def test_heartbeat_query_path_over_threshold():
    _reset_cache()
    db = _StubDB(value=9)
    hint = _run(_world_inbox_hint_for_heartbeat(_chapter(), db))
    assert hint is not None and "9 条" in hint["detail"]
    assert db.calls == 1


def test_heartbeat_no_chapter_returns_none():
    _reset_cache()
    db = _StubDB(value=9)
    assert _run(_world_inbox_hint_for_heartbeat(None, db)) is None
    assert db.calls == 0


def test_heartbeat_ttl_cache_hits():
    """缓存窗口内不重复查库（防抖 + 省查询）；换书各走各的缓存键。"""
    _reset_cache()
    db1 = _StubDB(value=9)
    ch1 = _chapter()
    assert _run(_world_inbox_hint_for_heartbeat(ch1, db1)) is not None
    # 第二次命中缓存：db1 不再被查询（换成必炸 db 仍返回缓存结果）
    boom = _StubDB(raise_exc=RuntimeError("should not be called"))
    hint2 = _run(_world_inbox_hint_for_heartbeat(ch1, boom))
    assert hint2 is not None and "9 条" in hint2["detail"]
    assert boom.calls == 0


def test_heartbeat_db_failure_silent_none():
    """计数失败静默缺席——提醒是柔性信号，绝不阻塞心跳。"""
    _reset_cache()
    ch = _chapter()
    # 先污染缓存外的独立书：直接用会炸的 db（无缓存可命中）
    db = _StubDB(raise_exc=RuntimeError("db down"))
    assert _run(_world_inbox_hint_for_heartbeat(ch, db)) is None

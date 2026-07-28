# Velluma - NLE-ADF Stepping Runtime Tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""_SteppingRun 状态机单元测试。"""

import asyncio
import time
import pytest

from backend.services.workflows.bsadf.stepping_runtime import (
    SteppingRun,
    SteppingRunStore,
)


def test_stepping_run_init_has_required_fields():
    run = SteppingRun(run_id="test_run_001", chapter_id=42, cards=[], workflow=None)
    assert run.run_id == "test_run_001"
    assert run.chapter_id == 42
    assert run.current_beat_index == 0
    assert run.locked_segments == []
    assert run.state_card_chain == []
    assert isinstance(run.advance_event, asyncio.Event)
    assert isinstance(run.action_queue, asyncio.Queue)
    assert isinstance(run.event_queue, asyncio.Queue)
    assert run.created_at > 0
    assert run.last_activity > 0


def test_stepping_run_store_set_get():
    store = SteppingRunStore(ttl_seconds=3600)
    run = SteppingRun(run_id="r1", chapter_id=1, cards=[], workflow=None)
    store.set(run)
    assert store.get("r1") is run
    assert store.get("nonexistent") is None


def test_stepping_run_store_pop():
    store = SteppingRunStore(ttl_seconds=3600)
    run = SteppingRun(run_id="r1", chapter_id=1, cards=[], workflow=None)
    store.set(run)
    assert store.pop("r1") is run
    assert store.get("r1") is None


def test_stepping_run_store_ttl_cleanup():
    store = SteppingRunStore(ttl_seconds=0)
    run = SteppingRun(run_id="r1", chapter_id=1, cards=[], workflow=None)
    store.set(run)
    store._cleanup_expired()
    assert store.get("r1") is None


def test_stepping_run_store_touch_refreshes_activity():
    store = SteppingRunStore(ttl_seconds=100)
    run = SteppingRun(run_id="r1", chapter_id=1, cards=[], workflow=None)
    store.set(run)
    old_activity = run.last_activity
    time.sleep(0.02)
    store.touch("r1")
    assert run.last_activity > old_activity

# Velluma - NLE-ADF Stepping Runtime Tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""_SteppingRun 状态机单元测试。"""

import asyncio
import time
import pytest
from typing import List

from backend.services.workflows.bsadf.stepping_runtime import (
    SteppingRun,
    SteppingRunStore,
    stepping_loop,
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


class _FakeCard:
    def __init__(self, beat_id: str, segment_index: int, target_word_count: int = 500):
        self.beat_id = beat_id
        self.segment_index = segment_index
        self.target_word_count = target_word_count
        self.core_plot_event = f"事件{segment_index}"
        self.key_anchors = []
        self.text_carrier = ""
        self.outline_beat = ""
        self.branch_directive = ""
        self.status = "pending"
        self.edit_count = 0
        self.render_attempts = 0
        self.edited = False


class _FakeSegment:
    def __init__(self, index: int, text: str):
        self.index = index
        self.text = text


class _FakeWorkflow:
    def __init__(self, texts: List[str]):
        self._texts = texts
        self._call_idx = 0
        self.post_step_called = False

    async def render_one(self, card, segment_index, locked_segments, state_card_chain, **kw):
        text = self._texts[self._call_idx % len(self._texts)]
        self._call_idx += 1
        return _FakeSegment(segment_index, text), None

    async def ingest_memory(self, segment, card, segment_index, **kw):
        return {"new_entities": []}

    async def run_post_step_phases(self, final_text, locked_segments, **kw):
        self.post_step_called = True
        return {"final_text": final_text, "stats": {}}


@pytest.mark.asyncio
async def test_stepping_loop_pass_advances_to_next_beat():
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["第一段正文。", "第二段正文。"])
    run = SteppingRun(run_id="r1", chapter_id=1, cards=cards, workflow=workflow)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))
    ev_name, _ = await run.event_queue.get()  # BEAT_RENDER_START
    assert ev_name == "BEAT_RENDER_START"
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_READY"
    assert ev_data["beat_id"] == "B00"
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_LOCKED"
    ev_name, _ = await run.event_queue.get()  # BEAT_RENDER_START
    assert ev_name == "BEAT_RENDER_START"
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_READY"
    assert ev_data["beat_id"] == "B01"
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_LOCKED"
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "ALL_BEATS_LOCKED"
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "COMPLETE"
    assert workflow.post_step_called
    await task


@pytest.mark.asyncio
async def test_stepping_loop_skip_jumps_segment_without_render():
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["第一段。", "第二段。"])
    run = SteppingRun(run_id="r2", chapter_id=1, cards=cards, workflow=workflow)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))
    await run.event_queue.get()  # BEAT_RENDER_START B00
    await run.event_queue.get()  # BEAT_RENDER_READY B00
    await run.action_queue.put({"action": "skip", "beat_id": "B00"})
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_SKIPPED"
    await run.event_queue.get()  # BEAT_RENDER_START B01
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_READY"
    assert ev_data["beat_id"] == "B01"
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task
    assert len(run.locked_segments) == 1


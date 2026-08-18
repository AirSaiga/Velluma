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
        self.author_locked_texts: List[str] = []

    @property
    def render_call_count(self) -> int:
        return self._call_idx

    async def render_one(self, card, segment_index, locked_segments, state_card_chain, **kw):
        text = self._texts[self._call_idx % len(self._texts)]
        self._call_idx += 1
        return _FakeSegment(segment_index, text), None

    async def lock_segment_with_author_text(self, card, author_text, segment_index, locked_segments, state_card_chain, **kw):
        self.author_locked_texts.append(author_text)
        return _FakeSegment(segment_index, author_text), None

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


@pytest.mark.asyncio
async def test_stepping_loop_edit_rerenders_same_segment():
    """edit 动作重渲染当前段（不推进到下一段），且更新卡的硬契约字段。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["原文。", "第二段。"])
    run = SteppingRun(run_id="r4", chapter_id=1, cards=cards, workflow=workflow)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))
    # 第一段就绪
    await run.event_queue.get()  # BEAT_RENDER_START B00
    await run.event_queue.get()  # BEAT_RENDER_READY B00
    # edit：作者改了硬契约
    await run.action_queue.put({
        "action": "edit", "beat_id": "B00",
        "edited_slot": {
            "core_plot_event": "新事件",
            "key_anchors": ["新锚点"],
            "text_carrier": "新台词",
        },
    })
    # 应该重新渲染 B00（不推进到 B01）
    ev_name, ev_data = await run.event_queue.get()  # BEAT_RENDER_START
    assert ev_name == "BEAT_RENDER_START"
    assert ev_data["beat_id"] == "B00"
    # card 的硬契约字段应被覆盖
    assert cards[0].core_plot_event == "新事件"
    assert cards[0].key_anchors == ["新锚点"]
    assert cards[0].text_carrier == "新台词"
    assert cards[0].edited is True
    assert cards[0].edit_count == 1
    # 清理：pass B00 → pass B01
    await run.event_queue.get()  # BEAT_RENDER_READY B00（重渲染后）
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # BEAT_RENDER_START B01
    await run.event_queue.get()  # BEAT_RENDER_READY B01
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task
    # edit 后只有 pass 才进 locked_segments，所以最终 2 段都锁死
    assert len(run.locked_segments) == 2


@pytest.mark.asyncio
async def test_stepping_loop_branch_updates_directive():
    """branch 动作更新 branch_directive 并重渲染当前段（不推进）。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["原文。", "第二段。"])
    run = SteppingRun(run_id="r5", chapter_id=1, cards=cards, workflow=workflow)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))
    await run.event_queue.get()  # BEAT_RENDER_START B00
    await run.event_queue.get()  # BEAT_RENDER_READY B00
    # branch：作者切走向
    await run.action_queue.put({
        "action": "branch", "beat_id": "B00",
        "branch_choice": {"option_id": "B", "label": "反抗", "plot_impact": "正面对抗"},
    })
    # 应该重渲染 B00
    ev_name, ev_data = await run.event_queue.get()  # BEAT_RENDER_START
    assert ev_name == "BEAT_RENDER_START"
    assert ev_data["beat_id"] == "B00"
    # branch_directive 应被更新（plot_impact 优先）
    assert "正面对抗" in cards[0].branch_directive
    # 清理
    await run.event_queue.get()  # BEAT_RENDER_READY B00
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # BEAT_RENDER_START B01
    await run.event_queue.get()  # BEAT_RENDER_READY B01
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


@pytest.mark.asyncio
async def test_stepping_loop_calls_ingest_memory_on_pass():
    """pass 动作在 enable_memory_ingestion=True 时触发 ingest_memory。"""
    from unittest.mock import AsyncMock
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["第一段。", "第二段。"])
    workflow.ingest_memory = AsyncMock(return_value={"new_entities": [{"name": "血噬"}]})
    run = SteppingRun(run_id="r3", chapter_id=1, cards=cards, workflow=workflow)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=True))
    await run.event_queue.get()  # BEAT_RENDER_START B00
    await run.event_queue.get()  # BEAT_RENDER_READY B00
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED（含 extracted_facts）
    # ingest_memory 应被调用一次
    workflow.ingest_memory.assert_called_once()
    # 清理
    await run.event_queue.get()  # BEAT_RENDER_START B01
    await run.event_queue.get()  # BEAT_RENDER_READY B01
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


@pytest.mark.asyncio
async def test_branch_gate_pauses_when_dde_branch_present():
    """岔路门：段有 DDE 岔路时，渲染前暂停发 BEAT_BRANCH_CHOICE。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["第一段。", "第二段。"])
    decision_set = {
        "has_story_branch": True,
        "decision_nodes": [{
            "beat_id": "B00",
            "node_title": "林尘的应对",
            "options": [
                {"option_id": "A", "label": "忍辱", "plot_impact": "默默承受"},
                {"option_id": "B", "label": "反抗", "plot_impact": "正面对抗"},
            ],
            "default_option": "A",
        }],
    }
    run = SteppingRun(run_id="r_gate", chapter_id=1, cards=cards, workflow=workflow, decision_set=decision_set)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    # B00 有岔路 → 应先收到 BEAT_BRANCH_CHOICE（而非 BEAT_RENDER_START）
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_BRANCH_CHOICE"
    assert ev_data["beat_id"] == "B00"
    assert ev_data["node"]["node_title"] == "林尘的应对"

    # 作者选了 B 走向
    await run.action_queue.put({
        "action": "branch", "beat_id": "B00",
        "branch_choice": {"option_id": "B", "label": "反抗", "plot_impact": "正面对抗"},
    })
    await asyncio.sleep(0)  # 让 stepping_loop 协程处理
    # 岔路门注入 directive 后继续渲染
    assert "正面对抗" in cards[0].branch_directive
    await run.event_queue.get()  # BEAT_RENDER_START B00
    await run.event_queue.get()  # BEAT_RENDER_READY B00
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED
    # B01 无岔路 → 直接 BEAT_RENDER_START
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_START"
    await run.event_queue.get()  # BEAT_RENDER_READY B01
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


@pytest.mark.asyncio
async def test_branch_gate_pass_uses_default_directive():
    """岔路门：作者 pass（接受默认）→ 用默认走向注入 directive。"""
    cards = [_FakeCard("B00", 0)]
    workflow = _FakeWorkflow(["第一段。"])
    decision_set = {
        "has_story_branch": True,
        "decision_nodes": [{
            "beat_id": "B00", "node_title": "test",
            "options": [{"option_id": "A", "label": "忍辱", "plot_impact": "默默承受"}],
            "default_option": "A",
        }],
    }
    run = SteppingRun(run_id="r_default", chapter_id=1, cards=cards, workflow=workflow, decision_set=decision_set)
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    await run.event_queue.get()  # BEAT_BRANCH_CHOICE
    # pass = 接受默认走向
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await asyncio.sleep(0)  # 让 stepping_loop 协程处理
    # 应注入默认走向 directive
    assert "忍辱" in cards[0].branch_directive
    assert "默默承受" in cards[0].branch_directive
    await run.event_queue.get()  # BEAT_RENDER_START
    await run.event_queue.get()  # BEAT_RENDER_READY
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


@pytest.mark.asyncio
async def test_branch_gate_no_branch_skips_gate():
    """无 DDE 岔路时，岔路门不触发，直接渲染。"""
    cards = [_FakeCard("B00", 0)]
    workflow = _FakeWorkflow(["第一段。"])
    run = SteppingRun(
        run_id="r_nogate", chapter_id=1, cards=cards, workflow=workflow,
        decision_set={"has_story_branch": False, "decision_nodes": []},
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))
    # 无岔路 → 直接 BEAT_RENDER_START（无 BEAT_BRANCH_CHOICE）
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_START"
    await run.event_queue.get()  # BEAT_RENDER_READY
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


# ============================================================
# NLE-ADF 2.0 作者模式（authoring_mode=True）
# ============================================================

@pytest.mark.asyncio
async def test_authoring_mode_opens_and_waits_without_render():
    """作者模式：到拍发 BEAT_AUTHORING_OPEN 挂起，不自动渲染；render 动作才代笔。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["代笔第一段。", "代笔第二段。"])
    run = SteppingRun(
        run_id="r_auth1", chapter_id=1, cards=cards, workflow=workflow,
        authoring_mode=True,
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    # 首事件必须是 AUTHORING_OPEN（不是 RENDER_START），且渲染未被调用
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_AUTHORING_OPEN"
    assert ev_data["beat_id"] == "B00"
    assert workflow.render_call_count == 0
    assert run.awaiting_authoring is True
    assert run.pending_authoring is not None

    # 作者召唤代笔 → 正常渲染序列
    await run.action_queue.put({"action": "render", "beat_id": "B00"})
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_START"
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_RENDER_READY"
    assert ev_data["beat_id"] == "B00"
    assert run.awaiting_authoring is False
    assert run.pending_authoring is None
    assert workflow.render_call_count == 1

    # pass 锁死代笔稿 → 下一拍再次 AUTHORING_OPEN（不自动渲染）
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_LOCKED"
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_AUTHORING_OPEN"
    assert ev_data["beat_id"] == "B01"
    assert workflow.render_call_count == 1

    # 清理：render + pass B01
    await run.action_queue.put({"action": "render", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_RENDER_START
    await run.event_queue.get()  # BEAT_RENDER_READY
    await run.action_queue.put({"action": "pass", "beat_id": "B01"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task
    assert workflow.post_step_called


@pytest.mark.asyncio
async def test_authoring_lock_with_text_skips_render():
    """作者模式：AUTHORING_OPEN 直接 lock_with_text → 整拍定稿，全程零渲染调用。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["永远不该被用到。"])
    run = SteppingRun(
        run_id="r_auth2", chapter_id=1, cards=cards, workflow=workflow,
        authoring_mode=True,
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    await run.event_queue.get()  # BEAT_AUTHORING_OPEN B00
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B00",
        "author_text": "雨砸在废铁车上，轴承卡死了。",
    })
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_LOCKED"
    assert ev_data["author_locked"] is True
    assert workflow.render_call_count == 0
    assert run.locked_segments[-1].text == "雨砸在废铁车上，轴承卡死了。"

    # 下一拍仍开 AUTHORING_OPEN；末拍同样定稿 → COMPLETE
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_AUTHORING_OPEN"
    assert ev_data["beat_id"] == "B01"
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B01",
        "author_text": "林尘进屋，柴油灯闪了一下。",
    })
    await run.event_queue.get()  # BEAT_LOCKED
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "ALL_BEATS_LOCKED"
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "COMPLETE"
    # 终稿 = 两段作者正文拼接
    assert "雨砸在废铁车上" in ev_data["final_text"]
    assert "林尘进屋" in ev_data["final_text"]
    await task
    assert workflow.render_call_count == 0
    assert workflow.author_locked_texts == [
        "雨砸在废铁车上，轴承卡死了。",
        "林尘进屋，柴油灯闪了一下。",
    ]


@pytest.mark.asyncio
async def test_authoring_empty_lock_degrades_to_skip():
    """作者模式：空 author_text 的 lock_with_text → skip 语义（无已渲染段可退化 pass）。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["第二段。"])
    run = SteppingRun(
        run_id="r_auth3", chapter_id=1, cards=cards, workflow=workflow,
        authoring_mode=True,
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    await run.event_queue.get()  # BEAT_AUTHORING_OPEN B00
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B00", "author_text": "   ",
    })
    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_SKIPPED"
    assert len(run.locked_segments) == 0
    # skip 压了快照栈（可 back 救回）
    assert len(run.snapshot_stack) == 1

    # 清理：B01 定稿 → COMPLETE
    await run.event_queue.get()  # BEAT_AUTHORING_OPEN B01
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B01", "author_text": "结尾。",
    })
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


@pytest.mark.asyncio
async def test_authoring_back_reopens_authoring():
    """作者模式：back 弹快照后，目标拍重新开 AUTHORING_OPEN（而非自动重渲）。"""
    cards = [_FakeCard("B00", 0), _FakeCard("B01", 1)]
    workflow = _FakeWorkflow(["不该被用到。"])
    run = SteppingRun(
        run_id="r_auth4", chapter_id=1, cards=cards, workflow=workflow,
        authoring_mode=True,
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    # B00 定稿 → B01 打开 → back 回 B00
    await run.event_queue.get()  # BEAT_AUTHORING_OPEN B00
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B00", "author_text": "第一拍定稿。",
    })
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # BEAT_AUTHORING_OPEN B01
    assert len(run.locked_segments) == 1
    await run.action_queue.put({"action": "back", "beat_id": "B01"})
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_BACKED"
    assert ev_data["beat_id"] == "B00"
    assert len(run.locked_segments) == 0
    # 关键断言：back 后重开 AUTHORING_OPEN，不自动渲染
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_AUTHORING_OPEN"
    assert ev_data["beat_id"] == "B00"
    assert workflow.render_call_count == 0

    # 清理：重新定稿 B00 → B01 定稿 → COMPLETE
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B00", "author_text": "第一拍重写。",
    })
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # BEAT_AUTHORING_OPEN B01
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B01", "author_text": "第二拍。",
    })
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "COMPLETE"
    assert "第一拍重写。" in ev_data["final_text"]
    await task


@pytest.mark.asyncio
async def test_authoring_branch_gate_deferred_to_render():
    """岔路门 JIT 化：作者模式拍开始不问走向（直开 AUTHORING_OPEN），
    仅当代笔动作（render）且岔路未决时才挂起问走向。"""
    cards = [_FakeCard("B00", 0)]
    workflow = _FakeWorkflow(["代笔段。"])
    decision_set = {
        "has_story_branch": True,
        "decision_nodes": [{
            "beat_id": "B00",
            "node_title": "林尘的应对",
            "options": [
                {"option_id": "A", "label": "忍辱", "plot_impact": "默默承受"},
                {"option_id": "B", "label": "反抗", "plot_impact": "正面对抗"},
            ],
            "default_option": "A",
        }],
    }
    run = SteppingRun(
        run_id="r_jit1", chapter_id=1, cards=cards, workflow=workflow,
        decision_set=decision_set, authoring_mode=True,
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    # 关键断言 1：首事件是 AUTHORING_OPEN，不是 BRANCH_CHOICE（拍前不问）
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_AUTHORING_OPEN"
    assert ev_data["beat_id"] == "B00"
    assert workflow.render_call_count == 0
    assert cards[0].branch_directive == ""

    # 召唤代笔 → 此刻才挂起问走向
    await run.action_queue.put({"action": "render", "beat_id": "B00"})
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_BRANCH_CHOICE"
    assert ev_data["node"]["node_title"] == "林尘的应对"
    assert workflow.render_call_count == 0  # 问完才渲染

    # 选 B → directive 注入 → 渲染
    await run.action_queue.put({
        "action": "branch", "beat_id": "B00",
        "branch_choice": {"option_id": "B", "label": "反抗", "plot_impact": "正面对抗"},
    })
    await asyncio.sleep(0)
    assert "正面对抗" in cards[0].branch_directive
    await run.event_queue.get()  # BEAT_RENDER_START
    await run.event_queue.get()  # BEAT_RENDER_READY
    await run.action_queue.put({"action": "pass", "beat_id": "B00"})
    await run.event_queue.get()  # BEAT_LOCKED
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


@pytest.mark.asyncio
async def test_authoring_lock_with_text_never_asks_branch():
    """岔路门 JIT 化：作者自己写完整拍（lock_with_text）时永不问走向。"""
    cards = [_FakeCard("B00", 0)]
    workflow = _FakeWorkflow(["不该被用到。"])
    decision_set = {
        "has_story_branch": True,
        "decision_nodes": [{
            "beat_id": "B00", "node_title": "岔路",
            "options": [{"option_id": "A", "label": "忍辱", "plot_impact": "默默承受"}],
            "default_option": "A",
        }],
    }
    run = SteppingRun(
        run_id="r_jit2", chapter_id=1, cards=cards, workflow=workflow,
        decision_set=decision_set, authoring_mode=True,
    )
    task = asyncio.create_task(stepping_loop(run, enable_memory_ingestion=False))

    ev_name, _ = await run.event_queue.get()
    assert ev_name == "BEAT_AUTHORING_OPEN"  # 拍前不问
    await run.action_queue.put({
        "action": "lock_with_text", "beat_id": "B00",
        "author_text": "林尘盯着工头，把扳手放下了。",
    })
    ev_name, ev_data = await run.event_queue.get()
    assert ev_name == "BEAT_LOCKED"  # 直接锁死，全程无 BRANCH_CHOICE
    assert ev_data["author_locked"] is True
    assert cards[0].branch_directive == ""  # 未注入任何走向
    assert workflow.render_call_count == 0
    await run.event_queue.get()  # ALL_BEATS_LOCKED
    await run.event_queue.get()  # COMPLETE
    await task


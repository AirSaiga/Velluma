"""downgrade 状态机单测。"""
# Velluma - BS-ADF downgrade tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from backend.services.workflows.bsadf.types import BeatSlotCard, DegradedBeat
from backend.services.workflows.bsadf.downgrade import render_with_downgrade, MAX_RENDER_ATTEMPTS
from backend.services.workflows.adf.types import SegmentResult


def _make_card():
    return BeatSlotCard(
        beat_id="BS_TEST_00", segment_index=0, beat_type="ESTABLISH",
        target_word_count=500, key_anchors=["气动扳手"],
        shot_type="wide", transition="cut", emotion_register="入口",
    )


def _make_passing_render_result(card):
    """模拟 render_slot_to_segment 成功返回（无 issues，有文本）。"""
    return (
        SegmentResult(index=card.segment_index, text="气动扳手响起，柴油味弥漫。", shot_type=card.shot_type),
        card,
        [],  # 无 issues
    )


def _make_failing_render_result(card, issues):
    """模拟 render_slot_to_segment 失败返回（有 issues）。"""
    return (
        SegmentResult(index=card.segment_index, text="", shot_type=card.shot_type),
        card,
        issues,
    )


class TestRenderWithDowngrade:
    def test_first_attempt_success(self):
        """首次渲染成功，不重试，status=rendered。"""
        card = _make_card()
        with patch("backend.services.workflows.bsadf.downgrade.render_slot_to_segment",
                   new_callable=AsyncMock, return_value=_make_passing_render_result(card)):
            seg, ret_card, degraded = asyncio.get_event_loop().run_until_complete(
                render_with_downgrade(card=card, rolling_prefix="", scene_setting_text="",
                                      name_registry_block="", state_card_block="",
                                      emotion_curve_text="", style_contract="")
            )
        assert ret_card.status == "rendered"
        assert degraded is None
        assert "气动扳手" in seg.text

    def test_continuous_failure_downgrades(self):
        """连续 MAX_RENDER_ATTEMPTS 次失败 → 降级。"""
        card = _make_card()
        fail_result = _make_failing_render_result(card, ["动作词: 气动扳手"])
        with patch("backend.services.workflows.bsadf.downgrade.render_slot_to_segment",
                   new_callable=AsyncMock, return_value=fail_result):
            seg, ret_card, degraded = asyncio.get_event_loop().run_until_complete(
                render_with_downgrade(card=card, rolling_prefix="", scene_setting_text="",
                                      name_registry_block="", state_card_block="",
                                      emotion_curve_text="", style_contract="")
            )
        assert ret_card.status == "degraded"
        assert degraded is not None
        assert degraded.reason == "coverage_fail"
        assert degraded.attempts == MAX_RENDER_ATTEMPTS
        assert seg.text == ""

    def test_retry_succeeds_on_second_attempt(self):
        """首次失败、第二次成功 → 不降级。"""
        card = _make_card()
        call_count = [0]

        async def mock_render(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _make_failing_render_result(card, ["coverage 缺失"])
            return _make_passing_render_result(card)

        with patch("backend.services.workflows.bsadf.downgrade.render_slot_to_segment",
                   new=mock_render):
            seg, ret_card, degraded = asyncio.get_event_loop().run_until_complete(
                render_with_downgrade(card=card, rolling_prefix="", scene_setting_text="",
                                      name_registry_block="", state_card_block="",
                                      emotion_curve_text="", style_contract="")
            )
        assert ret_card.status == "rendered"
        assert degraded is None
        assert call_count[0] == 2

    def test_progress_callback_called_on_success(self):
        """成功时 progress_callback 推 BEAT_RENDER_PROGRESS。"""
        card = _make_card()
        events = []

        async def cb(event, data):
            events.append((event, data))

        with patch("backend.services.workflows.bsadf.downgrade.render_slot_to_segment",
                   new_callable=AsyncMock, return_value=_make_passing_render_result(card)):
            asyncio.get_event_loop().run_until_complete(
                render_with_downgrade(card=card, rolling_prefix="", scene_setting_text="",
                                      name_registry_block="", state_card_block="",
                                      emotion_curve_text="", style_contract="",
                                      progress_callback=cb)
            )
        assert any(e == "BEAT_RENDER_PROGRESS" for e, _ in events)

    def test_progress_callback_called_on_downgrade(self):
        """降级时 progress_callback 推 BEAT_DOWNGRADED。"""
        card = _make_card()
        events = []
        fail_result = _make_failing_render_result(card, ["llm_error: 超时"])

        async def cb(event, data):
            events.append((event, data))

        with patch("backend.services.workflows.bsadf.downgrade.render_slot_to_segment",
                   new_callable=AsyncMock, return_value=fail_result):
            asyncio.get_event_loop().run_until_complete(
                render_with_downgrade(card=card, rolling_prefix="", scene_setting_text="",
                                      name_registry_block="", state_card_block="",
                                      emotion_curve_text="", style_contract="",
                                      progress_callback=cb)
            )
        assert any(e == "BEAT_DOWNGRADED" for e, _ in events)

    def test_downgrade_reason_classification(self):
        """不同 issues 对应不同降级原因。"""
        from backend.services.workflows.bsadf.downgrade import _classify_downgrade_reason
        assert _classify_downgrade_reason(["llm_error: 超时"]) == "llm_error"
        assert _classify_downgrade_reason(["动作词: X"]) == "coverage_fail"
        assert _classify_downgrade_reason(["segment_loop_duplicate"]) == "gate_fail"
        assert _classify_downgrade_reason(["角色A 已死亡/离场，不应再行动"]) == "gate_fail"
        assert _classify_downgrade_reason([]) == "ai_smell"

    def test_degraded_beat_contains_card_snapshot(self):
        """降级时 DegradedBeat.card_snapshot 应是降级时的 card 快照。"""
        card = _make_card()
        fail_result = _make_failing_render_result(card, ["coverage 缺失"])
        with patch("backend.services.workflows.bsadf.downgrade.render_slot_to_segment",
                   new_callable=AsyncMock, return_value=fail_result):
            _, _, degraded = asyncio.get_event_loop().run_until_complete(
                render_with_downgrade(card=card, rolling_prefix="", scene_setting_text="",
                                      name_registry_block="", state_card_block="",
                                      emotion_curve_text="", style_contract="")
            )
        assert degraded is not None
        assert degraded.card_snapshot.beat_id == card.beat_id
        assert degraded.card_snapshot.status == "degraded"

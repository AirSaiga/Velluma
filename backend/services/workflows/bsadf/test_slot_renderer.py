"""slot_renderer 单测。

覆盖：
- verify_slot_coverage：纯函数校验槽位覆盖（硬焦点锚点词/文本载体；
  感官词校验已随 sensory_details 字段一起删除，感官指导下沉为静态 system prompt）
- render_slot_to_segment：mock LLM，验证返回 SegmentResult + 后处理链触发

注意：mock LLMResult 时使用 .content 字段（call_llm_with_usage 返回类型实际字段名）。
"""
# Velluma - BS-ADF slot_renderer tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

from backend.services.workflows.bsadf.types import BeatSlotCard
from backend.services.workflows.bsadf.slot_renderer import (
    verify_slot_coverage,
    render_slot_to_segment,
)


def _make_card(**kwargs):
    defaults = dict(
        beat_id="BS_TEST_00", segment_index=0, beat_type="ESTABLISH",
        target_word_count=500, key_anchors=["气动扳手"],
        text_carrier="世界庞大", core_plot_event="门被踢开",
        shot_type="wide", transition="cut", emotion_register="入口", emotion_energy=3,
    )
    defaults.update(kwargs)
    return BeatSlotCard(**defaults)


class TestVerifySlotCoverage:
    def test_all_present_passes(self):
        card = _make_card()
        text = "他砸下气动扳手，柴油味弥漫，低声说'世界庞大'，门被踢开。"
        passed, missing = verify_slot_coverage(text, card)
        assert passed is True
        assert missing == []

    def test_missing_anchor_fails(self):
        card = _make_card(key_anchors=["气动扳手", "不存在词"])
        text = "他砸下气动扳手，柴油味弥漫，世界庞大。"
        passed, missing = verify_slot_coverage(text, card)
        assert passed is False
        assert any("不存在词" in m for m in missing)

    def test_missing_carrier_fails(self):
        card = _make_card(text_carrier="特定台词XYZ")
        text = "气动扳手响起，柴油味弥漫，门被踢开。"  # 没有载体
        passed, missing = verify_slot_coverage(text, card)
        assert passed is False
        assert any("特定台词XYZ" in m for m in missing)

    def test_empty_carrier_not_checked(self):
        card = _make_card(text_carrier="")
        text = "气动扳手响起，柴油味弥漫。"
        passed, missing = verify_slot_coverage(text, card)
        assert passed is True

    def test_empty_anchors_not_checked(self):
        # 全部槽位为空时，任意文本都应通过（验证"空槽不检查"语义）
        card = _make_card(key_anchors=[], text_carrier="")
        text = "任意文本"
        passed, missing = verify_slot_coverage(text, card)
        assert passed is True

    def test_core_plot_event_not_coverage_checked(self):
        """core_plot_event 是剧情转折描述，不做 coverage 逐词校验
        （校验的是 key_anchors/text_carrier；转折落座由 Phase 5 审计负责）。"""
        card = _make_card(core_plot_event="一段绝对不会出现的转折描述")
        text = "他砸下气动扳手，低声说'世界庞大'。"
        passed, missing = verify_slot_coverage(text, card)
        assert passed is True


class TestRenderSlotToSegment:
    def test_successful_render(self):
        """mock LLM 返回包含所有槽位词的正文，应成功。"""
        card = _make_card()
        # LLMResult 实际字段是 .content（不是 .text）
        mock_result = MagicMock()
        mock_result.content = "他砸下气动扳手，柴油味呛人，低声念'世界庞大'，门被踢开。"

        with patch("backend.services.workflows.bsadf.slot_renderer.call_llm_with_usage",
                   new_callable=AsyncMock, return_value=mock_result), \
             patch("backend.services.workflows.bsadf.slot_renderer.measure_ai_taste",
                   return_value=MagicMock(triggered=False)), \
             patch("backend.services.workflows.bsadf.slot_renderer.preprocess_segment",
                   side_effect=lambda t, genre=None: t), \
             patch("backend.services.workflows.bsadf.slot_renderer.sanitize_segment",
                   side_effect=lambda t: t), \
             patch("backend.services.workflows.bsadf.slot_renderer.segment_too_similar",
                   return_value=False), \
             patch("backend.services.workflows.bsadf.slot_renderer.check_segment_against_card",
                   return_value=[]):
            seg, ret_card, issues = asyncio.run(
                render_slot_to_segment(card=card, rolling_prefix="", scene_setting_text="",
                                       name_registry_block="", state_card_block="",
                                       emotion_curve_text="", style_contract="")
            )
        assert seg.index == 0
        assert "气动扳手" in seg.text
        assert ret_card.render_attempts == 1
        # coverage 应通过（所有词都在）
        assert not any("动作词" in i or "文本载体" in i for i in issues)

    def test_llm_failure_returns_empty(self):
        """LLM 抛异常时返回空文本 + llm_error issue。"""
        card = _make_card()
        with patch("backend.services.workflows.bsadf.slot_renderer.call_llm_with_usage",
                   new_callable=AsyncMock, side_effect=Exception("LLM 挂了")):
            seg, ret_card, issues = asyncio.run(
                render_slot_to_segment(card=card, rolling_prefix="", scene_setting_text="",
                                       name_registry_block="", state_card_block="",
                                       emotion_curve_text="", style_contract="")
            )
        assert seg.text == ""
        assert any("llm_error" in i for i in issues)

    def test_increment_render_attempts(self):
        """每次调用 render_attempts 应 +1。"""
        card = _make_card()
        assert card.render_attempts == 0
        mock_result = MagicMock()
        mock_result.content = "气动扳手，柴油味，世界庞大，门被踢开。"
        with patch("backend.services.workflows.bsadf.slot_renderer.call_llm_with_usage",
                   new_callable=AsyncMock, return_value=mock_result), \
             patch("backend.services.workflows.bsadf.slot_renderer.measure_ai_taste",
                   return_value=MagicMock(triggered=False)), \
             patch("backend.services.workflows.bsadf.slot_renderer.preprocess_segment",
                   side_effect=lambda t, genre=None: t), \
             patch("backend.services.workflows.bsadf.slot_renderer.sanitize_segment",
                   side_effect=lambda t: t), \
             patch("backend.services.workflows.bsadf.slot_renderer.segment_too_similar",
                   return_value=False), \
             patch("backend.services.workflows.bsadf.slot_renderer.check_segment_against_card",
                   return_value=[]):
            asyncio.run(
                render_slot_to_segment(card=card, rolling_prefix="", scene_setting_text="",
                                       name_registry_block="", state_card_block="",
                                       emotion_curve_text="", style_contract="")
            )
        assert card.render_attempts == 1

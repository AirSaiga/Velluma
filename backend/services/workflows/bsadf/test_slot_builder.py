"""slot_builder 单测：验证 anchor+spine → BeatSlotCard 的纯算法派生。

注意：本测试只覆盖纯算法部分（soft_assign_preconditions、shot_type 映射、
     emotion 采样、target_word_count 分摊）。LLM enrichment 在 P1.4 单独测。
"""
# Velluma - BS-ADF slot_builder tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
import pytest
from unittest.mock import patch, MagicMock

from backend.services.workflows.adf.types import (
    ChapterClimax, ClimaxSpec, Precondition, EmotionCurve, EmotionCurveSample,
    StoryContext, EntryState, ExitExpectation, ChapterPosition,
)
from backend.services.workflows.bsadf.types import BeatSlotCard
from backend.services.workflows.bsadf.slot_builder import (
    build_beat_slots,
    soft_assign_preconditions,
    shot_type_to_beat_type,
    transition_to_rhythm,
    dynamic_spread,
)


def _make_anchor(intensity=7):
    """构造测试用 ChapterClimax。"""
    return ChapterClimax(
        climax=ClimaxSpec(description="测试高潮", intensity=intensity),
        preconditions=[
            Precondition(id="PC_01", category="role", description="角色A登场",
                         must_use_terms=["气动扳手"]),
            Precondition(id="PC_02", category="foreshadow", description="埋伏笔X",
                         must_use_terms=["破旧译本"], min_landing_offset=300),
        ],
        emotion_curve=EmotionCurve(samples=[
            EmotionCurveSample(progress=0.0, register="入口", energy=2),
            EmotionCurveSample(progress=1.0, register="收束", energy=8),
        ]),
    )


def _make_spine():
    return StoryContext(
        entry_state=EntryState(character_positions={"角色A": "本章可涉及"}),
        exit_expectation=ExitExpectation(),
        chapter_position=ChapterPosition(offset_from_volume_climax=5),
        character_arc_advances={},
    )


class TestShotTypeMapping:
    def test_wide_to_establish(self):
        assert shot_type_to_beat_type("wide") == "ESTABLISH"

    def test_close_to_confront(self):
        assert shot_type_to_beat_type("close") == "CONFRONT"

    def test_macro_to_climactic(self):
        assert shot_type_to_beat_type("macro") == "CLIMACTIC"

    def test_full_to_establish(self):
        assert shot_type_to_beat_type("full") == "ESTABLISH"

    def test_medium_to_confront(self):
        assert shot_type_to_beat_type("medium") == "CONFRONT"


class TestTransitionToRhythm:
    def test_cut_to_short_punchy(self):
        assert transition_to_rhythm("cut") == "SHORT_PUNCHY"

    def test_fade_to_layered(self):
        assert transition_to_rhythm("fade") == "LAYERED"

    def test_push_in_to_varied(self):
        assert transition_to_rhythm("push_in") == "VARIED"

    def test_pull_out_to_varied(self):
        assert transition_to_rhythm("pull_out") == "VARIED"

    def test_counter_to_varied(self):
        assert transition_to_rhythm("counter") == "VARIED"


class TestDynamicSpread:
    def test_even_spread(self):
        """5 段 3000 字，每段应约 600 字。"""
        result = dynamic_spread(total_target=3000, segment_index=2, total_segments=5)
        assert 500 <= result <= 700

    def test_first_segment(self):
        result = dynamic_spread(total_target=2500, segment_index=0, total_segments=5)
        assert result == 500

    def test_minimum_floor(self):
        """单段目标不应低于 300。"""
        result = dynamic_spread(total_target=900, segment_index=0, total_segments=5)
        assert result >= 300


class TestSoftAssignPreconditions:
    def test_returns_subset_of_preconditions(self):
        anchor = _make_anchor()
        assigned = soft_assign_preconditions(
            anchor.preconditions, segment_index=2, progress=0.5, total_segments=5
        )
        assert len(assigned) <= len(anchor.preconditions)

    def test_empty_preconditions(self):
        assigned = soft_assign_preconditions([], segment_index=0, progress=0.0, total_segments=5)
        assert assigned == []

    def test_all_pcs_can_assign_to_late_segment(self):
        """后段应能容纳所有 PC（min_landing_offset 已满足）。"""
        anchor = _make_anchor()
        assigned = soft_assign_preconditions(
            anchor.preconditions, segment_index=4, progress=0.9, total_segments=5
        )
        # 后段（index=4）应包含两个 PC（min_landing_offset=300 // 600 = 0，都满足）
        assert len(assigned) == 2


class TestBuildBeatSlots:
    def test_returns_correct_count(self):
        """build_beat_slots 应返回 total_segments 张卡。"""
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=5, target_word_count=3000,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        assert len(cards) == 5

    def test_cards_have_sequential_indices(self):
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=4, target_word_count=2400,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        assert [c.segment_index for c in cards] == [0, 1, 2, 3]

    def test_beat_ids_unique(self):
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=5, target_word_count=3000,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        ids = [c.beat_id for c in cards]
        assert len(ids) == len(set(ids))

    def test_emotion_sampled_from_curve(self):
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=5, target_word_count=3000,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        # 第 0 段应接近 energy=2，末段应接近 energy=8
        assert cards[0].emotion_energy <= cards[-1].emotion_energy

    def test_anchor_actions_seeded_from_preconditions(self):
        """至少有一张卡的 anchor_actions 含 must_use_terms。"""
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=5, target_word_count=3000,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        all_actions = []
        for c in cards:
            all_actions.extend(c.anchor_actions)
        # 至少有一个 must_use_term 出现
        assert any("气动扳手" in a or "破旧译本" in a for a in all_actions)

    def test_locations_seed_sensory_details(self):
        """locations 参数应填入 sensory_details。"""
        anchor = _make_anchor()
        spine = _make_spine()
        loc_mock = MagicMock()
        loc_mock.name = "废弃工厂"
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=3, target_word_count=1800,
            chapter_number=1, locations=[loc_mock], assets=[], chapter=None,
        )
        all_sensory = []
        for c in cards:
            all_sensory.extend(c.sensory_details)
        assert "废弃工厂" in all_sensory

    def test_shot_type_and_transition_populated(self):
        """每张卡都应有 shot_type 和 transition（来自 storyboard）。"""
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=4, target_word_count=2400,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        for c in cards:
            assert c.shot_type in ("wide", "full", "medium", "close", "macro")
            assert c.transition in ("cut", "push_in", "pull_out", "counter", "fade")


# ============================================================================
# P1.4：enrich_slots 测试（mock LLM）
# ============================================================================

import asyncio
from unittest.mock import patch, MagicMock
from backend.services.workflows.bsadf.slot_builder import enrich_slots


class TestEnrichSlots:
    def _make_card(self):
        return BeatSlotCard(
            beat_id="BS_TEST_00", segment_index=0, beat_type="ESTABLISH",
            target_word_count=500, anchor_actions=["扳手"],
            sensory_details=["油污"], shot_type="wide", emotion_register="入口",
        )

    def test_enrich_success_merges_words(self):
        """LLM 返回有效 JSON 时，扩写词应合并进卡。"""
        card = self._make_card()

        mock_result = MagicMock()
        mock_result.content = '{"anchor_actions": ["砸下气动扳手", "抹开油污"], "sensory_details": ["刺鼻柴油味"]}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert "砸下气动扳手" in result[0].anchor_actions
        assert "刺鼻柴油味" in result[0].sensory_details
        # 原种子保留
        assert "扳手" in result[0].anchor_actions

    def test_enrich_failure_keeps_seeds(self):
        """LLM 抛异常时，保留原种子词。"""
        card = self._make_card()
        original_actions = list(card.anchor_actions)

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   side_effect=Exception("LLM 不可用")):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].anchor_actions == original_actions

    def test_enrich_disabled_returns_unchanged(self):
        """enable=False 时直接返回原卡。"""
        card = self._make_card()
        result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=False))
        assert result[0].anchor_actions == ["扳手"]

    def test_enrich_empty_result_keeps_seeds(self):
        """LLM 返回空列表时，保留种子。"""
        card = self._make_card()
        mock_result = MagicMock()
        mock_result.content = '{"anchor_actions": [], "sensory_details": []}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].anchor_actions == ["扳手"]

    def test_enrich_overlong_word_keeps_seeds(self):
        """LLM 返回超长词（>20字）时，保留种子。"""
        card = self._make_card()
        long_word = "这" * 21  # 21 字，超限
        mock_result = MagicMock()
        mock_result.content = f'{{"anchor_actions": ["{long_word}"], "sensory_details": []}}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].anchor_actions == ["扳手"]

    def test_enrich_dedup_preserves_order(self):
        """扩写词 + 原种子去重时，扩写词在前，原种子在后，保序。"""
        card = self._make_card()
        card.anchor_actions = ["扳手", "油污"]  # 原有两个
        mock_result = MagicMock()
        mock_result.content = '{"anchor_actions": ["砸下气动扳手", "扳手"], "sensory_details": []}'
        # 注意 LLM 返回里也有"扳手"——去重后应只出现一次

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        # 扩写词在前，原种子在后，"扳手"只出现一次
        assert result[0].anchor_actions == ["砸下气动扳手", "扳手", "油污"]

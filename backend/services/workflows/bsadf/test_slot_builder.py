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

    def test_each_pc_lands_exactly_one_segment(self):
        """定点分配：每个 PC 全章只落一个目标段（防词表累积膨胀）。"""
        anchor = _make_anchor()
        landed = {}
        for seg in range(5):
            for pc in soft_assign_preconditions(
                anchor.preconditions, segment_index=seg, progress=0.5, total_segments=5
            ):
                landed.setdefault(pc.id, []).append(seg)
        # 两个 PC 都被分配，且各自只落唯一一段
        assert sorted(landed.keys()) == ["PC_01", "PC_02"]
        for pc_id, segs in landed.items():
            assert len(segs) == 1, f"{pc_id} 落到了 {len(segs)} 段：{segs}"


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

    def test_key_anchors_seeded_from_preconditions(self):
        """至少有一张卡的 key_anchors 含 must_use_terms。"""
        anchor = _make_anchor()
        spine = _make_spine()
        cards = build_beat_slots(
            anchor=anchor, spine=spine, total_segments=5, target_word_count=3000,
            chapter_number=1, locations=[], assets=[], chapter=None,
        )
        all_anchors = []
        for c in cards:
            all_anchors.extend(c.key_anchors)
        # 至少有一个 must_use_term 出现
        assert any("气动扳手" in a or "破旧译本" in a for a in all_anchors)

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
            target_word_count=500, key_anchors=["扳手"],
            shot_type="wide", emotion_register="入口",
        )

    def test_enrich_success_merges_words(self):
        """LLM 返回有效 JSON 时，扩写词应合并进卡。"""
        card = self._make_card()

        mock_result = MagicMock()
        mock_result.content = '{"key_anchors": ["砸下气动扳手", "抹开油污"]}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert "砸下气动扳手" in result[0].key_anchors
        # 原种子保留
        assert "扳手" in result[0].key_anchors

    def test_enrich_failure_keeps_seeds(self):
        """LLM 抛异常时，保留原种子词。"""
        card = self._make_card()
        original_anchors = list(card.key_anchors)

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   side_effect=Exception("LLM 不可用")):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].key_anchors == original_anchors

    def test_enrich_disabled_returns_unchanged(self):
        """enable=False 时直接返回原卡。"""
        card = self._make_card()
        result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=False))
        assert result[0].key_anchors == ["扳手"]

    def test_enrich_empty_result_keeps_seeds(self):
        """LLM 返回空列表时，保留种子。"""
        card = self._make_card()
        mock_result = MagicMock()
        mock_result.content = '{"key_anchors": []}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].key_anchors == ["扳手"]

    def test_enrich_overlong_word_keeps_seeds(self):
        """LLM 返回超长词（>20字）时，保留种子。"""
        card = self._make_card()
        long_word = "这" * 21  # 21 字，超限
        mock_result = MagicMock()
        mock_result.content = f'{{"key_anchors": ["{long_word}"]}}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].key_anchors == ["扳手"]

    def test_enrich_dedup_preserves_order(self):
        """扩写词 + 原种子去重时，扩写词在前，原种子在后，保序。"""
        card = self._make_card()
        card.key_anchors = ["扳手", "油污"]  # 原有两个
        mock_result = MagicMock()
        mock_result.content = '{"key_anchors": ["砸下气动扳手", "扳手"]}'
        # 注意 LLM 返回里也有"扳手"——去重后应只出现一次

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        # 扩写词在前，原种子在后，"扳手"只出现一次
        assert result[0].key_anchors == ["砸下气动扳手", "扳手", "油污"]

    def test_enrich_fenced_json_parsed(self):
        """LLM 返回带 markdown 围栏的 JSON（DeepSeek 常见）也应正确解析。

        回归测试：之前用 json.loads 直接解析，遇到 ```json 围栏会报
        'Expecting value: line 1 column 1' 导致 enrichment 全部失败。
        现在用 _extract_json 容错解析。
        """
        card = self._make_card()
        mock_result = MagicMock()
        # 模拟 DeepSeek 带围栏 + 解释文字的输出
        mock_result.content = '好的，这是扩展结果：\n```json\n{"key_anchors": ["砸下气动扳手", "抹开油污"]}\n```\n希望对你有帮助。'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert "砸下气动扳手" in result[0].key_anchors

    def test_enrich_garbage_content_keeps_seeds(self):
        """LLM 返回完全非 JSON 内容（纯文本解释）时，保留种子。"""
        card = self._make_card()
        mock_result = MagicMock()
        mock_result.content = '抱歉，我无法完成这个任务。'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].key_anchors == ["扳手"]


# ============================================================================
# 幻觉闸门加固：空种子禁自由扩写 + 零接地过滤
# ============================================================================

class TestEnrichHallucinationGuards:
    def _make_card(self, anchors=None):
        return BeatSlotCard(
            beat_id="BS_TEST_01", segment_index=1, beat_type="ESTABLISH",
            target_word_count=500, key_anchors=list(anchors if anchors is not None else ["扳手"]),
            shot_type="wide", emotion_register="入口",
        )

    def test_empty_seed_skips_llm(self):
        """种子为空 → 跳过该卡的 LLM 扩写（防凭空发明"雷电劈裂古树"类幻觉）。"""
        card = self._make_card(anchors=[])

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage") as mock_llm:
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        mock_llm.assert_not_called()
        assert result[0].key_anchors == []

    def test_ungrounded_term_stripped(self):
        """零接地词（全部内容词都不在语料）被剥离；接地扩写保留。"""
        card = self._make_card()  # 种子 ["扳手"]
        mock_result = MagicMock()
        # "雷电劈裂古树"：雷电/劈裂/古树均不在语料 → 剥离
        # "砸下气动扳手"：含种子词"扳手" → 保留
        mock_result.content = '{"key_anchors": ["雷电劈裂古树", "砸下气动扳手"]}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert "雷电劈裂古树" not in result[0].key_anchors
        assert "砸下气动扳手" in result[0].key_anchors
        assert "扳手" in result[0].key_anchors

    def test_grounded_expansion_kept(self):
        """合理扩写（至少一个内容词接地，如大纲"工头"→"工头摘下黄色安全帽"）保留。"""
        card = self._make_card()
        mock_result = MagicMock()
        mock_result.content = '{"key_anchors": ["工头摘下黄色安全帽"]}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots(
                [card], enable=True, guard_context="工头走进车间，宣布加急订单",
            ))

        assert "工头摘下黄色安全帽" in result[0].key_anchors

    def test_plot_keyword_gate_not_regressed(self):
        """第一道剧情关键词闸门不回归：含未授权剧情级关键词的词仍被剥离
        （即使它有接地内容词，如"机甲变异融合"的"机甲"接地）。"""
        card = self._make_card(anchors=["机甲"])
        mock_result = MagicMock()
        mock_result.content = '{"key_anchors": ["机甲变异融合"]}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert "机甲变异融合" not in result[0].key_anchors
        assert result[0].key_anchors == ["机甲"]

    def test_cross_genre_imagery_stripped(self):
        """跨题材意象（中世纪"马蹄溅起泥水/火把点燃草垛"混入机甲场景）零接地被剥离。"""
        card = self._make_card(anchors=["机甲"])
        mock_result = MagicMock()
        mock_result.content = '{"key_anchors": ["马蹄溅起泥水", "火把点燃草垛"]}'

        with patch("backend.services.workflows.bsadf.slot_builder.call_llm_with_usage",
                   return_value=mock_result):
            result = asyncio.get_event_loop().run_until_complete(enrich_slots([card], enable=True))

        assert result[0].key_anchors == ["机甲"]


def test_dynamic_spread_min_500():
    from backend.services.workflows.bsadf.slot_builder import dynamic_spread
    assert dynamic_spread(1500, 0, 5) == 500
    assert dynamic_spread(5000, 0, 5) == 1000
    assert dynamic_spread(2500, 0, 5) == 500


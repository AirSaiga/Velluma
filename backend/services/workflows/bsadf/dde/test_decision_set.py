"""DDE 章节级剧情分叉（ChapterDecisionSet）单测。

覆盖（mock LLM）：
- 无岔路放行：LLM 判 has_story_branch=false / 输出被闸门滤空 → 空集放行
  （无岔路放行是特性不是失败，不再有 fallback 保底出题）
- 节点数 >2 截断
- default_option 缺失/非法时兜底 options[0]
- beat_id 无效（不在本章槽位卡中）的节点被丢弃
- LLM 异常 → 空集放行
- SlotMutator：写 branch_directive 不碰硬契约（core_plot_event/key_anchors/
  text_carrier 保持不变）；skipped 走 default_option；custom: 自定义走向
- Loop1 缺口提示节点（source="loop1_gap"）：force_branch_gaps 注入标记 source；
  mutator 仅作者 custom: 补充文本才写 directive，默认/跳过/空补充一律不注入
  （防提示语当走向污染渲染 prompt）；source 字段 to_dict/from_dict 往返
"""
# Velluma - DDE decision_set tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
import json
from unittest.mock import patch, MagicMock, AsyncMock

from backend.services.workflows.bsadf.types import BeatSlotCard
from backend.services.workflows.bsadf.dde.types import (
    BranchOption,
    ChapterDecisionSet,
    StoryBranch,
    story_branch_from_dict,
    story_branch_to_dict,
)
from backend.services.workflows.bsadf.dde.decision_card_generator import (
    generate_chapter_decision_set,
)
from backend.services.workflows.bsadf.dde.slot_mutator import mutate_slot_cards


def _run(coro):
    """在独立 loop 里跑协程（不用 asyncio.run——它会把事件循环策略的
    _set_called 置位，导致同进程后续测试的 asyncio.get_event_loop() 抛
    RuntimeError，典型症状是 test_downgrade 在本文件之后运行时报错）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ============================================================
# 工具：构造测试数据
# ============================================================

def _make_cards(n=3):
    return [
        BeatSlotCard(
            beat_id=f"BS_CH1_BEAT_{i:02d}",
            segment_index=i,
            beat_type="CONFRONT",
            target_word_count=500,
            core_plot_event=f"转折{i}",
            key_anchors=[f"锚点{i}"],
            text_carrier=f"台词{i}",
            outline_beat=f"节拍{i}",
        )
        for i in range(n)
    ]


def _make_llm_args(cards):
    """generate_chapter_decision_set 的 chapter/anchor/spine mock。"""
    chapter = MagicMock()
    chapter.outline_text = "林尘被工头恶意挑衅，忍了下来，暗中记下班头的罪证。"
    anchor = MagicMock()
    anchor.climax.description = "林尘当众揭穿班头"
    anchor.preconditions = []
    spine = MagicMock()
    spine.chapter_position = None
    return chapter, anchor, spine, cards


def _node_json(beat_id, node_id_suffix="", default="A", n_options=2):
    options = [
        {"option_id": chr(ord("A") + k), "label": f"走向{k}", "plot_impact": f"后果{k}"}
        for k in range(n_options)
    ]
    return {
        "beat_id": beat_id,
        "node_title": f"岔路{node_id_suffix}",
        "options": options,
        "default_option": default,
    }


def _mock_llm(content: str):
    mock_result = MagicMock()
    mock_result.content = content
    return patch(
        "backend.services.workflows.bsadf.dde.decision_card_generator.call_llm_with_usage",
        new_callable=AsyncMock, return_value=mock_result,
    )


# ============================================================
# 生成器：无岔路放行与代码闸门
# ============================================================

class TestGenerateChapterDecisionSet:
    def test_no_branch_passes_through(self):
        """LLM 判无岔路 → 空 DecisionSet 放行（特性，不是失败）。"""
        cards = _make_cards(3)
        chapter, anchor, spine, cards = _make_llm_args(cards)
        content = json.dumps({"has_story_branch": False, "decision_nodes": []})

        with _mock_llm(content):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
            ))
        assert ds.has_story_branch is False
        assert ds.decision_nodes == []

    def test_nodes_over_two_truncated(self):
        """LLM 返回 3 个节点 → 代码闸门截断到 2 个。"""
        cards = _make_cards(3)
        chapter, anchor, spine, cards = _make_llm_args(cards)
        content = json.dumps({
            "has_story_branch": True,
            "decision_nodes": [
                _node_json(cards[0].beat_id, "1"),
                _node_json(cards[1].beat_id, "2"),
                _node_json(cards[2].beat_id, "3"),
            ],
        })

        with _mock_llm(content):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
            ))
        assert ds.has_story_branch is True
        assert len(ds.decision_nodes) == 2
        assert ds.decision_nodes[0].beat_id == cards[0].beat_id
        assert ds.decision_nodes[1].beat_id == cards[1].beat_id

    def test_invalid_default_option_falls_back_to_first(self):
        """default_option 缺失/非法 → 兜底 options[0]。"""
        cards = _make_cards(1)
        chapter, anchor, spine, cards = _make_llm_args(cards)
        content = json.dumps({
            "has_story_branch": True,
            "decision_nodes": [
                _node_json(cards[0].beat_id, "1", default="Z"),  # 非法 id
                _node_json(cards[0].beat_id, "2", default=""),    # 缺失
            ],
        })

        with _mock_llm(content):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
            ))
        assert len(ds.decision_nodes) == 2
        for node in ds.decision_nodes:
            assert node.default_option == node.options[0].option_id

    def test_unknown_beat_id_node_dropped(self):
        """beat_id 不在本章槽位卡中的节点被丢弃（防 LLM 漂移出无效挂载点）。"""
        cards = _make_cards(1)
        chapter, anchor, spine, cards = _make_llm_args(cards)
        content = json.dumps({
            "has_story_branch": True,
            "decision_nodes": [
                _node_json("BS_CH99_BEAT_00", "幽灵节点"),
            ],
        })

        with _mock_llm(content):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
            ))
        # 节点全部被滤空 → 等价无岔路放行
        assert ds.has_story_branch is False
        assert ds.decision_nodes == []

    def test_llm_exception_passes_through_empty(self):
        """LLM 抛异常 → 空 DecisionSet 放行（不再有 fallback 保底出题）。"""
        cards = _make_cards(1)
        chapter, anchor, spine, cards = _make_llm_args(cards)

        with patch(
            "backend.services.workflows.bsadf.dde.decision_card_generator.call_llm_with_usage",
            new_callable=AsyncMock, side_effect=Exception("LLM 挂了"),
        ):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
            ))
        assert ds.has_story_branch is False
        assert ds.decision_nodes == []

    def test_garbage_content_passes_through_empty(self):
        """LLM 返回完全非 JSON 内容 → 空 DecisionSet 放行。"""
        cards = _make_cards(1)
        chapter, anchor, spine, cards = _make_llm_args(cards)

        with _mock_llm("抱歉，我无法完成这个任务。"):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
            ))
        assert ds.has_story_branch is False

    def test_force_branch_gaps_injected_when_llm_says_no_branch(self):
        """Loop 1 macro 缺口：即使 LLM 判无岔路，缺口仍包装成 StoryBranch
        注入 decision_set，并强制 has_story_branch=True。"""
        cards = _make_cards(3)
        chapter, anchor, spine, cards = _make_llm_args(cards)
        content = json.dumps({"has_story_branch": False, "decision_nodes": []})
        gaps = [
            {"description": "大纲未明确角色动机", "suggested_fill": "补充主角动机"},
            {"description": "无关系转折", "suggested_fill": "补充角色关系演变"},
        ]

        with _mock_llm(content):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
                force_branch_gaps=gaps,
            ))
        assert ds.has_story_branch is True
        assert len(ds.decision_nodes) == 2
        # 缺口分支挂在第一张卡上
        assert ds.decision_nodes[0].beat_id == cards[0].beat_id
        assert ds.decision_nodes[0].default_option == "A"
        assert ds.decision_nodes[0].options[0].option_id == "A"
        # 缺口注入节点必须标记 source="loop1_gap"（下游 mutator/岔路门据此
        # 区分"提示语节点"与真实走向岔路，只有作者 custom: 补充才写 directive）
        assert all(n.source == "loop1_gap" for n in ds.decision_nodes)

    def test_force_branch_gaps_none_keeps_empty(self):
        """force_branch_gaps=None → 行为不变（无岔路放行）。"""
        cards = _make_cards(1)
        chapter, anchor, spine, cards = _make_llm_args(cards)
        content = json.dumps({"has_story_branch": False, "decision_nodes": []})

        with _mock_llm(content):
            ds = _run(generate_chapter_decision_set(
                chapter=chapter, anchor=anchor, spine=spine, cards=cards,
                force_branch_gaps=None,
            ))
        assert ds.has_story_branch is False
        assert ds.decision_nodes == []


# ============================================================
# SlotMutator：branch_directive 突变
# ============================================================

def _make_decision_set(beat_id) -> ChapterDecisionSet:
    return ChapterDecisionSet(
        has_story_branch=True,
        decision_nodes=[
            StoryBranch(
                beat_id=beat_id,
                node_title="面对挑衅的应对分支",
                options=[
                    BranchOption(option_id="A", label="当场反抗", plot_impact="被关禁闭"),
                    BranchOption(option_id="B", label="忍辱负重", plot_impact="暗中收集证据"),
                ],
                default_option="B",
            )
        ],
    )


class TestMutateSlotCards:
    def test_mutation_writes_branch_directive_only(self):
        """选定 option → branch_directive 写入 f"{label}。{plot_impact}"；
        绝不触碰 core_plot_event/key_anchors/text_carrier 硬契约。"""
        cards = _make_cards(2)
        ds = _make_decision_set(cards[0].beat_id)
        # 记录硬契约原值
        original_event = cards[0].core_plot_event
        original_anchors = list(cards[0].key_anchors)
        original_carrier = cards[0].text_carrier

        result = mutate_slot_cards(
            cards=cards,
            decision_set=ds,
            branch_choices={cards[0].beat_id: "A"},
        )

        assert result[0].branch_directive == "当场反抗。被关禁闭"
        assert result[0].edited is True
        assert result[0].edit_count == 1
        # 硬契约零污染
        assert result[0].core_plot_event == original_event
        assert result[0].key_anchors == original_anchors
        assert result[0].text_carrier == original_carrier
        # 未挂载分支的卡不受影响
        assert result[1].branch_directive == ""
        assert result[1].edited is False

    def test_skipped_uses_default_option(self):
        """skipped=True（作者跳过/Track A 静默应用）→ 全部走 default_option。"""
        cards = _make_cards(2)
        ds = _make_decision_set(cards[1].beat_id)

        result = mutate_slot_cards(cards=cards, decision_set=ds, skipped=True)

        # default_option=B
        assert result[1].branch_directive == "忍辱负重。暗中收集证据"
        assert result[0].branch_directive == ""

    def test_unanswered_node_uses_default_option(self):
        """branch_choices 未覆盖的节点 → 走 default_option（默认是主路径）。"""
        cards = _make_cards(1)
        ds = _make_decision_set(cards[0].beat_id)

        result = mutate_slot_cards(
            cards=cards, decision_set=ds, branch_choices={}, skipped=False,
        )
        assert result[0].branch_directive == "忍辱负重。暗中收集证据"

    def test_custom_choice_writes_custom_text(self):
        """custom: 前缀自定义走向 → 直接写入 branch_directive。"""
        cards = _make_cards(1)
        ds = _make_decision_set(cards[0].beat_id)

        result = mutate_slot_cards(
            cards=cards,
            decision_set=ds,
            branch_choices={cards[0].beat_id: "custom:假意顺从，夜里放火烧掉账房"},
        )
        assert result[0].branch_directive == "假意顺从，夜里放火烧掉账房"
        # 硬契约不碰
        assert result[0].core_plot_event == "转折0"

    def test_empty_decision_set_noop(self):
        """空 DecisionSet（无岔路）→ 原样返回，不突变。"""
        cards = _make_cards(1)
        result = mutate_slot_cards(
            cards=cards, decision_set=ChapterDecisionSet(), skipped=True,
        )
        assert result[0].branch_directive == ""
        assert result[0].edited is False


# ============================================================
# StoryBranch.source 序列化往返
# ============================================================

class TestStoryBranchSourceRoundTrip:
    def test_source_round_trip_preserved(self):
        """to_dict → from_dict：source 字段往返无损（loop1_gap 标记不丢）。"""
        node = StoryBranch(
            beat_id="BS_CH1_BEAT_00",
            node_title="大纲缺口：角色动机不明",
            options=[BranchOption(option_id="A", label="建议补充：主角动机")],
            default_option="A",
            source="loop1_gap",
        )
        restored = story_branch_from_dict(story_branch_to_dict(node))
        assert restored.source == "loop1_gap"
        assert restored.beat_id == node.beat_id
        assert restored.options[0].label == "建议补充：主角动机"

    def test_source_defaults_to_dde(self):
        """缺省 source → "dde"；旧 pending 载荷（无 source 键）→ 按 "dde" 维持旧行为。"""
        node = StoryBranch(beat_id="BS_CH1_BEAT_00", node_title="岔路")
        assert node.source == "dde"
        # 旧载荷无 source 字段
        legacy = {
            "beat_id": "BS_CH1_BEAT_00",
            "node_title": "岔路",
            "options": [],
            "default_option": "",
        }
        assert story_branch_from_dict(legacy).source == "dde"
        # 显式空串/None 也回落 "dde"（防脏数据击穿 mutator 的 == 判定）
        assert story_branch_from_dict({**legacy, "source": ""}).source == "dde"


# ============================================================
# SlotMutator：Loop1 缺口提示节点（source="loop1_gap"）
# ============================================================

def _make_gap_decision_set(beat_id) -> ChapterDecisionSet:
    """Loop1 大纲自检缺口注入的单选项提示节点。"""
    return ChapterDecisionSet(
        has_story_branch=True,
        decision_nodes=[
            StoryBranch(
                beat_id=beat_id,
                node_title="大纲缺口：大纲未明确角色动机，可能影响剧情说服力",
                options=[
                    BranchOption(
                        option_id="A",
                        label="建议补充：主角为何采取此行动",
                    ),
                ],
                default_option="A",
                source="loop1_gap",
            )
        ],
    )


class TestGapNodeMutator:
    def test_gap_node_skipped_no_directive(self):
        """skipped=True（Track A 静默应用）→ 缺口节点不注入提示语。"""
        cards = _make_cards(1)
        ds = _make_gap_decision_set(cards[0].beat_id)

        result = mutate_slot_cards(cards=cards, decision_set=ds, skipped=True)

        assert result[0].branch_directive == ""
        assert result[0].edited is False

    def test_gap_node_unanswered_no_directive(self):
        """Track B 未作答/未覆盖 → 缺口节点不写 directive（提示语不是走向）。"""
        cards = _make_cards(1)
        ds = _make_gap_decision_set(cards[0].beat_id)

        result = mutate_slot_cards(
            cards=cards, decision_set=ds, branch_choices={}, skipped=False,
        )

        assert result[0].branch_directive == ""
        assert result[0].edited is False

    def test_gap_node_empty_custom_no_directive(self):
        """custom: 但文本为空 → 不写 directive（空补充视为放弃补充，
        严防 _resolve_option 回落默认把提示语注入）。"""
        cards = _make_cards(1)
        ds = _make_gap_decision_set(cards[0].beat_id)

        result = mutate_slot_cards(
            cards=cards,
            decision_set=ds,
            branch_choices={cards[0].beat_id: "custom:   "},
        )

        assert result[0].branch_directive == ""
        assert result[0].edited is False

    def test_gap_node_custom_text_writes_directive(self):
        """作者 custom: 补充文本 → directive=作者文本，硬契约不碰。"""
        cards = _make_cards(1)
        ds = _make_gap_decision_set(cards[0].beat_id)

        result = mutate_slot_cards(
            cards=cards,
            decision_set=ds,
            branch_choices={cards[0].beat_id: "custom:林尘为凑妹妹医药费只能忍"},
        )

        assert result[0].branch_directive == "林尘为凑妹妹医药费只能忍"
        assert result[0].edited is True
        assert result[0].core_plot_event == "转折0"
        assert result[0].key_anchors == ["锚点0"]
        assert result[0].text_carrier == "台词0"

    def test_normal_node_alongside_gap_node_unaffected(self):
        """混合决策集：普通 DDE 节点行为不变（default 照走），缺口节点仍豁免。"""
        cards = _make_cards(2)
        ds = ChapterDecisionSet(
            has_story_branch=True,
            decision_nodes=[
                StoryBranch(
                    beat_id=cards[0].beat_id,
                    node_title="面对挑衅的应对分支",
                    options=[
                        BranchOption(option_id="A", label="当场反抗", plot_impact="被关禁闭"),
                        BranchOption(option_id="B", label="忍辱负重", plot_impact="暗中收集证据"),
                    ],
                    default_option="B",
                ),
                StoryBranch(
                    beat_id=cards[1].beat_id,
                    node_title="大纲缺口：关系转折不明",
                    options=[BranchOption(option_id="A", label="建议补充：关系演变")],
                    default_option="A",
                    source="loop1_gap",
                ),
            ],
        )

        result = mutate_slot_cards(cards=cards, decision_set=ds, skipped=True)

        # 普通节点：skipped → default_option 照常注入
        assert result[0].branch_directive == "忍辱负重。暗中收集证据"
        # 缺口节点：skipped → 不注入
        assert result[1].branch_directive == ""
        assert result[1].edited is False

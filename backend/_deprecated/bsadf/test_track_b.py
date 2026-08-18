"""Track B 作者介入握手单测。

覆盖：
1. _PENDING_BEAT_SLOTS 的 store/load/pop/cleanup（纯函数，照搬 refinery _PENDING 模式）
2. BSAdfWorkflow.execute(pause_after_slot_build=True) 在 Phase 4a 后提前返回，
   result.debug_info 含 paused=True + beat_slots + paused_spine/anchor/tier/wc/seg
3. resume_from_slots 从编辑后的卡继续，复用 _run_render_and_postprocess
   （不进 1-3 + 4a，直接进 4c-7）

注意：本测试 patch 掉 Phase 1-3 + 4a/b 的 LLM/算法（返回固定数据），
     验证的是"暂停点 / 恢复点 / debug_info 契约"，而非渲染质量（后者在 P1.4 测）。
"""
# Velluma - BS-ADF Track B tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from backend.services.workflows.adf.types import (
    ChapterClimax,
    ClimaxSpec,
    EmotionCurve,
    EmotionCurveSample,
    StoryContext,
    Precondition,
    SegmentResult,
)
from backend.services.workflows.bsadf.bsadf_workflow import BSAdfWorkflow
from backend.services.workflows.bsadf.types import (
    BeatSlotCard,
    beat_slot_to_dict,
    beat_slot_from_dict,
)
from backend.routes.chapter_generation import bsadf as bsadf_route


# ============================================================
# 工具：构造测试用 workflow + 数据
# ============================================================

def _make_anchor(intensity=7):
    """构造测试用 ChapterClimax。"""
    return ChapterClimax(
        climax=ClimaxSpec(description="测试高潮", intensity=intensity),
        preconditions=[
            Precondition(id="PC_01", category="role", description="角色A登场",
                         must_use_terms=["气动扳手"]),
        ],
        emotion_curve=EmotionCurve(samples=[
            EmotionCurveSample(progress=0.0, register="入口", energy=2),
            EmotionCurveSample(progress=1.0, register="收束", energy=8),
        ]),
    )


def _make_spine():
    return StoryContext()


def _make_cards(n=3):
    return [
        BeatSlotCard(
            beat_id=f"BS_TEST_{i:02d}",
            segment_index=i,
            beat_type="ESTABLISH" if i == 0 else "CONFRONT",
            target_word_count=500,
            key_anchors=[f"动作{i}"],
        )
        for i in range(n)
    ]


def _make_workflow():
    """构造最小 BSAdfWorkflow（chapter/book/request 都是 MagicMock）。"""
    chapter = MagicMock()
    chapter.number = 1
    chapter.outline_text = "测试大纲"
    book = MagicMock()
    book.genre = None
    request = MagicMock()
    request.tier = "auto"
    request.target_word_count = None
    request.max_segments = 6
    request.enable_spine = True
    request.enable_slot_enrichment = True
    request.enable_anchor_audit = False  # 关闭以减少 mock 复杂度
    request.enable_refinement = False
    request.enable_consistency_guard = False
    request.enable_state_tracker = False
    request.enable_edit_verify = False
    request.enable_beat_coverage = False
    request.enable_dde = False  # DDE 流程在 TestDdeFlow 单独测，这里关闭减少 mock 复杂度
    request.user_tier_hint = None
    request.author_intent = None
    request.expectation_actions = None
    return BSAdfWorkflow(
        chapter=chapter,
        book=book,
        chapter_card=None,
        entities=[],
        style_card=None,
        request=request,
    )


# ============================================================
# 测试组 1：_PENDING_BEAT_SLOTS 纯函数（store/load/pop/cleanup/TTL）
# ============================================================

class TestPendingBeatSlots:
    """验证 _PENDING_BEAT_SLOTS 的 store/load/pop/cleanup/expiry。"""

    def setup_method(self):
        """每个测试前清空 _PENDING_BEAT_SLOTS（模块级全局，避免测试间污染）。"""
        bsadf_route._PENDING_BEAT_SLOTS.clear()

    def teardown_method(self):
        bsadf_route._PENDING_BEAT_SLOTS.clear()

    def test_store_then_load_returns_entry(self):
        """store 后 load 能取回 cards + ctx。"""
        cards = _make_cards(2)
        ctx = {"spine": _make_spine(), "tier": "turn"}
        bsadf_route._store_pending_beats("run_1", cards, ctx)

        loaded = bsadf_route._load_pending_beats("run_1")
        assert loaded is not None
        assert loaded["cards"] is cards
        assert loaded["ctx"]["tier"] == "turn"
        assert "expires" in loaded

    def test_load_unknown_returns_none(self):
        """load 未知的 run_id 返回 None。"""
        assert bsadf_route._load_pending_beats("nope") is None

    def test_pop_removes_entry(self):
        """pop 后 entry 移除，再 load 返回 None。"""
        cards = _make_cards(1)
        bsadf_route._store_pending_beats("run_2", cards, {"tier": "auto"})
        popped = bsadf_route._pop_pending_beats("run_2")
        assert popped is not None
        assert popped["cards"] is cards
        assert bsadf_route._load_pending_beats("run_2") is None
        # 二次 pop 返回 None
        assert bsadf_route._pop_pending_beats("run_2") is None

    def test_cleanup_expired_removes_old_entries(self):
        """过期的 entry 被 cleanup 清除。"""
        bsadf_route._store_pending_beats("fresh", _make_cards(1), {"tier": "auto"})
        # 手动塞一个过期 entry
        bsadf_route._PENDING_BEAT_SLOTS["stale"] = {
            "cards": _make_cards(1),
            "ctx": {"tier": "auto"},
            "expires": datetime.now() - timedelta(hours=2),
        }
        # load 触发 cleanup
        bsadf_route._load_pending_beats("fresh")
        assert "stale" not in bsadf_route._PENDING_BEAT_SLOTS
        assert "fresh" in bsadf_route._PENDING_BEAT_SLOTS

    def test_ttl_is_one_hour(self):
        """_PENDING_TTL = 1 小时（与 refinery 对齐）。"""
        assert bsadf_route._PENDING_TTL == timedelta(hours=1)


# ============================================================
# 测试组 2：execute(pause_after_slot_build=True) 暂停契约
# ============================================================

class TestPauseAfterSlotBuild:
    """验证 execute 在 Phase 4a 之后、4c 之前提前返回。"""

    def test_pause_returns_with_paused_flag_and_context(self):
        """pause=True 时 result.debug_info.paused=True，含 spine/anchor/tier 等恢复字段。"""
        wf = _make_workflow()
        anchor = _make_anchor(7)
        cards = _make_cards(3)

        # patch Phase 1/2/3/4a：返回固定数据，跳过 LLM
        with patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_story_context",
            new_callable=AsyncMock, return_value=_make_spine(),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.design_chapter_climax",
            new_callable=AsyncMock, return_value=anchor,
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_beat_slots",
            return_value=cards,
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.enrich_slots",
            new_callable=AsyncMock, return_value=None,
        ), patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ) as mock_post:
            result = asyncio.run(
                wf.execute(pause_after_slot_build=True)
            )

        # 暂停标志
        assert result.debug_info.get("paused") is True
        # 槽位卡序列化
        slots = result.debug_info.get("beat_slots", [])
        assert len(slots) == 3
        assert all("beat_id" in s for s in slots)
        # 恢复上下文齐全
        assert result.debug_info.get("paused_spine") is not None
        assert result.debug_info.get("paused_anchor") is anchor
        # tier 由 decide_tier(intensity=7) 实算，断言非空字符串即可（避免耦合档位规则）
        paused_tier = result.debug_info.get("paused_tier")
        assert isinstance(paused_tier, str) and paused_tier
        assert isinstance(result.debug_info.get("paused_target_word_count"), int)
        assert isinstance(result.debug_info.get("paused_max_segments"), int)
        # tier_decision 在暂停时也填了（route 层要读），tier 与 paused_tier 一致
        assert result.tier_decision.get("tier") == paused_tier
        # 4c-7 未被调用
        mock_post.assert_not_called()

    def test_pause_does_not_emit_beat_slots_built_event(self):
        """暂停模式（步进/Track B）工作流不再发 BEAT_SLOTS_BUILT。

        契约变更：pause_after_slot_build=True 时由 route 层补发带 run_id 的
        权威持卡事件（步进=STEPPING_INITIALIZED，Track B=route 版 BEAT_SLOTS_BUILT），
        工作流内同名无 run_id 事件已门控关闭（bsadf_workflow.py Phase 4b），
        避免前端收到两个同名语义事件。Track A（非暂停）仍发，见
        test_no_pause_runs_full_pipeline 的事件断言。
        """
        wf = _make_workflow()
        events = []

        async def cb(event, data):
            events.append((event, data))

        with patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_story_context",
            new_callable=AsyncMock, return_value=_make_spine(),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.design_chapter_climax",
            new_callable=AsyncMock, return_value=_make_anchor(),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_beat_slots",
            return_value=_make_cards(2),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.enrich_slots",
            new_callable=AsyncMock, return_value=None,
        ):
            asyncio.run(
                wf.execute(progress_callback=cb, pause_after_slot_build=True)
            )

        event_names = [e for e, _ in events]
        assert "BEAT_SLOTS_BUILT" not in event_names

    def test_no_pause_runs_full_pipeline(self):
        """pause=False（Track A）时 _run_render_and_postprocess 被调用（跑完全程）。"""
        wf = _make_workflow()
        with patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_story_context",
            new_callable=AsyncMock, return_value=_make_spine(),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.design_chapter_climax",
            new_callable=AsyncMock, return_value=_make_anchor(),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_beat_slots",
            return_value=_make_cards(2),
        ), patch(
            "backend.services.workflows.bsadf.bsadf_workflow.enrich_slots",
            new_callable=AsyncMock, return_value=None,
        ), patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ) as mock_post:
            result = asyncio.run(
                wf.execute(pause_after_slot_build=False)
            )
        # 未暂停
        assert result.debug_info.get("paused") is None
        # 4c-7 被调用
        mock_post.assert_called_once()


# ============================================================
# 测试组 3：resume_from_slots 从编辑卡继续
# ============================================================

class TestResumeFromSlots:
    """验证 resume_from_slots 跳过 1-3+4a，直接进 4c-7。"""

    def test_resume_calls_run_render_and_postprocess(self):
        """resume 把编辑后的卡传给 _run_render_and_postprocess。"""
        wf = _make_workflow()
        spine = _make_spine()
        anchor = _make_anchor()
        edited_cards = _make_cards(3)
        # 标记作者编辑
        for c in edited_cards:
            c.edited = True

        with patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ) as mock_post:
            result = asyncio.run(
                wf.resume_from_slots(
                    edited_cards=edited_cards,
                    spine=spine,
                    anchor=anchor,
                    tier="climax",
                    target_word_count=3000,
                    max_segments=3,
                )
            )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        # 编辑后的卡透传
        assert call_kwargs["cards"] is edited_cards
        assert call_kwargs["spine"] is spine
        assert call_kwargs["anchor"] is anchor
        assert call_kwargs["tier"] == "climax"
        assert call_kwargs["target_word_count"] == 3000
        assert call_kwargs["max_segments"] == 3
        # result.debug_info.beat_slots 已序列化
        assert len(result.debug_info["beat_slots"]) == 3
        # tier_decision 在 resume 时也填了
        assert result.tier_decision["tier"] == "climax"

    def test_resume_emits_render_resumed_event(self):
        """resume 进入时推 BSADF_STAGE(RENDER_RESUMED) 事件。"""
        wf = _make_workflow()
        events = []

        async def cb(event, data):
            events.append((event, data))

        with patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ):
            asyncio.run(
                wf.resume_from_slots(
                    edited_cards=_make_cards(2),
                    spine=_make_spine(),
                    anchor=_make_anchor(),
                    tier="turn",
                    target_word_count=2000,
                    max_segments=2,
                    progress_callback=cb,
                )
            )

        event_names = [e for e, _ in events]
        assert "BSADF_STAGE" in event_names
        stage_evt = next(d for e, d in events if e == "BSADF_STAGE")
        assert stage_evt["stage"] == "RENDER_RESUMED"
        assert stage_evt["count"] == 2


# ============================================================
# 测试组 4：BeatSlotCard 序列化往返（resume 的基础契约）
# ============================================================

class TestBeatSlotSerialization:
    """验证 beat_slot_to_dict / beat_slot_from_dict 往返保持字段。

    这是 /confirm-beats 把 Pydantic BeatSlotSchema → dict → BeatSlotCard 的基础契约。
    """

    def test_roundtrip_preserves_fields(self):
        card = BeatSlotCard(
            beat_id="BS_RT_01",
            segment_index=1,
            beat_type="CONFRONT",
            target_word_count=600,
            key_anchors=["挥刀", "翻滚"],
            text_carrier="「去死」",
            core_plot_event="伏击",
            branch_directive="忍辱负重。后续剧情会更压抑",
            emotion_register="愤怒",
            emotion_energy=8,
            landed_preconditions=["PC_01"],
            shot_type="close",
            transition="cut",
        )
        d = beat_slot_to_dict(card)
        restored = beat_slot_from_dict(d)
        assert restored.beat_id == card.beat_id
        assert restored.beat_type == card.beat_type
        assert restored.key_anchors == card.key_anchors
        assert restored.core_plot_event == card.core_plot_event
        assert restored.branch_directive == card.branch_directive
        assert restored.text_carrier == card.text_carrier
        assert restored.emotion_energy == card.emotion_energy
        assert restored.shot_type == card.shot_type


# ============================================================
# 测试组 5：DDE 流程穿透（Track A 静默应用 / Track B 单暂停内嵌）
# ============================================================

from backend.services.workflows.bsadf.dde.types import (
    BranchOption,
    ChapterDecisionSet,
    StoryBranch,
)


def _make_decision_set(beat_id: str, has_branch: bool = True) -> ChapterDecisionSet:
    """构造测试用 ChapterDecisionSet（一个分支节点，默认 B）。"""
    if not has_branch:
        return ChapterDecisionSet(has_story_branch=False, decision_nodes=[])
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


def _dde_patches(spine, anchor, cards, decision_set):
    """统一的 patch 上下文：Phase 1-3 + 4a/b + DDE 全部 mock 掉。"""
    return (
        patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_story_context",
            new_callable=AsyncMock, return_value=spine,
        ),
        patch(
            "backend.services.workflows.bsadf.bsadf_workflow.design_chapter_climax",
            new_callable=AsyncMock, return_value=anchor,
        ),
        patch(
            "backend.services.workflows.bsadf.bsadf_workflow.build_beat_slots",
            return_value=cards,
        ),
        patch(
            "backend.services.workflows.bsadf.bsadf_workflow.enrich_slots",
            new_callable=AsyncMock, return_value=None,
        ),
        patch(
            "backend.services.workflows.bsadf.bsadf_workflow.generate_chapter_decision_set",
            new_callable=AsyncMock, return_value=decision_set,
        ),
    )


class TestDdeFlow:
    """验证 DDE 章节级分叉在 Track A/B 的穿透行为。"""

    def _make_dde_workflow(self):
        wf = _make_workflow()
        wf.request.enable_dde = True
        return wf

    def test_track_a_silent_apply_default_branch(self):
        """Track A：有分支时立即用 default_option 静默突变（写 branch_directive），
        emit DDE_AUTO_APPLIED，全程不暂停（4c-7 照常执行）。"""
        wf = self._make_dde_workflow()
        cards = _make_cards(3)
        decision_set = _make_decision_set(cards[0].beat_id)
        events = []

        async def cb(event, data):
            events.append((event, data))

        p1, p2, p3, p4, p5 = _dde_patches(_make_spine(), _make_anchor(), cards, decision_set)
        with p1, p2, p3, p4, p5, patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ) as mock_post:
            result = asyncio.run(
                wf.execute(progress_callback=cb, pause_after_slot_build=False)
            )

        # 静默突变：default_option=B 的 label + plot_impact 写入 branch_directive
        assert cards[0].branch_directive == "忍辱负重。暗中收集证据"
        # 其余卡不受影响
        assert cards[1].branch_directive == ""
        # DDE_AUTO_APPLIED 事件（含 decision_set 与 applied 映射）
        event_names = [e for e, _ in events]
        assert "DDE_AUTO_APPLIED" in event_names
        dde_evt = next(d for e, d in events if e == "DDE_AUTO_APPLIED")
        assert dde_evt["has_story_branch"] is True
        assert dde_evt["applied"] == {cards[0].beat_id: "B"}
        assert dde_evt["decision_set"]["decision_nodes"][0]["default_option"] == "B"
        # 不暂停，4c-7 照常执行
        assert result.debug_info.get("paused") is None
        mock_post.assert_called_once()
        # debug_info 快照含 branch_directive 与 decision_set
        assert result.debug_info["beat_slots"][0]["branch_directive"] == "忍辱负重。暗中收集证据"
        assert result.debug_info["decision_set"]["has_story_branch"] is True

    def test_track_a_no_branch_emits_auto_applied_false(self):
        """Track A：无岔路时 emit DDE_AUTO_APPLIED(has_story_branch=false)，不突变。"""
        wf = self._make_dde_workflow()
        cards = _make_cards(2)
        decision_set = _make_decision_set(cards[0].beat_id, has_branch=False)
        events = []

        async def cb(event, data):
            events.append((event, data))

        p1, p2, p3, p4, p5 = _dde_patches(_make_spine(), _make_anchor(), cards, decision_set)
        with p1, p2, p3, p4, p5, patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ) as mock_post:
            asyncio.run(wf.execute(progress_callback=cb, pause_after_slot_build=False))

        dde_evt = next(d for e, d in events if e == "DDE_AUTO_APPLIED")
        assert dde_evt["has_story_branch"] is False
        assert dde_evt["applied"] == {}
        assert all(c.branch_directive == "" for c in cards)
        mock_post.assert_called_once()

    def test_track_b_single_pause_embeds_decision_set(self):
        """Track B：单次暂停——workflow 层不发 BEAT_SLOTS_BUILT（route 层补发
        带 run_id 的权威事件，内嵌 decision_set），不静默突变、不 emit
        DDE_AUTO_APPLIED（无独立 DDE 弹窗轮次）。"""
        wf = self._make_dde_workflow()
        cards = _make_cards(3)
        decision_set = _make_decision_set(cards[0].beat_id)
        events = []

        async def cb(event, data):
            events.append((event, data))

        p1, p2, p3, p4, p5 = _dde_patches(_make_spine(), _make_anchor(), cards, decision_set)
        with p1, p2, p3, p4, p5, patch.object(
            BSAdfWorkflow, "_run_render_and_postprocess", new_callable=AsyncMock,
        ) as mock_post:
            result = asyncio.run(
                wf.execute(progress_callback=cb, pause_after_slot_build=True)
            )

        # 单次暂停
        assert result.debug_info.get("paused") is True
        mock_post.assert_not_called()
        # workflow 层不发 BEAT_SLOTS_BUILT：route 层补发带 run_id 的权威持卡事件
        # （步进=STEPPING_INITIALIZED；Track B=route 版 BEAT_SLOTS_BUILT，bsadf.py），
        # 若这里也发（无 run_id），前端会收到两个同名语义事件。
        event_names = [e for e, _ in events]
        assert "BEAT_SLOTS_BUILT" not in event_names
        # debug_info 带 decision_set（route 层据此暂存并随权威事件下发，
        # 供 confirm-beats 时按作者选择突变）
        ds = result.debug_info["decision_set"]
        assert ds["has_story_branch"] is True
        assert ds["decision_nodes"][0]["beat_id"] == cards[0].beat_id
        # 不做静默突变、不 emit DDE_AUTO_APPLIED
        assert "DDE_AUTO_APPLIED" not in event_names
        assert all(c.branch_directive == "" for c in cards)

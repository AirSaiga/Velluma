# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 视野配比修复（2026-08-25 实测调窗）单测
"""「驴头不对马嘴」治理三件套的回归锚：

1. sentence_clean_tail：窗口起点不落半截句（窗首半截句会让模型误以为要续它）；
   无句界兜底原样保留（宁要半截句不要空窗）。
2. stitch_context._nearby_intent_from_outline：意图块只给大纲就近一两拍
   （整章地图诱导冲章——实测事故）；无大纲/全写完 → 空串（零变化契约）。
3. 窗口常量锚：SHORT=800 / LONG=1200（实测调窗值；再动它需新的实测证据，
   锁值防随手回退）。

运行：python -m pytest backend/services/adaptive/test_view_rebalance.py -v
"""

from types import SimpleNamespace

import asyncio
import json

from backend.services.adaptive.paragraph_source import sentence_clean_tail
from backend.services.context.budget import (
    STITCH_ROLLING_LONG_MAX_CHARS,
    STITCH_ROLLING_SHORT_MAX_CHARS,
)
from backend.services.context.stitch_context import _nearby_intent_from_outline


# ============================================================
# 窗口常量锚（实测调窗值，改动需新证据）
# ============================================================

def test_window_constants_locked_at_measured_values():
    assert STITCH_ROLLING_SHORT_MAX_CHARS == 800
    assert STITCH_ROLLING_LONG_MAX_CHARS == 1200


# ============================================================
# sentence_clean_tail：句界净截
# ============================================================

class TestSentenceCleanTail:
    def test_short_text_unchanged(self):
        assert sentence_clean_tail("短短一句。", 800) == "短短一句。"

    def test_exact_cap_unchanged(self):
        t = "正正好好。"
        assert sentence_clean_tail(t, len(t)) == t

    def test_drops_partial_sentence_at_window_head(self):
        tail = "完整的后半句。" + "长句" * 400   # 超 800 窗
        text = "被切断的前半" + tail
        got = sentence_clean_tail(text, 800)
        assert got  # 窗非空
        assert not got.startswith("半")  # 窗首半截句被丢弃
        assert len(got) <= 800

    def test_newline_is_boundary(self):
        text = "aaaa" + "一" * 100 + "\n" + "二" * 100
        got = sentence_clean_tail(text, 120)
        assert got.startswith("二")

    def test_no_boundary_keeps_whole_window(self):
        """对话连排无终止符的长段：宁要半截句不要空窗。"""
        text = "无标点长段" * 300
        got = sentence_clean_tail(text, 800)
        assert len(got) == 800

    def test_empty_text(self):
        assert sentence_clean_tail("", 800) == ""


# ============================================================
# _nearby_intent_from_outline：意图块就近化
# ============================================================

OUTLINE = """林尘在车间读名言发愣被工头打断
无奈自嘲自己的处境
基地遭到反抗组织的袭击
流光带领机甲侵入意欲血噬"""


def _bundle(outline="", content=""):
    return SimpleNamespace(outline_text=outline, content_text=content)


class TestNearbyIntentFromOutline:
    def test_no_outline_returns_empty(self):
        assert _nearby_intent_from_outline(_bundle()) == ""
        assert _nearby_intent_from_outline(_bundle(outline="   ")) == ""

    def test_nothing_written_picks_first_beats(self):
        got = _nearby_intent_from_outline(_bundle(outline=OUTLINE))
        assert "工头打断" in got
        assert "自嘲" in got
        # 远处的袭击/血噬不得出现（防冲章核心断言）
        assert "袭击" not in got and "血噬" not in got

    def test_written_beats_are_skipped(self):
        written = "林尘在车间读名言发愣被工头打断，他无奈自嘲自己的处境。"
        got = _nearby_intent_from_outline(_bundle(outline=OUTLINE, content=written))
        assert "袭击" in got  # 前两拍已写 → 就近到第三拍
        assert "工头打断" not in got

    def test_all_written_returns_empty(self):
        written = (
            "林尘在车间读名言发愣被工头打断，无奈自嘲自己的处境。"
            "基地遭到反抗组织的袭击，流光带领机甲侵入意欲血噬。"
        )
        assert _nearby_intent_from_outline(_bundle(outline=OUTLINE, content=written)) == ""


# ============================================================
# 点火剂量闸（路由级，全桩化）：open 模式只给开头一两拍
# ============================================================

class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRecorder:
    def record_result(self, *a, **k):
        pass


def _run_open_stitch(monkeypatch, outline: str):
    """直调 stitch_ghost 路由 mode=open（LLM/装配/观测全桩化），返回捕获的 user_prompt。"""
    from backend.routes.chapter_generation.adaptive import stitch as adaptive_route

    captured: list = []

    async def fake_llm(system_prompt, user_prompt, **kw):
        captured.append(user_prompt)
        return _FakeResult("开篇第一段。名言落地有声。")

    bundle = SimpleNamespace(
        outline_text=outline, previous_summary="", worldview_text="",
        canon_context="", spatial_brief="", character_secrets=[],
    )
    ctx = SimpleNamespace(
        bundle=bundle, proper_nouns=[], chapter_intent="",
        memory_echoes=[], style_positive="", author_samples=[],
    )

    async def fake_assemble(**kw):
        return ctx

    monkeypatch.setattr(adaptive_route, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(adaptive_route, "assemble_stitch_context", fake_assemble)
    monkeypatch.setattr(adaptive_route, "_spine_anchor_rows_for_prompt", _async_empty)
    monkeypatch.setattr(adaptive_route, "get_adaptive_recorder", lambda cid: _FakeRecorder())
    monkeypatch.setattr(adaptive_route, "flush_adaptive_records", _async_none)
    monkeypatch.setattr(adaptive_route, "bind_adaptive_trace", lambda cid: None)
    monkeypatch.setattr(adaptive_route, "trace_event", lambda *a, **k: None)

    async def scenario():
        resp = await adaptive_route.stitch_ghost(
            "ch-test", adaptive_route.StitchGhostRequest(fragment="", mode="open", target_chars=700), None,
        )
        async for _ in resp.body_iterator:
            pass

    asyncio.run(scenario())
    return captured[0] if captured else ""


async def _async_empty(*a, **k):
    return []


async def _async_none(*a, **k):
    return None


def test_open_mode_outline_dose_gate(monkeypatch):
    """点火只给开头一两拍：全章地图在场 = 模型直奔终点（实测事故 2026-08-24）。"""
    outline = (
        "林尘读名言发愣被工头打断\n"
        "基地遭到反抗组织袭击仓库\n"
        "血噬启动保护与林尘融合逃离"
    )
    user_prompt = _run_open_stitch(monkeypatch, outline)
    assert "工头打断" in user_prompt
    # 剂量闸核心断言：后段剧情不得出现在点火视野里
    assert "血噬" not in user_prompt
    assert "融合逃离" not in user_prompt


def test_open_mode_short_outline_fallback(monkeypatch):
    """无合格节拍行的短大纲回退原文（剂量天然小，不算破闸）。"""
    user_prompt = _run_open_stitch(monkeypatch, "短篇")
    assert "短篇" in user_prompt


# ============================================================
# spine-suggest 空输出兜底（路由级，全桩化）
# ============================================================

def _run_spine_suggest(monkeypatch, llm_contents):
    """直调 spine_suggest 路由（全桩化），返回 (响应 dict, LLM 调用 kwargs 列表)。"""
    from backend.routes.chapter_generation.adaptive import spine as adaptive_route

    calls: list = []

    async def fake_llm(system_prompt, user_prompt, **kw):
        calls.append(kw)
        return _FakeResult(llm_contents[min(len(calls) - 1, len(llm_contents) - 1)])

    class _B:
        outline_text = "大纲若干行"
        canon_context = ""
        worldview_text = ""
        previous_summary = ""

        def soft_constraints(self):
            return {"open_hooks": ""}

    async def fake_bundle(chapter_id, db):
        return _B()

    monkeypatch.setattr(adaptive_route, "load_chapter_settings_bundle", fake_bundle)
    monkeypatch.setattr(adaptive_route, "call_llm_with_usage", fake_llm)
    monkeypatch.setattr(adaptive_route, "get_adaptive_recorder", lambda cid: _FakeRecorder())
    monkeypatch.setattr(adaptive_route, "flush_adaptive_records", _async_none)
    monkeypatch.setattr(adaptive_route, "bind_adaptive_trace", lambda cid: None)
    monkeypatch.setattr(adaptive_route, "trace_event", lambda *a, **k: None)

    return asyncio.run(adaptive_route.spine_suggest("ch-test", None)), calls


def test_spine_suggest_retries_empty_output(monkeypatch):
    """空输出（思考烧光预算型）→ 关思考兜底重试一次，取到重试结果。"""
    from backend.services.llm.client import REASONING_DISABLED

    resp, calls = _run_spine_suggest(
        monkeypatch, ["", '{"intent": "活下去", "anchors": ["找到避难所"]}'],
    )
    assert len(calls) == 2
    assert calls[1].get("reasoning_config") == REASONING_DISABLED
    assert resp["intent"] == "活下去"
    assert resp["anchors"] == ["找到避难所"]


def test_spine_suggest_no_retry_when_valid(monkeypatch):
    """首次即有产出 → 不重试（单次调用契约不变）。"""
    resp, calls = _run_spine_suggest(monkeypatch, ['{"intent": "活下去", "anchors": []}'])
    assert len(calls) == 1
    assert resp["intent"] == "活下去"


def test_spine_suggest_still_empty_keeps_empty_contract(monkeypatch):
    """重试也空 → 空结果契约（建议本就柔性，前端对空静默）。"""
    resp, calls = _run_spine_suggest(monkeypatch, ["", ""])
    assert len(calls) == 2
    assert resp == {"intent": "", "anchors": []}

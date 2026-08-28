# Velluma - 三平面分权 单元测试（2026-08-29 文风重构，docs/style-paradigm.md）
# AGPL-3.0
"""
覆盖：
- P0 split_prohibition_tiers：负面块只留 warning；blocker 正面化重钉行
- P1 wash_ghost_text：blocker+alternative 精确替换 / warning 永不动手 /
  无替代词仅记录 / 长 pattern 让位 / regex 条目不替换
- P2 build_repair_prompt：句级修补指令形态
- P5 sample_prior：collab 事件派生贝叶斯先验（±20% 封顶、冷启动 1.0）
- P5/P6 retrieval：AI 来源配比 ≤1、样本轻指纹与旋钮选择器

运行：python -m pytest backend/services/style/test_style_paradigm.py
"""
from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import pytest

from backend.services.style.prohibitions import ProhibitionEntry, ProhibitionSet
from backend.services.style.ghost_wash import wash_ghost_text, build_repair_prompt
from backend.services.context.knowledge_plane import split_prohibition_tiers


def _ps(*entries):
    return ProhibitionSet(tuple(entries))


def _e(pattern, severity="warning", alternative=None, is_regex=False):
    return ProhibitionEntry(
        pattern=pattern, is_regex=is_regex,
        alternative=alternative, severity=severity, source="test",
    )


# ============================================================
# P0：分档
# ============================================================

class TestSplitTiers:
    def test_blocker_out_of_negative_block(self):
        warn, bits = split_prohibition_tiers(_ps(
            _e("深邃", "blocker", alternative="给具体动作"),
            _e("宛如", "warning"),
        ))
        assert warn == ["宛如"]                       # 负面块只剩提醒档
        assert bits == ["不用「深邃」——给具体动作"]      # blocker 进重钉行

    def test_no_alternative_gets_generic_positive_path(self):
        _, bits = split_prohibition_tiers(_ps(_e("指腹", "blocker")))
        assert "换成具体的动作或物件" in bits[0]

    def test_no_blocker_zero_change(self):
        warn, bits = split_prohibition_tiers(_ps(_e("宛如"), _e("仿若")))
        assert warn == ["宛如", "仿若"]
        assert bits == []

    def test_blocker_lines_capped_at_6(self):
        entries = [_e(f"禁词{i:02d}", "blocker") for i in range(10)]
        _, bits = split_prohibition_tiers(_ps(*entries))
        assert len(bits) == 6


# ============================================================
# P1：确定性洗层
# ============================================================

class TestWashGhost:
    def test_none_ps_zero_change(self):
        r = wash_ghost_text("他深邃地望着远方。", None)
        assert r.text == "他深邃地望着远方。" and r.hits == [] and r.original_text == ""

    def test_warning_never_touched(self):
        r = wash_ghost_text("他宛如一尊雕像。", _ps(_e("宛如", "warning")))
        assert r.text == "他宛如一尊雕像。" and r.hits == []

    def test_blocker_with_alternative_replaced(self):
        ps = _ps(_e("深邃", "blocker", alternative="沉静"))
        r = wash_ghost_text("他的目光深邃。", ps)
        assert r.text == "他的目光沉静。"
        assert len(r.hits) == 1 and r.hits[0].replaced
        assert r.original_text == "他的目光深邃。"     # 原稿快照保留（chip 用）

    def test_blocker_without_alternative_recorded_only(self):
        ps = _ps(_e("指腹", "blocker"))
        r = wash_ghost_text("他的指腹磨出茧。", ps)
        assert r.text == "他的指腹磨出茧。"            # 不动手
        assert len(r.residual_hits) == 1               # P2 修补触发依据
        assert r.original_text == ""                   # 未替换不留原稿

    def test_longer_pattern_wins_overlap(self):
        # 「深邃」落在 blocker 长词「深邃的眼」内 → 短词让位，按长词处理
        ps = _ps(
            _e("深邃", "blocker", alternative="沉静"),
            _e("深邃的眼", "blocker", alternative="沉静的眼睛"),
        )
        r = wash_ghost_text("他有一双深邃的眼。", ps)
        assert r.text == "他有一双沉静的眼睛。"
        assert len(r.hits) == 1 and r.hits[0].pattern == "深邃的眼"

    def test_regex_entry_never_replaced(self):
        ps = _ps(_e("一眼.{0,4}便", "blocker", alternative="X", is_regex=True))
        r = wash_ghost_text("他一眼扫过便懂了。", ps)
        assert "X" not in r.text                        # regex 只记录不替换
        assert len(r.hits) == 1 and not r.hits[0].replaced

    def test_multiple_hits_all_processed(self):
        ps = _ps(_e("深邃", "blocker", alternative="沉静"))
        r = wash_ghost_text("深邃的山，深邃的海。", ps)
        assert r.text == "沉静的山，沉静的海。"
        assert len(r.hits) == 2


# ============================================================
# P2：修补指令
# ============================================================

class TestRepairPrompt:
    def test_lists_patterns_and_keeps_original(self):
        from backend.services.style.ghost_wash import WashHit
        prompt = build_repair_prompt("原文。", [
            WashHit(pattern="指腹", span="指腹", start=0, replaced=False),
            WashHit(pattern="眸子", span="眸子", start=5, replaced=False, alternative="眼睛"),
        ])
        assert "「指腹」" in prompt and "「眸子」→ 改用「眼睛」" in prompt
        assert "其余句子一字不改" in prompt
        assert "--- 原稿 ---" in prompt and "原文。" in prompt


# ============================================================
# P5：采纳先验
# ============================================================

class TestSamplePrior:
    def _write_events(self, tmp_path, rows):
        path = tmp_path / "collab_events.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
        return path

    def test_cold_start_factor_one(self, monkeypatch, tmp_path):
        import backend.services.style.sample_prior as sp
        monkeypatch.setattr(sp, "_collab_events_path", lambda: tmp_path / "none.jsonl")
        monkeypatch.setattr(sp, "_rotated_path", lambda: tmp_path / "none.jsonl.1")
        sp._stats_cache = None
        sp._stats_cache_mtime = -1.0
        assert sp.sample_prior_factor("bk", "s1") == 1.0

    def test_adoption_rate_maps_to_factor(self, monkeypatch, tmp_path):
        import backend.services.style.sample_prior as sp
        # s1：2 采 0 弃 → prior=(2+1)/(2+2)=0.75 → factor 0.8+0.4*0.75=1.1
        # s2：0 采 2 弃 → prior=1/4=0.25 → factor 0.9
        # s3：1 采 1 弃 → prior=0.5 → factor 1.0
        path = self._write_events(tmp_path, [
            {"kind": "ghost_adopt", "book_id": "bk", "detail": {"sample_ids": ["s1", "s3"]}},
            {"kind": "ghost_adopt", "book_id": "bk", "detail": {"sample_ids": ["s1"]}},
            {"kind": "ghost_discard", "book_id": "bk", "detail": {"sample_ids": ["s2", "s3"]}},
            {"kind": "ghost_discard", "book_id": "bk", "detail": {"sample_ids": ["s2"]}},
        ])
        monkeypatch.setattr(sp, "_collab_events_path", lambda: path)
        monkeypatch.setattr(sp, "_rotated_path", lambda: tmp_path / "none.1")
        sp._stats_cache = None
        sp._stats_cache_mtime = -1.0
        assert sp.sample_prior_factor("bk", "s1") == pytest.approx(1.1)
        assert sp.sample_prior_factor("bk", "s2") == pytest.approx(0.9)
        assert sp.sample_prior_factor("bk", "s3") == pytest.approx(1.0)

    def test_factor_capped(self, monkeypatch, tmp_path):
        import backend.services.style.sample_prior as sp
        path = self._write_events(tmp_path, [
            {"kind": "ghost_adopt", "book_id": "bk", "detail": {"sample_ids": ["s1"]}},
        ] * 5)
        monkeypatch.setattr(sp, "_collab_events_path", lambda: path)
        monkeypatch.setattr(sp, "_rotated_path", lambda: tmp_path / "none.1")
        sp._stats_cache = None
        sp._stats_cache_mtime = -1.0
        assert sp.sample_prior_factor("bk", "s1") <= 1.2 + 1e-9   # ±20% 封顶


# ============================================================
# P5/P6：检索扩展
# ============================================================

class TestRetrievalExtensions:
    def test_light_stats(self):
        from backend.services.style.retrieval import sample_light_stats
        mean, ratio = sample_light_stats("他走了。她笑了。“你说什么？”")
        assert 0 < mean < 10
        assert ratio > 0

    def test_empty_stats(self):
        from backend.services.style.retrieval import sample_light_stats
        assert sample_light_stats("") == (0.0, 0.0)

    def test_ai_source_cap(self):
        from backend.services.style.retrieval import _cap_ai_source

        class S:
            def __init__(self, n, source="manual"):
                self.name, self.source = n, source

        ordered = [S("a1", "adopted_ghost"), S("a2", "adopted_ghost"), S("m1")]
        assert [s.name for s in _cap_ai_source(ordered, 3)] == ["a1", "m1"]  # AI ≤1

    def test_selector_adjust_neutral_without_knob(self):
        from backend.services.style.retrieval import _selector_adjust

        class Card:
            style_knobs = {}
            dialogue_ratio_target = None

        assert _selector_adjust(type("S", (), {"content": "短句。"}), Card()) == 0.0

    def test_selector_adjust_rhythm_short_knob(self):
        from backend.services.style.retrieval import _selector_adjust

        class Card:
            style_knobs = {"rhythm": 1}   # 极快 → 目标句均 ~10
            dialogue_ratio_target = None

        class SampleShort:
            content = "走。跑。停。"          # 句均 ~2 字 → 贴近

        class SampleLong:
            content = "他沿着那条被雨水浸得发亮的长街一直走到尽头才终于停下脚步歇了口气环顾四周无人。"  # 单长句 ~35 字 → 远离档位锚

        assert _selector_adjust(SampleShort(), Card()) < _selector_adjust(SampleLong(), Card())

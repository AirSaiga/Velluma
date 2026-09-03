# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""2026-09-03 质感密度测量对拍（质感批次第四层）。

锁三件事：
① texture 指标挂在指纹 dict 上（空文本同构/短文本不判/命中计数值正确）；
② most_textured_window 选出质感最密的句子连续窗（句界对齐/门槛/确定性）；
③ 既有指纹键零变化（加键不改旧键——同一把尺子原则只约束既有口径）。

运行：.venv/Scripts/python.exe -m pytest backend/services/style/test_texture_metric.py -v
"""

from backend.services.style.fingerprint import (
    TEX_PICK_MIN_DENSITY,
    compute_text_fingerprint,
    most_textured_window,
)

TEXTURED = (
    "车间里很暗，只有一盏昏黄的灯悬在头顶。机油味混着汗味扑面而来，"
    "他眯起眼，看见光束里浮尘乱舞。手里的扳手冰凉，硌手得很。"
    "远处机器嗡嗡地轰鸣，他攥紧扳手，喉咙发紧。"
)
FLAT = "他走进去。他坐下来。他开始工作。然后他站起来。他走到窗边。他又走回来。" * 6


class TestTextureStats:
    def test_texture_key_present_and_empty_isomorphic(self):
        fp = compute_text_fingerprint("")
        assert fp["texture"] == {"texture_per_1k": None, "texture_hits": 0, "texture_top": []}

    def test_textured_text_scores(self):
        fp = compute_text_fingerprint(TEXTURED)
        tex = fp["texture"]
        assert tex["texture_hits"] >= 5
        assert tex["texture_per_1k"] and tex["texture_per_1k"] > 30
        assert tex["texture_top"][0][1] >= 1

    def test_flat_text_low_density(self):
        fp = compute_text_fingerprint(FLAT)
        assert fp["texture"]["texture_hits"] == 0

    def test_light_mode_also_carries_texture(self):
        assert compute_text_fingerprint(TEXTURED, light=True)["texture"]["texture_hits"] >= 5

    def test_existing_keys_unchanged(self):
        # 同一把尺子：加 texture 键不动既有键（句长/对话/词汇/重复原位）
        fp = compute_text_fingerprint(TEXTURED)
        for key in (
            "char_count", "word_count", "sentence_count", "sentence_len_cv",
            "dialogue_ratio", "punctuation", "rhetoric", "lexical", "repetition",
        ):
            assert key in fp


class TestMostTexturedWindow:
    def test_picks_textured_window(self):
        filler = "他继续干活。时间过去。事情在进展。" * 8
        text = filler + TEXTURED + filler
        win = most_textured_window(text)
        assert win is not None
        assert "机油味" in win["text"] or "攥紧" in win["text"]
        assert win["density_per_1k"] >= TEX_PICK_MIN_DENSITY

    def test_flat_text_returns_none(self):
        assert most_textured_window(FLAT) is None

    def test_too_short_text_returns_none(self):
        assert most_textured_window("他眯起眼。") is None
        assert most_textured_window("") is None
        assert most_textured_window(None) is None

    def test_deterministic(self):
        filler = "他继续干活。时间过去。事情在进展。" * 8
        text = filler + TEXTURED + filler
        assert most_textured_window(text) == most_textured_window(text)

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""LocalPreprocessor 单测——Tier 2 本地预处理（0 Token 抽脂 + 硬断句）。

测试面（避开 jieba 分词不确定性）：
- _split_dialogue / _strip_connectives / _strip_adverb_fat：直接喂 (word, flag)
  序列，纯函数对拍（抽脂算法与 jieba 解耦验证）；
- _break_long_sentence(s)：长句硬切断的确定性规则（>40 字 + 含逗号 → 首逗号置换句号，只切一次）；
- preprocess_segment 兜底：空输入/处理异常变空/删减过半 → 回退原文（安全网）。

阈值契约：DEFAULT_MAX_SENTENCE_LEN=40（旧值 24 曾致全章机械断句事故，勿回退）。
"""

from backend.services.nlg.local_preprocessor import (
    DEFAULT_MAX_SENTENCE_LEN,
    LocalPreprocessor,
    _break_long_sentence,
    _break_long_sentences,
    _split_dialogue,
    _strip_adverb_fat,
    _strip_connectives,
)


class TestSplitDialogue:
    def test_plain_narration(self):
        frags = _split_dialogue("他推开门，走了进来。")
        assert frags == [("他推开门，走了进来。", False)]

    def test_dialogue_marked_true(self):
        frags = _split_dialogue("他说：“今天不错。”然后坐下。")
        # 三段：叙述 / 对话(True) / 尾部叙述
        assert [is_d for _, is_d in frags] == [False, True, False]
        assert frags[1][0] == "“今天不错。”"

    def test_unterminated_quote_is_dialogue_to_end(self):
        # 未闭合引号：从开引号到文本尾都算对话（保护不抽脂）
        frags = _split_dialogue("他说：“还没说完")
        assert frags[-1][1] is True

    def test_empty(self):
        assert _split_dialogue("") == []


class TestStripConnectives:
    def test_connectives_removed_by_token(self):
        words = [("然而", "c"), ("天", "n"), ("但是", "c"), ("亮了", "v")]
        assert _strip_connectives(words) == [("天", "n"), ("亮了", "v")]

    def test_normal_words_kept(self):
        words = [("随后", "d"), ("天", "n")]
        # “随后”不在连接词清单（“随后就”才是），保留
        assert _strip_connectives(words) == words


class TestStripAdverbFat:
    def test_stacked_adverbs_keep_last(self):
        # 缓缓地默默地 → 默默地（删前导修饰词连带其“地”）
        words = [("他", "r"), ("缓缓", "d"), ("地", "ud"), ("默默", "d"), ("地", "ud"), ("走", "v")]
        out = _strip_adverb_fat(words)
        assert [w for w, _ in out] == ["他", "默默", "地", "走"]

    def test_single_modifier_kept(self):
        words = [("他", "r"), ("慢慢", "d"), ("地", "ud"), ("走", "v")]
        assert _strip_adverb_fat(words) == words

    def test_modifier_run_broken_by_verb(self):
        # 修饰词被动词隔开 → 两个独立单修饰 run，都保留
        words = [
            ("轻轻", "d"), ("地", "ud"), ("点头", "v"),
            ("重重", "d"), ("地", "ud"), ("落", "v"),
        ]
        out = _strip_adverb_fat(words)
        assert [w for w, _ in out] == ["轻轻", "地", "点头", "重重", "地", "落"]

    def test_punctuation_between_modifiers_is_transparent(self):
        # run 内标点可穿透：叠修饰仍只留最后一个
        words = [("缓缓", "d"), ("，", "w"), ("默默", "d"), ("走", "v")]
        out = _strip_adverb_fat(words)
        assert "缓缓" not in [w for w, _ in out]
        assert "默默" in [w for w, _ in out]


class TestBreakLongSentence:
    """契约：sentence 不含句末标点，delim 由本函数补回。"""

    def test_short_sentence_untouched(self):
        assert _break_long_sentence("天亮了", "。", 40) == "天亮了。"

    def test_long_without_comma_untouched(self):
        sent = "一" * 50
        assert _break_long_sentence(sent, "。", 40) == sent + "。"

    def test_long_with_comma_cuts_once_at_first(self):
        sent = "一" * 30 + "，" + "二" * 30
        out = _break_long_sentence(sent, "。", 40)
        # 首逗号→句号，只切一次，原句末标点保留在尾
        assert out.count("。") == 2
        assert out.startswith("一" * 30 + "。")
        assert out.endswith("二" * 30 + "。")

    def test_default_threshold_is_40(self):
        assert DEFAULT_MAX_SENTENCE_LEN == 40


class TestBreakLongSentences:
    def test_mixed_text(self):
        text = "短句。" + "一" * 30 + "，" + "二" * 30 + "。收尾。"
        out = _break_long_sentences(text)
        assert out.startswith("短句。")
        assert out.count("。") >= 3

    def test_tailing_fragment_without_punct_kept(self):
        text = "天亮了。没有句末标点的尾巴"
        assert _break_long_sentences(text).endswith("没有句末标点的尾巴")


class TestPreprocessSegmentFallbacks:
    def test_empty_input(self):
        assert LocalPreprocessor().preprocess_segment("") == ""
        assert LocalPreprocessor().preprocess_segment("   ") == "   "

    def test_clean_narration_survives(self):
        # 正常叙述：无叠修饰、无连接词、无超长句 → 原样（jieba 重排不改变字面）
        text = "老周把扳手塞进工具包，锁了仓库门。雨还没停。"
        out = LocalPreprocessor().preprocess_segment(text)
        assert out == text

    def test_dialogue_content_preserved(self):
        # 对话保护红线：引号内台词一个字不动（乱删会 OOC）
        text = "他说：“然而你应该缓缓地默默地想一想。”"
        out = LocalPreprocessor().preprocess_segment(text)
        assert "“然而你应该缓缓地默默地想一想。”" in out

    def test_overshort_result_falls_back(self):
        # 删减 >50% 视为误伤 → 回退原文（兜底网）：无论内部抽脂结果如何，
        # 输出不短于原文的一半
        text = "然而然而然而然而，但是但是但是但是。"
        out = LocalPreprocessor().preprocess_segment(text)
        assert len(out) >= len(text) * 0.5

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
文风指纹测量单测（S1 测量层，纯算法——不连 LLM/DB）。

覆盖：
- 规范原语：切句/字数/CV/对话字符统计的边界与已知值
- 指纹结构：空文本全零不抛错；直方图桶计数；light 模式省略修辞
- 对拍锁定（设计稿 §9 风险对策）：同一文本在指纹侧与审计侧
  RhythmAuditor.sentence_len_cv / DialogueAuditor.dialogue_ratio 同值——
  「同一把尺子」的回归护栏，改任一侧算法先跑此测试。
"""

import asyncio
from itertools import product

import pytest

from backend.services.style.fingerprint import (
    aggregate_corpus,
    coefficient_of_variation,
    compute_style_drift_hint,
    compute_text_fingerprint,
    count_dialogue_chars,
    count_words,
    split_sentences,
)
from backend.services.validation.code_auditors import DialogueAuditor, RhythmAuditor


# ============================================================
# 测试语料
# ============================================================

# 句长刻意参差（含短句/长句/问叹），多段含对白段与叙述段
RICH_TEXT = (
    "雨停了。\n"
    "他站在渡口，看着江水在暮色里翻涌，想起十年前也是这样的天，也是这样的渡船，"
    "只是那时船上还有人等他回来吃饭，而现在只剩他一个人，和一封没有寄出的信。\n"
    "“走了？”艄公问。\n"
    "“走。”他说。\n"
    "船离岸的时候，他忽然想问艄公一句什么，最终没有问。江风很大，吹得人睁不开眼。\n"
    "对岸的灯火一盏一盏亮起来，像有人在替他数着剩下的日子。"
)

# 等长句（CV 应为 0）：六句长度几乎一致
FLAT_TEXT = (
    "他慢慢地走过去，看着前方。她轻轻地走过来，看着前方。"
    "他们慢慢地走过去，看着前方。它轻轻地飞过来，看着前方。"
    "我们慢慢地走过去，看着前方。你们轻轻地走过来，看着前方。"
)

# 纯对话文本（对话占比应极高）
DIALOGUE_TEXT = "他说：“你好。”她说：“你好吗？”他说：“我很好。”她说：“那太好了。”"


# ============================================================
# 规范原语
# ============================================================

class TestPrimitives:
    def test_split_sentences_filters_fragments(self):
        # "走了。"切出"走了"（2 字 = 过滤边界之外？——>2 才保留）
        sentences = split_sentences("他走了。嗯？这可真是一件漫长得不可思议的事情啊。")
        # "他走了"（3 字）保留；"嗯"（1 字）过滤
        assert sentences == ["他走了", "这可真是一件漫长得不可思议的事情啊"]

    def test_split_sentences_empty(self):
        assert split_sentences("") == []
        assert split_sentences(None or "") == []

    def test_count_words_strips_whitespace(self):
        assert count_words("你 好\n\t世界  ") == 4

    def test_count_words_empty(self):
        assert count_words("") == 0

    def test_cv_known_values(self):
        assert coefficient_of_variation([]) == 0.0
        assert coefficient_of_variation([5.0]) == 0.0
        # 全等 → 0
        assert coefficient_of_variation([10.0, 10.0, 10.0]) == 0.0
        # 已知分布：[10, 20] → mean 15, pstdev 5 → CV 1/3
        assert coefficient_of_variation([10.0, 20.0]) == pytest.approx(1 / 3, abs=1e-9)

    def test_count_dialogue_chars_paired_quotes(self):
        # “你好。” = 5 字符（两侧引号 + 引号内句号也计入，与审计口径一致）
        assert count_dialogue_chars("他说：“你好。”就走了。") == 5
        # 「走。」 = 4 字符（含引号内句号）
        assert count_dialogue_chars("「走。」") == 4
        # 未闭合引号：一路计入到文本末（“你好。= 4 字符，历史行为保持）
        assert count_dialogue_chars("他说：“你好。") == 4
        # 空文本
        assert count_dialogue_chars("") == 0


# ============================================================
# 指纹结构
# ============================================================

class TestFingerprintStructure:
    def test_empty_text_returns_zeroed_fingerprint(self):
        fp = compute_text_fingerprint("")
        assert fp["char_count"] == 0
        assert fp["word_count"] == 0
        assert fp["sentence_count"] == 0
        assert fp["sentence_len_cv"] == 0.0
        assert fp["dialogue_ratio"] == 0.0
        assert fp["rhetoric"] is None
        assert sum(fp["sentence_len_histogram"].values()) == 0

    def test_rich_text_fingerprint_basic_fields(self):
        fp = compute_text_fingerprint(RICH_TEXT)
        assert fp["word_count"] == count_words(RICH_TEXT)
        assert fp["sentence_count"] == len(split_sentences(RICH_TEXT))
        assert fp["sentence_count"] >= 5
        # 含对白引号 → 对话占比 > 0
        assert fp["dialogue_ratio"] > 0
        # 参差句长 → CV 显著高于等长句
        fp_flat = compute_text_fingerprint(FLAT_TEXT)
        assert fp["sentence_len_cv"] > fp_flat["sentence_len_cv"] + 0.3
        # 直方图计数守恒
        assert sum(fp["sentence_len_histogram"].values()) == fp["sentence_count"]
        # 修辞密度（全量模式）
        assert fp["rhetoric"] is not None
        assert "metaphor_per_500" in fp["rhetoric"]

    def test_flat_text_cv_low(self):
        fp = compute_text_fingerprint(FLAT_TEXT)
        assert fp["sentence_len_cv"] < 0.1

    def test_light_mode_skips_rhetoric(self):
        fp = compute_text_fingerprint(RICH_TEXT, light=True)
        assert fp["rhetoric"] is None
        # 其余字段照常
        assert fp["sentence_count"] > 0

    def test_paragraph_stats_excludes_dialogue_paragraphs(self):
        # 两条对白段 + 一条长叙述段：短段占比不应把对白段计入
        text = "“走了？”\n“走了。”\n" + "叙述段。" * 10
        fp = compute_text_fingerprint(text)
        assert fp["paragraph_count"] == 1  # 仅叙述段计入
        assert fp["paragraph_len_mean"] == 40  # 10 个"叙述段。"= 40 字

    def test_short_sentence_ratio_guard(self):
        # 句数 <10 不判碎句率 → 0（同 ai_taste_meter 口径）
        fp = compute_text_fingerprint("走。走。走。走得再远些又如何呢。")
        assert fp["short_sentence_ratio"] == 0.0

    def test_punctuation_stats(self):
        text = "他说——真的吗……？她喊道！不。"
        fp = compute_text_fingerprint(text)
        assert fp["punctuation"]["dash_per_1k"] > 0
        assert fp["punctuation"]["ellipsis_per_1k"] > 0
        assert fp["punctuation"]["exclaim_per_1k"] > 0
        assert fp["punctuation"]["question_per_1k"] > 0

    def test_deterministic(self):
        a = compute_text_fingerprint(RICH_TEXT)
        b = compute_text_fingerprint(RICH_TEXT)
        assert a == b


# ============================================================
# 语料聚合
# ============================================================

class TestAggregateCorpus:
    def test_empty(self):
        fp = aggregate_corpus([])
        assert fp["word_count"] == 0

    def test_joins_and_measures(self):
        fp = aggregate_corpus([RICH_TEXT, FLAT_TEXT])
        joined = RICH_TEXT + "\n\n" + FLAT_TEXT
        assert fp["word_count"] == count_words(joined)

    def test_max_chars_keeps_whole_samples(self):
        # 上限小于样本 1 时跳过样本 1，保留样本 2（不产生半截样本）
        fp = aggregate_corpus([RICH_TEXT, "短样本一句。"], max_chars=len(RICH_TEXT) - 1)
        assert fp["word_count"] == count_words("短样本一句。")


# ============================================================
# 对拍锁定：指纹侧 vs 审计侧（同一把尺子回归护栏）
# ============================================================

class TestAuditParity:
    """同一文本：指纹字段与 Auditor 指标必须同值。

    若此测试失败，说明指纹或审计任一侧的口径被改动——
    两侧对账区数值将不可比，须先对齐再合并（设计稿 §9）。
    """

    def test_sentence_len_cv_matches_rhythm_auditor(self):
        for text in (RICH_TEXT, FLAT_TEXT, DIALOGUE_TEXT):
            fp = compute_text_fingerprint(text, light=True)
            audit = asyncio.run(RhythmAuditor().audit(text, {}))
            assert fp["sentence_len_cv"] == audit.metrics["sentence_len_cv"], (
                f"CV 口径漂移: fingerprint={fp['sentence_len_cv']} "
                f"auditor={audit.metrics['sentence_len_cv']} text={text[:20]}..."
            )

    def test_dialogue_ratio_matches_dialogue_auditor(self):
        for text in (RICH_TEXT, DIALOGUE_TEXT, "他没有说话，只是站着。"):
            fp = compute_text_fingerprint(text, light=True)
            audit = asyncio.run(DialogueAuditor().audit(text, {}))
            assert fp["dialogue_ratio"] == audit.metrics["dialogue_ratio"], (
                f"对话占比口径漂移: fingerprint={fp['dialogue_ratio']} "
                f"auditor={audit.metrics['dialogue_ratio']}"
            )


# ============================================================
# 词汇丰富度与重复密度（NLP 扩展，任务包 C）
# ============================================================
# 精确断言用空格分隔的英文伪 token——jieba 对空格分词确定性高
# （每个 ASCII 词为独立 token，空格/标点被 _tokenize 过滤）。

# 12 个互异伪词；×3 + 前 4 词 = 40 token、12 类型 → ttr = 12/40 = 0.3
_PSEUDO_WORDS = [
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta",
    "eta", "theta", "iota", "kappa", "lambda", "mu",
]
PSEUDO_FLAT = " ".join(_PSEUDO_WORDS * 3 + _PSEUDO_WORDS[:4])  # 40 token

# 同一句子循环拼接（13 遍 ≈ 442 字 / 273 token）：bigram 几乎全部高频重复
REPETITIVE_CN = "夜色像墨一样浓。他推门进来，抖了抖肩上的雨。灯火晃了一下，又稳住了。" * 13

# 144 个互异双字母伪词（431 字）：bigram 全互异 → ratio = 0；兼作漂移提示的反例长文本
VARIED_TOKENS = " ".join("".join(p) for p in product("abcdefghijkl", repeat=2))


class TestLexicalStats:
    def test_exact_ttr_with_pseudo_tokens(self):
        # 手工可算：40 token / 12 类型 → ttr = 0.3；token <100 → mattr 回落全体 ttr
        fp = compute_text_fingerprint(PSEUDO_FLAT)
        assert fp["lexical"] == {"token_count": 40, "ttr": 0.3, "mattr": 0.3}

    def test_short_text_guard_returns_none(self):
        # 24 token < 30 → 不判丰富度（同碎句率「句数<10 不判」哲学）
        fp = compute_text_fingerprint(" ".join(_PSEUDO_WORDS * 2))
        assert fp["lexical"] == {"token_count": 24, "ttr": None, "mattr": None}

    def test_mattr_window_engaged_over_100_tokens(self):
        # 110 token = a×50 + b×50 + c×10，手算逐窗 TTR（窗口 100、步长 1，共 11 窗）：
        #   首窗（0-99）含 a、b 两型 → 0.02；其余 10 窗（右端进入 c）各 3 型 → 0.03
        #   MATTR = (0.02 + 10×0.03) / 11 = 0.02909… → 0.029 ≠ 全体 ttr（3/110=0.027）
        #   ——mattr ≠ ttr 证实窗口逻辑确实生效（而非全体 TTR 冒充）
        text = " ".join(["a"] * 50 + ["b"] * 50 + ["c"] * 10)
        lex = compute_text_fingerprint(text)["lexical"]
        assert lex["token_count"] == 110
        assert lex["ttr"] == 0.027
        assert lex["mattr"] == 0.029
        assert lex["mattr"] != lex["ttr"]

    def test_mattr_one_when_all_distinct(self):
        # 144 个互异 token：每窗 100 型全互异 → mattr = ttr = 1.0（滑窗计数器守恒 sanity）
        lex = compute_text_fingerprint(VARIED_TOKENS)["lexical"]
        assert lex == {"token_count": 144, "ttr": 1.0, "mattr": 1.0}

    def test_empty_and_punct_only_isomorphic_none(self):
        # 空文本与纯标点（分词后零 token）同构：token_count=0、其余 None
        for text in ("", "   ", "。……！"):
            fp = compute_text_fingerprint(text)
            assert fp["lexical"] == {"token_count": 0, "ttr": None, "mattr": None}
            assert fp["repetition"] == {"bigram_repeat_ratio": None, "repeated_bigrams_top": []}

    def test_bounds_within_unit_interval(self):
        for text in (RICH_TEXT, REPETITIVE_CN, VARIED_TOKENS):
            lex = compute_text_fingerprint(text)["lexical"]
            for value in (lex["ttr"], lex["mattr"]):
                assert value is None or 0.0 <= value <= 1.0


class TestRepetitionStats:
    def test_zero_ratio_on_all_distinct_bigrams(self):
        rep = compute_text_fingerprint(VARIED_TOKENS)["repetition"]
        assert rep == {"bigram_repeat_ratio": 0.0, "repeated_bigrams_top": []}

    def test_repetitive_text_ratio_significantly_higher(self):
        # 同句循环 → 几乎全部 bigram 频次 13 → ratio 1.0，显著高于互异文本的 0.0
        rep_loop = compute_text_fingerprint(REPETITIVE_CN)["repetition"]["bigram_repeat_ratio"]
        rep_varied = compute_text_fingerprint(VARIED_TOKENS)["repetition"]["bigram_repeat_ratio"]
        assert rep_loop > 0.5
        assert rep_loop > rep_varied + 0.4

    def test_top_bigrams_shape(self):
        top = compute_text_fingerprint(REPETITIVE_CN)["repetition"]["repeated_bigrams_top"]
        assert isinstance(top, list) and 0 < len(top) <= 5
        counts = []
        for item in top:
            assert isinstance(item, list) and len(item) == 2
            assert isinstance(item[0], str) and item[0]  # 两 token 直接拼接成串
            assert isinstance(item[1], int) and item[1] >= 3
            counts.append(item[1])
        assert counts == sorted(counts, reverse=True)

    def test_short_text_guard_returns_none(self):
        # 36 token < 50 → 不判重复密度
        fp = compute_text_fingerprint(" ".join(_PSEUDO_WORDS * 3))
        assert fp["repetition"] == {"bigram_repeat_ratio": None, "repeated_bigrams_top": []}

    def test_deterministic_new_keys(self):
        a = compute_text_fingerprint(REPETITIVE_CN)
        b = compute_text_fingerprint(REPETITIVE_CN)
        assert a["lexical"] == b["lexical"]
        assert a["repetition"] == b["repetition"]

    def test_light_mode_includes_new_families(self):
        # light 模式省略修辞，但词汇/重复两族照算（jieba 单遍代价可承受）
        fp = compute_text_fingerprint(REPETITIVE_CN, light=True)
        assert fp["rhetoric"] is None
        assert fp["lexical"]["token_count"] > 0
        assert fp["repetition"]["bigram_repeat_ratio"] is not None

    def test_top_level_key_structure_locked(self):
        # 结构锁：新键只增不改——既有 14 键 + lexical/repetition，防意外增删键
        fp = compute_text_fingerprint(PSEUDO_FLAT)
        assert set(fp.keys()) == {
            "char_count", "word_count",
            "sentence_count", "sentence_len_mean", "sentence_len_median",
            "sentence_len_cv", "short_sentence_ratio", "sentence_len_histogram",
            "dialogue_ratio", "paragraph_count", "paragraph_len_mean",
            "short_paragraph_ratio", "punctuation", "rhetoric",
            "lexical", "repetition",
        }


class TestStyleDriftRepeatHint:
    """compute_style_drift_hint 的用词重复度检查（阈值 NGRAM_REPEAT_RATIO_HI=0.15）。"""

    def test_repeat_note_fires_on_repetitive_long_text(self):
        hint = compute_style_drift_hint(REPETITIVE_CN, None, 0.35, 0.80)
        assert hint is not None
        assert "用词重复度偏高" in hint

    def test_no_repeat_note_on_varied_text(self):
        # 互异伪词长文本（>400 字）不触发重复度提示（其余条件也不满足 → 整体 None）
        hint = compute_style_drift_hint(VARIED_TOKENS, None, 0.35, 0.80)
        assert hint is None or "用词重复度偏高" not in hint

    def test_short_text_still_returns_none(self):
        # <400 字维持既有行为（不测量、不提示）
        assert compute_style_drift_hint("短文本。", None, 0.35, 0.80) is None

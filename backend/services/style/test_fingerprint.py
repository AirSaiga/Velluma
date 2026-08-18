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

import pytest

from backend.services.style.fingerprint import (
    aggregate_corpus,
    coefficient_of_variation,
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

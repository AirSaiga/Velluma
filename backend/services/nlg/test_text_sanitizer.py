# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""text_sanitizer 单测——确定性正则裁剪层（0 LLM）。

对拍口径（模块 docstring 红线）：
- 只删确定性无信息量内容（黑名单填充词/微操短语），绝不动句式结构；
- 裁剪后清理标点冗余，输出仍是通顺中文；
- sanitize 是「裁剪」不是「改写」——正常叙述零命中时逐字不变。
"""

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
from backend.services.nlg.text_sanitizer import (
    _cleanup_punctuation,
    sanitize_rolling_prefix,
    sanitize_segment,
)


class TestSanitizeSegment:
    def test_clean_text_unchanged(self):
        # 正常人类叙述零命中 → 逐字节不变（宁漏勿误红线）
        text = "老周把扳手塞进工具包，锁了仓库门。雨还没停。"
        assert sanitize_segment(text) == text

    def test_empty_input(self):
        assert sanitize_segment("") == ""
        assert sanitize_segment("   ") == "   "

    def test_banned_word_removed(self):
        # 「冷冽」是黑名单孤立填充词 → 整词删除
        out = sanitize_segment("她的声音冷冽，像冬天的河水。")
        assert "冷冽" not in out
        assert "冬天的河水" in out  # 事实性内容保留

    def test_micro_action_phrase_removed(self):
        out = sanitize_segment("他指尖颤了颤，没有说话。")
        assert "指尖颤了颤" not in out
        assert "没有说话" in out

    def test_micro_action_regex_removed(self):
        # 正则面：嘴角+（0-6 字）+上扬/勾起族
        out = sanitize_segment("她嘴角微微上扬，端起茶杯。")
        assert "嘴角" not in out
        assert "端起茶杯" in out

    def test_punctuation_cleanup_after_removal(self):
        # 删词后残留的悬空逗号/叠标点被收敛
        text = "他冷冽，深邃，站在门口。"
        out = sanitize_segment(text)
        assert "冷冽" not in out and "深邃" not in out
        assert "，，" not in out
        assert "。。" not in out

    def test_all_banned_leaves_only_punct(self):
        # 段落全由黑名单词组成 → 实义字符删空（仅余残句标点，调用方判触发洗涤）
        out = sanitize_segment("冷冽深邃，宛如，仿若。")
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in out)

    def test_custom_ban_list(self):
        # 自定义清单：传空清单时无词可删（相对 DEFAULT）
        from backend.services.nlg.anti_ai_rules import AntiAIBanList

        empty = AntiAIBanList(
            banned_words=(),
            banned_micro_actions=(),
            banned_regexes=(),
            metaphor_regexes=(),
            trailing_modifier_regexes=(),
            transition_word_regexes=(),
            zhi_phrase_regexes=(),
        )
        text = "她的声音冷冽。"
        assert sanitize_segment(text, ban_list=empty) == text


class TestCleanupPunctuation:
    def test_multi_comma_collapsed(self):
        assert _cleanup_punctuation("甲，，乙") == "甲，乙"
        assert _cleanup_punctuation("甲、、乙") == "甲、乙"

    def test_space_before_punct(self):
        assert _cleanup_punctuation("甲 ，乙") == "甲，乙"

    def test_multi_end_punct(self):
        assert _cleanup_punctuation("甲。。") == "甲。"
        assert _cleanup_punctuation("甲！！") == "甲！"

    def test_multi_space(self):
        assert _cleanup_punctuation("甲  乙") == "甲 乙"


class TestSanitizeRollingPrefix:
    def test_metaphor_dedup_keeps_first(self):
        # 比喻意象去重：同一套路比喻只保留首次出现
        text = "他像石头一样沉默。她像石头一样站着。"
        out = sanitize_rolling_prefix(text)
        assert out.count("像石头一样") == 1

    def test_trailing_modifier_dedup(self):
        text = "他看着我，眼中带着一抹疲惫。她转身，眼中带着一抹疲惫。"
        out = sanitize_rolling_prefix(text)
        assert out.count("眼中带着一抹") == 1

    def test_max_chars_truncation_keeps_tail(self):
        # 超长截断保留**尾部**（rolling_prefix 是衔接线索，尾部离续写点最近）
        filler = "这是一段平稳的叙述。" * 60  # 远超 500 字且零命中
        out = sanitize_rolling_prefix(filler, max_chars=100)
        assert len(out) <= 100
        assert out == filler[-100:]

    def test_empty_prefix(self):
        assert sanitize_rolling_prefix("") == ""

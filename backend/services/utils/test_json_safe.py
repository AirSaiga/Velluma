# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""parse_json_safe 单测——services/utils/json_safe.py（LLM 输出容错解析）。

消费面：adaptive 各组件解析 LLM JSON 响应（意图反推/挂件生发/事件草稿等）。
失败契约：全失败返回 None（调用方自判缺省），绝不抛异常。
"""

from backend.services.utils.json_safe import parse_json_safe


class TestDirectParse:
    def test_plain_object(self):
        assert parse_json_safe('{"a": 1}') == {"a": 1}

    def test_plain_array(self):
        assert parse_json_safe("[1, 2, 3]") == [1, 2, 3]

    def test_empty_and_blank(self):
        assert parse_json_safe("") is None
        assert parse_json_safe("   ") is None
        assert parse_json_safe(None) is None  # type: ignore[arg-type]


class TestMarkdownFence:
    def test_json_fenced(self):
        text = '```json\n{"a": 1}\n```'
        assert parse_json_safe(text) == {"a": 1}

    def test_bare_fenced(self):
        text = '```\n{"a": 1}\n```'
        assert parse_json_safe(text) == {"a": 1}

    def test_fenced_array(self):
        text = "```json\n[1, 2]\n```"
        assert parse_json_safe(text) == [1, 2]


class TestBracketExtraction:
    def test_prose_wrapped_object(self):
        # LLM 爱说废话：「好的，以下是结果：{...}」
        text = '好的，以下是结果：{"intent": "伏笔", "score": 0.8} 希望有帮助'
        assert parse_json_safe(text) == {"intent": "伏笔", "score": 0.8}

    def test_prose_wrapped_array(self):
        text = "结果如下 [\"甲\", \"乙\"] 请查收"
        assert parse_json_safe(text) == ["甲", "乙"]

    def test_invalid_json_returns_none(self):
        assert parse_json_safe("这不是 JSON") is None

    def test_object_preferred_over_array(self):
        # 同时出现 { 与 [ 时先试 {...} 截取（顺序契约）
        text = '废话 [1, { "a": 2 }] 结尾'
        assert parse_json_safe(text) == {"a": 2}

    def test_unclosed_bracket_falls_through(self):
        # 只有开括号没有闭括号 → 截取失败 → None
        assert parse_json_safe("开头 {未闭合") is None

    def test_nested_braces_use_outermost(self):
        text = '{"outer": {"inner": 1}}'
        assert parse_json_safe(text) == {"outer": {"inner": 1}}

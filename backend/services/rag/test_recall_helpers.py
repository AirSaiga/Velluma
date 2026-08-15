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

import unittest

from backend.services.rag.lexical import (
    extract_keywords,
    format_event_echo,
    keyword_coverage,
)


class ExtractKeywordsTests(unittest.TestCase):
    def test_normal_text_yields_keywords(self):
        kws = extract_keywords("林尘攥紧扳手走向灯塔，老烟在礁石滩等他退潮")
        self.assertTrue(len(kws) > 0)
        self.assertLessEqual(len(kws), 8)

    def test_short_or_empty_degrades_to_empty(self):
        self.assertEqual(extract_keywords(""), [])
        self.assertEqual(extract_keywords("  "), [])
        self.assertEqual(extract_keywords("a"), [])  # 单字符被 ≥2 过滤掉


class KeywordCoverageTests(unittest.TestCase):
    def test_scoring_arithmetic(self):
        keywords = ["林尘", "灯塔", "退潮"]
        # 三关键词各命中 1 次：3 × 1/3 = 1.0
        broad = keyword_coverage("林尘在灯塔看退潮。", keywords)
        self.assertAlmostEqual(broad, 1.0)
        # 两关键词（其一反复出现）：封顶满 1 + 退潮 1/3
        deep = keyword_coverage("林尘林尘林尘林尘林尘退潮", keywords)
        self.assertAlmostEqual(deep, 1.0 + 1.0 / 3)

    def test_single_keyword_hit_cap(self):
        keywords = ["林尘"]
        once = keyword_coverage("林尘", keywords)
        many = keyword_coverage("林尘" * 10, keywords)
        self.assertAlmostEqual(once, 1.0 / 3)
        self.assertAlmostEqual(many, 1.0)  # 命中 3 次即满 1 分，之后封顶

    def test_empty_inputs(self):
        self.assertEqual(keyword_coverage("", ["a"]), 0.0)
        self.assertEqual(keyword_coverage("text", []), 0.0)
        self.assertEqual(keyword_coverage("text", [""]), 0.0)


class FormatEventEchoTests(unittest.TestCase):
    def test_full_format(self):
        echo = format_event_echo(
            "alliance", ["林尘", "老烟"], "战俘营结义", 152
        )
        self.assertTrue(echo.startswith("【前情事件·alliance】"))
        self.assertIn("林尘、老烟：", echo)
        self.assertIn("战俘营结义", echo)
        self.assertIn("第 152 日", echo)

    def test_note_truncated_and_fallback(self):
        long_note = "很" * 200
        echo = format_event_echo("battle", ["甲"], long_note, None)
        self.assertLessEqual(len(echo), 30 + 80 + 20)  # 头+截断备注+余量
        self.assertNotIn("第", echo.split("：", 1)[-1])  # 无时间尾巴
        # 空备注回退为事件类型
        fallback = format_event_echo("move", [], "", 10)
        self.assertIn("move", fallback)

    def test_names_capped_at_three(self):
        echo = format_event_echo("war", ["甲", "乙", "丙", "丁"], "", 1)
        self.assertIn("甲、乙、丙", echo)
        self.assertNotIn("丁", echo)


class MergeEchoesTests(unittest.TestCase):
    """三层合并语义：组间质量序 A→V→B 保序、去重、截 k、空串过滤。"""

    def test_group_order_preserved(self):
        from backend.services.rag.recall import merge_echoes

        a = ["【前情事件·a】", "【前情事件·b】"]
        v = ["向量片段1"]
        b = ["词法片段1", "词法片段2"]
        self.assertEqual(merge_echoes([a, v, b], 5), a + v + b)

    def test_dedupe_across_groups(self):
        from backend.services.rag.recall import merge_echoes

        # 向量与词法命中同一块（chunk_text 相同）只保留先到者
        self.assertEqual(
            merge_echoes([["A1"], ["同一片段", "V2"], ["同一片段", "B1"]], 5),
            ["A1", "同一片段", "V2", "B1"],
        )

    def test_cap_and_empty_filter(self):
        from backend.services.rag.recall import merge_echoes

        self.assertEqual(merge_echoes([["A1", "", "A2"], ["V1"]], 2), ["A1", "A2"])
        self.assertEqual(merge_echoes([[], [], []], 3), [])


class EmbeddingRoutingTests(unittest.TestCase):
    """路由开关是纯配置读取（不测具体值，只保证函数存在且返回 bool）。"""

    def test_is_embedding_configured_returns_bool(self):
        from backend.services.llm.embedding import is_embedding_configured

        self.assertIsInstance(is_embedding_configured(), bool)


if __name__ == "__main__":
    unittest.main()

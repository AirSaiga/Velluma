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

import unittest

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
from backend.services.prompts.adaptive_prompts import build_outline_expand_prompt


class OutlineExpandPromptTests(unittest.TestCase):
    """细纲扩写 prompt 结构断言（纯函数，无 LLM/DB）。"""

    def test_double_anchor_sections_present(self):
        system, user = build_outline_expand_prompt(
            outline_note="打一架，她退缩，约300字",
            rolling_prefix="他推门进来，屋里一片漆黑。",
            after_text="第二天清晨，码头上雾还没散。",
            target_chars=400,
        )
        # 双端锚定：上文承接 + 下文引向
        self.assertIn("你的开头要自然承接它的结尾", user)
        self.assertIn("你的结尾要自然引向它的开头", user)
        self.assertIn("他推门进来", user)
        self.assertIn("第二天清晨", user)
        # 禁复述细纲 + 禁提前写下文
        self.assertIn("不要复述细纲原文", user)
        self.assertIn("不要顺势写下文", user)
        # 字数声明
        self.assertIn("400 字以内", user)
        # 速记原文必须作为核心事件出现
        self.assertIn("打一架，她退缩", user)

    def test_empty_after_text_degrades_to_single_anchor(self):
        system, user = build_outline_expand_prompt(
            outline_note="回忆母亲，情绪收束",
            rolling_prefix="他在楼下抽完最后一支烟。",
            after_text="",
            target_chars=300,
        )
        self.assertNotIn("你的结尾要自然引向它的开头", user)
        self.assertIn("自然收束处停笔", user)

    def test_system_blocks_injection(self):
        system, user = build_outline_expand_prompt(
            outline_note="过场",
            rolling_prefix="",
            proper_nouns=["林尘", "阿晚"],
            canon_context="【public】林尘是灯塔看守",
            memory_echoes=["三年前的雨夜，阿晚离开灯塔。"],
        )
        # 共享基座：禁词表已填充
        self.assertIn("、".join(DEFAULT_BAN_LIST.banned_words[:1]), system)
        # 专名硬约束块
        self.assertIn("林尘、阿晚", system)
        # Canon 块
        self.assertIn("灯塔看守", system)
        # 前情回响块
        self.assertIn("三年前的雨夜", system)
        # 空上下文不炸：开篇占位
        self.assertIn("（开篇）", user)

    def test_note_word_hint_excluded_from_prose_instruction(self):
        _, user = build_outline_expand_prompt(
            outline_note="约500字",
            rolling_prefix="前文",
            target_chars=400,
        )
        self.assertIn("字数说明", user)


if __name__ == "__main__":
    unittest.main()

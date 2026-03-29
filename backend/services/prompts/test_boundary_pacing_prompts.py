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

import json
import unittest
from types import SimpleNamespace

from backend.services.prompts.draft_prompts import build_draft_agent_prompt
from backend.services.prompts.planner_prompts import build_planner_agent_prompt
from backend.services.prompts.review_prompts import parse_review_result


class BoundaryPacingPromptTests(unittest.TestCase):
    def test_planner_prompt_injects_low_tension_red_lines(self):
        chapter = SimpleNamespace(
            chapter_name="第十章",
            chapter_number=10,
            title="静水暗涌",
            outline_text="主角在驿站探听消息。",
            tension_level=2,
            pacing_style="slow_burn"
        )
        book = SimpleNamespace(global_sys_prompt="系统提示", worldview_settings={})
        system_prompt, _ = build_planner_agent_prompt(
            chapter=chapter,
            book=book,
            entities=[],
            relationships=[],
            word_count=1800
        )

        self.assertIn("当前章节张力等级为 2（低张力）", system_prompt)
        self.assertIn("每个 beat 的 red_lines 必须包含：避免正面冲突、避免战斗升级", system_prompt)

    def test_draft_prompt_contains_exit_state_stop_and_red_lines(self):
        chapter = SimpleNamespace(
            chapter_name="第十一章",
            chapter_number=11,
            title="桥头夜谈",
            outline_text="两人夜谈后各自离开。"
        )
        book = SimpleNamespace(global_sys_prompt="系统提示", worldview_settings={})
        beat = {
            "summary": "主角试探性询问",
            "action_summary": "对话拉扯后保持克制",
            "entry_state": "两人保持礼貌距离",
            "exit_state": "谈话在试探阶段收束",
            "red_lines": ["不得主动挑衅", "不得升级为肢体冲突"]
        }

        system_prompt, _ = build_draft_agent_prompt(
            chapter=chapter,
            book=book,
            entities=[],
            relationships=[],
            word_count=1200,
            beat=beat
        )

        self.assertIn("强制切出状态（exit_state）：谈话在试探阶段收束", system_prompt)
        self.assertIn("绝对禁忌（red_lines）：不得主动挑衅；不得升级为肢体冲突", system_prompt)
        self.assertIn("必须立即收束并停在 exit_state", system_prompt)

    def test_parse_review_result_normalizes_pacing_overflow_issue(self):
        raw = json.dumps(
            {
                "pass": False,
                "issues": [
                    {
                        "type": "逻辑硬伤",
                        "severity": "high",
                        "description": "文本越过 exit_state 并触发 red_lines，剧情超速推进"
                    }
                ],
                "revision_plan": ""
            },
            ensure_ascii=False
        )
        parsed, error = parse_review_result(raw)

        self.assertIsNone(error)
        self.assertEqual(parsed["issues"][0]["type"], "PACING_OVERFLOW")
        self.assertIn("回退", parsed["revision_plan"])
        self.assertIn("exit_state", parsed["revision_plan"])


if __name__ == "__main__":
    unittest.main()

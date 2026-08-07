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
段级状态追踪器（Agent Loop 1 剧情状态卡）的单测。

纯函数 + mock，不依赖 DB / 真实 LLM。
运行方式（项目根目录）：
    python -m unittest backend.services.workflows.adf.test_state_tracker -v
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.llm.client import REASONING_DISABLED
from backend.services.workflows.adf.name_registry import build_name_registry
from backend.services.workflows.adf.state_tracker import (
    MAX_CARD_BLOCK_CHARS,
    SceneStateCard,
    card_to_prompt_block,
    check_segment_against_card,
    extract_state_card,
    validate_card,
)


def _make_registry():
    return build_name_registry(entities=[
        SimpleNamespace(character=SimpleNamespace(
            name="林尘", aliases=["尘哥"],
            static_prompt="", dynamic_state="",
        )),
        SimpleNamespace(character=SimpleNamespace(
            name="老周", aliases=[],
            static_prompt="", dynamic_state="",
        )),
    ])


class ValidateCardTests(unittest.TestCase):
    def setUp(self):
        self.registry = _make_registry()

    def test_non_dict_returns_none(self):
        self.assertIsNone(validate_card("不是JSON dict", self.registry))
        self.assertIsNone(validate_card(None, self.registry))
        self.assertIsNone(validate_card(["present"], self.registry))

    def test_missing_fields_fall_back_to_defaults(self):
        card = validate_card({}, self.registry)
        self.assertIsNotNone(card)
        self.assertTrue(card.is_empty())
        # 字段类型错误同样容错
        card = validate_card({"present": "林尘", "states": ["x"]}, self.registry)
        self.assertEqual(card.present, [])
        self.assertEqual(card.states, {})

    def test_alias_normalized_to_canonical(self):
        card = validate_card(
            {"present": ["尘哥"], "departed": ["老周"]}, self.registry,
        )
        self.assertEqual(card.present, ["林尘"])
        self.assertEqual(card.departed, ["老周"])

    def test_unregistered_name_dropped(self):
        card = validate_card(
            {"present": ["尘哥", "神秘人"], "departed": ["陌生人"]}, self.registry,
        )
        self.assertEqual(card.present, ["林尘"])
        self.assertEqual(card.departed, [])

    def test_no_registry_keeps_names_verbatim(self):
        # registry 为空无法校验 → 降级宽松，原样保留
        card = validate_card({"present": ["神秘人"]}, None)
        self.assertEqual(card.present, ["神秘人"])

    def test_states_keys_normalized_items_keys_kept(self):
        card = validate_card(
            {
                "states": {"尘哥": "受了伤", "神秘人": "窥视"},
                "items": {"断剑": "林尘手中"},
            },
            self.registry,
        )
        # states 的键是角色名：别名归一 + 表外丢弃
        self.assertEqual(card.states, {"林尘": "受了伤"})
        # items 的键是物品名：不过 registry，原样保留
        self.assertEqual(card.items, {"断剑": "林尘手中"})


class CardToPromptBlockTests(unittest.TestCase):
    def test_empty_card_returns_empty_string(self):
        self.assertEqual(card_to_prompt_block(SceneStateCard()), "")
        self.assertEqual(card_to_prompt_block(None), "")

    def test_block_renders_all_sections(self):
        card = SceneStateCard(
            pov="林尘", location="仓库区",
            present=["林尘"], departed=["老周"],
            states={"林尘": "左臂受伤"}, items={"断剑": "货箱上"},
            progress="对峙升级",
        )
        block = card_to_prompt_block(card)
        self.assertIn("剧情状态卡", block)
        self.assertIn("林尘", block)
        self.assertIn("仓库区", block)
        self.assertIn("老周", block)
        self.assertIn("已死亡/离场", block)
        self.assertIn("断剑", block)

    def test_block_truncated_to_budget(self):
        card = SceneStateCard(
            present=["林尘"],
            states={f"角色{i}": "状态" * 30 for i in range(6)},
            progress="进展" * 40,
        )
        block = card_to_prompt_block(card)
        self.assertLessEqual(len(block), MAX_CARD_BLOCK_CHARS + 1)
        self.assertTrue(block.endswith("…"))


class CheckSegmentAgainstCardTests(unittest.TestCase):
    def test_departed_acting_is_flagged(self):
        card = SceneStateCard(departed=["老周"])
        violations = check_segment_against_card(
            "老周喊了一嗓子，人群往西边跑。", card,
        )
        self.assertEqual(len(violations), 1)
        self.assertIn("老周", violations[0])

    def test_recall_marker_exempts(self):
        card = SceneStateCard(departed=["老周"])
        for text in (
            "他想起老周昨天说过的话。",
            "老周的尸体还躺在废墟里。",
            "她梦到老周站在门口。",
        ):
            self.assertEqual(check_segment_against_card(text, card), [], text)

    def test_marker_in_other_paragraph_does_not_exempt(self):
        # 回忆标记词必须与 departed 名在同一段落才豁免
        card = SceneStateCard(departed=["老周"])
        text = "他想起了很多往事。\n\n老周喊了一嗓子。"
        violations = check_segment_against_card(text, card)
        self.assertEqual(len(violations), 1)

    def test_present_character_not_flagged(self):
        card = SceneStateCard(present=["林尘"], departed=["老周"])
        self.assertEqual(check_segment_against_card("林尘拔剑冲出。", card), [])

    def test_empty_card_never_flags(self):
        self.assertEqual(
            check_segment_against_card("老周喊了一嗓子。", SceneStateCard()), [],
        )
        self.assertEqual(check_segment_against_card("老周喊了一嗓子。", None), [])

    def test_same_name_reported_once(self):
        card = SceneStateCard(departed=["老周"])
        text = "老周推开门。\n\n老周又喊了一嗓子。"
        violations = check_segment_against_card(text, card)
        self.assertEqual(len(violations), 1)


def _run(coro):
    """用独立 event loop 跑异步（不用 asyncio.run / IsolatedAsyncioTestCase——
    它们会把事件循环策略的 _set_called 置位，导致同进程后续测试的
    asyncio.get_event_loop() 抛 RuntimeError，典型症状是 bsadf/test_downgrade
    在本文件之后运行时报错）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class ExtractStateCardTests(unittest.TestCase):
    """extract_state_card 的失败降级与 LLM 调用参数（mock LLM）。

    真实事故：deepseek-v4-pro 忽略 reasoning 关闭参数，400 token 预算全被
    推理烧光，content=''，5 次抽取全灭且静默。
    """

    _LLM = "backend.services.workflows.adf.state_tracker.call_llm_with_usage"

    def test_empty_content_keeps_prev_card(self):
        """LLM 空输出 → 返回同一旧卡对象（调用方据此记 degraded）。"""
        prev = SceneStateCard(pov="林尘", present=["林尘"])
        mock_result = SimpleNamespace(content="", finish_reason="length")
        with patch(self._LLM, new=AsyncMock(return_value=mock_result)):
            card = _run(extract_state_card(prev, "他推开舱门。", None, None, 0))
        self.assertIs(card, prev)

    def test_junk_empty_card_treated_as_failure(self):
        """LLM 返回 {} 之类的全空废卡 → 视为失败沿用旧卡（废卡替换旧卡
        等于静默丢失全部剧情状态）。"""
        prev = SceneStateCard(pov="林尘", present=["林尘"])
        mock_result = SimpleNamespace(content="{}", finish_reason="stop")
        with patch(self._LLM, new=AsyncMock(return_value=mock_result)):
            card = _run(extract_state_card(prev, "他推开舱门。", None, None, 0))
        self.assertIs(card, prev)

    def test_token_budget_and_reasoning_disabled(self):
        """max_tokens=1600（推理关不掉时给 content 留生路）且显式传
        REASONING_DISABLED（空 dict 会被 client 吞掉等于没关）。"""
        prev = SceneStateCard()
        mock_result = SimpleNamespace(content='{"pov": "林尘"}', finish_reason="stop")
        with patch(self._LLM, new=AsyncMock(return_value=mock_result)) as mock_llm:
            card = _run(extract_state_card(prev, "他推开舱门。", None, None, 0))
        kwargs = mock_llm.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], 1600)
        self.assertEqual(kwargs["reasoning_config"], REASONING_DISABLED)
        self.assertEqual(card.pov, "林尘")

    def test_llm_exception_keeps_prev_card(self):
        prev = SceneStateCard(pov="林尘")
        with patch(self._LLM, new=AsyncMock(side_effect=RuntimeError("boom"))):
            card = _run(extract_state_card(prev, "他推开舱门。", None, None, 0))
        self.assertIs(card, prev)


if __name__ == "__main__":
    unittest.main()

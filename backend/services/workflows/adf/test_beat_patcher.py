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
节拍补写器（Phase 6.5 beat_patcher）的单测。

纯函数 + mock LLM，不依赖 DB / 真实 LLM。
运行方式（项目根目录）：
    python -m unittest backend.services.workflows.adf.test_beat_patcher -v
"""

import unittest
from types import SimpleNamespace

import backend.services.workflows.adf.beat_patcher as bp
from backend.services.workflows.adf.beat_patcher import (
    anchor_in_text,
    locate_insert_position,
    parse_outline_beats,
    patch_missing_beats,
    score_beat_coverage,
)

# score_beat_coverage 依赖 jieba 切词：未装 jieba 时降级返回 guess="未知"，
# 这两个依赖切词命中的断言在无 jieba 环境下会误报失败，故跳过。
requires_jieba = unittest.skipIf(
    bp._jieba is None, "jieba 未安装，score_beat_coverage 降级为'未知'"
)


class ParseOutlineBeatsTests(unittest.TestCase):
    def test_fragment_lines_filtered(self):
        outline = "序章\n\n林尘在工棚借着灯光读书\n转折\n工头走进来打断了林尘\n  \n"
        beats = parse_outline_beats(outline)
        # "序章"/"转折"（<6 字）与空白行被丢弃
        self.assertEqual(beats, ["林尘在工棚借着灯光读书", "工头走进来打断了林尘"])

    def test_cap_at_15_beats(self):
        outline = "\n".join(f"这是第{i}个大纲节拍行" for i in range(20))
        beats = parse_outline_beats(outline)
        self.assertEqual(len(beats), 15)

    def test_empty_outline(self):
        self.assertEqual(parse_outline_beats(""), [])
        self.assertEqual(parse_outline_beats(None), [])
        self.assertEqual(parse_outline_beats("短\n也行\n"), [])


class ScoreBeatCoverageTests(unittest.TestCase):
    TEXT = "林尘在工棚里借着灯光读书，工头走了进来，仓库的铁门被风撞得哐当作响。"

    @requires_jieba
    def test_covered_beat_guessed_covered(self):
        beats = ["林尘在工棚里借着灯光读书"]
        result = score_beat_coverage(beats, self.TEXT)
        self.assertEqual(result[0]["guess"], "疑似覆盖")
        self.assertGreaterEqual(result[0]["coverage"], 0.35)

    @requires_jieba
    def test_missing_beat_guessed_missing(self):
        beats = ["白霆驾驶流光机甲逃离统合局"]
        result = score_beat_coverage(beats, self.TEXT)
        self.assertEqual(result[0]["guess"], "疑似缺失")
        self.assertLess(result[0]["coverage"], 0.35)

    def test_jieba_unavailable_returns_unknown(self):
        old = bp._jieba
        bp._jieba = None
        try:
            result = score_beat_coverage(["林尘在工棚里借着灯光读书"], self.TEXT)
            self.assertEqual(result[0]["guess"], "未知")
            self.assertIsNone(result[0]["coverage"])
        finally:
            bp._jieba = old


class AnchorLocateTests(unittest.TestCase):
    PARAS = [
        "灰尘还没散。林尘从碎石堆里抬起头，看见的不是头顶塌陷的天花板。",
        "然后他听见了说话声，声音从仓库深处传来。",
        "白霆站在货箱上，慢条斯理地摘下手套。",
    ]

    def test_raw_substring_hit(self):
        idx = locate_insert_position(self.PARAS, "然后他听见了说话声")
        self.assertEqual(idx, 1)

    def test_normalized_fallback_hit(self):
        # 引文标点与正文不同（，vs 。）→ 原文子串失败，归一化子串命中
        idx = locate_insert_position(self.PARAS, "灰尘还没散，林尘从碎石堆里抬起头")
        self.assertEqual(idx, 0)

    def test_not_found_returns_none(self):
        self.assertIsNone(locate_insert_position(self.PARAS, "完全不存在的引文内容"))
        self.assertIsNone(locate_insert_position(self.PARAS, ""))

    def test_anchor_in_text(self):
        text = "\n\n".join(self.PARAS)
        self.assertTrue(anchor_in_text(text, "白霆站在货箱上"))
        self.assertTrue(anchor_in_text(text, "白霆站在货箱上，慢条斯理"))
        self.assertFalse(anchor_in_text(text, "林尘驾驶机甲逃离"))
        self.assertFalse(anchor_in_text(text, ""))


def _make_missing_beat(quote, position="after", patchable=True, beat="林尘在工棚借着灯光读书"):
    return {
        "beat": beat,
        "status": "missing",
        "evidence": "正文未写",
        "insert_position": position,
        "insert_anchor_quote": quote,
        "patchable": patchable,
    }


class PatchMissingBeatsTests(unittest.IsolatedAsyncioTestCase):
    P0 = "灰尘还没散。林尘从碎石堆里抬起头，看见的不是头顶塌陷的天花板。"
    P1 = "然后他听见了说话声，声音从仓库深处传来。"
    P2 = "白霆站在货箱上，慢条斯理地摘下手套。"
    PATCH = "工棚的灯泡忽明忽暗，林尘把书页又翻过一页，指尖在行间停了很久。" \
            "门轴一响，工头的影子先一步跨进来，嗓音把满屋寂静砸得粉碎。" \
            "林尘合上书，慢慢站起身，把那点还没来得及沉淀的思绪收回了眼底。"

    def _text(self):
        return "\n\n".join([self.P0, self.P1, self.P2])

    def _mock_llm(self, content):
        async def fake_call(**kwargs):
            return SimpleNamespace(content=content)
        return fake_call

    async def asyncSetUp(self):
        self._orig_call = bp.call_llm_with_usage

    async def asyncTearDown(self):
        bp.call_llm_with_usage = self._orig_call

    async def test_patch_inserted_after_anchor(self):
        self.assertGreaterEqual(len(self.PATCH), 80)  # 护栏下限自检
        bp.call_llm_with_usage = self._mock_llm(self.PATCH)
        result = await patch_missing_beats(
            final_text=self._text(),
            missing_beats=[_make_missing_beat("然后他听见了说话声", "after")],
            purpose="测试主旨",
            style_contract="",
            name_registry_block="",
        )
        self.assertEqual(result.patched, ["林尘在工棚借着灯光读书"])
        self.assertEqual(result.failed, [])
        paras = result.new_text.split("\n\n")
        # 结构完整性：插入到锚点段（P1）之后，原有段落顺序不变
        self.assertEqual(paras, [self.P0, self.P1, self.PATCH, self.P2])

    async def test_patch_inserted_before_anchor(self):
        bp.call_llm_with_usage = self._mock_llm(self.PATCH)
        result = await patch_missing_beats(
            final_text=self._text(),
            missing_beats=[_make_missing_beat("灰尘还没散", "before")],
            purpose="测试主旨",
            style_contract="",
            name_registry_block="",
        )
        paras = result.new_text.split("\n\n")
        self.assertEqual(paras, [self.PATCH, self.P0, self.P1, self.P2])

    async def test_overlong_output_abandoned(self):
        bp.call_llm_with_usage = self._mock_llm("长" * 700)
        result = await patch_missing_beats(
            final_text=self._text(),
            missing_beats=[_make_missing_beat("然后他听见了说话声")],
            purpose="", style_contract="", name_registry_block="",
        )
        self.assertEqual(result.patched, [])
        self.assertEqual(result.failed[0]["reason"], "length_guard")
        self.assertEqual(result.new_text, self._text())  # 保留原文

    async def test_too_short_output_abandoned(self):
        bp.call_llm_with_usage = self._mock_llm("太短了。")
        result = await patch_missing_beats(
            final_text=self._text(),
            missing_beats=[_make_missing_beat("然后他听见了说话声")],
            purpose="", style_contract="", name_registry_block="",
        )
        self.assertEqual(result.failed[0]["reason"], "length_guard")

    async def test_output_copying_neighbor_abandoned(self):
        # 邻段与补写输出都是长文本（≥200 字）且相同 → segment_too_similar 护栏拦截
        long_a = "仓库的铁门被风撞得哐当作响，林尘把身影藏进立柱后的阴影里。" * 8
        long_b = "白霆站在货箱上，慢条斯理地摘下手套，声音不大却让众人心惊。" * 8
        text = "\n\n".join([long_a, long_b])
        bp.call_llm_with_usage = self._mock_llm(long_a)
        result = await patch_missing_beats(
            final_text=text,
            missing_beats=[_make_missing_beat("白霆站在货箱上", "before")],
            purpose="", style_contract="", name_registry_block="",
        )
        self.assertEqual(result.patched, [])
        self.assertEqual(result.failed[0]["reason"], "duplicate_guard")
        self.assertEqual(result.new_text, text)

    async def test_unpatchable_beat_skipped(self):
        called = []

        async def spy_call(**kwargs):
            called.append(kwargs)
            return SimpleNamespace(content=self.PATCH)

        bp.call_llm_with_usage = spy_call
        result = await patch_missing_beats(
            final_text=self._text(),
            missing_beats=[_make_missing_beat("然后他听见了说话声", patchable=False)],
            purpose="", style_contract="", name_registry_block="",
        )
        self.assertEqual(called, [])  # patchable=False 根本不进 LLM 流程
        self.assertEqual(result.patched, [])
        self.assertEqual(result.failed, [])  # 也不算补写失败（只上报）
        self.assertEqual(result.new_text, self._text())


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""2026-09-03 双轨生成契约对拍：选档判据 + prompt 契约变体。

问题（trace 实证）：stitch/continue 只有推进一档，幽灵把一切供给当「该立刻
写掉的事」，不会停在当下细写。解法：motion/texture 双轨由代码选档——
零件槽位优先（作者亲选=意图明证），无零件走尾部「了」密度兜底。

运行：.venv/Scripts/python.exe -m pytest backend/services/adaptive/test_texture_contract.py -v
"""

from backend.services.adaptive.texture_contract import (
    CONTRACT_MOTION,
    CONTRACT_TEXTURE,
    pick_contract,
)
from backend.services.prompts.adaptive_prompts import build_continue_prompt

DENSE_TAIL = "他抄起扳手拧了两圈，机油溅了他一手，他骂了一句，把螺栓重新拧紧，起身拍了拍裤子上的灰，又转身去开另一台机器，一口气把三台车床全都校了一遍。"
SPARSE_TAIL = "车间里很安静。灯光从高高的窗户斜下来，落在他的工作台上，像一层薄薄的白灰，覆盖着一切。远处传来机器的嗡鸣，他站在那里，很久没有动。"


class TestPickContract:
    def test_other_modes_always_motion(self):
        for m in ("burst", "outline", "open"):
            assert pick_contract(m, ["echo"], DENSE_TAIL) == CONTRACT_MOTION

    def test_motion_slots_win(self):
        assert pick_contract("stitch", ["landing"], "") == CONTRACT_MOTION
        assert pick_contract("stitch", ["toward_beat"], "") == CONTRACT_MOTION
        # 混合点选：有推进型槽位即 motion（作者既要氛围又要推进时，推进优先）
        assert pick_contract("stitch", ["ambient", "landing"], "") == CONTRACT_MOTION

    def test_texture_slots_select_texture(self):
        assert pick_contract("stitch", ["echo"]) == CONTRACT_TEXTURE
        assert pick_contract("stitch", ["ambient"]) == CONTRACT_TEXTURE
        assert pick_contract("stitch", ["echo", "ambient"]) == CONTRACT_TEXTURE

    def test_unknown_slot_falls_back_motion(self):
        assert pick_contract("stitch", ["", " nonsense "]) == CONTRACT_MOTION

    def test_density_fallback(self):
        # 无零件：尾部动作密度高（刚连续推进）→ 允许停下来细写
        assert pick_contract("continue", [], DENSE_TAIL) == CONTRACT_TEXTURE
        assert pick_contract("stitch", None, DENSE_TAIL) == CONTRACT_TEXTURE
        assert pick_contract("continue", [], SPARSE_TAIL) == CONTRACT_MOTION
        # 尾部太短（章刚开始）→ 地上没东西可细写，motion
        assert pick_contract("continue", [], "他来了。") == CONTRACT_MOTION
        assert pick_contract("continue", [], "") == CONTRACT_MOTION


class TestContractPromptVariants:
    def test_motion_is_default_and_byte_identical(self):
        args = dict(fragment="他放下扳手", rolling_prefix="前文……", mode="stitch")
        default = build_continue_prompt(**args)
        explicit = build_continue_prompt(contract="motion", **args)
        assert default == explicit
        assert "只写新东西" in default[1]
        assert "停在当下细写" not in default[1]

    def test_texture_swaps_advance_rule(self):
        _sys, user = build_continue_prompt(
            "他放下扳手", "前文……", mode="stitch", contract="texture",
        )
        assert "停在当下细写" in user
        assert "唯一的推进是感受的加深" in user
        assert "只写新东西" not in user
        # 其余戒律不受影响：接缝契约与结尾律原样在
        assert "从它的断点直接往下写" in user
        assert "停在人物自己正在做的事上" in user

    def test_continue_texture_variant(self):
        _sys, user = build_continue_prompt(
            "他放下扳手", "前文……", mode="continue", contract="texture",
        )
        assert "停在当下细写" in user
        assert "只写新东西" not in user

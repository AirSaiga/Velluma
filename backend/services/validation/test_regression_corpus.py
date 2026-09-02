# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - out_of_scene 检测器事故回归语料库准入测试
"""
准入门槛（约束治理一期 · docs/constraint-governance.md §回归语料库）：

- 事故样本（流光穿帮真实 trace 文本）100% 命中；
- 合法样本（纯叙述/对白预告/负面动词清单）0 误报；
- 豁免样本（闪回回指词）产 exempt 不产 warning；
- 已知误伤面（对白转述/铭文/背景叙事）命中并显式归档——一期接受的 shadow
  FP，未来若判据进化使它们变 no-hit，本测试就是要求同步更新归档的哨兵。

换模型 checklist 的一部分：换厂商/型号后重跑本语料库 + 注册表按模型分桶
（docs/constraint-governance.md §换模型）。

运行：python -m pytest backend/services/validation/test_regression_corpus.py -v
"""
import json
from pathlib import Path

import pytest

from backend.services.context.scene_visibility import (
    find_location_jump_hits,
    find_out_of_scene_hits,
)

CORPUS_DIR = Path(__file__).parent / "regression_corpus"
# 《最终武装》第 1 章开篇形态：林尘是唯一在场/提及者；势力「统合局」不入
# 候选宇宙（组织不是物件，事件语料实证「统合局×检修」是纯碰撞）
VISIBLE = ["林尘"]
UNIVERSE = ["林尘", "流光", "白霆", "血噬", "红月"]


def _cases(filename: str) -> list:
    return _corpus(filename)["cases"]


def _corpus(filename: str) -> dict:
    return json.loads((CORPUS_DIR / filename).read_text(encoding="utf-8"))


def _hits(text: str) -> list:
    return find_out_of_scene_hits(text, VISIBLE, UNIVERSE)


@pytest.mark.parametrize(
    "case", _cases("incident_liuguang.json"), ids=lambda c: c["text"][:18]
)
def test_incident_corpus(case):
    hits = _hits(case["text"])
    hit_names = {h["name"] for h in hits}
    if case["expect"] == "hit":
        assert hits, f"事故样本漏报：{case['note']}"
    elif case["expect"] == "no_hit":
        assert not hits, f"合法样本误报：{hits} | {case['note']}"
    elif case["expect"] == "known_fp_hit":
        # 一期接受的 shadow 误伤面：命中是「现状的显式归档」——若判据进化使
        # 其变 no-hit，请同步更新本条归档与 note（哨兵语义）
        assert hits, f"已知误伤面行为变化（更新归档）: {case['note']}"


@pytest.mark.parametrize(
    "case", _cases("boundary_cases.json"), ids=lambda c: c["text"][:18]
)
def test_boundary_corpus(case):
    hits = _hits(case["text"])
    if case["expect"] == "no_hit":
        assert not hits, f"边界合法样本误报：{hits} | {case['note']}"
    elif case["expect"] == "exempt":
        assert hits and all(h["exempt"] for h in hits), (
            f"闪回豁免样本应产 exempt 而非真命中：{hits} | {case['note']}"
        )
    elif case["expect"] == "hit":
        assert hits and not any(h["exempt"] for h in hits), (
            f"对照样本应真命中（豁免不能吞掉真越界）：{hits}"
        )


def test_flagship_incident_hits_liuguang_exact():
    """旗舰断言：截图原文必须由「流光」本体命中（而非其他名字的碰撞证据）。"""
    case = next(
        c for c in _cases("incident_liuguang.json") if c["expect"] == "hit"
    )
    hits = _hits(case["text"])
    assert any(h["name"] == "流光" and h["verb"] == "拧" for h in hits)


# ============================================================
# 地点穿越闸（ghost-guard-location-jump，二期 shadow 出生）
# ============================================================

_LOCATION_JUMP = _corpus("location_jump_cases.json")
OFF_SCENE_LOCATIONS = _LOCATION_JUMP["off_scene_locations"]


@pytest.mark.parametrize(
    "case", _LOCATION_JUMP["cases"], ids=lambda c: c["text"][:18]
)
def test_location_jump_corpus(case):
    hits = find_location_jump_hits(case["text"], OFF_SCENE_LOCATIONS)
    if case["expect"] == "no_hit":
        assert not hits, f"合法样本误报：{hits} | {case['note']}"
    elif case["expect"] == "exempt":
        assert hits and all(h["exempt"] for h in hits), (
            f"闪回豁免样本应产 exempt 而非真命中：{hits} | {case['note']}"
        )
    elif case["expect"] == "hit":
        assert hits and not any(h["exempt"] for h in hits), (
            f"穿越样本漏报（或被豁免吞掉）：{hits} | {case['note']}"
        )


def test_location_jump_flagship_verb_adjacency():
    """旗舰断言：「走进了北岸要塞」必须由 走进×北岸要塞 本体命中。"""
    case = _LOCATION_JUMP["cases"][0]
    hits = find_location_jump_hits(case["text"], OFF_SCENE_LOCATIONS)
    assert any(h["name"] == "北岸要塞" and h["verb"] == "走进" for h in hits)

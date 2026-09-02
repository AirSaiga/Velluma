# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - dock prompt 编译器验收闸（约束治理一期 · 剂量治理样板）
"""
验收闸（导师审查裁决：第 5 组是批次内唯一「pytest 看不见回归」的组，
三件套②③在此落锁；③黄金 trace 对拍=人工闸，施工收口时单独执行）：

1. 三形态 diff 即测试——全素材/无就近节拍/无 echo 素材三种输入下，编译
   产物的差异仅限预期子句缺席（节拍依赖子句/echo 规则的出没边界）；
2. 剂量 lint——强措辞（铁律/绝不/必须/禁止/不许/严禁/务必）计数达标：
   「铁律」归零（三个节名+编号头全退役）、总较旧基线（15+）显著下降；
3. 过采样要求 4-6 枚、自检清单删除——prompt 侧与 dock 校对环代码闸的
   分工契约。

运行：python -m pytest backend/services/prompts/test_dock_prompt_compiler.py -v
"""
from backend.services.constraints.registry import scan_prompt_wording
from backend.services.prompts.adaptive_prompts import build_dock_generator_prompt

_RECENT = "林尘停下手里的活，在这个世道，这句话"
_NEARBY = ["林尘喜欢读书，干着活的期间想到昨晚读到的内容，正在发愣"]
_EXPECTATIONS = [{"type": "mystery", "description": "那本书的来历", "tension": 7}]
_ECHOES = ["第三章：扳手砸中脚边铁屑"]


def _build(nearby=False, expectations=None, echoes=None):
    return build_dock_generator_prompt(
        _RECENT,
        projections=[],
        nutrients={},
        hard_constraints={},
        outline_nearby=_NEARBY if nearby else None,
        reader_expectations=expectations,
        memory_echoes=echoes,
    )


class TestThreeFormDiff:
    """编译产物差异仅限预期分节缺席（diff 即测试）。"""

    def test_full_material_form(self):
        system, user = _build(nearby=True, expectations=_EXPECTATIONS, echoes=_ECHOES)
        # 节拍依赖子句在
        for phrase in ("节拍保全检验", "写不坏节拍的才是第一步", "节拍 > 推测",
                       "绝不提前搬上来", "toward_beat【通往节拍】"):
            assert phrase in system, f"全素材形态缺 {phrase}"
        # 通用约束在
        for phrase in ("下一屏", "文流第一", "道具分两类", "上手件", "空间不瞬移",
                       "保底本场景", "不复述已写"):
            assert phrase in system, f"通用约束缺 {phrase}"
        # 自检清单已删（中档模型负资产）
        assert "自检" not in system
        # 过采样：4-6 枚
        assert "生成 4-6 个" in user
        assert "生成 3-4 个" not in user
        # toward_beat 子句在有节拍时出现
        assert "给了就近节拍则含 1 枚 toward_beat" in user

    def test_no_outline_form_beat_clauses_absent(self):
        system, user = _build()
        for phrase in ("节拍保全检验", "写不坏节拍的才是第一步", "节拍 > 推测",
                       "绝不提前搬上来", "toward_beat【通往节拍】"):
            assert phrase not in system, f"无大纲形态不应有 {phrase}"
        assert "给了就近节拍则含" not in user
        # 通用约束与无节拍兜底在
        for phrase in ("下一屏", "文流第一", "保底本场景", "没有大纲节拍可用时"):
            assert phrase in system, f"无大纲形态通用约束缺 {phrase}"

    def test_no_echo_material_form(self):
        """无期待/回响素材：echo 槽位规则恒在（无害），素材块本身缺席。"""
        system, user = _build(nearby=True)
        assert "slot=echo【呼应】" in system
        assert "读者期待" not in user          # 素材块缺席
        assert "前情回响" not in user


class TestDosageLint:
    """强措辞剂量：编译产物过 registry.scan_prompt_wording 验收。"""

    def test_full_form_strong_wording_budget(self):
        system, _user = _build(nearby=True, expectations=_EXPECTATIONS, echoes=_ECHOES)
        counts = scan_prompt_wording(system)
        # 旧整段常量基线 15+ 处；编译器化后「铁律」归零、总数个位数
        assert counts.get("铁律", 0) == 0, f"铁律措辞残留: {counts}"
        assert counts.get("total", 0) <= 4, f"强措辞总量超预算: {counts}"

    def test_lint_reports_dictionary_words(self):
        report = scan_prompt_wording("这是铁律，必须遵守；绝对不行也禁止。")
        assert report["铁律"] == 1 and report["必须"] == 1 and report["禁止"] == 1
        assert report["total"] == 3
        assert "绝不" not in report or report.get("绝不", 0) == 0  # 「绝对」不算「绝不」

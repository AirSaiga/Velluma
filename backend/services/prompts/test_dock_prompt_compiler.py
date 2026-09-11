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
        """无期待/回响素材：echo 槽位换「允许零呼应」柔性变体（2026-09-11
        前情强买强卖修复——召回侧相关性门 + prompt 同口径放开），素材块缺席。"""
        system, user = _build(nearby=True)
        assert "slot=echo：本批无相关前情或读者期待素材" in system
        assert "无需强行生成呼应件" in system
        assert "呼应类允许零枚" in system
        assert "slot=echo【呼应】" not in system   # 旧硬性槽位定义退场
        assert "读者期待" not in user          # 素材块缺席
        assert "前情回响" not in user

    def test_echo_material_form_zero_change(self):
        """有回响/期待素材：旧 echo 槽位定义逐字节在场（拆节零变化契约）。"""
        system, user = _build(nearby=True, expectations=_EXPECTATIONS, echoes=_ECHOES)
        assert "- slot=echo【呼应】（至多 1 枚）：呼应前情回响或读者期待的碎片" in system
        assert "重演前情等于没给选项" in system
        assert "- slot=ambient【氛围】（其余补位）" in system
        assert "允许零呼应" not in system
        assert "# 前情回响" in user


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


# ============================================================
# 在场制形态（2026-09-08 红队「地面+重力场」重构验收）
# ============================================================
_ONSTAGE = {
    "entities": [{"name": "林尘", "state": "此刻位于北岸要塞·机房"}],
    "props": [{"name": "发电机", "desc": "机房尽头的老柴油机"}],
    "scene_line": "北岸要塞·机房——铁皮机房，柴油味重",
    "offstage_characters": ["老周"],
    "offstage_assets": ["脚手架"],
}


def _build_onstage(template="default", nearby=True):
    return build_dock_generator_prompt(
        _RECENT,
        projections=[],
        nutrients={},
        hard_constraints={},
        outline_nearby=_NEARBY if nearby else None,
        reader_expectations=_EXPECTATIONS,
        memory_echoes=_ECHOES,
        onstage=_ONSTAGE,
        template=template,
    )


class TestOnstageForm:
    """在场制（有 onstage 投影）：三档物质性 + 在册坐标系 + 引力措辞。"""

    def test_three_tier_replaces_two_class(self):
        system, user = _build_onstage()
        # 三档物质性上场，两分法退位（legacy 形态仍保留两分法——见 TestThreeFormDiff）
        assert "道具三档" in system
        assert "指不出来源的质感就是造物" in system
        assert "道具分两类" not in system
        # 在册块 + anchor_ref 序号坐标系（entities 在前 props 在后统一编号）
        assert "本场在册" in user
        assert "[1] 林尘" in user
        assert "[2] 发电机" in user
        # 养料在场制拆分：场外只留名字
        assert "场外物件：脚手架" in user
        # 引力措辞取代配额子句
        assert "贴近就近节拍即可" in user
        assert "给了就近节拍则含 1 枚 toward_beat" not in user

    def test_dialogue_template_sections(self):
        system, _ = _build_onstage(template="dialogue")
        assert "slot=reply【接话缓冲】" in system
        assert "slot=prop【在场特写】" in system
        assert "anchor_ref" in system
        # 模板分派下 toward_beat 子句退位（引力已接管方向）
        assert "toward_beat【通往节拍】" not in system

    def test_combat_panorama_templates(self):
        system, _ = _build_onstage(template="combat")
        assert "搏杀时刻的槽位取向" in system
        assert "slot=reply" not in system
        system, _ = _build_onstage(template="panorama")
        assert "初入新地的槽位取向" in system
        assert "册外不添" in system

    def test_template_without_onstage_normalizes_default(self):
        """零变化契约：无 onstage 时模板强制归一 default，模板分节不悬空。"""
        system, user = build_dock_generator_prompt(
            _RECENT, projections=[], nutrients={}, hard_constraints={},
            outline_nearby=_NEARBY, template="dialogue",
        )
        assert "slot=reply" not in system
        assert "本场在册" not in user
        # legacy 配额子句原样（与 TestThreeFormDiff 同口径）
        assert "给了就近节拍则含 1 枚 toward_beat" in user
        assert "道具分两类" in system

    def test_onstage_dialogue_dosage_budget(self):
        """在场制+模板形态的强措辞剂量同样受验收闸约束。"""
        system, _ = _build_onstage(template="dialogue")
        counts = scan_prompt_wording(system)
        assert counts.get("铁律", 0) == 0, f"铁律措辞残留: {counts}"
        assert counts.get("total", 0) <= 4, f"强措辞总量超预算: {counts}"


class TestBridgeForm:
    """中插桥接形态（2026-09-09 FIM）：slots-bridge 分节 + 下文禁区块 + 免大纲引力。"""

    def test_bridge_sections_and_suffix_block(self):
        system, user = build_dock_generator_prompt(
            _RECENT, projections=[], nutrients={}, hard_constraints={},
            onstage=_ONSTAGE, template="bridge",
            suffix_anchor="“今晚回来得晚了些。”明姐端来脸盆。",
        )
        assert "中插桥接" in system
        assert "下文已写的事实是禁区" in system
        assert "下文已写" in user and "明姐端来脸盆" in user
        # 桥不吃大纲引力配额（方向由后文锚定义）
        assert "贴近就近节拍" not in user

    def test_bridge_survives_without_onstage(self):
        """零变化契约边界：bridge 是光标位置事实——legacy 书（无在册）同样分派。"""
        system, user = build_dock_generator_prompt(
            _RECENT, projections=[], nutrients={}, hard_constraints={},
            template="bridge", suffix_anchor="明姐端来脸盆。",
        )
        assert "中插桥接" in system
        assert "本场在册" not in user                    # 无在册块（legacy 形态）

    def test_suffix_empty_keeps_legacy_bytes(self):
        a = build_dock_generator_prompt(
            _RECENT, projections=[], nutrients={}, hard_constraints={},
            outline_nearby=_NEARBY,
        )
        assert "下文已写" not in a[1]
        assert "给了就近节拍则含 1 枚 toward_beat" in a[1]   # legacy 配额原文未动

    def test_bridge_cuts_doc_edge_supply(self):
        """桥接供给切断（2026-09-09「卡片接着文末写」事故）：推测/方向猜测/
        就近节拍全以含后文的画布全文推导，桥接态=后文剧透——素材块与对应
        系统分节一并断供（桥的方向由后文锚定义）。"""
        projections = [{"possible_beats": [
            {"event": "明姐把炖菜搁上桌", "anchors": ["陶盆"]},
        ]}]
        system, user = build_dock_generator_prompt(
            _RECENT, projections=projections, nutrients={}, hard_constraints={},
            onstage=_ONSTAGE, template="bridge", suffix_anchor="明姐端来脸盆。",
            outline_nearby=_NEARBY, intent_guess="林尘坐下吃明姐做的饭",
        )
        # 推测块切断（回落自由生发占位行）
        assert "明姐把炖菜搁上桌" not in user
        assert "（无推测，基于当前段落自由生发）" in user
        # 就近节拍/意图猜测切断（猜测块本例被节拍优先压住，另建无节拍形态断言）
        assert "作者大纲·就近节拍" not in user
        assert "林尘坐下吃明姐做的饭" not in user
        # 系统分节同口径：无节拍供给 → 节拍保全分节缺席、无节拍兜底在
        assert "节拍保全检验" not in system
        assert "没有大纲节拍可用时" in system
        # 桥接本体的双端材料不受影响
        assert "下文已写" in user and "明姐端来脸盆" in user
        assert "中插桥接" in system

    def test_bridge_cuts_guess_only_supply(self):
        """无节拍+有猜测的桥接形态：猜测块（toward_beat 供料）同样切断。"""
        system, user = build_dock_generator_prompt(
            _RECENT, projections=[], nutrients={}, hard_constraints={},
            template="bridge", suffix_anchor="明姐端来脸盆。",
            intent_guess="往明姐家的饭桌走",
        )
        assert "本章方向猜测" not in user
        assert "toward_beat【通往方向】" not in system

    def test_non_bridge_keeps_supply_bytes(self):
        """零变化契约：无 suffix_anchor 时推测/节拍供给原样（桥接切断不外溢）。"""
        projections = [{"possible_beats": [
            {"event": "明姐把炖菜搁上桌", "anchors": ["陶盆"]},
        ]}]
        system, user = build_dock_generator_prompt(
            _RECENT, projections=projections, nutrients={}, hard_constraints={},
            onstage=_ONSTAGE, template="default",
            outline_nearby=_NEARBY,
        )
        assert "明姐把炖菜搁上桌" in user
        assert "作者大纲·就近节拍" in user
        assert "节拍保全检验" in system

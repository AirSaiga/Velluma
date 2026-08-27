# Velluma - NLE-ADF 场景锚定 prompt 契约单测
# AGPL-3.0
"""
2026-08-27 场景锚定修复轮的契约锁。

背景：实测幽灵草稿「完全不符合场景」——推测组件看不到大纲，凭「读书+上海」
字面联想幻觉出错误时代场景（2177 工地发愣 → 民国书房钢笔木窗），挂件继承
错误推测还生造道具，stitch 契约「必须落地」又把场景错误的零件硬塞进正文。

锁定：
- 推测 prompt：大纲就近节拍块注入/缺席零变化；系统行场景锚定在位
- 挂件系统：时态锚定（道具必须在「此刻」）与节拍>推测两条新铁律在位
- stitch：零件落地的「正文事实最高优先」改造出口在位
"""
from backend.services.prompts.adaptive_prompts import (
    build_continue_prompt,
    build_dock_generator_prompt,
    build_future_projection_prompt,
    _DOCK_GENERATOR_SYSTEM,
    _FUTURE_PROJECTION_SYSTEM,
)


class TestProjectionSceneAnchoring:
    def test_nearby_block_injected(self):
        """大纲就近节拍块注入：推测锚到作者定的下一步。"""
        _, user = build_future_projection_prompt(
            written_text="林尘停下手里的活，在这个世道，",
            intent={"arc": "血噬的觉醒", "emotion_curve": [], "setup_points": []},
            nutrients={},
            soft_constraints={},
            outline_nearby=["林尘喜欢读书，干着活的期间想到昨晚读到的内容，正在发愣"],
        )
        assert "作者大纲·就近节拍" in user
        assert "干着活的期间" in user
        assert "不得与节拍的场景矛盾" in user

    def test_nearby_block_absent_zero_change(self):
        """无节拍 → 整块缺席（旧书无大纲 prompt 零变化契约）。"""
        _, user = build_future_projection_prompt(
            written_text="灯下。",
            intent={"arc": "x", "emotion_curve": [], "setup_points": []},
            nutrients={},
            soft_constraints={},
        )
        assert "就近节拍" not in user

    def test_system_scene_anchor_line(self):
        """系统行：场景锚定禁字面联想换场景/时代。"""
        assert "场景锚定" in _FUTURE_PROJECTION_SYSTEM
        assert "切换到另一个场景、时代或道具库" in _FUTURE_PROJECTION_SYSTEM


class TestDockTemporalRules:
    def test_beat_over_projection_rule(self):
        """节拍 > 推测：冲突时以节拍为准，推测只取情绪。"""
        assert "节拍 > 推测" in _DOCK_GENERATOR_SYSTEM
        assert "不取其场景与道具" in _DOCK_GENERATOR_SYSTEM


class TestStitchPartEscapeHatch:
    def test_picked_part_scene_override(self):
        """stitch：零件与正文场景矛盾时改造优先于硬塞（正文事实最高优先）。"""
        _, user = build_continue_prompt(
            fragment="这是林尘昨晚睡前翻书时撇到的话，在这个世道，",
            rolling_prefix="灯下。",
            mode="stitch",
            picked_parts=["林尘指尖摩挲着书页折角"],
        )
        assert "作者正文的事实最高优先" in user
        assert "绝不硬塞" in user


class TestPerceptionBeatBoundary:
    """2026-08-27 感知逻辑诊断轮（导师裁决）：节拍边界 + 物理落点。"""

    def test_projection_stage_contract(self):
        """推测输出契约：stage 枚举标注，首幅必为 now（接缝裁剪的数据源）。"""
        _, user = build_future_projection_prompt(
            written_text="林尘停下手里的活",
            intent={"arc": "x", "emotion_curve": [], "setup_points": []},
            nutrients={},
            soft_constraints={},
        )
        assert '"stage"' in user
        assert "第一幅必须是" in user
        assert "approach" in user and "beat" in user and "after" in user

    def test_dock_physical_landing_priority(self):
        """第一优先：作者最后一句的物理落点（主动作，非表情非静止）。"""
        assert "接住作者刚写的" in _DOCK_GENERATOR_SYSTEM
        assert "物理落点" in _DOCK_GENERATOR_SYSTEM
        assert "主动发出" in _DOCK_GENERATOR_SYSTEM

    def test_dock_beat_preservation_test(self):
        """节拍保全检验替换旧对白禁令：写不坏节拍的才是第一步。"""
        assert "节拍保全检验" in _DOCK_GENERATOR_SYSTEM
        assert "写不坏节拍的才是第一步" in _DOCK_GENERATOR_SYSTEM
        assert "在来的路上" in _DOCK_GENERATOR_SYSTEM
        assert "不许" in _DOCK_GENERATOR_SYSTEM and "已经到达" in _DOCK_GENERATOR_SYSTEM

    def test_dock_prop_two_classes(self):
        """道具两分：氛围件自由生发，上手件须出处（连续性债判据）。"""
        assert "氛围件" in _DOCK_GENERATOR_SYSTEM
        assert "上手件" in _DOCK_GENERATOR_SYSTEM
        assert "连续性债" in _DOCK_GENERATOR_SYSTEM

    def test_dock_arrival_exception_noted(self):
        """空间不瞬移括注：抵达即节拍的情形交给保全检验。"""
        assert "除非抵达本身就是那一拍的事件" in _DOCK_GENERATOR_SYSTEM

    def test_quota_current_moment_bound(self):
        """方向配额满足域限定：禁止跳到节拍之后凑数。"""
        _, user = build_dock_generator_prompt(
            "林尘停下手里的活，在这个世道，这句话",
            projections=[],
            nutrients={},
            hard_constraints={},
            salience_hints=["林尘（近3段提及2次）", "白露（被冷落的重要）"],
        )
        # B7：方向权重配额已废——热层具名提示行取代（常量权重下的硬性扭曲）
        assert "此刻值得盯住" in user
        assert "林尘（近3段提及2次）" in user

    def test_projection_block_anti_compressor(self):
        """推测注入块：防挂件退化成推测压缩器（优先从当前段落生发）。"""
        _, user = build_dock_generator_prompt(
            "林尘停下手里的活，在这个世道，这句话",
            projections=[],
            nutrients={},
            hard_constraints={},
        )
        assert "优先从作者当前段落生发" in user
        assert "不得整句照搬推测画面" in user

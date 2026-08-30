# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
分模式差异化注入单测（P5 批次 4 · C3，docs/foundation-hardening.md §5.3）。

克制首版三处的 prompt 级契约（纯函数，不连 LLM/DB）：
1. burst 样本加量（k 2→3）：无样本书 prompt 逐字节不变（零变化锁）；
   3 条样本满额注入不被预算裁剪（k=3 的装配侧断言在
   test_stitch_context.TestAssembleQueryContract，满配 allocate 对账在
   test_budget_allocate.test_burst_fat_k3_samples_no_trim）；
2. outline 注入 spine 全锚点行：无 spine 零变化；锚点行内容（状态标签
   pending=待兑现 / hit=已兑现 / dropped 不入行 / 未知按待兑现）、
   ≤5 封顶、与 serves_anchor 的排布（全章盘面在前、本段单锚在后）；
3. continue 画像压缩：mode ∈ {continue, stitch} 只留关键行（句长节奏 +
   对话占比目标 + 旋钮意图行），burst/outline/open 与试听（build_audition_
   prompt 旁路）保持完整画像；无文风卡零变化。

运行：python -m pytest backend/services/prompts/test_c3_mode_differential.py -v
"""

from backend.services.prompts.adaptive_prompts import (
    build_audition_prompt,
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
    render_system_blocks,
    render_system_blocks_with_usage,
)

# 完整画像（render_style_positive 全行型：五维 + 段落节奏 + 对话目标 + 旋钮意图）
STYLE_FULL = "\n".join([
    "- 句长节奏：短句为主，偶尔长句铺陈",
    "- 词汇层级：口语，少成语",
    "- 语域偏好：冷峻克制",
    "- 开头习惯：从动作切入",
    "- 结尾习惯：留白收束",
    "- 段落节奏：两长一短",
    "- 对话占比目标：35%",
    "- 句长节奏意图：偏快——以短句为主，长句只作点缀",
])
# 轻档（continue/stitch）保留集：句长节奏 + 对话目标 + 旋钮意图行
STYLE_LIGHT_LINES = [
    "- 句长节奏：短句为主，偶尔长句铺陈",
    "- 对话占比目标：35%",
    "- 句长节奏意图：偏快——以短句为主，长句只作点缀",
]

SAMPLES_K3 = ["样本一号。" + "一" * 40, "样本二号。" + "二" * 40, "样本三号。" + "三" * 40]


# ============================================================
# 1. burst 样本加量（k 2→3）
# ============================================================

class TestBurstSamplesK:
    def test_no_samples_zero_change(self):
        """零变化锁：无样本书 burst 档 prompt 与不传参逐字节一致。"""
        old_sys, old_user = build_burst_prompt(
            fragment="风更大了。", rolling_prefix="退潮在即。",
            beat_guidance="两人撤离灯塔",
        )
        for empty in ([], None):
            new_sys, new_user = build_burst_prompt(
                fragment="风更大了。", rolling_prefix="退潮在即。",
                beat_guidance="两人撤离灯塔", author_samples=empty,
            )
            assert new_sys == old_sys
            assert new_user == old_user
        assert "笔迹示范" not in old_sys

    def test_burst_mode_render_identity_without_samples(self):
        """零变化锁：无样本时 mode=burst 的块渲染与恒等路径（mode=""）逐一致。"""
        assert render_system_blocks(mode="burst") == render_system_blocks(mode="")

    def test_three_samples_full_injection_not_trimmed(self):
        """生效路径：burst 档 3 条样本满额注入（默认预算上调后不裁剪）。"""
        sys_prompt, _ = build_burst_prompt(
            fragment="风更大了。", rolling_prefix="退潮在即。",
            author_samples=SAMPLES_K3,
        )
        for i in (1, 2, 3):
            assert f"【示范 {i}】" in sys_prompt
        assert "样本三号" in sys_prompt
        # 裁剪哨兵：被裁块不带 trimmed 标记（经 usage 明细对照）
        _blocks, usages = render_system_blocks_with_usage(
            author_samples=SAMPLES_K3, mode="burst",
        )
        samples_usage = next(u for u in usages if u.key == "author_samples")
        assert samples_usage.entries_total == 3
        assert samples_usage.entries_kept == 3
        assert samples_usage.trimmed is False


# ============================================================
# 2. outline 注入 spine 全锚点行
# ============================================================

class TestOutlineSpineAnchors:
    ARGS = dict(
        outline_note="约300字：阿晚说出怀表真相",
        rolling_prefix="灯下。",
        chapter_intent="逼近真相但不揭穿。",
    )

    def test_zero_change_without_spine(self):
        """零变化锁：无 spine（None/空/省略）→ user prompt 逐字节一致。"""
        old_sys, old_user = build_outline_expand_prompt(**self.ARGS)
        for empty in (None, []):
            new_sys, new_user = build_outline_expand_prompt(
                spine_anchors=empty, **self.ARGS,
            )
            assert new_sys == old_sys
            assert new_user == old_user
        assert "本章锚点" not in old_user

    def test_anchor_line_content_with_status(self):
        """生效路径：全锚点行含状态标签（pending=待兑现 / hit=已兑现）。"""
        _sys, user = build_outline_expand_prompt(
            spine_anchors=[
                {"text": "发现假信", "status": "pending"},
                {"text": "压住不表", "status": "hit"},
            ],
            **self.ARGS,
        )
        assert "# 本章锚点：发现假信（待兑现）；压住不表（已兑现）" in user

    def test_dropped_and_invalid_entries_excluded(self):
        """dropped 不入行（作者已划掉的锚不引导 AI）；空文本/非 dict 跳过；
        未知 status 防御性按待兑现。"""
        _sys, user = build_outline_expand_prompt(
            spine_anchors=[
                {"text": "发现假信", "status": "dropped"},
                {"text": "  ", "status": "pending"},
                "不是 dict",
                {"text": "压住不表", "status": "weird-status"},
            ],
            **self.ARGS,
        )
        assert "发现假信" not in user
        assert "# 本章锚点：压住不表（待兑现）" in user

    def test_caps_at_five_entries(self):
        """≤5 封顶（与 spine 端点 SPINE_MAX_ANCHORS 同值）。"""
        anchors = [{"text": f"锚点{i}", "status": "pending"} for i in range(1, 8)]
        _sys, user = build_outline_expand_prompt(spine_anchors=anchors, **self.ARGS)
        assert "# 本章锚点：锚点1（待兑现）；锚点2（待兑现）；锚点3（待兑现）；锚点4（待兑现）；锚点5（待兑现）" in user
        assert "锚点6" not in user and "锚点7" not in user

    def test_anchor_line_precedes_serves_anchor(self):
        """排布：全章盘面（一般）在前、本段服务的单锚（具体）在后，两者并存。"""
        _sys, user = build_outline_expand_prompt(
            spine_anchors=[{"text": "发现假信", "status": "pending"}],
            serves_anchor="发现假信",
            **self.ARGS,
        )
        assert user.index("# 本章锚点：") < user.index("# 本段服务的谋篇锚点")
        assert "发现假信" in user.split("# 本段服务的谋篇锚点")[1]  # 单锚文本仍在

    def test_anchor_line_without_chapter_intent(self):
        """意图为空时锚点行独立成立（格式不依赖意图块）。"""
        _sys, user = build_outline_expand_prompt(
            outline_note="过场",
            rolling_prefix="灯下。",
            spine_anchors=[{"text": "发现假信", "status": "pending"}],
        )
        assert "# 本章锚点：发现假信（待兑现）" in user


# ============================================================
# 3. continue 画像压缩（轻档关键行）
# ============================================================

class TestContinueStyleCondense:
    def test_zero_change_without_style_card(self):
        """零变化锁：无文风卡 → 轻/重档与恒等路径逐字节一致（无块残留）。"""
        old_sys, old_user = build_continue_prompt(
            fragment="他攥紧扳手", rolling_prefix="灯下。", mode="stitch",
        )
        new_sys, new_user = build_continue_prompt(
            fragment="他攥紧扳手", rolling_prefix="灯下。",
            mode="stitch", style_positive="", author_samples=[],
        )
        assert new_sys == old_sys and new_user == old_user
        assert "作者文风画像" not in old_sys
        # 无文风卡时压缩是空操作：五档块渲染与恒等路径（mode=""）逐一致
        for mode in ("continue", "stitch", "burst", "outline", "open"):
            assert render_system_blocks(mode=mode) == render_system_blocks(mode="")

    def test_all_modes_keep_full_profile_task_parity(self):
        """知识检索平面 v3.1（2026-08-27）：轻档画像压缩退役——任务平权，
        句级两档与段落级三档拿到同一份完整画像（docs §1 公理二；
        实测证伪「句级少注入」：stitch 档 0/7 采纳恰是最瞎的档）。"""
        for mode in ("continue", "stitch"):
            sys_prompt, _ = build_continue_prompt(
                fragment="他攥紧扳手", rolling_prefix="灯下。",
                mode=mode, style_positive=STYLE_FULL,
            )
            for line in STYLE_FULL.split("\n"):
                assert line in sys_prompt, f"{mode} 应保留完整画像行: {line}"

    def test_style_block_mode_identity(self):
        """五档 style 块与恒等路径逐字节一致（档间差分已随轻档压缩退役）。"""
        base = dict(render_system_blocks(style_positive=STYLE_FULL, mode=""))
        for mode in ("continue", "stitch", "burst", "outline", "open"):
            by = dict(render_system_blocks(style_positive=STYLE_FULL, mode=mode))
            assert by["style_positive"] == base["style_positive"]

    def test_paragraph_modes_keep_full_profile(self):
        """burst/outline/open 保持完整画像（段落级生成不压缩）。"""
        cases = [
            (build_burst_prompt, dict(fragment="风更大了。", rolling_prefix="退潮。")),
            (build_outline_expand_prompt, dict(outline_note="约300字：对峙", rolling_prefix="灯下。")),
            (build_opening_prompt, dict(outline_text="第一章：暴风雨夜。")),
        ]
        for builder, extra in cases:
            sys_prompt, _ = builder(style_positive=STYLE_FULL, **extra)
            for line in STYLE_FULL.split("\n"):
                assert line in sys_prompt, f"{builder.__name__} 应保留完整画像行: {line}"

    def test_audition_keeps_full_profile(self):
        """试听（旁路调用方，不走模式档）保持完整画像——试衣间展示配置全貌。"""
        sys_prompt, _ = build_audition_prompt("测试段。", style_positive=STYLE_FULL)
        for line in STYLE_FULL.split("\n"):
            assert line in sys_prompt

    def test_preview_usage_full_entries_no_condense(self):
        """预算器同源：BlockUsage 条目口径=完整画像行数（压缩退役后无档间差分）。"""
        _blocks, usages = render_system_blocks_with_usage(
            style_positive=STYLE_FULL, mode="continue",
        )
        style_usage = next(u for u in usages if u.key == "style_positive")
        assert style_usage.entries_total == len(STYLE_FULL.split("\n"))
        assert style_usage.entries_kept == len(STYLE_FULL.split("\n"))
        assert style_usage.trimmed is False  # allocate 未触发

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
文风执行层注入单测（S2，纯算法——不连 LLM/DB）。

覆盖（docs/style-module-redesign.md §4 E1/E2/E5 + §9 风险对策）：
- 零变化契约：无文风卡/无样本时，四个 stitch prompt 与旧版**逐字节一致**
  （无风格块残留）——这是"无样本的书行为不变"的回归护栏
- 画像渲染器：render_style_positive 五维标签/段落节奏/对话目标/空卡空串
- 范例块与画像块：注入后出现在 system prompt 且语义边界清楚
- 选区改写：style_context 空 → user prompt 与旧版一致；非空 → 文风约束块注入
- 样本截断：句界优先，找不到句界回退原窗口
"""

from backend.services.context.settings_bundle import render_style_positive
from backend.services.llm.selection_rewrite import build_selection_rewrite_user_prompt
from backend.services.prompts.adaptive_prompts import (
    build_audition_prompt,
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
    build_outline_expand_prompt,
)
from backend.services.style.retrieval import truncate_sample


# ============================================================
# 零变化契约（最重要的回归护栏）
# ============================================================

class TestZeroChangeContract:
    """无文风卡/无样本 → prompt 与旧版逐字节一致。"""

    COMMON = dict(
        proper_nouns=["林尘", "阿晚"],
        canon_context="[public]\n- 林尘：灯塔守夜人",
        memory_echoes=["第三章：林尘捡到一枚锈蚀的怀表。"],
    )

    def test_continue_prompt_zero_change(self):
        old_sys, old_user = build_continue_prompt(
            fragment="他攥紧扳手", rolling_prefix="夜里的礁石滩只有风声。", **self.COMMON,
        )
        new_sys, new_user = build_continue_prompt(
            fragment="他攥紧扳手", rolling_prefix="夜里的礁石滩只有风声。",
            style_positive="", author_samples=[], **self.COMMON,
        )
        assert new_sys == old_sys
        assert new_user == old_user
        assert "文风画像" not in new_sys and "笔迹示范" not in new_sys

    def test_burst_prompt_zero_change(self):
        old_sys, _ = build_burst_prompt(fragment="风更大了。", rolling_prefix="退潮在即。", beat_guidance="两人撤离灯塔", **self.COMMON)
        new_sys, _ = build_burst_prompt(
            fragment="风更大了。", rolling_prefix="退潮在即。", beat_guidance="两人撤离灯塔",
            style_positive="", author_samples=None, **self.COMMON,
        )
        assert new_sys == old_sys

    def test_outline_expand_prompt_zero_change(self):
        old_sys, _ = build_outline_expand_prompt(outline_note="约300字：阿晚说出怀表真相", rolling_prefix="灯下。", **self.COMMON)
        new_sys, _ = build_outline_expand_prompt(
            outline_note="约300字：阿晚说出怀表真相", rolling_prefix="灯下。",
            style_positive="", author_samples=[], **self.COMMON,
        )
        assert new_sys == old_sys

    def test_opening_prompt_zero_change(self):
        old_sys, _ = build_opening_prompt(outline_text="第一章：暴风雨夜，灯塔失电。", previous_summary="", **self.COMMON)
        new_sys, _ = build_opening_prompt(
            outline_text="第一章：暴风雨夜，灯塔失电。", previous_summary="",
            style_positive="", author_samples=[], **self.COMMON,
        )
        assert new_sys == old_sys


# ============================================================
# 注入生效
# ============================================================

class TestInjection:
    STYLE = "- 句长节奏：短句与长句交替，平均 15 字\n- 语域偏好：冷峻克制"
    SAMPLES = ["他走到窗前。外面在下雨，雨点砸在铁皮檐上，一声一声，像谁在数着什么。"]

    def test_continue_prompt_with_style_and_samples(self):
        sys_prompt, _ = build_continue_prompt(
            fragment="他攥紧扳手", rolling_prefix="夜里的礁石滩只有风声。",
            proper_nouns=["林尘", "阿晚"],
            style_positive=self.STYLE, author_samples=self.SAMPLES,
        )
        assert "作者文风画像" in sys_prompt
        assert "句长节奏：短句与长句交替" in sys_prompt
        assert "作者笔迹示范" in sys_prompt
        assert "【示范 1】" in sys_prompt
        assert "像同一个人写的" in sys_prompt
        # 风格块在基座之后、专名块之前（顺序稳定）
        # 知识检索平面 v3.1（2026-08-27）：注入序=事实层前于文风层——专名块
        # （此处无实体数据走兜底）先于画像块（docs/knowledge-retrieval-plane.md §6）
        assert sys_prompt.index("反 AI 腔指令") < sys_prompt.index("在场实体专名") < sys_prompt.index("作者文风画像")

    def test_samples_block_empty_strings_filtered(self):
        sys_prompt, _ = build_burst_prompt(
            fragment="风更大了。", rolling_prefix="退潮在即。",
            author_samples=["", "   "],
        )
        assert "笔迹示范" not in sys_prompt

    def test_render_style_positive_full_card(self):
        class FakeCard:
            positive_profile = {
                "sentence_rhythm": "短促，常 2-3 句一段",
                "vocabulary": "口语化，少成语",
                "register": "冷峻",
                "opening_habit": "",
                "ending_habit": "留白收束",
            }
            paragraph_rhythm = "段落短促"
            dialogue_ratio_target = 0.35
        text = render_style_positive(FakeCard())
        lines = text.splitlines()
        assert lines[0] == "- 句长节奏：短促，常 2-3 句一段"
        assert "- 开头习惯" not in text          # 空值字段不渲染
        assert "- 段落节奏：段落短促" in text
        assert "- 对话占比目标：35%" in text

    def test_render_style_positive_empty(self):
        assert render_style_positive(None) == ""
        class EmptyCard:
            positive_profile = {}
            paragraph_rhythm = None
            dialogue_ratio_target = None
        assert render_style_positive(EmptyCard()) == ""


# ============================================================
# 试听 prompt（S3 试衣间：与 stitch 同一套注入路径）
# ============================================================

class TestAuditionPrompt:
    TEXT = "他不禁感到一阵愤怒涌上心头，眼中闪过一丝寒意。"

    def test_baseline_has_no_style_blocks(self):
        """A/B 基线（无画像无样本）与 stitch 续写同构：无文风块残留。"""
        sys_prompt, user_prompt = build_audition_prompt(self.TEXT)
        assert "作者文风画像" not in sys_prompt
        assert "作者笔迹示范" not in sys_prompt
        # 基座与改写任务都在
        assert "反 AI 腔指令" in sys_prompt
        assert "改写成这位作者的笔迹" in user_prompt
        assert self.TEXT in user_prompt

    def test_styled_version_injects_blocks(self):
        sys_prompt, _ = build_audition_prompt(
            self.TEXT,
            style_positive="- 句长节奏：短句为主",
            author_samples=["他走到窗前。雨在下。"],
        )
        assert "作者文风画像" in sys_prompt
        assert "作者笔迹示范" in sys_prompt

    def test_same_blocks_as_continue_prompt(self):
        """试听与写作台共用同一套块——「所见即所得」的机制保证。

        C3（docs/foundation-hardening.md §5.3）后 continue/stitch 档画像压缩
        为关键行，与试听的完整画像**有意**不同（试听展示配置的画像全貌，
        顺句档只注入关键行）——因此：①示范块与 continue 仍逐字一致；
        ②完整画像块的对拍改挂 burst 档（段落级模式不压缩，见下测）。
        """
        style = "- 语域偏好：冷峻"
        samples = ["样本一。"]
        cont_sys, _ = build_continue_prompt(fragment="他", rolling_prefix="", style_positive=style, author_samples=samples)
        audi_sys, _ = build_audition_prompt(self.TEXT, style_positive=style, author_samples=samples)
        # 示范块两侧逐字一致（继续生效）
        marker = "# 作者笔迹示范"
        c_start = cont_sys.index(marker)
        a_start = audi_sys.index(marker)
        c_end = cont_sys.index("\n\n#", c_start + 2) if "\n\n#" in cont_sys[c_start + 2:] else len(cont_sys)
        a_end = audi_sys.index("\n\n#", a_start + 2) if "\n\n#" in audi_sys[a_start + 2:] else len(audi_sys)
        assert cont_sys[c_start:c_end] == audi_sys[a_start:a_end]

    def test_same_style_blocks_as_burst_prompt(self):
        """试听的完整画像块与 burst 连写（不压缩档）逐字一致。"""
        style = "- 语域偏好：冷峻"
        samples = ["样本一。"]
        burst_sys, _ = build_burst_prompt(fragment="他", rolling_prefix="", style_positive=style, author_samples=samples)
        audi_sys, _ = build_audition_prompt(self.TEXT, style_positive=style, author_samples=samples)
        for marker in ("# 作者文风画像", "# 作者笔迹示范"):
            b_start = burst_sys.index(marker)
            a_start = audi_sys.index(marker)
            b_end = burst_sys.index("\n\n#", b_start + 2) if "\n\n#" in burst_sys[b_start + 2:] else len(burst_sys)
            a_end = audi_sys.index("\n\n#", a_start + 2) if "\n\n#" in audi_sys[a_start + 2:] else len(audi_sys)
            assert burst_sys[b_start:b_end] == audi_sys[a_start:a_end], f"块不一致: {marker}"


# ============================================================
# 意图旋钮（S4）：档位渲染 + 自动档零注入
# ============================================================

class TestStyleKnobs:
    def test_render_knob_lines_manual_tiers(self):
        from backend.services.style.knobs import render_knob_lines

        lines = render_knob_lines({"rhythm": 1, "register": 5})
        assert len(lines) == 2
        assert lines[0].startswith("句长节奏意图：极快——")
        assert lines[1].startswith("文白意图：极文——")

    def test_render_knob_lines_auto_and_invalid(self):
        from backend.services.style.knobs import render_knob_lines

        # 空/全自动 → 零行（prompt 零变化）
        assert render_knob_lines({}) == []
        assert render_knob_lines(None) == []
        # 非法档（越界/非数字/未知键）静默跳过
        assert render_knob_lines({"rhythm": 9, "register": "快", "unknown": 3}) == []

    def test_render_style_positive_includes_knobs(self):
        class CardWithKnobs:
            positive_profile = {"register": "冷峻"}
            paragraph_rhythm = None
            dialogue_ratio_target = None
            style_knobs = {"density": 1, "warmth": 4}

        text = render_style_positive(CardWithKnobs())
        assert "- 语域偏好：冷峻" in text
        assert "- 浓淡意图：极淡——" in text
        assert "- 冷热意图：偏热——" in text

    def test_render_style_positive_without_knobs_zero_change(self):
        """无旋钮字段（旧卡）→ 渲染与 S2 行为一致，无意图行。"""

        class OldCard:
            positive_profile = {"register": "冷峻"}
            paragraph_rhythm = None
            dialogue_ratio_target = None
            style_knobs = None  # 列迁移前的旧卡（属性缺省）

        text = render_style_positive(OldCard())
        assert "意图：" not in text


# ============================================================
# 声纹通路（S4）：实体「说话风格」→ 生成上下文（world_bridge 既有链路锁定）
# ============================================================

class TestVoicePath:
    def test_speech_style_flows_into_static_prompt(self):
        """声纹=实体档案 speech_style 字段——它必须出现在 static_prompt（生成上下文）里。

        这是「笔迹 vs 声纹」切分的供给侧保证：角色对话腔调走实体档案，
        叙述文风走文风页，两条通路不混。
        """
        from backend.services.context.world_bridge import static_prompt_from_world_entity

        class FakeEntity:
            props = {
                "personality": "谨慎",
                "speech_style": "老朽常带叹词，句短，爱用古语",
            }

        text = static_prompt_from_world_entity(FakeEntity())
        assert "语言习惯：老朽常带叹词，句短，爱用古语" in text
        assert "性格：谨慎" in text


# ============================================================
# 选区改写（E5b）
# ============================================================

class TestSelectionRewriteStyle:
    ARGS = dict(
        selected_text="他不禁感到一阵愤怒涌上心头。",
        context_before="灯灭了。",
        context_after="门外传来脚步声。",
        outline="第一章",
        user_instruction="",
    )

    def test_zero_change_without_style(self):
        old = build_selection_rewrite_user_prompt(**self.ARGS)
        new = build_selection_rewrite_user_prompt(style_context="", **self.ARGS)
        assert new == old
        assert "文风约束" not in new

    def test_style_block_injected(self):
        prompt = build_selection_rewrite_user_prompt(
            style_context="- 句长节奏：短句为主\n避免用词：不禁、涌上心头", **self.ARGS,
        )
        assert "【文风约束（改写后的文字要像同一个人写的）】" in prompt
        assert "避免用词：不禁、涌上心头" in prompt
        # 约束块在后文之后、用户附加指令之前
        assert prompt.index("【后文】") < prompt.index("【文风约束") < prompt.index("【用户附加指令】")


# ============================================================
# 样本截断（retrieval 纯函数部分）
# ============================================================

class TestTruncateSample:
    def test_short_sample_untouched(self):
        assert truncate_sample("短样本。", 1200) == "短样本。"

    def test_truncate_at_sentence_boundary(self):
        text = "句一号。句二号。" + "长" * 50 + "。句尾。"
        result = truncate_sample(text, 10)
        assert result.endswith("。")
        assert len(result) <= 10

    def test_no_sentence_mark_falls_back_to_window(self):
        text = "无标点的连续文本" * 20
        result = truncate_sample(text, 30)
        assert result == text[:30]

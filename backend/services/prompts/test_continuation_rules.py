# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 续写三律与禁词分层单测
"""
2026-08-27 文学诊断轮的 prompt 契约锁。

背景：幽灵草稿实测三类结构性 AI 腔（回说式填充/断点徘徊/外部打断收尾），
词表打不中（好句坏句共享词汇），落指令级约束（正面任务式措辞）。
导师诊断结论：中档模型对负面禁令堆叠会退化出新套路与判断稀释，
故约束少而狠——基座只换血「感官描写指导」→「细节功能」，句级模式加三律。

锁定：
- continue 注入三律（新东西/断点/收尾）；stitch 注入新东西+收尾两律
  （断点契约已有专文，不重复注入断点律）
- burst/open 注入段落版收尾律
- 基座旧「感官描写指导」节已被「细节功能」替换
- prompt 侧禁词扩展进禁词表，且 DEFAULT_BAN_LIST 未被污染——sanitizer 对
  代码词表做确定性子串删除，「回味」「顿了顿」进代码层会打穿句子（安全边界）
"""
from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
from backend.services.prompts.adaptive_prompts import (
    _base_system,
    build_burst_prompt,
    build_continue_prompt,
    build_opening_prompt,
)


class TestSentenceModeRules:
    def test_continue_injects_three_rules(self):
        """continue：三律齐备（回说禁令 + 断点即走 + 收尾落点）。"""
        _, user = build_continue_prompt(
            fragment="在这个世道，", rolling_prefix="灯下。", mode="continue",
        )
        assert "只写新东西" in user
        assert "不「回味/想起/还在想」" in user
        assert "接下来发生什么" in user
        assert "补完立即向前走" in user
        assert "停在人物自己正在做的事上" in user
        assert "突然响起的声响或喊声" in user

    def test_stitch_injects_two_rules_keeps_breakpoint_contract(self):
        """stitch：新东西+收尾两律注入；断点契约保持专文，不重复注入断点律。"""
        _, user = build_continue_prompt(
            fragment="他攥紧扳手", rolling_prefix="灯下。",
            mode="stitch", picked_parts=["咬平齿的废管钳"],
        )
        assert "只写新东西" in user
        assert "停在人物自己正在做的事上" in user
        # 既有追加式断点契约原话仍在（2026-08-26 反转契约，勿回退）
        assert "从断点最后一个词的后面直接续" in user
        # 断点律未注入（stitch 已有断点契约，双写徒增禁令）
        assert "补完立即向前走" not in user


class TestParagraphModeRules:
    def test_burst_injects_ending_rule(self):
        _, user = build_burst_prompt(
            fragment="风更大了。", rolling_prefix="退潮在即。", beat_guidance="两人撤离灯塔",
        )
        assert "停在人物自己正在做的事上" in user
        assert "突然响起的声响或喊声" in user

    def test_opening_injects_ending_rule(self):
        _, user = build_opening_prompt(outline_text="林尘在工地第一次顶撞工头")
        assert "停在人物自己正在做的事上" in user
        # 点火原有的 bullets 与空行分隔指令仍在
        assert "只写\"引子\"" in user
        assert "段落之间用一个空行分隔" in user


class TestBaseSystemDetailRule:
    def test_sensory_section_replaced_by_detail_function(self):
        """基座换血：旧「感官描写指导」节缺席，「细节功能」尺子在位。"""
        sys_prompt = _base_system()
        assert "感官描写指导" not in sys_prompt
        assert "细节功能" in sys_prompt
        assert "静态贴图" in sys_prompt
        assert "限额不是配额" in sys_prompt

    def test_core_contract_lines_survive(self):
        """基座既有契约（微操/套路比喻/心理限制）未被动摇。"""
        sys_prompt = _base_system()
        assert "禁病态微操" in sys_prompt
        assert "禁套路比喻" in sys_prompt
        assert "禁止直接心理升华" in sys_prompt


class TestPromptOnlyBanLayering:
    def test_extended_words_in_prompt_ban_list(self):
        """扩展禁词进 prompt 禁词表（与静态词表同段呈现）。"""
        sys_prompt = _base_system()
        for w in ("一抹", "氤氲", "指腹", "眸子", "眸光", "回味", "顿了顿"):
            assert w in sys_prompt, f"prompt 禁词表缺 {w}"

    def test_code_ban_list_not_polluted(self):
        """安全边界：扩展词不进 DEFAULT_BAN_LIST——sanitizer 子串删除
        会把「回味」从句中抠掉打穿句子，词表必须分层。"""
        for w in ("一抹", "氤氲", "指腹", "眸子", "眸光", "回味", "顿了顿"):
            assert w not in DEFAULT_BAN_LIST.banned_words, f"{w} 混入代码删除层"


class TestAntiPseudoSensoryBan:
    """白描契约与假感官封杀令（2026-09-09 实测事故紧急植入）：

    - stitch/continue 两模式注入（system 尾部高服从位）；
    - burst/open/outline 不受染（各有专职，白描硬约束只圈句级续写）；
    - 用户逐字拍板的封杀令原样在场（三类禁令 + 白描准则两组标题齐全）。
    """

    def _continue(self, mode: str = "stitch"):
        sys_p, _ = build_continue_prompt(
            fragment="他接过扳手。", rolling_prefix="工棚里很静。", mode=mode,
        )
        return sys_p

    def test_stitch_and_continue_carry_the_ban(self):
        for mode in ("stitch", "continue"):
            sys_p = self._continue(mode)
            assert "Anti-Pseudo-Sensory Ban" in sys_p, mode
            assert "北方硬朗白描" in sys_p, mode
            # 三类禁令的病灶语料原样在场（实测事故词）
            for phrase in ("掌心发热/发烫", "震动顺着XX传进掌心", "眼里亮了一下又暗下去",
                           "倒吸一口凉气", "喉结滚动", "嘴角勾起/扯动", "接错的线头"):
                assert phrase in sys_p, f"{mode} 缺禁令语料「{phrase}」"

    def test_burst_opening_outline_untouched(self):
        from backend.services.prompts.adaptive_prompts import build_outline_expand_prompt
        sys_b, _ = build_burst_prompt(fragment="他接过扳手。", rolling_prefix="前文。")
        sys_o, _ = build_opening_prompt(outline_text="开头一两拍")
        sys_e, _ = build_outline_expand_prompt(outline_note="速记", rolling_prefix="前文。")
        for sys_p, name in ((sys_b, "burst"), (sys_o, "open"), (sys_e, "outline")):
            assert "Anti-Pseudo-Sensory Ban" not in sys_p, name
            assert "北方硬朗白描" not in sys_p, name

    def test_ban_sits_at_system_tail(self):
        """追加在 system 尾部（首尾高服从位）——文风块之后。"""
        sys_p, _ = build_continue_prompt(
            fragment="他接过扳手。", rolling_prefix="工棚里很静。", mode="stitch",
            style_positive="句短，动词多",
        )
        # 尾部=白描块收尾（2026-09-11 追加注水禁令后，块尾从「靠拢。」
        # 变为「宁短勿水。」——注入位不变：仍是 system 末位分节）
        assert sys_p.rstrip().endswith("宁短勿水。")
        assert "严禁逗号串联注水" in sys_p

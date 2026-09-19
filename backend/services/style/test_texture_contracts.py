# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
文章质感契约注册表对拍（2026-09 白描封杀令收编批 + 靶场开关批）。

锁定四件事：
1. 契约正文逐字在场——用户逐字拍板文案（含 4 组标题与病灶语料）收编时
   零改写；全启渲染 SHA256 锁定（5f87fd9e…438c）防 span 漂移；
2. mode 门控 + 按书覆盖语义（缺键/空 body=系统默认，未知键忽略）；
3. 规矩开关：单关只摘该规矩的原文 span（其余逐字不动），绝对禁止族双关
   全关时段头一并消失（不留空头）；
4. 执法词表策展口径：全 blocker、无替代词、正则可编译、「倒吸一口凉气」
   不重复收录（系统陈词层已覆盖）。
"""
import hashlib
import re

from backend.services.style.texture_contracts import (
    CONTRACTS,
    ENFORCEMENT_ENTRY_SPECS,
    RULE_NO_COMMA_PAD,
    RULE_NO_FABRICATION,
    RULE_PLAIN_STYLE,
    RULE_PSEUDO_SENSORY,
    _compose_body,
    normalize_texture_overrides,
    render_texture_contract,
    resolve_contract_body,
    texture_enforcement_entries,
)

# 全启=拍板原文的 SHA256（迁移自 git HEAD adaptive_prompts 的逐字比对锚）
_CANONICAL_SHA256 = "5f87fd9e45cca9276866a839f391885ae382f72d43e087aba4d9db3beed8438c"


class TestRuleSwitches:
    """规矩开关（靶场 UI 的四checkbox）：span 级摘条，逐字不动。"""

    def test_all_enabled_byte_identical_sha(self):
        body = _compose_body()
        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == _CANONICAL_SHA256
        assert body == CONTRACTS["anti_pseudo_sensory"].body

    def test_disable_single_rule_removes_only_its_span(self):
        body = _compose_body(frozenset({"no_comma_pad"}))
        assert "严禁逗号串联注水" not in body
        # 其余三组逐字在场
        assert "绝对禁止" in body
        assert "北方硬朗白描" in body
        assert "成了！" in body
        assert body.endswith("靠拢。\n")

    def test_disable_plain_style_keeps_others_with_separators(self):
        body = _compose_body(frozenset({"plain_style"}))
        assert "北方硬朗白描" not in body
        assert "绝对禁止" in body
        assert "严禁逗号串联注水" in body
        # 段间空行不塌：节与节之间仍有 \n\n 间隔
        assert "\n\n【严禁逗号串联注水】" in body

    def test_disable_both_s1_rules_drops_section_head(self):
        body = _compose_body(frozenset({"pseudo_sensory", "no_fabrication"}))
        assert "绝对禁止" not in body  # 族全关=段头一并消失，不留空头
        assert "北方硬朗白描" in body

    def test_disable_s1_head_kept_when_one_s1_rule_alive(self):
        body = _compose_body(frozenset({"no_fabrication"}))
        assert "绝对禁止" in body
        assert "严禁擅自脑补事故" not in body
        body2 = _compose_body(frozenset({"pseudo_sensory"}))
        assert "绝对禁止" in body2
        assert "严禁擅自脑补事故" in body2

    def test_resolve_disabled_rules_via_overrides(self):
        ov = {"anti_pseudo_sensory": {"disabled_rules": ["plain_style", "unknown_key"]}}
        body = resolve_contract_body("anti_pseudo_sensory", ov)
        assert "北方硬朗白描" not in body
        assert "绝对禁止" in body  # 未知键忽略

    def test_body_override_beats_disabled_rules(self):
        ov = {"anti_pseudo_sensory": {"body": "整文覆盖", "disabled_rules": ["plain_style"]}}
        assert resolve_contract_body("anti_pseudo_sensory", ov) == "整文覆盖"

    def test_empty_disabled_rules_means_default(self):
        ov = {"anti_pseudo_sensory": {"disabled_rules": []}}
        assert resolve_contract_body("anti_pseudo_sensory", ov) == CONTRACTS["anti_pseudo_sensory"].body


class TestContractBodyVerbatim:
    """用户逐字拍板文案逐字在位（收编红线：只迁户籍不改文案）。"""

    def test_key_sections_present(self):
        body = CONTRACTS["anti_pseudo_sensory"].body
        # 四组标题
        for heading in (
            "【绝对禁止：假感官堆砌与生理微知觉（Anti-Pseudo-Sensory Ban）】",
            "【语言风格准则：北方硬朗白描（Narrative Economy）】",
            "【严禁逗号串联注水】",
        ):
            assert heading in body, f"缺标题：{heading}"
        # 实测事故病灶语料原样在场
        for phrase in (
            "掌心发热/发烫",
            "震动顺着XX传进掌心",
            "眼里亮了一下又暗下去",
            "倒吸一口凉气",
            "喉结滚动",
            "呼吸一滞/一沉",
            "下意识地藏/缩",
            "嘴角勾起/扯动",
            "接错的线头",
            "宁短勿水。",
        ):
            assert phrase in body, f"缺语料：{phrase}"

    def test_header_holds_priority_framing(self):
        header = CONTRACTS["anti_pseudo_sensory"].header
        assert header.startswith("\n\n# ")
        assert "最高优先级" in header


class TestRenderGating:
    """mode 门控：stitch/continue 在场，其余空串（零变化契约的空串块）。"""

    def test_stitch_and_continue_carry_block(self):
        for mode in ("stitch", "continue"):
            block = render_texture_contract("anti_pseudo_sensory", mode)
            assert block.startswith("\n\n# 白描契约与假感官封杀令（最高优先级）\n")
            assert "Anti-Pseudo-Sensory Ban" in block

    def test_other_modes_empty(self):
        for mode in ("burst", "open", "outline", ""):
            assert render_texture_contract("anti_pseudo_sensory", mode) == "", mode

    def test_unknown_key_empty(self):
        assert render_texture_contract("no_such_contract", "stitch") == ""


class TestBookOverrides:
    """按书覆盖：非空 body 替换正文；空/缺键回系统默认；未知键忽略。"""

    def test_custom_body_replaces(self):
        block = render_texture_contract(
            "anti_pseudo_sensory", "stitch",
            {"anti_pseudo_sensory": {"body": "自定义规矩正文"}},
        )
        assert block.endswith("自定义规矩正文")
        assert "最高优先级" in block  # 块头恒由系统持有

    def test_blank_body_falls_back(self):
        for blank in ("", "   ", None):
            block = render_texture_contract(
                "anti_pseudo_sensory", "stitch",
                {"anti_pseudo_sensory": {"body": blank}},
            )
            assert "Anti-Pseudo-Sensory Ban" in block

    def test_missing_key_and_malformed_overrides(self):
        default = render_texture_contract("anti_pseudo_sensory", "stitch")
        assert render_texture_contract("anti_pseudo_sensory", "stitch", {}) == default
        assert render_texture_contract("anti_pseudo_sensory", "stitch", None) == default
        # 形态脏数据不炸：非 dict 覆盖 / 非 dict overrides
        assert render_texture_contract(
            "anti_pseudo_sensory", "stitch", {"anti_pseudo_sensory": "oops"},
        ) == default
        assert render_texture_contract("anti_pseudo_sensory", "stitch", ["oops"]) == default

    def test_resolve_body_unknown_key(self):
        assert resolve_contract_body("no_such_key", {"no_such_key": {"body": "x"}}) == ""


class TestEnforcementEntries:
    """执法词表策展口径（洗层/上屏快检/完稿审计三处旁路合并的供数面）。"""

    def test_all_blocker_no_alternative(self):
        entries = texture_enforcement_entries()
        assert len(entries) == len(ENFORCEMENT_ENTRY_SPECS)
        for e in entries:
            assert e.severity == "blocker"
            assert e.alternative is None
            assert e.source == "texture_contract"

    def test_disease_words_present(self):
        patterns = {e.pattern for e in texture_enforcement_entries()}
        for w in ("喉结滚动", "嘴角勾起", "掌心发热", "眼里亮了一下又暗下去"):
            assert w in patterns

    def test_no_duplicate_of_system_cliche(self):
        """倒吸一口凉气已是 SystemCliche blocker 种子——不重复收录。"""
        patterns = {e.pattern for e in texture_enforcement_entries()}
        assert "倒吸一口凉气" not in patterns
        assert "不禁倒吸一口凉气" not in patterns

    def test_regex_entries_compile(self):
        regex_specs = [p for p, is_re in ENFORCEMENT_ENTRY_SPECS if is_re]
        assert regex_specs, "占位病灶（震动顺着XX…）必须以正则收录"
        for p in regex_specs:
            re.compile(p)

    def test_regex_matches_intended_shapes(self):
        from backend.services.style.prohibitions import ProhibitionSet
        ps = ProhibitionSet(tuple(texture_enforcement_entries()))
        text = "震动顺着桌腿传进掌心，他下意识地缩了缩。"
        hits = [e.pattern for _m, e in ps.finditer(text)]
        assert "震动顺着.{1,8}传进掌心" in hits
        assert "下意识地(藏|缩)" in hits

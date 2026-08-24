# -*- coding: utf-8 -*-
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
禁忌面归一（任务包 A）单测——services/style/prohibitions.py。

纯算法 / 假数据（不连真实 LLM / DB）：系统层经 monkeypatch 控制
cliche_provider.get_active_cliches；db=None 时 provider 本身回落种子，
因此所有需要「受控系统层」的用例都显式 mock。

对拍口径：
- finditer 与旧 StyleClicheValidator 三层合并的 (span, 命中文本) 集合相等
  （旧逻辑内联复制作参照）
- 与 settings_bundle._merge_banned_words 的**集合**相等（仅
  blacklist + negative_list + 静态表、无系统陈词场景；顺序不要求——
  新顺序 system → negative → blacklist → static 是有意变化）
"""

import asyncio
import re

import pytest

from backend.services.nlg.anti_ai_rules import DEFAULT_BAN_LIST
from backend.services.style import cliche_provider
from backend.services.style.prohibitions import (
    EMPTY_PROHIBITION_SET,
    ProhibitionEntry,
    ProhibitionSet,
    load_prohibition_set,
)


# ============================================================
# fixtures / 工具
# ============================================================

class _FakeBook:
    def __init__(self, style_blacklist=None, style_cliche_exemptions=None):
        self.style_blacklist = style_blacklist
        self.style_cliche_exemptions = style_cliche_exemptions


class _FakeCard:
    def __init__(self, negative_list=None):
        self.negative_list = negative_list


def _mock_system(monkeypatch, items):
    async def _fake(db=None, use_cache=True, **kwargs):
        return items
    monkeypatch.setattr(cliche_provider, "get_active_cliches", _fake)


def _mock_system_empty(monkeypatch):
    _mock_system(monkeypatch, [])


def _load(**kwargs):
    return asyncio.run(load_prohibition_set(db=None, **kwargs))


def _old_validator_layers(system_items, style_blacklist, style_negative_list):
    """旧 StyleClicheValidator._ensure_loaded 三层合并 + 编译（内联参照实现）。

    逐行对齐改造前代码（含 str 黑名单拆分、dict word/phrase 兼容、
    re.escape / 原样编译 / re.error 跳过），供 finditer 对拍。
    """
    cliches = []
    for item in system_items:
        cliches.append((
            item.get("pattern", ""),
            bool(item.get("is_regex", False)),
            item.get("alternative"),
            item.get("severity", "warning"),
        ))
    if style_blacklist:
        items = []
        if isinstance(style_blacklist, str):
            items = [c.strip() for c in re.split(r'[,，\n]', style_blacklist) if c.strip()]
        elif isinstance(style_blacklist, list):
            items = style_blacklist
        for item in items:
            if isinstance(item, str):
                cliches.append((item, False, None, "warning"))
            elif isinstance(item, dict):
                word = item.get("word") or item.get("phrase") or ""
                if word:
                    cliches.append((word, False, item.get("alternative"), item.get("severity", "warning")))
    if style_negative_list and isinstance(style_negative_list, list):
        for item in style_negative_list:
            if isinstance(item, dict):
                word = item.get("word") or item.get("phrase") or ""
                if word:
                    cliches.append((word, False, item.get("alternative"), "warning"))
    compiled = []
    for pattern_str, is_regex, alt, sev in cliches:
        if not pattern_str:
            continue
        try:
            actual = pattern_str if is_regex else re.escape(pattern_str)
            compiled.append((re.compile(actual), alt or "", sev or "warning"))
        except re.error:
            continue
    return compiled


# ============================================================
# 四源合并顺序 / 优先级去重
# ============================================================

class TestMergeOrderAndDedup:
    def test_layer_priority_first_wins(self, monkeypatch):
        """同 pattern 出现在多源 → 保留先层条目及 alternative/severity/source。"""
        _mock_system(monkeypatch, [
            {"pattern": "共词", "is_regex": False,
             "alternative": "系统替", "severity": "blocker"},
        ])
        ps = _load(
            book=_FakeBook(style_blacklist=["共词", "独黑"]),
            style_card=_FakeCard(negative_list=[
                {"word": "共词", "alternative": "负面替"}, {"word": "独负面"},
            ]),
        )
        patterns = [e.pattern for e in ps.entries]
        assert patterns.count("共词") == 1  # 去重，先到先得
        first = ps.entries[0]
        assert first.source == "system_cliche"
        assert first.alternative == "系统替"
        assert first.severity == "blocker"
        assert [e.pattern for e in ps.entries[:3]] == ["共词", "独负面", "独黑"]
        assert ps.entries[1].source == "negative_list"
        assert ps.entries[2].source == "book_blacklist"

    def test_layer_order_system_negative_blacklist_static(self, monkeypatch):
        _mock_system(monkeypatch, [{"pattern": "系词", "is_regex": False}])
        ps = _load(
            book=_FakeBook(style_blacklist=["黑词"]),
            style_card=_FakeCard(negative_list=[{"word": "负词"}]),
        )
        sources = [e.source for e in ps.entries]
        assert sources[:3] == ["system_cliche", "negative_list", "book_blacklist"]
        assert set(sources[3:]) == {"anti_ai_static"}


# ============================================================
# negative_list 契约
# ============================================================

class TestNegativeList:
    def test_word_phrase_keys_and_empty_skip(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load(style_card=_FakeCard(negative_list=[
            {"word": "甲词"},
            {"phrase": "乙词"},
            {"word": ""},                      # 空串跳过
            {"word": "丙词", "alternative": "替代"},
            "裸字符串",                         # 仅 dict 条目，str 忽略
            {"alternative": "无词"},            # 无 word/phrase 跳过
        ]))
        got = [(e.pattern, e.alternative, e.severity, e.source) for e in ps.entries
               if e.source == "negative_list"]
        assert got == [
            ("甲词", None, "warning", "negative_list"),
            ("乙词", None, "warning", "negative_list"),
            ("丙词", "替代", "warning", "negative_list"),
        ]


# ============================================================
# style_blacklist 三形态
# ============================================================

class TestStyleBlacklistForms:
    def test_str_delimited(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load(book=_FakeBook(style_blacklist="旧词,新词　中文逗号后\n尾词，  空  "))
        # 全角逗号 / 中文顿号空格条目被 strip 后为空则剔除
        got = [e.pattern for e in ps.entries if e.source == "book_blacklist"]
        # "新词　中文逗号后"（全角空格不分隔，与旧 re.split 契约一致）
        assert "旧词" in got and "尾词" in got

    def test_str_split_contract(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load(book=_FakeBook(style_blacklist="a，b,c\nd"))
        got = [e.pattern for e in ps.entries if e.source == "book_blacklist"]
        assert got == ["a", "b", "c", "d"]

    def test_list_of_str(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load(book=_FakeBook(style_blacklist=["词一", "词二"]))
        got = [(e.pattern, e.severity, e.source) for e in ps.entries
               if e.source == "book_blacklist"]
        assert got == [("词一", "warning", "book_blacklist"),
                       ("词二", "warning", "book_blacklist")]

    def test_list_of_dict(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load(book=_FakeBook(style_blacklist=[
            {"word": "字词", "alternative": "替", "severity": "blocker"},
            {"phrase": "短语词"},
        ]))
        got = [(e.pattern, e.alternative, e.severity) for e in ps.entries
               if e.source == "book_blacklist"]
        assert got == [("字词", "替", "blocker"), ("短语词", None, "warning")]


# ============================================================
# 豁免：仅作用于系统层
# ============================================================

class TestExemptions:
    def test_exemption_only_removes_system_layer(self, monkeypatch):
        _mock_system(monkeypatch, [{"pattern": "系统词", "is_regex": False}])
        ps = _load(
            book=_FakeBook(
                style_blacklist=["系统词"],
                style_cliche_exemptions=["系统词"],
            ),
            style_card=_FakeCard(negative_list=[{"word": "系统词"}]),
        )
        # 豁免剔除系统层后，同 pattern 的下层条目仍可进入（豁免只针对
        # 系统层）；层序 negative_list 先于 book_blacklist，归 negative_list
        got = [(e.pattern, e.source) for e in ps.entries if e.pattern == "系统词"]
        assert got == [("系统词", "negative_list")]

    def test_exemption_only_removes_system_layer_blacklist_variant(self, monkeypatch):
        _mock_system(monkeypatch, [{"pattern": "系统词", "is_regex": False}])
        ps = _load(
            book=_FakeBook(
                style_blacklist=["系统词"],
                style_cliche_exemptions=["系统词"],
            ),
        )
        got = [(e.pattern, e.source) for e in ps.entries if e.pattern == "系统词"]
        assert got == [("系统词", "book_blacklist")]

    def test_exemption_from_book_attr(self, monkeypatch):
        _mock_system(monkeypatch, [
            {"pattern": "豁词", "is_regex": False},
            {"pattern": "留词", "is_regex": False},
        ])
        ps = _load(book=_FakeBook(style_cliche_exemptions=["豁词"]))
        assert "豁词" not in [e.pattern for e in ps.entries]
        assert any(e.pattern == "留词" and e.source == "system_cliche" for e in ps.entries)

    def test_exemption_param_overrides_book_attr(self, monkeypatch):
        _mock_system(monkeypatch, [{"pattern": "参数豁词", "is_regex": False}])
        # book 属性豁 A，参数显式豁 B（空）——参数优先，A 保留
        ps = _load(
            book=_FakeBook(style_cliche_exemptions=["别的词"]),
            cliche_exemptions=[],
        )
        assert any(e.pattern == "参数豁词" for e in ps.entries)

    def test_non_collection_exemptions_ignored(self, monkeypatch):
        _mock_system(monkeypatch, [{"pattern": "系统词", "is_regex": False}])
        ps = _load(book=_FakeBook(style_cliche_exemptions="系统词"))  # str 非 list/tuple/set
        assert any(e.pattern == "系统词" for e in ps.entries)


# ============================================================
# 编译契约
# ============================================================

class TestCompile:
    def test_regex_compiled_as_is(self):
        ps = ProhibitionSet((ProhibitionEntry(pattern=r"瞳孔[^\n，。]{0,4}?(收缩|放大)", is_regex=True),))
        text = "他的瞳孔骤然收缩了一下。"
        hits = [(m.start(), m.end()) for m, _e in ps.finditer(text)]
        assert len(hits) == 1

    def test_non_regex_escaped(self):
        ps = ProhibitionSet((ProhibitionEntry(pattern="a.b"),))
        assert [m.group(0) for m, _e in ps.finditer("x a.b y axb z")] == ["a.b"]

    def test_bad_regex_skipped(self):
        ps = ProhibitionSet((
            ProhibitionEntry(pattern="([bad", is_regex=True),
            ProhibitionEntry(pattern="好词"),
        ))
        assert len(ps.compiled) == 1  # 坏正则静默跳过，好条目保留

    def test_empty_pattern_skipped(self):
        ps = ProhibitionSet((ProhibitionEntry(pattern=""),))
        assert len(ps) == 1
        assert ps.compiled == []


# ============================================================
# 静态层边界
# ============================================================

class TestStaticLayer:
    def test_only_banned_words_merged(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load()
        assert [e.pattern for e in ps.entries] == list(DEFAULT_BAN_LIST.banned_words)
        assert all(e.source == "anti_ai_static" for e in ps.entries)
        assert all(e.severity == "warning" for e in ps.entries)
        # micro_actions / regexes 不进合并（模块 docstring 边界声明）
        assert "指尖颤了颤" not in [e.pattern for e in ps.entries]
        assert "眼角余光" not in [e.pattern for e in ps.entries]

    def test_static_words_deduped_against_upper_layers(self, monkeypatch):
        _mock_system_empty(monkeypatch)
        ps = _load(style_card=_FakeCard(negative_list=[{"word": "深邃"}]))
        assert [e.pattern for e in ps.entries].count("深邃") == 1
        assert ps.entries[0].source == "negative_list"


# ============================================================
# words / prompt_text / 空集安全
# ============================================================

class TestPresentation:
    def test_words_truncation(self):
        ps = ProhibitionSet(tuple(ProhibitionEntry(pattern=f"词{i}") for i in range(5)))
        assert ps.words(3) == ["词0", "词1", "词2"]
        assert ps.words(0) == []
        assert ps.words(99) == [f"词{i}" for i in range(5)]

    def test_prompt_text(self):
        ps = ProhibitionSet(tuple(ProhibitionEntry(pattern=w) for w in ["甲", "乙", "丙"]))
        assert ps.prompt_text(2) == "甲、乙"
        assert ps.prompt_text(10) == "甲、乙、丙"

    def test_empty_set_safe(self):
        assert len(EMPTY_PROHIBITION_SET) == 0
        assert not EMPTY_PROHIBITION_SET
        assert EMPTY_PROHIBITION_SET.words(5) == []
        assert EMPTY_PROHIBITION_SET.prompt_text(5) == ""
        assert EMPTY_PROHIBITION_SET.compiled_patterns == []
        assert list(EMPTY_PROHIBITION_SET.finditer("任意文本")) == []

    def test_compiled_patterns_compat_view(self):
        ps = ProhibitionSet((
            ProhibitionEntry(pattern="甲", alternative="替", severity="blocker", source="x"),
            ProhibitionEntry(pattern="乙"),
        ))
        view = ps.compiled_patterns
        assert len(view) == 2
        c, alt, sev = view[0]  # 旧消费方三元素解包
        assert c.pattern == re.escape("甲")
        assert (alt, sev) == ("替", "blocker")
        c2, alt2, sev2 = view[1]
        assert (c2.pattern, alt2, sev2) == (re.escape("乙"), "", "warning")


# ============================================================
# finditer 与旧三层实现对拍（span 集合相等）
# ============================================================

class TestFinditerParity:
    def test_spans_equal_to_old_layers(self, monkeypatch):
        system_items = [
            {"pattern": "眼底闪过一丝", "is_regex": False, "alternative": "替A", "severity": "warning"},
            {"pattern": r"瞳孔[^\n，。]{0,4}?(收缩|放大)", "is_regex": True,
             "alternative": None, "severity": "warning"},
        ]
        blacklist = ["黑名单词", {"word": "字典词", "alternative": "替B", "severity": "warning"}]
        negative = [{"word": "负面词", "alternative": "替C"}]
        _mock_system(monkeypatch, system_items)

        text = ("他眼底闪过一丝寒意。她的瞳孔骤然收缩。黑名单词出现了。"
                "字典词与负面词同框。瞳孔缓缓放大。眼底闪过一丝又一丝。")

        ps = _load(book=_FakeBook(style_blacklist=blacklist), style_card=_FakeCard(negative))

        new_hits = {(m.start(), m.end(), m.group(0)) for m, _e in ps.finditer(text)}
        old_hits = set()
        for compiled, _alt, _sev in _old_validator_layers(system_items, blacklist, negative):
            for m in compiled.finditer(text):
                old_hits.add((m.start(), m.end(), m.group(0)))
        assert new_hits == old_hits
        assert len(new_hits) >= 5  # 样本文本确实命中（防两边同空假绿）


# ============================================================
# 与 settings_bundle._merge_banned_words 的集合对拍
# ============================================================

class TestOldMergeParity:
    def test_set_equality_without_system_layer(self, monkeypatch):
        from backend.services.context.settings_bundle import _merge_banned_words

        _mock_system_empty(monkeypatch)
        card = _FakeCard(negative_list=[{"word": "负面甲"}, {"phrase": "负面乙"}])
        blacklist = ["黑一", {"word": "黑二", "alternative": "x"}]

        ps = _load(book=_FakeBook(style_blacklist=blacklist), style_card=card)
        old = _merge_banned_words(card, blacklist)

        assert set(old) == set(ps.words(60))
        assert {"负面甲", "负面乙", "黑一", "黑二"} <= set(old)
        assert set(DEFAULT_BAN_LIST.banned_words) <= set(old)
        # 顺序是有意变化（旧：blacklist → negative → static；
        # 新：negative → blacklist → static），只锁集合
        assert ps.words(60)[:2] == ["负面甲", "负面乙"]


# ============================================================
# 系统层异常降级种子库
# ============================================================

class TestDegradeToSeeds:
    def test_exception_falls_back_to_seeds(self, monkeypatch):
        async def _boom(db=None, use_cache=True, **kwargs):
            raise RuntimeError("DB 挂了")
        monkeypatch.setattr(cliche_provider, "get_active_cliches", _boom)

        ps = _load()
        seeds = {e.pattern for e in ps.entries if e.source == "system_cliche"}
        from backend.services.style.default_cliches import get_all_seed_cliches
        assert seeds == {i["pattern"] for i in get_all_seed_cliches()}
        assert "眼底闪过一丝" in seeds


# ============================================================
# StyleClicheValidator 静态源排除（validate 行为锁定）
# ============================================================

class TestValidatorStaticExclusion:
    def test_static_words_do_not_soft_fail(self, monkeypatch):
        """静态高频词命中不进 threshold=2 软失败计数（防误伤）。"""
        from backend.services.workflows.validators import StyleClicheValidator

        _mock_system_empty(monkeypatch)
        v = StyleClicheValidator()  # threshold=2
        result = asyncio.run(v.validate("他的眼神深邃而幽深，宛如墨色。", {}))
        assert result.is_valid  # 深邃/幽深/宛如 均静态源，不触发软失败

    def test_negative_list_over_threshold_soft_fails(self, monkeypatch):
        from backend.services.workflows.validators import StyleClicheValidator

        _mock_system_empty(monkeypatch)
        v = StyleClicheValidator()
        text = "啰嗦词一。啰嗦词二。啰嗦词三。"
        result = asyncio.run(v.validate(text, {"style_negative_list": [{"word": "啰嗦词"}]}))
        assert not result.is_valid
        assert result.categories == ["文风"]
        assert "啰嗦词" in result.errors[0]

    def test_blocker_hard_fails_regardless_of_source(self, monkeypatch):
        from backend.services.workflows.validators import StyleClicheValidator

        _mock_system_empty(monkeypatch)
        v = StyleClicheValidator()
        result = asyncio.run(v.validate("硬禁词出现了。", {
            "style_blacklist": [{"word": "硬禁词", "severity": "blocker"}],
        }))
        assert not result.is_valid
        assert any("硬阻断" in e for e in result.errors)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))

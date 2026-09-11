# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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

    def test_severity_blocker_passthrough(self, monkeypatch):
        """Phase 3：negative_list 条目标 blocker 原样收（层② 读 severity）。"""
        _mock_system_empty(monkeypatch)
        ps = _load(negative_list=[{"word": "测试词", "severity": "blocker"}])
        entry = next(e for e in ps.entries if e.pattern == "测试词")
        assert entry.severity == "blocker"
        assert entry.source == "negative_list"

    def test_severity_invalid_downgrades_to_warning(self, monkeypatch):
        """白名单校验：None / 非法串 / 大小写不一致 一律降级 warning。"""
        _mock_system_empty(monkeypatch)
        ps = _load(negative_list=[
            {"word": "无键词"},                                  # 无 severity 键
            {"word": "非法词", "severity": "hard"},              # 非法串
            {"word": "空串词", "severity": ""},                  # 空串
            {"word": "大写词", "severity": "BLOCKER"},           # 大小写敏感——降级
            {"word": "正常词", "severity": "warning"},           # 合法 warning
        ])
        got = {e.pattern: e.severity for e in ps.entries if e.source == "negative_list"}
        assert got == {
            "无键词": "warning", "非法词": "warning", "空串词": "warning",
            "大写词": "warning", "正常词": "warning",
        }


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
# 呈现排序（Phase 3 任务包 E：作者负面清单第一档、blocker 次档）
# ============================================================

class TestPresentationOrder:
    def test_mixed_sources_ordering(self, monkeypatch):
        """混合源集合的呈现序：作者 blocker → 作者 warning → 系统 blocker →
        系统 warning / blacklist / static 按原层序。"""
        _mock_system(monkeypatch, [
            {"pattern": "系警", "is_regex": False, "severity": "warning"},
            {"pattern": "系禁", "is_regex": False, "severity": "blocker"},
        ])
        ps = _load(
            book=_FakeBook(style_blacklist=["黑词"]),
            negative_list=[
                {"word": "作警", "severity": "warning"},
                {"word": "作禁", "severity": "blocker"},
            ],
        )
        assert ps.prompt_text(99) == "作禁、作警、系禁、系警、黑词、" + "、".join(
            DEFAULT_BAN_LIST.banned_words
        )

    def test_entries_storage_order_unchanged(self, monkeypatch):
        """呈现排序不回写存储序：entries / compiled 仍按层序（加载序）。"""
        _mock_system(monkeypatch, [{"pattern": "系词", "is_regex": False}])
        ps = _load(
            book=_FakeBook(style_blacklist=["黑词"]),
            negative_list=[{"word": "负词", "severity": "blocker"}],
        )
        sources = [e.source for e in ps.entries]
        assert sources[0] == "system_cliche"
        assert sources[1] == "negative_list"       # blocker 仍排存储序第二
        assert sources[2] == "book_blacklist"
        # compiled 遍历序与 entries 一致（匹配行为零变化）
        assert [e.pattern for _c, e in ps.compiled][:3] == ["系词", "负词", "黑词"]

    def test_truncation_prefers_author_entries(self, monkeypatch):
        """截断时作者负面清单优先占坑（prompt 预算内作者的话先说）。"""
        _mock_system(monkeypatch, [
            {"pattern": f"系词{i}", "is_regex": False} for i in range(5)
        ])
        ps = _load(negative_list=[{"word": "作者词"}])
        assert ps.words(3) == ["作者词", "系词0", "系词1"]
        assert ps.words(1) == ["作者词"]

    def test_same_tier_stable_original_order(self):
        """同档内保持原 index（sort 稳定性）——无 source/severity 的裸条目序不变。"""
        ps = ProhibitionSet(tuple(ProhibitionEntry(pattern=w) for w in ["甲", "乙", "丙"]))
        assert ps.words(10) == ["甲", "乙", "丙"]


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
# 与旧 settings_bundle._merge_banned_words 的集合对拍——
# 已随任务包 B 删除（deprecated 回退函数退役，prohibitions 成为唯一权威）
# ============================================================


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


# ============================================================
# NegativeEntry schema 兼容（Phase 3 任务 1：旧数据零迁移零 422 硬约束）
# ============================================================

class TestNegativeEntrySchema:
    def _orm_like(self, negative_list):
        """SimpleNamespace 模拟 StyleCard ORM 行（from_attributes 走属性访问）。"""
        from datetime import datetime, timezone as _tz
        from types import SimpleNamespace
        from uuid import uuid4

        return SimpleNamespace(
            id=uuid4(), book_id=uuid4(), chapter_id=None,
            created_at=datetime.now(_tz.utc), updated_at=datetime.now(_tz.utc),
            positive_profile={}, negative_list=negative_list,
            dialogue_ratio_target=None, paragraph_rhythm=None, notes=None,
            style_knobs={}, locked_keys=None, fingerprint=None,
        )

    def test_legacy_entry_without_severity_no_422(self):
        """硬约束实证：DB 存量条目（无 severity 键）经 from_attributes 不断言
        错误，且条目 severity 兜底 "warning"。"""
        from backend.schemas import StyleCardResponse

        obj = self._orm_like([
            {"word": "旧词", "alternative": "替"},   # 无 severity 键（存量主流形态）
            {"word": "另一旧词"},                     # 无 alternative 无 severity
        ])
        resp = StyleCardResponse.model_validate(obj)  # 不得 422
        assert [e.severity for e in resp.negative_list] == ["warning", "warning"]
        assert resp.negative_list[0].alternative == "替"

    def test_legacy_phrase_only_entry_mapped_to_word(self):
        """仅带 phrase 键的存量条目归一到 word（读取侧 phrase 容错口径对齐）。"""
        from backend.schemas import StyleCardResponse

        obj = self._orm_like([{"phrase": "旧短语", "alternative": "替"}])
        resp = StyleCardResponse.model_validate(obj)
        assert resp.negative_list[0].word == "旧短语"
        assert resp.negative_list[0].severity == "warning"

    def test_blocker_entry_roundtrip(self):
        from backend.schemas import StyleCardResponse

        obj = self._orm_like([{"word": "硬禁词", "severity": "blocker"}])
        resp = StyleCardResponse.model_validate(obj)
        assert resp.negative_list[0].severity == "blocker"

    def test_invalid_severity_rejected_on_write_path(self):
        """写入侧（PUT /style-card）严格校验：非法 severity 422——脏数据
        不入库（与 prohibitions 读取侧白名单降级是两道独立的闸）。"""
        import pytest as _pytest
        from pydantic import ValidationError
        from backend.schemas import NegativeEntry

        with _pytest.raises(ValidationError):
            NegativeEntry(word="词", severity="hard")

    def test_extract_response_normalizes_entries(self):
        """StyleExtractResponse.negative_list 同步结构化：缺省 severity 归一。"""
        from backend.schemas import StyleExtractResponse

        resp = StyleExtractResponse(
            positive_profile={}, negative_list=[{"word": "提炼词", "alternative": "替"}],
        )
        assert resp.negative_list[0].severity == "warning"


# ============================================================
# confirm 收件箱确认解析（Phase 3 任务 3：severity 透传 + 可选覆盖字段）
# ============================================================

class TestConfirmNegativeResolve:
    def _resolve(self, payload, **override_kwargs):
        from backend.routes.style.feedback import _resolve_negative_confirm
        from backend.schemas import StyleInboxConfirmRequest

        override = StyleInboxConfirmRequest(**override_kwargs) if override_kwargs else None
        return _resolve_negative_confirm(payload, override)

    def test_no_override_passthrough(self):
        """旧调用方（空 body）行为逐字节不变。"""
        assert self._resolve({"word": "原词", "alternative": "原替"}) == ("原词", "原替", "warning")

    def test_severity_passthrough_and_downgrade(self):
        assert self._resolve({"word": "w", "severity": "blocker"})[2] == "blocker"
        assert self._resolve({"word": "w", "severity": "hard"})[2] == "warning"
        assert self._resolve({"word": "w"})[2] == "warning"

    def test_word_override_non_empty(self):
        got = self._resolve({"word": "原词"}, word="  改后词  ")
        assert got == ("改后词", None, "warning")

    def test_word_override_empty_ignored(self):
        """word 覆盖 strip 后为空 → 忽略覆盖（词是非空必填，空值不成条目）。"""
        got = self._resolve({"word": "原词"}, word="   ")
        assert got[0] == "原词"

    def test_alternative_override_set_and_clear(self):
        # 覆盖为非空：替代改写
        assert self._resolve({"word": "w", "alternative": "旧替"}, alternative="新替")[1] == "新替"
        # 覆盖为空串：清除替代（None）
        assert self._resolve({"word": "w", "alternative": "旧替"}, alternative="  ")[1] is None
        # 未携带（None）：维持原候选
        assert self._resolve({"word": "w", "alternative": "旧替"})[1] == "旧替"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


# ============================================================
# words() severity 过滤（2026-08-25 A2：生成侧只拦 blocker 档）
# ============================================================

class TestWordsSeverityFilter:
    def _set(self):
        return ProhibitionSet((
            ProhibitionEntry(pattern="作者提醒词", severity="warning", source="negative_list"),
            ProhibitionEntry(pattern="作者硬禁词", severity="blocker", source="negative_list"),
            ProhibitionEntry(pattern="系统陈词", severity="warning", source="system_cliche"),
        ))

    def test_default_returns_all_zero_change(self):
        """缺省 severity=None 收全量——prompt 注入等存量消费方零变化。

        呈现序（既有语义）：作者负面清单第一档、其中 blocker 在前。
        """
        assert self._set().words(60) == ["作者硬禁词", "作者提醒词", "系统陈词"]

    def test_blocker_only(self):
        assert self._set().words(60, severity="blocker") == ["作者硬禁词"]

    def test_warning_only(self):
        got = self._set().words(60, severity="warning")
        assert got == ["作者提醒词", "系统陈词"]

    def test_missing_severity_defaults_to_warning(self):
        """条目 severity 缺省/None 按 warning 档归（与 load 侧口径一致）。"""
        s = ProhibitionSet((
            ProhibitionEntry(pattern="无档词", source="book_blacklist"),
            ProhibitionEntry(pattern="硬词", severity="blocker", source="negative_list"),
        ))
        assert s.words(60, severity="blocker") == ["硬词"]
        assert "无档词" in s.words(60, severity="warning")

    def test_max_entries_applies_after_filter(self):
        assert self._set().words(1, severity="warning") == ["作者提醒词"]

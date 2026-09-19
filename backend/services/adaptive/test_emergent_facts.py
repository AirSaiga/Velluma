# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 涌现抽取失败标记单测（02 候选回流修缮 P6）
"""EmergentFacts.failed 契约：「LLM 失败」与「无涌现」显式区分。

- LLM 异常 / 空响应 / 输出不可解析 → failed=True（调用方据此保留重试资格）
- 合法 JSON（含全空列表=无涌现）→ failed=False（照写幂等锚）
- 提取仍是「绝不抛异常」契约（失败静默降级，只换标记）

mock 形状：call_llm_with_usage 返回 (text, usage) 二元组（对齐模块
_unwrap_llm_response 的测试形态）。运行：
python -m pytest backend/services/adaptive/test_emergent_facts.py -v
"""

import asyncio
from unittest.mock import AsyncMock, patch

from backend.services.adaptive.emergent_facts import extract_emergent_facts

_LLM = "backend.services.adaptive.emergent_facts.call_llm_with_usage"
SEG = "陈朗带着李岩父女连夜出了北门，雪一直下到天明。"


def test_llm_exception_marks_failed():
    with patch(_LLM, new=AsyncMock(side_effect=RuntimeError("boom"))):
        out = asyncio.run(extract_emergent_facts(SEG, beat_id="b1"))
    assert out.failed is True
    assert out.is_empty()


def test_empty_output_marks_failed():
    with patch(_LLM, new=AsyncMock(return_value=("", {}))):
        out = asyncio.run(extract_emergent_facts(SEG, beat_id="b1"))
    assert out.failed is True


def test_unparseable_output_marks_failed():
    with patch(_LLM, new=AsyncMock(return_value=("这不是 JSON", {}))):
        out = asyncio.run(extract_emergent_facts(SEG, beat_id="b1"))
    assert out.failed is True


def test_valid_json_with_entities_not_failed():
    raw = ('{"new_entities": [{"name": "李岩", "kind": "character"}],'
           ' "new_locations": [], "relationship_changes": [], "outline_addenda": []}')
    with patch(_LLM, new=AsyncMock(return_value=(raw, {}))):
        out = asyncio.run(extract_emergent_facts(SEG, beat_id="b1"))
    assert out.failed is False
    assert len(out.new_entities) == 1
    assert out.is_empty() is False


def test_no_emergence_is_not_failure():
    """可解析的全空列表=无涌现（合法结果）——与失败严格区分。"""
    raw = ('{"new_entities": [], "new_locations": [],'
           ' "relationship_changes": [], "outline_addenda": []}')
    with patch(_LLM, new=AsyncMock(return_value=(raw, {}))):
        out = asyncio.run(extract_emergent_facts(SEG, beat_id="b1"))
    assert out.failed is False
    assert out.is_empty()


def test_empty_segment_short_circuits_not_failed():
    """空段早退不走 LLM——不是失败（调用方本就不该为空段花预算）。"""
    out = asyncio.run(extract_emergent_facts("", beat_id="b1"))
    assert out.failed is False
    assert out.is_empty()

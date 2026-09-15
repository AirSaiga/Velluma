# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""extract_style_card 单测——services/style/extractor.py（文风画像提炼）。

LLM 全 mock（monkeypatch 模块内 call_llm）。失败降级红线（Phase 0 失败
不静默）：任何失败路径都必须返回 degraded 字段说明原因，函数永不抛出。

提炼红线（S1）：提炼不落库，过目才存——本模块只产 dict。
"""

import pytest

import backend.services.style.extractor as extractor_mod
from backend.services.style.extractor import extract_style_card


def _good_llm_response() -> str:
    return (
        '{"positive_profile": {"sentence_style": "短句为主"}, '
        '"negative_list": [{"word": "眼底闪过", "alternative": "用具体动作"}], '
        '"dialogue_ratio_target": 0.4, '
        '"paragraph_rhythm": "两短一长"}'
    )


@pytest.mark.asyncio
async def test_no_valid_samples_degrades(monkeypatch):
    async def fail_llm(**kwargs):  # 不应被调用
        raise AssertionError("无样本不应触发 LLM")

    monkeypatch.setattr(extractor_mod, "call_llm", fail_llm)
    result = await extract_style_card([])
    assert result["degraded"]["reason"] == "no_valid_samples"
    assert result["degraded"]["action"] == "genre_fallback"
    assert result["negative_list"] == []
    # 空白样本同判
    result2 = await extract_style_card(["   ", ""])
    assert result2["degraded"]["reason"] == "no_valid_samples"


@pytest.mark.asyncio
async def test_llm_exception_degrades(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("模型超时")

    monkeypatch.setattr(extractor_mod, "call_llm", boom)
    result = await extract_style_card(["作者样本一段。"])
    assert result["degraded"]["reason"] == "llm_call_exception"
    assert "positive_profile" in result  # 兜底画像仍给（题材默认）


@pytest.mark.asyncio
async def test_parse_failure_degrades(monkeypatch):
    async def bad_json(**kwargs):
        return "这不是 JSON"

    monkeypatch.setattr(extractor_mod, "call_llm", bad_json)
    result = await extract_style_card(["作者样本一段。"])
    assert result["degraded"]["reason"] == "parse_failed"


@pytest.mark.asyncio
async def test_success_path(monkeypatch):
    async def good(**kwargs):
        return _good_llm_response()

    monkeypatch.setattr(extractor_mod, "call_llm", good)
    result = await extract_style_card(["作者样本一段。", "作者样本二段。"])
    assert result["degraded"] is None
    assert result["positive_profile"]["sentence_style"] == "短句为主"
    assert result["negative_list"] == [{"word": "眼底闪过", "alternative": "用具体动作"}]
    assert result["dialogue_ratio_target"] == 0.4
    assert result["paragraph_rhythm"] == "两短一长"


@pytest.mark.asyncio
async def test_success_with_markdown_fence(monkeypatch):
    # LLM 常把 JSON 包在 ```json 围栏里，解析层须剥
    async def fenced(**kwargs):
        return f"```json\n{_good_llm_response()}\n```"

    monkeypatch.setattr(extractor_mod, "call_llm", fenced)
    result = await extract_style_card(["作者样本一段。"])
    assert result["degraded"] is None
    assert result["dialogue_ratio_target"] == 0.4


@pytest.mark.asyncio
async def test_empty_profile_filled_by_fallback(monkeypatch):
    # 成功解析但画像为空 → 题材默认画像补位，不算降级
    async def sparse(**kwargs):
        return '{"positive_profile": {}, "negative_list": []}'

    monkeypatch.setattr(extractor_mod, "call_llm", sparse)
    result = await extract_style_card(["作者样本一段。"])
    assert result["degraded"] is None
    assert result["positive_profile"]  # 非空（默认画像补位）


@pytest.mark.asyncio
async def test_dialogue_ratio_clamped(monkeypatch):
    # 越界对话占比钳制到 [0, 1]
    async def overflow(**kwargs):
        return '{"positive_profile": {"a": "b"}, "dialogue_ratio_target": 1.7}'

    monkeypatch.setattr(extractor_mod, "call_llm", overflow)
    result = await extract_style_card(["作者样本一段。"])
    assert result["dialogue_ratio_target"] == 1.0

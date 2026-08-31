# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""deai 宿主侧单测：运行时闸门对拍 + polish_fragment 保底行为（零 LLM/零网络）。

对拍纪律：gates 用例取自 deai/scripts/validate_pairs.py 的 SELFTEST（fact=None
路径）——权威实现判据变更时先跑其 --selftest，再同步本文件用例。
配方同 test_stitch_gates.py：同步测试函数内独立 asyncio.run、monkeypatch
打桩（不连真实 LLM/DB/网络）。
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.services.deai import gates as deai_gates
from backend.services.deai import client as deai_client
from backend.services.deai.client import DeaiResult, polish_fragment


# ============================================================
# 运行时闸门（对拍 deai SELFTEST 用例，fact=None 路径）
# ============================================================

def _run(source: str, rewritten: str):
    return deai_gates.runtime_gates(source, rewritten)


def test_gate_normal_rewrite_passes():
    """正常改写：零事实失败、零警告（SELFTEST「正常通过」对拍）。"""
    fact_fail, warnings = _run(
        "综上所述，本次改版显著提升了页面加载速度，为后续增长夯实了基础。",
        "这轮改版后，页面加载快了不少，后面的增长也有底了。",
    )
    assert fact_fail == []
    assert warnings == []


def test_gate_lost_number_is_fact_failure():
    """数字被改/丢失 → 数字闸事实失败（运行时必须回退原文）。"""
    fact_fail, _ = _run("会议定在6月3日，覆盖3个城市。", "会议定在6月，覆盖三个城市。")
    assert [g for g, _ in fact_fail] == ["数字闸"]


def test_gate_new_number_is_fact_failure():
    """新增数字（编造事实）→ 新增事实闸。"""
    fact_fail, _ = _run(
        "这个项目的项目周期为两周，先做起来。", "项目周期两周，预算50万，先做起来。"
    )
    assert "新增事实闸" in [g for g, _ in fact_fail]


def test_gate_quote_altered_is_fact_failure():
    """引文/书名内容被改 → 专名闸 + 新增事实闸（SELFTEST「引文被改」对拍）。"""
    fact_fail, _ = _run(
        "他在《三体》里最喜欢的角色是“罗辑”，没有之一。",
        "《三体》里，他最喜欢的角色叫“逻辑”，没有之一。",
    )
    names = {g for g, _ in fact_fail}
    assert names == {"专名闸", "新增事实闸"}


def test_gate_latin_token_lost_is_fact_failure():
    """英文专名丢失 → 专名闸。"""
    fact_fail, _ = _run("他在用iPhone拍照。", "他在用手机拍照。")
    assert "专名闸" in [g for g, _ in fact_fail]


def test_gate_forbidden_word_is_warning_only():
    """套话残留 → 仅警告（非事实闸，改写仍可用，契约§6）。"""
    fact_fail, warnings = _run("这个方案整体来说值得肯定。", "这个方案为团队赋能，值得肯定。")
    assert fact_fail == []
    assert any("套话闸" in w for w in warnings)


def test_gate_overlong_is_warning_only():
    """输出超 120% → 仅警告。"""
    fact_fail, warnings = _run(
        "今天天气不错。",
        "今天天气真的很不错，让人心情也跟着变好，走在路上都觉得轻快，连工作效率都提高了。",
    )
    assert fact_fail == []
    assert any("长度闸" in w for w in warnings)


def test_gate_unchanged_is_warning_only():
    """没改（差异率不足）→ 像人闸警告，不是事实失败。"""
    fact_fail, warnings = _run("我觉得这个功能很好用。", "我觉得这个功能很好用。")
    assert fact_fail == []
    assert any("像人闸" in w for w in warnings)


# ============================================================
# polish_fragment：配置守门 + 契约§6 保底（_call_dashscope 全程打桩）
# ============================================================

CFG = {"enabled": True, "api_key": "sk-test", "model": "test-model", "base_url": "http://x"}


def _patch_config(monkeypatch, cfg=None):
    monkeypatch.setattr(deai_client, "get_deai_config", lambda: cfg or CFG)


def _patch_model(monkeypatch, output: str | Exception):
    async def fake(text, model, api_key, base_url):
        if isinstance(output, Exception):
            raise output
        return output, {"input_tokens": 3, "output_tokens": 5}
    monkeypatch.setattr(deai_client, "_call_dashscope", fake)


def test_polish_unconfigured_key_skips_without_call(monkeypatch):
    """未配置 Key → 直通零调用（零变化契约）。"""
    _patch_config(monkeypatch, {**CFG, "api_key": ""})
    called = []

    async def boom(*a, **k):
        called.append(1)
        raise AssertionError("不应发起调用")
    monkeypatch.setattr(deai_client, "_call_dashscope", boom)
    res = asyncio.run(polish_fragment("综上所述，体验显著提升。"))
    assert res.skipped and not res.applied
    assert res.text == "综上所述，体验显著提升。"
    assert called == []


def test_polish_over_100_chars_skips(monkeypatch):
    """>100 字 → 契约 C1 不改写（burst/outline 长稿自动跳过的机制）。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, AssertionError("不应调用"))  # 占位：不会被执行
    long_text = "字" * 101
    res = asyncio.run(polish_fragment(long_text))
    assert res.skipped and res.text == long_text


def test_polish_clean_rewrite_applied(monkeypatch):
    """干净改写 → 采纳替换。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, "这轮改版后，页面加载快了不少。")
    res = asyncio.run(polish_fragment("综上所述，本次改版显著提升了页面加载速度。"))
    assert res.applied and res.text == "这轮改版后，页面加载快了不少。"


def test_polish_fact_alteration_falls_back(monkeypatch):
    """模型动了数字 → 契约§6 回退原文。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, "会议定在6月，覆盖三个城市。")
    src = "会议定在6月3日，覆盖3个城市。"
    res = asyncio.run(polish_fragment(src))
    assert not res.applied and res.text == src
    assert res.reason.startswith("事实被改")


def test_polish_network_error_falls_back(monkeypatch):
    """网络/HTTP 异常 → 回退原文，绝不阻塞生成。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, httpx.ConnectError("boom"))
    src = "综上所述，体验显著提升。"
    res = asyncio.run(polish_fragment(src))
    assert not res.applied and res.text == src
    assert "网络错误" in res.reason


def test_polish_empty_output_falls_back(monkeypatch):
    """空输出 → 回退原文。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, "  ")
    src = "综上所述，体验显著提升。"
    res = asyncio.run(polish_fragment(src))
    assert not res.applied and res.text == src


def test_polish_form_override_beats_config(monkeypatch):
    """试一试的表单覆盖值优先（未保存也能测）。"""
    _patch_config(monkeypatch, {**CFG, "api_key": ""})  # 配置里无 Key
    seen = {}

    async def fake(text, model, api_key, base_url):
        seen.update(model=model, api_key=api_key)
        return "这轮改版后，页面加载快了不少。", {}
    monkeypatch.setattr(deai_client, "_call_dashscope", fake)
    res = asyncio.run(polish_fragment(
        "综上所述，本次改版显著提升了页面加载速度。",
        model="form-model", api_key="form-key",
    ))
    assert res.applied
    assert seen == {"model": "form-model", "api_key": "form-key"}


# ============================================================
# 宿主侧保名闸（导师审 P1-1：契约专名闸不护中文名）
# ============================================================

def test_polish_protected_name_lost_falls_back(monkeypatch):
    """原文出现的保护名在改写稿中消失 → 按事实失败回退原文。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, "他站在北岸要塞，望着对岸的火光。")  # 「林尘」被改掉
    src = "林尘站在北岸要塞，望着对岸的火光。"
    res = asyncio.run(polish_fragment(src, protected_names=["林尘", "萧燕"]))
    assert not res.applied and res.text == src
    assert "保名闸" in res.reason


def test_polish_protected_name_absent_from_source_ignored(monkeypatch):
    """保护名不在原文中出现 → 不参与比对（萧燕不在文中，改写不背锅）。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, "林尘站在北岸，望着对岸的火光。")
    res = asyncio.run(polish_fragment(
        "林尘站在北岸要塞，望着对岸的火光。", protected_names=["林尘", "萧燕"],
    ))
    assert res.applied


# ============================================================
# 用量记账（导师审 P1-3：DashScope usage 透传进 DeaiResult/trace）
# ============================================================

def test_polish_usage_carried_to_result(monkeypatch):
    """DashScope usage 的 input/output tokens 透传（applied 与保底两路都要带）。"""
    _patch_config(monkeypatch)
    _patch_model(monkeypatch, "这轮改版后，页面加载快了不少。")
    res = asyncio.run(polish_fragment("综上所述，本次改版显著提升了页面加载速度。"))
    assert res.applied and res.tokens_in == 3 and res.tokens_out == 5

    # 保底路（事实被改回退）同样带 token——钱已经花了，账要记
    _patch_model(monkeypatch, "会议定在6月，覆盖三个城市。")
    res2 = asyncio.run(polish_fragment("会议定在6月3日，覆盖3个城市。"))
    assert not res2.applied and res2.tokens_in == 3 and res2.tokens_out == 5


def test_is_deai_configured_gate(monkeypatch):
    """is_deai_configured = enabled 且 key 且 model 三者齐备。"""
    monkeypatch.setattr(deai_client, "get_deai_config", lambda: CFG)
    assert deai_client.is_deai_configured() is True
    for miss in ("enabled", "api_key", "model"):
        bad = {**CFG, miss: (False if miss == "enabled" else "")}
        monkeypatch.setattr(deai_client, "get_deai_config", lambda bad=bad: bad)
        assert deai_client.is_deai_configured() is False


def test_deai_result_contract():
    """DeaiResult 默认形态：text 恒为最终采用文本（保底=原文）。"""
    r = DeaiResult(text="原文")
    assert r.text == "原文" and not r.applied and not r.skipped
    assert r.reason == "" and r.warnings == []

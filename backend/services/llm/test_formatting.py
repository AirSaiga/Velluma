# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""llm/formatting 单测——智能文本格式化（全文格式整理 ⋯ 菜单消费）。

LLM 全 mock。对拍口径：
- _clean_llm_output：剥 ``` 围栏/「整理后：」前缀/CRLF 归一（纯函数）；
- llm_based_formatting：<50 字短文直返不烧 LLM；
- hybrid_formatting ±30% 门：LLM 结果长度畸变（模型删改原文）→ 回退规则引擎。
"""

import pytest

import backend.services.llm.formatting as fmt_mod
from backend.services.llm.formatting import _clean_llm_output, llm_based_formatting


class TestCleanLlmOutput:
    def test_code_fence_stripped(self):
        assert _clean_llm_output("```\n正文\n```") == "正文"
        assert _clean_llm_output("```text\n正文\n```") == "正文"

    def test_prefix_stripped(self):
        assert _clean_llm_output("整理后：正文") == "正文"
        assert _clean_llm_output("输出: 正文") == "正文"

    def test_crlf_normalized(self):
        assert _clean_llm_output("第一行\r\n第二行") == "第一行\n第二行"

    def test_plain_text_untouched(self):
        assert _clean_llm_output("  正文  ") == "正文"


class TestLlmBasedFormatting:
    @pytest.mark.asyncio
    async def test_short_text_skips_llm(self, monkeypatch):
        async def fail_llm(**kwargs):
            raise AssertionError("短文本不应调 LLM")

        monkeypatch.setattr(fmt_mod, "call_llm", fail_llm)
        out = await llm_based_formatting("很短的一段话，不足五十字。")
        assert out == "很短的一段话，不足五十字。"

    @pytest.mark.asyncio
    async def test_empty_input(self):
        assert await llm_based_formatting("") == ""
        assert await llm_based_formatting("   ") == ""

    @pytest.mark.asyncio
    async def test_llm_failure_returns_original(self, monkeypatch):
        async def boom(**kwargs):
            raise RuntimeError("模型不可用")

        monkeypatch.setattr(fmt_mod, "call_llm", boom)
        text = "这是一段足够长的正文，用来超过五十个字符的门槛，" * 2
        assert await llm_based_formatting(text) == text

    @pytest.mark.asyncio
    async def test_normal_output_cleaned(self, monkeypatch):
        async def fenced(**kwargs):
            return "```\n整理后的正文。\n```"

        monkeypatch.setattr(fmt_mod, "call_llm", fenced)
        text = "这是一段足够长的正文，用来超过五十个字符的门槛，" * 3  # ≥50 字才走 LLM
        out = await llm_based_formatting(text)
        assert out == "整理后的正文。"


class TestHybridGate:
    """±30% 长度门：LLM 结果畸变 → 回退规则引擎。（call_llm 返回裸字符串）"""

    @pytest.fixture
    def long_text(self) -> str:
        return "这是一段足够长的正文用来触发 LLM 路径并且方便控制长度。" * 3

    @pytest.mark.asyncio
    async def test_llm_result_within_band_accepted(self, monkeypatch, long_text):
        async def good(**kwargs):
            return long_text

        monkeypatch.setattr(fmt_mod, "call_llm", good)
        assert await fmt_mod.hybrid_formatting(long_text) == long_text

    @pytest.mark.asyncio
    async def test_llm_result_too_short_falls_back(self, monkeypatch, long_text):
        async def shrink(**kwargs):
            return "太短。"

        monkeypatch.setattr(fmt_mod, "call_llm", shrink)
        out = await fmt_mod.hybrid_formatting(long_text)
        # 回退规则引擎：产出与畸变的 LLM 结果不同
        assert out != "太短。"
        assert out

    @pytest.mark.asyncio
    async def test_llm_result_too_long_falls_back(self, monkeypatch, long_text):
        async def bloat(**kwargs):
            return long_text * 3

        monkeypatch.setattr(fmt_mod, "call_llm", bloat)
        out = await fmt_mod.hybrid_formatting(long_text)
        assert len(out) < len(long_text) * 3

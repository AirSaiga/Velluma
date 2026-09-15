# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""de_ai_washer 单测——去 AI 味洗涤编排（唯一含 LLM I/O 的 NLG 模块）。

LLM 全 mock（monkeypatch call_llm_with_usage），洗后密度复评 mock
measure_ai_taste——验证**处置分支**而非洗涤质量：

- 未超阈值 → 仅正则轻裁，washed=False，零 LLM 调用；
- LLM 异常 / 返回空 → 退回 sanitize 原文（失败不阻塞红线）；
- 洗后达标 → washed=True 用洗后文；
- 洗后仍超标但改善（分更低）→ 采洗后文+轻裁；
- 洗后更糟（分更高）→ 退回原文裁剪；
- must_keep / extra_banned_words 注入 user_prompt（锚点保护与负面清单接线）。
"""

from types import SimpleNamespace

import pytest

import backend.services.nlg.de_ai_washer as washer_mod
from backend.services.nlg.ai_taste_meter import DensityReport
from backend.services.nlg.de_ai_washer import wash_segment_if_too_ai


def _report(triggered: bool, score: float, reasons=("综合分超标",)) -> DensityReport:
    return DensityReport(triggered=triggered, overall_score=score, flagged_reasons=list(reasons))


def _llm_result(content: str):
    return SimpleNamespace(content=content, prompt_tokens=10, completion_tokens=10)


@pytest.fixture
def no_wash_profile(monkeypatch):
    # 无独立 wash 槽配置（默认环境），洗涤走 REASONING_DISABLED 分支
    monkeypatch.setattr(washer_mod, "has_dedicated_wash_profile", lambda: False)


class TestNotTriggered:
    @pytest.mark.asyncio
    async def test_below_threshold_no_llm(self, monkeypatch):
        calls = []

        async def fake_llm(**kwargs):
            calls.append(kwargs)
            return _llm_result("不该被调用")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        result = await wash_segment_if_too_ai("平静的叙述。", _report(False, 30.0))
        assert result.washed is False
        assert calls == []  # 零 LLM 调用
        assert result.text == "平静的叙述。"
        assert "未超阈值" in result.reason


class TestLlmFailureFallback:
    @pytest.mark.asyncio
    async def test_exception_falls_back_to_sanitized(self, monkeypatch, no_wash_profile):
        async def fake_llm(**kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        result = await wash_segment_if_too_ai("她的声音冷冽。", _report(True, 85.0))
        assert result.washed is False
        assert "冷冽" not in result.text  # 兜底文本是正则裁剪后的
        assert "洗涤失败" in result.reason

    @pytest.mark.asyncio
    async def test_empty_llm_output_falls_back(self, monkeypatch, no_wash_profile):
        async def fake_llm(**kwargs):
            return _llm_result("   ")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        result = await wash_segment_if_too_ai("平静的叙述。", _report(True, 85.0))
        assert result.washed is False
        assert result.text == "平静的叙述。"
        assert "退回正则裁剪" in result.reason


class TestWashOutcomes:
    @pytest.mark.asyncio
    async def test_wash_success(self, monkeypatch, no_wash_profile):
        async def fake_llm(**kwargs):
            return _llm_result("洗后的干净文本。")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(washer_mod, "measure_ai_taste", lambda text, thresholds=None: _report(False, 20.0))
        result = await wash_segment_if_too_ai("超标原文。", _report(True, 85.0))
        assert result.washed is True
        assert result.text == "洗后的干净文本。"
        assert result.final_score == 20.0

    @pytest.mark.asyncio
    async def test_still_triggered_but_improved(self, monkeypatch, no_wash_profile):
        async def fake_llm(**kwargs):
            return _llm_result("改善但仍超标的文本。")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(washer_mod, "measure_ai_taste", lambda text, thresholds=None: _report(True, 60.0))
        result = await wash_segment_if_too_ai("超标原文。", _report(True, 85.0))
        assert result.washed is True
        assert "改善" in result.reason

    @pytest.mark.asyncio
    async def test_wash_made_it_worse(self, monkeypatch, no_wash_profile):
        async def fake_llm(**kwargs):
            return _llm_result("越洗越糟的文本。")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(washer_mod, "measure_ai_taste", lambda text, thresholds=None: _report(True, 95.0))
        result = await wash_segment_if_too_ai("超标原文。", _report(True, 85.0))
        assert result.washed is False
        assert result.text == "超标原文。"
        assert "更糟" in result.reason


class TestPromptInjection:
    @pytest.mark.asyncio
    async def test_must_keep_and_banned_words_in_prompt(self, monkeypatch, no_wash_profile):
        captured = {}

        async def fake_llm(**kwargs):
            captured.update(kwargs)
            return _llm_result("洗后文本。")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(washer_mod, "measure_ai_taste", lambda text, thresholds=None: _report(False, 10.0))
        await wash_segment_if_too_ai(
            "超标原文。",
            _report(True, 85.0, reasons=("病态微操密度超标",)),
            must_keep=["北岸要塞"],
            extra_banned_words=["眼底闪过"],
        )
        assert "北岸要塞" in captured["user_prompt"]
        assert "必须保留的词" in captured["user_prompt"]
        assert "眼底闪过" in captured["user_prompt"]
        assert "本书负面清单禁词" in captured["user_prompt"]
        # 命中问题进 prompt（供 LLM 对症处理）
        assert "病态微操密度超标" in captured["user_prompt"]

    @pytest.mark.asyncio
    async def test_banned_words_capped_at_30(self, monkeypatch, no_wash_profile):
        captured = {}

        async def fake_llm(**kwargs):
            captured.update(kwargs)
            return _llm_result("洗后文本。")

        monkeypatch.setattr(washer_mod, "call_llm_with_usage", fake_llm)
        monkeypatch.setattr(washer_mod, "measure_ai_taste", lambda text, thresholds=None: _report(False, 10.0))
        await wash_segment_if_too_ai(
            "超标原文。",
            _report(True, 85.0),
            extra_banned_words=[f"禁词{i}" for i in range(50)],
        )
        assert "禁词49" not in captured["user_prompt"]
        assert "禁词29" in captured["user_prompt"]

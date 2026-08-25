# Velluma - 推理参数 provider 适配层单测
# AGPL-3.0
"""
纯算法单测，不连真实 LLM/DB。覆盖：
- detect_provider 按 base_url 域名识别 6 家 provider + local + unknown
- adapt_reasoning_config 各 provider 的开关/effort 映射
- 边界：None 输入、REASONING_DISABLED、无效 effort、缺失字段

运行：python -m pytest backend/services/llm/test_reasoning_adapter.py
"""
from __future__ import annotations

import sys
import os

# 确保能 import backend 包（pytest 从仓库根运行时通常不需要，但从本文件目录运行时需要）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

import pytest
from backend.services.llm.reasoning_adapter import (
    detect_provider,
    adapt_reasoning_config,
    DEEPSEEK, OPENAI, OPENROUTER, QWEN, DOUBAO, MIMO, LOCAL, UNKNOWN,
)
from backend.services.llm.client import REASONING_DISABLED


# ============================================================
# detect_provider 测试
# ============================================================

class TestDetectProvider:
    """按 base_url 域名识别 provider。"""

    @pytest.mark.parametrize("base_url,expected", [
        ("https://api.deepseek.com/v1", DEEPSEEK),
        ("https://api.deepseek.com", DEEPSEEK),
        ("https://api.openai.com/v1", OPENAI),
        ("https://openrouter.ai/api/v1", OPENROUTER),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", QWEN),
        ("https://ark.cn-beijing.volces.com/api/v3", DOUBAO),
        ("https://api.xiaomimimo.com/v1", MIMO),
        ("http://localhost:11434/v1", LOCAL),
        ("http://127.0.0.1:1234/v1", LOCAL),
        ("http://0.0.0.0:8080", LOCAL),
        ("https://some-unknown-proxy.example.com/v1", UNKNOWN),
        ("", UNKNOWN),
    ])
    def test_domain_recognition(self, base_url, expected):
        assert detect_provider(base_url) == expected

    def test_case_insensitive(self):
        """域名大小写不敏感。"""
        assert detect_provider("HTTPS://API.DEEPSEEK.COM/v1") == DEEPSEEK

    def test_volces_distinguishes_from_dashscope(self):
        """火山(volces)和通义(dashscope)是不同厂商，域名不能混。"""
        assert detect_provider("https://dashscope.aliyuncs.com/compatible-mode/v1") == QWEN
        assert detect_provider("https://ark.cn-beijing.volces.com/api/v3") == DOUBAO


# ============================================================
# adapt_reasoning_config 测试
# ============================================================

# 开启思考的典型中间表示（模拟 get_default_reasoning_config 产出）
ENABLED_HIGH = {"reasoning": {"enabled": True, "effort": "high", "exclude": False}}
ENABLED_LOW = {"reasoning": {"enabled": True, "effort": "low", "exclude": False}}
ENABLED_MAX = {"reasoning": {"enabled": True, "effort": "max", "exclude": False}}


class TestAdaptMimo:
    """小米 MiMo（api.xiaomimimo.com）：thinking.type。

    关键修复点（2026-08-16 实测）：MiMo 静默忽略 OpenRouter 的 reasoning.enabled
    与 Qwen 的 enable_thinking——隐藏思考继续烧 token 预算，小预算调用
    （速记解析 max_tokens=800）finish=length 空输出。thinking.type 才能真正关闭。
    """

    def test_disabled_produces_thinking_disabled(self):
        """REASONING_DISABLED → thinking.type=disabled（实测 reasoning_tokens=0）。"""
        result = adapt_reasoning_config(REASONING_DISABLED, "https://api.xiaomimimo.com/v1")
        assert result == {"thinking": {"type": "disabled"}}

    def test_enabled_produces_thinking_enabled_without_effort(self):
        """开启 → thinking.type=enabled；effort 档位未验证支持，不发。"""
        result = adapt_reasoning_config(ENABLED_HIGH, "https://api.xiaomimimo.com/v1")
        assert result == {"thinking": {"type": "enabled"}}


class TestAdaptDeepSeek:
    """DeepSeek：thinking.type + reasoning_effort。

    关键修复点：DeepSeek 不认 OpenRouter 的 reasoning.enabled，
    必须用 thinking.type 才能真正控制开关。
    """

    def test_disabled_produces_thinking_disabled(self):
        """REASONING_DISABLED → thinking.type=disabled（而非无效的 reasoning.enabled=false）。"""
        result = adapt_reasoning_config(REASONING_DISABLED, "https://api.deepseek.com/v1")
        assert result == {"thinking": {"type": "disabled"}, }

    def test_enabled_with_effort(self):
        result = adapt_reasoning_config(ENABLED_HIGH, "https://api.deepseek.com/v1")
        assert result["thinking"]["type"] == "enabled"
        assert result["reasoning_effort"] == "high"

    def test_disabled_has_no_reasoning_effort(self):
        """关闭时不附带 reasoning_effort（DeepSeek 关闭即不需要强度）。"""
        result = adapt_reasoning_config(REASONING_DISABLED, "https://api.deepseek.com")
        assert "reasoning_effort" not in result


class TestAdaptOpenAI:
    """OpenAI：顶层 reasoning_effort，无独立开关。"""

    def test_enabled_produces_reasoning_effort(self):
        result = adapt_reasoning_config(ENABLED_HIGH, "https://api.openai.com/v1")
        assert result == {"reasoning_effort": "high"}

    def test_disabled_returns_none(self):
        """OpenAI 无独立思考开关，关闭时不发参数（避免非推理模型收到报错）。"""
        result = adapt_reasoning_config(REASONING_DISABLED, "https://api.openai.com/v1")
        assert result is None


class TestAdaptOpenRouter:
    """OpenRouter：嵌套 reasoning 对象（Velluma 原生设计目标）。"""

    def test_enabled_preserves_structure(self):
        result = adapt_reasoning_config(ENABLED_HIGH, "https://openrouter.ai/api/v1")
        assert result == {"reasoning": {"enabled": True, "effort": "high", "exclude": False}}

    def test_disabled(self):
        result = adapt_reasoning_config(REASONING_DISABLED, "https://openrouter.ai/api/v1")
        assert result["reasoning"]["enabled"] is False


class TestAdaptQwen:
    """Qwen/通义：enable_thinking + thinking_budget。"""

    def test_enabled_with_budget(self):
        result = adapt_reasoning_config(ENABLED_HIGH, "https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert result["enable_thinking"] is True
        assert result["thinking_budget"] == 16384  # high → 16384

    def test_low_effort_budget(self):
        result = adapt_reasoning_config(ENABLED_LOW, "https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert result["thinking_budget"] == 2048  # low → 2048

    def test_max_effort_budget(self):
        result = adapt_reasoning_config(ENABLED_MAX, "https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert result["thinking_budget"] == 32768  # max → 32768

    def test_disabled_only_sends_flag(self):
        """关闭时只发 enable_thinking=False，不发 thinking_budget。"""
        result = adapt_reasoning_config(REASONING_DISABLED, "https://dashscope.aliyuncs.com/compatible-mode/v1")
        assert result == {"enable_thinking": False}
        assert "thinking_budget" not in result


class TestAdaptDoubao:
    """火山豆包：thinking.type，无 effort 控制。"""

    def test_enabled(self):
        result = adapt_reasoning_config(ENABLED_HIGH, "https://ark.cn-beijing.volces.com/api/v3")
        assert result == {"thinking": {"type": "enabled"}}

    def test_disabled(self):
        result = adapt_reasoning_config(REASONING_DISABLED, "https://ark.cn-beijing.volces.com/api/v3")
        assert result == {"thinking": {"type": "disabled"}}

    def test_no_effort_field(self):
        """豆包原生无 effort 控制，结果里不应出现 reasoning_effort。"""
        result = adapt_reasoning_config(ENABLED_HIGH, "https://ark.cn-beijing.volces.com/api/v3")
        assert "reasoning_effort" not in result


class TestAdaptLocal:
    """本地端点：默认不发推理参数（行为不可靠）。"""

    def test_localhost_returns_none(self):
        assert adapt_reasoning_config(ENABLED_HIGH, "http://localhost:11434/v1") is None

    def test_127_returns_none(self):
        assert adapt_reasoning_config(REASONING_DISABLED, "http://127.0.0.1:1234/v1") is None


class TestAdaptUnknown:
    """未知 provider：默认按 OpenRouter 协议透传（向后兼容）。"""

    def test_enabled_falls_back_to_openrouter_protocol(self):
        result = adapt_reasoning_config(ENABLED_HIGH, "https://some-proxy.example.com/v1")
        assert "reasoning" in result
        assert result["reasoning"]["enabled"] is True

    def test_disabled_falls_back(self):
        result = adapt_reasoning_config(REASONING_DISABLED, "https://some-proxy.example.com/v1")
        assert result["reasoning"]["enabled"] is False


# ============================================================
# 边界与健壮性测试
# ============================================================

class TestEdgeCases:

    def test_none_input_returns_none(self):
        """None 输入直接返回 None（不发任何参数）。"""
        assert adapt_reasoning_config(None, "https://api.deepseek.com/v1") is None

    def test_empty_dict_returns_none(self):
        """空 dict 输入返回 None（与 client.py 的 if truthy 检查一致）。"""
        assert adapt_reasoning_config({}, "https://api.deepseek.com/v1") is None

    def test_invalid_effort_falls_back_to_medium(self):
        """无效 effort 值回退到 medium。"""
        bad_effort = {"reasoning": {"enabled": True, "effort": "ultra", "exclude": False}}
        result = adapt_reasoning_config(bad_effort, "https://api.openai.com/v1")
        assert result == {"reasoning_effort": "medium"}

    def test_missing_effort_field(self):
        """缺 effort 字段时回退到 medium（兼容连接测试路径不传 effort 的情况）。"""
        no_effort = {"reasoning": {"enabled": True}}
        result = adapt_reasoning_config(no_effort, "https://api.deepseek.com/v1")
        assert result["reasoning_effort"] == "medium"

    def test_missing_exclude_field(self):
        """缺 exclude 字段时默认 False。"""
        no_exclude = {"reasoning": {"enabled": True, "effort": "high"}}
        result = adapt_reasoning_config(no_exclude, "https://openrouter.ai/api/v1")
        assert result["reasoning"]["exclude"] is False


# ============================================================
# get_default_reasoning_config 语义（2026-08-25 修复：enabled=False → 显式关闭）
# ============================================================

class TestDefaultReasoningConfigSemantics:
    """槽位 enabled=False 的旧语义是返回 None（不表态）——MiMo 等厂商服务端默认
    思考开，「不表态=开」（实证：spine-suggest 被隐藏思考烧光 800 预算返回空）。
    修复后返回显式关闭（与 REASONING_DISABLED 同形）。
    """

    def test_disabled_profile_returns_explicit_disable(self, monkeypatch):
        from backend.core import model_config as mc
        monkeypatch.setattr(mc, "get_model_profile", lambda role: {"enabled": False, "effort": "medium"})
        assert mc.get_default_reasoning_config("creative") == {"reasoning": {"enabled": False}}

    def test_missing_enabled_key_means_explicit_disable(self, monkeypatch):
        """profile 缺 enabled 键（从未配置过）同样显式关闭——不表态的时代结束。"""
        from backend.core import model_config as mc
        monkeypatch.setattr(mc, "get_model_profile", lambda role: {})
        assert mc.get_default_reasoning_config("default") == {"reasoning": {"enabled": False}}

    def test_enabled_profile_unchanged(self, monkeypatch):
        from backend.core import model_config as mc
        monkeypatch.setattr(
            mc, "get_model_profile",
            lambda role: {"enabled": True, "effort": "high", "exclude": True},
        )
        assert mc.get_default_reasoning_config("reasoning") == {
            "reasoning": {"enabled": True, "effort": "high", "exclude": True},
        }

    def test_explicit_disable_safe_for_openai_and_local(self):
        """零变化契约：显式关闭经适配层后，OpenAI/本地端点依然不发任何参数。"""
        disabled = {"reasoning": {"enabled": False}}
        assert adapt_reasoning_config(disabled, "https://api.openai.com/v1") is None
        assert adapt_reasoning_config(disabled, "http://localhost:11434/v1") is None

    def test_explicit_disable_reaches_default_on_vendors(self):
        """修复的目标：默认即开的厂商能收到显式关闭（MiMo 为代表）。"""
        disabled = {"reasoning": {"enabled": False}}
        assert adapt_reasoning_config(disabled, "https://api.xiaomimimo.com/v1") == {
            "thinking": {"type": "disabled"}
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

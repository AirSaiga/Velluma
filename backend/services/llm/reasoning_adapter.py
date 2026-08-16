# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

"""
LLM 推理参数 provider 适配层。

职责：把 Velluma 内部统一的推理参数中间表示
（{"reasoning": {"enabled": bool, "effort": "low"|"medium"|"high"|"max", ...}}）
转换成各 provider 原生的思考/推理参数结构，经 OpenAI SDK 的 extra_body 透传。

设计意图：
- Velluma 上层（get_default_reasoning_config / REASONING_DISABLED）只产出统一中间表示，
  不感知 provider 差异；本模块是唯一的「中间表示 → 原生参数」转换点。
- provider 识别基于 base_url 域名匹配（用户可自定义 base_url，域名是可用的信号）。
- 这是一个「尽力适配」层：各 provider 协议会随模型代际变化，本模块负责消除最常见的
  协议错配，不做绝对正确性保证。未识别的 provider 默认按 OpenRouter 协议透传
  （向后兼容历史行为）。

各 provider 原生协议（2026-08 调研）：
- DeepSeek：thinking.type（"enabled"|"disabled"）+ 顶层 reasoning_effort（low/high/max）
- OpenAI：顶层 reasoning_effort（low/medium/high/...），无独立开关，靠选模型
- OpenRouter：嵌套 reasoning.effort（low/medium/high/max），Velluma 原生设计目标
- Qwen/通义：enable_thinking（布尔）+ thinking_budget（整数 token）
- 火山豆包：thinking.type（"enabled"|"disabled"），无 effort 控制
- 本地（Ollama/vLLM/LM Studio）：推理参数支持不可靠/忽略，默认不发

副作用：无（纯函数）。改后即时生效（无需重建）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ============================================================
# Provider 识别
# ============================================================

# 已知 provider 类型
DEEPSEEK = "deepseek"
OPENAI = "openai"
OPENROUTER = "openrouter"
QWEN = "qwen"          # 阿里通义/Qwen（dashscope）
DOUBAO = "doubao"      # 火山引擎豆包（volces）
MIMO = "mimo"          # 小米 MiMo（api.xiaomimimo.com）
LOCAL = "local"        # 本地 OpenAI 兼容端点（Ollama/vLLM/LM Studio）
UNKNOWN = "unknown"

# base_url 域名 → provider 映射（按子串匹配，顺序敏感：更具体的放前面）
# 警示：dashscope（通义）和 volces（豆包）是不同厂商的域名，不能混。
_PROVIDER_DOMAIN_RULES: list[tuple[str, str]] = [
    ("api.deepseek.com", DEEPSEEK),
    ("api.openai.com", OPENAI),
    ("openrouter.ai", OPENROUTER),
    ("dashscope.aliyuncs.com", QWEN),
    ("ark.cn-beijing.volces.com", DOUBAO),
    ("volces.com", DOUBAO),
    ("xiaomimimo.com", MIMO),
    # 本地端点
    ("localhost", LOCAL),
    ("127.0.0.1", LOCAL),
    ("0.0.0.0", LOCAL),
]


def detect_provider(base_url: str, model: str = "") -> str:
    """按 base_url 域名识别 provider。

    Args:
        base_url: 模型配置里的 base_url（如 "https://api.deepseek.com/v1"）
        model: 模型名（当前未参与识别，保留参数供后续按模型名细分）

    Returns:
        provider 类型字符串（DEEPSEEK/OPENAI/OPENROUTER/QWEN/DOUBAO/LOCAL/UNKNOWN）
    """
    if not base_url:
        return UNKNOWN
    # 提取域名（去掉协议、端口、路径），小写匹配
    try:
        parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
        host = (parsed.hostname or "").lower()
    except Exception:
        host = base_url.lower()

    for domain_fragment, provider in _PROVIDER_DOMAIN_RULES:
        if domain_fragment in host:
            return provider
    return UNKNOWN


# ============================================================
# Effort 统一映射
# ============================================================

# 统一 effort 档位
EFFORT_LOW = "low"
EFFORT_MEDIUM = "medium"
EFFORT_HIGH = "high"
EFFORT_MAX = "max"
_VALID_EFFORTS = {EFFORT_LOW, EFFORT_MEDIUM, EFFORT_HIGH, EFFORT_MAX}

# Qwen thinking_budget（token 数）按 effort 档位估算。
# 依据：Qwen3 thinking 模式典型预算范围；max 对应较大预算。
# 设计意图：Qwen 没有 effort 枚举，只有 token 预算，这里把档位折算成具体数值。
_EFFORT_TO_QWEN_BUDGET: Dict[str, int] = {
    EFFORT_LOW: 2048,
    EFFORT_MEDIUM: 8192,
    EFFORT_HIGH: 16384,
    EFFORT_MAX: 32768,
}


def _normalize_effort(effort: Optional[str]) -> str:
    """把 effort 规范化到 low/medium/high/max；无效值回退 medium。"""
    if effort and effort in _VALID_EFFORTS:
        return effort
    return EFFORT_MEDIUM


# ============================================================
# 中间表示解析
# ============================================================

def _parse_intermediate(reasoning_config: dict) -> tuple[bool, str, bool]:
    """从统一中间表示 {"reasoning": {...}} 解析出 (enabled, effort, exclude)。

    兼容两种输入：
    - REASONING_DISABLED = {"reasoning": {"enabled": False}}
    - get_default_reasoning_config 产出 = {"reasoning": {"enabled": True, "effort": ..., "exclude": ...}}
    - 连接测试自定义 = {"reasoning": {"enabled": True, "effort": ...}}（可能缺 exclude）

    返回 (enabled, effort_normalized, exclude)。
    """
    inner = reasoning_config.get("reasoning", {})
    if not isinstance(inner, dict):
        # 非预期结构，当作「关闭」处理（保守，不发参数）
        return False, EFFORT_MEDIUM, False
    enabled = bool(inner.get("enabled", False))
    effort = _normalize_effort(inner.get("effort"))
    exclude = bool(inner.get("exclude", False))
    return enabled, effort, exclude


# ============================================================
# 主适配函数
# ============================================================

def adapt_reasoning_config(
    reasoning_config: Optional[dict],
    base_url: str,
    model: str = "",
) -> Optional[dict]:
    """把统一推理参数中间表示转换成 provider 原生结构。

    Args:
        reasoning_config: 统一中间表示 dict（通常是 get_default_reasoning_config
            或 REASONING_DISABLED 的返回值）。None 时直接返回 None（不发）。
        base_url: 当前调用的 base_url，用于识别 provider。
        model: 模型名（保留供后续按模型细分）。

    Returns:
        转换后的 dict（放进 OpenAI SDK 的 extra_body），或 None（不发任何推理参数）。

    设计说明：
    - None 输入 → None 输出（上层 client.py 的 if 判断已过滤，这里防御性处理）。
    - 各 provider 的 enabled=False 策略不同：DeepSeek/豆包/Qwen 能显式关闭，
      OpenAI 无独立开关（靠选模型），local 默认不发。
    - 未识别 provider（unknown）默认按 OpenRouter 协议透传，向后兼容历史行为。
    """
    if not reasoning_config:
        return None

    enabled, effort, _exclude = _parse_intermediate(reasoning_config)
    provider = detect_provider(base_url, model)

    if provider == DEEPSEEK:
        # DeepSeek：thinking.type 控制开关，reasoning_effort 控制强度。
        # 关键修复：DeepSeek 不认 OpenRouter 的 reasoning.enabled，必须用 thinking.type。
        result: Dict[str, Any] = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if enabled:
            # effort 仅在开启时有意义；DeepSeek 认 low/high/max（medium 透传由 provider 裁决）
            result["reasoning_effort"] = effort
        return result

    if provider == OPENAI:
        # OpenAI：无独立思考开关（靠选 o1/o3/gpt-5 等推理模型）。
        # enabled=False 时不发任何参数（OpenAI 非推理模型收到 reasoning_effort 会报错）。
        if not enabled:
            return None
        # reasoning_effort 是 OpenAI Chat Completions 的顶层 body 参数，
        # 通过 extra_body 透传（SDK 会合并到请求体顶层）。
        return {"reasoning_effort": effort}

    if provider == OPENROUTER:
        # OpenRouter：Velluma 的原生设计目标，协议本身即统一中间表示，原样透传。
        return {
            "reasoning": {
                "enabled": enabled,
                "effort": effort if enabled else EFFORT_MEDIUM,
                "exclude": _exclude,
            }
        }

    if provider == QWEN:
        # Qwen/通义：enable_thinking（布尔）+ thinking_budget（整数 token）。
        # 两者同一 extra_body 内组合使用；关闭时只发 enable_thinking=False。
        result = {"enable_thinking": enabled}
        if enabled:
            result["thinking_budget"] = _EFFORT_TO_QWEN_BUDGET.get(effort, 8192)
        return result

    if provider == DOUBAO:
        # 火山豆包：thinking.type 控制开关，原生无 effort 控制。
        # （部分较新 Seed 2.0 模型在网关层认 reasoning_effort，但火山原生协议以 thinking.type 为准）
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}

    if provider == MIMO:
        # 小米 MiMo（api.xiaomimimo.com）：实测（2026-08-16）认 DeepSeek 风格 thinking.type；
        # OpenRouter 的 reasoning.enabled 与 Qwen 的 enable_thinking 均被静默忽略——
        # 推理继续烧 token 预算，小预算调用（速记解析 max_tokens=800）finish=length 空输出。
        # effort 档位未验证支持，保守不发。
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}

    if provider == LOCAL:
        # 本地 OpenAI 兼容端点（Ollama/vLLM/LM Studio）：推理参数支持不可靠/忽略。
        # 默认不发，避免触发不可预期行为（vLLM 可能容忍、LM Studio 静默忽略、Ollama 行为不定）。
        return None

    # unknown：默认按 OpenRouter 协议透传（向后兼容——Velluma 历史行为即 OpenRouter 协议）
    return {
        "reasoning": {
            "enabled": enabled,
            "effort": effort if enabled else EFFORT_MEDIUM,
            "exclude": _exclude,
        }
    }

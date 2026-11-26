# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
LLM 推理参数 provider 适配层。

职责：把 Velluma 内部统一的推理参数中间表示
（{"reasoning": {"enabled": bool, "effort": "low"|"medium"|"high"|"max", ...}}）
转换成各 provider 原生的思考/推理参数结构，经 OpenAI SDK 的 extra_body 透传。

设计意图：
- Velluma 上层（get_default_reasoning_config / REASONING_DISABLED）只产出统一中间表示，
  不感知 provider 差异；本模块是唯一的「中间表示 → 原生参数」转换点。
- provider 识别（detect_provider）与厂商档案在 vendor_profiles.py 定义（2026-08-28
  五厂商调研定稿，docs/model-vendor-matrix.md），本模块 import 并 re-export 保持兼容。
- 这是一个「尽力适配」层：各 provider 协议会随模型代际变化，本模块负责消除最常见的
  协议错配，不做绝对正确性保证。未识别的 provider 默认按 OpenRouter 协议透传
  （向后兼容历史行为）。

各 provider 原生思考协议（2026-08-28 调研，docs/model-vendor-matrix.md）：
- DeepSeek V4：thinking.type（enabled/disabled）+ 顶层 reasoning_effort（low/high/max）；默认开
- Kimi：k2.6/k2.5 thinking.type 同上；**k3 无 thinking 参数**只有顶层 reasoning_effort
  （low/high/max，恒思考）；k2.7-code 只认 enabled（恒思考）——强制思考模型收到
  「关闭」请求时一律不发参数（发 disabled 会 400 或无效）
- 智谱 GLM：thinking.type + clear_thinking；reasoning_effort 仅 5.2+（low/high/max）；
  **glm-5.3 系强制思考，disabled 报错**——同样转不发参数
- OpenAI：顶层 reasoning_effort（low/medium/high），无独立开关，靠选模型
- OpenRouter：嵌套 reasoning.effort（low/medium/high/max），Velluma 原生设计目标
- Qwen/通义：enable_thinking（布尔）+ thinking_budget（整数 token）
- 火山豆包：thinking.type（enabled/disabled），无 effort 控制
- 小米 MiMo：thinking.type（唯一方言，实测+官方双证）；无 effort/budget 字段
- 本地（Ollama/vLLM/LM Studio）：关闭态发 reasoning_effort:"none"（Ollama /v1
  实测有效——思考默认开的本地模型不关=预算被 reasoning_content 烧光零产出）；
  开启态不发（档位映射未实测）

副作用：无（纯函数）。改后即时生效（无需重建）。
"""
from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

from backend.services.llm.vendor_profiles import (
    DEEPSEEK, GLM, KIMI, MIMO, OPENAI, OPENROUTER, QWEN, DOUBAO, LOCAL, UNKNOWN,
    detect_provider,
    get_vendor_profile,
    match_model_rule,
)

logger = logging.getLogger(__name__)


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
_EFFORT_TO_QWEN_BUDGET: dict = {
    EFFORT_LOW: 2048,
    EFFORT_MEDIUM: 8192,
    EFFORT_HIGH: 16384,
    EFFORT_MAX: 32768,
}

# effort 白名单外的就近映射（DeepSeek/GLM/Kimi 只认 low/high/max → medium 归 high；
# OpenAI 不认 max → max 归 high）。找不到映射时回退白名单最后一档。
_EFFORT_FALLBACK = {
    EFFORT_MEDIUM: EFFORT_HIGH,
    EFFORT_MAX: EFFORT_HIGH,
    "xhigh": EFFORT_MAX,
    "minimal": EFFORT_LOW,
}

# 厂商级 effort 白名单（模型级规则优先；None=不约束透传）
_VENDOR_EFFORT_WHITELIST = {
    OPENAI: (EFFORT_LOW, EFFORT_MEDIUM, EFFORT_HIGH),  # max 会 400，归一为 high
}


def _normalize_effort(effort: Optional[str]) -> str:
    """把 effort 规范化到 low/medium/high/max；无效值回退 medium。"""
    if effort and effort in _VALID_EFFORTS:
        return effort
    return EFFORT_MEDIUM


def _effort_for_provider(provider: str, model: str, effort: str) -> str:
    """按厂商/模型 effort 白名单归一档位。

    模型级规则（vendor_profiles.ModelRule.effort_values，如 deepseek-*/glm-5.2*/
    kimi-k3 只认 low/high/max）优先；无模型规则时查厂商白名单；都无则透传。
    """
    allowed = None
    rule = match_model_rule(get_vendor_profile(provider), model)
    if rule is not None and rule.effort_values:
        allowed = rule.effort_values
    else:
        allowed = _VENDOR_EFFORT_WHITELIST.get(provider)
    if allowed is None or effort in allowed:
        return effort
    mapped = _EFFORT_FALLBACK.get(effort, allowed[-1])
    logger.info(
        "[LLM] effort=%s 不在 %s/%s 白名单 %s，归一为 %s",
        effort, provider, model, list(allowed), mapped,
    )
    return mapped


# ============================================================
# 中间表示解析
# ============================================================

def _parse_intermediate(reasoning_config: dict) -> tuple:
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
        model: 模型名（强制思考/effort 白名单等模型级规则的判据）。

    Returns:
        转换后的 dict（放进 OpenAI SDK 的 extra_body），或 None（不发任何推理参数）。

    设计说明：
    - None 输入 → None 输出（上层 client.py 的 if 判断已过滤，这里防御性处理）。
    - 各 provider 的 enabled=False 策略不同：DeepSeek/GLM/Kimi/豆包/Qwen 能显式关闭，
      OpenAI 无独立开关（靠选模型），local 默认不发。
    - **强制思考模型**（glm-5.3*、kimi-k3、kimi-k2.7-code）：收到「关闭」请求时
      返回 None 不发参数——这些模型 disabled 会 400（GLM 5.3 官方迁移指南）或
      根本没有关闭通道（K3 恒思考），「不发」是唯一不发错的形态。
    - 未识别 provider（unknown）默认按 OpenRouter 协议透传，向后兼容历史行为。
    """
    if not reasoning_config:
        return None

    enabled, effort, _exclude = _parse_intermediate(reasoning_config)
    provider = detect_provider(base_url, model)
    rule = match_model_rule(get_vendor_profile(provider), model)

    if provider == DEEPSEEK:
        # DeepSeek：thinking.type 控制开关，reasoning_effort 控制强度。
        # 关键修复：DeepSeek 不认 OpenRouter 的 reasoning.enabled，必须用 thinking.type。
        result: dict = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if enabled:
            # effort 仅在开启时有意义；low/high/max（medium 经白名单归一为 high）
            result["reasoning_effort"] = _effort_for_provider(provider, model, effort)
        return result

    if provider == GLM:
        # 智谱：thinking.type（4.5+）；reasoning_effort 仅 5.2+（模型规则标记）。
        if rule is not None and rule.force_thinking:
            # glm-5.3 系强制思考：disabled 报错（官方迁移指南），只能不发（服务端强制开）
            if not enabled:
                logger.info("[LLM] %s 强制思考（无法关闭），跳过关闭请求按服务端默认执行", model)
                return None
            result = {"thinking": {"type": "enabled"}}
            if rule.effort_values:
                result["reasoning_effort"] = _effort_for_provider(provider, model, effort)
            return result
        result = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        if enabled and rule is not None and rule.effort_values:
            result["reasoning_effort"] = _effort_for_provider(provider, model, effort)
        return result

    if provider == KIMI:
        # Kimi：方言按模型分三族（2026-08-28 调研）。
        model_lower = (model or "").lower()
        if model_lower.startswith("moonshot-v1"):
            # 老系非思考模型（8-31 下线中）：无思考参数，不发
            return None
        if rule is not None and rule.force_thinking:
            if not enabled:
                # k3 恒思考 / k2.7-code 只认 enabled：关不掉，不发参数
                logger.info("[LLM] %s 强制思考（无法关闭），跳过关闭请求按服务端默认执行", model)
                return None
            if rule.effort_values:
                # k3：无 thinking 参数，只有顶层 reasoning_effort（low/high/max）
                return {"reasoning_effort": _effort_for_provider(provider, model, effort)}
            return {"thinking": {"type": "enabled"}}
        # k2.6 / k2.5：thinking.type 开关（keep 不发——默认不保留思考，单轮调用语义）
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}

    if provider == OPENAI:
        # OpenAI：无独立思考开关（靠选 o1/o3/gpt-5 等推理模型）。
        # enabled=False 时不发任何参数（OpenAI 非推理模型收到 reasoning_effort 会报错）。
        if not enabled:
            return None
        # reasoning_effort 是 OpenAI Chat Completions 的顶层 body 参数，
        # 通过 extra_body 透传（SDK 会合并到请求体顶层）；max 不在枚举内，归一。
        return {"reasoning_effort": _effort_for_provider(provider, model, effort)}

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
        # 小米 MiMo（api.xiaomimimo.com）：认 DeepSeek 风格 thinking.type；
        # OpenRouter 的 reasoning.enabled 与 Qwen 的 enable_thinking 均被静默忽略——
        # 推理继续烧 token 预算，小预算调用（速记解析 max_tokens=800）finish=length 空输出。
        # effort 档位未验证支持，保守不发。
        return {"thinking": {"type": "enabled" if enabled else "disabled"}}

    if provider == LOCAL:
        # 本地 OpenAI 兼容端点（Ollama/vLLM/LM Studio）。
        # 关闭态（2026-09-15 实测 qwen3.5:9b）：Ollama /v1 认 OpenAI 标准
        # reasoning_effort:"none"——其余关思考通路全数无效（chat_template_kwargs、
        # Qwen3 老系 /no_think 软开关、/v1 think 字段均被无视）。思考默认开的
        # 本地模型会把 completion 预算全烧在 reasoning_content 上（1600/2000/
        # 8000 三档预算实测全灭、content 恒空），不发参数=零产出，必须显式关。
        # LM Studio 静默忽略该参数、vLLM 容忍（vendor notes 既有结论）。
        # 开启态仍不发：effort→预算档位映射未实测，宁可不发不乱发。
        if not enabled:
            return {"reasoning_effort": "none"}
        return None

    # unknown：默认按 OpenRouter 协议透传（向后兼容——Velluma 历史行为即 OpenRouter 协议）。
    # 关闭态例外（2026-08-26 修复）：历史行为是「不发参数」（585784c 语义修复前上游
    # 返回 None）；对不认 OpenRouter 协议的未知网关该参数本就无效，而严格校验 body
    # 的网关会 400（全槽位调用失败）。需要显式关闭的服务端默认思考厂商，正路是往
    # vendor_profiles._PROVIDER_DOMAIN_RULES 加识别分支（MiMo/Kimi 先例——实测认证
    # 的协议才接）。
    if not enabled:
        return None
    return {
        "reasoning": {
            "enabled": enabled,
            "effort": effort if enabled else EFFORT_MEDIUM,
            "exclude": _exclude,
        }
    }

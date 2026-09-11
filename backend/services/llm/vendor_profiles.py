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
LLM 厂商能力档案（2026-08-28 五厂商调研定稿；2026-09-10 DeepSeek V4.1 Flash 修订）。

唯一事实源：docs/model-vendor-matrix.md。职责三件事：
1. **provider 识别**（detect_provider）：base_url 域名 → 厂商 id。
   reasoning_adapter 从这里 import（保持自身 re-export 向后兼容）。
2. **采样参数整形**（shape_sampling_params）：按厂商/模型规则在发送前
   删掉或钳制会被拒/无效的采样参数——Kimi K 系传 temperature 直接 400、
   DeepSeek 双 penalty 已废弃、GLM 温度上限 1.0 等。这是「前置整形」，
   client.py 的 400 自适应缓存（_PARAM_LOCK_CACHE）降级为最后防线。
3. **厂商目录**（vendor_catalog）：喂前端设置弹窗（选厂商自动填 base_url、
   模型候选、能力提示），GET /system/model-catalog 消费。

设计纪律：
- 档案数据是「截至 2026-09-10 的官方文档实证」，厂商协议随代际变化——
  改这里必须同步改 docs/model-vendor-matrix.md 并跑 test_vendor_profiles.py。
- 不做绝对正确性保证：shape 之后仍可能有未知锁定，由自适应层兜底。
- 纯函数、零副作用、零 LLM。

副作用：无。改后即时生效（无需重建）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

# ============================================================
# Provider id（权威定义；reasoning_adapter re-export 保持兼容）
# ============================================================

DEEPSEEK = "deepseek"
GLM = "glm"            # 智谱（open.bigmodel.cn）
KIMI = "kimi"          # 月之暗面（api.moonshot.cn）
MIMO = "mimo"          # 小米（api.xiaomimimo.com）
OPENAI = "openai"
OPENROUTER = "openrouter"
QWEN = "qwen"          # 阿里通义/百炼（dashscope + 新版 maas 域名）
DOUBAO = "doubao"      # 火山引擎豆包（volces）
LOCAL = "local"        # 本地 OpenAI 兼容端点（Ollama/vLLM/LM Studio）
UNKNOWN = "unknown"

# base_url 域名 → provider（子串匹配，顺序敏感：更具体的放前面）
_PROVIDER_DOMAIN_RULES: List[Tuple[str, str]] = [
    ("api.deepseek.com", DEEPSEEK),
    ("open.bigmodel.cn", GLM),
    ("bigmodel.cn", GLM),
    ("moonshot.cn", KIMI),
    ("moonshot.ai", KIMI),
    ("api.xiaomimimo.com", MIMO),
    ("xiaomimimo.com", MIMO),
    ("api.openai.com", OPENAI),
    ("openrouter.ai", OPENROUTER),
    ("dashscope.aliyuncs.com", QWEN),
    ("maas.aliyuncs.com", QWEN),      # 百炼新版业务空间域名
    ("ark.cn-beijing.volces.com", DOUBAO),
    ("volces.com", DOUBAO),
    # 本地端点
    ("localhost", LOCAL),
    ("127.0.0.1", LOCAL),
    ("0.0.0.0", LOCAL),
]


def detect_provider(base_url: str, model: str = "") -> str:
    """按 base_url 域名识别 provider（model 保留供未来按模型名细分）。"""
    if not base_url:
        return UNKNOWN
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
# 厂商能力档案
# ============================================================

@dataclass(frozen=True)
class ModelRule:
    """模型级覆盖规则（同一厂商内不同模型族的差异）。

    prefixes: 模型名前缀命中即生效（大小写不敏感）。
    locked_sampling: 该模型族采样参数完全不发（schema 不含，传了 400）。
    force_thinking: 服务端强制思考——「关闭」请求转为不发思考参数
      （发 disabled 会 400 或无效；glm-5.3 / kimi-k3 / kimi-k2.7-code）。
    effort_values: 该模型族认的 effort 枚举（None=跟随厂商默认策略）。
    """
    prefixes: Tuple[str, ...]
    locked_sampling: bool = False
    force_thinking: bool = False
    effort_values: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class VendorProfile:
    """厂商级档案：采样范围/惩罚支持/思考方言说明/前端目录数据。"""
    id: str
    label: str
    base_url: str
    docs_url: str
    # 采样参数取值范围（None = OpenAI 通行 [0,2]/(0,1] 不钳制）
    temperature_range: Optional[Tuple[float, float]] = None
    top_p_range: Optional[Tuple[float, float]] = None
    # 双 penalty：False = 一律不发（DeepSeek 已废弃 / GLM 现行文档未定义 / Kimi K 系 schema 不含）
    supports_penalties: bool = True
    # 思考态/非思考态分别静默无效、发送前删除的采样参数
    # （2026-09-10 DeepSeek 文档：思考态 temperature 无效、非思考态 top_p 恒 1.0 忽略；
    #   MiMo 思考态静默锁 1.0/0.95——两组都是「发了也白发」）
    thinking_drops: Tuple[str, ...] = ()
    non_thinking_drops: Tuple[str, ...] = ()
    notes: Tuple[str, ...] = ()
    models: Tuple[Dict, ...] = field(default_factory=tuple)
    model_rules: Tuple[ModelRule, ...] = field(default_factory=tuple)


VENDORS: Dict[str, VendorProfile] = {
    DEEPSEEK: VendorProfile(
        id=DEEPSEEK, label="DeepSeek", base_url="https://api.deepseek.com",
        docs_url="https://api-docs.deepseek.com",
        temperature_range=(0.0, 2.0), top_p_range=(0.0, 1.0),
        supports_penalties=False,
        thinking_drops=("temperature",), non_thinking_drops=("top_p",),
        notes=("峰谷定价：工作日 9-12/14-18 点为高峰（2 倍价），夜间与周末半价。",
               "思考默认开启；思考模式下 temperature 无效（top_p 生效，低于 0.95 会被抬升），关闭思考后温度才生效。"),
        models=(
            # 2026-09-10 V4.1 Flash 发布：规范 id 改 deepseek-flash（旧 v4-flash 名暂时路由到它）
            {"id": "deepseek-flash", "label": "V4.1 Flash（推荐·性价比）", "note": "原生多模态；1M 上下文/384K 输出；空闲档 ¥1/百万进 ¥4/百万出"},
            {"id": "deepseek-v4-pro", "label": "v4-pro（旗舰·下线倒计时）", "note": "09-14 12:00 起请求路由到 V4.1 Flash 并按其计费（至 V4.1 Pro 上线）"},
        ),
        model_rules=(
            # deepseek-chat / deepseek-reasoner 已于 2026-07-24 弃用；deepseek-v4-flash 已并入
            # deepseek-flash（旧名暂时路由）——目录只给现行规范名
            ModelRule(prefixes=("deepseek-",), effort_values=("low", "high", "max")),
        ),
    ),
    GLM: VendorProfile(
        id=GLM, label="智谱 GLM", base_url="https://open.bigmodel.cn/api/paas/v4",
        docs_url="https://docs.bigmodel.cn",
        temperature_range=(0.0, 1.0), top_p_range=(0.01, 1.0),
        supports_penalties=False,
        notes=("temperature 上限 1.0（比别家严，已自动钳制）。",
               "glm-4.7-flash / glm-4.5-flash 完全免费，可零成本试写。"),
        models=(
            {"id": "glm-5.2", "label": "GLM-5.2（推荐·1M 上下文）", "note": "MIT 开源；$1.4/$4.4 每百万"},
            {"id": "glm-5.3", "label": "GLM-5.3（旗舰·强制思考）", "note": "思考无法关闭；2026-08-19 发布"},
            {"id": "glm-5.1", "label": "GLM-5.1", "note": "200K 上下文；中文长篇创作者口碑偏好"},
            {"id": "glm-4.7", "label": "GLM-4.7", "note": "上一代标准档"},
            {"id": "glm-4.7-flash", "label": "GLM-4.7-Flash（免费）", "note": "完全免费，200K 上下文；零成本试写首选"},
        ),
        model_rules=(
            ModelRule(prefixes=("glm-5.3",), force_thinking=True, effort_values=("low", "high", "max")),
            ModelRule(prefixes=("glm-5.2",), effort_values=("low", "high", "max")),
        ),
    ),
    KIMI: VendorProfile(
        id=KIMI, label="Kimi（月之暗面）", base_url="https://api.moonshot.cn/v1",
        docs_url="https://platform.kimi.com",
        temperature_range=(0.0, 1.0), top_p_range=(0.0, 1.0),
        supports_penalties=False,
        notes=("K 系模型采样参数由服务端全锁（温度/_top_p 传了报错）——本应用自动不发，无需配置。",
               "kimi-k2.6 深度思考默认开启；写作槽关闭思考后输出更稳更快。"),
        models=(
            {"id": "kimi-k2.6", "label": "K2.6（推荐·写作口碑佳）", "note": "256K；¥1.1/¥6.5/¥27 每百万（命中/未命中/输出）"},
            {"id": "kimi-k3", "label": "K3（旗舰·恒思考·贵）", "note": "1M；¥2/¥20/¥100 每百万；思考不可关"},
            {"id": "kimi-k2.7-code", "label": "K2.7-Code", "note": "256K；思考不可关，偏代码场景"},
        ),
        model_rules=(
            # ⚠ match_model_rule 取最长前缀命中：具体规则（k3/k2.7）必须自带 locked_sampling
            # k3：无 thinking 参数，只有顶层 reasoning_effort；恒思考
            ModelRule(prefixes=("kimi-k3",), locked_sampling=True, force_thinking=True,
                      effort_values=("low", "high", "max")),
            # k2.7-code：只认 enabled；恒思考
            ModelRule(prefixes=("kimi-k2.7",), locked_sampling=True, force_thinking=True),
            # K 系通用（k2.6/k2.5 等）：schema 不含采样参数（k2.6 思考态锁 1.0/非思考态锁 0.6）
            ModelRule(prefixes=("kimi-k",), locked_sampling=True),
        ),
    ),
    QWEN: VendorProfile(
        id=QWEN, label="通义千问 Qwen（百炼）", base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        docs_url="https://help.aliyun.com/zh/model-studio/",
        temperature_range=(0.0, 2.0), top_p_range=(0.0, 1.0),
        notes=("3.5+ 商业版默认开思考；经典版（qwen-plus/flash/turbo）默认关。",
               "API Key 按地域绑定：新业务空间域名需配同地域 Key，跨地域 401。"),
        models=(
            {"id": "qwen3.7-plus", "label": "qwen3.7-plus（推荐·主力）", "note": "1M；¥2/¥8 每百万（256K 内）"},
            {"id": "qwen3.8-max", "label": "qwen3.8-max（旗舰）", "note": "1M；¥12/¥36 每百万"},
            {"id": "qwen3.8-flash", "label": "qwen3.8-flash", "note": "1M；¥0.8/¥2.7 每百万"},
            {"id": "qwen3.7-flash", "label": "qwen3.7-flash（便宜档）", "note": "1M；32K 内 ¥0.2/¥0.8 每百万"},
            {"id": "qwen-flash", "label": "qwen-flash（最便宜）", "note": "128K 内 ¥0.15/¥1.5 每百万"},
        ),
        model_rules=(),
    ),
    MIMO: VendorProfile(
        id=MIMO, label="小米 MiMo", base_url="https://api.xiaomimimo.com/v1",
        docs_url="https://mimo.mi.com",
        temperature_range=(0.0, 1.5), top_p_range=(0.01, 1.0),
        thinking_drops=("temperature", "top_p"),
        notes=("思考模式下温度/top_p 被服务端静默锁为 1.0/0.95——本应用思考开启时自动不发采样参数。",
               "深度思考默认开启；小预算调用务必显式关闭（本应用已自动处理）。"),
        models=(
            {"id": "mimo-v2.5", "label": "MiMo-v2.5（推荐）", "note": "1M；¥1/¥2 每百万"},
            {"id": "mimo-v2.5-pro", "label": "MiMo-v2.5-pro", "note": "1M；¥3/¥6 每百万"},
        ),
        model_rules=(),
    ),
}


def get_vendor_profile(provider: str) -> Optional[VendorProfile]:
    return VENDORS.get(provider)


def match_model_rule(profile: Optional[VendorProfile], model: str) -> Optional[ModelRule]:
    """模型名前缀命中厂商内模型规则，**最长前缀优先**。

    规则表允许泛化前缀（kimi-k）与具体前缀（kimi-k3）并存——具体规则自带
    全部属性（locked_sampling 等不继承泛化规则），最长前缀命中保证具体规则
    不被泛化规则遮蔽。
    """
    if profile is None or not model:
        return None
    lowered = model.lower()
    best: Optional[ModelRule] = None
    best_len = -1
    for rule in profile.model_rules:
        for prefix in rule.prefixes:
            p = prefix.lower()
            if lowered.startswith(p) and len(p) > best_len:
                best = rule
                best_len = len(p)
    return best


# ============================================================
# 采样参数整形（发送前的前置防线）
# ============================================================

# 参与整形的四个采样参数（与 client._ADAPTIVE_PARAMS 同集）
_SAMPLING_PARAMS = ("temperature", "top_p", "frequency_penalty", "presence_penalty")


def shape_sampling_params(
    base_url: str,
    model: str,
    params: Dict,
    thinking_enabled: bool,
) -> Tuple[Dict, List[str]]:
    """按厂商/模型档案整形采样参数。

    Args:
        base_url / model: 当前调用的连接信息（识别厂商与模型规则）。
        params: 待发送参数 dict（只动 _SAMPLING_PARAMS 四键，其余原样）。
        thinking_enabled: 本次调用思考是否开启（思考锁采样的厂商据此删参数）。

    Returns:
        (shaped_params, dropped)——shaped 是可直接发送的新 dict；
        dropped 是被删除/钳制的参数名列表（供 trace/日志观测）。

    规则（docs/model-vendor-matrix.md §六）：
    - Kimi K 系：采样参数全删（schema 不含，传了 400）。
    - DeepSeek：双 penalty 全模式删；思考态删 temperature（无效）；
      非思考态删 top_p（恒 1.0 忽略；思考态 top_p 生效，下限 0.95 由服务端抬升，原样透传）。
    - MiMo：思考态删 temperature/top_p（静默锁 1.0/0.95，发了也白发）。
    - GLM：温度钳 ≤1.0；双 penalty 删（现行 API 未定义）。
    - Qwen：温度钳 <2.0、top_p 钳 ≤1.0。
    - 未识别厂商 / 本地：原样透传（自适应层兜底）。
    """
    provider = detect_provider(base_url, model)
    profile = get_vendor_profile(provider)
    if profile is None:
        return dict(params), []

    rule = match_model_rule(profile, model)
    shaped = dict(params)
    dropped: List[str] = []

    def _drop(key: str):
        if key in shaped:
            shaped.pop(key)
            dropped.append(key)

    def _clamp(key: str, lo: float, hi: float):
        val = shaped.get(key)
        if isinstance(val, (int, float)):
            clamped = min(max(float(val), lo), hi)
            if clamped != float(val):
                shaped[key] = clamped
                dropped.append(key)

    # 1. penalty 不支持的厂商：全模式删
    if not profile.supports_penalties:
        _drop("frequency_penalty")
        _drop("presence_penalty")

    # 2. 模型级采样锁（Kimi K 系）：采样参数全删
    if rule and rule.locked_sampling:
        for key in ("temperature", "top_p"):
            _drop(key)

    # 3. 思考态/非思考态分别静默无效的参数（DeepSeek/MiMo，2026-09-10 档案）
    for key in (profile.thinking_drops if thinking_enabled else profile.non_thinking_drops):
        _drop(key)

    # 4. 范围钳制（GLM 温度 ≤1.0 等）
    if profile.temperature_range:
        _clamp("temperature", *profile.temperature_range)
    if profile.top_p_range:
        _clamp("top_p", *profile.top_p_range)

    return shaped, dropped


# ============================================================
# 厂商目录（前端设置弹窗消费）
# ============================================================

# 无档案但可在前端预设 base_url 的通用端点（整形/思考适配走既有分支或 unknown 兜底）
_GENERIC_ENDPOINTS: Tuple[Dict, ...] = (
    {"id": OPENAI, "label": "OpenAI", "base_url": "https://api.openai.com/v1", "docs_url": "https://platform.openai.com/docs", "notes": (), "models": ()},
    {"id": OPENROUTER, "label": "OpenRouter（聚合）", "base_url": "https://openrouter.ai/api/v1", "docs_url": "https://openrouter.ai/docs", "notes": ("统一 reasoning 协议，一家 Key 调多家模型。",), "models": ()},
    {"id": LOCAL, "label": "本地端点（Ollama/vLLM 等）", "base_url": "http://localhost:11434/v1", "docs_url": "", "notes": ("推理参数支持不可靠，本应用对本地端点不发思考参数。",), "models": ()},
)


def vendor_catalog() -> List[Dict]:
    """厂商目录（GET /system/model-catalog 响应体）。

    条目：{id, label, base_url, docs_url, notes: [str], models: [{id, label, note}]}。
    前端语义：选厂商 → 自动填 base_url + 模型候选 datalist + 能力提示；
    模型名永远允许自由输入（目录只是候选，不是白名单）。
    """
    out: List[Dict] = []
    for profile in VENDORS.values():
        out.append({
            "id": profile.id,
            "label": profile.label,
            "base_url": profile.base_url,
            "docs_url": profile.docs_url,
            "notes": list(profile.notes),
            "models": [dict(m) for m in profile.models],
        })
    out.extend(dict(ep, notes=list(ep["notes"]), models=list(ep["models"])) for ep in _GENERIC_ENDPOINTS)
    return out

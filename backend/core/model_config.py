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
模型配置文件读取模块。

职责：
- 读取项目根目录下的 model_config.json
- 提供统一的模型配置访问接口

配置结构（V4.3）：
{
  "llm": {
    "reasoning": {
      "api_key": "...",
      "base_url": "...",
      "model": "...",
      "enabled": true | false,
      "effort": "medium",
      "exclude": false
    },
    "creative": {
      "api_key": "...",
      "base_url": "...",
      "model": "...",
      "enabled": false,
      "effort": "low",
      "exclude": false
    },
    "wash": {   // 可选：去 AI 味洗涤专用槽（2026-07 新增）
      ...       // 结构同上；缺失或不完整时洗涤回退到 creative 槽
    }
  },
  "embedding": {
    "api_key": "...",
    "base_url": "...",        // 可选；缺省回退 DashScope OpenAI 兼容端点
    "model": "text-embedding-v2",
    "dimensions": 1536,       // 向量维度，必须与数据库 schema 一致
    "follow_llm": false       // true=连接（api_key/base_url）跟随文本模型，忽略自管 Key/URL
  },
  "deai": {                   // 去AI味小模型（deai/ 子项目，2026-08-31 接入，实验）
    "enabled": false,         // 卡片舱幽灵短稿上屏前的「小模型抛光」开关
    "api_key": "...",         // 阿里云百炼 DashScope Key
    "model": "qwen3-4b-instruct-2507-78a06917f4ca",  // 部署后的 deployed_model（重训会变）
    "base_url": ""            // 留空 = DashScope 原生端点（调优模型不支持 OpenAI 兼容入口）
  },
  "proxy": {
    "enabled": true,
    "url": "http://127.0.0.1:4780"
  }
}

Deepseek 配置示例：
{
  "llm": {
    "reasoning": {
      "api_key": "sk-xxx",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-flash",
      "enabled": true,
      "effort": "medium",
      "exclude": false
    },
    "creative": {
      "api_key": "sk-xxx",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-flash",
      "enabled": true
    }
  }
}
"""

import json
import os
from typing import Dict, Optional

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "model_config.json")

# 内存缓存
_config_cache: Optional[Dict] = None

# base_url 为空时的硬编码兜底。provider 字段已删除，不再按厂商映射；
# 兜底值与 example.json 默认（DeepSeek）一致，用户应显式填写 base_url。
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"

# embedding.base_url 缺省兜底：阿里云 DashScope 的 OpenAI 兼容端点。
# 历史配置（只有 DashScope Key、无 base_url）经此零迁移切换到兼容协议，
# 同一 Key 在该端点上可直接调 text-embedding-v2/v3/v4。
DASHSCOPE_COMPAT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# deai 小模型（去AI味改写，deai/ 子项目）的 DashScope 原生生成端点兜底。
# 百炼调优模型只认原生接口，OpenAI 兼容入口报 model_not_found
# （deai/docs/usage.md §2 实测踩坑，勿改成 compatible-mode）。
DASHSCOPE_NATIVE_GENERATION_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
)
# 2026-08-31 v1 部署的 deployed_model（deai/docs/archive.md §3）；
# 重训/重部署后此 ID 会变，用百炼控制台或部署管理接口查新值。
DEFAULT_DEAI_MODEL = "qwen3-4b-instruct-2507-78a06917f4ca"


def _load_config() -> Dict:
    """从文件加载配置（带缓存）"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"模型配置文件不存在: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _config_cache = json.load(f)

    return _config_cache


def get_model_config() -> Dict:
    """获取完整模型配置"""
    return _load_config()


def get_llm_config() -> Dict:
    """获取完整 LLM 配置对象（含 reasoning / creative）"""
    config = _load_config()
    return config.get("llm", {})


def get_model_profile(model_type: str = "default") -> Dict:
    """
    获取指定模型类型的独立配置（api_key / base_url / model / enabled / effort / exclude）。

    Args:
        model_type: "reasoning" | "creative" | "wash" | "default"

    Returns:
        该模型类型对应的完整配置字典

    设计说明：
    - "default" 映射到 "reasoning" 配置，与旧版行为一致
      （旧版中 model_type="default" 默认使用 reasoning_model）
    - "reasoning"（分析模型）：读取 llm.reasoning 配置；槽位不完整（缺
      model/api_key）时，连接三件套（api_key/base_url/model）整体回退到
      creative，使「分析模型留空→自动用写作模型」在连接层面成立。
      enabled/effort/exclude 仍保留 reasoning 自己的语义（不随 creative 变），
      避免「写作模型关 thinking 的配置意外影响分析任务」。
      前端设置面板据此承诺「分析模型留空则自动使用与写作模型相同的配置」。
    - "wash"（洗涤槽，去 AI 味专用）：读取 llm.wash 配置；
      槽位缺失或不完整（缺 model/api_key）时整体回退到 creative 配置，
      保证未配置 wash 的用户行为与旧版完全一致。
    """
    llm_cfg = get_llm_config()
    if model_type in ("reasoning", "default"):
        key = "reasoning"
    elif model_type == "wash":
        key = "wash"
    else:
        key = "creative"
    profile = llm_cfg.get(key, {})

    # wash 槽未配置/不完整 → 整体回退 creative（编辑任务与正文同源，行为同旧版）
    if model_type == "wash" and not (profile.get("model") and profile.get("api_key")):
        profile = llm_cfg.get("creative", {})

    # reasoning 槽不完整 → 仅借用 creative 的连接三件套，保留自身 thinking 语义。
    # 场景：前端设置面板允许「分析模型留空→自动用写作模型」；此时连接必须复用
    # creative 的 api_key/base_url/model 才能发请求，但 reasoning 任务
    # 的 thinking 开关（enabled/effort/exclude）不应被 creative 的配置污染。
    if model_type in ("reasoning", "default") and not (profile.get("model") and profile.get("api_key")):
        creative_profile = llm_cfg.get("creative", {})
        if creative_profile.get("model") and creative_profile.get("api_key"):
            profile = {
                **profile,
                "api_key": creative_profile.get("api_key", ""),
                "base_url": creative_profile.get("base_url", ""),
                "model": creative_profile.get("model", ""),
            }

    return {
        "api_key": profile.get("api_key", ""),
        "base_url": profile.get("base_url", "") or DEFAULT_BASE_URL,
        "model": profile.get("model", ""),
        "enabled": profile.get("enabled", False),
        "effort": profile.get("effort", "medium"),
        "exclude": profile.get("exclude", False),
    }


def has_dedicated_wash_profile() -> bool:
    """是否配置了独立的洗涤模型槽（llm.wash 含 model + api_key）。

    业务场景：de_ai_washer 据此决定洗涤调用的 thinking 配置——
    独立槽尊重其 enabled/effort；回退 creative 时强制关闭 thinking
    （编辑任务不需要深度思考，避免继承 creative 的 effort=max 拖慢洗涤）。
    """
    profile = get_llm_config().get("wash", {})
    return bool(profile.get("model") and profile.get("api_key"))


def get_embedding_config() -> Dict:
    """获取 Embedding 配置"""
    config = _load_config()
    return config.get("embedding", {})


def get_embedding_dimensions() -> int:
    """
    获取 Embedding 向量维度配置。

    Returns:
        向量维度，默认 1536（兼容 text-embedding-v2）
    """
    emb_config = get_embedding_config()
    return emb_config.get("dimensions", 1536)


def get_embedding_follow_source() -> Dict:
    """follow_llm 模式下 embedding 将继承的文本模型连接。

    creative 槽优先、缺 Key 回退 reasoning 槽（reasoning 自身不完整时会再借
    creative 的连接三件套，见 get_model_profile）；两槽均未配置时 api_key 为空，
    source 仍标 "creative" 便于 UI 提示该配哪个槽。
    """
    for role in ("creative", "reasoning"):
        profile = get_model_profile(role)
        if profile.get("api_key"):
            return {
                "api_key": profile["api_key"],
                "base_url": profile["base_url"],
                "source": role,
            }
    return {"api_key": "", "base_url": "", "source": "creative"}


def get_embedding_connection() -> Dict:
    """
    解析 Embedding 的有效连接配置（调用侧唯一入口）。

    Returns:
        {api_key, base_url, model, dimensions, follow_llm, source}
        source 标明连接来源："self"（embedding 自管 Key）/ "creative" /
        "reasoning"（跟随文本模型时实际命中的槽位）。
        api_key 为空 = 未配置（调用方据此走结构化+词法默认记忆流）。

    follow_llm=true 时连接（api_key + base_url）跟随文本模型（解析规则见
    get_embedding_follow_source）；embedding 自管的 api_key/base_url
    被忽略，model/dimensions 仍取 embedding 自己的——向量模型名与文本模型
    名无关，必须单独配。
    """
    emb = get_embedding_config()
    follow = bool(emb.get("follow_llm", False))
    connection = {
        "api_key": "",
        "base_url": "",
        "model": emb.get("model", "text-embedding-v2"),
        "dimensions": emb.get("dimensions", 1536),
        "follow_llm": follow,
        "source": "self",
    }
    if follow:
        followed = get_embedding_follow_source()
        connection["api_key"] = followed["api_key"]
        connection["base_url"] = followed["base_url"]
        connection["source"] = followed["source"]
        return connection
    connection["api_key"] = emb.get("api_key", "")
    connection["base_url"] = emb.get("base_url", "") or DASHSCOPE_COMPAT_BASE_URL
    return connection


def get_deai_config() -> Dict:
    """获取 deai 去AI味小模型配置（deai/ 子项目，docs/deai-integration.md）。

    结构：{enabled, api_key, model, base_url}。「已配置」判据 = enabled 且
    api_key 且 model 三者齐备（调用方 services/deai/client.py 的
    is_deai_configured）；未配置时运行时直通零调用——幽灵文本逐字节
    零变化（零变化契约，同 embedding 未配置短路）。

    base_url 默认 DashScope 原生 text-generation 端点：百炼调优模型
    实测不支持 OpenAI 兼容入口（deai/docs/usage.md §2 踩坑记录）。
    model 默认 2026-08-31 部署的 deployed_model，重训/重部署后会变
    （百炼控制台或 GET /api/v1/deployments 查询新值后改配置）。
    """
    deai = _load_config().get("deai", {})
    return {
        "enabled": bool(deai.get("enabled", False)),
        "api_key": deai.get("api_key", ""),
        "model": deai.get("model", "") or DEFAULT_DEAI_MODEL,
        "base_url": deai.get("base_url", "") or DASHSCOPE_NATIVE_GENERATION_URL,
    }


def update_deai_config(updates: Dict):
    """合并更新 deai 配置节并持久化（仅更新出现的字段，其余保持原值）。"""
    config = _load_config()
    deai = config.setdefault("deai", {})
    deai.update(updates)
    _write_config(config)


def get_proxy_config() -> dict:
    """获取代理配置"""
    config = _load_config()
    proxy = config.get("proxy", {})
    return {
        "enabled": proxy.get("enabled", True),
        "url": proxy.get("url", "http://127.0.0.1:4780"),
    }


def set_proxy_config(enabled: bool, url: str):
    """更新代理配置并持久化到文件"""
    config = _load_config()
    config["proxy"] = {
        "enabled": enabled,
        "url": url,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    _invalidate_cache()


def _write_config(config: Dict):
    """写回配置文件并清除缓存"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    _invalidate_cache()


def update_llm_profile(role: str, updates: Dict):
    """
    合并更新指定 LLM profile（reasoning / creative）并持久化。

    副作用：仅更新 updates 中出现的字段，未提供的字段（如 exclude）保持原值。
    """
    if role not in ("reasoning", "creative", "wash"):
        raise ValueError(f"未知的 LLM 角色: {role}")
    config = _load_config()
    profile = config.setdefault("llm", {}).setdefault(role, {})
    profile.update(updates)
    _write_config(config)


def update_embedding_config(updates: Dict):
    """
    合并更新 Embedding 配置并持久化。

    警示：dimensions 变更后需重启后端，启动迁移会删列重建向量数据（破坏性）。
    """
    config = _load_config()
    embedding = config.setdefault("embedding", {})
    embedding.update(updates)
    _write_config(config)


# ============================================================
# 模型价目表（2026-09-11 成本核算）
#
# 形态（model_config.json 顶层 "prices" 节，按模型名键控——generation_runs
# 每行存当次 model_name，换模型后历史账仍按各自价格计）：
#   "prices": {"qwen3.8-flash": {"input": 0.5, "cached_input": 0.1, "output": 2.0}}
# 单位 = 元 / 百万 token。cached_input 可缺省（缺省=按 input 全价，保守）。
# 价格来源：用户按各厂商公布页自填（厂商无统一计价 API，本地表是唯一
# 可靠来源）；删一个模型的价格 = 从 dict 里删键。
# ============================================================

PRICE_FIELDS = ("input", "cached_input", "output")


def get_model_prices() -> Dict[str, Dict[str, float]]:
    """读价目表（无 prices 节 = 空表，一切调用未计价）。"""
    raw = _load_config().get("prices") or {}
    prices: Dict[str, Dict[str, float]] = {}
    if not isinstance(raw, dict):
        return prices
    for model, entry in raw.items():
        if not isinstance(model, str) or not model.strip() or not isinstance(entry, dict):
            continue
        clean = {}
        for field in PRICE_FIELDS:
            v = entry.get(field)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                clean[field] = float(v)
        if "input" in clean and "output" in clean:
            prices[model.strip()] = clean
    return prices


def update_model_prices(prices: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """整表覆写价目并持久化（空 dict = 清空价目，回到未计价态）。

    输入先过同一把清洗（get_model_prices 同款判据：input/output 必填非负，
    cached_input 可选）；非法条目丢弃不炸——价目表是镜子不是闸门。
    返回清洗后的实际落盘值。
    """
    config = _load_config()
    cleaned: Dict[str, Dict[str, float]] = {}
    for model, entry in (prices or {}).items():
        if not isinstance(model, str) or not model.strip() or not isinstance(entry, dict):
            continue
        clean = {}
        for field in PRICE_FIELDS:
            v = entry.get(field)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                clean[field] = float(v)
        if "input" in clean and "output" in clean:
            cleaned[model.strip()] = clean
    if cleaned:
        config["prices"] = cleaned
    else:
        config.pop("prices", None)
    _write_config(config)
    return cleaned


def _invalidate_cache():
    """清除配置缓存，强制下次重新加载"""
    global _config_cache
    _config_cache = None


def get_default_reasoning_config(model_type: str = "default") -> Optional[dict]:
    """
    获取默认推理配置（extra_body 格式）。

    根据 model_type 从对应 profile 的 enabled/effort/exclude 读取。

    语义修复（2026-08-25）：enabled 为 False → 返回**显式关闭**（与
    services/llm/client.py 的 REASONING_DISABLED 同形），不再是 None
    「不表态」。动机实证：MiMo 等厂商服务端默认思考开，「不表态=开」——
    spine-suggest 曾被隐藏思考烧光 800 token 预算返回空输出（finish=length）。
    对 OpenAI/本地端点零变化：适配层在这些厂商的 enabled=False 分支
    依然返回 None 不发参数（reasoning_adapter.py 各分支保证）。
    """
    profile = get_model_profile(model_type)
    if profile.get("enabled"):
        return {
            "reasoning": {
                "enabled": True,
                "effort": profile.get("effort", "medium"),
                "exclude": profile.get("exclude", False),
            }
        }
    # 显式关闭（与 REASONING_DISABLED 同形；此处不 import client 防循环依赖）
    return {"reasoning": {"enabled": False}}


def resolve_model_name(model: Optional[str] = None, model_type: str = "default") -> str:
    """
    解析模型名称。

    规则：
    - 如果 model 显式传入且不是 'reasoning'/'creative'，直接使用
    - 如果 model 为 None 或等于 'reasoning'/'creative'，从对应 profile 读取 model 字段
    - model_type 作为后备：reasoning/creative/default
    """
    profile = get_model_profile(model_type)
    fallback_profile = get_model_profile("creative" if model_type == "reasoning" else "reasoning")

    explicit = model if model and model not in ("reasoning", "creative") else None
    if explicit:
        return explicit

    return profile.get("model") or fallback_profile.get("model") or "gpt-4o-mini"

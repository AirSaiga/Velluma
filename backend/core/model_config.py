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
    "model": "text-embedding-v2",
    "dimensions": 1536  // 向量维度，必须与数据库 schema 一致
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
      "model": "deepseek-reasoner",
      "enabled": true,
      "effort": "medium",
      "exclude": false
    },
    "creative": {
      "api_key": "sk-xxx",
      "base_url": "https://api.deepseek.com",
      "model": "deepseek-chat",
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


def _invalidate_cache():
    """清除配置缓存，强制下次重新加载"""
    global _config_cache
    _config_cache = None


def get_default_reasoning_config(model_type: str = "default") -> Optional[dict]:
    """
    获取默认推理配置（extra_body 格式）。

    根据 model_type 从对应 profile 的 enabled/effort/exclude 读取。
    如果 enabled 为 False，返回 None。
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
    return None


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

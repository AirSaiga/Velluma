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

配置结构：
{
  "openrouter": {
    "api_key": "...",
    "base_url": "https://openrouter.ai/api/v1",
    "reasoning_model": "...",
    "creative_model": "..."
  },
  "embedding": {
    "api_key": "...",
    "model": "text-embedding-v2"
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


def get_openrouter_config() -> Dict:
    """获取 OpenRouter 配置"""
    config = _load_config()
    return config.get("openrouter", {})


def get_embedding_config() -> Dict:
    """获取 Embedding 配置"""
    config = _load_config()
    return config.get("embedding", {})


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


def _invalidate_cache():
    """清除配置缓存，强制下次重新加载"""
    global _config_cache
    _config_cache = None


def get_default_reasoning_config(model_type: str = "default") -> Optional[dict]:
    """
    获取默认推理配置。

    根据 model_type 从 model_config.json 的 openrouter.{reasoning|creative} 读取。
    如果 enabled 为 False，返回 None。
    """
    or_config = get_openrouter_config()
    key = "reasoning" if model_type == "reasoning" else "creative"
    cfg = or_config.get(key, {})
    if cfg.get("enabled"):
        return {
            "reasoning": {
                "enabled": True,
                "effort": cfg.get("effort", "medium"),
                "exclude": cfg.get("exclude", False),
            }
        }
    return None


def resolve_model_name(model: Optional[str] = None, model_type: str = "default") -> str:
    """
    解析模型名称。

    规则：
    - 如果 model 显式传入且不是 'reasoning'/'creative'，直接使用
    - 如果 model 为 None 或等于 'reasoning'/'creative'，从配置读取对应类型
    - model_type 作为后备：reasoning/creative/default
    """
    or_config = get_openrouter_config()

    explicit = model if model and model not in ("reasoning", "creative") else None
    if explicit:
        return explicit

    if model in ("reasoning", None):
        if model_type == "reasoning":
            return or_config.get("reasoning_model") or or_config.get("creative_model") or "gpt-4o-mini"

    if model in ("creative", None):
        if model_type == "creative":
            return or_config.get("creative_model") or or_config.get("reasoning_model") or "gpt-4o-mini"

    # default fallback
    return or_config.get("reasoning_model") or or_config.get("creative_model") or "gpt-4o-mini"

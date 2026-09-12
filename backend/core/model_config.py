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
  "presets": [                // 模型配置预设（2026-09-11 快速切换，切走不丢 Key）
    {
      "id": "a1b2c3d4e5f6",   // uuid 短 id（重名覆盖时保持不变）
      "name": "DeepSeek 主力",
      "source": "manual",     // manual=用户点名保存 / auto=覆盖前自动存档
      "model": "deepseek-flash",
      "api_key": "sk-...",    // 明文仅存本地 json（同 llm.* 现状）；API 出参一律掩码
      "base_url": "https://api.deepseek.com/v1",
      "enabled": true,
      "effort": "medium"
    }
  ],
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
from typing import Dict, List, Optional, Tuple

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


# ============================================================
# 模型配置预设（presets，2026-09-11 快速切换）
#
# 业务动机：切换厂商/模型/Key 时旧值直接被覆盖丢失，而重建 Key 很麻烦。
# 预设池把整套连接配置（model/api_key/base_url + 思考开关）持久化在
# model_config.json 顶层 "presets" 节，设置面板下拉一点即切回。
#
# 纪律：
# - Key 明文只落本地 json（与 llm.* 现状同待遇）；API 出参一律掩码，
#   切换动作由服务端 apply 完成——明文 Key 不经前端往返。
# - source=auto 是安全网：槽位连接三件套即将被覆盖、旧值完整
#   （model+api_key 均非空）且无同签名预设时，覆盖前静默存一条——
#   「切走永不丢 Key」不依赖用户记得手动保存。
# - 签名=(model, api_key, base_url)：已有同签名预设（无论 manual/auto）
#   就不再存第二条，自动存档不会堆积重复。
# ============================================================

PRESET_ROLES = ("reasoning", "creative")
PRESET_EFFORTS = ("low", "medium", "high", "max")


def get_model_presets() -> List[Dict]:
    """读预设池（内部口径：api_key 明文；出参序列化在路由层做掩码）。

    非法条目（缺 id/name、非 dict）静默丢弃——预设池是工具不是闸门，
    手改 json 写坏了不该炸设置面板。
    """
    raw = _load_config().get("presets")
    if not isinstance(raw, list):
        return []
    out: List[Dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        if not entry.get("id") or not entry.get("name"):
            continue
        effort = str(entry.get("effort", "medium") or "medium")
        out.append({
            "id": str(entry["id"]),
            "name": str(entry["name"]),
            "source": entry.get("source") if entry.get("source") in ("manual", "auto") else "manual",
            "model": str(entry.get("model", "") or ""),
            "api_key": str(entry.get("api_key", "") or ""),
            "base_url": str(entry.get("base_url", "") or ""),
            "enabled": bool(entry.get("enabled", False)),
            "effort": effort if effort in PRESET_EFFORTS else "medium",
        })
    return out


def get_model_preset(preset_id: str) -> Optional[Dict]:
    """按 id 取单条预设；不存在返回 None。"""
    for preset in get_model_presets():
        if preset["id"] == preset_id:
            return preset
    return None


def _preset_signature(preset: Dict) -> Tuple[str, str, str]:
    """连接签名：自动存档的去重判据（enabled/effort 不参与）。"""
    return (preset.get("model", ""), preset.get("api_key", ""), preset.get("base_url", ""))


def _unique_preset_name(base_name: str, presets: List[Dict]) -> str:
    """自动命名撞车时追加 (2)/(3)——手动保存不走这里（同名=用户意图覆盖）。"""
    names = {p["name"] for p in presets}
    if base_name not in names:
        return base_name
    i = 2
    while f"{base_name} ({i})" in names:
        i += 1
    return f"{base_name} ({i})"


def _auto_preset_display_name(conn: Dict) -> str:
    """自动存档默认名：厂商标签 + 模型名（如「Kimi kimi-k2.6」）。

    vendor_profiles 在 services 层（其包 __init__ 会拉起 llm client，
    而 client import 本模块），只能惰性导入避免循环依赖；识别失败
    退化为纯模型名。
    """
    model = conn.get("model") or "未命名模型"
    try:
        from backend.services.llm.vendor_profiles import detect_provider, vendor_catalog
        provider = detect_provider(conn.get("base_url", ""), model)
        if provider and provider != "unknown":
            label = next((v.get("label") for v in vendor_catalog() if v.get("id") == provider), "")
            return f"{label or provider} {model}".strip()
    except Exception:
        pass
    return model


def upsert_model_preset(name: str, fields: Dict, source: str = "manual") -> Dict:
    """按名保存/覆盖预设并持久化，返回落盘后的完整预设。

    同名覆盖：id 与原条目保持一致（前端持有的引用不失效），source 以
    本次为准（手动覆盖自动存档=用户接管该条目）。
    """
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("预设名不能为空")
    config = _load_config()
    presets = get_model_presets()
    effort = str(fields.get("effort", "medium") or "medium")
    clean_fields = {
        "model": str(fields.get("model", "") or ""),
        "api_key": str(fields.get("api_key", "") or ""),
        "base_url": str(fields.get("base_url", "") or ""),
        "enabled": bool(fields.get("enabled", False)),
        "effort": effort if effort in PRESET_EFFORTS else "medium",
    }
    existing = next((p for p in presets if p["name"] == clean_name), None)
    if existing is not None:
        existing.update(clean_fields)
        if source in ("manual", "auto"):
            existing["source"] = source
        saved = existing
    else:
        import uuid
        saved = {
            "id": uuid.uuid4().hex[:12],
            "name": clean_name,
            "source": source if source in ("manual", "auto") else "manual",
            **clean_fields,
        }
        presets.append(saved)
    config["presets"] = presets
    _write_config(config)
    return saved


def delete_model_preset(preset_id: str) -> bool:
    """按 id 删预设；不存在返回 False（幂等删除）。"""
    config = _load_config()
    presets = get_model_presets()
    remaining = [p for p in presets if p["id"] != preset_id]
    if len(remaining) == len(presets):
        return False
    config["presets"] = remaining
    _write_config(config)
    return True


def apply_model_preset(preset_id: str, role: str) -> Dict:
    """把预设整卡写入指定槽位（model/api_key/base_url/enabled/effort 五件
    全量覆盖）并持久化。调用方负责先 maybe_capture_outgoing_slot 存档旧值。

    只收 reasoning/creative 两个可见槽（wash UI 已隐藏，语义是「跟随
    creative」，整卡覆盖会破坏该语义）。
    """
    if role not in PRESET_ROLES:
        raise ValueError(f"预设只能应用到 reasoning/creative 槽，收到: {role}")
    preset = get_model_preset(preset_id)
    if preset is None:
        raise KeyError(f"预设不存在: {preset_id}")
    update_llm_profile(role, {k: preset[k] for k in ("model", "api_key", "base_url", "enabled", "effort")})
    return preset


def maybe_capture_outgoing_slot(role: str, incoming_fields: Dict) -> Optional[Dict]:
    """安全网：槽位连接三件套即将被覆盖时，把旧值自动存为预设（source=auto）。

    跳过条件（返回 None）：
    - role 不是 reasoning/creative（wash 半态/不可见，不存）
    - 旧值不完整（缺 model 或 api_key——半态槽位本就跟随 creative，无 Key 可丢）
    - 连接三件套实际未变（只改 enabled/effort/保存 noop）
    - 已有同签名预设（自动存档不堆积重复；手动预设也算「已存档」）

    incoming_fields 是即将 merge 进槽位的字段（缺省键=保持原值，与
    update_llm_profile 的合并语义一致）；api_key 由路由层先行剥掉
    掩码回显值，这里按「未提供=沿用旧 Key」计算新三件套。
    """
    if role not in PRESET_ROLES:
        return None
    slot = get_llm_config().get(role) or {}
    old = {
        "model": slot.get("model", "") or "",
        "api_key": slot.get("api_key", "") or "",
        "base_url": slot.get("base_url", "") or "",
    }
    if not (old["model"] and old["api_key"]):
        return None
    new = dict(old)
    for key in ("model", "api_key", "base_url"):
        if incoming_fields.get(key) is not None:
            new[key] = str(incoming_fields[key])
    if _preset_signature(new) == _preset_signature(old):
        return None
    presets = get_model_presets()
    if any(_preset_signature(p) == _preset_signature(old) for p in presets):
        return None
    name = _unique_preset_name(_auto_preset_display_name(old), presets)
    return upsert_model_preset(name, {
        **old,
        "enabled": bool(slot.get("enabled", False)),
        "effort": slot.get("effort", "medium") or "medium",
    }, source="auto")


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

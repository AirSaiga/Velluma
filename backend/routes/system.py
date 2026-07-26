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
系统健康检查与配置路由模块。

职责：提供系统级 API，用于健康检查和运行时配置查询。

业务场景：
- 健康检查（/health）
- 获取后端实际端口（开发环境动态分配）
- 系统信息查询
- 模型连接测试（含推理模式支持检测）

设计说明：
- /health 用于容器编排系统（K8s/Docker）健康探测
- 端口获取解决开发环境动态切换端口的问题

数据来源：
- 端口信息来自 core/config.py 的运行时配置
"""

import logging
from typing import Optional

from fastapi import APIRouter

from backend.core.config import get_actual_port, check_reasoning_support
from backend.core.model_config import (
    resolve_model_name,
    get_default_reasoning_config,
    get_model_profile,
    get_model_config,
    has_dedicated_wash_profile,
    update_llm_profile,
    update_embedding_config,
    DEFAULT_PROVIDER_URLS,
)
from backend.services.llm import get_proxy_config, set_proxy_config, call_llm
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_SYSTEM
from backend.schemas import ProxyConfig, ModelTestRequest, ModelTestResponse, ModelConfigUpdate

router = APIRouter(prefix="/api", tags=["system"])
logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_SYSTEM)


# =============================================================================
# 健康检查与配置查询
 # =============================================================================

@router.get("/health")
async def health_check():
    """业务目的：提供基础健康检查端点，用于服务监控和负载均衡探测。

    用途：
    - Kubernetes/容器编排探针
    - 负载均衡健康检测
    - 运维监控确认服务存活

    副作用：
    - 无数据库操作，轻量级接口

    设计考量：
    - 返回固定值而非实时系统指标（CPU/内存等）
    - 简化监控复杂度，避免频繁采样
    - 若需要详细监控，应使用专门指标端点（如 /metrics）
    """
    return {"status": "ok", "service": "StoryWeaver-Core"}


@router.get("/port")
async def get_port():
    """业务目的：返回服务实际监听端口，用于容器环境下的服务发现。

    背景：
    - 容器化部署时，PORT 可能通过环境变量动态指定
    - 前端或网关需要知道实际端口进行连接

    数据来源：
    - get_actual_port() 读取环境变量或配置文件
    - 默认为 8000，开发环境常用

    权衡点：
    - 为什么不直接硬编码？
      因为容器环境端口映射的灵活性要求
    - 为什么不返回 IP？
      因为单实例部署场景，客户端通过网关访问
    """
    return {"port": get_actual_port()}


@router.get("/system/proxy")
async def get_proxy_config_endpoint():
    """获取当前代理配置"""
    return get_proxy_config()


@router.put("/system/proxy")
async def update_proxy_config_endpoint(config: ProxyConfig):
    """更新代理配置"""
    set_proxy_config(config.enabled, config.url)
    return get_proxy_config()


# =============================================================================
# 模型配置（设置面板）
# =============================================================================

def _mask_api_key(key: str) -> str:
    """API Key 掩码：仅保留首尾各 4 位，避免明文经 HTTP 传输。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _serialize_profile(role: str) -> dict:
    profile = get_model_profile(role)
    return {
        "provider": profile["provider"],
        "api_key_masked": _mask_api_key(profile["api_key"]),
        "has_api_key": bool(profile["api_key"]),
        "base_url": profile["base_url"],
        "default_base_url": DEFAULT_PROVIDER_URLS.get(profile["provider"], ""),
        "model": profile["model"],
        "enabled": profile["enabled"],
        "effort": profile["effort"],
    }


def _serialize_wash_profile() -> dict:
    """洗涤槽序列化：返回原始配置（不做 creative 回退），未配置时字段为空。

    与 _serialize_profile 的区别：get_model_profile("wash") 会在未配置时
    回退到 creative，直接复用会让前端把 creative 的值显示成 wash 的配置，
    保存时还会把这些值固化进 wash 槽。configured 标志供前端提示"跟随创意模型"。
    """
    raw = get_model_config().get("llm", {}).get("wash", {})
    provider = raw.get("provider", "deepseek")
    return {
        "provider": provider,
        "api_key_masked": _mask_api_key(raw.get("api_key", "")),
        "has_api_key": bool(raw.get("api_key")),
        "base_url": raw.get("base_url", ""),
        "default_base_url": DEFAULT_PROVIDER_URLS.get(provider, ""),
        "model": raw.get("model", ""),
        "enabled": raw.get("enabled", False),
        "effort": raw.get("effort", "low"),
        "configured": bool(raw.get("model") and raw.get("api_key")),
    }


def _serialize_model_config() -> dict:
    """序列化完整模型配置（API Key 掩码后返回）"""
    config = get_model_config()
    embedding = config.get("embedding", {})
    return {
        "llm": {
            "reasoning": _serialize_profile("reasoning"),
            "creative": _serialize_profile("creative"),
            "wash": _serialize_wash_profile(),
        },
        "embedding": {
            "api_key_masked": _mask_api_key(embedding.get("api_key", "")),
            "has_api_key": bool(embedding.get("api_key")),
            "model": embedding.get("model", "text-embedding-v2"),
            "dimensions": embedding.get("dimensions", 1536),
        },
        "proxy": get_proxy_config(),
    }


@router.get("/system/model-config")
async def get_model_config_endpoint():
    """获取模型配置（LLM / Embedding / 代理），API Key 以掩码返回"""
    return _serialize_model_config()


@router.put("/system/model-config")
async def update_model_config_endpoint(update: ModelConfigUpdate):
    """更新模型配置并持久化到 model_config.json。

    副作用：
    - 未提供的字段保持原值；api_key 传空字符串/None 表示不修改
    - LLM 与代理配置保存后立即生效（每次调用实时读取）
    - embedding.dimensions 变更需重启后端，启动迁移会删列重建向量数据（破坏性）
    """
    for role, profile in (
        ("reasoning", update.reasoning),
        ("creative", update.creative),
        ("wash", update.wash),
    ):
        if profile is None:
            continue
        fields = profile.model_dump(exclude_none=True)
        if not fields.get("api_key"):
            fields.pop("api_key", None)  # 空 Key 视为保持不变
        if fields:
            update_llm_profile(role, fields)

    if update.embedding is not None:
        fields = update.embedding.model_dump(exclude_none=True)
        if not fields.get("api_key"):
            fields.pop("api_key", None)
        if fields:
            update_embedding_config(fields)

    if update.proxy is not None:
        set_proxy_config(update.proxy.enabled, update.proxy.url)

    svc_logger.info("模型配置已更新")
    return _serialize_model_config()


# =============================================================================
# 模型连接测试
# =============================================================================

@router.post("/system/test-model", response_model=ModelTestResponse)
async def test_model_connection(request: ModelTestRequest):
    """
    测试模型连接并检测推理模式支持。
    
    业务目的：
    - 验证 API Key 和 Base URL 是否正确配置
    - 检测 reasoning 和 creative 两个模型是否可用；
      配置了独立洗涤槽（llm.wash）时一并测试 wash 模型
    - 如果启用推理模式，检测模型是否支持推理功能
    
    测试流程：
    1. 分别测试 reasoning 和 creative 模型
    2. 检查模型名称是否在已知支持推理的列表中
    3. 如果启用推理，尝试带推理参数的请求
    
    Returns:
        ModelTestResponse: 包含连接状态、推理支持信息等
    """
    import time
    
    start_time = time.perf_counter()
    reasoning_model = resolve_model_name(model_type="reasoning")
    creative_model = resolve_model_name(model_type="creative")
    
    reasoning_profile = get_model_profile("reasoning")
    creative_profile = get_model_profile("creative")
    
    # 构建推理配置（如果启用）
    reasoning_config = None
    reasoning_enabled = request.reasoning_enabled
    reasoning_effort = request.reasoning_effort

    if reasoning_enabled is None:
        default_cfg = get_default_reasoning_config("reasoning")
        if default_cfg:
            reasoning_config = default_cfg
            reasoning_enabled = True
            reasoning_effort = default_cfg.get("reasoning", {}).get("effort", "medium")
    elif reasoning_enabled:
        reasoning_config = {
            "reasoning": {
                "enabled": True,
                "effort": reasoning_effort or "medium"
            }
        }

    test_prompt = "请回复'连接测试成功'这六个字，不要输出其他内容。"
    
    # 测试 reasoning 模型
    reasoning_success = False
    reasoning_response = ""
    reasoning_error = ""
    try:
        reasoning_response = await call_llm(
            system_prompt="你是一个测试助手。请严格按照用户的要求回复。",
            user_prompt=test_prompt,
            model=reasoning_model,
            model_type="reasoning",
            temperature=0.1,
            max_tokens=50,
            reasoning_config=reasoning_config,
        )
        reasoning_success = True
    except Exception as e:
        reasoning_error = str(e)
    
    # 测试 creative 模型
    creative_success = False
    creative_response = ""
    creative_error = ""
    try:
        creative_response = await call_llm(
            system_prompt="你是一个测试助手。请严格按照用户的要求回复。",
            user_prompt=test_prompt,
            model=creative_model,
            model_type="creative",
            temperature=0.7,
            max_tokens=50,
        )
        creative_success = True
    except Exception as e:
        creative_error = str(e)

    # 测试 wash 模型（仅在配置了独立洗涤槽时；未配置时洗涤跟随 creative，无需重复测）
    wash_configured = has_dedicated_wash_profile()
    wash_model = ""
    wash_provider = ""
    wash_success: Optional[bool] = None
    wash_error = ""
    if wash_configured:
        wash_model = resolve_model_name(model_type="wash")
        wash_provider = get_model_profile("wash")["provider"]
        try:
            await call_llm(
                system_prompt="你是一个测试助手。请严格按照用户的要求回复。",
                user_prompt=test_prompt,
                model=wash_model,
                model_type="wash",
                temperature=0.8,
                max_tokens=50,
                reasoning_config={},  # 洗涤默认不开 thinking，测试保持一致
            )
            wash_success = True
        except Exception as e:
            wash_success = False
            wash_error = str(e)

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # 检查推理模式支持
    reasoning_supported, reasoning_message = check_reasoning_support(reasoning_model)
    creative_supported, creative_message = check_reasoning_support(creative_model)

    # 构建返回消息
    messages = []
    if reasoning_success:
        messages.append(f"推理模型 ({reasoning_model}): 连接成功")
    else:
        messages.append(f"推理模型 ({reasoning_model}): 连接失败 - {reasoning_error[:100]}")

    if creative_success:
        messages.append(f"创意模型 ({creative_model}): 连接成功")
    else:
        messages.append(f"创意模型 ({creative_model}): 连接失败 - {creative_error[:100]}")

    if wash_configured:
        if wash_success:
            messages.append(f"洗涤模型 ({wash_model}): 连接成功")
        else:
            messages.append(f"洗涤模型 ({wash_model}): 连接失败 - {wash_error[:100]}")

    overall_success = reasoning_success or creative_success
    
    return ModelTestResponse(
        success=overall_success,
        message="; ".join(messages),
        model_info={
            "reasoning_model": reasoning_model,
            "creative_model": creative_model,
            "reasoning_provider": reasoning_profile["provider"],
            "reasoning_base_url": reasoning_profile["base_url"],
            "creative_provider": creative_profile["provider"],
            "creative_base_url": creative_profile["base_url"],
            "reasoning_success": reasoning_success,
            "creative_success": creative_success,
            "wash_configured": wash_configured,
            "wash_model": wash_model or None,
            "wash_provider": wash_provider or None,
            "wash_success": wash_success,
        },
        reasoning_supported=reasoning_supported,
        reasoning_message=reasoning_message,
        response_time_ms=round(elapsed_ms, 2)
    )

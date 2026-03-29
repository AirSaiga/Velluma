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
from backend.services.llm import get_proxy_config, set_proxy_config, call_llm
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_SYSTEM
from backend.schemas import ProxyConfig, ModelTestRequest, ModelTestResponse

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
# 模型连接测试
# =============================================================================

@router.post("/system/test-model", response_model=ModelTestResponse)
async def test_model_connection(request: ModelTestRequest):
    """
    测试模型连接并检测推理模式支持。
    
    业务目的：
    - 验证 API Key 和 Base URL 是否正确配置
    - 检测模型是否可用
    - 如果启用推理模式，检测模型是否支持推理功能
    
    测试流程：
    1. 发送简单的测试请求验证连接
    2. 检查模型名称是否在已知支持推理的列表中
    3. 如果启用推理，尝试带推理参数的请求
    
    Returns:
        ModelTestResponse: 包含连接状态、推理支持信息等
    """
    import time
    
    start_time = time.perf_counter()
    
    try:
        # 构建推理配置（如果启用）
        reasoning_config = None
        if request.reasoning_enabled:
            reasoning_config = {
                "reasoning": {
                    "enabled": True,
                    "effort": request.reasoning_effort
                }
            }
        
        # 发送测试请求
        test_prompt = "请回复'连接测试成功'这六个字，不要输出其他内容。"
        response = await call_llm(
            system_prompt="你是一个测试助手。请严格按照用户的要求回复。",
            user_prompt=test_prompt,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            temperature=0.1,
            max_tokens=50,
            reasoning_config=reasoning_config,
        )
        
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        
        # 检查推理模式支持
        reasoning_supported = None
        reasoning_message = None
        
        if request.reasoning_enabled:
            # 检查模型名称
            reasoning_supported, reasoning_message = check_reasoning_support(request.model)
            
            # 如果模型名称匹配，但实际请求可能失败（API 不支持）
            # 这里我们基于模型名称判断，实际使用时如果 API 不支持会报错
        
        return ModelTestResponse(
            success=True,
            message=f"模型连接成功，响应: {response[:50]}..." if len(response) > 50 else f"模型连接成功，响应: {response}",
            model_info={
                "model": request.model,
                "base_url": request.base_url or "默认"
            },
            reasoning_supported=reasoning_supported,
            reasoning_message=reasoning_message,
            response_time_ms=round(elapsed_ms, 2)
        )
        
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        error_msg = str(e)
        
        # 解析常见错误类型
        if "401" in error_msg or "Unauthorized" in error_msg or "invalid_api_key" in error_msg.lower():
            message = "API Key 无效或未授权，请检查 API Key 是否正确"
        elif "404" in error_msg or "not_found" in error_msg.lower() or "model" in error_msg.lower():
            message = f"模型 {request.model} 不存在或不可用，请检查模型名称"
        elif "429" in error_msg or "rate_limit" in error_msg.lower():
            message = "请求过于频繁，请稍后重试"
        elif "timeout" in error_msg.lower():
            message = "连接超时，请检查网络或代理设置"
        elif "connection" in error_msg.lower():
            message = "无法连接到 API 服务器，请检查 Base URL 或网络设置"
        elif "reasoning" in error_msg.lower():
            message = f"推理模式不支持：该模型可能不支持推理功能。错误: {error_msg[:100]}"
        else:
            message = f"连接测试失败: {error_msg[:200]}"
        
        svc_logger.warning("Model test failed", model=request.model, error=error_msg)
        
        return ModelTestResponse(
            success=False,
            message=message,
            response_time_ms=round(elapsed_ms, 2)
        )

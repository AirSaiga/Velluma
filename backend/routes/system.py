"""
系统健康检查与配置路由模块。

职责：提供系统级 API，用于健康检查和运行时配置查询。

业务场景：
- 健康检查（/health）
- 获取后端实际端口（开发环境动态分配）
- 系统信息查询

设计说明：
- /health 用于容器编排系统（K8s/Docker）健康探测
- 端口获取解决开发环境动态切换端口的问题

数据来源：
- 端口信息来自 core/config.py 的运行时配置
"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.core.config import get_actual_port
from backend.services.llm_client import get_proxy_config, set_proxy_config

router = APIRouter(prefix="/api", tags=["system"])


class ProxyConfig(BaseModel):
    enabled: bool
    url: str


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

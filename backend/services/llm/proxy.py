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
代理配置模块 - HTTP 代理管理。

职责：
- 管理 LLM API 调用的代理配置
- 支持运行时启用/禁用代理
- 提供代理 URL 查询接口

业务场景：
- 开发环境网络受限需通过代理访问外网
- 生产环境可能需要代理进行流量控制
- 测试环境需要切换不同代理

主要功能：
- 代理启用/禁用切换
- 代理 URL 运行时修改
- 环境变量同步

依赖项：
- os: 环境变量读写

使用方式：
    set_proxy_config(enabled=True, url="http://proxy.example.com:8080")
    proxy = get_active_proxy()
"""

import os
import logging
from typing import Optional


logger = logging.getLogger(__name__)


_default_proxy = "http://127.0.0.1:4780"
PROXY_URL = os.environ.get("PROXY_URL", _default_proxy)

_proxy_config = {
    "enabled": True,
    "url": PROXY_URL,
}


def get_proxy_config() -> dict:
    return _proxy_config.copy()


def set_proxy_config(enabled: bool, url: str):
    _proxy_config["enabled"] = enabled
    _proxy_config["url"] = url
    _clear_proxy_env()
    if enabled and url:
        os.environ["HTTP_PROXY"] = url
        os.environ["HTTPS_PROXY"] = url
        os.environ["ALL_PROXY"] = url
        os.environ["http_proxy"] = url
        os.environ["https_proxy"] = url
        os.environ["all_proxy"] = url
        logger.info(f"代理已启用: {url}")
    else:
        logger.info("代理已禁用")


def get_active_proxy() -> Optional[str]:
    if _proxy_config["enabled"] and _proxy_config["url"]:
        return _proxy_config["url"]
    return None


def _clear_proxy_env():
    for key in [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ]:
        os.environ.pop(key, None)

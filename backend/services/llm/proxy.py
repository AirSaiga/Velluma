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
- 配置源统一为项目根目录 model_config.json
- 支持运行时启用/禁用代理并同步环境变量
"""

import os
import logging
from typing import Optional

from backend.core.model_config import (
    get_proxy_config as _get_proxy_config_from_file,
    set_proxy_config as _set_proxy_config_in_file,
)

logger = logging.getLogger(__name__)


def get_proxy_config() -> dict:
    return _get_proxy_config_from_file()


def set_proxy_config(enabled: bool, url: str):
    _set_proxy_config_in_file(enabled, url)
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
    cfg = get_proxy_config()
    if cfg["enabled"] and cfg["url"]:
        return cfg["url"]
    return None


def _clear_proxy_env():
    for key in [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ]:
        os.environ.pop(key, None)

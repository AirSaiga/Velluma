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
日志工具模块 - 统一日志格式和辅助函数

职责：
- 提供标准化的日志前缀格式
- Re-export SSE 消息构建工具（向后兼容）
- Re-export 性能计时和超时控制工具（向后兼容）

设计原则：
- 所有日志前缀统一格式：[ModuleName] message
- SSE 消息构建集中管理，避免重复代码
"""

import logging
from typing import Union

from backend.services.utils.sse import (
    build_sse_event,
    build_sse_metric_frame,
    build_sse_text_chunk,
    build_sse_done,
    build_sse_error,
)
from backend.services.utils.timeout import (
    timed,
    with_timeout,
    TimeoutManager,
)

LogValue = Union[str, int, float, bool, None]


LOG_PREFIX_DUAL_TRACK = "[DualTrack]"
LOG_PREFIX_RAG = "[RAG]"
LOG_PREFIX_PROMPT_LOGGER = "[PromptLogger]"
LOG_PREFIX_EMBEDDING = "[Embedding]"
LOG_PREFIX_SUMMARY = "[Summary]"
LOG_PREFIX_WORKFLOW = "[Workflow]"
LOG_PREFIX_SYSTEM = "[System]"


def log_info(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 info 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.info(f"{prefix} {message} {extra_info}")
    else:
        logger.info(f"{prefix} {message}")


def log_warning(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 warning 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.warning(f"{prefix} {message} {extra_info}")
    else:
        logger.warning(f"{prefix} {message}")


def log_error(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 error 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.error(f"{prefix} {message} {extra_info}")
    else:
        logger.error(f"{prefix} {message}")


def log_debug(logger: logging.Logger, prefix: str, message: str, **kwargs: LogValue) -> None:
    """输出标准化 debug 日志"""
    extra_info = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None) if kwargs else ""
    if extra_info:
        logger.debug(f"{prefix} {message} {extra_info}")
    else:
        logger.debug(f"{prefix} {message}")


class ServiceLogger:
    """
    服务日志助手 - 为特定服务提供预配置前缀的日志方法

    用法：
        logger = ServiceLogger(logging.getLogger(__name__), "[DualTrack]")
        logger.info("Starting workflow")
        # 输出: [DualTrack] Starting workflow
    """

    def __init__(self, logger: logging.Logger, prefix: str):
        self._logger = logger
        self._prefix = prefix

    def info(self, message: str, **kwargs: LogValue) -> None:
        log_info(self._logger, self._prefix, message, **kwargs)

    def warning(self, message: str, **kwargs: LogValue) -> None:
        log_warning(self._logger, self._prefix, message, **kwargs)

    def error(self, message: str, **kwargs: LogValue) -> None:
        log_error(self._logger, self._prefix, message, **kwargs)

    def debug(self, message: str, **kwargs: LogValue) -> None:
        log_debug(self._logger, self._prefix, message, **kwargs)

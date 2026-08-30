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
超时与计时工具

职责：
- 提供性能计时装饰器 (timed)
- 提供异步超时控制装饰器 (with_timeout)
- 提供统一的超时管理器 (TimeoutManager)
"""

import asyncio
import logging
import time
from functools import wraps
from typing import Callable, Dict, Optional


def timed(logger: Optional[logging.Logger] = None, prefix: str = "", log_level: int = logging.INFO):
    """
    性能计时装饰器

    用法：
        @timed(logger, "[Module]")
        async def my_function():
            pass
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} completed in {elapsed:.2f}s"
                    logger.log(log_level, log_msg)
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} failed after {elapsed:.2f}s: {e}"
                    logger.error(log_msg)
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} completed in {elapsed:.2f}s"
                    logger.log(log_level, log_msg)
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start
                if logger:
                    log_msg = f"{prefix} {func.__name__} failed after {elapsed:.2f}s: {e}"
                    logger.error(log_msg)
                raise

        return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
    return decorator


def with_timeout(timeout_seconds: float, timeout_message: str = "Operation timed out"):
    """
    为异步函数添加超时控制的装饰器

    用法：
        @with_timeout(120, "LLM call timed out")
        async def call_llm_with_timeout(...):
            return await call_llm(...)

    Args:
        timeout_seconds: 超时时间（秒）
        timeout_message: 超时时的错误消息

    Returns:
        装饰器函数
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await asyncio.wait_for(
                    func(*args, **kwargs),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                raise asyncio.TimeoutError(timeout_message)
        return wrapper
    return decorator


class TimeoutManager:
    """
    超时管理器 - 统一管理常用操作的超时设置

    用法：
        timeout_mgr = TimeoutManager()
        result = await timeout_mgr.call_with_timeout(llm_call(), "llm")
    """

    DEFAULT_TIMEOUTS = {
        "llm": 120,
        "embedding": 60,
        "summary": 180,
        "world_state": 150,
        "character_update": 180,
        "db_query": 30,
    }

    def __init__(self, custom_timeouts: Optional[Dict[str, float]] = None):
        """
        初始化超时管理器

        Args:
            custom_timeouts: 自定义超时配置，覆盖默认值
        """
        self._timeouts = {**self.DEFAULT_TIMEOUTS, **(custom_timeouts or {})}

    async def call_with_timeout(
        self,
        coro,
        operation_type: str,
        custom_timeout: Optional[float] = None
    ):
        """
        使用配置的超时时间执行协程

        Args:
            coro: 要执行的协程
            operation_type: 操作类型（用于查找默认超时）
            custom_timeout: 自定义超时（覆盖配置）

        Returns:
            协程执行结果

        Raises:
            asyncio.TimeoutError: 超时
        """
        timeout = custom_timeout or self._timeouts.get(operation_type, 120)
        return await asyncio.wait_for(coro, timeout=timeout)

    def get_timeout(self, operation_type: str) -> float:
        """获取指定操作类型的超时时间"""
        return self._timeouts.get(operation_type, 120)

    def set_timeout(self, operation_type: str, timeout: float) -> None:
        """设置指定操作类型的超时时间"""
        self._timeouts[operation_type] = timeout

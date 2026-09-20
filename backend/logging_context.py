# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# 请求关联上下文（request correlation context）
"""
request_id contextvar + 日志过滤器——**零后端依赖**（只 import 标准库）。

为什么独立成顶层模块：main.py 的日志配置区要在 `from backend.core.*` 任何
import 发生**之前**把 RequestContextFilter 挂上 root handler——若过滤器住在
backend.core 包内，import 它本身就会触发 backend.core/__init__ 的依赖链
（dependencies → repositories）在 import 期打日志，此时过滤器尚未挂上，
`%(req_id)s` 格式化会报 KeyError（DEBUG 级别下必现）。backend/__init__.py
是纯许可证头，从本模块 import 只初始化 backend 包本身，无副作用。

消费方：
- main.py 日志配置区：挂 root handler，所有 backend.* 业务日志携带 [req=...]
- backend/core/request_observability.py：re-export（request_id_var /
  get_request_id / RequestContextFilter），中间件与 HTTP 异常处理器共用
"""

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """当前请求的 req id；请求上下文之外返回空串。"""
    return request_id_var.get()


class RequestContextFilter(logging.Filter):
    """把 request_id 注入每条 record（record.req_id，无上下文时 '-'）。

    必须挂在 **root handler** 上（handler 级 filter 对所有传播记录生效；
    logger 级 filter 只管直接挂在它身上的记录——勿挪到 logger 上）。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.req_id = request_id_var.get() or "-"
        return True

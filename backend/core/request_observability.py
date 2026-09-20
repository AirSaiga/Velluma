# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# 请求级链路观测（request observability）
"""
请求级日志基建：request_id 关联 + 请求日志中间件 + HTTP 异常处理器。

==== 职责 ====
- 每个进入的 HTTP 请求生成 8 位 request_id，经 contextvar 贯穿本次请求的
  全部业务日志（RequestContextFilter 注入 [req=...]），并回写响应头
  X-Request-ID（前端排障可对账）。
- RequestLoggingMiddleware：纯 ASGI 中间件（不用 BaseHTTPMiddleware，
  不缓冲流式响应，SSE 安全），完成后打一行 [REQ]：
  方法 + 路由模板 + 状态码 + 耗时 + req id + handler + query。
- HTTP 异常落日志：4xx WARNING / 5xx ERROR（此前 189 处 HTTPException
  全部无痕）；未捕获异常 ERROR + traceback，响应统一 JSON 500。

==== 级别策略（降噪）====
- OPTIONS 预检、/api 之外（静态/SPA/world-images）→ 不打 INFO 完成行；
- /api/health → DEBUG；
- 状态码 >=400 WARNING、>=500 ERROR。

==== 接线（main.py）====
- root handler 挂 RequestContextFilter（定义在零依赖的 backend/logging_context.py，
  本模块 re-export；handler 级 filter 对传播记录生效，logger 级 filter 只管
  直接挂在它身上的记录——勿挪到 logger 上。且必须在任何 backend.core.* import
  之前挂上，原因见 logging_context 模块头）；
- app.add_middleware(RequestLoggingMiddleware)（注册在 CORS 之后 = 最外层）；
- register_exception_handlers(app)。
日志仍走 stdout → dev_backend.log 泵（文件为真相源契约不变，launcher 零改动）。

警示：不记录请求体（隐私与体积）；trace/prompt_log/generation_runs 三通道
结构不受影响，本模块只补请求级关联。
"""

import logging
import time
import uuid

from backend.logging_context import (  # 零依赖顶层模块（见其模块头说明）
    RequestContextFilter,
    get_request_id,
    request_id_var,
)
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "RequestContextFilter",
    "RequestLoggingMiddleware",
    "get_request_id",
    "register_exception_handlers",
    "request_id_var",
]


# ============================================================
# request_id contextvar（定义在 backend/logging_context.py，此处 re-export）
# ============================================================

def _new_request_id() -> str:
    return uuid.uuid4().hex[:8]


# ============================================================
# 请求日志中间件
# ============================================================

_API_ROOT = "/api"
_HEALTH_PATH = "/api/health"
_QUERY_MAX_CHARS = 300

_req_logger = logging.getLogger("backend.request")


def _endpoint_label(scope: Scope) -> str:
    """handler 归因标签：`<模块尾段>.<函数名>`（如 world.get_scene_slice）。

    用 __name__ 优先（路由端点都是普通函数；__qualname__ 对闭包内定义的
    端点会带 <locals> 噪声）。
    """
    endpoint = scope.get("endpoint")
    if endpoint is None:
        return ""
    module = getattr(endpoint, "__module__", "") or ""
    short_module = module.rsplit(".", 1)[-1]
    qualname = getattr(endpoint, "__name__", "") or getattr(endpoint, "__qualname__", "")
    return f"{short_module}.{qualname}" if qualname else ""


def _route_template(scope: Scope, path: str) -> str:
    """路由模板（FastAPI APIRoute 会写入 scope['route']）；未匹配回退实际路径。"""
    route = scope.get("route")
    return getattr(route, "path", None) or path


class RequestLoggingMiddleware:
    """纯 ASGI 请求日志中间件（SSE 安全：不缓冲、不改响应体）。

    完成行示例：
    [REQ] GET /api/books/{book_id}/world/scene-slice -> 200 8.2ms
          req=ab12cd3f handler=world.get_scene_slice ?chapter_id=...
    未捕获异常时 Starlette ServerErrorMiddleware 会在栈内产出 500 响应
    （异常随后照旧向上抛给 uvicorn），所以这里状态码仍是 500 而非 0。
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = (scope.get("query_string") or b"").decode("utf-8", "replace")
        # OPTIONS 预检由 CORS 短路应答、/api 之外是静态资源——都无业务语义
        skip_log = (method == "OPTIONS") or (not path.startswith(_API_ROOT))

        req_id = _new_request_id()
        token = request_id_var.set(req_id)
        start = time.perf_counter()
        status_holder: dict = {"status": 0}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", req_id.encode("ascii")))
            await send(message)

        if not skip_log:
            # 入口行（DEBUG）：默认不可见，VELLUMA_LOG_LEVEL=DEBUG 时可看在途请求
            _req_logger.debug("[REQ] --> %s %s req=%s", method, path, req_id)
        crashed = False
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # 未捕获异常：ServerErrorMiddleware（本层外侧）会兜 500 响应并照旧
            # 向上抛给 uvicorn——本层 send_wrapper 看不到那个响应，用 crashed 标记
            crashed = True
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            status = status_holder["status"]
            if crashed and status == 0:
                status = 500  # 外层兜底响应，本层不可见，按 500 记
            if not skip_log:
                self._log_completion(
                    method, path, query, scope, status, elapsed_ms, req_id,
                )
            request_id_var.reset(token)

    def _log_completion(
        self,
        method: str,
        path: str,
        query: str,
        scope: Scope,
        status: int,
        elapsed_ms: float,
        req_id: str,
    ) -> None:
        template = _route_template(scope, path)
        if path == _HEALTH_PATH:
            level = logging.DEBUG
        elif status >= 500 or status == 0:
            level = logging.ERROR
        elif status >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO
        suffix = f" ?{query[:_QUERY_MAX_CHARS]}" if query else ""
        handler = _endpoint_label(scope)
        handler_part = f" handler={handler}" if handler else ""
        status_text = str(status) if status else "<no-response>"
        _req_logger.log(
            level,
            "[REQ] %s %s -> %s %.1fms req=%s%s%s",
            method, template, status_text, elapsed_ms, req_id, handler_part, suffix,
        )


# ============================================================
# HTTP 异常处理器
# ============================================================

async def http_exception_logger(
    request: Request, exc: StarletteHTTPException,
) -> JSONResponse:
    """HTTPException 落日志后按 Starlette 默认形状回 JSON（{detail}，可带 headers）。

    此前 4xx/404 一行日志都不打——前端拿到 {detail} 而控制台全静默，这里补归因。
    非 /api 路径（world-images 404 等）降 DEBUG 降噪。
    """
    path = request.url.path
    if path.startswith(_API_ROOT):
        level = logging.ERROR if exc.status_code >= 500 else logging.WARNING
    else:
        level = logging.DEBUG
    _req_logger.log(
        level,
        "[HTTP] %s %s -> %d detail=%s",
        request.method, path, exc.status_code, str(exc.detail)[:200],
    )
    headers = getattr(exc, "headers", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=headers or None,
    )


async def validation_exception_logger(
    request: Request, exc: RequestValidationError,
) -> JSONResponse:
    """422 参数校验失败落 WARNING 后委托 FastAPI 默认 handler（响应形状不变）。"""
    _req_logger.warning(
        "[HTTP] %s %s -> 422 校验失败 errors=%s",
        request.method, request.url.path, str(exc.errors())[:300],
    )
    return await request_validation_exception_handler(request, exc)


async def unhandled_exception_logger(
    request: Request, exc: Exception,
) -> JSONResponse:
    """未捕获异常：ERROR + traceback；响应 JSON 500。

    Starlette ServerErrorMiddleware 会照旧把异常向上抛给 uvicorn
    （"Exception in ASGI application" traceback 仍在），此处日志带
    req id 与路由归因，两路互补。
    """
    _req_logger.exception(
        "[HTTP] %s %s -> 500 未捕获异常",
        request.method, request.url.path,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


def register_exception_handlers(app) -> None:
    """注册三个异常处理器（main.py 调用一次）。"""
    app.add_exception_handler(StarletteHTTPException, http_exception_logger)
    app.add_exception_handler(RequestValidationError, validation_exception_logger)
    app.add_exception_handler(Exception, unhandled_exception_logger)

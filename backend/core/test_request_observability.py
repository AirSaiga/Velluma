# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
对拍口径（backend/core/request_observability.py 请求级观测契约锁定）：

- [REQ] 完成行：`[REQ] <方法> <路由模板> -> <状态> <耗时>ms req=<8hex>
  handler=<模块尾段.函数名> ?<query>`；X-Request-ID 响应头与日志 req= 一致
- 降噪策略：OPTIONS 预检与非 /api 路径零完成行；/api/health 完成行恒 DEBUG
- 异常落日志：4xx → WARNING（[HTTP] 行 + 完成行）、422 → WARNING（响应形状
  不变，委托 FastAPI 默认 handler）、未捕获异常 → ERROR + JSON 500
- 纯 ASGI 中间件不缓冲流式响应（StreamingResponse 全量到达 + 完成行正常）
- RequestContextFilter 无上下文时 req_id='-'；get_runtime_logger 归真模块命名空间
- VELLUMA_LOG_LEVEL 解析语义：非法值回退 INFO（与 main._resolve_log_level 同口径）
"""
import logging
import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from backend.core.request_observability import (
    RequestContextFilter,
    RequestLoggingMiddleware,
    get_request_id,
    register_exception_handlers,
    request_id_var,
)
from backend.services.utils.logging import get_runtime_logger

_REQ_ID_RE = re.compile(r"req=([0-9a-f]{8})")


def _make_app() -> FastAPI:
    """最小应用：只装被测中间件与异常处理器，不 import backend.main。"""
    app = FastAPI()
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    @app.get("/api/echo")
    async def echo():
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/four04")
    async def four04():
        raise HTTPException(status_code=404, detail="not found")

    @app.get("/api/items/{item_id}")
    async def item(item_id: int):
        return {"id": item_id}

    @app.get("/api/boom")
    async def boom():
        raise RuntimeError("boom")

    @app.get("/api/stream")
    async def stream():
        async def gen():
            yield b"chunk1"
            yield b"chunk2"

        return StreamingResponse(gen(), media_type="text/plain")

    @app.get("/assets/app.js")
    async def asset():
        return {"js": True}

    return app


def _req_records(caplog) -> list:
    return [r for r in caplog.records if r.name == "backend.request"]


def _completion_records(caplog) -> list:
    return [
        r for r in _req_records(caplog)
        if r.getMessage().startswith("[REQ]") and "[REQ] -->" not in r.getMessage()
    ]


def test_completion_line_and_request_id_header(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/api/echo")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    completions = [r for r in _completion_records(caplog) if r.levelno == logging.INFO]
    assert len(completions) == 1
    msg = completions[0].getMessage()
    # 路由模板 / 状态码 / 耗时 / req id / handler 归因
    assert "[REQ] GET /api/echo -> 200" in msg
    assert "handler=test_request_observability.echo" in msg
    assert "ms" in msg
    m = _REQ_ID_RE.search(msg)
    assert m, msg
    # 响应头与日志行同一 req id
    assert resp.headers["x-request-id"] == m.group(1)


def test_health_completion_line_is_debug(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/api/health")

    assert resp.status_code == 200
    completions = [r for r in _completion_records(caplog) if "/api/health" in r.getMessage()]
    assert len(completions) == 1
    assert completions[0].levelno == logging.DEBUG


def test_options_preflight_has_no_req_line(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        client.options("/api/echo")

    # OPTIONS 预检不打任何 [REQ] 行（测试 app 无 CORS 时路由会回 405，
    # 该 [HTTP] 行属于异常处理器口径，不受此约束）
    assert all("[REQ]" not in r.getMessage() for r in _req_records(caplog))


def test_non_api_path_not_logged(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/assets/app.js")

    assert resp.status_code == 200
    assert _req_records(caplog) == []


def test_404_logged_as_warning_with_default_shape(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/api/four04")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "not found"}
    http_lines = [r for r in _req_records(caplog) if r.getMessage().startswith("[HTTP]")]
    assert len(http_lines) == 1
    assert http_lines[0].levelno == logging.WARNING
    assert "[HTTP] GET /api/four04 -> 404 detail=not found" in http_lines[0].getMessage()
    # 完成行同样升 WARNING
    completions = [r for r in _completion_records(caplog) if "/api/four04" in r.getMessage()]
    assert len(completions) == 1
    assert completions[0].levelno == logging.WARNING


def test_422_validation_logged_as_warning_with_default_shape(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/api/items/abc")

    assert resp.status_code == 422
    assert "detail" in resp.json()
    http_lines = [r for r in _req_records(caplog) if r.getMessage().startswith("[HTTP]")]
    assert len(http_lines) == 1
    assert http_lines[0].levelno == logging.WARNING
    assert "-> 422" in http_lines[0].getMessage()


def test_unhandled_exception_logged_as_error_with_json_500(caplog):
    client = TestClient(_make_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/api/boom")

    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal Server Error"}
    http_lines = [r for r in _req_records(caplog) if r.getMessage().startswith("[HTTP]")]
    assert len(http_lines) == 1
    assert http_lines[0].levelno == logging.ERROR
    assert "未捕获异常" in http_lines[0].getMessage()
    # 异常处理器产出的 500 响应走完成行：ERROR 且带 handler 归因
    completions = [r for r in _completion_records(caplog) if "/api/boom" in r.getMessage()]
    assert len(completions) == 1
    assert completions[0].levelno == logging.ERROR
    assert "-> 500" in completions[0].getMessage()


def test_streaming_response_not_buffered(caplog):
    client = TestClient(_make_app())
    with caplog.at_level(logging.DEBUG, logger="backend.request"):
        resp = client.get("/api/stream")

    assert resp.status_code == 200
    assert resp.content == b"chunk1chunk2"
    completions = [r for r in _completion_records(caplog) if "/api/stream" in r.getMessage()]
    assert len(completions) == 1
    assert completions[0].levelno == logging.INFO
    assert "-> 200" in completions[0].getMessage()


def test_request_context_filter_defaults_to_dash():
    record = logging.LogRecord(
        "some.logger", logging.INFO, __file__, 1, "message", None, None,
    )
    assert RequestContextFilter().filter(record) is True
    assert record.req_id == "-"


def test_request_id_contextvar_roundtrip():
    token = request_id_var.set("abcd1234")
    try:
        assert get_request_id() == "abcd1234"
    finally:
        request_id_var.reset(token)
    assert get_request_id() == ""


def test_get_runtime_logger_returns_module_namespace():
    assert get_runtime_logger("backend.foo").name == "backend.foo"


@pytest.mark.parametrize("raw,expected", [
    ("DEBUG", logging.DEBUG),
    ("INFO", logging.INFO),
    ("warning", logging.WARNING),
    ("BOGUS", logging.INFO),
    ("", logging.INFO),
])
def test_log_level_env_parsing_semantics(raw, expected):
    """VELLUMA_LOG_LEVEL 解析语义锁：非法值回退 INFO（main._resolve_log_level）。"""
    import os

    from backend.main import _resolve_log_level

    old = os.environ.get("VELLUMA_LOG_LEVEL")
    try:
        os.environ["VELLUMA_LOG_LEVEL"] = raw
        assert _resolve_log_level() == expected
    finally:
        if old is None:
            os.environ.pop("VELLUMA_LOG_LEVEL", None)
        else:
            os.environ["VELLUMA_LOG_LEVEL"] = old

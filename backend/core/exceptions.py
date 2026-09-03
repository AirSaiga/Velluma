# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""HTTP 异常工厂（2026-09-04 审计清理后收敛版）。

清理说明：原文件里的 BusinessException 异常类族与 conflict/timeout_error/
require_not_none/require_condition 全部零 raise 零 import（且异常类不是
HTTPException 子类、无注册 handler，误用即 500）——已删除。仅保留在役的
HTTPException 工厂：not_found / bad_request / generation_error / timeout_error。
"""
from typing import Optional

from fastapi import HTTPException


def not_found(resource: str, resource_id: Optional[str] = None) -> HTTPException:
    detail = f"{resource}不存在"
    if resource_id:
        detail += f"：{resource_id}"
    return HTTPException(status_code=404, detail=detail)


def bad_request(message: str, field: Optional[str] = None) -> HTTPException:
    detail = f"{message}（{field}）" if field else message
    return HTTPException(status_code=400, detail=detail)


def generation_error(message: str, original_error: Optional[Exception] = None) -> HTTPException:
    detail = message
    if original_error is not None:
        detail = f"{message}：{original_error}"
    return HTTPException(status_code=500, detail=detail)


def timeout_error(operation: str, timeout_seconds: int) -> HTTPException:
    return HTTPException(
        status_code=504,
        detail=f"{operation}超时（>{timeout_seconds}s），请稍后重试",
    )

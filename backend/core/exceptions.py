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
异常处理模块 - 统一错误响应格式

职责：
- 定义标准化的业务异常类
- 提供统一的错误响应构建函数
- 支持错误分类和追踪

设计原则：
- 所有业务错误都有明确的类型和状态码
- 错误消息支持国际化（预留）
- 错误响应包含足够上下文便于调试
"""

from typing import Optional, Dict, Any
from fastapi import HTTPException


# =============================================================================
# 业务异常基类
# =============================================================================

class BusinessException(Exception):
    """
    业务异常基类
    
    所有业务相关异常都应继承此类
    """
    
    def __init__(
        self,
        message: str,
        status_code: int = 500,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.status_code = status_code
        self.error_code = error_code or f"ERR_{status_code}"
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class NotFoundException(BusinessException):
    """资源不存在异常"""
    
    def __init__(self, resource: str, resource_id: Optional[str] = None):
        message = f"{resource}不存在"
        if resource_id:
            message = f"{resource}不存在: {resource_id}"
        super().__init__(
            message=message,
            status_code=404,
            error_code="ERR_NOT_FOUND",
            details={"resource": resource, "resource_id": resource_id}
        )


class ValidationException(BusinessException):
    """参数验证异常"""
    
    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message=message,
            status_code=400,
            error_code="ERR_VALIDATION",
            details={"field": field} if field else {}
        )


class ConflictException(BusinessException):
    """资源冲突异常（如重复发布）"""
    
    def __init__(self, message: str):
        super().__init__(
            message=message,
            status_code=409,
            error_code="ERR_CONFLICT"
        )


class GenerationException(BusinessException):
    """AI 生成异常"""
    
    def __init__(self, message: str, stage: Optional[str] = None):
        super().__init__(
            message=message,
            status_code=500,
            error_code="ERR_GENERATION",
            details={"stage": stage} if stage else {}
        )


class TimeoutException(BusinessException):
    """操作超时异常"""
    
    def __init__(self, operation: str, timeout_seconds: float):
        super().__init__(
            message=f"{operation}操作超时（{timeout_seconds}秒）",
            status_code=504,
            error_code="ERR_TIMEOUT",
            details={"operation": operation, "timeout": timeout_seconds}
        )


# =============================================================================
# HTTPException 构建函数
# =============================================================================

def not_found(resource: str, resource_id: Optional[str] = None) -> HTTPException:
    """
    创建 404 错误响应
    
    Args:
        resource: 资源类型（如"书籍"、"章节"）
        resource_id: 资源ID（可选）
        
    Returns:
        HTTPException with 404 status
    """
    message = f"{resource}不存在"
    if resource_id:
        message = f"{resource}不存在: {resource_id}"
    return HTTPException(status_code=404, detail=message)


def bad_request(message: str, field: Optional[str] = None) -> HTTPException:
    """
    创建 400 错误响应
    
    Args:
        message: 错误消息
        field: 相关字段（可选）
        
    Returns:
        HTTPException with 400 status
    """
    detail = message
    if field:
        detail = f"{field}: {message}"
    return HTTPException(status_code=400, detail=detail)


def conflict(message: str) -> HTTPException:
    """
    创建 409 冲突错误响应
    
    Args:
        message: 错误消息
        
    Returns:
        HTTPException with 409 status
    """
    return HTTPException(status_code=409, detail=message)


def generation_error(message: str, original_error: Optional[Exception] = None) -> HTTPException:
    """
    创建生成错误响应
    
    Args:
        message: 错误消息
        original_error: 原始异常（可选）
        
    Returns:
        HTTPException with 500 status
    """
    detail = message
    if original_error:
        detail = f"{message}: {str(original_error)}"
    return HTTPException(status_code=500, detail=detail)


def timeout_error(operation: str, timeout_seconds: float) -> HTTPException:
    """
    创建超时错误响应
    
    Args:
        operation: 操作名称
        timeout_seconds: 超时时间
        
    Returns:
        HTTPException with 504 status
    """
    return HTTPException(
        status_code=504,
        detail=f"{operation}操作超时（{timeout_seconds}秒）"
    )


# =============================================================================
# 便捷验证函数
# =============================================================================

def require_not_none(value: Any, name: str) -> None:
    """
    验证值不为 None，否则抛出 404
    
    Args:
        value: 要验证的值
        name: 值名称（用于错误消息）
        
    Raises:
        HTTPException: 如果值为 None
    """
    if value is None:
        raise not_found(name)


def require_condition(condition: bool, message: str, field: Optional[str] = None) -> None:
    """
    验证条件为真，否则抛出 400
    
    Args:
        condition: 要验证的条件
        message: 错误消息
        field: 相关字段（可选）
        
    Raises:
        HTTPException: 如果条件为假
    """
    if not condition:
        raise bad_request(message, field)

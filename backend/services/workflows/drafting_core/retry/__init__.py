"""
重试引擎模块 - 提供 LLM 调用失败时的重试机制。

职责：
- 管理生成失败的重试逻辑
- 动态调整生成参数（温度等）
- 记录重试历史用于分析

重试策略：
- RetryEngine: 统一重试执行器
- ParameterAdjuster: 参数调整器，根据失败类型调整参数

使用方式：
    from backend.services.workflows.drafting_core.retry import RetryEngine

    engine = RetryEngine(config)
    result = await engine.execute_with_retry(generate_func, validate_func)
"""

from backend.services.workflows.drafting_core.retry.retry_engine import RetryEngine
from backend.services.workflows.drafting_core.retry.parameter_adjuster import ParameterAdjuster

__all__ = [
    "RetryEngine",
    "ParameterAdjuster",
]

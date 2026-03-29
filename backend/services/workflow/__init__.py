"""
工作流子模块。

职责：提供章节生成工作流的类型定义和状态管理。

子模块：
- workflow_types.py: 工作流类型定义

使用方式：
    from backend.services.workflow import (
        WorkflowStage,
        WorkflowState,
        WorkflowResult,
        ChapterGenerationOrchestrator,
    )
"""

from backend.services.workflow.workflow_types import (
    WorkflowStage,
    WorkflowState,
    WorkflowResult,
)

__all__ = [
    "WorkflowStage",
    "WorkflowState",
    "WorkflowResult",
]

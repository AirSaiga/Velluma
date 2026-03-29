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
工作流子模块。

职责：提供章节生成工作流的类型定义和状态管理。

子模块：
- workflow_types.py: 工作流类型定义

使用方式：
    from backend.services.workflow import (
        WorkflowStage,
        WorkflowState,
        WorkflowResult,
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

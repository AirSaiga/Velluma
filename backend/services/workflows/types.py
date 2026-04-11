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
工作流类型定义模块。

职责：定义工作流相关的类型、状态和结果。

包含：
- WorkflowStage: 工作流阶段枚举（从 rag 模块统一导入）
- WorkflowState: 工作流状态
- WorkflowResult: 工作流执行结果
"""

from typing import List, Dict, Optional
from pydantic import BaseModel, Field

# 从 rag 模块统一导入 WorkflowStage，避免重复定义
from backend.services.rag import WorkflowStage


class WorkflowState(BaseModel):
    current_stage: WorkflowStage = WorkflowStage.ASSEMBLING
    iteration: int = 0
    max_iterations: int = 2
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    pre_check_passed: bool = False
    beats: List[Dict] = Field(default_factory=list)
    beat_drafts: List[Dict] = Field(default_factory=list)
    sketch_result: Optional[Dict] = None
    stitched_text: str = ""
    alignment_score: float = 0.0
    review_report: Optional[Dict] = None
    final_text: str = ""

    error_message: str = ""
    error_stage: Optional[str] = None

    llm_calls: int = 0
    total_tokens: int = 0


class WorkflowResult(BaseModel):
    success: bool
    final_text: str = ""
    word_count: int = 0

    character_state_changes: List[Dict] = Field(default_factory=list)
    relationship_state_changes: List[Dict] = Field(default_factory=list)

    pre_check_report: Optional[Dict] = None
    review_report: Optional[Dict] = None

    iterations: int = 0
    llm_calls: int = 0

    error_message: str = ""

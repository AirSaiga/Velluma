"""
工作流类型定义模块。

职责：定义工作流相关的类型、状态和结果。

包含：
- WorkflowStage: 工作流阶段枚举
- WorkflowState: 工作流状态
- WorkflowResult: 工作流执行结果

使用场景：
- workflow/chapter_orchestrator.py: 编排器使用
- workflow/workflow_runner.py: 工作流运行器使用
"""

from enum import Enum
from typing import List, Dict, Optional
from pydantic import BaseModel, Field


class WorkflowStage(str, Enum):
    """工作流阶段"""
    IDLE = "IDLE"
    ASSEMBLING_CONTEXT = "ASSEMBLING_CONTEXT"
    PRE_CHECK = "PRE_CHECK"
    PLANNING = "PLANNING"
    POV_ASSIGNMENT = "POV_ASSIGNMENT"
    DRAFTING = "DRAFTING"
    SKETCH_GENERATION = "SKETCH_GENERATION"
    STITCHING = "STITCHING"
    ADVERSARIAL_ALIGNMENT = "ADVERSARIAL_ALIGNMENT"
    REVIEWING = "REVIEWING"
    REFINING = "REFINING"
    STITCHING_AFTER_REFINE = "STITCHING_AFTER_REFINE"
    POST_CHECK = "POST_CHECK"
    STATE_PERSISTENCE = "STATE_PERSISTENCE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WorkflowState(BaseModel):
    """工作流状态"""
    current_stage: WorkflowStage = WorkflowStage.IDLE
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
    """工作流执行结果"""
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

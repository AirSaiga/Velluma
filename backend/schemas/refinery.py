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
精修流水线（Refinery）Pydantic schemas（V4.1 新建）。

职责：定义精修流水线对外/对内的数据结构。

模块组织：
- Issue / IssueType：诊断产出的问题
- Operation / OperationType：手术计划
- SurgeryResult：手术结果
- HolisticVerdict：整体回读结论
- RefineryResult：总结果
- ConfirmRequest：对话式介入点 2 的作者确认请求

业务场景：
- routes/chapter_generation/refinery.py
- services/refinery/
- 前端 services/api/domain/index.ts 的 refineryApi

依赖项：pydantic.BaseModel
"""

from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
from pydantic import BaseModel, Field


# ============================================================
# 问题类型枚举
# ============================================================

class IssueType(str, Enum):
    """诊断问题类型（覆盖生成质量的所有常见问题）。"""
    TELL_NOT_SHOW = "tell_not_show"          # 直陈该用动作
    PACING_DRAG = "pacing_drag"              # 节奏拖沓
    PACING_BREAK = "pacing_break"            # 节奏断裂（拼接错位）
    SCENE_JUMP = "scene_jump"                # 场景切换突兀
    INFO_LEAK = "info_leak"                  # 信息泄露
    CHARACTER_OFF = "character_off"          # 角色行为不符
    REDUNDANCY = "redundancy"                # 冗余重复
    WEAK_HOOK = "weak_hook"                  # 章末钩子弱
    EMOTION_MISMATCH = "emotion_mismatch"    # 情绪与曲线不符
    CUSTOM = "custom"                        # 作者补充的问题


class IssueSeverity(str, Enum):
    """问题严重程度。"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueStatus(str, Enum):
    """问题处理状态（由对话式介入点更新）。"""
    PENDING = "pending"        # 待作者确认
    CONFIRMED = "confirmed"    # 作者确认要修
    IGNORED = "ignored"        # 作者否决（有意为之）
    AUTO = "auto"              # 自动处理（轻量模式）


class ImpactRadius(str, Enum):
    """问题影响半径（决定手术范围）。"""
    LOCAL = "local"                    # 单段
    MULTI_PARAGRAPH = "multi_paragraph"  # 多段
    GLOBAL = "global"                  # 全文


class OperationType(str, Enum):
    """手术类型。"""
    REWRITE = "rewrite"    # 重写段落
    MERGE = "merge"        # 合并多段
    DELETE = "delete"      # 删除段落
    INSERT = "insert"      # 插入新内容


# ============================================================
# 诊断产出
# ============================================================

class IssueLocation(BaseModel):
    """问题位置（精确定位）。"""
    paragraph: Optional[int] = Field(None, description="段序号（0-based）")
    paragraph_range: Optional[Tuple[int, int]] = Field(None, description="段范围 [start, end]")
    quote: str = Field("", description="引文（精确锚定到文本片段）")
    char_offset: Optional[Tuple[int, int]] = Field(None, description="字符偏移 [start, end]")


class Issue(BaseModel):
    """诊断出的问题。"""
    id: str = Field(..., description="问题 ID，如 I001")
    location: IssueLocation = Field(default_factory=IssueLocation)
    type: str = Field(..., description="问题类型（IssueType 值）")
    severity: str = Field(..., description="high | medium | low")
    diagnosis: str = Field(..., description="诊断说明")
    suggestion: str = Field("", description="建议处理方式")
    impact_radius: str = Field("local", description="local | multi_paragraph | global")
    status: str = Field("pending", description="pending | confirmed | ignored | auto")


class DiagnosticResult(BaseModel):
    """诊断阶段产出。"""
    issues: List[Issue] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 手术计划与执行
# ============================================================

class Operation(BaseModel):
    """手术计划（一个 Operation 处理一个或多个 Issue）。"""
    id: str = Field(..., description="手术 ID，如 OP001")
    issue_ids: List[str] = Field(..., description="处理的 issue id 列表")
    operation_type: str = Field("rewrite", description="OperationType 值")
    target_paragraphs: List[int] = Field(default_factory=list, description="目标段序号")
    context_summary: str = Field("", description="全文上下文摘要（注入手术 prompt）")
    canon_constraints: str = Field("", description="Canon 约束（private 不许泄露等）")


class SurgeryResult(BaseModel):
    """单次手术结果。"""
    operation_id: str
    original_text: str = Field("", description="原文")
    revised_text: str = Field("", description="修改后")
    diff_summary: str = Field("", description="改了什么")
    applied: bool = Field(True, description="是否应用")


class HolisticVerdict(BaseModel):
    """整体回读结论。"""
    verdict: str = Field(..., description="pass | needs_final_touch")
    remaining_issues: List[str] = Field(default_factory=list, description="剩余问题描述")
    final_touch_suggestion: str = Field("", description="最后微调建议")


# ============================================================
# 总结果
# ============================================================

class RefineryStats(BaseModel):
    """精修统计。"""
    raw_word_count: int = 0
    final_word_count: int = 0
    issues_total: int = 0
    issues_confirmed: int = 0
    issues_ignored: int = 0
    operations_executed: int = 0
    holistic_verdict: str = ""
    llm_calls: int = 0


class RefineryResult(BaseModel):
    """精修流水线完整结果。"""
    raw_text: str = Field("", description="原始粗坯")
    issues: List[Issue] = Field(default_factory=list, description="诊断出的问题")
    confirmed_issues: List[Issue] = Field(default_factory=list, description="作者确认的问题")
    operations: List[Operation] = Field(default_factory=list)
    surgeries: List[SurgeryResult] = Field(default_factory=list)
    holistic_verdict: Optional[HolisticVerdict] = None
    polished_text: str = Field("", description="最终抛光后正文")
    stats: Dict[str, Any] = Field(default_factory=dict)
    degraded: List[Dict[str, Any]] = Field(default_factory=list)


# ============================================================
# 对话式介入点 2：作者确认请求
# ============================================================

class IssueDecision(BaseModel):
    """作者对单个 issue 的决策。"""
    issue_id: str
    decision: str = Field(..., description="confirmed | ignored")
    edited_suggestion: Optional[str] = Field(None, description="作者修改后的建议")


class ConfirmRefineryRequest(BaseModel):
    """作者确认问题清单的请求（对话式介入点 2）。"""
    run_id: str = Field(..., description="从 diagnose 阶段获得的 run_id")
    decisions: List[IssueDecision] = Field(default_factory=list)
    custom_issues: List[Issue] = Field(
        default_factory=list,
        description="作者补充的新问题（type=custom）",
    )
    mode: str = Field("deep", description="deep | light（深度模式逐条确认；轻量模式自动处理 medium/low）")


# ============================================================
# 触发精修的请求
# ============================================================

class StartRefineryRequest(BaseModel):
    """启动精修的请求。"""
    chapter_id: str
    raw_text: Optional[str] = Field(None, description="待精修文本（None 时用 chapter.draft_text）")
    mode: str = Field("deep", description="deep | light")
    enable_polish: bool = Field(True, description="是否启用抛光工序")
    canon_context: str = Field("", description="Canon 上下文（从 V4.0 注入）")


class RefineryStage(str, Enum):
    """精修阶段标识（SSE 事件用）。"""
    DIAGNOSTIC = "DIAGNOSTIC"
    DIALOGUE = "DIALOGUE"  # 等待作者确认
    SURGERY = "SURGERY"
    REREAD = "REREAD"
    POLISH = "POLISH"
    COMPLETE = "COMPLETE"

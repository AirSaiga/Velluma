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
质量报告 Pydantic schemas（Phase 2 CP3.1a 新建）。

涵盖：
- FindingItem：LLM 审计产出的单条证据链问题（蓝图 §4.8.2/§4.8.3）
- MetricsBlock：代码级审计产出的量化指标（蓝图 §4.8.1）
- DegradedInfo：审计降级标记（蓝图 §4.8 + decisions §3.5）
- QualityReportResponse：完整报告响应（GET /quality-report）

业务场景：
- routes/chapter_generation 的 GET /api/chapters/{id}/quality-report 端点
- CP3.2 精修阶段读取 findings 作为证据驱动输入
- 前端 QualityReportPanel（CP3.4）展示指标卡片 + findings 列表 + verdict 徽章
"""

from datetime import datetime
from typing import List, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# FindingItem（单条证据链问题）
# ============================================================
# 蓝图 §4.8.3 字段契约：
# - severity: blocker（仅 LLM 审计）/ warning / info
# - category: timeline / characterization / worldview / fact / style
# - quote + offset: 原文引用 + 字符偏移（用于前端跳转高亮）
# - beat_id: 关联的拍序号（用于 CP3.2 局部精修定位目标 beat）
# - detail + suggestion: 问题描述 + 修复建议


class FindingItem(BaseModel):
    """单条审计发现（LLM 证据链产出）。"""

    severity: str = Field(
        ...,
        description="严重性：blocker | warning | info",
    )
    category: str = Field(
        ...,
        description="问题维度：timeline | characterization | worldview | fact | style",
    )
    quote: Optional[str] = Field(
        None,
        description="原文引用（证据）",
    )
    offset: Optional[Tuple[int, int]] = Field(
        None,
        description="字符偏移 [start, end]，前端跳转高亮用",
    )
    beat_id: Optional[int] = Field(
        None,
        description="关联拍序号（CP3.2 局部精修定位）",
    )
    detail: str = Field(
        ...,
        description="问题描述（含推理过程）",
    )
    suggestion: Optional[str] = Field(
        None,
        description="修复建议",
    )


# ============================================================
# MetricsBlock（代码级量化指标）
# ============================================================
# 蓝图 §4.8.1 七个 Auditor 产出的指标契约：
# - cliche_hits_per_1k: 禁词命中率（每千字）
# - sentence_len_cv: 句长分布 CV（burstiness），Phase 2 仅参考不阻断
# - dialogue_ratio: 对话占比（0-1）
# - word_achieve_rate: 字数达标率（0-1）
# - red_line_violations: 红线违反次数（整数）
# extra=allow 保持向前兼容（CP3.1b 可能新增指标）


class MetricsBlock(BaseModel):
    """代码级审计量化指标块。"""

    cliche_hits_per_1k: Optional[float] = Field(
        None,
        description="禁词命中率（每千字）",
    )
    sentence_len_cv: Optional[float] = Field(
        None,
        description="句长分布变异系数 CV（burstiness）；Phase 2 仅参考",
    )
    dialogue_ratio: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="对话占比（0-1）",
    )
    word_achieve_rate: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="字数达标率（0-1）",
    )
    red_line_violations: Optional[int] = Field(
        None,
        ge=0,
        description="红线引号词硬校验违反次数",
    )

    class Config:
        extra = "allow"


# ============================================================
# DegradedInfo（降级标记）
# ============================================================
# 承接"失败不静默"原则（蓝图 P5）：
# - reason: 降级原因（如 llm_parse_failed / auditor_timeout）
# - action: 采取的兜底动作（如 retry_exhausted / mark_unaudited）
# - detail: 可选补充细节


class DegradedInfo(BaseModel):
    """审计降级标记（失败不静默）。"""

    reason: str = Field(..., description="降级原因")
    action: str = Field(..., description="兜底动作")
    detail: Optional[str] = Field(None, description="补充细节")


# ============================================================
# QualityReportResponse（完整报告响应）
# ============================================================
# 与 ORM QualityReport 字段对齐，Pydantic 校验输出契约
# verdict 取值：pass / pass_with_fixes / fail / unaudited（降级时）


class QualityReportResponse(BaseModel):
    """质量报告响应（GET /api/chapters/{id}/quality-report）。"""

    id: UUID
    chapter_id: UUID
    run_id: Optional[str] = None
    metrics: MetricsBlock = Field(
        default_factory=MetricsBlock,
        description="代码级量化指标块",
    )
    findings: List[FindingItem] = Field(
        default_factory=list,
        description="LLM 证据链问题列表",
    )
    degraded: Optional[DegradedInfo] = Field(
        None,
        description="降级标记（若有）",
    )
    verdict: Optional[str] = Field(
        None,
        description="审计结论：pass / pass_with_fixes / fail / unaudited",
    )
    created_at: datetime

    class Config:
        from_attributes = True

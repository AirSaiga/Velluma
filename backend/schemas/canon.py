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
Canon（作者脑中世界图谱）Pydantic schemas（V4.0 新建）。

职责：定义 Canon REST API 对外的数据模型。

模块组织：
- CanonNodeCreate / CanonNodeUpdate / CanonNodeResponse：节点 CRUD
- CanonEdgeCreate / CanonEdgeUpdate / CanonEdgeResponse：边 CRUD
- CanonGraphResponse：整书图谱（可视化主查询）
- ImpactAnalysisRequest / ImpactAnalysisResponse：变更连锁分析
- ConsistencyCheckRequest / ConsistencyCheckResponse：一致性检查
- CanonExtractionRequest / CanonExtractionResponse：自动提取

业务场景：
- routes/canon.py 的 REST API
- 前端 services/api/domain/canon.api.ts

依赖项：pydantic.BaseModel
"""

from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field


# ============================================================
# 节点 schemas
# ============================================================

class CanonNodeBase(BaseModel):
    """节点公共字段。"""
    type: str = Field(..., description="节点类型：character|event|object|place|hook")
    label: str = Field(..., min_length=1, max_length=200, description="显示名")
    canon_text: str = Field("", description="作者脑中的完整真相")
    public_text: str = Field("", description="读者目前看到的描述")
    visibility: str = Field("public", description="public|private|partial")
    reveal_plan: str = Field("", description="揭示计划")
    expected_reveal_chapter: Optional[int] = Field(None, ge=1, description="预期揭示章节")
    tags: List[str] = Field(default_factory=list)
    confidence: str = Field("confirmed", description="confirmed|tentative|draft")
    source: str = Field("author", description="author|auto_extracted|mixed")
    metadata_: Dict[str, Any] = Field(default_factory=dict, alias="metadata", description="自由扩展字段")
    appeared_in: List[int] = Field(default_factory=list, description="出现在哪些章")
    revealed_in: List[int] = Field(default_factory=list, description="在哪些章被揭示")


class CanonNodeCreate(CanonNodeBase):
    """创建节点请求。"""
    book_id: UUID


class CanonNodeUpdate(BaseModel):
    """更新节点请求（所有字段可选）。"""
    type: Optional[str] = None
    label: Optional[str] = None
    canon_text: Optional[str] = None
    public_text: Optional[str] = None
    visibility: Optional[str] = None
    reveal_plan: Optional[str] = None
    expected_reveal_chapter: Optional[int] = None
    tags: Optional[List[str]] = None
    confidence: Optional[str] = None
    source: Optional[str] = None
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata")
    appeared_in: Optional[List[int]] = None
    revealed_in: Optional[List[int]] = None


class CanonNodeResponse(CanonNodeBase):
    """节点响应。"""
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ============================================================
# 边 schemas
# ============================================================

class CanonEdgeBase(BaseModel):
    """边公共字段。"""
    source_id: UUID
    target_id: UUID
    type: str = Field(..., description="边类型：causes|before|hints|setups|callbacks|echoes")
    strength: int = Field(5, ge=1, le=10)
    visibility: str = Field("public")
    note: str = Field("")
    established_in: List[int] = Field(default_factory=list)
    metadata_: Dict[str, Any] = Field(default_factory=dict, alias="metadata")


class CanonEdgeCreate(CanonEdgeBase):
    """创建边请求。"""
    book_id: UUID


class CanonEdgeUpdate(BaseModel):
    """更新边请求。"""
    type: Optional[str] = None
    strength: Optional[int] = None
    visibility: Optional[str] = None
    note: Optional[str] = None
    established_in: Optional[List[int]] = None
    metadata_: Optional[Dict[str, Any]] = Field(None, alias="metadata")


class CanonEdgeResponse(CanonEdgeBase):
    """边响应。"""
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ============================================================
# 图谱查询
# ============================================================

class CanonGraphResponse(BaseModel):
    """整书图谱响应（前端可视化主查询）。"""
    nodes: List[CanonNodeResponse]
    edges: List[CanonEdgeResponse]


class NeighborsResponse(BaseModel):
    """邻居查询响应（变更连锁分析用）。"""
    center: CanonNodeResponse
    nodes: List[CanonNodeResponse]
    edges: List[CanonEdgeResponse]


# ============================================================
# 一致性检查
# ============================================================

class ConsistencyIssue(BaseModel):
    """一致性问题。"""
    severity: str = Field(..., description="warning|error|info")
    kind: str = Field(..., description="private_leak|contradiction|missing_setup|orphan_hook")
    node_id: Optional[str] = None
    node_label: Optional[str] = None
    detail: str = Field(..., description="问题描述")
    evidence: Optional[str] = Field(None, description="证据引文")
    suggestions: List[str] = Field(default_factory=list, description="处理建议")


class ConsistencyCheckResponse(BaseModel):
    """一致性检查响应。"""
    issues: List[ConsistencyIssue]
    stats: Dict[str, Any]


# ============================================================
# 变更连锁分析
# ============================================================

class ImpactItem(BaseModel):
    """单个受影响项。"""
    node_id: str
    node_label: str
    node_type: str
    impact_type: str = Field(..., description="contradiction|tone_shift|requires_setup|ok")
    detail: str
    suggestions: List[str] = Field(default_factory=list)


class ImpactAnalysisResponse(BaseModel):
    """变更连锁分析响应。"""
    changed_node: CanonNodeResponse
    affected: List[ImpactItem]
    total_affected: int


# ============================================================
# 自动提取
# ============================================================

class CanonExtractionRequest(BaseModel):
    """自动提取请求（从已发布章节提取候选节点/边）。"""
    chapter_id: UUID
    auto_commit: bool = Field(False, description="False=进待确认队列，True=直接进 Canon")


class CanonExtractionResponse(BaseModel):
    """自动提取响应。"""
    extracted_nodes: List[Dict[str, Any]]
    extracted_edges: List[Dict[str, Any]]
    committed: bool
    message: str


# ============================================================
# 待确认队列
# ============================================================

class PendingEntry(BaseModel):
    """待确认队列项。"""
    id: str
    kind: str = Field(..., description="node|edge")
    payload: Dict[str, Any]
    source_chapter: Optional[int] = None
    created_at: datetime


class PendingResponse(BaseModel):
    """待确认队列响应。"""
    entries: List[PendingEntry]

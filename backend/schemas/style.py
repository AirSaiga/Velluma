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
文风体系 Pydantic schemas（Phase 1 CP2.2 新建）。

涵盖：
- StyleCard（文风卡：正面画像 + 负面清单 + 量化指标）
- AuthorSample（作者样本库）
- SystemCliche（系统禁词表）
- StyleExtract（Match My Style 提炼请求/响应）

业务场景：
- routes/style.py 的 API 端点用这些 schema 做请求/响应校验
- ContextEngine 读取 StyleCard 渲染 P0 文风段
"""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# StyleCard（文风卡）
# ============================================================

class StyleCardBase(BaseModel):
    """文风卡基础字段。"""
    positive_profile: dict = Field(
        default_factory=dict,
        description="正面画像：句长节奏/词汇层级/语域/开头结尾习惯等",
    )
    negative_list: List[dict] = Field(
        default_factory=list,
        description="负面清单：[{word/phrase, alternative}]，每条禁令配正面替代",
    )
    dialogue_ratio_target: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="对话占比目标（0-1）",
    )
    paragraph_rhythm: Optional[str] = Field(None, description="段落节奏说明")
    notes: Optional[str] = Field(None, description="备注")


class StyleCardCreate(StyleCardBase):
    """创建文风卡（书级或章级覆盖）。"""
    chapter_id: Optional[UUID] = Field(None, description="非空表示章级覆盖")


class StyleCardUpdate(BaseModel):
    """更新文风卡（所有字段可选）。"""
    positive_profile: Optional[dict] = None
    negative_list: Optional[List[dict]] = None
    dialogue_ratio_target: Optional[float] = Field(None, ge=0.0, le=1.0)
    paragraph_rhythm: Optional[str] = None
    notes: Optional[str] = None


class StyleCardResponse(StyleCardBase):
    """文风卡响应。"""
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# AuthorSample（作者样本库）
# ============================================================

class AuthorSampleBase(BaseModel):
    """作者样本基础字段。"""
    scene_type: str = Field("general", description="场景类型：dialogue/action/lyrical/suspense/general")
    content: str = Field(..., min_length=1, description="样本原文")
    source: str = Field("manual", description="来源：manual/golden_snippet/published_chapter")


class AuthorSampleCreate(AuthorSampleBase):
    """创建作者样本。"""
    chapter_id: Optional[UUID] = None


class AuthorSampleResponse(AuthorSampleBase):
    """作者样本响应。"""
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    word_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class AuthorSampleSearchRequest(BaseModel):
    """作者样本向量检索请求。"""
    query_text: str = Field(..., min_length=1, description="查询文本（向量化后检索）")
    scene_type: Optional[str] = None
    limit: int = Field(3, ge=1, le=10)


class AuthorSampleSearchHit(BaseModel):
    """向量检索单条命中。"""
    sample: AuthorSampleResponse
    distance: float = Field(..., description="cosine 距离（越小越相似）")


# ============================================================
# SystemCliche（系统禁词表）
# ============================================================

class SystemClicheBase(BaseModel):
    """系统禁词基础字段。"""
    pattern: str = Field(..., min_length=1, max_length=200, description="字面词或正则")
    is_regex: bool = Field(False, description="是否为正则表达式")
    language: str = Field("zh", description="语言：zh/en")
    category: str = Field("cliche", description="类别：cliche/house_voice/transition")
    severity: str = Field("warning", description="严重性：warning/blocker")
    alternative: Optional[str] = Field(None, description="替代建议")
    enabled: bool = Field(True)


class SystemClicheCreate(SystemClicheBase):
    pass


class SystemClicheUpdate(BaseModel):
    pattern: Optional[str] = Field(None, min_length=1, max_length=200)
    is_regex: Optional[bool] = None
    language: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    alternative: Optional[str] = None
    enabled: Optional[bool] = None


class SystemClicheResponse(SystemClicheBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# StyleCard 提炼（Match My Style）
# ============================================================

class StyleExtractRequest(BaseModel):
    """文风画像提炼请求（蓝图 §6.2）。"""
    samples: List[str] = Field(
        ..., min_length=1, max_length=5,
        description="作者样本原文（1-5 段，建议每段 200-2000 字）",
    )
    genre: Optional[str] = Field(None, description="题材（用于兜底画像）")


class StyleExtractResponse(BaseModel):
    """文风画像提炼响应。"""
    positive_profile: dict = Field(..., description="正面画像")
    negative_list: List[dict] = Field(..., description="负面清单")
    dialogue_ratio_target: Optional[float] = None
    paragraph_rhythm: Optional[str] = None
    degraded: Optional[dict] = Field(None, description="提炼降级标记（如有）")


# ============================================================
# ChapterCard（章节卡，CP2.3 用，先在这里定义）
# ============================================================

class MustHitEvent(BaseModel):
    """必达事件。"""
    event: str
    emotion: Optional[str] = None
    must: bool = True


class ChapterCardBase(BaseModel):
    """章节卡基础字段（蓝图 §4.1.3）。"""
    chapter_number: int = Field(..., ge=1)
    purpose: Optional[str] = Field(None, description="一句话主旨（场景化语言）")
    must_hit_events: List[dict] = Field(default_factory=list)
    involved_characters: List[dict] = Field(default_factory=list)
    foreshadow_ops: List[dict] = Field(default_factory=list)
    continuity: dict = Field(default_factory=dict)
    word_target: int = Field(3000, ge=100)
    pacing: str = Field("medium")
    tension: int = Field(5, ge=1, le=10)
    status: str = Field("draft")


class ChapterCardCreate(ChapterCardBase):
    chapter_id: Optional[UUID] = None


class ChapterCardUpdate(BaseModel):
    purpose: Optional[str] = None
    must_hit_events: Optional[List[dict]] = None
    involved_characters: Optional[List[dict]] = None
    foreshadow_ops: Optional[List[dict]] = None
    continuity: Optional[dict] = None
    word_target: Optional[int] = Field(None, ge=100)
    pacing: Optional[str] = None
    tension: Optional[int] = Field(None, ge=1, le=10)
    status: Optional[str] = None


class ChapterCardResponse(ChapterCardBase):
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    style_override_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

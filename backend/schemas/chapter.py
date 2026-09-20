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

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .enums import PacingStyle


class ChapterBase(BaseModel):
    chapter_number: int = Field(..., ge=1)
    chapter_name: Optional[str] = Field(None, max_length=200)
    title: Optional[str] = Field(None, max_length=500)
    outline_text: Optional[str] = None
    content_text: Optional[str] = None
    draft_text: Optional[str] = None
    summary: Optional[str] = None
    review_feedback: Optional[dict] = Field(default_factory=dict)
    map_activity_range: Optional[str] = None
    # 世界页章节叙事时间锚（连续日计数；docs/reports/world-unified-settings.md §2.4）
    narrative_time: Optional[int] = None
    # 本章场景钉（写作桥 W5-lite）：显式钉定本章地点，切片「脚下」第一优先级
    # ⚠ 必须是 UUID 而非 str：ORM 返回 UUID 对象，str 声明会让章节列表响应 500
    scene_location_id: Optional[UUID] = None
    tension_level: int = Field(default=3, ge=1, le=5, description="剧情张力等级 (1-5)，决定工作流层级")
    pacing_style: PacingStyle = Field(default="balanced")
    world_snapshot: Optional[dict] = Field(default=None, description="章节发布时提取的世界状态快照")

    @field_validator('tension_level', mode='before')
    @classmethod
    def clamp_tension_level(cls, v):
        if v is not None:
            try:
                return max(1, min(5, int(v)))
            except (ValueError, TypeError):
                return 3
        return v
    revision_count: int = Field(default=0)
    status: str = Field(default="draft")
    chapter_assets_schema: Optional[str] = None


class ChapterCreate(ChapterBase):
    book_id: UUID


class ChapterUpdate(BaseModel):
    chapter_number: Optional[int] = Field(None, ge=1)
    chapter_name: Optional[str] = Field(None, max_length=200)
    title: Optional[str] = Field(None, max_length=500)
    outline_text: Optional[str] = None
    content_text: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    map_activity_range: Optional[str] = None
    narrative_time: Optional[int] = None
    scene_location_id: Optional[UUID] = None
    tension_level: Optional[int] = Field(None, ge=1, le=5, description="剧情张力等级 (1-5)")
    pacing_style: Optional[PacingStyle] = None
    chapter_assets_schema: Optional[str] = None
    # 意图驱动设置
    creative_intents: Optional[list] = None
    chapter_goals: Optional[list] = None
    selected_plan_type: Optional[str] = None
    user_overrides: Optional[dict] = None
    author_intent: Optional[str] = None

    @field_validator('tension_level', mode='before')
    @classmethod
    def clamp_tension_level(cls, v):
        if v is not None:
            try:
                return max(1, min(5, int(v)))
            except (ValueError, TypeError):
                return None
        return v


class ChapterResponse(ChapterBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

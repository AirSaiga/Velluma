# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

class AssetBase(BaseModel):
    name: str = Field(..., max_length=200, description="资产名称")
    aliases: List[str] = Field(default_factory=list, description="别名列表")
    static_description: Optional[str] = Field(None, description="静态设定（外观、功能等）")
    current_state: Optional[str] = Field(None, description="当前状态（如耐久度、是否激活）")
    importance_level: int = Field(default=1, ge=1, le=5, description="重要性等级 1-5")

class AssetCreate(AssetBase):
    pass

class AssetUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    aliases: Optional[List[str]] = None
    static_description: Optional[str] = None
    current_state: Optional[str] = None
    importance_level: Optional[int] = Field(None, ge=1, le=5)

class AssetResponse(AssetBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

class ChapterAssetResponse(BaseModel):
    id: UUID
    chapter_id: UUID
    asset_id: UUID
    asset: AssetResponse

    class Config:
        from_attributes = True

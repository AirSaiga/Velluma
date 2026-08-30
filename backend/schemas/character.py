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
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CharacterBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    aliases: List[str] = Field(default_factory=list)
    static_prompt: Optional[str] = None
    dynamic_state: Optional[str] = None
    current_state: Optional[str] = None
    importance_level: int = Field(default=1, ge=1, le=10)


class CharacterCreate(CharacterBase):
    book_id: UUID


class CharacterUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    aliases: Optional[List[str]] = None
    static_prompt: Optional[str] = None
    dynamic_state: Optional[str] = None
    current_state: Optional[str] = None
    importance_level: Optional[int] = Field(None, ge=1, le=10)


class CharacterResponse(CharacterBase):
    id: UUID
    book_id: UUID
    created_at: datetime
    dynamic_state_history: List[dict] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CharacterDynamicStateUpdateRequest(BaseModel):
    chapter_id: UUID
    manual_current_state: Optional[str] = None


class CharacterDynamicStateUpdateResponse(BaseModel):
    character_id: UUID
    old_dynamic_state: str
    new_dynamic_state: str


class RelationshipBase(BaseModel):
    source_char_id: UUID
    target_char_id: UUID
    relation_type: str = Field(..., max_length=100)
    affinity_score: int = Field(default=0, ge=-100, le=100)
    interaction_prompt: Optional[str] = None
    is_public: bool = Field(default=True)


class RelationshipCreate(RelationshipBase):
    pass


class RelationshipUpdate(BaseModel):
    relation_type: Optional[str] = Field(None, max_length=100)
    affinity_score: Optional[int] = Field(None, ge=-100, le=100)
    interaction_prompt: Optional[str] = None
    is_public: Optional[bool] = None


class RelationshipResponse(RelationshipBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

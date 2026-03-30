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

from pydantic import BaseModel, Field


class MapLocationBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    current_state: Optional[str] = None


class MapLocationCreate(MapLocationBase):
    book_id: UUID


class MapLocationUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    current_state: Optional[str] = None


class MapLocationResponse(MapLocationBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ChapterMapLocationCreate(BaseModel):
    location_id: UUID


class ChapterMapLocationResponse(BaseModel):
    id: UUID
    chapter_id: UUID
    location_id: UUID
    location: MapLocationResponse

    class Config:
        from_attributes = True

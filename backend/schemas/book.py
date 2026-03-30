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

from .enums import PacingStyle


class BookBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    global_sys_prompt: Optional[str] = None
    core_motifs_taboos: Optional[str] = None
    worldview_settings: Optional[dict] = Field(default_factory=dict)
    golden_snippets: Optional[list] = Field(default_factory=list)
    style_blacklist: Optional[list] = Field(default_factory=list)


class BookCreate(BookBase):
    pass


class BookUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    global_sys_prompt: Optional[str] = None
    core_motifs_taboos: Optional[str] = None
    worldview_settings: Optional[dict] = None
    golden_snippets: Optional[list] = None
    style_blacklist: Optional[list] = None


class BookResponse(BookBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class WorldviewUpdate(BaseModel):
    worldview_settings: dict = Field(default_factory=dict)

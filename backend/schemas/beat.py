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
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from .enums import PovAperture, PovMode


class PersistentStateAnchor(BaseModel):
    anchor_type: str = Field(..., description="锚点类型: unresolved_conflict/emotional_tone/spatial_attachment")
    description: str = Field(..., description="锚点描述")
    involved_characters: List[str] = Field(default_factory=list, description="涉及的角色名列表")


class StoryBeatBase(BaseModel):
    chapter_id: Optional[UUID] = None
    beat_id: Optional[str] = Field(None, min_length=1, max_length=120)
    beat_type: str = Field(default="progression", max_length=100)
    position: int = Field(default=0, ge=0)
    location: Optional[str] = None
    pov_character: Optional[str] = Field(None, max_length=120)
    pov_mode: Optional[PovMode] = Field(
        default=PovMode.SINGLE,
        description="V3.6 叙事视角模式：single(单视角)/ensemble(多角色共存)/omniscient(全知)"
    )
    pov_characters: List[str] = Field(
        default_factory=list,
        description="V3.6 ensemble/omniscient模式下的多视角角色列表"
    )
    pov_aperture: Optional[PovAperture] = Field(default=PovAperture.SUBJECTIVE_OBSERVATION, description="叙事光圈，控制视角景深")
    persistent_state_anchors: List[PersistentStateAnchor] = Field(default_factory=list, description="持久状态锚点列表")
    action_summary: Optional[str] = None
    worldbuilding_instruction: Optional[str] = None
    entry_state: Optional[str] = Field(None, min_length=1)
    exit_state: Optional[str] = Field(None, min_length=1)
    red_lines: List[str] = Field(default_factory=list)
    word_count_target: int = Field(default=0, ge=0)
    summary: str = Field(..., min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="planned", max_length=50)
    pacing_type: Optional[str] = Field(None, max_length=50)
    weight: Optional[int] = Field(default=1, ge=1)


class StoryBeatCreate(StoryBeatBase):
    book_id: UUID


class StoryBeatUpdate(BaseModel):
    chapter_id: Optional[UUID] = None
    beat_id: Optional[str] = Field(None, min_length=1, max_length=120)
    beat_type: Optional[str] = Field(None, max_length=100)
    position: Optional[int] = Field(None, ge=0)
    location: Optional[str] = None
    pov_character: Optional[str] = Field(None, min_length=1, max_length=120)
    pov_mode: Optional[PovMode] = Field(
        default=None,
        description="V3.6 叙事视角模式：single/ensemble/omniscient"
    )
    pov_characters: Optional[List[str]] = Field(
        default=None,
        description="V3.6 ensemble模式下的多视角角色列表"
    )
    pov_aperture: Optional[PovAperture] = Field(None, description="叙事光圈，控制视角景深")
    persistent_state_anchors: Optional[List[PersistentStateAnchor]] = Field(None, description="持久状态锚点列表")
    action_summary: Optional[str] = None
    worldbuilding_instruction: Optional[str] = None
    entry_state: Optional[str] = Field(None, min_length=1)
    exit_state: Optional[str] = Field(None, min_length=1)
    red_lines: Optional[List[str]] = None
    word_count_target: Optional[int] = Field(None, ge=0)
    summary: Optional[str] = Field(None, min_length=1)
    meta: Optional[dict[str, Any]] = None
    status: Optional[str] = Field(None, max_length=50)


class StoryBeatResponse(StoryBeatBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class SceneIntentBase(BaseModel):
    chapter_id: UUID
    story_beat_id: Optional[UUID] = None
    intent_label: str = Field(..., min_length=1, max_length=120)
    character_name: Optional[str] = Field(None, min_length=1, max_length=120)
    goal: str = Field(..., min_length=1)
    obstacle: Optional[str] = None
    tactic: Optional[str] = None
    stakes: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0)


class SceneIntentCreate(SceneIntentBase):
    book_id: UUID


class SceneIntentUpdate(BaseModel):
    chapter_id: Optional[UUID] = None
    story_beat_id: Optional[UUID] = None
    intent_label: Optional[str] = Field(None, min_length=1, max_length=120)
    character_name: Optional[str] = Field(None, min_length=1, max_length=120)
    goal: Optional[str] = Field(None, min_length=1)
    obstacle: Optional[str] = None
    tactic: Optional[str] = None
    stakes: Optional[str] = None
    constraints: Optional[List[str]] = None
    priority: Optional[int] = Field(None, ge=0)


class SceneIntentResponse(SceneIntentBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class PlotLedgerBase(BaseModel):
    chapter_id: Optional[UUID] = None
    story_beat_id: Optional[UUID] = None
    ledger_key: str = Field(..., min_length=1, max_length=150)
    hook_id: Optional[str] = Field(None, min_length=1, max_length=150)
    entry_type: str = Field(default="foreshadow", max_length=50)
    content: str = Field(..., min_length=1)
    status: Literal["open", "closed", "dropped"] = Field(default="open")
    created_at_chapter: Optional[int] = Field(None, ge=1)
    resolved_in_chapter_id: Optional[UUID] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class PlotLedgerCreate(PlotLedgerBase):
    book_id: UUID


class PlotLedgerUpdate(BaseModel):
    chapter_id: Optional[UUID] = None
    story_beat_id: Optional[UUID] = None
    ledger_key: Optional[str] = Field(None, min_length=1, max_length=150)
    hook_id: Optional[str] = Field(None, min_length=1, max_length=150)
    entry_type: Optional[str] = Field(None, max_length=50)
    content: Optional[str] = Field(None, min_length=1)
    status: Optional[Literal["open", "closed", "dropped"]] = None
    created_at_chapter: Optional[int] = Field(None, ge=1)
    resolved_in_chapter_id: Optional[UUID] = None
    meta: Optional[dict[str, Any]] = None


class PlotLedgerResponse(PlotLedgerBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

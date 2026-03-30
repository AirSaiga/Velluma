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

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CharacterTerminalStatus(BaseModel):
    physical_condition: str = Field(
        default="active",
        description="物理状态: active/injured/disabled/inactive/dead"
    )
    current_location_desc: str = Field(
        default="",
        description="当前位置描述"
    )
    immediate_intention: str = Field(
        default="",
        description="即时意图"
    )
    relationship_state: Dict[str, str] = Field(
        default_factory=dict,
        description="与其他角色的关系状态"
    )
    emotional_state: str = Field(
        default="",
        description="情绪状态摘要，20字以内"
    )
    equipment_status: List[str] = Field(
        default_factory=list,
        description="当前装备/持有物品列表"
    )

    @field_validator('physical_condition')
    @classmethod
    def validate_condition(cls, v: str) -> str:
        valid_conditions = [
            "active", "injured", "disabled", "inactive", "dead",
            "昏迷", "轻伤", "重伤", "正常", "离场", "死亡"
        ]
        if v and v.lower() not in [c.lower() for c in valid_conditions]:
            pass
        return v


class SceneTerminalStatus(BaseModel):
    location_summary: str = Field(default="", description="位置摘要")
    physical_anchors: List[str] = Field(default_factory=list, description="物理锚点列表")
    environment_tags: List[str] = Field(default_factory=list, description="环境标签")
    damages: List[str] = Field(default_factory=list, description="场景破坏列表")
    atmosphere: str = Field(default="", description="氛围描述")

    @field_validator('physical_anchors', 'environment_tags', 'damages', mode='before')
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v else []
        return list(v)


class WorldTerminalState(BaseModel):
    scene: SceneTerminalStatus = Field(default_factory=SceneTerminalStatus)
    characters: Dict[str, CharacterTerminalStatus] = Field(default_factory=dict)
    narrative_inertia: str = Field(default="", description="叙事惯性")
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_chapter_id: Optional[str] = Field(default=None)
    source_chapter_number: Optional[int] = Field(default=None)
    version: str = Field(default="3.6")

    @model_validator(mode='after')
    def validate_consistency(self):
        return self

    def to_compact_json(self) -> str:
        import json
        return json.dumps(
            self.model_dump(exclude={'extracted_at'}, mode='json'),
            ensure_ascii=False,
            separators=(',', ':')
        )

    def to_prompt_format(self) -> str:
        lines = [
            "## 【前一章末尾世界状态快照】",
            "",
            f"**场景位置**: {self.scene.location_summary or '未指定'}",
        ]

        if self.scene.environment_tags:
            lines.append(f"**环境特征**: {', '.join(self.scene.environment_tags)}")

        if self.scene.damages:
            lines.append(f"**场景破坏**: {', '.join(self.scene.damages)}")

        if self.scene.physical_anchors:
            lines.append(f"**待处理锚点**: {', '.join(self.scene.physical_anchors)}")

        if self.characters:
            lines.extend(["", "**角色状态**:"])
            for char_id, char_status in self.characters.items():
                condition = char_status.physical_condition
                location = char_status.current_location_desc
                intention = char_status.immediate_intention

                char_line = f"- {char_id}: 状态[{condition}]"
                if location:
                    char_line += f", 位置[{location}]"
                if intention:
                    char_line += f", 意图[{intention}]"
                lines.append(char_line)

        if self.narrative_inertia:
            lines.extend(["", f"**剧情惯性**: {self.narrative_inertia}"])

        lines.extend([
            "",
            "⚠️ **约束提醒**: Beat 1 的 entry_state 必须与上述状态保持 100% 连续性！",
            "⚠️ **角色离场检查**: 状态为 inactive/dead 的角色严禁在本章分配 Beat！"
        ])

        return "\n".join(lines)

    @classmethod
    def from_legacy_snapshot(cls, legacy_snapshot: Dict[str, Any]) -> "WorldTerminalState":
        if not legacy_snapshot:
            return cls()

        scene_data = legacy_snapshot.get("scene_state", {})
        scene = SceneTerminalStatus(
            location_summary=scene_data.get("location", ""),
            physical_anchors=scene_data.get("active_anchors", []),
            damages=scene_data.get("damages", []),
            atmosphere=scene_data.get("current_state", "")
        )

        characters = {}
        char_snapshots = legacy_snapshot.get("character_snapshots", {})
        for char_id, char_data in char_snapshots.items():
            if isinstance(char_data, dict):
                characters[char_id] = CharacterTerminalStatus(
                    physical_condition=char_data.get("status", "active"),
                    current_location_desc=char_data.get("location", ""),
                    immediate_intention=char_data.get("immediate_intention", ""),
                    emotional_state=char_data.get("current_state", "")
                )

        return cls(
            scene=scene,
            characters=characters,
            narrative_inertia=legacy_snapshot.get("narrative_momentum", "")
        )

    @classmethod
    def from_chapter_snapshot(cls, snapshot: Optional[Dict[str, Any]]) -> Optional["WorldTerminalState"]:
        if not snapshot:
            return None

        try:
            return cls.model_validate(snapshot)
        except Exception:
            try:
                return cls.from_legacy_snapshot(snapshot)
            except Exception:
                return None

    def get_active_characters(self) -> Dict[str, CharacterTerminalStatus]:
        active = {}
        for char_id, status in self.characters.items():
            raw_condition = status.physical_condition
            condition_lower = raw_condition.lower()
            is_inactive_english = condition_lower in ["inactive", "dead"]
            is_inactive_chinese = raw_condition in ["离场", "死亡", "昏迷", "失去意识", "重伤无法行动"]
            if not is_inactive_english and not is_inactive_chinese:
                active[char_id] = status
        return active

    def get_character_location(self, char_id: str) -> Optional[str]:
        char = self.characters.get(char_id)
        if char:
            return char.current_location_desc or self.scene.location_summary
        return None

    def has_character(self, char_id: str) -> bool:
        return char_id in self.characters


class StateValidationViolation(BaseModel):
    violation_type: str = Field(description="违规类型")
    message: str = Field(description="违规描述")
    severity: str = Field(default="warning", description="严重程度: error/warning")
    involved_character: Optional[str] = Field(default=None, description="涉及的角色")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class StateValidationResult(BaseModel):
    passed: bool = Field(description="是否通过验证")
    violations: List[StateValidationViolation] = Field(default_factory=list)
    warnings: List[StateValidationViolation] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == "error" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0 or any(v.severity == "warning" for v in self.violations)


def merge_world_states(
    previous: Optional[WorldTerminalState],
    current: WorldTerminalState
) -> WorldTerminalState:
    if not previous:
        return current

    merged_chars = dict(previous.characters)
    merged_chars.update(current.characters)

    merged_scene = previous.scene.model_copy(update={
        k: v for k, v in current.scene.model_dump().items() if v
    })

    return WorldTerminalState(
        scene=merged_scene,
        characters=merged_chars,
        narrative_inertia=current.narrative_inertia or previous.narrative_inertia,
        source_chapter_id=current.source_chapter_id,
        extracted_at=current.extracted_at
    )

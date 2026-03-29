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
角色状态类型定义模块 - 角色状态机相关类型定义。

职责：
- 定义角色状态枚举（存活/受伤/死亡等）
- 定义角色位置枚举
- 定义情绪状态枚举
- 定义物理状态枚举
- 定义状态转换规则
- 定义角色静态/动态状态数据结构

业务场景：
- 角色状态机管理
- 章节生成时的状态约束
- 状态历史记录

主要功能：
- 状态枚举定义
- 转换规则定义
- 状态数据结构

依赖项：
- pydantic: 数据验证
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from dataclasses import dataclass


class CharacterStatus(str, Enum):
    ALIVE = "alive"
    INJURED = "injured"
    CRITICAL = "critical"
    DECEASED = "deceased"
    UNKNOWN = "unknown"


class CharacterLocation(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    OFFSCREEN = "offscreen"
    TRAVELING = "traveling"
    UNKNOWN = "unknown"


class EmotionalState(str, Enum):
    CALM = "calm"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    SAD = "sad"
    JOYFUL = "joyful"
    FEARFUL = "fearful"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class PhysicalCondition(str, Enum):
    HEALTHY = "healthy"
    FATIGUED = "fatigued"
    INJURED = "injured"
    CRITICAL = "critical"
    UNCONSCIOUS = "unconscious"
    INCAPACITATED = "incapacitated"


class RelationshipType(str, Enum):
    FAMILY = "family"
    FRIEND = "friend"
    LOVER = "lover"
    ALLY = "ally"
    ENEMY = "enemy"
    RIVAL = "rival"
    STRANGER = "stranger"
    MENTOR = "mentor"
    STUDENT = "student"


class RelationshipStage(str, Enum):
    STRANGER = "stranger"
    ACQUAINTANCE = "acquaintance"
    FAMILIAR = "familiar"
    CLOSE = "close"
    INTIMATE = "intimate"
    ESTRANGED = "estranged"
    HOSTILE = "hostile"
    ARCHENEMY = "archenemy"


class StateChangeType(str, Enum):
    GRADUAL = "gradual"
    ABRUPT = "abrupt"
    CRITICAL = "critical"
    INVALID = "invalid"


@dataclass
class StateTransitionRule:
    from_state: str
    to_state: str
    allowed: bool
    requires_explanation: bool = False
    explanation_min_length: int = 50


class CharacterStaticPortrait(BaseModel):
    name: str = Field(..., description="角色名称")
    aliases: List[str] = Field(default_factory=list, description="别名/绰号")
    age: Optional[str] = Field(None, description="年龄/年龄段")
    gender: Optional[str] = Field(None, description="性别")
    appearance: str = Field(default="", description="外貌描写")
    personality: str = Field(default="", description="性格特点")
    background: str = Field(default="", description="背景故事")
    abilities: List[str] = Field(default_factory=list, description="能力/技能")
    weaknesses: List[str] = Field(default_factory=list, description="弱点/缺陷")
    core_traits: List[str] = Field(default_factory=list, description="核心特质（不可改变）")
    immutable_facts: List[str] = Field(default_factory=list, description="不可变事实")

    def to_prompt_context(self, max_length: int = 500) -> str:
        parts = [f"【{self.name}】"]
        if self.aliases:
            parts.append(f"别名：{'、'.join(self.aliases)}")
        if self.age:
            parts.append(f"年龄：{self.age}")
        if self.appearance:
            parts.append(f"外貌：{self.appearance[:200]}")
        if self.personality:
            parts.append(f"性格：{self.personality[:200]}")
        if self.core_traits:
            parts.append(f"核心特质：{'、'.join(self.core_traits)}")
        result = "\n".join(parts)
        return result[:max_length]


class CharacterDynamicState(BaseModel):
    physical_condition: PhysicalCondition = Field(
        default=PhysicalCondition.HEALTHY,
        description="物理状态"
    )
    location: CharacterLocation = Field(
        default=CharacterLocation.PRESENT,
        description="位置状态"
    )
    current_place: Optional[str] = Field(None, description="当前位置描述")

    emotional_state: EmotionalState = Field(
        default=EmotionalState.NEUTRAL,
        description="情感状态"
    )
    emotional_notes: str = Field(default="", description="情感状态说明")

    current_goal: str = Field(default="", description="当前目标")
    motivation: str = Field(default="", description="行为动机")

    known_secrets: List[str] = Field(default_factory=list, description="已知的秘密")
    beliefs: List[str] = Field(default_factory=list, description="信念/误解")

    is_conscious: bool = Field(default=True, description="是否有意识")
    can_act: bool = Field(default=True, description="是否能行动")
    is_captive: bool = Field(default=False, description="是否被囚禁")

    chapter_number: int = Field(default=0, description="状态所属章节")
    timestamp: Optional[str] = Field(None, description="故事内时间")

    @model_validator(mode="after")
    def validate_state_consistency(self):
        if not self.is_conscious:
            self.can_act = False
        return self

    def to_prompt_context(self) -> str:
        parts = []

        if self.physical_condition != PhysicalCondition.HEALTHY:
            parts.append(f"物理状态：{self.physical_condition.value}")
        if self.current_place:
            parts.append(f"当前位置：{self.current_place}")

        if self.emotional_state != EmotionalState.NEUTRAL:
            parts.append(f"情绪：{self.emotional_state.value}")
            if self.emotional_notes:
                parts.append(f"  说明：{self.emotional_notes}")

        if self.current_goal:
            parts.append(f"当前目标：{self.current_goal}")

        if not self.is_conscious:
            parts.append("⚠️ 无意识状态")
        if not self.can_act:
            parts.append("⚠️ 无法行动")
        if self.is_captive:
            parts.append("⚠️ 被囚禁")

        return "\n".join(parts) if parts else "状态正常"


class CharacterCurrentState(BaseModel):
    is_present_in_scene: bool = Field(default=True, description="是否在场景中")
    action_in_progress: str = Field(default="", description="正在进行的动作")
    last_line: str = Field(default="", description="最后一句台词/动作")

    immediate_emotion: str = Field(default="", description="即时情感反应")
    recent_event_impact: str = Field(default="", description="最近事件的影响")

    locked_attributes: Set[str] = Field(default_factory=set, description="锁定的属性")

    def lock_attribute(self, attr: str) -> None:
        self.locked_attributes.add(attr)

    def is_locked(self, attr: str) -> bool:
        return attr in self.locked_attributes


class CharacterStateHistory(BaseModel):
    chapter_number: int
    timestamp: datetime
    previous_state: CharacterDynamicState
    new_state: CharacterDynamicState
    change_reason: str
    change_type: StateChangeType

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "timestamp": self.timestamp.isoformat(),
            "change_reason": self.change_reason,
            "change_type": self.change_type.value,
            "previous": self.previous_state.model_dump(),
            "new": self.new_state.model_dump(),
        }

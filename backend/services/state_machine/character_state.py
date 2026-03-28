# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
角色状态机 (Character State Machine)

职责：
- 定义角色状态的三层架构：静态画像、动态状态、当前状态
- 管理角色状态的合法流转
- 提供状态变化约束与校验
- 支持 OOC (Out of Character) 检测

设计原则：
1. 静态画像（Static Portrait）：永恒不变的核心设定
2. 动态状态（Dynamic State）：章节级别的状态快照
3. 当前状态（Current State）：实时状态，可被生成过程更新
4. 历史状态（State History）：状态变化的时间线记录

状态流转约束：
- 静态画像 → 禁止修改（除非管理员手动操作）
- 动态状态 → 仅在章节发布时更新
- 当前状态 → 生成过程中可更新，但必须符合约束
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from dataclasses import dataclass, field as dataclass_field
import re
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# 枚举定义
# =============================================================================

class CharacterStatus(str, Enum):
    """角色存活状态"""
    ALIVE = "alive"
    INJURED = "injured"
    CRITICAL = "critical"
    DECEASED = "deceased"
    UNKNOWN = "unknown"


class CharacterLocation(str, Enum):
    """角色位置状态"""
    PRESENT = "present"          # 在场
    ABSENT = "absent"            # 不在场
    OFFSCREEN = "offscreen"      # 幕后
    TRAVELING = "traveling"      # 移动中
    UNKNOWN = "unknown"


class EmotionalState(str, Enum):
    """情感状态"""
    CALM = "calm"
    ANXIOUS = "anxious"
    ANGRY = "angry"
    SAD = "sad"
    JOYFUL = "joyful"
    FEARFUL = "fearful"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class PhysicalCondition(str, Enum):
    """物理状态"""
    HEALTHY = "healthy"
    FATIGUED = "fatigued"
    INJURED = "injured"
    CRITICAL = "critical"  # 危急状态
    UNCONSCIOUS = "unconscious"
    INCAPACITATED = "incapacitated"


class RelationshipType(str, Enum):
    """关系类型"""
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
    """关系阶段"""
    STRANGER = "stranger"          # 陌生人
    ACQUAINTANCE = "acquaintance"  # 泛泛之交
    FAMILIAR = "familiar"          # 熟人
    CLOSE = "close"                # 亲密
    INTIMATE = "intimate"          # 极亲密
    ESTRANGED = "estranged"        # 疏远
    HOSTILE = "hostile"            # 敌对
    ARCHENEMY = "archenemy"        # 死敌


class StateChangeType(str, Enum):
    """状态变化类型"""
    GRADUAL = "gradual"      # 渐变（合理）
    ABRUPT = "abrupt"        # 突变（需解释）
    CRITICAL = "critical"    # 关键转折（必须解释）
    INVALID = "invalid"      # 非法变化


# =============================================================================
# 角色状态定义
# =============================================================================

class CharacterStaticPortrait(BaseModel):
    """
    角色静态画像 - 永恒不变的核心设定
    
    来源：Character.static_prompt
    更新时机：仅管理员手动编辑
    约束：禁止通过 LLM 生成修改
    """
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
        """生成 Prompt 上下文"""
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
    """
    角色动态状态 - 章节级别的状态快照
    
    来源：Character.dynamic_state
    更新时机：章节发布时
    约束：必须符合静态画像，不能违反 immutable_facts
    """
    # 物理状态
    physical_condition: PhysicalCondition = Field(
        default=PhysicalCondition.HEALTHY,
        description="物理状态"
    )
    location: CharacterLocation = Field(
        default=CharacterLocation.PRESENT,
        description="位置状态"
    )
    current_place: Optional[str] = Field(None, description="当前位置描述")
    
    # 情感状态
    emotional_state: EmotionalState = Field(
        default=EmotionalState.NEUTRAL,
        description="情感状态"
    )
    emotional_notes: str = Field(default="", description="情感状态说明")
    
    # 目标与动机
    current_goal: str = Field(default="", description="当前目标")
    motivation: str = Field(default="", description="行为动机")
    
    # 知识与记忆
    known_secrets: List[str] = Field(default_factory=list, description="已知的秘密")
    beliefs: List[str] = Field(default_factory=list, description="信念/误解")
    
    # 关键状态
    is_conscious: bool = Field(default=True, description="是否有意识")
    can_act: bool = Field(default=True, description="是否能行动")
    is_captive: bool = Field(default=False, description="是否被囚禁")
    
    # 状态元数据
    chapter_number: int = Field(default=0, description="状态所属章节")
    timestamp: Optional[str] = Field(None, description="故事内时间")
    
    @model_validator(mode="after")
    def validate_state_consistency(self):
        """验证状态一致性"""
        # 无意识状态下不能行动
        if not self.is_conscious:
            self.can_act = False
        return self
    
    def to_prompt_context(self) -> str:
        """生成 Prompt 上下文"""
        parts = []
        
        # 物理状态
        if self.physical_condition != PhysicalCondition.HEALTHY:
            parts.append(f"物理状态：{self.physical_condition.value}")
        if self.current_place:
            parts.append(f"当前位置：{self.current_place}")
        
        # 情感状态
        if self.emotional_state != EmotionalState.NEUTRAL:
            parts.append(f"情绪：{self.emotional_state.value}")
            if self.emotional_notes:
                parts.append(f"  说明：{self.emotional_notes}")
        
        # 目标
        if self.current_goal:
            parts.append(f"当前目标：{self.current_goal}")
        
        # 状态标记
        if not self.is_conscious:
            parts.append("⚠️ 无意识状态")
        if not self.can_act:
            parts.append("⚠️ 无法行动")
        if self.is_captive:
            parts.append("⚠️ 被囚禁")
        
        return "\n".join(parts) if parts else "状态正常"


class CharacterCurrentState(BaseModel):
    """
    角色当前状态 - 实时状态
    
    来源：Character.current_state
    更新时机：生成过程中可更新
    约束：必须与动态状态兼容
    """
    # 实时物理状态
    is_present_in_scene: bool = Field(default=True, description="是否在场景中")
    action_in_progress: str = Field(default="", description="正在进行的动作")
    last_line: str = Field(default="", description="最后一句台词/动作")
    
    # 实时情感
    immediate_emotion: str = Field(default="", description="即时情感反应")
    recent_event_impact: str = Field(default="", description="最近事件的影响")
    
    # 状态锁定（防止生成中状态漂移）
    locked_attributes: Set[str] = Field(default_factory=set, description="锁定的属性")
    
    def lock_attribute(self, attr: str) -> None:
        """锁定属性，防止修改"""
        self.locked_attributes.add(attr)
    
    def is_locked(self, attr: str) -> bool:
        """检查属性是否被锁定"""
        return attr in self.locked_attributes


class CharacterStateHistory(BaseModel):
    """
    角色状态历史记录
    
    存储：Character.dynamic_state_history (JSONB)
    """
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


# =============================================================================
# 角色状态机
# =============================================================================

@dataclass
class StateTransitionRule:
    """状态转换规则"""
    from_state: str
    to_state: str
    allowed: bool
    requires_explanation: bool = False
    explanation_min_length: int = 50


class CharacterStateMachine:
    """
    角色状态机
    
    职责：
    - 管理角色状态的合法流转
    - 检测 OOC (Out of Character) 行为
    - 提供状态变化验证
    - 记录状态变化历史
    """
    
    # 物理状态转换规则
    PHYSICAL_TRANSITIONS: Dict[Tuple[PhysicalCondition, PhysicalCondition], StateTransitionRule] = {
        # 健康状态转换
        (PhysicalCondition.HEALTHY, PhysicalCondition.FATIGUED): StateTransitionRule("healthy", "fatigued", True),
        (PhysicalCondition.HEALTHY, PhysicalCondition.INJURED): StateTransitionRule("healthy", "injured", True, True, 30),
        (PhysicalCondition.HEALTHY, PhysicalCondition.UNCONSCIOUS): StateTransitionRule("healthy", "unconscious", True, True, 50),
        (PhysicalCondition.HEALTHY, PhysicalCondition.INCAPACITATED): StateTransitionRule("healthy", "incapacitated", True, True, 100),
        
        # 疲劳状态转换
        (PhysicalCondition.FATIGUED, PhysicalCondition.HEALTHY): StateTransitionRule("fatigued", "healthy", True, True, 30),
        (PhysicalCondition.FATIGUED, PhysicalCondition.INJURED): StateTransitionRule("fatigued", "injured", True, True, 30),
        (PhysicalCondition.FATIGUED, PhysicalCondition.UNCONSCIOUS): StateTransitionRule("fatigued", "unconscious", True, True, 50),
        
        # 受伤状态转换
        (PhysicalCondition.INJURED, PhysicalCondition.HEALTHY): StateTransitionRule("injured", "healthy", True, True, 100),
        (PhysicalCondition.INJURED, PhysicalCondition.FATIGUED): StateTransitionRule("injured", "fatigued", True),
        (PhysicalCondition.INJURED, PhysicalCondition.CRITICAL): StateTransitionRule("injured", "critical", True, True, 50),
        
        # 无意识状态转换
        (PhysicalCondition.UNCONSCIOUS, PhysicalCondition.HEALTHY): StateTransitionRule("unconscious", "healthy", True, True, 50),
        (PhysicalCondition.UNCONSCIOUS, PhysicalCondition.INJURED): StateTransitionRule("unconscious", "injured", True),
    }
    
    # 情感状态转换规则（定义哪些情感可以突变）
    EMOTIONAL_ABRUPT_ALLOWED: Set[Tuple[EmotionalState, EmotionalState]] = {
        # 可以突然变化到恐惧
        (EmotionalState.CALM, EmotionalState.FEARFUL),
        (EmotionalState.NEUTRAL, EmotionalState.FEARFUL),
        (EmotionalState.JOYFUL, EmotionalState.FEARFUL),
        
        # 可以突然变化到愤怒
        (EmotionalState.CALM, EmotionalState.ANGRY),
        (EmotionalState.SAD, EmotionalState.ANGRY),
        
        # 可以突然变化到悲伤
        (EmotionalState.CALM, EmotionalState.SAD),
        (EmotionalState.JOYFUL, EmotionalState.SAD),
    }
    
    # 不可变的角色属性
    IMMUTABLE_ATTRIBUTES: Set[str] = {
        "name", "gender", "age", "core_traits", "immutable_facts"
    }
    
    def __init__(
        self,
        static_portrait: CharacterStaticPortrait,
        dynamic_state: CharacterDynamicState,
        current_state: Optional[CharacterCurrentState] = None,
    ):
        self.static_portrait = static_portrait
        self.dynamic_state = dynamic_state
        self.current_state = current_state or CharacterCurrentState()
        self._history: List[CharacterStateHistory] = []
        self._violations: List[str] = []
    
    def validate_transition(
        self,
        new_state: CharacterDynamicState,
        context: Optional[str] = None,
    ) -> Tuple[bool, StateChangeType, List[str]]:
        """
        验证状态转换是否合法
        
        Args:
            new_state: 新状态
            context: 转换上下文（事件描述）
        
        Returns:
            Tuple[bool, StateChangeType, List[str]]: 
                (是否合法, 变化类型, 错误/警告列表)
        """
        errors: List[str] = []
        warnings: List[str] = []
        
        # 1. 检查物理状态转换
        physical_change_type = self._validate_physical_transition(
            self.dynamic_state.physical_condition,
            new_state.physical_condition,
            context,
            errors,
            warnings,
        )
        
        # 2. 检查情感状态转换
        emotional_change_type = self._validate_emotional_transition(
            self.dynamic_state.emotional_state,
            new_state.emotional_state,
            context,
            warnings,
        )
        
        # 3. 检查 OOC 违规
        self._check_ooc_violations(new_state, errors, warnings)
        
        # 4. 检查不可变属性
        self._check_immutable_violations(new_state, errors)
        
        # 确定变化类型
        if errors:
            change_type = StateChangeType.INVALID
        elif physical_change_type == StateChangeType.CRITICAL or emotional_change_type == StateChangeType.CRITICAL:
            change_type = StateChangeType.CRITICAL
        elif physical_change_type == StateChangeType.ABRUPT or emotional_change_type == StateChangeType.ABRUPT:
            change_type = StateChangeType.ABRUPT
        else:
            change_type = StateChangeType.GRADUAL
        
        is_valid = len(errors) == 0
        return is_valid, change_type, errors + warnings
    
    def _validate_physical_transition(
        self,
        old: PhysicalCondition,
        new: PhysicalCondition,
        context: Optional[str],
        errors: List[str],
        warnings: List[str],
    ) -> StateChangeType:
        """验证物理状态转换"""
        if old == new:
            return StateChangeType.GRADUAL
        
        key = (old, new)
        rule = self.PHYSICAL_TRANSITIONS.get(key)
        
        if rule is None:
            # 没有定义规则，需要检查是否是跳变
            if new in [PhysicalCondition.HEALTHY]:
                # 恢复健康需要解释
                if not context or len(context) < 50:
                    warnings.append(
                        f"物理状态从 {old.value} 恢复到 {new.value} 需要充分解释"
                    )
                return StateChangeType.ABRUPT
            return StateChangeType.GRADUAL
        
        if not rule.allowed:
            errors.append(
                f"非法物理状态转换：{old.value} → {new.value}"
            )
            return StateChangeType.INVALID
        
        if rule.requires_explanation:
            if not context or len(context) < rule.explanation_min_length:
                warnings.append(
                    f"物理状态从 {old.value} 变为 {new.value} 需要 "
                    f"至少 {rule.explanation_min_length} 字的解释"
                )
            return StateChangeType.ABRUPT
        
        return StateChangeType.GRADUAL
    
    def _validate_emotional_transition(
        self,
        old: EmotionalState,
        new: EmotionalState,
        context: Optional[str],
        warnings: List[str],
    ) -> StateChangeType:
        """验证情感状态转换"""
        if old == new:
            return StateChangeType.GRADUAL
        
        # 检查是否允许突变
        if (old, new) in self.EMOTIONAL_ABRUPT_ALLOWED:
            return StateChangeType.ABRUPT
        
        # 其他情感变化应该是渐变的
        if context:
            # 有上下文解释，标记为突变
            return StateChangeType.ABRUPT
        
        warnings.append(
            f"情感状态从 {old.value} 变为 {new.value} 建议提供上下文"
        )
        return StateChangeType.GRADUAL
    
    def _check_ooc_violations(
        self,
        new_state: CharacterDynamicState,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        """检查 OOC 违规"""
        # 检查核心特质是否被违反
        for trait in self.static_portrait.core_traits:
            if self._is_trait_violated(trait, new_state):
                errors.append(f"核心特质违反：{trait}")
    
    def _is_trait_violated(self, trait: str, state: CharacterDynamicState) -> bool:
        """检查特质是否被违反"""
        # 简化实现：检查状态描述中是否有矛盾
        # 实际实现需要更复杂的语义分析
        return False
    
    def _check_immutable_violations(
        self,
        new_state: CharacterDynamicState,
        errors: List[str],
    ) -> None:
        """检查不可变属性违规"""
        # 检查动态状态是否违反不可变事实
        for fact in self.static_portrait.immutable_facts:
            if self._is_fact_violated(fact, new_state):
                errors.append(f"不可变事实违反：{fact}")
    
    def _is_fact_violated(self, fact: str, state: CharacterDynamicState) -> bool:
        """检查事实是否被违反"""
        # 简化实现
        return False
    
    def apply_transition(
        self,
        new_state: CharacterDynamicState,
        chapter_number: int,
        reason: str,
        change_type: StateChangeType,
    ) -> CharacterStateHistory:
        """
        应用状态转换
        
        Args:
            new_state: 新状态
            chapter_number: 章节编号
            reason: 转换原因
            change_type: 转换类型
        
        Returns:
            CharacterStateHistory: 状态历史记录
        """
        history = CharacterStateHistory(
            chapter_number=chapter_number,
            timestamp=datetime.now(),
            previous_state=self.dynamic_state.model_copy(deep=True),
            new_state=new_state,
            change_reason=reason,
            change_type=change_type,
        )
        
        self.dynamic_state = new_state
        self._history.append(history)
        
        logger.info(
            f"[CharacterStateMachine] {self.static_portrait.name} "
            f"状态变更: {history.previous_state.physical_condition.value} → "
            f"{new_state.physical_condition.value} ({change_type.value})"
        )
        
        return history
    
    def get_ooc_report(self, proposed_actions: str) -> Dict[str, Any]:
        """
        生成 OOC 检测报告
        
        Args:
            proposed_actions: 提议的动作/行为描述
        
        Returns:
            Dict: OOC 报告
        """
        violations = []
        warnings = []
        
        # 检查角色是否有能力执行提议的动作
        if not self.dynamic_state.can_act:
            violations.append(
                f"{self.static_portrait.name} 当前无法行动，不能执行任何动作"
            )
        
        if not self.dynamic_state.is_conscious:
            violations.append(
                f"{self.static_portrait.name} 处于无意识状态，不能有主动行为"
            )
        
        # 检查角色是否在场
        if not self.current_state.is_present_in_scene:
            warnings.append(
                f"{self.static_portrait.name} 不在当前场景中"
            )
        
        return {
            "character_name": self.static_portrait.name,
            "is_valid": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "current_state_summary": self.dynamic_state.to_prompt_context(),
        }
    
    def to_character_card(self) -> str:
        """生成角色卡片（用于 Prompt）"""
        parts = [
            "=== 角色状态卡片 ===",
            self.static_portrait.to_prompt_context(500),
            "",
            "--- 当前状态 ---",
            self.dynamic_state.to_prompt_context(),
        ]
        
        if self.current_state.action_in_progress:
            parts.append(f"正在进行：{self.current_state.action_in_progress}")
        
        return "\n".join(parts)


# =============================================================================
# 工具函数
# =============================================================================

def create_character_state_machine_from_entity(
    character_entity: Any,
) -> CharacterStateMachine:
    """
    从 Character 实体创建状态机
    
    Args:
        character_entity: Character ORM 实体
    
    Returns:
        CharacterStateMachine: 角色状态机
    """
    # 解析静态画像
    static_prompt = getattr(character_entity, "static_prompt", "") or ""
    static_portrait = _parse_static_prompt(
        getattr(character_entity, "name", "未知角色"),
        static_prompt,
        getattr(character_entity, "aliases", []) or [],
    )
    
    # 解析动态状态
    dynamic_state_str = getattr(character_entity, "dynamic_state", "") or ""
    dynamic_state = _parse_dynamic_state(dynamic_state_str)
    
    # 解析当前状态
    current_state_str = getattr(character_entity, "current_state", "") or ""
    current_state = _parse_current_state(current_state_str)
    
    return CharacterStateMachine(static_portrait, dynamic_state, current_state)


def _parse_static_prompt(
    name: str,
    prompt: str,
    aliases: List[str],
) -> CharacterStaticPortrait:
    """解析静态画像"""
    return CharacterStaticPortrait(
        name=name,
        aliases=aliases,
        appearance=_extract_section(prompt, "外貌"),
        personality=_extract_section(prompt, "性格"),
        background=_extract_section(prompt, "背景"),
        core_traits=_extract_list_section(prompt, "核心特质"),
    )


def _extract_section(text: str, section_name: str) -> str:
    """提取文本中的特定段落"""
    pattern = rf"【{section_name}】(.+?)(?=【|$)"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_list_section(text: str, section_name: str) -> List[str]:
    """提取文本中的列表段落"""
    content = _extract_section(text, section_name)
    if not content:
        return []
    return [item.strip() for item in content.split("、") if item.strip()]


def _parse_dynamic_state(state_str: str) -> CharacterDynamicState:
    """解析动态状态"""
    if not state_str:
        return CharacterDynamicState()
    
    # 简化实现：尝试解析 JSON 或提取关键信息
    # 实际实现需要更复杂的解析逻辑
    return CharacterDynamicState()


def _parse_current_state(state_str: str) -> CharacterCurrentState:
    """解析当前状态"""
    if not state_str:
        return CharacterCurrentState()
    return CharacterCurrentState()

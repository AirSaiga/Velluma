# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
关系状态机 (Relationship State Machine)

职责：
- 定义角色之间的关系状态
- 管理关系阶段的合法流转
- 提供关系变化约束与校验
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class RelationshipStage(str, Enum):
    """关系阶段"""
    STRANGER = "stranger"
    ACQUAINTANCE = "acquaintance"
    FAMILIAR = "familiar"
    CLOSE = "close"
    INTIMATE = "intimate"
    ESTRANGED = "estranged"
    HOSTILE = "hostile"
    ARCHENEMY = "archenemy"


class RelationshipChangeType(str, Enum):
    """关系变化类型"""
    GRADUAL_IMPROVE = "gradual_improve"
    GRADUAL_DECLINE = "gradual_decline"
    ABRUPT_IMPROVE = "abrupt_improve"
    ABRUPT_DECLINE = "abrupt_decline"
    CRITICAL_EVENT = "critical_event"
    INVALID = "invalid"


class RelationshipMetrics(BaseModel):
    """关系度量指标"""
    affinity: int = Field(default=0, ge=-100, le=100)
    trust: int = Field(default=50, ge=0, le=100)
    conflict: int = Field(default=0, ge=0, le=100)
    
    def derive_stage(self) -> RelationshipStage:
        """根据指标推导关系阶段"""
        if self.affinity <= -60:
            return RelationshipStage.ARCHENEMY
        elif self.affinity <= -20:
            return RelationshipStage.HOSTILE
        elif self.affinity <= 20:
            if self.trust <= 20:
                return RelationshipStage.STRANGER
            elif self.trust <= 40:
                return RelationshipStage.ACQUAINTANCE
            return RelationshipStage.FAMILIAR
        elif self.affinity <= 60:
            return RelationshipStage.CLOSE
        return RelationshipStage.INTIMATE


class RelationshipState(BaseModel):
    """关系完整状态"""
    source_char_name: str
    target_char_name: str
    relation_type: str = "acquaintance"
    metrics: RelationshipMetrics = Field(default_factory=RelationshipMetrics)
    stage: RelationshipStage = RelationshipStage.STRANGER
    interaction_pattern: str = ""
    last_interaction_chapter: int = 0
    interaction_count: int = 0
    
    def to_prompt_context(self) -> str:
        """生成 Prompt 上下文"""
        return (
            f"【{self.source_char_name} ↔ {self.target_char_name}】\n"
            f"关系：{self.stage.value} | 类型：{self.relation_type}\n"
            f"亲密度：{self.metrics.affinity} | 信任：{self.metrics.trust}"
        )


class RelationshipStateMachine:
    """关系状态机"""
    
    MAX_SINGLE_AFFINITY_CHANGE = 30
    MAX_SINGLE_TRUST_CHANGE = 20
    
    def __init__(self, state: RelationshipState):
        self.state = state
        self._history: List[Dict] = []
    
    def validate_transition(
        self,
        new_metrics: RelationshipMetrics,
        context: Optional[str] = None,
    ) -> Tuple[bool, RelationshipChangeType, List[str]]:
        """验证关系变化"""
        errors: List[str] = []
        warnings: List[str] = []
        
        affinity_delta = abs(new_metrics.affinity - self.state.metrics.affinity)
        
        if affinity_delta > self.MAX_SINGLE_AFFINITY_CHANGE:
            if not context or len(context) < 50:
                errors.append(f"亲密度变化超出限制: {affinity_delta}")
                return False, RelationshipChangeType.INVALID, errors
            warnings.append(f"亲密度变化较大，需要充分解释")
        
        change_type = RelationshipChangeType.GRADUAL_IMPROVE
        if new_metrics.affinity < self.state.metrics.affinity:
            change_type = RelationshipChangeType.GRADUAL_DECLINE
        elif affinity_delta > 20:
            change_type = RelationshipChangeType.ABRUPT_IMPROVE
        
        return True, change_type, warnings
    
    def apply_transition(
        self,
        new_metrics: RelationshipMetrics,
        chapter_number: int,
        reason: str,
        change_type: RelationshipChangeType,
    ) -> Dict:
        """应用关系变化"""
        new_stage = new_metrics.derive_stage()
        history = {
            "chapter_number": chapter_number,
            "previous_metrics": self.state.metrics.model_dump(),
            "new_metrics": new_metrics.model_dump(),
            "change_reason": reason,
            "change_type": change_type.value,
        }
        self.state.metrics = new_metrics
        self.state.stage = new_stage
        self._history.append(history)
        return history
    
    def change_affinity(
        self,
        delta: int,
        reason: str,
        chapter_number: int,
    ) -> Tuple[bool, RelationshipChangeType]:
        """
        改变亲密度
        
        Args:
            delta: 变化量（正数增加，负数减少）
            reason: 变化原因
            chapter_number: 章节号
        
        Returns:
            Tuple[bool, RelationshipChangeType]: (是否成功, 变化类型)
        """
        new_affinity = max(-100, min(100, self.state.metrics.affinity + delta))
        new_metrics = RelationshipMetrics(
            affinity=new_affinity,
            trust=self.state.metrics.trust,
            conflict=self.state.metrics.conflict,
        )
        
        valid, change_type, _ = self.validate_transition(new_metrics, reason)
        if valid:
            self.apply_transition(new_metrics, chapter_number, reason, change_type)
        return valid, change_type
    
    def transition_to_stage(
        self,
        new_stage: RelationshipStage,
        reason: str,
        chapter_number: int,
    ) -> bool:
        """
        转换到新的关系阶段
        
        Args:
            new_stage: 目标阶段
            reason: 转换原因
            chapter_number: 章节号
        
        Returns:
            bool: 是否成功
        """
        # 检查阶段跳跃是否合法
        stage_order = [
            RelationshipStage.STRANGER,
            RelationshipStage.ACQUAINTANCE,
            RelationshipStage.FAMILIAR,
            RelationshipStage.CLOSE,
            RelationshipStage.INTIMATE,
        ]
        
        current_idx = stage_order.index(self.state.stage) if self.state.stage in stage_order else -1
        target_idx = stage_order.index(new_stage) if new_stage in stage_order else -1
        
        if current_idx >= 0 and target_idx >= 0:
            # 不允许跳跃超过一个阶段
            if abs(target_idx - current_idx) > 1:
                return False
        
        
        self.state.stage = new_stage
        self._history.append({
            "chapter_number": chapter_number,
            "change_type": "stage_transition",
            "previous_stage": self.state.stage.value,
            "new_stage": new_stage.value,
            "change_reason": reason,
        })
        return True
    
    def to_context_string(self) -> str:
        """生成上下文字符串"""
        return self.state.to_prompt_context()

# Velluma - AI Novel Writing Assistant
# 状态机模块导出

"""
角色/关系状态机模块 - 统一导出入口。

职责：
- 统一导出角色和关系状态机相关类型和类
- 提供状态管理和转换约束

子模块：
- character_state: 角色状态机
- character_state_types: 角色状态类型定义
- character_state_machine: 状态机实现
- character_state_factory: 状态机工厂
- relationship_state: 关系状态机

业务场景：
- 章节生成时的状态约束
- 状态合法性验证
- 状态历史记录

依赖项：
- backend.models: 数据模型
"""

from backend.services.state_machine.character_state import (
    CharacterStateMachine,
    CharacterStaticPortrait,
    CharacterDynamicState,
    CharacterCurrentState,
    CharacterStateHistory,
    CharacterStatus,
    CharacterLocation,
    EmotionalState,
    PhysicalCondition,
    StateChangeType,
    create_character_state_machine_from_entity,
)

from backend.services.state_machine.relationship_state import (
    RelationshipStateMachine,
    RelationshipState,
    RelationshipMetrics,
    RelationshipStage,
    RelationshipChangeType,
)

__all__ = [
    # 角色状态机
    "CharacterStateMachine",
    "CharacterStaticPortrait",
    "CharacterDynamicState",
    "CharacterCurrentState",
    "CharacterStateHistory",
    "CharacterStatus",
    "CharacterLocation",
    "EmotionalState",
    "PhysicalCondition",
    "StateChangeType",
    "create_character_state_machine_from_entity",
    
    # 关系状态机
    "RelationshipStateMachine",
    "RelationshipState",
    "RelationshipMetrics",
    "RelationshipStage",
    "RelationshipChangeType",
]

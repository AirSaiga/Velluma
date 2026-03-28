# Velluma - AI Novel Writing Assistant
# 状态机模块导出

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

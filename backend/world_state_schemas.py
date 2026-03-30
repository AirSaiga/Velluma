"""
向后兼容重导出模块 - 所有类型已迁移至 backend.schemas.world_state
"""

from backend.schemas.world_state import (  # noqa: F401
    CharacterTerminalStatus,
    SceneTerminalStatus,
    WorldTerminalState,
    StateValidationViolation,
    StateValidationResult,
    merge_world_states,
)

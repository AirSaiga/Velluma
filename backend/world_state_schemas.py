# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
向后兼容重导出模块 - 所有类型已迁移至 backend.schemas.world_state
"""

from backend.schemas.world_state import (  # noqa: F401
    CharacterTerminalStatus,
    SceneTerminalStatus,
    AssetTerminalStatus,
    WorldTerminalState,
    StateValidationViolation,
    StateValidationResult,
    merge_world_states,
)

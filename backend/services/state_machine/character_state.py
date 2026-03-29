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

from backend.services.state_machine.character_state_types import (
    CharacterStatus,
    CharacterLocation,
    EmotionalState,
    PhysicalCondition,
    RelationshipType,
    RelationshipStage,
    StateChangeType,
    StateTransitionRule,
    CharacterStaticPortrait,
    CharacterDynamicState,
    CharacterCurrentState,
    CharacterStateHistory,
)
from backend.services.state_machine.character_state_machine import CharacterStateMachine
from backend.services.state_machine.character_state_factory import (
    create_character_state_machine_from_entity,
)

__all__ = [
    "CharacterStatus",
    "CharacterLocation",
    "EmotionalState",
    "PhysicalCondition",
    "RelationshipType",
    "RelationshipStage",
    "StateChangeType",
    "StateTransitionRule",
    "CharacterStaticPortrait",
    "CharacterDynamicState",
    "CharacterCurrentState",
    "CharacterStateHistory",
    "CharacterStateMachine",
    "create_character_state_machine_from_entity",
]

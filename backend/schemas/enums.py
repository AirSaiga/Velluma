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

from enum import Enum
from typing import Literal

PacingStyle = Literal["slow_burn", "balanced", "fast_paced"]

WorkflowTier = Literal["TIER_1_FAST", "TIER_2_STANDARD", "TIER_3_FORTRESS"]

ReasoningEffortLevel = Literal["xhigh", "high", "medium", "low", "minimal", "none"]


class PovAperture(str, Enum):
    INTERNAL_ONLY = "internal_only"
    SUBJECTIVE_OBSERVATION = "subjective_observation"
    SYSTEMIC_SENSE = "systemic_sense"


class PovMode(str, Enum):
    SINGLE = "single"
    ENSEMBLE = "ensemble"
    OMNISCIENT = "omniscient"

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""deai 子项目宿主侧服务包（去AI味小模型，docs/deai-integration.md）。"""

from backend.services.deai.client import DeaiResult, is_deai_configured, polish_fragment
from backend.services.deai.gates import FORBIDDEN_WORDS, runtime_gates

__all__ = [
    "DeaiResult",
    "is_deai_configured",
    "polish_fragment",
    "FORBIDDEN_WORDS",
    "runtime_gates",
]

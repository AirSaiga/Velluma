# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
Phase 3: 定档决策器（Tier Decider，V3.2 §4.3）。

职责：
- 薄包装层，调用 adf/tier_classifier.classify_tier（原 detonation 包，已随引擎剥离迁入 adf/）
- 依据 anchor.climax.intensity + chapter_position + user_tier_hint 决定 tier
- 由 tier 推导 target_word_count 与 max_segments

设计意图：
- 不重新发明定档逻辑，复用 V3.1 已验证的算法
- 仅做"从 anchor 派生决策依据"的适配

业务场景：
- workflows/adf/adf_workflow.py Phase 3 调用
"""

import logging
from typing import Any, Dict, Tuple

from backend.models import (
    TIER_AUTO, TIER_CLIMAX, TIER_TURN, TIER_PROGRESS, TIER_TRANSITION,
)
from backend.services.workflows.adf.tier_classifier import classify_tier

logger = logging.getLogger(__name__)


# ============================================================
# Tier → 资源参数映射（V3.2 ADF 专用）
# ============================================================

TIER_TARGET_WORD_COUNT = {
    TIER_CLIMAX: 5000,
    TIER_TURN: 3500,
    TIER_PROGRESS: 2500,
    TIER_TRANSITION: 1500,
}

TIER_MAX_SEGMENTS = {
    TIER_CLIMAX: 7,
    TIER_TURN: 6,
    TIER_PROGRESS: 5,
    TIER_TRANSITION: 4,
}


def decide_tier(
    requested_tier: str,
    climax_intensity: int,
    offset_from_volume_climax: int,
    user_tier_hint: Any = None,
) -> Tuple[str, str, int, int]:
    """Phase 3: 决策定档。

    Args:
        requested_tier: 用户请求的 tier（auto|climax|turn|progress|transition）
        climax_intensity: 远端锚高潮强度自评（1-10）
        offset_from_volume_climax: 距卷高潮的章数
        user_tier_hint: 用户弱信号提示

    Returns:
        tuple: (tier, reason, target_word_count, max_segments)
    """
    if requested_tier != TIER_AUTO:
        # 强制档位
        tier = requested_tier
        reason = f"用户强制指定档位：{tier}"
    else:
        # auto：复用 V3.1 算法（基于 climax_score 与 chapter_position）
        tier_decision = classify_tier(
            candidates=[{"climax_score": climax_intensity}],
            tension_level=None,
            user_tier_hint=user_tier_hint,
        )
        tier = tier_decision.get("tier", TIER_PROGRESS)
        reason = tier_decision.get("reason", f"自动定档：climax_score={climax_intensity}")

    target_wc = TIER_TARGET_WORD_COUNT.get(tier, 2500)
    max_seg = TIER_MAX_SEGMENTS.get(tier, 5)

    logger.info(
        f"[ADF] 定档：tier={tier}, target_word_count={target_wc}, max_segments={max_seg}, "
        f"reason={reason}"
    )
    return tier, reason, target_wc, max_seg

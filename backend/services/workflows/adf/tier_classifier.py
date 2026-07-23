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
章节定档器（V3.1 §2.2 新建）。

职责（规格 §2.2 决策函数）：
根据候选高潮强度自评 + 章节位置 + 章节卡 tension_level + 用户标注，
自主决定本章落在四档（climax/turn/progress/transition）中的哪一档。

核心原则：**宁低勿高**。
- 挂低档的代价是"章平庸但完整"
- 挂高档的代价是"过渡章硬造高潮"（更伤）
- 低估可靠中途升档（§8）修正，高估没有好下场

决策依据（按权重）：
1. 候选高潮强度自评（climax_score，1-10）——主信号
2. 章节在卷/弧中的位置（弧高潮位、卷首卷尾加权）
3. 章节卡 tension_level、word_count
4. 用户显式标注（user_tier_hint，若有）

档位与阈值（基于候选最高 climax_score）：
- climax_score ≥ 8 → climax
- climax_score 5-7 → turn
- climax_score 3-4 → progress
- climax_score ≤ 2 → transition

位置加权（规格 §2.2 依据 2）：
- 卷末倒数 1-2 章：+1 强度（更倾向高档）
- 卷首第 1-2 章：-1 强度（更倾向低档，铺垫章）
- 弧高潮位（若有标注）：+1 强度

最终档位取（强度映射档 vs 位置调整后强度映射档）的较低者（宁低勿高），
但用户强制指定时直接采用。

业务场景：
- UnifiedWorkflow Phase 1 在生成候选后立即调用
- 输出 TierDecision 作为 TIER_DECIDED SSE 事件 payload（通知式，规格 §2.3）
"""

import logging
from typing import Any, Dict, List, Optional

from backend.models import (
    TIER_CLIMAX, TIER_TURN, TIER_PROGRESS, TIER_TRANSITION,
    VALID_TIERS,
    TIER_MAX_DEPTH, TIER_DEVELOPMENT_RATIO,
)

logger = logging.getLogger(__name__)


# climax_score → tier 直接映射（基于候选最高分）
SCORE_TO_TIER_THRESHOLDS = [
    (8, TIER_CLIMAX),       # score >= 8 → climax
    (5, TIER_TURN),         # score >= 5 → turn
    (3, TIER_PROGRESS),     # score >= 3 → progress
    (0, TIER_TRANSITION),   # score < 3 → transition
]

# 档位排序值（用于"宁低勿高"取较低档）
TIER_RANK = {
    TIER_TRANSITION: 0,
    TIER_PROGRESS: 1,
    TIER_TURN: 2,
    TIER_CLIMAX: 3,
}

# 位置加权常量（规格 §2.2 依据 2）
VOLUME_END_BOOST_CHAPTERS = 2   # 卷末倒数 N 章加权
VOLUME_START_PENALTY_CHAPTERS = 2  # 卷首前 N 章降权
VOLUME_END_BOOST = 1             # 卷末位置 +1 强度
VOLUME_START_PENALTY = -1        # 卷首位置 -1 强度


def classify_tier(
    candidates: List[Dict[str, Any]],
    chapter_number: Optional[int] = None,
    total_chapters_in_volume: Optional[int] = None,
    tension_level: Optional[int] = None,
    word_count: Optional[int] = None,
    user_tier_hint: Optional[str] = None,
    forced_tier: Optional[str] = None,
) -> Dict[str, Any]:
    """章节定档决策函数（规格 §2.2，宁低勿高）。

    Args:
        candidates: 高潮点候选列表（含 climax_score 字段）
        chapter_number: 本章序号（用于位置加权）
        total_chapters_in_volume: 本卷总章数（用于判断卷末位置）
        tension_level: 章节卡 tension_level（1-10）
        word_count: 章节卡 word_count
        user_tier_hint: 用户预期档位提示（弱信号，仅 auto 时参考）
        forced_tier: 用户强制指定档位（非 auto 时直接采用，跳过决策）

    Returns:
        dict: TierDecision 字典
            {
                "tier": "climax" | "turn" | "progress" | "transition",
                "reason": "...",
                "climax_score": int,
                "chapter_position_signal": "...",
                "tension_level": int,
                "forced_by_user": bool,
                "max_depth": int,
                "development_ratio": float,
            }
    """
    # ---- 0. 用户强制指定优先 ----
    if forced_tier and forced_tier in VALID_TIERS:
        return _build_decision(
            tier=forced_tier,
            reason="用户强制指定",
            climax_score=None,
            chapter_position_signal=None,
            tension_level=tension_level,
            forced_by_user=True,
        )

    # ---- 1. 取候选最高 climax_score（主信号）----
    scores = [
        c.get("climax_score") for c in candidates
        if isinstance(c, dict) and c.get("climax_score") is not None
    ]
    # 过滤无效分数
    valid_scores = []
    for s in scores:
        try:
            s_int = int(s)
            if 1 <= s_int <= 10:
                valid_scores.append(s_int)
        except (TypeError, ValueError):
            continue

    if valid_scores:
        max_score = max(valid_scores)
        score_source = "候选自评最高分"
    else:
        # 候选无有效分数：fallback 用 tension_level 推断
        max_score = _infer_score_from_tension(tension_level)
        score_source = "候选无强度自评，由 tension_level 推断"

    # ---- 2. 位置加权（规格 §2.2 依据 2）----
    position_signal = None
    position_adjustment = 0
    if chapter_number is not None:
        if total_chapters_in_volume is not None:
            # 已知卷长：判断卷末/卷首
            chapters_to_end = total_chapters_in_volume - chapter_number
            if chapters_to_end < VOLUME_END_BOOST_CHAPTERS:
                position_adjustment = VOLUME_END_BOOST
                position_signal = f"卷末倒数第 {chapters_to_end + 1} 章（+{VOLUME_END_BOOST} 强度）"
            elif chapter_number <= VOLUME_START_PENALTY_CHAPTERS:
                position_adjustment = VOLUME_START_PENALTY
                position_signal = f"卷首第 {chapter_number} 章（{VOLUME_START_PENALTY} 强度，铺垫章倾向）"
            else:
                position_signal = f"卷中第 {chapter_number}/{total_chapters_in_volume} 章（位置无加权）"
        elif chapter_number <= VOLUME_START_PENALTY_CHAPTERS:
            # 未知卷长但章节靠前：轻微降权
            position_adjustment = VOLUME_START_PENALTY
            position_signal = f"靠前章节（第 {chapter_number} 章，倾向铺垫）"

    # 调整后的强度
    adjusted_score = max(0, min(10, max_score + position_adjustment))

    # ---- 3. 强度 → 档位映射 ----
    tier_from_raw_score = _score_to_tier(max_score)
    tier_from_adjusted_score = _score_to_tier(adjusted_score)

    # ---- 4. 用户 hint 作为弱信号（仅能在边界处微调）----
    hint_influence = ""
    if user_tier_hint and user_tier_hint in VALID_TIERS and user_tier_hint != forced_tier:
        # hint 只在"用户预期比决策更低"时采纳（宁低勿高）
        if TIER_RANK[user_tier_hint] < TIER_RANK[tier_from_adjusted_score]:
            tier_from_adjusted_score = user_tier_hint
            hint_influence = f"；用户标注 {user_tier_hint}（采纳为宁低勿高）"

    # ---- 5. 宁低勿高：取两档中较低者 ----
    final_tier = (
        tier_from_raw_score
        if TIER_RANK[tier_from_raw_score] < TIER_RANK[tier_from_adjusted_score]
        else tier_from_adjusted_score
    )

    # ---- 6. 构造透明化理由 ----
    reason_parts = [f"高潮强度 {max_score} 分（{score_source}）"]
    if position_signal:
        reason_parts.append(position_signal)
    if adjusted_score != max_score:
        reason_parts.append(f"调整后强度 {adjusted_score}")
    if hint_influence:
        reason_parts.append(hint_influence.strip("；"))
    reason = " + ".join(reason_parts)

    logger.info(
        f"[TierClassifier] 定档={final_tier} (raw_score={max_score}→{tier_from_raw_score}, "
        f"adjusted={adjusted_score}→{tier_from_adjusted_score}, 取较低者); reason={reason}"
    )

    return _build_decision(
        tier=final_tier,
        reason=reason,
        climax_score=max_score,
        chapter_position_signal=position_signal,
        tension_level=tension_level,
        forced_by_user=False,
    )


def classify_from_user_forced(
    forced_tier: str,
    tension_level: Optional[int] = None,
) -> Dict[str, Any]:
    """用户强制指定档位的快捷构造（跳过决策）。

    业务场景：generate 请求体 tier != auto 时调用。
    """
    if forced_tier not in VALID_TIERS:
        # 无效档位 fallback 到 transition（宁低勿高）
        logger.warning(f"[TierClassifier] 无效强制档位 {forced_tier!r}，fallback 到 transition")
        forced_tier = TIER_TRANSITION
    return _build_decision(
        tier=forced_tier,
        reason=f"用户强制指定为 {forced_tier}",
        climax_score=None,
        chapter_position_signal=None,
        tension_level=tension_level,
        forced_by_user=True,
    )


def assign_zones(
    nodes: List[Dict[str, Any]],
    reading_order: List[str],
    tier: str,
) -> Dict[str, List[str]]:
    """根据 tier 与 distance_to_climax 分配三分区（规格 §6 zones 字段）。

    分区规则：
    - climax: ["PAYLOAD"]（固定）
    - buildup: distance_to_climax ≤ buildup_threshold 的节点（蓄势段）
    - development: 其余节点（铺陈段）

    buildup_threshold 按 tier 调整：
    - climax 档：threshold=2（更多节点进入蓄势段，重兵投入）
    - turn 档：threshold=1
    - progress 档：threshold=1（仅直接前置节点入蓄势段）
    - transition 档：threshold=0（全部进 development，纯过渡章铺陈为主）

    Args:
        nodes: SetupNode dict 列表
        reading_order: 节点 id 序（用于过滤，PAYLOAD 归 climax）
        tier: 章节档位

    Returns:
        dict: {"climax": ["PAYLOAD"], "buildup": [...], "development": [...]}
    """
    # buildup 距离阈值按档位
    buildup_threshold = {
        TIER_CLIMAX: 2,
        TIER_TURN: 1,
        TIER_PROGRESS: 1,
        TIER_TRANSITION: 0,
    }.get(tier, 1)

    node_by_id = {str(n.get("id", "")): n for n in nodes if n.get("id")}
    # 只考虑 reading_order 中存在的非 PAYLOAD 节点
    candidate_ids = [nid for nid in reading_order if nid != "PAYLOAD" and nid in node_by_id]

    climax_zone = ["PAYLOAD"]
    buildup_zone: List[str] = []
    development_zone: List[str] = []

    for nid in candidate_ids:
        node = node_by_id[nid]
        # 双键读取 distance
        d_raw = node.get("distance_to_climax")
        if d_raw is None:
            d_raw = node.get("distance_to_payload", 1)
        try:
            d = int(d_raw)
        except (TypeError, ValueError):
            d = 1

        if d <= buildup_threshold:
            buildup_zone.append(nid)
        else:
            development_zone.append(nid)

    # Fallback：transition 档若 buildup 为空但 development 也为空，至少把最近节点放 buildup
    # （保证有内容可写）
    if not buildup_zone and not development_zone and candidate_ids:
        buildup_zone = [candidate_ids[-1]]  # 最后一个（最靠近高潮）放 buildup
        development_zone = candidate_ids[:-1]

    return {
        "climax": climax_zone,
        "buildup": buildup_zone,
        "development": development_zone,
    }


# ============================================================
# 内部辅助
# ============================================================

def _score_to_tier(score: int) -> str:
    """强度分 → 档位映射。"""
    for threshold, tier in SCORE_TO_TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return TIER_TRANSITION


def _infer_score_from_tension(tension_level: Optional[int]) -> int:
    """无候选强度自评时，由 tension_level 推断（保守映射）。"""
    if tension_level is None:
        return 3  # 默认 progress 倾向
    # tension_level 通常 1-10，映射到 score（保守：tension 7+ 才算 turn）
    if tension_level >= 9:
        return 7
    if tension_level >= 7:
        return 6
    if tension_level >= 5:
        return 4
    if tension_level >= 3:
        return 3
    return 2


def _build_decision(
    tier: str,
    reason: str,
    climax_score: Optional[int],
    chapter_position_signal: Optional[str],
    tension_level: Optional[int],
    forced_by_user: bool,
) -> Dict[str, Any]:
    """构造 TierDecision dict（含投资参数表）。"""
    return {
        "tier": tier,
        "reason": reason,
        "climax_score": climax_score,
        "chapter_position_signal": chapter_position_signal,
        "tension_level": tension_level,
        "forced_by_user": forced_by_user,
        "max_depth": TIER_MAX_DEPTH.get(tier, 4),
        "development_ratio": TIER_DEVELOPMENT_RATIO.get(tier, 0.5),
    }

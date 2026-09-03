# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""Velluma - 双轨生成契约选档（2026-09-03 质感批次第二层）。

问题（trace 实证）：stitch/continue 只有「推进」一档——_RULE_NEW_INFO 要求
每一句都推进，模型于是把一切供给（节拍/在场名单/设定）都当「该立刻写掉的
事」，幽灵只顾着奔向下一事件，不会停在当下细写（用户实测：「太显式，不会
写细腻的桥段」）。

解法：「这一笔怎么写」由代码选档而非模型自选——
- motion（动感档，默认）：既有行为逐字节不变（每句推进）；
- texture（质感档）：停在当下细写——光线/声响/触感/小动作/神情，唯一
  的推进是感受的加深。

选档判据（确定性、可测试，零 LLM）：
1. 作者点选的零件槽位是最强信号（作者亲选=意图明证）：含 landing/
   toward_beat → motion（作者要推进）；全是 echo/ambient → texture。
2. 无零件（continue/未点选）：正文尾部动作密度兜底——尾 100 字「了」
   ≥ TEXTURE_LE_MIN 说明刚连续推进了多个动作，允许停下来细写当下
   （breath）；否则 motion。「了」是中文叙事完成体标记，密度≈动作推进
   速度的粗代理——v1 启发式，阈值待 trace 校准（adaptive_stitch_contract
   埋点回采选档分布与采纳率）。

红线：texture 只放宽「必须推进」的戒律，其余闸门（字数/接缝/抢拍/快检/
洗层）一律不变——质感稿同样不得复读、不得抢拍、不得泄底。
"""
from __future__ import annotations

from typing import List, Optional

CONTRACT_MOTION = "motion"
CONTRACT_TEXTURE = "texture"

# 推进型槽位（作者要往前走）与停留型槽位（作者要氛围/回响）
_MOTION_SLOTS = {"landing", "toward_beat"}
_TEXTURE_SLOTS = {"echo", "ambient"}

# 尾部动作密度判定窗与阈值（v1 启发式，待 trace 校准）
TEXTURE_TAIL_CHARS = 100
TEXTURE_LE_MIN = 3
# 尾部太短（章刚开始）不给质感档——地上还没有东西可细写
TEXTURE_MIN_TAIL = 60


def pick_contract(
    mode: str,
    picked_slots: Optional[List[str]] = None,
    rolling_tail: str = "",
) -> str:
    """stitch/continue 的本笔写法选档（其余模式恒 motion——它们各有专职）。

    Args:
        mode: stitch|continue|burst|outline|open
        picked_slots: 作者点选零件的功能槽位表（与 picked_parts 同序；
            未知/缺失值按无槽位处理）
        rolling_tail: 已写正文尾部（裁窗后；continue 密度兜底判定用）
    """
    if mode not in ("stitch", "continue"):
        return CONTRACT_MOTION
    slots = [str(s or "").strip() for s in (picked_slots or [])]
    slots = [s for s in slots if s]
    if slots:
        if any(s in _MOTION_SLOTS for s in slots):
            return CONTRACT_MOTION
        if any(s in _TEXTURE_SLOTS for s in slots):
            return CONTRACT_TEXTURE
        return CONTRACT_MOTION
    tail = (rolling_tail or "")[-TEXTURE_TAIL_CHARS:]
    if len(tail) < TEXTURE_MIN_TAIL:
        return CONTRACT_MOTION
    return CONTRACT_TEXTURE if tail.count("了") >= TEXTURE_LE_MIN else CONTRACT_MOTION

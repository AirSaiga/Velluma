# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 缝合返修环（约束治理二期 · docs/constraint-governance.md 唯一权威）
"""
生成稿硬违规的有界返修环（2026-09-02，用户拍板：可接受生成变慢，不可接受
错误结果上屏；不相信模型自觉——prompt 软提醒之外必须有代码硬闸兜底）。

闭环形态（泛型，prompt 组装与 LLM 调用全部由调用方注入）：

    检出硬违规 → 带稿改写重试（最多 max_retries 次，违规清单作反馈）
    → 确定性验收（recheck 零违规才采纳）→ 仍不过则句级切除（excise，
    调用方注入豁免纪律）→ 再不行 → rejected（调用方决定拒稿/降级）

设计纪律：
- 本模块不感知任何具体约束种类——违规是 warning dict，判定闭环 = recheck；
- 验收永远是确定性的（重跑同一套闸门），不采信模型「我改好了」的自我声明；
- 返修稿必须重跑接缝/字数等确定性后处理（由调用方在 regenerate 内完成），
  防止修好了违规却引入了复读/超字；
- 任何异常 = 保守返回原稿 rejected=False 的 clean 形态由调用方兜——
  本模块自己不吞异常，但约定 regenerate/recheck/excise 回调内部静默失败
  （返回 ""/违规列表原样/None），与 ghost_guard 零报错契约对齐。

副作用：无（纯编排；台账/trace 由调用方按 result.action 落）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

# 返修结果动作（调用方据此落 constraint_events 台账——outcome 词表同义）
ACTION_CLEAN = "clean"          # 无硬违规，原稿放行
ACTION_REPAIRED = "repaired"    # 带稿改写成功（验收零违规）
ACTION_EXCISED = "excised"      # 改写失败，句级切除成功（验收零违规）
ACTION_REJECTED = "rejected"    # 改写与切除均失败——稿子不可用


@dataclass
class RepairResult:
    """返修环产物。text 在 rejected 时仍带原稿（调用方熔断降级可警示上屏，
    或走拒稿帧把原稿交给前端逃生舱——本模块不裁决处置）。"""

    text: str
    action: str
    fixed_kinds: List[str] = field(default_factory=list)   # 被修掉的违规 kind 去重表
    remaining: List[Dict[str, Any]] = field(default_factory=list)  # 终稿仍存的违规
    attempts: int = 0                                       # 实际返修调用次数


async def run_repair_loop(
    text: str,
    violations: List[Dict[str, Any]],
    *,
    regenerate: Callable[[str, List[Dict[str, Any]]], Awaitable[str]],
    recheck: Callable[[str], List[Dict[str, Any]]],
    excise: Optional[Callable[[str, List[Dict[str, Any]]], Optional[str]]] = None,
    max_retries: int = 1,
) -> RepairResult:
    """有界返修环。

    Args:
        text: 待检生成稿（已过完确定性后处理）。
        violations: 预检产出的硬违规 warning 列表（空调用方不该进这里——
            但也按 clean 放行，防御位）。
        regenerate: (原稿, 违规列表) → 改写稿（""= 失败）；内部须含接缝/字数
            等确定性后处理。
        recheck: (稿子) → 该稿的硬违规列表（与预检同一套判定；空=验收通过）。
        excise: (稿子, 违规列表) → 切除违规句后的稿子；None=不可切除
            （豁免/长度地板/定位失败）。None 回调 = 无切除兜底。
        max_retries: 改写重试上限（默认 1——延迟封顶纪律）。
    """
    if not violations:
        return RepairResult(text=text, action=ACTION_CLEAN)

    fixed_kinds = sorted({str(w.get("kind") or "") for w in violations if w.get("kind")})
    attempts = 0
    for _ in range(max(0, max_retries)):
        attempts += 1
        cand = await regenerate(text, violations)
        if not cand:
            continue
        remaining = recheck(cand)
        if not remaining:
            return RepairResult(
                text=cand, action=ACTION_REPAIRED,
                fixed_kinds=fixed_kinds, attempts=attempts,
            )

    if excise is not None:
        excised = excise(text, violations)
        if excised:
            remaining = recheck(excised)
            if not remaining:
                return RepairResult(
                    text=excised, action=ACTION_EXCISED,
                    fixed_kinds=fixed_kinds, attempts=attempts,
                )

    return RepairResult(
        text=text, action=ACTION_REJECTED,
        fixed_kinds=[], remaining=violations, attempts=attempts,
    )

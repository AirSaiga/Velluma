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
Layer 0 图校验器（V3.0 新建）。

职责（设计文档 §5 Phase 6 Layer 0 + D4 图即审计）：
纯算法验证因果正确性，零 token 消耗。三件事：
1. 图合法性：每个 payoff 有 plant？每个 plant 在阅读序上先于其 payoff？无环？
2. texture 占比：texture 节点占比 ≤ 阈值（默认 15%）
3. 阅读序合法性：末位是 PAYLOAD？所有节点都出现且仅一次？

业务场景：
- chain_grower 生长后立即跑（带反馈重试 ≤2 轮）
- workflow.execute 组装后跑（最终图校验）
- GET /detonation-chain/report 返回结论

设计要点：
- 全部纯 Python，无 LLM 调用、无 DB 访问
- 返回结构化 verdict + 具体违规列表，便于前端展示与 LLM 反馈
"""

from typing import Any, Dict, List, Optional, Set


# 阈值默认值（设计文档 §4.3 + §9）
DEFAULT_TEXTURE_BUDGET_RATIO = 0.15


def audit_chain_graph(
    nodes: List[Dict[str, Any]],
    reading_order: List[str],
    payload: Optional[Dict[str, Any]] = None,
    texture_budget_ratio: float = DEFAULT_TEXTURE_BUDGET_RATIO,
) -> Dict[str, Any]:
    """对爆发链做 Layer 0 图校验（零 token）。

    Args:
        nodes: SetupNode dict 列表（含 id/type/sets_up/distance_to_payload 或 distance_to_climax）
        reading_order: 节点 id 序（末位应为 PAYLOAD）
        payload: PayloadMoment dict（可选，用于校验 must_land）
        texture_budget_ratio: texture 节点占比上限（默认 0.15）

    V3.1 双键兼容：distance 字段读取优先 distance_to_climax，fallback distance_to_payload

    Returns:
        dict: {
            "verdict": "pass" | "fail",
            "checks": {
                "reading_order_valid": bool,
                "all_nodes_reachable_to_payload": bool,
                "no_cycles": bool,
                "texture_ratio_ok": bool,
                "every_plant_has_payoff": bool,  # 对本章而言，每个节点的 sets_up 都指向 PAYLOAD 或树内节点
            },
            "violations": List[str],  # 具体违规描述（供 LLM 反馈或前端展示）
            "stats": {
                "node_count": int,
                "texture_count": int,
                "texture_ratio": float,
                "max_distance": int,
            },
        }
    """
    violations: List[str] = []
    checks: Dict[str, bool] = {}

    # ---- 1. 节点 id 集合 + PAYLOAD 约定 ----
    node_ids: Set[str] = set()
    node_by_id: Dict[str, Dict[str, Any]] = {}
    for n in nodes:
        nid = str(n.get("id", "")).strip()
        if not nid:
            continue
        node_ids.add(nid)
        node_by_id[nid] = n

    # ---- 2. 阅读序合法性 ----
    reading_order_valid = True
    if not reading_order:
        reading_order_valid = False
        violations.append("reading_order 为空")
    else:
        # 末位必须是 PAYLOAD
        if reading_order[-1] != "PAYLOAD":
            reading_order_valid = False
            violations.append(f"reading_order 末位应是 PAYLOAD，实为 {reading_order[-1]!r}")
        # 所有节点必须出现且仅一次
        seen: List[str] = []
        for nid in reading_order:
            if nid in seen:
                reading_order_valid = False
                violations.append(f"reading_order 中 {nid!r} 重复出现")
            seen.append(nid)
        # reading_order 里的 id 要么是已知节点，要么是 PAYLOAD
        for nid in reading_order:
            if nid != "PAYLOAD" and nid not in node_ids:
                reading_order_valid = False
                violations.append(f"reading_order 含未知节点 id {nid!r}")
        # 所有节点都应该在 reading_order 里（除非是被 satisfied_by_existing 终止的，但仍应出现）
        missing = node_ids - set(reading_order)
        if missing:
            reading_order_valid = False
            violations.append(f"以下节点未出现在 reading_order: {sorted(missing)}")
    checks["reading_order_valid"] = reading_order_valid

    # ---- 3. 可达性（每个节点能沿 sets_up 链到达 PAYLOAD）----
    reachable_to_payload = True
    unreachable: List[str] = []

    def _can_reach_payload(start_id: str, visited: Set[str]) -> bool:
        """DFS：从 start_id 沿 sets_up 链能否到达 PAYLOAD。"""
        if start_id == "PAYLOAD":
            return True
        if start_id in visited:
            return False  # 环路由 no_cycles 检查处理
        visited.add(start_id)
        node = node_by_id.get(start_id)
        if node is None:
            return False
        sets_up = node.get("sets_up", []) or []
        if not isinstance(sets_up, list):
            return False
        for target in sets_up:
            if _can_reach_payload(str(target), visited):
                return True
        return False

    for nid in node_ids:
        if not _can_reach_payload(nid, set()):
            reachable_to_payload = False
            unreachable.append(nid)
    if unreachable:
        violations.append(f"以下节点无法沿 sets_up 链到达 PAYLOAD（孤儿/断线）: {sorted(unreachable)}")
    checks["all_nodes_reachable_to_payload"] = reachable_to_payload

    # ---- 4. 无环 ----
    no_cycles = True
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {nid: WHITE for nid in node_ids}

    def _has_cycle(start_id: str) -> bool:
        stack = [(start_id, iter(node_by_id.get(start_id, {}).get("sets_up", []) or []))]
        color[start_id] = GRAY
        while stack:
            current, it = stack[-1]
            advanced = False
            for target in it:
                target_str = str(target)
                if target_str == "PAYLOAD":
                    continue
                if target_str not in node_ids:
                    continue  # 未知目标由其他检查报错
                if color[target_str] == GRAY:
                    return True  # 回边 = 环
                if color[target_str] == WHITE:
                    color[target_str] = GRAY
                    stack.append((target_str, iter(node_by_id.get(target_str, {}).get("sets_up", []) or [])))
                    advanced = True
                    break
            if not advanced:
                color[current] = BLACK
                stack.pop()
        return False

    for nid in node_ids:
        if color[nid] == WHITE:
            if _has_cycle(nid):
                no_cycles = False
                violations.append(f"检测到环（涉及节点含 {nid!r}）")
                break
    checks["no_cycles"] = no_cycles

    # ---- 5. texture 占比 ----
    texture_count = 0
    for n in nodes:
        if str(n.get("type", "")).strip() == "texture":
            texture_count += 1
    total = len(nodes)
    texture_ratio = (texture_count / total) if total > 0 else 0.0
    texture_ratio_ok = texture_ratio <= texture_budget_ratio
    if not texture_ratio_ok:
        violations.append(
            f"texture 节点占比 {texture_ratio:.0%} 超过预算 {texture_budget_ratio:.0%}"
            f"（{texture_count}/{total}）"
        )
    checks["texture_ratio_ok"] = texture_ratio_ok

    # ---- 6. 每个 plant 必须有 payoff（sets_up 非空，且指向树内或 PAYLOAD）----
    every_plant_has_payoff = True
    for n in nodes:
        ntype = str(n.get("type", "")).strip()
        if ntype in ("plant", "development"):
            sets_up = n.get("sets_up", []) or []
            if not isinstance(sets_up, list) or not sets_up:
                every_plant_has_payoff = False
                violations.append(
                    f"节点 {n.get('id')!r}（type={ntype}）的 sets_up 为空，无 payoff"
                )
    checks["every_plant_has_payoff"] = every_plant_has_payoff

    # ---- 统计 ----
    max_distance = 0
    for n in nodes:
        try:
            # V3.1 双键兼容：优先 distance_to_climax，fallback distance_to_payload
            d_raw = n.get("distance_to_climax")
            if d_raw is None:
                d_raw = n.get("distance_to_payload", 0)
            d = int(d_raw or 0)
            if d > max_distance:
                max_distance = d
        except (TypeError, ValueError):
            pass

    verdict = "pass" if not violations else "fail"

    return {
        "verdict": verdict,
        "checks": checks,
        "violations": violations,
        "stats": {
            "node_count": total,
            "texture_count": texture_count,
            "texture_ratio": round(texture_ratio, 3),
            "max_distance": max_distance,
        },
    }


def build_retry_feedback(audit_result: Dict[str, Any]) -> str:
    """把图校验违规转成 LLM 重试反馈（供 chain_grower 带反馈重试用）。

    Args:
        audit_result: audit_chain_graph 的返回

    Returns:
        str: 反馈文本，可直接拼到下次 chain_grow prompt 的 user 段末尾
    """
    if audit_result.get("verdict") == "pass":
        return ""
    violations = audit_result.get("violations", [])
    if not violations:
        return ""
    lines = ["## 上次生成的树存在以下问题，请修正："]
    for i, v in enumerate(violations, 1):
        lines.append(f"{i}. {v}")
    return "\n".join(lines)

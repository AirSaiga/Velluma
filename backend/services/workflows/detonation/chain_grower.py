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
铺垫树生长器（V3.0 新建）。

职责（设计文档 §5 Phase 2 + §7.2）：
以高潮点为根，逆向递归长出铺垫树。

业务流程：
1. 构建 prompt（payload + 章节卡 + established_facts + 伏笔 + 角色）
2. 调 LLM（reasoning, T=0.3，两段式输出）
3. 解析为 nodes + reading_order
4. 跑 Layer 0 图校验（graph_auditor）
5. 若校验失败，带反馈重试 ≤2 轮
6. 返回 GrowResult

业务场景：
- 闸门 2：POST /api/chapters/{id}/detonation-chain/grow
- workflow.execute 内部不再调用本模块（树在闸门阶段已确认）

设计要点：
- 1~2 次 reasoning 调用（成功 1 次；失败带反馈重试 1-2 次）
- 降级显式化：解析失败/校验失败均返回 degraded，由调用方决策
- 不持有 DB session（工作流层约定）
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.prompts.detonation_prompts import (
    build_chain_grow_prompt,
    parse_chain_grow_response,
)
from backend.services.workflows.detonation.graph_auditor import (
    audit_chain_graph,
    build_retry_feedback,
)
from backend.services.workflows.detonation.types import GrowResult

logger = logging.getLogger(__name__)


# 生长参数（设计文档 §5 Phase 2 + §7.2）
GROW_TEMPERATURE = 0.3
GROW_MAX_TOKENS = 8192
GROW_MAX_RETRY = 2  # 校验失败后带反馈重试次数上限


async def grow_detonation_chain(
    payload: Dict[str, Any],
    chapter: Any,
    chapter_card: Any,
    established_facts: List[Dict[str, Any]],
    open_hooks: Optional[List[Any]] = None,
    entities: Optional[List[Any]] = None,
    previous_summary: Optional[str] = None,
    max_depth: int = 6,
    texture_budget_ratio: float = 0.15,
    recorder: Optional[Any] = None,
    existing_nodes: Optional[List[Dict[str, Any]]] = None,
    partial_from_node_id: Optional[str] = None,
) -> GrowResult:
    """生长铺垫树（1-2 次 reasoning + Layer 0 校验 + 带反馈重试）。

    Args:
        payload: PayloadMoment dict（已确认的高潮点）
        chapter: Chapter ORM 对象
        chapter_card: ChapterCard ORM 对象
        established_facts: 已成立事实清单（递归终止依据 a）
        open_hooks: 开放伏笔列表
        entities: 本章关联角色列表
        previous_summary: 前章摘要
        max_depth: 递归深度上限（默认 6）
        texture_budget_ratio: texture 占比上限（默认 0.15）
        recorder: 可选 RunRecorder
        existing_nodes: 已有节点列表（Slice C 局部重长用，保留不变的节点）
        partial_from_node_id: 局部重长起点（Slice C）——
            若提供，existing_nodes 中该节点及其后代被丢弃，其余保留；
            LLM 基于保留的节点 + payload 重新补全丢弃部分

    Returns:
        GrowResult
    """
    prompts_history: Dict[str, str] = {}
    last_validation: Dict[str, Any] = {}

    # Slice C: 局部重长——计算保留节点
    preserved_nodes: List[Dict[str, Any]] = []
    preserved_block_hint = ""
    if existing_nodes and partial_from_node_id:
        preserved_nodes = _compute_preserved_nodes(existing_nodes, partial_from_node_id)
        if preserved_nodes:
            preserved_block_hint = _format_preserved_hint(preserved_nodes)

    for attempt in range(GROW_MAX_RETRY + 1):
        # 构建 prompt（首次无反馈；重试时附加校验反馈）
        system_prompt, user_prompt = build_chain_grow_prompt(
            payload=payload,
            chapter=chapter,
            chapter_card=chapter_card,
            established_facts=established_facts,
            open_hooks=open_hooks,
            entities=entities,
            previous_summary=previous_summary,
            max_depth=max_depth,
            texture_budget_ratio=texture_budget_ratio,
        )
        # Slice C: 追加局部重长指令
        if preserved_block_hint:
            user_prompt = user_prompt + "\n\n" + preserved_block_hint
        if attempt > 0 and last_validation:
            feedback = build_retry_feedback(last_validation)
            if feedback:
                user_prompt = user_prompt + "\n\n" + feedback

        prompts_history[f"attempt_{attempt}_system"] = system_prompt
        prompts_history[f"attempt_{attempt}_user"] = user_prompt

        # LLM 调用（reasoning, T=0.3）
        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"detonation.chain_grow.attempt_{attempt}",
                    model_slot="reasoning",
                ) as ctx:
                    result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="reasoning",
                        temperature=GROW_TEMPERATURE,
                        max_tokens=GROW_MAX_TOKENS,
                    )
                    ctx.set_result(result)
            else:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=GROW_TEMPERATURE,
                    max_tokens=GROW_MAX_TOKENS,
                )
        except Exception as e:
            logger.warning(f"[ChainGrower] LLM 调用失败 attempt={attempt}: {e}")
            return GrowResult(
                degraded={
                    "reason": "llm_call_exception",
                    "action": "empty_tree",
                    "detail": f"{type(e).__name__}: {str(e)[:200]}",
                    "attempt": attempt,
                },
                prompts=prompts_history,
            )

        # 解析
        nodes, reading_order, parse_degraded = parse_chain_grow_response(result.content)

        if parse_degraded:
            logger.warning(
                f"[ChainGrower] 解析失败 attempt={attempt}: {parse_degraded.get('reason')}"
            )
            last_validation = {"verdict": "fail", "violations": ["解析失败，无法生成 JSON"]}
            if attempt >= GROW_MAX_RETRY:
                return GrowResult(
                    degraded=parse_degraded,
                    prompts=prompts_history,
                    validation=last_validation,
                )
            continue

        # Layer 0 图校验
        validation = audit_chain_graph(
            nodes=nodes,
            reading_order=reading_order,
            payload=payload,
            texture_budget_ratio=texture_budget_ratio,
        )
        last_validation = validation

        if validation.get("verdict") == "pass":
            # Slice C: 局部重长——合并保留节点 + 新生节点
            if preserved_nodes:
                nodes, reading_order = _merge_preserved_with_new(
                    preserved_nodes, nodes, reading_order
                )
                # 重新校验合并后的树
                validation = audit_chain_graph(
                    nodes=nodes,
                    reading_order=reading_order,
                    payload=payload,
                    texture_budget_ratio=texture_budget_ratio,
                )
            logger.info(
                f"[ChainGrower] 树生长成功 attempt={attempt} "
                f"nodes={len(nodes)} max_distance={validation['stats']['max_distance']}"
                f"{' (局部重长合并后)' if preserved_nodes else ''}"
            )
            return GrowResult(
                nodes=nodes,
                reading_order=reading_order,
                validation=validation,
                degraded=None,
                prompts=prompts_history,
            )

        # 校验失败 → 带反馈重试
        logger.info(
            f"[ChainGrower] 图校验失败 attempt={attempt} "
            f"violations={len(validation.get('violations', []))} → 重试"
        )
        if attempt >= GROW_MAX_RETRY:
            # 重试耗尽：返回最后一次的结果（即使有违规），标记 degraded
            logger.warning(
                f"[ChainGrower] 重试耗尽，返回带违规的树（{len(validation.get('violations', []))} 条）"
            )
            return GrowResult(
                nodes=nodes,
                reading_order=reading_order,
                validation=validation,
                degraded={
                    "reason": "graph_audit_failed_after_retries",
                    "action": "return_with_violations",
                    "violations": validation.get("violations", [])[:5],
                    "attempts": attempt + 1,
                },
                prompts=prompts_history,
            )

    # 理论上不会到达
    return GrowResult(
        degraded={"reason": "unexpected_exit", "action": "empty_tree"},
        validation=last_validation,
        prompts=prompts_history,
    )


def extract_established_facts(
    entities: List[Any],
    open_hooks: List[Any],
    previous_summary: Optional[str],
    rolling_summary: Optional[str],
) -> List[Dict[str, Any]]:
    """从上下文中提取 established_facts（递归终止依据 a）。

    业务流程（设计文档 §5 Phase 0 新增产物）：
    - 角色当前状态（dynamic_state）→ 已成立事实
    - 已 closed 的伏笔 → 已成立事实
    - 前章摘要 / 滚动摘要 → 已成立事实

    Args:
        entities: ChapterEntity 列表（含 .character）
        open_hooks: 开放伏笔（仅 open 状态；closed 的不算）
        previous_summary: 前章 summary
        rolling_summary: Book.rolling_summary

    Returns:
        List[Dict]: [{"id": "...", "description": "..."}]
    """
    facts: List[Dict[str, Any]] = []

    # 角色当前状态
    for ent in (entities or [])[:10]:
        char = getattr(ent, "character", None)
        if char is None:
            continue
        name = getattr(char, "name", "") or ""
        dynamic = (getattr(char, "dynamic_state", "") or "").strip()
        if name and dynamic:
            facts.append({
                "id": f"char_state_{name}",
                "description": f"{name} 当前：{dynamic[:150]}",
            })

    # 开放伏笔（读者已知的事实）
    for h in (open_hooks or [])[:8]:
        if isinstance(h, dict):
            content = h.get("content", "") or ""
            hook_id = h.get("hook_id", "") or ""
        else:
            content = getattr(h, "content", "") or ""
            hook_id = getattr(h, "hook_id", "") or ""
        if content:
            facts.append({
                "id": f"hook_{hook_id}" if hook_id else "hook_anon",
                "description": content[:150],
            })

    # 前章摘要
    if previous_summary:
        facts.append({
            "id": "prev_chapter_summary",
            "description": previous_summary[:300],
        })

    # 滚动摘要
    if rolling_summary:
        facts.append({
            "id": "rolling_summary",
            "description": rolling_summary[:300],
        })

    return facts


# ============================================================
# Slice C: 局部重长辅助函数
# ============================================================

def _compute_preserved_nodes(
    existing_nodes: List[Dict[str, Any]],
    partial_from_node_id: str,
) -> List[Dict[str, Any]]:
    """计算局部重长时保留的节点（排除指定节点及其后代）。

    业务逻辑：
    - 从 partial_from_node_id 开始，它及其所有后代（沿 sets_up 链）被丢弃
    - 其余节点保留

    Args:
        existing_nodes: 全部现有节点
        partial_from_node_id: 局部重长起点

    Returns:
        保留的节点列表
    """
    node_by_id = {str(n.get("id", "")): n for n in existing_nodes if n.get("id")}
    if partial_from_node_id not in node_by_id:
        return list(existing_nodes)  # 起点不存在,全部保留(降级)

    # BFS 找出 partial_from_node_id 及其所有后代
    discarded: set = set()
    queue = [partial_from_node_id]
    while queue:
        current = queue.pop(0)
        if current in discarded:
            continue
        discarded.add(current)
        # 找以 current 为 sets_up 目标的节点（即 current 的后代）
        for n in existing_nodes:
            sets_up = n.get("sets_up", []) or []
            if isinstance(sets_up, list) and current in [str(x) for x in sets_up]:
                nid = str(n.get("id", ""))
                if nid and nid not in discarded:
                    queue.append(nid)

    return [n for n in existing_nodes if str(n.get("id", "")) not in discarded]


def _format_preserved_hint(preserved_nodes: List[Dict[str, Any]]) -> str:
    """把保留节点格式化为 LLM 提示（让 LLM 知道哪些已存在，不要重复生成）。"""
    if not preserved_nodes:
        return ""
    lines = ["## 以下节点已存在（局部重长场景），请保留它们，只生成缺失的铺垫节点："]
    for n in preserved_nodes:
        nid = n.get("id", "")
        content = n.get("content", "")[:80]
        lines.append(f"- [{nid}] {content}")
    lines.append("\n## 要求")
    lines.append("- 在已有节点的基础上，补全从高潮点到这些节点之间的缺失铺垫")
    lines.append("- 新生成的节点 sets_up 可指向已有节点或 PAYLOAD")
    lines.append("- 输出 JSON 时，nodes 数组应包含已有节点 + 新节点；reading_order 重新排定")
    return "\n".join(lines)


def _merge_preserved_with_new(
    preserved: List[Dict[str, Any]],
    new_nodes: List[Dict[str, Any]],
    new_reading_order: List[str],
) -> tuple:
    """合并保留节点 + LLM 新生节点。

    策略：
    - 以 LLM 输出为基线（它的 reading_order 是完整的）
    - 补充 LLM 没输出但保留节点里有的（防止 LLM 漏掉）
    - 去重（按 node_id）
    """
    # 用 LLM 输出建立 id 索引
    new_ids = {str(n.get("id", "")) for n in new_nodes if n.get("id")}
    merged_nodes = list(new_nodes)
    # 补充保留节点中 LLM 没输出的
    for n in preserved:
        nid = str(n.get("id", ""))
        if nid and nid not in new_ids:
            merged_nodes.append(n)
            new_ids.add(nid)

    # reading_order 补充:确保保留节点都在序里
    merged_order = list(new_reading_order)
    existing_in_order = set(merged_order)
    # 把不在 reading_order 的保留节点插到 PAYLOAD 之前
    for n in preserved:
        nid = str(n.get("id", ""))
        if nid and nid not in existing_in_order and nid != "PAYLOAD":
            # 插到末位 PAYLOAD 之前
            if merged_order and merged_order[-1] == "PAYLOAD":
                merged_order.insert(-1, nid)
            else:
                merged_order.append(nid)
            existing_in_order.add(nid)

    return merged_nodes, merged_order

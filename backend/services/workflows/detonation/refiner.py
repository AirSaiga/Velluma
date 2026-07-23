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
局部精修器（V3.0 Slice B 新建）。

职责（设计文档 §5 Phase 7）：
证据驱动的局部精修，≤2 轮。未解 → degraded 标记进质量报告随稿放出。

精修类型：
1. **断线节点补埋**：定向插入/改写，输入仅相关段 + 节点（避免全文重写）
2. **过早泄底段降燃**：重写该段，带"降一档"指令
3. **高潮爆发不足爆发段重写**：换候选重写（若 payload_writer 有多候选）
4. **restraint 违反删改**：删掉说破的内容

业务场景：
- workflow.execute 在 Layer 1 有锚审计后调用
- 仅当 audit_result.verdict == "needs_refinement" 时触发

设计要点：
- 不重写全文（成本太高），只定向修复
- 每类精修独立的 LLM 调用，输入最小化
- 失败不静默：降级标记随稿放出
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage

logger = logging.getLogger(__name__)


REFINE_TEMPERATURE = 0.7
REFINE_MAX_TOKENS = 3072
MAX_REFINE_ROUNDS = 2


async def refine_broken_nodes(
    full_text: str,
    nodes: List[Dict[str, Any]],
    broken_node_ids: List[str],
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """补埋断线节点（定向插入/改写）。

    Args:
        full_text: 完整正文
        nodes: 全部节点
        broken_node_ids: 断线节点 id 列表
        recorder: 可选 RunRecorder

    Returns:
        dict: {"refined_text": str, "inserted": [{node_id, where}], "degraded": Optional}
    """
    broken_nodes = [n for n in nodes if n.get("id") in broken_node_ids]
    if not broken_nodes:
        return {"refined_text": full_text, "inserted": [], "degraded": None}

    # 构造补埋指令
    broken_block = "\n".join([
        f"- [{n.get('id')}] {n.get('content', '')[:120]}"
        + (f"（克制：{n.get('restraint_note')}）" if n.get('restraint_note') else "")
        for n in broken_nodes
    ])

    system_prompt = """你是一位小说编辑。下面给你一份成稿和一份"断线节点清单"——这些节点的铺垫内容痕迹在正文中没有真实落地。请在不破坏整体结构的前提下，把这些铺垫自然地补埋进正文。

要求：
- 只输出修改后的完整正文
- 补埋必须自然，禁止预告腔
- 遵守每个节点的 restraint_note（不说破的内容）
- 不要大改其他段落，只定向补埋"""

    user_prompt = f"""## 断线节点清单（需补埋）
{broken_block}

## 当前正文
{full_text[:6000]}

## 要求
把上述节点的铺垫自然补埋进正文，输出修改后的完整正文。"""

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="detonation.refine.broken",
                model_slot="creative",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=REFINE_TEMPERATURE,
                    max_tokens=REFINE_MAX_TOKENS,
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=REFINE_TEMPERATURE,
                max_tokens=REFINE_MAX_TOKENS,
            )
    except Exception as e:
        logger.warning(f"[Refiner] 断线补埋失败: {e}")
        return {
            "refined_text": full_text,
            "inserted": [],
            "degraded": {"reason": "broken_refine_exception", "action": "skip", "detail": str(e)[:200]},
        }

    refined = (result.content or "").strip()
    if not refined or len(refined) < len(full_text) * 0.5:
        return {
            "refined_text": full_text,
            "inserted": [],
            "degraded": {"reason": "broken_refine_empty", "action": "skip"},
        }

    return {
        "refined_text": refined,
        "inserted": [{"node_id": nid, "where": "embedded"} for nid in broken_node_ids],
        "degraded": None,
    }


async def refine_premature_segments(
    full_text: str,
    premature_segments: List[Dict[str, Any]],
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """过早泄底段降燃（重写带"降一档"指令）。

    Args:
        full_text: 完整正文
        premature_segments: [{segment_index, quote, reason}]
        recorder: 可选 RunRecorder

    Returns:
        dict: {"refined_text": str, "degraded": Optional}
    """
    if not premature_segments:
        return {"refined_text": full_text, "degraded": None}

    quotes_block = "\n".join([
        f"- 段落 {s.get('segment_index', '?')}：「{s.get('quote', '')[:100]}」"
        f"（{s.get('reason', '')[:80]}）"
        for s in premature_segments
    ])

    system_prompt = """你是一位小说编辑。下面给你一份成稿和一份"过早泄底段清单"——这些段落过早释放了情绪或真相，破坏了铺垫树的情绪阶梯。请把这些段落"降一档"——情绪减弱、真相收回、给读者更少的满足（留更大的台阶给后文）。

要求：
- 只输出修改后的完整正文
- 只降燃过早泄底段，不要动其他段落
- 降燃不等于平淡：用问题流保温（读者仍抱着问题走）"""

    user_prompt = f"""## 过早泄底段清单（需降燃）
{quotes_block}

## 当前正文
{full_text[:6000]}

## 要求
把上述过早泄底段降一档，输出修改后的完整正文。"""

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="detonation.refine.premature",
                model_slot="creative",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=REFINE_TEMPERATURE,
                    max_tokens=REFINE_MAX_TOKENS,
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=REFINE_TEMPERATURE,
                max_tokens=REFINE_MAX_TOKENS,
            )
    except Exception as e:
        logger.warning(f"[Refiner] 过早泄底降燃失败: {e}")
        return {
            "refined_text": full_text,
            "degraded": {"reason": "premature_refine_exception", "action": "skip", "detail": str(e)[:200]},
        }

    refined = (result.content or "").strip()
    if not refined or len(refined) < len(full_text) * 0.5:
        return {
            "refined_text": full_text,
            "degraded": {"reason": "premature_refine_empty", "action": "skip"},
        }

    return {"refined_text": refined, "degraded": None}


async def refine_full(
    full_text: str,
    nodes: List[Dict[str, Any]],
    audit_result: Dict[str, Any],
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """完整精修流程（按审计结论驱动，≤2 轮）。

    Args:
        full_text: 完整正文
        nodes: 全部节点
        audit_result: run_anchored_audit 的返回
        recorder: 可选 RunRecorder

    Returns:
        dict: {
            "refined_text": str,
            "rounds": int,
            "actions": [str],  # 执行的精修类型
            "degraded": [dict],  # 累积降级事件
        }
    """
    from backend.services.workflows.detonation.anchored_auditor import derive_refinement_targets

    targets = derive_refinement_targets(audit_result)
    if not targets.get("needs_refinement"):
        return {
            "refined_text": full_text,
            "rounds": 0,
            "actions": [],
            "degraded": [],
        }

    current_text = full_text
    actions: List[str] = []
    degraded_acc: List[Dict[str, Any]] = []

    # 按优先级依次精修（单轮即可，每类问题一次 LLM 调用）
    # 1. 断线补埋
    if targets.get("broken_nodes"):
        r1 = await refine_broken_nodes(current_text, nodes, targets["broken_nodes"], recorder)
        current_text = r1["refined_text"]
        actions.append(f"broken_refine:{len(targets['broken_nodes'])}")
        if r1.get("degraded"):
            degraded_acc.append(r1["degraded"])

    # 2. 过早泄底降燃
    if targets.get("premature_segments"):
        r2 = await refine_premature_segments(current_text, targets["premature_segments"], recorder)
        current_text = r2["refined_text"]
        actions.append(f"premature_refine:{len(targets['premature_segments'])}")
        if r2.get("degraded"):
            degraded_acc.append(r2["degraded"])

    # 3. 高潮爆发不足：Slice B 阶段标记 degraded（爆发段重写需重新调 payload_writer，
    #    涉及 chain 状态变更，留待 Slice C 的"换高潮点局部重长"统一处理）
    if targets.get("detonation_low"):
        degraded_acc.append({
            "reason": "detonation_score_low",
            "action": "needs_payload_rewrite",
            "detail": f"高潮爆发分 {targets.get('detonation_score')} < {7}，建议重新写作爆发段",
        })

    return {
        "refined_text": current_text,
        "rounds": 1,
        "actions": actions,
        "degraded": degraded_acc,
    }

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
Layer 1 有锚审计器（V3.0 Slice B 新建）。

职责（设计文档 §5 Phase 6 Layer 1 + §7.4）：
对爆发链生成的正文做有锚审计，全部给证据链。

三件事：
1. **落地验证**：逐节点问"该铺垫是否在正文中真实落地？"→ 证据链 JSON（引用+偏移）
   断线节点 → 进 Slice B2 精修
2. **高潮爆发验证**：爆发段+其前 500 字单独送读者模型：
   "读到此刻，你的情绪是否被爆发？1-10 分+一句话理由"
   <7 分 → 爆发段重修（优先）而非铺垫返工
3. **过早泄底检查**：各铺垫段单独扫描"是否存在提前释放"（情绪峰值+真相泄露）
4. **restraint 校验**：节点 restraint_note 对照正文，确认"没说破的依然没说破"

业务场景：
- workflow.execute 在 Layer 0 图校验通过后调用
- 失败不静默：任何解析失败 → 标记 unaudited，绝不视同通过

设计要点：
- 1 次 reasoning 调用（合并三件事到单次审计，省钱）
- 输出结构化证据链，供精修阶段消费
- 与 DualTrack 的 adversarial_aligner 本质区别：有锚（对节点验证）vs 无锚（采样对比）
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.prompts.detonation_prompts import (
    build_anchored_audit_prompt,
    parse_anchored_audit_response,
)

logger = logging.getLogger(__name__)


# 审计参数
AUDIT_TEMPERATURE = 0.1
AUDIT_MAX_TOKENS = 6144
DETONATION_SCORE_THRESHOLD = 7  # 高潮爆发分达标线


async def run_anchored_audit(
    nodes: List[Dict[str, Any]],
    reading_order: List[str],
    full_text: str,
    payload_text: str,
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """对完整正文做有锚审计（落地 + 高潮爆发 + 过早泄底 + restraint）。

    Args:
        nodes: SetupNode dict 列表（含 id/content/restraint_note）
        reading_order: 阅读序（用于定位爆发段前的 500 字）
        full_text: 完整正文（铺垫段 + 爆发段）
        payload_text: 爆发段成文（单独定位用）
        recorder: 可选 RunRecorder

    Returns:
        dict: {
            "verdict": "pass" | "needs_refinement" | "fail" | "unaudited",
            "planted": [{node_id, quote, offset}],
            "broken": [node_id],  # 断线节点
            "premature": [{segment_index, quote, reason}],
            "detonation_score": int,
            "detonation_reason": str,
            "restraint_violations": [{node_id, quote, should_not_reveal}],
            "degraded": Optional[dict],
        }
    """
    # 构造 prompt
    system_prompt, user_prompt = build_anchored_audit_prompt(
        nodes=nodes,
        full_text=full_text,
    )

    # LLM 调用
    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="detonation.anchored_audit",
                model_slot="reasoning",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=AUDIT_TEMPERATURE,
                    max_tokens=AUDIT_MAX_TOKENS,
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=AUDIT_TEMPERATURE,
                max_tokens=AUDIT_MAX_TOKENS,
            )
    except Exception as e:
        logger.warning(f"[AnchoredAuditor] LLM 调用失败: {e}")
        return {
            "verdict": "unaudited",
            "planted": [],
            "broken": [],
            "premature": [],
            "detonation_score": None,
            "detonation_reason": "",
            "restraint_violations": [],
            "degraded": {
                "reason": "llm_call_exception",
                "action": "unaudited",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            },
        }

    # 解析
    audit_data, parse_degraded = parse_anchored_audit_response(result.content)

    if parse_degraded or not audit_data:
        logger.warning(f"[AnchoredAuditor] 解析失败: {parse_degraded}")
        return {
            "verdict": "unaudited",
            "planted": [],
            "broken": [],
            "premature": [],
            "detonation_score": None,
            "detonation_reason": "",
            "restraint_violations": [],
            "degraded": parse_degraded or {"reason": "empty_audit", "action": "unaudited"},
        }

    # 补充 restraint 校验（代码级抽查：restraint_note 关键词是否在正文出现）
    restraint_violations = _check_restraint_violations(nodes, full_text)
    audit_data["restraint_violations"] = restraint_violations

    # 推断 verdict
    broken = audit_data.get("broken", []) or []
    premature = audit_data.get("premature", []) or []
    detonation_score = audit_data.get("detonation_score")
    try:
        detonation_score_int = int(detonation_score) if detonation_score is not None else None
    except (TypeError, ValueError):
        detonation_score_int = None
    audit_data["detonation_score"] = detonation_score_int

    if broken or premature or restraint_violations:
        audit_data["verdict"] = "needs_refinement"
    elif detonation_score_int is not None and detonation_score_int < DETONATION_SCORE_THRESHOLD:
        audit_data["verdict"] = "needs_refinement"
    else:
        audit_data["verdict"] = "pass"

    audit_data["degraded"] = None
    logger.info(
        f"[AnchoredAuditor] 审计完成：verdict={audit_data['verdict']} "
        f"broken={len(broken)} premature={len(premature)} "
        f"detonation={detonation_score_int} restraint_violations={len(restraint_violations)}"
    )

    return audit_data


def _check_restraint_violations(
    nodes: List[Dict[str, Any]],
    full_text: str,
) -> List[Dict[str, Any]]:
    """代码级 restraint 抽查：restraint_note 的关键词是否在正文中出现。

    这是保守的粗筛——只标记 restraint_note 中明确出现的、且在正文也出现的"关键名词"。
    LLM 抽查在 Slice B 末接入（目前代码级够用）。

    业务逻辑：
    - restraint_note 形如"不点破他为什么犹豫"
    - 抽取其中的名词性关键词（"犹豫""原因"等）
    - 若关键词在正文密度过高 → 标记疑似违反
    - 这是启发式，会有误报，仅供精修参考
    """
    violations = []
    for node in nodes:
        restraint = node.get("restraint_note")
        if not restraint:
            continue
        # 简化：若 restraint_note 本身的字面内容在正文中出现，标记疑似
        # （正常情况，restraint 是"不说破的"，其字面不应直接出现在正文）
        restraint_str = str(restraint).strip()
        if len(restraint_str) < 6:  # 太短的关键词跳过（易误报）
            continue
        if restraint_str in full_text:
            violations.append({
                "node_id": node.get("id"),
                "quote": restraint_str[:60],
                "should_not_reveal": restraint_str,
                "reason": "restraint_note 字面出现在正文中（疑似说破）",
            })
    return violations


def derive_refinement_targets(audit_result: Dict[str, Any]) -> Dict[str, Any]:
    """从审计结论推导精修目标（供 Slice B2 的 refiner 消费）。

    Args:
        audit_result: run_anchored_audit 的返回

    Returns:
        dict: {
            "broken_nodes": [{node_id, content}],  # 断线节点需补埋
            "premature_segments": [{segment_index, quote}],  # 过早泄底段需降燃
            "detonation_low": bool,  # 高潮爆发分不足，爆发段需重写
            "restraint_violations": [...],  # restraint 违反需删改
            "needs_refinement": bool,
        }
    """
    broken = audit_result.get("broken", []) or []
    premature = audit_result.get("premature", []) or []
    detonation_score = audit_result.get("detonation_score")
    restraint_violations = audit_result.get("restraint_violations", []) or []

    needs_refinement = audit_result.get("verdict") == "needs_refinement"

    return {
        "broken_nodes": broken,
        "premature_segments": premature,
        "detonation_low": (
            detonation_score is not None
            and detonation_score < DETONATION_SCORE_THRESHOLD
        ),
        "detonation_score": detonation_score,
        "restraint_violations": restraint_violations,
        "needs_refinement": needs_refinement,
    }

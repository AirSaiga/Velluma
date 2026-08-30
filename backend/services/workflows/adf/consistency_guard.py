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
Phase 7: 一致性守卫（Consistency Guard）—— 设定一致性四层防线之"查得出 + 修得掉"。

职责：
- 第 0 步：全文重复块清除（0 LLM，dedup_guard）——剧情回路护栏
- 代码级预扫（0 LLM）：scan_name_anomalies 产出专名 suspects
- LLM 一致性审计（1×reasoning）：对照专名表/Canon/场景设定/知识边界审全文，
  只报 name_drift / knowledge_breach / setting_conflict / state_contradiction 四类
- 定点手术（0~3×creative）：复用 Refinery 的 planner/surgeon 做最小侵入式修复
- 手术复验回滚（0~1×reasoning，Agent Loop 2）：代码预验（改动与原文邻段
  近重复）+ LLM 复验（改动是否引入新问题），不通过的手术回滚重拼

设计意图：
- 与 Phase 5 锚点审计分工：锚点审计管结构/情绪/钩子（头尾采样）；
  一致性审计管设定幻觉，必须看全文（超长时头40%+中30%+尾30%三段采样）。
- judge 防幻觉：每条 issue 必须带 canon_evidence 引用设定原文，
  代码侧丢弃无证据 issue（parse_consistency_audit_response 已过滤）。
- 修复用定点手术而非整章重写：违规是局部的，整章重写引入新风险且贵。
- 手术安全网：任何手术结果违反长度/伏笔关键词/专名保护则 applied=False 保留原文。
- 全部异常降级为"跳过守卫、保留原文、记 degraded"，绝不阻塞主流程。

业务场景：
- workflows/adf/adf_workflow.py Phase 7（Phase 6 条件补埋之后、统计收尾之前）

使用方式：
    guard = await run_consistency_guard(
        final_text=final_text, registry=registry, canon_context=canon_context,
        scene_setting_text=scene_setting_text, knowledge_constraints=kc,
        anchor=anchor, purpose=purpose, recorder=recorder,
    )
    final_text = guard.new_text

依赖项：
- services.refinery.planner.plan_operations（手术规划，纯算法）
- services.refinery.surgeon.execute_surgery / apply_surgeries_to_text（定点手术）
- services.prompts.adf_prompts（审计 prompt 构建/解析）
- workflows.adf.name_registry（专名注册表 + 代码预扫）
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import (
    CONSISTENCY_ISSUE_TYPES,
    build_consistency_audit_prompt,
    build_edit_verify_prompt,
    parse_consistency_audit_response,
    parse_edit_verify_response,
)
from backend.services.refinery.planner import plan_operations
from backend.services.refinery.surgeon import (
    apply_surgeries_to_text,
    execute_surgery,
)
from backend.services.workflows.adf.name_registry import (
    NameRegistry,
    registry_to_prompt_block,
    scan_name_anomalies,
)
from backend.services.workflows.adf.dedup_guard import (
    remove_duplicate_blocks,
    segment_too_similar,
)
from backend.services.workflows.adf.types import ChapterClimax

logger = logging.getLogger(__name__)

# 审计输入预算：≤20k 字全量；超长按 头40% + 中30% + 尾30% 三段采样
AUDIT_TEXT_BUDGET = 20000
# 手术上限：最多 3 个 operation（成本控制，违规通常集中在少数几处）
MAX_SURGERY_OPERATIONS = 3
# 手术安全网：修订后长度不得超过原文的 1.5 倍
SURGERY_MAX_LENGTH_RATIO = 1.5


@dataclass
class ConsistencyGuardResult:
    """一致性守卫产出。

    Attributes:
        new_text: 守卫后的正文（未发现问题或全部手术被安全网拦截时等于原文）
        issues_found: 审计确认的问题数（过滤后）
        issues_fixed: 被手术成功修复的问题数
        surgeries_applied: 实际应用的手术数
        dedup_removed: 第 0 步删除的重复块范围列表 [(start, end), ...]（段号）；
            去重不计入 issues_fixed（它是代码级清除，不是 LLM 审计修复）
        rolled_back: 第 6 步复验未通过被回滚的手术说明列表
        degraded: 降级记录（phase/reason/detail），由调用方并入 result.degraded
    """

    new_text: str = ""
    issues_found: int = 0
    issues_fixed: int = 0
    surgeries_applied: int = 0
    dedup_removed: List[Tuple[int, int]] = field(default_factory=list)
    rolled_back: List[str] = field(default_factory=list)
    degraded: List[Dict[str, Any]] = field(default_factory=list)


def _mark_paragraphs_for_audit(paragraphs: List[str]) -> str:
    """把段落列表转为带 [Pn] 段标的审计输入文本，超长时三段采样。

    采样保留原始段号（[Pn] 即 paragraphs 的真实下标），保证审计返回的
    location.paragraph 能直接用于手术定位。头/中/尾采样覆盖：入口衔接（头）、
  状态矛盾高发区（中）、高潮与章末钩子（尾）。
    """
    marked = [f"[P{i}] {p}" for i, p in enumerate(paragraphs)]
    total = sum(len(m) for m in marked)
    if total <= AUDIT_TEXT_BUDGET:
        return "\n\n".join(marked)

    head_budget = int(AUDIT_TEXT_BUDGET * 0.4)
    mid_budget = int(AUDIT_TEXT_BUDGET * 0.3)
    tail_budget = AUDIT_TEXT_BUDGET - head_budget - mid_budget

    def _take(seq, budget):
        picked, used = [], 0
        for m in seq:
            if used + len(m) > budget and picked:
                break
            picked.append(m)
            used += len(m)
        return picked

    head = _take(marked, head_budget)
    tail = _take(list(reversed(marked)), tail_budget)
    tail.reverse()
    head_end = len(head)
    tail_start = len(marked) - len(tail)
    middle = _take(marked[head_end:tail_start], mid_budget) if tail_start > head_end else []

    parts = head
    if middle:
        parts += ["……（段间省略）……"] + middle
    if tail:
        parts += ["……（段间省略）……"] + tail
    return "\n\n".join(parts)


def _surgery_safe(
    original_text: str,
    revised_text: str,
    anchor: Optional[ChapterClimax],
    registry: Optional[NameRegistry],
) -> Tuple[bool, str]:
    """手术安全网：三项检查任一违反则手术不可应用（保留原文）。

    (a) 长度防爆：revised 长度 ≤ 原文 × 1.5（防 LLM 借手术扩写跑偏）
    (b) 伏笔保护：原段落中出现的已落地 Precondition must_use_terms 不得在修订中丢失
    (c) 专名保护：原段落中出现的注册表记（规范名/别名）不得被替换为表外名称

    Returns:
        (safe, reason)：safe=False 时 reason 为拦截原因
    """
    if not revised_text:
        return False, "修订文本为空"
    if len(revised_text) > len(original_text) * SURGERY_MAX_LENGTH_RATIO:
        return False, (
            f"修订超长（{len(revised_text)} > 原文 {len(original_text)}×{SURGERY_MAX_LENGTH_RATIO}）"
        )
    if anchor is not None:
        for pc in (anchor.preconditions or []):
            if not getattr(pc, "landed", False):
                continue
            for term in (getattr(pc, "must_use_terms", None) or []):
                if term and term in original_text and term not in revised_text:
                    return False, f"丢失已落地伏笔关键词「{term}」（{pc.id}）"
    if registry is not None:
        for form in registry.all_surface_forms:
            if form in original_text and form not in revised_text:
                canonical = registry.alias_to_canonical.get(form, form)
                return False, f"专名「{form}」（规范名 {canonical}）在修订中丢失或被替换"
    return True, ""


def _extract_private_labels(canon_context: str) -> List[str]:
    """从 canon_context 的 [private] 区块提取节点 label（手术 forbidden_terms 用）。"""
    import re

    if not canon_context or "[private]" not in canon_context:
        return []
    start = canon_context.find("[private]")
    end = canon_context.find("\n## ", start)
    if end < 0:
        end = len(canon_context)
    section = canon_context[start:end]
    return [m.strip() for m in re.findall(r"^-\s+([^：:]+)[：:]", section, re.MULTILINE) if m.strip()]


def _post_apply_neighbors(
    post_paragraphs: List[str],
    surgery: Dict[str, Any],
) -> Tuple[str, str]:
    """在手术应用后的段落列表中定位某手术改动块的前后邻段（复验 prompt 用）。

    定位策略：先按 revised_text 首块精确匹配（apply 会把首块写回 target_indices[0]
    位置）；匹配失败回退到 target_indices[0] 钳位下标。越界一律容错为空串。
    """
    if not post_paragraphs:
        return "", ""
    indices = surgery.get("target_indices") or []
    revised = (surgery.get("revised_text") or "").strip()
    first_chunk = revised.split("\n\n")[0].strip() if revised else ""
    pos: Optional[int] = None
    if first_chunk:
        for k, p in enumerate(post_paragraphs):
            if p.strip() == first_chunk:
                pos = k
                break
    if pos is None and indices:
        pos = min(max(indices[0], 0), len(post_paragraphs) - 1)
    if pos is None:
        return "", ""
    prev_nb = post_paragraphs[pos - 1] if pos > 0 else ""
    next_nb = post_paragraphs[pos + 1] if pos + 1 < len(post_paragraphs) else ""
    return prev_nb, next_nb


async def _verify_applied_surgeries(
    applied: List[Dict[str, Any]],
    paragraphs: List[str],
    recorder: Optional[RunRecorder] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """第 6 步：手术复验（Agent Loop 2）——代码预验 + 1×reasoning 复验，不通过的回滚。

    两道关卡：
    (6a) 代码级预验（0 LLM）：revised_text 与**原始 paragraphs** 的前后邻段
         （按 target_indices 取，越界容错）跑 segment_too_similar，命中说明手术
         把邻段内容又写了一遍（引入新重复），直接回滚。
    (6b) LLM 复验（1×reasoning）：剩余手术连同**应用后文本**中的前后邻段一次
         送审，verdict not-ok 的回滚。

    保守方向约定：
    - LLM 调用异常 / 响应解析失败 → 全部视为 ok（不回滚）。误杀好修复的代价
      高于少回滚一处坏修复。
    - verdicts 中缺失的 operation_id → 视为 ok。

    Args:
        applied: 已通过安全网的手术列表（均含 target_indices/revised_text）
        paragraphs: 手术应用**前**的段落列表
        recorder: RunRecorder（复验 stage=adf.edit_verify）

    Returns:
        (通过的手术列表, 回滚说明列表)
    """
    rolled_back: List[str] = []

    # ---- 6a. 代码级预验：改动后与原文邻段近重复 → 直接回滚 ----
    survivors: List[Dict[str, Any]] = []
    for s in applied:
        indices = s.get("target_indices") or []
        revised = (s.get("revised_text") or "").strip()
        neighbors: List[str] = []
        if indices:
            for ni in (indices[0] - 1, indices[-1] + 1):
                if 0 <= ni < len(paragraphs):
                    neighbors.append(paragraphs[ni])
        if revised and any(segment_too_similar(revised, nb) for nb in neighbors):
            op_id = s.get("operation_id", "OP?")
            rolled_back.append(f"{op_id}: 代码预验命中——改动后与原文邻段近重复")
            logger.info(f"[ADF] 手术 {op_id} 代码预验未通过（与邻段近重复），回滚")
            continue
        survivors.append(s)

    if not survivors:
        return survivors, rolled_back

    # ---- 6b. LLM 复验：剩余手术一次送审（邻段取自应用后文本）----
    post_paragraphs = apply_surgeries_to_text(paragraphs, survivors)
    edits = []
    for s in survivors:
        prev_nb, next_nb = _post_apply_neighbors(post_paragraphs, s)
        edits.append({
            "operation_id": s.get("operation_id", "OP?"),
            "original_text": s.get("original_text", ""),
            "revised_text": s.get("revised_text", ""),
            "prev_neighbor": prev_nb,
            "next_neighbor": next_nb,
        })
    system_prompt, user_prompt = build_edit_verify_prompt(edits)

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="adf.edit_verify",
                model_slot="reasoning",
            ) as call_ctx:
                llm_result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.1,
                    max_tokens=2048,
                    response_format={"type": "json_object"},
                )
                call_ctx.set_result(llm_result)
        else:
            llm_result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.1,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
        verdicts = parse_edit_verify_response(llm_result.content or "")
    except Exception as e:
        # 复验自身失败不扩大损失：全部视为 ok，不回滚
        logger.warning(f"[ADF] 手术复验 LLM 调用失败（视为全部通过）: {e}")
        return survivors, rolled_back

    passed: List[Dict[str, Any]] = []
    for s in survivors:
        op_id = str(s.get("operation_id", "OP?"))
        # verdicts 缺失 → 视为 ok（保守方向）
        if verdicts.get(op_id, True):
            passed.append(s)
        else:
            rolled_back.append(f"{op_id}: LLM 复验判定改动引入新问题")
            logger.info(f"[ADF] 手术 {op_id} LLM 复验未通过，回滚")
    return passed, rolled_back


async def run_consistency_guard(
    final_text: str,
    registry: NameRegistry,
    canon_context: str,
    scene_setting_text: str,
    knowledge_constraints: List[str],
    anchor: Optional[ChapterClimax],
    purpose: str,
    recorder: Optional[RunRecorder] = None,
    progress_callback: Optional[Callable[[str, dict], Any]] = None,
    enable_edit_verify: bool = True,
) -> ConsistencyGuardResult:
    """Phase 7: 一致性守卫（1×reasoning 审计 + 0~3×creative 定点手术 + 0~1×reasoning 复验）。

    流程：代码预扫 → LLM 审计（证据锚定）→ 过滤 → 手术规划（≤3）→ 定点手术
    （安全网）→ 应用重拼 → 手术复验回滚（Loop 2）。任何环节异常都降级为
    "保留原文 + 记 degraded"。

    Args:
        final_text: 待守卫的整章正文（Phase 4.5/6 之后的最终文本）
        registry: 专名注册表（与 Phase 4 写作期同源构建）
        canon_context: Canon 全文上下文
        scene_setting_text: 场景设定文本（build_scene_setting_text 输出）
        knowledge_constraints: 知识边界约束行（_build_knowledge_constraints 输出）
        anchor: 远端锚（手术安全网的 must_use_terms 保护用）
        purpose: 章节主旨（手术 prompt 上下文）
        recorder: RunRecorder（审计 stage=adf.consistency_audit，
            手术 stage=adf.consistency_surgery.{op_id}，
            复验 stage=adf.edit_verify）
        progress_callback: 进度回调（保留给调用方发事件，本函数不直接发）
        enable_edit_verify: 第 6 步手术复验回滚开关（默认开；关闭可省 1×reasoning）

    Returns:
        ConsistencyGuardResult（new_text 保证非空输入时非空）
    """
    result = ConsistencyGuardResult(new_text=final_text)
    if not final_text or not final_text.strip():
        return result

    # ---- 0. 全文重复块清除（0 LLM，剧情回路护栏）----
    # 真实故障：模型把已写过的场景近乎逐字重写一遍（块 A / 块 A′），
    # 锚点审计/OOC/一致性审计都不做"全文自我相似"检查，全部漏检。
    # 有删除时用清除后的文本继续后续审计/手术；无删除时零行为变化。
    try:
        deduped_text, removed = remove_duplicate_blocks(final_text)
    except Exception as e:
        logger.warning(f"[ADF] 重复块检测异常（跳过去重，保留原文）: {e}")
        deduped_text, removed = final_text, []
        result.degraded.append({"phase": "consistency_guard", "reason": "dedup_exception", "detail": str(e)[:200]})
    if removed:
        result.dedup_removed = removed
        result.new_text = deduped_text
        final_text = deduped_text
        logger.info(f"[ADF] 一致性守卫第 0 步：删除 {len(removed)} 个重复块 {removed}")

    # ---- 1. 代码级预扫（0 LLM）----
    try:
        suspects = scan_name_anomalies(final_text, registry)
    except Exception as e:
        logger.warning(f"[ADF] 一致性预扫异常（降级空 suspects）: {e}")
        suspects = []
        result.degraded.append({"phase": "consistency_guard", "reason": "prescan_exception", "detail": str(e)[:200]})

    # ---- 2. LLM 一致性审计（1×reasoning，JSON）----
    paragraphs = [p for p in final_text.split("\n\n") if p.strip()]
    if not paragraphs:
        return result
    marked_text = _mark_paragraphs_for_audit(paragraphs)
    registry_block = registry_to_prompt_block(registry) if registry else ""

    system_prompt, user_prompt = build_consistency_audit_prompt(
        name_registry_block=registry_block,
        canon_context=canon_context,
        scene_setting_text=scene_setting_text,
        knowledge_constraints=knowledge_constraints or [],
        suspects=suspects,
        marked_text=marked_text,
        paragraph_count=len(paragraphs),
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="adf.consistency_audit",
                model_slot="reasoning",
            ) as call_ctx:
                llm_result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.1,
                    max_tokens=6144,
                    response_format={"type": "json_object"},
                )
                call_ctx.set_result(llm_result)
        else:
            llm_result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.1,
                max_tokens=6144,
                response_format={"type": "json_object"},
            )
        raw_content = llm_result.content or ""
    except Exception as e:
        logger.warning(f"[ADF] 一致性审计 LLM 调用失败（跳过守卫，保留原文）: {e}")
        result.degraded.append({"phase": "consistency_guard", "reason": "audit_exception", "detail": str(e)[:200]})
        return result

    issues = parse_consistency_audit_response(raw_content)
    # 只修 high/medium（parse 已过滤无证据/无 quote/非四类 的 issue）
    actionable = [i for i in issues if i.get("severity") in ("high", "medium")]
    result.issues_found = len(actionable)
    if not actionable:
        logger.info("[ADF] 一致性守卫：审计无可修复问题")
        return result

    # ---- 3. 手术规划（纯算法，复用 refinery.planner，上限 3 个 operation）----
    canon_constraints_text = "\n\n".join(
        t for t in (canon_context, scene_setting_text) if t and t.strip()
    )
    try:
        operations = plan_operations(
            actionable,
            context_summary_template=f"章节主旨：{purpose}" if purpose else "",
            canon_constraints=canon_constraints_text,
        )[:MAX_SURGERY_OPERATIONS]
    except Exception as e:
        logger.warning(f"[ADF] 一致性手术规划失败（保留原文）: {e}")
        result.degraded.append({"phase": "consistency_guard", "reason": "plan_exception", "detail": str(e)[:200]})
        return result

    # forbidden_terms：private 标签（防手术时泄露）+ 漂移错误名（防手术保留错误名）
    drift_names = [s["name"] for s in suspects if s.get("type") == "name_drift" and s.get("name")]
    forbidden_terms = "、".join(dict.fromkeys(_extract_private_labels(canon_context) + drift_names))

    # ---- 4. 定点手术（每 op 1×creative，安全网三项检查）----
    surgeries: List[Dict[str, Any]] = []
    for op in operations:
        op_id = op.get("id", "OP?")
        try:
            surgery = await execute_surgery(
                op,
                paragraphs,
                purpose=purpose or "",
                canon_constraints=canon_constraints_text,
                forbidden_terms=forbidden_terms,
                recorder=recorder,
                stage_prefix="adf.consistency_surgery",
            )
        except Exception as e:
            logger.warning(f"[ADF] 一致性手术 {op_id} 异常（跳过该手术）: {e}")
            result.degraded.append({"phase": "consistency_guard", "reason": "surgery_exception", "detail": f"{op_id}: {str(e)[:160]}"})
            continue

        if surgery.get("applied"):
            safe, reason = _surgery_safe(
                surgery.get("original_text", ""),
                surgery.get("revised_text", ""),
                anchor,
                registry,
            )
            if not safe:
                surgery["applied"] = False
                surgery["diff_summary"] = f"{surgery.get('diff_summary', '')}（安全网拦截：{reason}）"
                logger.info(f"[ADF] 一致性手术 {op_id} 被安全网拦截：{reason}")
        surgeries.append(surgery)

    # ---- 5. 应用手术，重拼正文 ----
    applied = [s for s in surgeries if s.get("applied")]
    if applied:
        try:
            new_paragraphs = apply_surgeries_to_text(paragraphs, applied)
            new_text = "\n\n".join(new_paragraphs)

            # ---- 6. 手术复验回滚（Agent Loop 2，0~1×reasoning）----
            # 修完不复验是既有缺口：手术可能修对目标却引入新问题（与邻段重复/
            # 设定矛盾/衔接断裂）。不通过的手术从 applied 移出，用**原始
            # paragraphs** 重 apply 通过子集；全部不通过则回到手术前文本。
            if enable_edit_verify:
                try:
                    applied, rolled_back = await _verify_applied_surgeries(
                        applied, paragraphs, recorder=recorder,
                    )
                    result.rolled_back = rolled_back
                    if rolled_back:
                        if applied:
                            new_paragraphs = apply_surgeries_to_text(paragraphs, applied)
                            new_text = "\n\n".join(new_paragraphs)
                        else:
                            new_text = final_text  # 全部回滚 → 手术前文本
                except Exception as e:
                    # 复验流程自身异常：保持第 5 步结果，不阻断主流程
                    logger.warning(f"[ADF] 手术复验异常（跳过复验，保留第 5 步结果）: {e}")
                    result.degraded.append({"phase": "consistency_guard", "reason": "edit_verify_exception", "detail": str(e)[:200]})

            if new_text.strip():
                result.new_text = new_text
                result.surgeries_applied = len(applied)
                # issues_fixed = 被应用手术覆盖的 issue 数
                applied_op_ids = {s.get("operation_id") for s in applied}
                result.issues_fixed = sum(
                    len(op.get("issue_ids") or [])
                    for op in operations
                    if op.get("id") in applied_op_ids
                )
        except Exception as e:
            logger.warning(f"[ADF] 一致性手术应用失败（保留原文）: {e}")
            result.degraded.append({"phase": "consistency_guard", "reason": "apply_exception", "detail": str(e)[:200]})

    logger.info(
        f"[ADF] 一致性守卫完成：发现 {result.issues_found} 处，"
        f"修复 {result.issues_fixed} 处（{result.surgeries_applied} 个手术）"
        + (f"，复验回滚 {len(result.rolled_back)} 个手术" if result.rolled_back else "")
    )
    return result

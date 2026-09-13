# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""局部手术（Surgeon，自 services/refinery/surgeon.py 抽迁，2026-09-12）。

职责：对每个 Operation，1 次 creative LLM，做最小侵入式修改。

核心设计（与"纯局部重写"的区别）：
- prompt 注入"全文上下文摘要"（让 LLM 改局部时有整体感）
- 不只看 target_text，还看章节主旨/情绪曲线/角色状态/Canon/伏笔
- 这样 LLM 不会"局部改对了但破坏了整体"

在役消费方：ADF 一致性守卫（stage_prefix="adf.consistency_surgery"）。
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.text_surgery.prompts import (
    build_surgery_prompt,
    format_diagnosis_for_surgery,
)

logger = logging.getLogger(__name__)


# 单段最大长度（防止 LLM 被巨大段落淹没）
MAX_PARAGRAPH_CHARS = 2000
# 单次手术的最多目标段数（防止一次改太多）
MAX_TARGET_PARAGRAPHS = 6


async def execute_surgery(
    operation: Dict[str, Any],
    paragraphs: List[str],
    purpose: str = "",
    emotion_curve: str = "",
    character_states: str = "",
    canon_constraints: str = "",
    active_hooks: str = "",
    forbidden_terms: str = "",
    recorder: Optional[RunRecorder] = None,
    stage_prefix: str = "adf.consistency_surgery",
) -> Dict[str, Any]:
    """执行单个手术（1 次 creative LLM）。

    Args:
        operation: Operation dict（含 issue_ids/target_paragraphs/issues 等）
        paragraphs: 章节按段切分的列表
        purpose/emotion_curve/character_states/canon_constraints/active_hooks: 上下文
        forbidden_terms: 禁止出现的词（如 private 字段名）
        recorder: RunRecorder
        stage_prefix: recorder 计量 stage 前缀（唯一在役消费方 ADF 一致性守卫
            传 adf.consistency_surgery）

    Returns:
        SurgeryResult dict：含 operation_id/original_text/revised_text/diff_summary/applied
    """
    op_id = operation.get("id", "OP?")
    target_indices = operation.get("target_paragraphs") or []
    issues = operation.get("issues") or []

    # 没有目标段 → 全局问题（如 weak_hook），跳过段落定位，提示插入
    if not target_indices:
        # 找最后一段作为目标（章末钩子通常在最后）
        if paragraphs:
            target_indices = [len(paragraphs) - 1]
        else:
            logger.warning(f"[TextSurgery] 手术 {op_id} 无目标段且章节为空")
            return {
                "operation_id": op_id,
                "original_text": "",
                "revised_text": "",
                "diff_summary": "无目标段",
                "applied": False,
            }

    # 限制目标段数
    if len(target_indices) > MAX_TARGET_PARAGRAPHS:
        logger.warning(
            f"[TextSurgery] 手术 {op_id} 目标段 {len(target_indices)} 过多，截断到 {MAX_TARGET_PARAGRAPHS}"
        )
        target_indices = target_indices[:MAX_TARGET_PARAGRAPHS]

    # 取原文
    try:
        original_chunks = [paragraphs[i] for i in target_indices if 0 <= i < len(paragraphs)]
    except IndexError:
        logger.warning(f"[TextSurgery] 手术 {op_id} 目标段越界")
        return {
            "operation_id": op_id,
            "original_text": "",
            "revised_text": "",
            "diff_summary": "目标段越界",
            "applied": False,
        }

    original_text = "\n\n".join(original_chunks)
    if len(original_text) > MAX_PARAGRAPH_CHARS * 2:
        original_text = original_text[:MAX_PARAGRAPH_CHARS * 2]
        logger.warning(f"[TextSurgery] 手术 {op_id} 原文过长，截断到 {MAX_PARAGRAPH_CHARS * 2} 字")

    # 诊断摘要
    diagnosis_summary = format_diagnosis_for_surgery(issues)

    # 字数提示
    op_type = operation.get("operation_type", "rewrite")
    if op_type == "merge":
        word_hint = "比原文总和短（合并删减）"
    elif op_type == "delete":
        word_hint = "可大幅缩短或留空"
    elif op_type == "insert":
        word_hint = "在原文基础上增加 100-300 字"
    else:
        word_hint = "与原文相近或略短"

    # 构建 prompt
    system_prompt, user_prompt = build_surgery_prompt(
        purpose=purpose,
        emotion_curve=emotion_curve,
        character_states=character_states,
        canon_constraints=canon_constraints,
        active_hooks=active_hooks,
        target_text=original_text,
        diagnosis_summary=diagnosis_summary,
        operation_type=op_type,
        word_hint=word_hint,
        forbidden_terms=forbidden_terms or "（无特别禁止）",
    )

    # 调用 LLM
    try:
        if recorder is not None:
            async with recorder.record_call(
                stage=f"{stage_prefix}.{op_id}",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.6,
                    max_tokens=4096,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.6,
                max_tokens=4096,
            )
    except Exception as e:
        logger.warning(f"[TextSurgery] 手术 {op_id} LLM 调用失败: {e}")
        return {
            "operation_id": op_id,
            "original_text": original_text,
            "revised_text": original_text,  # 失败时保持原文
            "diff_summary": f"手术失败：{e}",
            "applied": False,
        }

    revised_text = (result.content or "").strip()
    if not revised_text:
        logger.warning(f"[TextSurgery] 手术 {op_id} 返回空，保持原文")
        return {
            "operation_id": op_id,
            "original_text": original_text,
            "revised_text": original_text,
            "diff_summary": "LLM 返回空",
            "applied": False,
        }

    # diff 摘要（简单字数对比）
    diff_summary = f"原文 {len(original_text)} 字 → 修改后 {len(revised_text)} 字"

    logger.info(f"[TextSurgery] 手术 {op_id} 完成：{diff_summary}")
    return {
        "operation_id": op_id,
        "original_text": original_text,
        "revised_text": revised_text,
        "diff_summary": diff_summary,
        "applied": True,
        "target_indices": target_indices,  # 给应用层用
    }


def apply_surgeries_to_text(
    paragraphs: List[str],
    surgeries: List[Dict[str, Any]],
) -> List[str]:
    """把所有手术结果应用到段落列表（原地替换）。

    Args:
        paragraphs: 原始段落列表
        surgeries: 手术结果列表（含 target_indices + revised_text）

    Returns:
        修改后的段落列表（新 list，不修改原 list）
    """
    if not paragraphs:
        return []

    result_paragraphs = list(paragraphs)

    for surgery in surgeries:
        if not surgery.get("applied"):
            continue
        target_indices = surgery.get("target_indices") or []
        revised_text = surgery.get("revised_text") or ""
        if not target_indices or not revised_text:
            continue

        # 合并的多段可能被改写为一段（revised_text 是合并后的）
        # 策略：把第一段替换为 revised_text，其他段清空（后续 join 时自然消除）
        first_idx = target_indices[0]
        if 0 <= first_idx < len(result_paragraphs):
            # 如果 revised_text 包含多段（\n\n 分隔），按段拆开填入
            revised_chunks = [c.strip() for c in revised_text.split("\n\n") if c.strip()]
            for i, idx in enumerate(target_indices):
                if 0 <= idx < len(result_paragraphs):
                    if i < len(revised_chunks):
                        result_paragraphs[idx] = revised_chunks[i]
                    else:
                        result_paragraphs[idx] = ""  # 清空多余段

    # 过滤掉空段
    return [p for p in result_paragraphs if p.strip()]

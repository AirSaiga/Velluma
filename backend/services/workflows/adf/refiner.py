"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
Phase 6: 条件补埋器（Refiner，V3.2 §4.6）。

职责：
- 对未落地的 Precondition，定位最自然的段落做"内嵌式补写"
- 每个 Precondition 1 次 creative LLM 调用
- 优先在 develop 区（情绪能量较低的段）插入，避免破坏高潮节奏

设计意图：
- 内嵌式补写而非新开段落（保护流畅性）
- 最小侵入式补充（只补必要内容，不动其他）

业务场景：
- workflows/adf/adf_workflow.py Phase 6 调用
"""

import logging
from typing import Any, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import build_refine_prompt
from backend.services.workflows.adf.types import (
    StructureCheck,
    ChapterClimax,
    SegmentResult,
)

logger = logging.getLogger(__name__)

CANDIDATE_PARAGRAPHS_PER_PC = 3  # 每个 Precondition 给 LLM 看几段候选
MAX_REFINE_PARAGRAPHS_CHARS = 2000  # 候选段落总字数上限


def _select_candidate_segments(
    segments: List[SegmentResult],
) -> List[SegmentResult]:
    """选择候选段落：优先情绪能量低（develop 区）的段。"""
    if not segments:
        return []
    # 排除最后一段（高潮段，不动）
    candidates = [s for s in segments if s.index < len(segments) - 1]
    return candidates[:CANDIDATE_PARAGRAPHS_PER_PC + 2]


def _build_candidate_paragraphs(segments: List[SegmentResult]) -> str:
    """把候选段落格式化为 prompt 文本。"""
    candidates = _select_candidate_segments(segments)
    if not candidates:
        return "（无候选段落）"
    parts = []
    for s in candidates:
        parts.append(f"【第 {s.index + 1} 段】（情绪：{s.emotion_register}）\n{s.text[:600]}")
    full_text = "\n\n".join(parts)
    return full_text[:MAX_REFINE_PARAGRAPHS_CHARS]


def _replace_segment_text(
    segments: List[SegmentResult],
    refined_text: str,
    precondition_terms: List[str],
) -> Tuple[bool, int]:
    """在段落列表中找到含关键词最多的段，替换为 refined_text。

    Returns:
        tuple: (是否替换成功, 替换的段 index)
    """
    if not refined_text.strip() or not segments:
        return False, -1

    # 找包含最多关键词的段（说明 LLM 选择在那段补写）
    best_idx = -1
    best_hits = 0
    for term in precondition_terms:
        for s in segments:
            if term and term in refined_text and term in s.text:
                hits = sum(1 for t in precondition_terms if t in s.text)
                if hits > best_hits:
                    best_hits = hits
                    best_idx = s.index

    # 兜底：如果找不到，找 refined_text 起始 30 字与哪段最相似
    if best_idx < 0 and segments:
        refined_head = refined_text[:30]
        for s in segments:
            if s.text and s.text[:30] == refined_head:
                best_idx = s.index
                break
        if best_idx < 0:
            # 取第 2 段（不是开篇、不是高潮）
            if len(segments) >= 3:
                best_idx = segments[1].index
            else:
                best_idx = segments[0].index

    if best_idx >= 0:
        for s in segments:
            if s.index == best_idx:
                s.text = refined_text.strip()
                return True, best_idx
    return False, -1


async def refine_missing_preconditions(
    audit: StructureCheck,
    anchor: ChapterClimax,
    segments: List[SegmentResult],
    style_card: Any,
    recorder: Optional[RunRecorder] = None,
) -> Tuple[List[SegmentResult], List[str]]:
    """Phase 6: 对未落地的 Precondition 做内嵌式补埋。

    Args:
        audit: 审计结论（含 refinement_targets）
        anchor: 远端锚
        segments: 已写段落列表（会被原地修改）
        style_card: 文风卡
        recorder: RunRecorder

    Returns:
        tuple: (segments, refined_pc_ids)  refined_pc_ids 是成功补埋的 PC id 列表
    """
    targets = audit.refinement_targets or audit.missing_preconditions
    if not targets:
        return segments, []

    refined_ids: List[str] = []
    candidate_text = _build_candidate_paragraphs(segments)

    for pc_id in targets[:3]:  # 最多补 3 个，避免 token 失控
        pc = next((p for p in anchor.preconditions if p.id == pc_id), None)
        if pc is None:
            continue

        system_prompt, user_prompt = build_refine_prompt(
            style_contract=getattr(style_card, "positive_traits", "") or "",
            precondition_id=pc.id,
            precondition_description=pc.description,
            must_use_terms=pc.must_use_terms,
            candidate_paragraphs=candidate_text,
        )

        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"adf.refine.{pc_id}",
                    model_slot="creative",
                ) as call_ctx:
                    result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=0.6,
                        max_tokens=3072,
                    )
                    call_ctx.set_result(result)
            else:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.6,
                    max_tokens=3072,
                )
            refined_text = (result.content or "").strip()

            if refined_text:
                ok, seg_idx = _replace_segment_text(segments, refined_text, pc.must_use_terms)
                if ok:
                    pc.landed = True
                    pc.landed_segment = seg_idx
                    refined_ids.append(pc_id)
                    logger.info(f"[ADF] Precondition {pc_id} 已通过精修补埋到第 {seg_idx + 1} 段")
                else:
                    logger.warning(f"[ADF] Precondition {pc_id} 精修后未匹配到段落")
        except Exception as e:
            logger.warning(f"[ADF] Precondition {pc_id} 精修失败: {e}")

    return segments, refined_ids

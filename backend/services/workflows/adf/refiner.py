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
import re
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

# ---- 越界防护（补写重叠 bug 修复，2026-07）----
# 事故现象：LLM 补写时从章节开头重写并一路写进下一段，整段替换后
# 下一段内容在成品中出现两遍（实测两章分别重复 ~1500 字 / ~829 字）。
_MIN_ANCHOR_CHARS = 12  # 归一化后邻段锚点最小长度
_MAX_REFINED_GROWTH = 1.8  # 补写后段长相对原段的上限倍数（超过视为越界重写，拒绝替换）

# 归一化时剥离的字符（空白/标点/引号变体——LLM 常改写标点，原文锚点直接匹配会失效）
_OVERLAP_STRIP = re.compile(r"[\s，。！？!?；;、…—：:\"'″“”‘’「』()（）<>《》-]")

# 候选段元数据标签清洗（修【第 X 段】泄漏事故）：
# _build_candidate_paragraphs 给 LLM 的格式是 "【第 N 段】（情绪：xxx）\n<正文>"，
# LLM 偶尔把整段含标签原样回吐。_replace_segment_text 若不剥离，标签会进 final_text。
# 匹配开头的【...】（段号）和（情绪：...）（可选），连同其后到正文前的换行/空白一起清掉。
_SEGMENT_META_TAG = re.compile(
    r"^\s*【[^】]*】\s*(?:[（(][^）)]*[）)])?\s*\n?"
)


def _norm_with_map(text: str) -> Tuple[str, List[int]]:
    """归一化文本（去空白/标点），返回 (归一化串, 归一化下标→原文下标映射)。"""
    chars: List[str] = []
    idx_map: List[int] = []
    for i, ch in enumerate(text):
        if not _OVERLAP_STRIP.match(ch):
            chars.append(ch)
            idx_map.append(i)
    return "".join(chars), idx_map


def _find_anchor(haystack_norm: str, anchor_norm: str, search_from: int) -> int:
    """在归一化串中从 search_from 起找锚点（从长到短尝试），返回命中下标或 -1。"""
    for length in (48, 36, 24, _MIN_ANCHOR_CHARS):
        if len(anchor_norm) < length:
            continue
        pos = haystack_norm.find(anchor_norm[:length], search_from)
        if pos >= 0:
            return pos
    return -1


def _trim_neighbor_overlap(refined: str, prev_text: str, next_text: str) -> str:
    """裁掉 LLM 补写越界部分（尾部写下一段内容 / 头部重复上一段结尾）。

    策略：
    - 尾部：下一段的开头（归一化锚点）出现在 refined 的 25% 之后 → 从命中处截断
    - 头部：上一段的结尾出现在 refined 的开头 30% 之内 → 裁掉重复前缀
    """
    norm, idx_map = _norm_with_map(refined)

    if next_text:
        next_norm, _ = _norm_with_map(next_text)
        pos = _find_anchor(norm, next_norm, int(len(norm) * 0.25))
        if pos > 0:
            refined = refined[:idx_map[pos]]
            norm, idx_map = _norm_with_map(refined)

    if prev_text:
        prev_norm, _ = _norm_with_map(prev_text)
        for length in (36, 24, _MIN_ANCHOR_CHARS):
            if len(prev_norm) < length:
                continue
            anchor = prev_norm[-length:]
            end = norm.find(anchor)
            if 0 <= end <= int(len(norm) * 0.3):
                refined = refined[idx_map[end + length]:]
                norm, idx_map = _norm_with_map(refined)
                break  # 命中并裁剪后才退出；未命中继续试更短锚点

    return refined.strip()


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

    # 清洗候选段元数据标签（修【第 X 段】（情绪：…）泄漏进正文事故）：
    # LLM 偶尔把 _build_candidate_paragraphs 给的整段格式原样回吐，标签不剥会进 final_text。
    refined_text = _SEGMENT_META_TAG.sub("", refined_text, count=1)
    if not refined_text.strip():
        logger.warning("[ADF] 精修文本清洗元数据标签后为空（LLM 仅回吐了标签），放弃补埋")
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
        target = next((s for s in segments if s.index == best_idx), None)
        if target is None:
            return False, -1
        # 越界防护：裁掉 LLM 写进邻段的部分，再做长度护栏
        prev_text = next((s.text for s in segments if s.index == best_idx - 1), "")
        next_text = next((s.text for s in segments if s.index == best_idx + 1), "")
        trimmed = _trim_neighbor_overlap(refined_text.strip(), prev_text, next_text)
        if not trimmed:
            logger.warning(f"[ADF] 第 {best_idx + 1} 段精修文本越界裁剪后为空，放弃补埋")
            return False, -1
        if target.text and len(trimmed) > len(target.text) * _MAX_REFINED_GROWTH:
            logger.warning(
                f"[ADF] 第 {best_idx + 1} 段精修文本超长"
                f"（{len(trimmed)} vs 原段 {len(target.text)}，超 {_MAX_REFINED_GROWTH}x），放弃补埋"
            )
            return False, -1
        target.text = trimmed
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

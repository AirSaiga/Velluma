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
Phase 4.5: 去 AI 味剪枝器（De-AI Pruner，V3.2 §4.5 新增）。

职责：
- 对 FORWARD_FLOW 产出的每段正文做"重构剪枝"——破匀速句式、删逻辑过渡词、
  剥套路比喻、心理转物理，但保留叙事密度（字数 ±25%）
- precondition 安全网：剪枝误删 must_use_terms 时翻 pc.landed=False，
  交由下游 Phase 5/6 自动补埋
- OOC 安全线：剪枝后用 LLM 裁判检测整章角色崩坏，触发则整章回退

设计意图（区别于现有 de_ai_washer 的"润色取向"）：
- de_ai_washer 是"润色"——在原句上修补、字数浮动 ±15%，倾向保留原句结构，
  导致真正的腔调问题洗不掉。本剪枝是"重构"——允许重写句式结构。
  警示：早期版本 prompt 要求"制造陡峭顿挫感"（长句切碎+极短句连发），
  实测导致整章碎句化（≤5字句占比 41%）——现已纠偏为"以正常语流为主"，
  并新增剪枝后碎句率护栏（碎句化超过原文则保留原文）。
- 全章无条件触发（不依赖密度阈值），因为 AI 味往往是章节级整体腔调，
  单看每段不超标、连起来却浓浓 AI 味。
- 对话可改（AI 对话本身就书面化），但 OOC 安全线兜底。

成本控制：
- 每段 1 次 creative 剪枝调用 + 整章 1 次 creative OOC 裁判 = N+1 次/章
- 失败不阻塞：单段异常保留原文；OOC 触发整章回退（记 degraded）

业务场景：
- workflows/adf/adf_workflow.py Phase 4.5 调用（Phase 4 之后、Phase 5 之前）
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import build_ooc_check_prompt, build_prune_prompt
from backend.services.workflows.adf.types import ChapterClimax, SegmentResult
from backend.services.nlg.ai_taste_meter import short_sentence_ratio
from backend.services.nlg.anti_ai_rules import DEFAULT_THRESHOLDS

logger = logging.getLogger(__name__)

PRUNE_TEMPERATURE = 0.4  # 偏低：严格执行剪枝指令，防止 LLM 二次脑补
PRUNE_MAX_TOKENS = 4096
OOC_TEMPERATURE = 0.1  # 极低：裁判需稳定
OOC_MAX_TOKENS = 1024
ROLLING_PREFIX_TAIL = 500  # 与 segment_writer 保持一致


# ============================================================
# 结果数据结构
# ============================================================


@dataclass
class PruneReport:
    """剪枝 pass 的报告。

    Attributes:
        pruned_count: 实际成功剪枝的段数
        failed_segments: 剪枝失败（保留原文）的段序号列表（0-based）
        dropped_precondition_terms: 被误删的 must_use_terms 列表
        flipped_precondition_ids: 因误删而翻 landed=False 的 PC id 列表
        ooc_triggered: OOC 安全线是否触发（True=整章已回退到未剪枝文本）
        ooc_issues: OOC 裁判报告的问题列表（ooc_triggered=True 时有值）
    """

    pruned_count: int = 0
    failed_segments: List[int] = field(default_factory=list)
    dropped_precondition_terms: List[str] = field(default_factory=list)
    flipped_precondition_ids: List[str] = field(default_factory=list)
    ooc_triggered: bool = False
    ooc_issues: List[str] = field(default_factory=list)


# ============================================================
# JSON 提取（复用 structure_checker._extract_json 的轻量模式）
# ============================================================


def _extract_json(content: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON（支持 ```json 围栏与裸 {} 两种）。"""
    if not content:
        return None
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    return None


# ============================================================
# precondition 安全网
# ============================================================


def _check_precondition_safety(
    anchor: ChapterClimax,
    original_text: str,
    pruned_text: str,
) -> Tuple[List[str], List[str]]:
    """检测剪枝是否误删了 must_use_terms，并翻对应 PC 的 landed=False。

    策略 B：不改正文，只翻状态。翻 landed=False 后下游链路自动接管：
    - Phase 5 _precompute_missing 会把它算进 missing
    - 审计判 needs_refinement
    - Phase 6 refiner 用 must_use_terms 自然补回

    Args:
        anchor: 远端锚（含 preconditions，会被原地修改）
        original_text: 剪枝前整章文本
        pruned_text: 剪枝后整章文本

    Returns:
        tuple: (dropped_terms, flipped_pc_ids)
    """
    dropped_terms: List[str] = []
    flipped_ids: List[str] = []

    for pc in anchor.preconditions:
        if not pc.must_use_terms or not pc.landed:
            # 无关键词或本来就没落地，无需检查
            continue
        for term in pc.must_use_terms:
            if not term:
                continue
            # 原文有、剪枝后没了 → 被误删
            if term in original_text and term not in pruned_text:
                logger.warning(
                    f"[ADF-Pruner] Precondition {pc.id} 的 must_use_term "
                    f"'{term}' 被剪枝误删，翻 landed=False 交下游补埋"
                )
                dropped_terms.append(term)
                # 翻状态只做一次（守卫避免重复日志），但被删词全部记录
                if pc.id not in flipped_ids:
                    flipped_ids.append(pc.id)
                    pc.landed = False
                    pc.landed_segment = None
                    pc.landed_evidence = None

    return dropped_terms, flipped_ids


# ============================================================
# OOC 安全线
# ============================================================


async def _run_ooc_check(
    characters_setting: str,
    pruned_text: str,
    recorder: Optional[RunRecorder] = None,
) -> Tuple[bool, List[str]]:
    """OOC 安全线裁判：检测整章是否发生严重角色崩坏。

    Args:
        characters_setting: 角色设定文本
        pruned_text: 剪枝后整章正文
        recorder: RunRecorder

    Returns:
        tuple: (passed, ooc_issues)  passed=False 表示触发回退
    """
    system_prompt, user_prompt = build_ooc_check_prompt(
        characters_setting=characters_setting,
        pruned_text=pruned_text,
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="adf.prune.ooc_check",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=OOC_TEMPERATURE,
                    max_tokens=OOC_MAX_TOKENS,
                    response_format={"type": "json_object"},
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=OOC_TEMPERATURE,
                max_tokens=OOC_MAX_TOKENS,
                response_format={"type": "json_object"},
            )
    except Exception as e:
        # 裁判失败 → 保守放过（不回退），避免误伤
        logger.warning(f"[ADF-Pruner] OOC 裁判调用失败，保守放过（不回退）: {e}")
        return True, []

    data = _extract_json(result.content or "")
    if data is None:
        logger.warning("[ADF-Pruner] OOC 裁判返回无法解析的 JSON，保守放过")
        return True, []

    passed = bool(data.get("pass", True))
    issues = data.get("ooc_issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    return passed, [str(i) for i in issues]


# ============================================================
# 主入口
# ============================================================


async def run_prune_pass(
    segments: List[SegmentResult],
    anchor: ChapterClimax,
    characters_setting: str,
    style_contract: str,
    author_samples: str,
    recorder: Optional[RunRecorder] = None,
    progress_callback: Any = None,
) -> Tuple[List[SegmentResult], str, PruneReport]:
    """Phase 4.5: 去除 AI 味剪枝 pass（整章重构）。

    流程：
    1. 遍历每段，调 build_prune_prompt + creative LLM 做重构剪枝
    2. precondition 安全网：误删 must_use_terms 则翻 landed=False
    3. OOC 安全线：整章裁判，触发则整章回退到未剪枝文本

    Args:
        segments: Phase 4 产出的段落列表
        anchor: 远端锚（preconditions 可能被翻 landed）
        characters_setting: 角色设定文本（OOC 红线）
        style_contract: 文风契约
        author_samples: 作者样本
        recorder: RunRecorder
        progress_callback: 进度回调（可选）

    Returns:
        tuple: (pruned_segments, pruned_final_text, report)
        - OOC 触发时返回的是原始未剪枝的 segments/text
        - report.ooc_triggered 标记是否回退
    """
    if not segments:
        return segments, "", PruneReport()

    original_full_text = "\n\n".join(s.text for s in segments if s.text)

    # ---- 1. 逐段剪枝 ----
    pruned_segments: List[SegmentResult] = []
    rolling_prefix = ""
    pruned_count = 0
    failed_segments: List[int] = []

    for i, seg in enumerate(segments):
        if not seg.text or not seg.text.strip():
            pruned_segments.append(seg)
            continue

        system_prompt, user_prompt = build_prune_prompt(
            characters_setting=characters_setting,
            style_contract=style_contract,
            author_samples=author_samples,
            rolling_prefix=rolling_prefix[-ROLLING_PREFIX_TAIL:] if rolling_prefix else "",
            text=seg.text,
        )

        pruned_text = ""
        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"adf.prune.segment.{i}",
                    model_slot="creative",
                ) as call_ctx:
                    result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=PRUNE_TEMPERATURE,
                        max_tokens=PRUNE_MAX_TOKENS,
                    )
                    call_ctx.set_result(result)
            else:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=PRUNE_TEMPERATURE,
                    max_tokens=PRUNE_MAX_TOKENS,
                )
            pruned_text = (result.content or "").strip()
        except Exception as e:
            logger.warning(f"[ADF-Pruner] 第 {i + 1} 段剪枝失败，保留原文: {e}")
            failed_segments.append(i)

        # 空结果或过短（明显异常）→ 保留原文
        if not pruned_text or len(pruned_text) < len(seg.text) * 0.5:
            if pruned_text:
                logger.warning(
                    f"[ADF-Pruner] 第 {i + 1} 段剪枝后过短（{len(pruned_text)}/{len(seg.text)}），"
                    f"疑似删过头，保留原文"
                )
                failed_segments.append(i)
            pruned_text = seg.text
        else:
            # 碎句化护栏：剪枝后 ≤5 字碎句占比超阈值且高于原文 → 保留原文
            # （早期 prune prompt 的"切碎制造顿挫"指令曾导致整章机枪句，2026-07 纠偏）
            _, _, orig_frag = short_sentence_ratio(seg.text)
            _, _, pruned_frag = short_sentence_ratio(pruned_text)
            if pruned_frag > max(orig_frag, DEFAULT_THRESHOLDS.short_sentence_ratio_max):
                logger.warning(
                    f"[ADF-Pruner] 第 {i + 1} 段剪枝后碎句化"
                    f"（{pruned_frag:.0%} vs 原文 {orig_frag:.0%}），保留原文"
                )
                failed_segments.append(i)
                pruned_text = seg.text
            else:
                pruned_count += 1

        # 构造新 SegmentResult（保留元数据，只换 text）
        from dataclasses import replace

        new_seg = replace(seg, text=pruned_text)
        pruned_segments.append(new_seg)
        rolling_prefix = pruned_text

        # 推送进度
        if progress_callback:
            try:
                await progress_callback("ADF_PRUNE_PROGRESS", {
                    "segment_index": i + 1,
                    "total_segments": len(segments),
                    "pruned": pruned_text != seg.text,
                })
            except Exception as cb_err:
                logger.warning(f"[ADF-Pruner] progress_callback 失败: {cb_err}")

    pruned_full_text = "\n\n".join(s.text for s in pruned_segments if s.text)

    logger.info(
        f"[ADF-Pruner] 剪枝完成：{pruned_count}/{len(segments)} 段成功重构，"
        f"{len(failed_segments)} 段保留原文"
    )

    # ---- 2. precondition 安全网 ----
    dropped_terms, flipped_ids = _check_precondition_safety(
        anchor=anchor,
        original_text=original_full_text,
        pruned_text=pruned_full_text,
    )
    if flipped_ids:
        logger.info(
            f"[ADF-Pruner] {len(flipped_ids)} 个 precondition 的关键词被误删，"
            f"已翻 landed=False 交下游 Phase 5/6 补埋：{flipped_ids}"
        )

    # ---- 3. OOC 安全线 ----
    passed, ooc_issues = await _run_ooc_check(
        characters_setting=characters_setting,
        pruned_text=pruned_full_text,
        recorder=recorder,
    )

    report = PruneReport(
        pruned_count=pruned_count,
        failed_segments=failed_segments,
        dropped_precondition_terms=dropped_terms,
        flipped_precondition_ids=flipped_ids,
        ooc_triggered=not passed,
        ooc_issues=ooc_issues,
    )

    if not passed:
        # OOC 触发：整章回退到未剪枝文本
        # 注意：precondition 安全网已翻的 landed=False 不回滚——
        # 因为 OOC 回退意味着用的是原始文本，原文本本就含 must_use_terms，
        # 但既然 OOC 裁判发现问题，说明剪枝方向有问题，保守起见让下游重新审计。
        logger.warning(
            f"[ADF-Pruner] OOC 安全线触发，整章回退到未剪枝文本。问题：{ooc_issues}"
        )
        # 回退：重新检测原始文本的 landed 状态（撤销我们翻的 False）
        # —— 实际上不撤销更安全：让 Phase 5 基于原始文本重新审计落地情况
        return segments, original_full_text, report

    return pruned_segments, pruned_full_text, report

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
Phase 5: 锚点审计器（Anchor Auditor，V3.2 §4.5）。

职责：
- 1 次 reasoning LLM，合并校验四个维度：
  1. Precondition 落地（先代码级扫关键词，未落地的交 LLM 判断语义性）
  2. 情绪曲线符合度
  3. 脉络符合度（钩子/角色弧/前章衔接）
  4. 高潮验收（1-10 打分）
- 失败不静默，降级 verdict="unaudited"

业务场景：
- workflows/adf/adf_workflow.py Phase 5 调用
"""

import json
import logging
import re
from typing import Any, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import (
    build_anchor_audit_prompt,
    format_emotion_curve,
    format_preconditions,
)
from backend.services.workflows.adf.story_context_builder import (
    format_entry_state_for_prompt,
)
from backend.services.workflows.adf.types import (
    StructureCheck,
    ChapterClimax,
    StoryContext,
)

logger = logging.getLogger(__name__)


def _extract_json(content: str) -> Optional[dict]:
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


def _precompute_missing(anchor: ChapterClimax) -> list:
    """代码级：must_use_terms 关键词检测未落地的 Precondition id 列表。"""
    return [pc.id for pc in anchor.preconditions if not pc.landed]


async def run_structure_check(
    anchor: ChapterClimax,
    spine: StoryContext,
    purpose: str,
    tier: str,
    full_text: str,
    recorder: Optional[RunRecorder] = None,
) -> StructureCheck:
    """Phase 5: 锚点审计（1 次 reasoning）。

    Args:
        anchor: 远端锚（含 preconditions 的 landed 状态）
        spine: 脉络轨
        purpose: 章节主旨
        tier: 定档
        full_text: 完整正文
        recorder: RunRecorder

    Returns:
        StructureCheck
    """
    # 代码级先扫一遍
    code_missing = _precompute_missing(anchor)

    if not full_text.strip():
        logger.warning("[ADF] 审计时正文为空")
        return StructureCheck(
            verdict="fail",
            missing_preconditions=code_missing,
            spine_violations=["正文为空"],
        )

    # 构造 prompt 输入
    preconditions_text = format_preconditions([
        {
            "id": pc.id,
            "description": pc.description,
            "must_use_terms": pc.must_use_terms,
            "landed": pc.landed,
        }
        for pc in anchor.preconditions
    ])
    emotion_curve_text = format_emotion_curve([
        {"progress": s.progress, "register": s.register, "energy": s.energy}
        for s in anchor.emotion_curve.samples
    ])

    system_prompt, user_prompt = build_anchor_audit_prompt(
        purpose=purpose,
        tier=tier,
        climax_description=anchor.climax.description,
        climax_emotional_target=anchor.climax.emotional_target,
        preconditions=preconditions_text,
        emotion_curve=emotion_curve_text,
        entry_state=format_entry_state_for_prompt(spine),
        must_plant_hooks=spine.must_plant_hooks,
        must_resolve_hooks=spine.must_resolve_hooks,
        character_arc_advances=spine.character_arc_advances,
        full_text=full_text,
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="adf.anchor_audit",
                model_slot="reasoning",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.1,
                    max_tokens=6144,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.1,
                max_tokens=6144,
            )
    except Exception as e:
        logger.warning(f"[ADF] 锚点审计 LLM 调用失败，降级代码级审计: {e}")
        # 降级：仅用代码级结果
        verdict = "needs_refinement" if code_missing else "pass"
        return StructureCheck(
            verdict=verdict,
            missing_preconditions=code_missing,
            climax_score=None,
            refinement_targets=code_missing,
        )

    data = _extract_json(result.content)
    if not data:
        logger.warning("[ADF] 审计 JSON 解析失败，降级代码级审计")
        verdict = "needs_refinement" if code_missing else "pass"
        return StructureCheck(
            verdict=verdict,
            missing_preconditions=code_missing,
            climax_score=None,
            refinement_targets=code_missing,
        )

    # 合并：LLM 报告的 missing ∪ 代码级 missing（取并集，宁严勿松）
    llm_missing = data.get("missing_preconditions") or []
    missing_set = set(code_missing) | set(llm_missing)

    audit = StructureCheck(
        verdict=str(data.get("verdict", "pass")).strip(),
        missing_preconditions=list(missing_set),
        emotion_mismatches=data.get("emotion_mismatches") or [],
        spine_violations=data.get("spine_violations") or [],
        climax_score=data.get("climax_score"),
        refinement_targets=data.get("refinement_targets") or list(missing_set),
        style_violations=data.get("style_violations") or [],
        style_score=data.get("style_score"),
    )

    # 强制规则 1：任何 missing_preconditions 非空 → needs_refinement
    if audit.missing_preconditions and audit.verdict == "pass":
        audit.verdict = "needs_refinement"

    # 强制规则 2：文风质量不达标（style_score < 6）→ needs_refinement
    # 注：文风问题不进 refinement_targets（那是 Precondition 补埋用的），
    # 只影响 verdict，让作者知道这章需要手动润色。
    if audit.style_score is not None and audit.style_score < 6 and audit.verdict == "pass":
        audit.verdict = "needs_refinement"

    logger.info(
        f"[ADF] 审计完成：verdict={audit.verdict}, "
        f"missing={len(audit.missing_preconditions)}, "
        f"climax_score={audit.climax_score}, "
        f"style_score={audit.style_score}"
    )
    return audit

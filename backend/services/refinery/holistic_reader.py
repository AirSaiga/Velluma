"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors (AGPL-3.0)
"""

"""
工序 4.5.5：整体回读（Holistic Reader，V4.1 新建）。

职责：1 次 reasoning LLM，读手术后的全文，检查手术之间是否冲突。

设计依据：docs/generation-v4.1-refinery.md §3.5
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.refinery_prompts import build_holistic_read_prompt

logger = logging.getLogger(__name__)


def _extract_json(content: str) -> Optional[dict]:
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", content, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    return None


async def holistic_read(
    full_text: str,
    purpose: str = "",
    emotion_curve: str = "",
    canon_constraints: str = "",
    surgeries_summary: str = "",
    recorder: Optional[RunRecorder] = None,
) -> Dict[str, Any]:
    """工序 4.5.5：整体回读（1 次 reasoning LLM）。

    Args:
        full_text: 修改后的完整正文
        purpose/emotion_curve/canon_constraints: 上下文
        surgeries_summary: 已做的手术摘要
        recorder: RunRecorder

    Returns:
        HolisticVerdict dict：{ verdict, remaining_issues, final_touch_suggestion }
    """
    if not full_text.strip():
        return {"verdict": "pass", "remaining_issues": [], "final_touch_suggestion": ""}

    system_prompt, user_prompt = build_holistic_read_prompt(
        purpose=purpose,
        emotion_curve=emotion_curve,
        canon_constraints=canon_constraints,
        surgeries_summary=surgeries_summary,
        full_text=full_text,
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="refinery.holistic_read",
                model_slot="reasoning",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.1,
                    max_tokens=2048,
                    response_format={"type": "json_object"},
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.1,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
    except Exception as e:
        logger.warning(f"[Refinery] 整体回读失败，降级 pass: {e}")
        return {"verdict": "pass", "remaining_issues": [], "final_touch_suggestion": ""}

    data = _extract_json(result.content)
    if not data:
        logger.warning("[Refinery] 整体回读 JSON 解析失败，降级 pass")
        return {"verdict": "pass", "remaining_issues": [], "final_touch_suggestion": ""}

    verdict = {
        "verdict": str(data.get("verdict", "pass")),
        "remaining_issues": data.get("remaining_issues") or [],
        "final_touch_suggestion": str(data.get("final_touch_suggestion", "")),
    }
    logger.info(f"[Refinery] 整体回读：verdict={verdict['verdict']}")
    return verdict

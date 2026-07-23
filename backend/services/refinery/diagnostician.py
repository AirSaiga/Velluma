"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors (AGPL-3.0)
"""

"""
工序 4.5.1：诊断（Diagnostician，V4.1 新建）。

职责：1 次 reasoning LLM，读全文，输出结构化问题清单。

设计依据：docs/generation-v4.1-refinery.md §3.1

业务场景：
- services/refinery/refinery.py 的 diagnose 阶段调用
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.refinery_prompts import (
    build_diagnostic_prompt,
    parse_diagnostic_response,
)

logger = logging.getLogger(__name__)


async def diagnose(
    raw_text: str,
    purpose: str = "",
    emotion_curve: str = "",
    canon_summary: str = "",
    author_intent: str = "",
    recorder: Optional[RunRecorder] = None,
) -> List[Dict[str, Any]]:
    """工序 4.5.1：诊断（1 次 reasoning LLM）。

    Args:
        raw_text: 待诊断的完整正文
        purpose: 章节主旨
        emotion_curve: 情绪曲线文本
        canon_summary: Canon 摘要
        author_intent: 作者补充意图
        recorder: RunRecorder

    Returns:
        issue dict 列表（每个含 id/location/type/severity/diagnosis/suggestion/impact_radius/status）
    """
    if not raw_text or len(raw_text.strip()) < 200:
        logger.warning("[Refinery] 待诊断文本过短，跳过诊断")
        return []

    system_prompt, user_prompt = build_diagnostic_prompt(
        purpose=purpose,
        emotion_curve=emotion_curve,
        canon_summary=canon_summary,
        author_intent=author_intent,
        full_text=raw_text,
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="refinery.diagnostic",
                model_slot="reasoning",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.2,
                    max_tokens=6144,
                    response_format={"type": "json_object"},
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.2,
                max_tokens=6144,
                response_format={"type": "json_object"},
            )
    except Exception as e:
        logger.warning(f"[Refinery] 诊断 LLM 调用失败: {e}")
        return []

    issues = parse_diagnostic_response(result.content)
    logger.info(f"[Refinery] 诊断完成：{len(issues)} 个问题")
    return issues

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
工序 4.5.6：抛光（Polisher，V4.1 新建）。

职责：1 次 creative LLM，文风统一 + 句式去重 + 章末钩子强化。

设计依据：docs/generation-v4.1-refinery.md §3.6

业务场景：
- services/refinery/refinery.py 的 polish 阶段调用
- 第 4 期会接入"作者样本"做文风指纹学习（当前 v1 用 StyleCard）
"""

import logging
from typing import Any, Dict, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.refinery_prompts import build_polish_prompt

logger = logging.getLogger(__name__)


async def polish(
    full_text: str,
    author_samples: str = "",
    recorder: Optional[RunRecorder] = None,
) -> str:
    """工序 4.5.6：抛光（1 次 creative LLM）。

    Args:
        full_text: 待抛光的完整正文
        author_samples: 作者样本（第 4 期接入文风指纹）
        recorder: RunRecorder

    Returns:
        抛光后的完整正文（失败时返回原文）
    """
    if not full_text.strip():
        return full_text

    system_prompt, user_prompt = build_polish_prompt(
        full_text=full_text,
        author_samples=author_samples,
    )

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="refinery.polish",
                model_slot="creative",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.5,
                    max_tokens=10000,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=0.5,
                max_tokens=10000,
            )
    except Exception as e:
        logger.warning(f"[Refinery] 抛光失败，返回原文: {e}")
        return full_text

    polished = (result.content or "").strip()
    if not polished:
        logger.warning("[Refinery] 抛光返回空，返回原文")
        return full_text

    logger.info(f"[Refinery] 抛光完成：原文 {len(full_text)} 字 → 抛光后 {len(polished)} 字")
    return polished

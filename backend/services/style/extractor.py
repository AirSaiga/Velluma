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
StyleCard 文风画像提炼服务（Phase 1 CP2.2a 新建）。

职责：
- 从作者样本（2-3 段真实文字）提炼结构化文风画像
- 输出 StyleCardCreate 兼容的字段：positive_profile / negative_list / dialogue_ratio_target / paragraph_rhythm
- 失败降级到题材默认画像 + 标 degraded（Phase 0 失败不静默原则）

业务场景：
- POST /api/books/{id}/style-card/extract 端点调用
- 用户上传样本 → LLM 提炼 → 落库 StyleCard

设计依据：
- 蓝图 §6.2 Match My Style 式
- 调研报告 §4.3：作者样本 few-shot 是单一最有效去味手段
- 调研报告 §1.4：失败必须显式降级（不静默通过）

依赖项：
- backend.services.llm.call_llm：1 次 reasoning 调用
- backend.services.prompts.style_extract_prompts：prompt 构建 + 解析
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm import call_llm
from backend.services.prompts.style_extract_prompts import (
    build_style_extract_prompt,
    parse_style_extract_response,
    build_genre_fallback_profile,
)

logger = logging.getLogger(__name__)


async def extract_style_card(
    samples: List[str],
    genre: Optional[str] = None,
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """从作者样本提炼文风画像。

    Args:
        samples: 作者样本文本列表（1-5 段，建议每段 200-2000 字）
        genre: 可选题材（用于兜底画像）
        recorder: 可选 RunRecorder，记录 LLM 调用与降级事件（Phase 0 观测层）

    Returns:
        Dict: {
            positive_profile: dict,
            negative_list: List[dict],
            dialogue_ratio_target: Optional[float],
            paragraph_rhythm: Optional[str],
            degraded: Optional[dict]  # 降级时非空，含 {reason, action}
        }

    Raises:
        无——任何失败都降级处理，不抛出（保证 API 总能返回）
    """
    # 输入校验
    if not samples or not any(s.strip() for s in samples):
        # 极端兜底：完全无样本 → 题材默认画像
        logger.warning("[StyleExtract] 无有效样本，返回题材默认画像")
        return {
            "positive_profile": build_genre_fallback_profile(genre),
            "negative_list": [],
            "dialogue_ratio_target": None,
            "paragraph_rhythm": None,
            "degraded": {
                "reason": "no_valid_samples",
                "action": "genre_fallback",
            },
        }

    # 构建 prompt
    system_prompt, user_prompt = build_style_extract_prompt(samples, genre)

    # LLM 调用（reasoning 槽，温度低保证稳定）
    try:
        raw_response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="reasoning",
            temperature=0.2,
            response_format={"type": "json_object"},
            max_tokens=2000,
        )
    except Exception as e:
        logger.error(f"[StyleExtract] LLM 调用失败: {e}")
        if recorder is not None:
            recorder.record_degraded(
                stage="style.extract",
                reason="llm_call_exception",
                action="genre_fallback",
                model_slot="reasoning",
                detail=f"{type(e).__name__}: {str(e)[:200]}",
            )
        return {
            "positive_profile": build_genre_fallback_profile(genre),
            "negative_list": [],
            "dialogue_ratio_target": None,
            "paragraph_rhythm": None,
            "degraded": {
                "reason": "llm_call_exception",
                "action": "genre_fallback",
                "detail": str(e)[:200],
            },
        }

    # 解析响应
    positive_profile, negative_list, dialogue_ratio, paragraph_rhythm, parse_error = (
        parse_style_extract_response(raw_response)
    )

    if parse_error:
        logger.warning(f"[StyleExtract] 解析失败: {parse_error}，降级")
        if recorder is not None:
            recorder.record_degraded(
                stage="style.extract",
                reason="parse_failed",
                action="genre_fallback",
                model_slot="reasoning",
                detail=parse_error,
            )
        return {
            "positive_profile": build_genre_fallback_profile(genre),
            "negative_list": [],
            "dialogue_ratio_target": None,
            "paragraph_rhythm": None,
            "degraded": {
                "reason": "parse_failed",
                "action": "genre_fallback",
                "detail": parse_error,
            },
        }

    # 成功路径：补全缺失字段
    if not positive_profile:
        positive_profile = build_genre_fallback_profile(genre)

    logger.info(
        f"[StyleExtract] 提炼成功: positive_profile={len(positive_profile)}项, "
        f"negative_list={len(negative_list)}条"
    )

    return {
        "positive_profile": positive_profile,
        "negative_list": negative_list,
        "dialogue_ratio_target": dialogue_ratio,
        "paragraph_rhythm": paragraph_rhythm,
        "degraded": None,
    }

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
章节卡生成服务（Phase 1 CP2.3b 新建）。

职责：从书级大纲+前一章卡+滚动摘要生成结构化章节卡。

业务流程（蓝图 §4.1.3）：
1. 构建 prompt（书级大纲 + 前一章卡 + 滚动摘要 + 开放伏笔 + 涉及角色）
2. LLM 调用（reasoning, temperature=0.3, JSON 输出）
3. 解析为 ChapterCard fields
4. 失败降级：仅用 chapter.outline_text + book.outline 拼接，标 degraded

业务场景：
- POST /api/chapters/{id}/plan 端点调用（CP2.3d）
- 也可独立调用作为"重生成章节卡"工具

依赖项：
- backend.services.llm.call_llm：1 次 reasoning 调用
- backend.services.prompts.chapter_card_prompts：prompt 构建 + 解析
- backend.models.ChapterCard：ORM 模型
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.llm import call_llm
from backend.services.prompts.chapter_card_prompts import (
    build_chapter_card_prompt,
    parse_chapter_card_response,
    build_fallback_card_fields,
)

logger = logging.getLogger(__name__)


async def generate_chapter_card(
    chapter: Any,
    book: Any,
    previous_card: Optional[Any] = None,
    rolling_summary: Optional[str] = None,
    open_hooks: Optional[List[Any]] = None,
    entities: Optional[List[Any]] = None,
    recorder: Optional[Any] = None,
) -> Dict[str, Any]:
    """生成章节卡（1 次 reasoning 调用）。

    Args:
        chapter: Chapter ORM 对象
        book: Book ORM 对象
        previous_card: 前一章 ChapterCard ORM 对象（章节卡链）
        rolling_summary: Book.rolling_summary 或上一章 chapter.summary
        open_hooks: 开放伏笔列表
        entities: 本章关联角色列表
        recorder: 可选 RunRecorder，记录降级事件

    Returns:
        Dict: {
            fields: Dict[str, Any],  # ChapterCard 兼容字段
            degraded: Optional[Dict],  # 降级标记（None 表示成功路径）
            prompts: Dict,  # prompt 历史（调试用）
        }

    Raises:
        无——任何失败都降级处理
    """
    # 构建 prompt
    system_prompt, user_prompt = build_chapter_card_prompt(
        chapter=chapter,
        book=book,
        previous_card=previous_card,
        rolling_summary=rolling_summary,
        open_hooks=open_hooks,
        entities=entities,
    )

    prompts_history = [{
        "stage": "CHAPTER_CARD_GENERATION",
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }]

    # LLM 调用
    try:
        raw_response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="reasoning",
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=3000,
        )
    except Exception as e:
        logger.error(f"[ChapterCard] LLM 调用失败: {e}")
        if recorder is not None:
            recorder.record_degraded(
                stage="plan.chapter_card",
                reason="llm_call_exception",
                action="fallback_to_outline",
                model_slot="reasoning",
                detail=f"{type(e).__name__}: {str(e)[:200]}",
            )
        return {
            "fields": build_fallback_card_fields(chapter, book),
            "degraded": {
                "reason": "llm_call_exception",
                "action": "fallback_to_outline",
                "detail": str(e)[:200],
            },
            "prompts": prompts_history,
        }

    # 解析
    chapter_number = getattr(chapter, "chapter_number", 1)
    fields, parse_error = parse_chapter_card_response(raw_response, chapter_number)

    if parse_error or fields is None:
        logger.warning(f"[ChapterCard] 解析失败: {parse_error}")
        if recorder is not None:
            recorder.record_degraded(
                stage="plan.chapter_card",
                reason="parse_failed",
                action="fallback_to_outline",
                model_slot="reasoning",
                detail=str(parse_error)[:200] if parse_error else "unknown",
            )
        return {
            "fields": build_fallback_card_fields(chapter, book),
            "degraded": {
                "reason": "parse_failed",
                "action": "fallback_to_outline",
                "detail": str(parse_error)[:200] if parse_error else "",
            },
            "prompts": prompts_history,
        }

    # 成功路径
    logger.info(
        f"[ChapterCard] 生成成功: purpose={len(fields.get('purpose') or '')}字, "
        f"events={len(fields.get('must_hit_events') or [])}, "
        f"characters={len(fields.get('involved_characters') or [])}"
    )
    return {
        "fields": fields,
        "degraded": None,
        "prompts": prompts_history,
    }

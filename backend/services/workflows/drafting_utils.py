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
起草阶段公共工具函数。

职责：
- 提供起草阶段被活路径 _execute_unified_path 复用的工具函数
- CP1.0 死代码清理时，从 drafting_prose.py（已删除）抽取的唯一活函数 quick_qc 迁入此处
- 提供 _extract_tail / _clamp_tokens 的便捷别名（底层来自 beat_utils）

业务场景：
- drafting._execute_unified_path 在每拍生成后调用 quick_qc 做长度/结构异常修复
- 滚动前缀计算（extract_tail）与字数 token 上限（clamp_tokens）的统一入口

依赖项：
- backend.services.llm: LLM 调用（quick_qc 内部 review + refine 两步）
- backend.services.prompts: chunk_review / chunk_refine prompt 模板
- backend.services.workflows.beat_utils: extract_tail / clamp_tokens 底层实现
"""

import json
import logging
from typing import Any, List

from backend.services.utils.logging import get_runtime_logger
from backend.services.llm import call_llm
from backend.services.prompts import build_chunk_review_prompt, build_chunk_refine_prompt
from backend.services.workflows.utils import clean_llm_output
from backend.services.workflows.beat_utils import clamp_tokens, extract_tail

logger = get_runtime_logger(__name__)


# 向后兼容别名（drafting_prose.py 删除后，drafting.py 内部仍用这些短名）
_extract_tail = extract_tail
_clamp_tokens = clamp_tokens


async def quick_qc(
    prose_text: str,
    beat: dict,
    beat_index: int,
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    target_words: int,
) -> tuple[str, List[dict]]:
    """生成后轻量质检：仅对长度/结构异常触发，做 review+refine 两步 LLM 修复。

    职责：
    - 检测过短（< 目标 50% 或 <120 字）或无段落分隔（>500 字单段）
    - 异常时调用 LLM review（creative, temp=0.1）→ 若不通过则 refine（creative, temp=0.7）
    - 正常时直接放行，零 LLM 调用

    Args:
        prose_text: 待检文本
        beat: Beat 字典
        beat_index: Beat 序号（1-based）
        chapter: 章节对象
        book: 书籍对象
        entities: 章节关联角色列表
        relationships: 角色关系列表
        target_words: 目标字数

    Returns:
        tuple: (修复后文本, prompts 历史)
    """
    prompts: List[dict] = []

    compact_text = prose_text.replace("\n", "").replace(" ", "")
    has_abnormal_length = len(compact_text) < max(120, int(target_words * 0.5))
    has_abnormal_structure = ("\n\n" not in prose_text) and len(prose_text) > 500

    if not has_abnormal_length and not has_abnormal_structure:
        return prose_text, prompts

    logger.info(f"[QC] Beat {beat_index} 检测到异常，开始修复...")

    try:
        review_system, review_user = build_chunk_review_prompt(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beat_summary=beat.get("summary", ""),
            chunk_text=prose_text,
        )

        prompts.append({
            "stage": "CHUNK_REVIEW",
            "beat_index": beat_index,
            "system_prompt": review_system,
            "user_prompt": review_user,
        })

        review_response = await call_llm(
            system_prompt=review_system,
            user_prompt=review_user,
            model_type="creative",
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=800,
        )

        try:
            review_result = json.loads(clean_llm_output(review_response))
        except json.JSONDecodeError:
            return prose_text, prompts

        if review_result.get("pass", True):
            return prose_text, prompts

        instruction = review_result.get("revision_instruction", "")
        if not instruction:
            issues = review_result.get("issues", [])
            instruction = "; ".join(issues) if issues else "修正文本质量问题"

        logger.info(f"[QC] Beat {beat_index} 修复指令: {instruction[:50]}...")

        refine_system, refine_user = build_chunk_refine_prompt(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beat_summary=beat.get("summary", ""),
            chunk_text=prose_text,
            revision_instruction=instruction,
        )

        prompts.append({
            "stage": "CHUNK_REFINE",
            "beat_index": beat_index,
            "system_prompt": refine_system,
            "user_prompt": refine_user,
        })

        refine_response = await call_llm(
            system_prompt=refine_system,
            user_prompt=refine_user,
            model_type="creative",
            temperature=0.7,
            max_tokens=_clamp_tokens(target_words),
        )

        refined_text = clean_llm_output(refine_response).strip()
        logger.info(f"[QC] Beat {beat_index} 修复完成，新字数 {len(refined_text)}")

        return refined_text, prompts

    except Exception as e:
        logger.error(f"[QC] Beat {beat_index}: {e}")
        return prose_text, prompts


# 向后兼容别名（旧名 _quick_qc 仍被 drafting.py 引用）
_quick_qc = quick_qc

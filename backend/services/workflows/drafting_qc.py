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
起草模块质量控制（QC）函数。

职责：提供起草阶段的质检和微审功能。

主要功能：
- 微审断言检查
- 失败类别推断
- 快速质检
- 文本截取

使用场景：
- workflows/drafting.py: 主起草逻辑调用

依赖：
- backend.services.prompts: build_micro_review_prompt, build_chunk_review_prompt, build_chunk_refine_prompt
- backend.services.llm_client: call_llm
- backend.services.workflows.utils: clean_llm_output
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from backend.schemas import MicroReviewResult
from backend.services.prompts import (
    build_micro_review_prompt,
    build_chunk_review_prompt,
    build_chunk_refine_prompt,
)
from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output


async def _micro_review_assertion(
    chunk_text: str,
    beat: dict,
    scene_intent: dict,
    api_key: str,
    base_url: str,
    model: str,
    stats_callback: Optional[Any] = None,
) -> MicroReviewResult:
    """
    微审断言检查（Fail-Fast Micro-Review）。

    在正文生成后立即进行质量断言，快速发现问题并决定是否重试。
    使用轻量级模型进行断言，减少 token 消耗。

    Args:
        chunk_text: 生成的正文片段
        beat: 节拍数据
        scene_intent: 场景意图
        stats_callback: 统计回调（可选）

    Returns:
        MicroReviewResult: 包含 pass/fail 状态和失败原因
    """
    system_prompt, user_prompt = build_micro_review_prompt(
        chunk_text=chunk_text,
        beat=beat,
        scene_intent=scene_intent,
    )

    # 1. 引入代码级强校验 (ValidatorPipeline)
    from backend.services.workflows.validators import DraftValidatorPipeline
    validator = DraftValidatorPipeline()
    context = {
        "required_entities": beat.get("required_entities", []),
        "forbidden_locations": beat.get("forbidden_locations", []),
        "entities": beat.get("involved_characters", []), # 示例: [{"name": "张三", "traits": ["怯懦"]}]
    }
    
    validation_result = await validator.validate_draft(chunk_text, context)
    if not validation_result.is_valid:
        logger.warning(f"代码级强校验未通过: {validation_result.errors}")
        # 如果存在严重代码级错误，直接阻断，不消耗 Token 进行 LLM 审阅
        return MicroReviewResult(
            passed=False,
            reason="\n".join(validation_result.errors),
            failed_checks=_infer_fail_categories(validation_result.errors[0], ["code_validation"]),
        )

    # 2. 如果代码级校验通过，再调用 LLM 进行语义微审
    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=0.1,
        )

        result = clean_llm_output(response).strip()

        if "PASS" in result.upper():
            return MicroReviewResult(
                passed=True,
                reason="微审通过",
                failed_checks=[],
            )
        else:
            failed_checks = _infer_fail_categories(result, [])
            return MicroReviewResult(
                passed=False,
                reason=result,
                failed_checks=failed_checks,
            )
    except Exception as e:
        logger.warning(f"微审断言失败，降级通过: {e}")
        return MicroReviewResult(
            passed=True,
            reason=f"微审异常降级: {str(e)[:100]}",
            failed_checks=[],
        )


def _infer_fail_categories(
    fail_reason: str,
    failed_checks: List[str]
) -> List[str]:
    """
    从失败原因推断失败类别。

    分析 LLM 返回的失败原因，分类为结构/角色/伏笔等维度，
    便于后续针对性重试。

    Args:
        fail_reason: 原始失败原因文本
        failed_checks: 已有失败检查列表

    Returns:
        推断的失败类别列表
    """
    categories = list(failed_checks)
    reason_lower = fail_reason.lower()

    if any(keyword in reason_lower for keyword in ["结构", "格式", "格式", "章节"]):
        categories.append("structure")
    if any(keyword in reason_lower for keyword in ["角色", "人物", "性格", "POV", "视角"]):
        categories.append("character")
    if any(keyword in reason_lower for keyword in ["伏笔", "hook", "悬念"]):
        categories.append("foreshadowing")
    if any(keyword in reason_lower for keyword in ["逻辑", "连贯", "一致"]):
        categories.append("logic")
    if any(keyword in reason_lower for keyword in ["语言", "文笔", "表达"]):
        categories.append("language")

    if not categories:
        categories.append("unknown")

    return categories


async def _quick_qc(
    draft_chunks: List[dict],
    stats_callback: Optional[Any] = None,
    reasoning_config: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    快速质检（Quick QC）。

    对所有生成的 Beats 进行批量质检，检查：
    - 格式规范性
    - 叙事一致性
    - 伏笔闭合

    Args:
        draft_chunks: 起草片段列表
        stats_callback: 统计回调（可选）
        reasoning_config: 推理配置（可选）

    Returns:
        Dict: 包含 qc_passed 和 issues 列表
    """
    if not draft_chunks:
        return {"qc_passed": True, "issues": []}

    issues = []
    chunk_texts = []
    for chunk in draft_chunks:
        text = chunk.get("draft_chunk", "")
        chunk_texts.append(text)

    combined_text = "\n\n".join(chunk_texts)
    system_prompt, user_prompt = build_chunk_review_prompt(
        chunks=chunk_texts,
        combined_text=combined_text,
    )

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="creative",
            temperature=0.2,
            reasoning_config=reasoning_config,
        )

        result = clean_llm_output(response).strip()

        if "PASS" in result.upper() or "通过" in result:
            return {"qc_passed": True, "issues": []}

        issues.append({
            "type": "quick_qc",
            "description": result,
        })

        return {"qc_passed": False, "issues": issues}

    except Exception as e:
        logger.warning(f"快速质检失败，降级通过: {e}")
        return {"qc_passed": True, "issues": []}


async def refine_chunk_with_feedback(
    chunk_text: str,
    beat: dict,
    feedback: str,
) -> str:
    """
    基于反馈精修片段。

    Args:
        chunk_text: 原始片段
        beat: 节拍数据
        feedback: 反馈内容

    Returns:
        精修后的文本
    """
    system_prompt, user_prompt = build_chunk_refine_prompt(
        chunk_text=chunk_text,
        beat=beat,
        feedback=feedback,
    )

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="creative",
            temperature=0.3,
        )

        return clean_llm_output(response).strip()
    except Exception as e:
        logger.error(f"片段精修失败: {e}")
        return chunk_text

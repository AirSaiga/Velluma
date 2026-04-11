"""
微观审阅模块 - 正文生成的代码级和语义级审阅。

职责：
- 提供代码级强校验（ValidatorPipeline）
- 提供 LLM 级别的微审阅
- 推理失败类别用于重试决策

原子组件：
- _micro_review_assertion: 主审阅入口
- _infer_fail_categories: 失败类别推断
- _quick_qc: 快速质量检查

依赖项：
- backend.services.workflows.validators: 验证器管道
- backend.services.prompts: Prompt 构建

使用方式：
    from backend.services.workflows.drafting_prose_modules.micro_reviewer import (
        micro_review_assertion,
        infer_fail_categories,
        quick_qc,
    )
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.schemas import DynamicContext, MicroReviewResult
from backend.services.llm import call_llm
from backend.services.prompts import (
    build_micro_review_prompt,
    build_chunk_review_prompt,
)
from backend.services.workflows.drafting_thinking import _call_llm_with_stats
from backend.services.workflows.utils import clean_llm_output

logger = logging.getLogger(__name__)

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


def infer_fail_categories(fail_reason: str, failed_checks: List[str]) -> List[str]:
    """
    推断失败类别。

    根据失败原因和检查项推断所属类别，用于重试时的参数调整。

    Args:
        fail_reason: 失败原因文本
        failed_checks: 失败的检查项列表

    Returns:
        失败类别列表，可能包含：
        - 红线: 触及红线/禁忌
        - 物理幻觉: 物理状态/空间位置错误
        - OOC: 角色设定偏离
        - 关系: 角色关系处理错误
        - 文风: 文风问题
        - 其他: 未知原因
    """
    categories = []
    reason_lower = fail_reason.lower()
    checks_lower = [c.lower() for c in failed_checks]

    for check in checks_lower:
        if any(kw in check for kw in ["red_line", "红线", "禁忌"]):
            categories.append("红线")
        elif any(kw in check for kw in ["physical", "物理", "状态", "空间", "位置"]):
            categories.append("物理幻觉")
        elif any(kw in check for kw in ["ooc", "角色", "设定", "性格"]):
            categories.append("OOC")
        elif any(kw in check for kw in ["relation", "关系", "态度", "信任"]):
            categories.append("关系")
        elif any(kw in check for kw in ["style", "文风", "文笔", "语言"]):
            categories.append("文风")

    if any(kw in reason_lower for kw in ["红线", "禁忌", "禁止"]):
        categories.append("红线")
    if any(kw in reason_lower for kw in ["物理", "空间", "位置", "幻觉", "瞬移"]):
        categories.append("物理幻觉")
    if any(kw in reason_lower for kw in ["ooc", "角色", "设定", "性格", "行为偏离"]):
        categories.append("OOC")
    if any(kw in reason_lower for kw in ["关系", "态度", "信任", "敌对", "友好"]):
        categories.append("关系")
    if any(kw in reason_lower for kw in ["文风", "白开水", "ai味", "平淡", "机械", "套路", "模板"]):
        categories.append("文风")

    unique_categories = list(set(categories))
    if not unique_categories:
        unique_categories.append("其他")

    return unique_categories


async def micro_review_assertion(
    chunk_text: str,
    dynamic_context: DynamicContext,
    pov_character: str,
    beat: Optional[dict] = None,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    entity_spatial_ledger: Optional[dict] = None,
    beat_index: Optional[int] = None,
    stats_callback: LLMStatsCallback = None,
    book: Optional[Any] = None,
    chapter: Optional[Any] = None,
    entities: Optional[List[Any]] = None,
) -> Tuple[bool, str, List[str]]:
    """
    微观审阅断言。

    对生成的片段进行代码级和语义级审阅：
    1. 代码级校验：使用 ValidatorPipeline 检查红线、物理状态等
    2. 语义级审阅：使用 LLM 检查角色一致性、逻辑连贯性

    Args:
        chunk_text: 待审阅的文本片段
        dynamic_context: 动态上下文
        pov_character: 视角角色
        beat: 节拍信息
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称
        entity_spatial_ledger: 实体空间台账
        beat_index: 节拍索引
        stats_callback: 统计回调
        book: 书籍对象
        chapter: 章节对象
        entities: 角色实体列表

    Returns:
        Tuple[bool, str, List[str]]:
        - pass_check: 是否通过
        - fail_reason: 失败原因
        - fail_categories: 失败类别列表
    """
    try:
        char_prompts = _extract_character_prompts_for_beat(beat, dynamic_context) if beat else None

        effective_physical_lock = dynamic_context.physical_state_lock
        if entity_spatial_ledger:
            from backend.services.prompts.draft_prompts import _format_entity_spatial_ledger
            spatial_info = _format_entity_spatial_ledger(entity_spatial_ledger)
            if spatial_info:
                effective_physical_lock = f"{effective_physical_lock}\n\n【角色空间绑定】:\n{spatial_info}"

        # ====== 代码级强校验 (ValidatorPipeline) ======
        from backend.services.workflows.validators import DraftValidatorPipeline
        validator = DraftValidatorPipeline()

        val_context = {
            "pacing_type": beat.get("pacing_type", "medium") if beat else "medium",
            "red_lines": beat.get("red_lines", []) if beat else [],
            "required_entities": beat.get("required_entities", []) if beat else [],
            "forbidden_locations": beat.get("forbidden_locations", []) if beat else [],
            "entities": [e.model_dump() if hasattr(e, "model_dump") else e for e in (entities or [])],
            "api_key": api_key,
            "base_url": base_url,
        }

        if book:
            if hasattr(book, "style_blacklist") and book.style_blacklist:
                val_context["style_blacklist"] = book.style_blacklist
            if hasattr(book, "core_motifs_taboos") and book.core_motifs_taboos:
                val_context["taboos"] = book.core_motifs_taboos

        validation_result = await validator.validate_draft(chunk_text, val_context)
        if not validation_result.is_valid:
            logger.warning(f"Beat {beat_index} 代码级强校验未通过: {validation_result.errors}")
            fail_reason = "\n".join(validation_result.errors)
            return False, fail_reason, infer_fail_categories(validation_result.errors[0], ["code_validation"])
        # ===========================================

        system_prompt, user_prompt = build_micro_review_prompt(
            chunk_text=chunk_text,
            physical_state_lock=effective_physical_lock,
            pov_character=pov_character,
            red_lines=beat.get("red_lines") if beat else None,
            relational_state_lock=dynamic_context.relational_state_lock,
            character_static_prompts=char_prompts,
            pov_mode=beat.get("pov_mode", "single") if beat else "single",
            pov_characters=beat.get("pov_characters", []) if beat else [],
        )

        response = await _call_llm_with_stats(
            stage="micro_review",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.0,
            response_format={"type": "json_object"},
            max_tokens=200,
            beat_index=beat_index,
            stats_callback=stats_callback,
        )

        result_text = clean_llm_output(response).strip()
        result = json.loads(result_text)

        review_result = MicroReviewResult(**result)

        failed_reason = review_result.reason or "未知逻辑错误"
        if review_result.failed_checks:
            failed_reason = f"[检查项 {', '.join(review_result.failed_checks)}] {failed_reason}"

        fail_categories = infer_fail_categories(failed_reason, review_result.failed_checks or [])

        if review_result.pass_check:
            return True, "", []
        else:
            return False, failed_reason, fail_categories

    except json.JSONDecodeError as e:
        logger.warning(f"[Fail-Fast] JSON 解析失败: {e}")
        return True, "", []
    except Exception as e:
        logger.warning(f"[Fail-Fast] 断言检查异常: {e}")
        return True, "", []


async def quick_qc(
    prose_text: str,
    beat: dict,
    beat_index: int,
    chapter: Any,
    api_key: str,
    base_url: str,
    model: str,
    word_count: int,
    stats_callback: LLMStatsCallback = None,
) -> Tuple[str, List[dict]]:
    """
    快速质量检查。

    在重试失败后进行轻量级检查：
    - 字数检查
    - 基本格式检查

    Args:
        prose_text: 待检查文本
        beat: 节拍信息
        beat_index: 节拍索引
        chapter: 章节对象
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称
        word_count: 目标字数
        stats_callback: 统计回调

    Returns:
        Tuple[str, List[dict]]:
        - 检查后的文本
        - 使用的 prompt 列表
    """
    prompts = []
    try:
        target_words = get_target_words(beat, word_count)
        min_words = int(target_words * 0.7)

        if len(prose_text) < min_words:
            logger.warning(f"Beat {beat_index}: 字数不足 {len(prose_text)} < {min_words}")

            prompt_pair = build_chunk_review_prompt(
                chunk_text=prose_text,
                beat=beat,
                chapter=chapter,
                target_words=target_words,
            )
            prompts.append(prompt_pair)

            response = await _call_llm_with_stats(
                stage="quick_qc",
                system_prompt=prompt_pair["system_prompt"],
                user_prompt=prompt_pair["user_prompt"],
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.7,
                max_tokens=int(target_words * 1.5),
                beat_index=beat_index,
                stats_callback=stats_callback,
            )

            if response and len(response) > len(prose_text):
                prose_text = response

    except Exception as e:
        logger.error(f"[QC] Beat {beat_index}: {e}")

    return prose_text, prompts


def _extract_character_prompts_for_beat(
    beat: Optional[dict],
    dynamic_context: DynamicContext
) -> Optional[dict[str, str]]:
    """提取节拍的角色提示"""
    if not beat:
        return None

    pov_character = beat.get("pov_character", "")
    present_characters = beat.get("present_characters", []) or [pov_character] if pov_character else []

    if not present_characters:
        return None

    return {}


def get_target_words(beat: dict, total_word_count: int) -> int:
    """获取节拍目标字数"""
    beat_allocation = beat.get("beat_allocation")
    if beat_allocation and isinstance(beat_allocation, (int, float)):
        return int(beat_allocation)

    return int(total_word_count * 0.25)


# 向后兼容别名
_infer_fail_categories = infer_fail_categories
_micro_review_assertion = micro_review_assertion
_quick_qc = quick_qc

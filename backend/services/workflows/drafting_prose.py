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
正文生成模块 - 三种并发策略的 Prose Draft 生成。

职责：提供起草阶段的正文生成功能，支持三种并发策略。

主要功能：
- _generate_prose_serial_v25: 串行滑动窗口正文生成（Rolling Prefix）
- _generate_prose_parallel_v25: 并行模式正文生成（无视前文衔接）
- _generate_prose_semi_parallel_v25: 串行 Cascade 正文生成
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

from backend.schemas import (
    DynamicContext,
    DraftingFeatureFlags,
    MicroReviewResult,
    DynamicStateUpdateResult,
)
from backend.services.prompts import (
    build_prose_draft_prompt_v25,
    build_micro_review_prompt,
    build_emotional_update_prompt,
    build_dynamic_state_update_prompt,
    build_chunk_review_prompt,
    build_chunk_refine_prompt,
)
from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.services.workflows.drafting_thinking import _call_llm_with_stats
from backend.services.workflows.drafting_types import (
    DraftingModels,
    DraftingContext,
    DraftingOptions,
    DraftingCallbacks,
    ProseGenerationState,
    BeatDraftResult as ProseBeatResult,
    BeatContext,
)
from backend.services.workflows.beat_utils import (
    get_target_words,
    safe_get_beat_id,
    safe_get_from_list,
    clamp_tokens,
    extract_tail,
    get_pov_profile,
    build_context_summaries,
    BeatDefaults,
)

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


# 保持向后兼容的别名
_extract_tail = extract_tail
_clamp_tokens = clamp_tokens


async def _micro_review_assertion(
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
) -> tuple[bool, str, List[str]]:
    try:
        char_prompts = _extract_character_prompts_for_beat(beat, dynamic_context) if beat else None

        effective_physical_lock = dynamic_context.physical_state_lock
        if entity_spatial_ledger:
            from backend.services.prompts.draft_prompts import _format_entity_spatial_ledger
            spatial_info = _format_entity_spatial_ledger(entity_spatial_ledger)
            if spatial_info:
                effective_physical_lock = f"{effective_physical_lock}\n\n【角色空间绑定】:\n{spatial_info}"

        # ====== 引入代码级强校验 (ValidatorPipeline) ======
        from backend.services.workflows.validators import DraftValidatorPipeline
        validator = DraftValidatorPipeline()
        
        # 动态组装环境参数和特征数据
        val_context = {
            "pacing_type": beat.get("pacing_type", "medium") if beat else "medium",
            "red_lines": beat.get("red_lines", []) if beat else [],
            "required_entities": beat.get("required_entities", []) if beat else [],
            "forbidden_locations": beat.get("forbidden_locations", []) if beat else [],
            "entities": [e.model_dump() if hasattr(e, "model_dump") else e for e in (entities or [])],
            "api_key": api_key,
            "base_url": base_url,
        }
        
        # 如果书籍有全局设定（如禁忌词、文风黑名单），注入验证器
        if book:
            if hasattr(book, "style_blacklist") and book.style_blacklist:
                val_context["style_blacklist"] = book.style_blacklist
            if hasattr(book, "core_motifs_taboos") and book.core_motifs_taboos:
                val_context["taboos"] = book.core_motifs_taboos

        validation_result = await validator.validate_draft(chunk_text, val_context)
        if not validation_result.is_valid:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Beat {beat_index} 代码级强校验未通过: {validation_result.errors}")
            # 如果存在严重代码级错误，直接阻断，不消耗 Token 进行 LLM 审阅
            # 格式化失败类别，供上层重试逻辑使用
            from backend.services.workflows.drafting_qc import _infer_fail_categories
            fail_reason = "\n".join(validation_result.errors)
            return False, fail_reason, _infer_fail_categories(validation_result.errors[0], ["code_validation"])
        # =================================================

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

        fail_categories = _infer_fail_categories(failed_reason, review_result.failed_checks or [])

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


def _infer_fail_categories(fail_reason: str, failed_checks: List[str]) -> List[str]:
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


async def _quick_qc(
    prose_text: str,
    beat: dict,
    beat_index: int,
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    target_words: int,
) -> tuple[str, List[dict]]:
    prompts = []

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
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=800,
        )

        import json as _json
        try:
            review_result = _json.loads(clean_llm_output(review_response))
        except _json.JSONDecodeError:
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
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=_clamp_tokens(target_words),
        )

        refined_text = clean_llm_output(refine_response).strip()
        logger.info(f"[QC] Beat {beat_index} 修复完成，新字数 {len(refined_text)}")

        return refined_text, prompts

    except Exception as e:
        logger.error(f"[QC] Beat {beat_index}: {e}")
        return prose_text, prompts


def _extract_character_prompts_for_beat(
    beat: Optional[dict],
    dynamic_context: DynamicContext
) -> Optional[dict[str, str]]:
    if not beat:
        return None

    pov_character = beat.get("pov_character", "")
    present_characters = beat.get("present_characters", []) or [pov_character] if pov_character else []

    if not present_characters:
        return None

    return {}


async def _update_dynamic_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
    relational_state_lock: str = "",
    beat_context: Optional[Any] = None,
    book_genre: str = "通用小说",
) -> DynamicStateUpdateResult:
    try:
        system_prompt, user_prompt = build_dynamic_state_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
            relational_state_lock=relational_state_lock,
            beat_context=beat_context,
            book_genre=book_genre,
        )

        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=300,
        )

        result_text = clean_llm_output(response).strip()
        result_json = json.loads(result_text)

        result = DynamicStateUpdateResult(**result_json)
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"[Dynamic State Update] JSON 解析失败: {e}")
        return DynamicStateUpdateResult(
            new_emotional_state=current_emotional_state,
            relational_delta="",
            beat_summary=_extract_fallback_summary(chunk_text)
        )
    except Exception as e:
        logger.warning(f"[Dynamic State Update] 状态更新失败: {e}")
        return DynamicStateUpdateResult(
            new_emotional_state=current_emotional_state,
            relational_delta="",
            beat_summary=_extract_fallback_summary(chunk_text)
        )


def _extract_fallback_summary(text: str, max_len: int = 40) -> str:
    if len(text) <= max_len:
        return text

    truncated = text[:max_len]
    for punct in ["，", "。", "！", "？", ",", ".", "!"]:
        idx = truncated.rfind(punct)
        if idx > 10:
            return truncated[:idx + 1]

    return truncated + "..."


def _build_initial_relational_state(relationships: List[Any], entities: List[Any]) -> str:
    if not relationships:
        return ""

    rel_descriptions = []
    for rel in relationships:
        source = rel.source_character.name if hasattr(rel, 'source_character') and rel.source_character else "?"
        target = rel.target_character.name if hasattr(rel, 'target_character') and rel.target_character else "?"
        rel_type = rel.relation_type if hasattr(rel, 'relation_type') else "未知关系"
        affinity = rel.affinity_score if hasattr(rel, 'affinity_score') else 0

        if affinity <= -50:
            affinity_desc = "敌对"
        elif affinity <= -20:
            affinity_desc = "不信任"
        elif affinity < 20:
            affinity_desc = "中立"
        elif affinity < 50:
            affinity_desc = "友好"
        else:
            affinity_desc = "亲密"

        desc = f"{source} ↔ {target}: {rel_type}（{affinity_desc}）"

        if hasattr(rel, 'interaction_prompt') and rel.interaction_prompt:
            desc += f" - {rel.interaction_prompt}"

        rel_descriptions.append(desc)

    return "\n".join(rel_descriptions)


def _merge_relational_delta(current_state: str, delta: str) -> str:
    MAX_LEN = 300

    if not delta:
        return current_state

    new_state = f"{current_state}\n[更新]: {delta}" if current_state else delta

    if len(new_state) > MAX_LEN:
        return new_state[-MAX_LEN:]

    return new_state


async def _update_emotional_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    try:
        system_prompt, user_prompt = build_emotional_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
        )

        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,
            max_tokens=100,
        )

        new_emotion = clean_llm_output(response).strip()

        if len(new_emotion) > 30:
            for punct in [".", "。", ",", "，"]:
                last_punct = new_emotion.rfind(punct, 0, 30)
                if last_punct > 10:
                    new_emotion = new_emotion[:last_punct + 1]
                    break
            else:
                new_emotion = new_emotion[:30] + "..."

        return new_emotion

    except Exception as e:
        logger.warning(f"[Emotional Update] 情绪更新失败: {e}")
        return current_emotional_state


def _init_serial_context(
    beats: List[dict],
    relationships: List[Any],
    entities: List[Any],
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
) -> DynamicContext:
    """
    初始化串行生成的动态上下文。
    
    Args:
        beats: Beat 列表
        relationships: 关系列表
        entities: 实体列表
        physical_state_lock: 物理状态锁
        entity_spatial_ledger: 实体空间台账
        
    Returns:
        DynamicContext: 初始化的动态上下文
    """
    initial_emotional_state = "初始状态：未知"
    if beats and beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"
    
    initial_relational_state = _build_initial_relational_state(relationships, entities)
    
    return DynamicContext(
        previous_tail="",
        current_emotional_state=initial_emotional_state,
        physical_state_lock=physical_state_lock or "",
        accumulated_summary="",
        relational_state_lock=initial_relational_state,
        entity_spatial_ledger=entity_spatial_ledger or {},
    )


def _adjust_after_failure(
    current_temp: float,
    fail_categories: List[str],
    flags: DraftingFeatureFlags,
    fail_reason: str,
) -> tuple[float, str]:
    """
    根据失败类别调整生成参数。
    
    Args:
        current_temp: 当前温度
        fail_categories: 失败类别列表
        flags: 功能标志
        fail_reason: 失败原因
        
    Returns:
        tuple[float, str]: (新温度, 待处理提示)
    """
    if "文风" in fail_categories:
        new_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
        pending_hint = ""
    else:
        new_temp = max(0.3, current_temp - 0.1)
        pending_hint = f"\n\n【修正要求】上一版本存在以下问题：{fail_reason}。请保持原语境，仅修复该冲突。"
    return new_temp, pending_hint


@dataclass
class _RetryState:
    """内部重试状态（简化版）"""
    attempt: int = 0
    chunk: str = ""
    is_valid: bool = False
    current_temp: float = BeatDefaults.DEFAULT_TEMPERATURE
    pending_hint: str = ""
    prompts_history: List[dict] = None
    
    def __post_init__(self):
        if self.prompts_history is None:
            self.prompts_history = []


async def _execute_generation_with_retry(
    beat_context: "BeatContext",
    generate_once: Callable[[float, str], Awaitable[tuple[str, dict, dict]]],
    validate: Optional[Callable[[str], Awaitable[tuple[bool, str, List[str]]]]],
    flags: DraftingFeatureFlags,
    beat_number: int,
    strategy_name: str = "Generation",
) -> tuple[str, List[dict]]:
    """
    带重试机制的生成执行器。
    
    统一处理三个策略共有的重试逻辑：
    - 初始化重试状态
    - 执行生成（支持 pending_hint 追加）
    - Fail-Fast 验证
    - 参数调整（温度、提示词）
    - 异常处理
    
    Args:
        beat_context: Beat 上下文（用于计算 max_attempts）
        generate_once: 单次生成函数，接收 (temperature, pending_hint)，返回 (chunk, sys_p, usr_p)
        validate: 可选的验证函数，接收 chunk，返回 (is_valid, fail_reason, fail_categories)
        flags: 功能标志
        beat_number: Beat 编号（用于日志）
        strategy_name: 策略名称（用于日志）
        
    Returns:
        tuple[str, List[dict]]: (生成的文本, prompts_history)
    """
    max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
    state = _RetryState()
    
    logger.info(f"[{strategy_name}] Beat {beat_number} 开始生成（最多 {max_attempts} 次尝试）...")
    
    while state.attempt < max_attempts and not state.is_valid:
        state.attempt += 1
        try:
            # 执行单次生成
            chunk, sys_p, usr_p = await generate_once(state.current_temp, state.pending_hint)
            state.chunk = chunk
            
            # 记录 prompt
            state.prompts_history.append({
                "stage": f"PROSE_DRAFT_ATTEMPT_{state.attempt}",
                "beat_index": beat_number,
                "temperature": state.current_temp,
                "system_prompt": sys_p,
                "user_prompt": usr_p,
            })
            
            # 处理空响应
            if not chunk:
                logger.warning(f"[{strategy_name}] Beat {beat_number} 第{state.attempt}次返回空文本")
                if state.attempt < max_attempts:
                    state.current_temp = min(1.0, state.current_temp + 0.1)
                    continue
            
            # Fail-Fast 验证
            if validate and flags.enable_fail_fast and state.attempt < max_attempts:
                is_valid, fail_reason, fail_categories = await validate(chunk)
                if not is_valid:
                    logger.warning(f"[{strategy_name}] Beat {beat_number} 第{state.attempt}次断言失败: {fail_reason}")
                    state.current_temp, state.pending_hint = _adjust_after_failure(
                        state.current_temp, fail_categories, flags, fail_reason
                    )
                else:
                    state.is_valid = True
            else:
                state.is_valid = True
                
        except Exception as e:
            logger.error(f"[{strategy_name}] Beat {beat_number} 第{state.attempt}次异常: {type(e).__name__}: {e}")
            if state.attempt >= max_attempts:
                break
            await asyncio.sleep(1)
    
    logger.info(f"[{strategy_name}] Beat {beat_number} 完成，字数={len(state.chunk)}")
    return state.chunk, state.prompts_history


async def _generate_single_beat_serial(
    beat_context: BeatContext,
    dynamic_context: DynamicContext,
    drafting_context: DraftingContext,
    models: DraftingModels,
    options: DraftingOptions,
    stats_callback: LLMStatsCallback,
) -> dict:
    """
    生成单个 Beat 的正文（串行策略）。
    
    Args:
        beat_context: Beat 上下文（使用 BeatContext 封装）
        dynamic_context: 动态上下文
        drafting_context: 起草上下文
        models: 模型配置
        options: 选项配置
        stats_callback: 统计回调
        
    Returns:
        dict: {"text": ..., "prompts": [...]}
    """
    beat = beat_context.beat
    beat_number = beat_context.beat_number
    flags = options.feature_flags or DraftingFeatureFlags()
    
    # 准备 POV 信息
    pov_profile = get_pov_profile(beat_context.pov_character, drafting_context.entities)
    target_words = beat_context.target_words
    
    # 定义单次生成函数
    async def generate_once(current_temp: float, pending_hint: str) -> tuple[str, str, str]:
        sys_p, usr_p = build_prose_draft_prompt_v25(
            chapter=drafting_context.chapter,
            book=drafting_context.book,
            beat=beat,
            scene_intent=beat_context.scene_intent,
            subconscious_thought=beat_context.subconscious,
            previous_tail=dynamic_context.previous_tail,
            target_words=target_words,
            physical_state_lock=dynamic_context.physical_state_lock,
            current_emotional_state=dynamic_context.current_emotional_state,
            accumulated_summary=dynamic_context.accumulated_summary,
            relational_state_lock=dynamic_context.relational_state_lock,
            red_lines=beat.get("red_lines"),
            entity_spatial_ledger=dynamic_context.entity_spatial_ledger or None,
            chapter_assets_schema=options.chapter_assets_schema or '',
            pov_perception_state=beat_context.pov_perception_state,
            pov_character_profile=pov_profile,
            is_first_beat=beat_context.is_first,
        )
        if pending_hint:
            usr_p = usr_p + pending_hint
        
        response = await _call_llm_with_stats(
            stage="prose_draft",
            system_prompt=sys_p,
            user_prompt=usr_p,
            api_key=models.api_key,
            base_url=models.base_url,
            model=models.creative_model,
            temperature=current_temp,
            max_tokens=_clamp_tokens(target_words),
            beat_index=beat_number,
            stats_callback=stats_callback,
        )
        chunk = clean_llm_output(response).strip()
        return chunk, sys_p, usr_p
    
    # 定义验证函数（仅当启用 fail-fast 时）
    async def validate(chunk: str) -> tuple[bool, str, List[str]]:
        return await _micro_review_assertion(
            chunk_text=chunk,
            dynamic_context=dynamic_context,
            pov_character=beat_context.pov_character,
            beat=beat,
            api_key=models.api_key,
            base_url=models.base_url,
            model=models.reasoning_model,
            entity_spatial_ledger=dynamic_context.entity_spatial_ledger or None,
            beat_index=beat_number,
            stats_callback=stats_callback,
            book=drafting_context.book,
            chapter=drafting_context.chapter,
            entities=drafting_context.entities,
        )
    
    # 使用统一重试执行器
    chunk, prompts_history = await _execute_generation_with_retry(
        beat_context=beat_context,
        generate_once=generate_once,
        validate=validate if flags.enable_fail_fast else None,
        flags=flags,
        beat_number=beat_number,
        strategy_name="Prose V25-Serial",
    )
    
    # QC 检查
    if options.enable_qc and chunk:
        try:
            chunk, qc_prompts = await _quick_qc(
                prose_text=chunk,
                beat=beat,
                beat_index=beat_number,
                chapter=drafting_context.chapter,
                book=drafting_context.book,
                entities=drafting_context.entities,
                relationships=drafting_context.relationships,
                api_key=models.api_key,
                base_url=models.base_url,
                model=models.creative_model,
                target_words=target_words,
            )
            prompts_history.extend(qc_prompts)
        except Exception as e:
            logger.warning(f"[Prose V25-Serial] Beat {beat_number} QC 失败: {e}")
    
    return {"text": chunk, "prompts": prompts_history}


async def _update_context_serial(
    dynamic_context: DynamicContext,
    beat: dict,
    beat_idx: int,
    beats: List[dict],
    result: dict,
    flags: DraftingFeatureFlags,
    reasoning_model: str,
    api_key: str,
    base_url: str,
) -> None:
    """
    更新动态上下文供下一个 Beat 使用。
    
    Args:
        dynamic_context: 动态上下文（会被修改）
        beat: 当前 Beat
        beat_idx: Beat 索引
        beats: 所有 Beats
        result: 生成结果
        flags: 功能标志
        reasoning_model: 推理模型
        api_key: API Key
        base_url: Base URL
    """
    n = len(beats)
    if beat_idx >= n - 1:
        return
    
    pov_ch = beat.get("pov_character", "主角")
    chunk = result["text"]
    beat_number = beat_idx + 1
    
    next_entry = beats[beat_idx + 1].get('entry_state', '未指定')
    current_exit = beat.get('exit_state', '未指定')
    
    # 更新 Rolling Prefix
    pov_anchor = (
        f"\n[System Tracker: 当前主语视角强锁定为 {pov_ch} "
        f"| 当前退出状态: {current_exit} "
        f"| 下一拍进入状态: {next_entry}]"
    )
    dynamic_context.previous_tail = _extract_tail(chunk, max_chars=300) + pov_anchor
    
    # 更新物理状态锁
    if current_exit and current_exit != '未指定':
        dynamic_context.physical_state_lock = (
            f"{pov_ch}当前态势（{beat.get('beat_title', f'Beat {beat_number}')}结束）：{current_exit}"
        )
        logger.debug(f"[Prose V25-Serial] Beat {beat_number} 更新 physical_state_lock: {current_exit[:50]}...")
    
    # 更新情感状态
    if flags.enable_emotional_scratchpad:
        try:
            state_update = await _update_dynamic_state(
                chunk_text=chunk,
                current_emotional_state=dynamic_context.current_emotional_state,
                pov_character=pov_ch,
                api_key=api_key,
                base_url=base_url,
                model=reasoning_model,
                relational_state_lock=dynamic_context.relational_state_lock,
            )
            dynamic_context.current_emotional_state = state_update.new_emotional_state
            if state_update.relational_delta:
                dynamic_context.relational_state_lock = _merge_relational_delta(
                    dynamic_context.relational_state_lock, state_update.relational_delta)
            if state_update.beat_summary:
                dynamic_context.update_summary(state_update.beat_summary)
        except Exception as e:
            logger.warning(f"[Emotional Update] 更新失败: {e}")


async def _generate_prose_serial_v25(
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    creative_model: str,
    reasoning_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: DraftingFeatureFlags = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[dict]:
    """
    V2.5 串行滑动窗口正文生成（Rolling Prefix + DynamicContext）。

    策略：Beat 1 → Beat 2 → ... → Beat N，每个 Beat 使用上一 Beat 的真实正文尾部
    作为 previous_tail，确保全链路 Rolling Prefix 连贯性。
    
    架构：
    - 主函数：控制整体流程
    - _init_serial_context: 初始化动态上下文
    - _generate_single_beat_serial: 生成单个 Beat
    - _update_context_serial: 更新上下文
    """
    flags = feature_flags or DraftingFeatureFlags()
    n = len(beats)
    
    # 构建统一的上下文对象（减少参数传递）
    drafting_context = DraftingContext(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=word_count,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        locations=locations,
    )
    models = DraftingModels(
        creative_model=creative_model,
        reasoning_model=reasoning_model,
        api_key=api_key,
        base_url=base_url,
    )
    options = DraftingOptions(
        enable_qc=enable_qc,
        feature_flags=flags,
        physical_state_lock=physical_state_lock,
        entity_spatial_ledger=entity_spatial_ledger,
        chapter_assets_schema=chapter_assets_schema,
    )
    
    # 初始化上下文
    dynamic_context = _init_serial_context(
        beats, relationships, entities, physical_state_lock, entity_spatial_ledger
    )
    
    # 逐个 Beat 生成
    all_results = []
    for beat_idx, beat in enumerate(beats):
        # 创建 BeatContext 封装单个 Beat 的所有信息
        beat_context = BeatContext(
            beat=beat,
            beat_idx=beat_idx,
            total_beats=n,
            scene_intent=safe_get_from_list(
                scene_intent_results, beat_idx,
                {"intent_label": "默认", "goal": beat.get("summary", "")}
            ),
            subconscious=safe_get_from_list(subconscious_results, beat_idx, ""),
        )
        
        result = await _generate_single_beat_serial(
            beat_context=beat_context,
            dynamic_context=dynamic_context,
            drafting_context=drafting_context,
            models=models,
            options=options,
            stats_callback=stats_callback,
        )
        
        all_results.append(result)
        
        # 更新上下文供下一个 Beat 使用
        await _update_context_serial(
            dynamic_context=dynamic_context,
            beat=beat,
            beat_idx=beat_idx,
            beats=beats,
            result=result,
            flags=flags,
            reasoning_model=reasoning_model,
            api_key=api_key,
            base_url=base_url,
        )
    
    logger.info(f"[Prose V25-Serial] 串行生成完成，共 {n} 个 Beats")
    return all_results


async def _generate_prose_parallel_v25(
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    creative_model: str,
    reasoning_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: DraftingFeatureFlags = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[dict]:
    """
    V3.0 并行模式正文生成 - 极速但可能损失连贯性。
    
    架构：
    - 主函数：创建并行任务并收集结果
    - _generate_single_beat_parallel: 单个 Beat 的并行生成
    - _init_parallel_beat: 初始化并行 Beat 的上下文
    - _execute_parallel_generation: 执行带重试的生成
    - _finalize_parallel_result: 结果后处理
    """
    flags = feature_flags or DraftingFeatureFlags()

    # 构建初始共享上下文
    initial_emotional_state = "初始状态：未知"
    if beats and beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"

    initial_relational_state = _build_initial_relational_state(relationships, entities)

    logger.info(f"[Prose V25-Parallel] 启动并行生成，共 {len(beats)} 个 Beats")

    # 创建并行任务
    tasks = [
        _generate_single_beat_parallel(
            beat=beat,
            beat_index=i + 1,
            scene_intent=safe_get_from_list(
                scene_intent_results, i,
                {"intent_label": "默认", "goal": beat.get("summary", "")}
            ),
            subconscious=safe_get_from_list(subconscious_results, i, ""),
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            initial_emotional_state=initial_emotional_state,
            initial_relational_state=initial_relational_state,
            physical_state_lock=physical_state_lock,
            word_count=word_count,
            total_beats=len(beats),
            creative_model=creative_model,
            reasoning_model=reasoning_model,
            api_key=api_key,
            base_url=base_url,
            chapter_assets_schema=chapter_assets_schema,
            enable_qc=enable_qc,
            flags=flags,
            stats_callback=stats_callback,
        )
        for i, beat in enumerate(beats)
    ]

    # 并行执行所有任务
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理后处理异常
    return [_finalize_parallel_result(r, i + 1) for i, r in enumerate(results)]


def _finalize_parallel_result(result: Any, beat_index: int) -> dict:
    """
    规范化并行任务结果。
    
    Args:
        result: 任务结果或异常
        beat_index: Beat 索引
        
    Returns:
        dict: 规范化的结果 {"text": ..., "prompts": [...]}
    """
    if isinstance(result, Exception):
        logger.error(f"[Prose V25-Parallel] Beat {beat_index}: {result}")
        return {"text": "", "prompts": []}
    return result


def _init_parallel_beat(
    beat: dict,
    beat_index: int,
    entities: List[Any],
    initial_emotional_state: str,
    initial_relational_state: str,
    physical_state_lock: Optional[str],
    word_count: int,
    total_beats: int,
) -> ProseGenerationState:
    """
    初始化单个并行 Beat 的生成状态。
    
    Args:
        beat: 当前 Beat
        beat_index: Beat 索引
        entities: 实体列表
        initial_emotional_state: 初始情感状态
        initial_relational_state: 初始关系状态
        physical_state_lock: 物理状态锁
        word_count: 目标字数
        total_beats: 总 Beat 数
        
    Returns:
        ProseGenerationState: 初始化的生成状态
    """
    pov_character = beat.get("pov_character", "主角")
    pov_profile = get_pov_profile(pov_character, entities)
    pov_perception_state = beat.get("pov_perception_state") or beat.get("entry_state") or "正常"
    target_words = get_target_words(beat, word_count, total_beats)
    
    return ProseGenerationState(
        beat_id=safe_get_beat_id(beat, beat_index),
        pov_character=pov_character,
        pov_profile=pov_profile,
        pov_perception_state=pov_perception_state,
        target_words=target_words,
        initial_emotional_state=initial_emotional_state,
        initial_relational_state=initial_relational_state,
        physical_state_lock=physical_state_lock,
        current_temp=BeatDefaults.DEFAULT_TEMPERATURE,
        prompts_history=[],
    )


async def _execute_parallel_generation(
    state: ProseGenerationState,
    beat: dict,
    beat_index: int,
    scene_intent: dict,
    subconscious: str,
    chapter: Any,
    book: Any,
    entities: List[Any],
    creative_model: str,
    api_key: str,
    base_url: str,
    chapter_assets_schema: str,
    flags: DraftingFeatureFlags,
    stats_callback: LLMStatsCallback,
) -> tuple[str, List[dict], bool]:
    """
    执行并行 Beat 的生成（带重试逻辑）。
    
    Args:
        state: 生成状态
        beat: 当前 Beat
        beat_index: Beat 索引
        scene_intent: Scene Intent
        subconscious: Subconscious thought
        chapter: 章节对象
        book: 书籍对象
        entities: 实体列表
        creative_model: 创作模型
        api_key: API Key
        base_url: Base URL
        chapter_assets_schema: 章节资产模式
        flags: 功能标志
        stats_callback: 统计回调
        
    Returns:
        tuple[str, List[dict], bool]: (生成的文本, Prompts历史, 是否成功)
    """
    max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
    chunk_text = ""
    is_valid = False
    attempt = 0
    
    while attempt < max_attempts and not is_valid:
        attempt += 1
        
        try:
            # 构建 Prompt
            system_prompt, user_prompt = build_prose_draft_prompt_v25(
                chapter=chapter,
                book=book,
                beat=beat,
                scene_intent=scene_intent,
                subconscious_thought=subconscious,
                previous_tail="",
                target_words=state.target_words,
                physical_state_lock=state.physical_state_lock or "",
                current_emotional_state=state.initial_emotional_state,
                accumulated_summary="",
                relational_state_lock=state.initial_relational_state,
                red_lines=beat.get("red_lines"),
                entity_spatial_ledger=None,
                chapter_assets_schema=chapter_assets_schema or '',
                pov_perception_state=state.pov_perception_state,
                pov_character_profile=state.pov_profile,
                is_first_beat=(beat_index == 1),
            )
            
            state.prompts_history.append({
                "stage": f"PROSE_PARALLEL_ATTEMPT_{attempt}",
                "beat_index": beat_index,
                "temperature": state.current_temp,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            })
            
            logger.info(f"[Prose V25-Parallel] Beat {beat_index} 尝试 {attempt}/{max_attempts}...")
            
            # 调用 LLM
            response = await _call_llm_with_stats(
                stage="prose_draft_parallel",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=creative_model,
                temperature=state.current_temp,
                max_tokens=clamp_tokens(state.target_words),
                beat_index=beat_index,
                stats_callback=stats_callback,
            )
            
            chunk_text = clean_llm_output(response).strip()
            
            # Fail-Fast 检查
            if flags.enable_fail_fast and attempt < max_attempts:
                temp_context = DynamicContext(
                    previous_tail="",
                    current_emotional_state=state.initial_emotional_state,
                    physical_state_lock=state.physical_state_lock or "",
                    accumulated_summary="",
                    relational_state_lock=state.initial_relational_state,
                    entity_spatial_ledger={},
                )
                
                is_valid, fail_reason, fail_categories = await _micro_review_assertion(
                    chunk_text=chunk_text,
                    dynamic_context=temp_context,
                    pov_character=state.pov_character,
                    beat=beat,
                    api_key=api_key,
                    base_url=base_url,
                    model=reasoning_model,
                    entity_spatial_ledger=None,
                    beat_index=beat_index,
                    stats_callback=stats_callback,
                    book=book,
                    chapter=chapter,
                    entities=entities,
                )
                
                if not is_valid:
                    logger.warning(f"[Fail-Fast Parallel] Beat {beat_index} 断言失败: {fail_reason}")
                    if "文风" in fail_categories:
                        state.current_temp = min(1.0, state.current_temp + flags.fail_fast_temperature_step)
                    else:
                        state.current_temp = max(0.3, state.current_temp - 0.1)
                else:
                    logger.info(f"[Fail-Fast Parallel] Beat {beat_index} 断言通过")
            else:
                is_valid = True
                
        except Exception as e:
            logger.error(f"[Prose V25-Parallel] Beat {beat_index} 第{attempt}次异常: {e}")
            if attempt >= max_attempts:
                return chunk_text, state.prompts_history, False
    
    return chunk_text, state.prompts_history, is_valid


async def _generate_single_beat_parallel(
    beat: dict,
    beat_index: int,
    scene_intent: dict,
    subconscious: str,
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    initial_emotional_state: str,
    initial_relational_state: str,
    physical_state_lock: Optional[str],
    word_count: int,
    total_beats: int,
    creative_model: str,
    reasoning_model: str,
    api_key: str,
    base_url: str,
    chapter_assets_schema: str,
    enable_qc: bool,
    flags: DraftingFeatureFlags,
    stats_callback: LLMStatsCallback,
) -> dict:
    """
    单个 Beat 的并行生成任务。
    
    每个 Beat 独立生成，不依赖其他 Beat 的结果。
    
    Args:
        beat: 当前 Beat
        beat_index: Beat 索引（从1开始）
        scene_intent: Scene Intent
        subconscious: Subconscious thought
        chapter: 章节对象
        book: 书籍对象
        entities: 实体列表
        relationships: 关系列表
        initial_emotional_state: 初始情感状态
        initial_relational_state: 初始关系状态
        physical_state_lock: 物理状态锁
        word_count: 目标字数
        total_beats: 总 Beat 数
        creative_model: 创作模型
        reasoning_model: 推理模型
        api_key: API Key
        base_url: Base URL
        chapter_assets_schema: 章节资产模式
        enable_qc: 是否启用 QC
        flags: 功能标志
        stats_callback: 统计回调
        
    Returns:
        dict: {"text": ..., "prompts": [...]}
    """
    try:
        # 初始化状态
        state = _init_parallel_beat(
            beat=beat,
            beat_index=beat_index,
            entities=entities,
            initial_emotional_state=initial_emotional_state,
            initial_relational_state=initial_relational_state,
            physical_state_lock=physical_state_lock,
            word_count=word_count,
            total_beats=total_beats,
        )
        
        # 执行生成
        chunk_text, prompts_history, _ = await _execute_parallel_generation(
            state=state,
            beat=beat,
            beat_index=beat_index,
            scene_intent=scene_intent,
            subconscious=subconscious,
            chapter=chapter,
            book=book,
            entities=entities,
            creative_model=creative_model,
            api_key=api_key,
            base_url=base_url,
            chapter_assets_schema=chapter_assets_schema,
            flags=flags,
            stats_callback=stats_callback,
        )
        
        # QC 检查
        if enable_qc and chunk_text:
            try:
                chunk_text, qc_prompts = await _quick_qc(
                    prose_text=chunk_text,
                    beat=beat,
                    beat_index=beat_index,
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    target_words=state.target_words,
                )
                prompts_history.extend(qc_prompts)
            except Exception as e:
                logger.warning(f"[Prose V25-Parallel] Beat {beat_index} QC 失败: {e}")
        
        return {"text": chunk_text, "prompts": prompts_history}
        
    except Exception as e:
        logger.error(f"[Prose V25-Parallel] Beat {beat_index}: {e}")
        return {"text": "", "prompts": []}

async def _generate_prose_semi_parallel_v25(
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    creative_model: str,
    reasoning_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: DraftingFeatureFlags = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[dict]:
    """
    串行 Cascade 正文生成 - 完整 Rolling Prefix 连贯性。

    策略：Beat 1 → Beat 2 → ... → Beat N，每个 Beat 使用上一 Beat 的真实正文尾部
    作为 previous_tail，确保全链路 Rolling Prefix 连贯性。
    
    架构：
    - 主函数：控制整体流程和降级逻辑
    - _init_cascade_context: 初始化 Cascade 上下文
    - _generate_single_beat_cascade: 生成单个 Beat
    - _update_cascade_context: 更新 Cascade 上下文
    """
    flags = feature_flags or DraftingFeatureFlags()
    n = len(beats)

    # 降级：如果 Beats 数量太少，使用全串行模式
    if n <= 2:
        logger.warning("[Prose Serial-Cascade] Beats <= 2，降级为全串行模式")
        return await _generate_prose_serial_v25(
            beats=beats,
            scene_intent_results=scene_intent_results,
            subconscious_results=subconscious_results,
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            api_key=api_key,
            base_url=base_url,
            creative_model=creative_model,
            reasoning_model=reasoning_model,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            enable_qc=enable_qc,
            feature_flags=flags,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            stats_callback=stats_callback,
        )

    # 初始化 Cascade 上下文
    dynamic_context = _init_cascade_context(
        beats=beats,
        relationships=relationships,
        entities=entities,
        physical_state_lock=physical_state_lock,
        entity_spatial_ledger=entity_spatial_ledger,
    )

    # 逐个 Beat 串行生成（保持上下文连贯）
    all_results = []
    for beat_idx, beat in enumerate(beats):
        result = await _generate_single_beat_cascade(
            beat=beat,
            beat_idx=beat_idx,
            beats=beats,
            scene_intent_results=scene_intent_results,
            subconscious_results=subconscious_results,
            dynamic_context=dynamic_context,
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            flags=flags,
            creative_model=creative_model,
            reasoning_model=reasoning_model,
            api_key=api_key,
            base_url=base_url,
            chapter_assets_schema=chapter_assets_schema,
            enable_qc=enable_qc,
            stats_callback=stats_callback,
        )
        
        all_results.append(result)
        
        # 更新上下文供下一个 Beat 使用
        await _update_cascade_context(
            dynamic_context=dynamic_context,
            beat=beat,
            beat_idx=beat_idx,
            beats=beats,
            result=result,
            flags=flags,
            reasoning_model=reasoning_model,
            book_genre=getattr(book, 'genre', '通用小说'),
            api_key=api_key,
            base_url=base_url,
        )

    logger.info(f"[Prose Serial-Cascade] 串行 Cascade 生成完成，共 {n} 个 Beats")
    return all_results


def _init_cascade_context(
    beats: List[dict],
    relationships: List[Any],
    entities: List[Any],
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
) -> DynamicContext:
    """
    初始化串行 Cascade 的动态上下文。
    
    Args:
        beats: Beat 列表
        relationships: 关系列表
        entities: 实体列表
        physical_state_lock: 物理状态锁
        entity_spatial_ledger: 实体空间台账
        
    Returns:
        DynamicContext: 初始化的动态上下文
    """
    initial_emotional_state = "初始状态：未知"
    if beats and beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"
    
    initial_relational_state = _build_initial_relational_state(relationships, entities)
    
    return DynamicContext(
        previous_tail="",
        current_emotional_state=initial_emotional_state,
        physical_state_lock=physical_state_lock or "",
        accumulated_summary="",
        relational_state_lock=initial_relational_state,
        entity_spatial_ledger=entity_spatial_ledger or {},
    )


async def _generate_single_beat_cascade(
    beat: dict,
    beat_idx: int,
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    dynamic_context: DynamicContext,
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    flags: DraftingFeatureFlags,
    creative_model: str,
    reasoning_model: str,
    api_key: str,
    base_url: str,
    chapter_assets_schema: str,
    enable_qc: bool,
    stats_callback: LLMStatsCallback,
) -> dict:
    """
    生成单个 Beat 的正文（串行 Cascade 策略）。
    
    Args:
        beat: 当前 Beat
        beat_idx: Beat 索引（从0开始）
        beats: 所有 Beats
        scene_intent_results: Scene Intent 结果
        subconscious_results: Subconscious 结果
        dynamic_context: 动态上下文
        chapter: 章节对象
        book: 书籍对象
        entities: 实体列表
        relationships: 关系列表
        flags: 功能标志
        creative_model: 创作模型
        reasoning_model: 推理模型
        api_key: API Key
        base_url: Base URL
        chapter_assets_schema: 章节资产模式
        enable_qc: 是否启用 QC
        stats_callback: 统计回调
        
    Returns:
        dict: {"text": ..., "prompts": [...]}
    """
    beat_number = beat_idx + 1
    n = len(beats)
    is_first = (beat_idx == 0)
    
    # 准备 Beat 上下文
    pov_ch = beat.get("pov_character", "主角")
    pov_profile = get_pov_profile(pov_ch, entities)
    pov_perception_state = beat.get("pov_perception_state") or beat.get("entry_state") or "正常"
    target_words = get_target_words(beat, 0, n)
    
    # 初始化状态
    max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
    chunk = ""
    is_ok = False
    attempt = 0
    current_temp = BeatDefaults.DEFAULT_TEMPERATURE
    prompts_history = []
    pending_hint = ""
    
    logger.info(f"[Prose Serial-Cascade] Beat {beat_number}/{n} 开始生成...")
    
    # 重试循环
    while attempt < max_attempts and not is_ok:
        attempt += 1
        try:
            # 获取输入数据
            scene_intent = safe_get_from_list(
                scene_intent_results, beat_idx,
                {"intent_label": "默认", "goal": beat.get("summary", "")}
            )
            subconscious = safe_get_from_list(subconscious_results, beat_idx, "")
            
            # 构建 Prompt
            sys_p, usr_p = build_prose_draft_prompt_v25(
                chapter=chapter,
                book=book,
                beat=beat,
                scene_intent=scene_intent,
                subconscious_thought=subconscious,
                previous_tail=dynamic_context.previous_tail,
                target_words=target_words,
                physical_state_lock=dynamic_context.physical_state_lock,
                current_emotional_state=dynamic_context.current_emotional_state,
                accumulated_summary=dynamic_context.accumulated_summary,
                relational_state_lock=dynamic_context.relational_state_lock,
                red_lines=beat.get("red_lines"),
                entity_spatial_ledger=dynamic_context.entity_spatial_ledger or None,
                chapter_assets_schema=chapter_assets_schema or '',
                pov_perception_state=pov_perception_state,
                pov_character_profile=pov_profile,
                is_first_beat=is_first,
            )
            
            if pending_hint:
                usr_p = usr_p + pending_hint
            
            prompts_history.append({
                "stage": f"PROSE_DRAFT_ATTEMPT_{attempt}",
                "beat_index": beat_number,
                "temperature": current_temp,
                "system_prompt": sys_p,
                "user_prompt": usr_p,
            })
            
            # 调用 LLM
            resp = await _call_llm_with_stats(
                stage="prose_draft",
                system_prompt=sys_p,
                user_prompt=usr_p,
                api_key=api_key,
                base_url=base_url,
                model=creative_model,
                temperature=current_temp,
                max_tokens=_clamp_tokens(target_words),
                beat_index=beat_number,
                stats_callback=stats_callback,
            )
            chunk = clean_llm_output(resp).strip()
            
            # 处理空响应
            if not chunk:
                logger.warning(f"[Prose Serial-Cascade] Beat {beat_number} 第{attempt}次返回空文本")
                if attempt < max_attempts:
                    current_temp = min(1.0, current_temp + 0.1)
                    continue
            
            # Fail-Fast 断言检查
            if flags.enable_fail_fast and attempt < max_attempts:
                is_ok, fail_reason, fail_categories = await _micro_review_assertion(
                    chunk_text=chunk,
                    dynamic_context=dynamic_context,
                    pov_character=pov_ch,
                    beat=beat,
                    api_key=api_key,
                    base_url=base_url,
                    model=reasoning_model,
                    entity_spatial_ledger=dynamic_context.entity_spatial_ledger or None,
                    beat_index=beat_number,
                    stats_callback=stats_callback,
                    book=book,
                    chapter=chapter,
                    entities=entities,
                )
                if not is_ok:
                    logger.warning(f"[Prose Serial-Cascade] Beat {beat_number} 第{attempt}次断言失败: {fail_reason}")
                    if "文风" in fail_categories:
                        current_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
                    else:
                        current_temp = max(0.3, current_temp - 0.1)
                        pending_hint = f"\n\n【修正要求】上一版本存在以下问题：{fail_reason}。请保持原语境，仅修复该冲突。"
                else:
                    is_ok = True
            else:
                is_ok = True
                
        except Exception as e:
            logger.error(f"[Prose Serial-Cascade] Beat {beat_number} 第{attempt}次异常: {type(e).__name__}: {e}")
            if attempt >= max_attempts:
                break
            await asyncio.sleep(1)
    
    # QC 检查
    if enable_qc and chunk:
        try:
            chunk, qc_prompts = await _quick_qc(
                prose_text=chunk,
                beat=beat,
                beat_index=beat_number,
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                api_key=api_key,
                base_url=base_url,
                model=creative_model,
                target_words=target_words,
            )
            prompts_history.extend(qc_prompts)
        except Exception as e:
            logger.warning(f"[Prose Serial-Cascade] Beat {beat_number} QC 失败: {e}")
    
    logger.info(f"[Prose Serial-Cascade] Beat {beat_number} 完成，字数={len(chunk)}")
    
    return {"text": chunk, "prompts": prompts_history}


async def _update_cascade_context(
    dynamic_context: DynamicContext,
    beat: dict,
    beat_idx: int,
    beats: List[dict],
    result: dict,
    flags: DraftingFeatureFlags,
    reasoning_model: str,
    book_genre: str,
    api_key: str,
    base_url: str,
) -> None:
    """
    更新 Cascade 动态上下文供下一个 Beat 使用。
    
    Args:
        dynamic_context: 动态上下文（会被修改）
        beat: 当前 Beat
        beat_idx: Beat 索引
        beats: 所有 Beats
        result: 生成结果
        flags: 功能标志
        reasoning_model: 推理模型
        book_genre: 书籍类型
        api_key: API Key
        base_url: Base URL
    """
    n = len(beats)
    if beat_idx >= n - 1:
        return
    
    pov_ch = beat.get("pov_character", "主角")
    chunk = result["text"]
    beat_number = beat_idx + 1
    
    next_entry = beats[beat_idx + 1].get('entry_state', '未指定')
    current_exit = beat.get('exit_state', '未指定')
    
    # 更新 Rolling Prefix
    pov_anchor = (
        f"\n[System Tracker: 当前主语视角强锁定为 {pov_ch} "
        f"| 当前退出状态: {current_exit} "
        f"| 下一拍进入状态: {next_entry}]"
    )
    dynamic_context.previous_tail = _extract_tail(chunk, max_chars=300) + pov_anchor
    
    # 更新物理状态锁
    if current_exit and current_exit != '未指定':
        dynamic_context.physical_state_lock = (
            f"{pov_ch}当前态势（{beat.get('beat_title', f'Beat {beat_number}')}结束）：{current_exit}"
        )
        logger.debug(f"[Prose Serial-Cascade] Beat {beat_number} 更新 physical_state_lock: {current_exit[:50]}...")
    
    # 更新情感状态
    if flags.enable_emotional_scratchpad:
        try:
            state_update = await _update_dynamic_state(
                chunk_text=chunk,
                current_emotional_state=dynamic_context.current_emotional_state,
                pov_character=pov_ch,
                api_key=api_key,
                base_url=base_url,
                model=reasoning_model,
                relational_state_lock=dynamic_context.relational_state_lock,
                beat_context=beat,
                book_genre=book_genre,
            )
            dynamic_context.current_emotional_state = state_update.new_emotional_state
            if state_update.relational_delta:
                dynamic_context.relational_state_lock = _merge_relational_delta(
                    dynamic_context.relational_state_lock, state_update.relational_delta)
            if state_update.beat_summary:
                dynamic_context.update_summary(state_update.beat_summary)
        except Exception as e:
            logger.warning(f"[Emotional Update] 更新失败: {e}")

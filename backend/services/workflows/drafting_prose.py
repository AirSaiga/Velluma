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

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


def _extract_tail(text: str, max_chars: int = 300) -> str:
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    paragraphs = text.split("\n\n")
    tail_parts = []
    current_length = 0

    for para in reversed(paragraphs):
        if current_length + len(para) + 2 > max_chars:
            remaining = max_chars - current_length
            if remaining > 50:
                sentences = para.split("。")
                partial = ""
                for sent in reversed(sentences):
                    if len(partial) + len(sent) + 1 <= remaining:
                        partial = sent + "。" + partial if partial else sent + "。"
                    else:
                        break
                if partial:
                    tail_parts.insert(0, partial)
            break
        tail_parts.insert(0, para)
        current_length += len(para) + 2

    result = "\n\n".join(tail_parts)

    if len(result) > max_chars:
        result = result[-max_chars:]
        first_period = result.find("。")
        if first_period > 0 and first_period < 50:
            result = result[first_period + 1:]

    return result.strip()


def _clamp_tokens(target_words: int) -> int:
    estimated_tokens = int(target_words * 2)
    return max(1200, min(estimated_tokens, 5200))


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
    """
    flags = feature_flags or DraftingFeatureFlags()
    n = len(beats)

    initial_emotional_state = "初始状态：未知"
    if beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"
    initial_relational_state = _build_initial_relational_state(relationships, entities)

    dynamic_context = DynamicContext(
        previous_tail="",
        current_emotional_state=initial_emotional_state,
        physical_state_lock=physical_state_lock or "",
        accumulated_summary="",
        relational_state_lock=initial_relational_state,
        entity_spatial_ledger=entity_spatial_ledger or {},
    )

    all_results = []

    for beat_idx_0, beat in enumerate(beats):
        beat_number = beat_idx_0 + 1
        is_first = (beat_idx_0 == 0)
        pov_ch = beat.get("pov_character", "主角")

        pov_profile = ""
        if pov_ch and entities:
            for entity in entities:
                char = getattr(entity, 'character', None) or entity
                char_name = getattr(char, 'name', '') or ''
                if char_name and pov_ch in char_name:
                    raw_profile = getattr(char, 'static_prompt', '') or ''
                    pov_profile = raw_profile[:150] if raw_profile else ''
                    break

        pov_perception_state = beat.get("pov_perception_state") or beat.get("entry_state") or "正常"

        target_words = beat.get("word_count_target")
        if not isinstance(target_words, int) or target_words <= 0:
            target_words = beat.get("target_words", max(200, word_count // max(1, n)))

        max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
        chunk = ""
        is_valid = False
        attempt = 0
        current_temp = 0.75
        prompts_history = []
        pending_hint = ""

        logger.info(f"[Prose V25-Serial] Beat {beat_number}/{n} 开始生成...")

        while attempt < max_attempts and not is_valid:
            attempt += 1
            try:
                # 安全检查数组索引
                scene_intent = scene_intent_results[beat_idx_0] if beat_idx_0 < len(scene_intent_results) else {"intent_label": "默认", "goal": beat.get("summary", "")}
                subconscious = subconscious_results[beat_idx_0] if beat_idx_0 < len(subconscious_results) else ""
                
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

                response = await _call_llm_with_stats(
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
                chunk = clean_llm_output(response).strip()

                if not chunk:
                    logger.warning(f"[Prose V25-Serial] Beat {beat_number} 第{attempt}次返回空文本")
                    if attempt < max_attempts:
                        current_temp = min(1.0, current_temp + 0.1)
                        continue

                if flags.enable_fail_fast and attempt < max_attempts:
                    is_valid, fail_reason, fail_categories = await _micro_review_assertion(
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
                    if not is_valid:
                        logger.warning(f"[Prose V25-Serial] Beat {beat_number} 第{attempt}次断言失败: {fail_reason}")
                        if "文风" in fail_categories:
                            current_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
                        else:
                            current_temp = max(0.3, current_temp - 0.1)
                            pending_hint = f"\n\n【修正要求】上一版本存在以下问题：{fail_reason}。请保持原语境，仅修复该冲突。"
                    else:
                        is_valid = True
                else:
                    is_valid = True

            except Exception as e:
                logger.error(f"[Prose V25-Serial] Beat {beat_number} 第{attempt}次异常: {type(e).__name__}: {e}")
                if attempt >= max_attempts:
                    break
                await asyncio.sleep(1)

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
                logger.warning(f"[Prose V25-Serial] Beat {beat_number} QC 失败: {e}")

        all_results.append({"text": chunk, "prompts": prompts_history})
        logger.info(f"[Prose V25-Serial] Beat {beat_number} 完成，字数={len(chunk)}")

        if beat_idx_0 < n - 1:
            next_entry = beats[beat_idx_0 + 1].get('entry_state', '未指定')
            current_exit = beat.get('exit_state', '未指定')
            pov_anchor = (
                f"\n[System Tracker: 当前主语视角强锁定为 {pov_ch} "
                f"| 当前退出状态: {current_exit} "
                f"| 下一拍进入状态: {next_entry}]"
            )
            dynamic_context.previous_tail = _extract_tail(chunk, max_chars=300) + pov_anchor

            if current_exit and current_exit != '未指定':
                dynamic_context.physical_state_lock = (
                    f"{pov_ch}当前态势（{beat.get('beat_title', f'Beat {beat_number}')}结束）：{current_exit}"
                )
                logger.debug(f"[Prose V25-Serial] Beat {beat_number} 更新 physical_state_lock: {current_exit[:50]}...")

            if flags.enable_emotional_scratchpad:
                state_update = await _update_dynamic_state(
                    chunk_text=chunk,
                    current_emotional_state=dynamic_context.current_emotional_state,
                    pov_character=pov_ch,
                    api_key=api_key,
                    base_url=base_url,
                    model=reasoning_model,
                    relational_state_lock=dynamic_context.relational_state_lock,
                    beat_context=beat,
                    book_genre=getattr(book, 'genre', '通用小说'),
                )
                dynamic_context.current_emotional_state = state_update.new_emotional_state
                if state_update.relational_delta:
                    dynamic_context.relational_state_lock = _merge_relational_delta(
                        dynamic_context.relational_state_lock, state_update.relational_delta)
                if state_update.beat_summary:
                    dynamic_context.update_summary(state_update.beat_summary)

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
    """
    flags = feature_flags or DraftingFeatureFlags()

    initial_emotional_state = "初始状态：未知"
    if beats and beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"

    initial_relational_state = _build_initial_relational_state(relationships, entities)

    logger.info(f"[Prose V25-Parallel] 启动并行生成，共 {len(beats)} 个 Beats")

    async def _single_prose_task(
        beat_index: int,
        beat: dict,
        scene_intent: dict,
        subconscious: str,
    ) -> dict:
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        pov_character = beat.get("pov_character", "主角")

        pov_profile = ""
        if pov_character and entities:
            for entity in entities:
                char = getattr(entity, 'character', None) or entity
                char_name = getattr(char, 'name', '') or ''
                if char_name and pov_character in char_name:
                    raw_profile = getattr(char, 'static_prompt', '') or ''
                    pov_profile = raw_profile[:150] if raw_profile else ''
                    break

        try:
            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))

            max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
            chunk_text = ""
            is_valid = False
            attempt = 0
            current_temp = 0.75

            prompts_history = []

            pov_perception_state = beat.get("pov_perception_state") or beat.get("entry_state") or "正常"

            while attempt < max_attempts and not is_valid:
                attempt += 1

                system_prompt, user_prompt = build_prose_draft_prompt_v25(
                    chapter=chapter,
                    book=book,
                    beat=beat,
                    scene_intent=scene_intent,
                    subconscious_thought=subconscious,
                    previous_tail="",
                    target_words=target_words,
                    physical_state_lock=physical_state_lock or "",
                    current_emotional_state=initial_emotional_state,
                    accumulated_summary="",
                    relational_state_lock=initial_relational_state,
                    red_lines=beat.get("red_lines"),
                    entity_spatial_ledger=entity_spatial_ledger or None,
                    chapter_assets_schema=chapter_assets_schema or '',
                    pov_perception_state=pov_perception_state,
                    pov_character_profile=pov_profile,
                    is_first_beat=(beat_index == 1),
                )

                prompts_history.append({
                    "stage": f"PROSE_PARALLEL_ATTEMPT_{attempt}",
                    "beat_index": beat_index,
                    "temperature": current_temp,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                })

                logger.info(f"[Prose V25-Parallel] Beat {beat_index}/{len(beats)} 尝试 {attempt}/{max_attempts}...")

                response = await _call_llm_with_stats(
                    stage="prose_draft_parallel",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    temperature=current_temp,
                    max_tokens=_clamp_tokens(target_words),
                    beat_index=beat_index,
                    stats_callback=stats_callback,
                )

                chunk_text = clean_llm_output(response).strip()

                if flags.enable_fail_fast and attempt < max_attempts:
                    temp_context = DynamicContext(
                        previous_tail="",
                        current_emotional_state=initial_emotional_state,
                        physical_state_lock=physical_state_lock or "",
                        accumulated_summary="",
                        relational_state_lock=initial_relational_state,
                        entity_spatial_ledger=entity_spatial_ledger or {},
                    )

                    is_valid, fail_reason, fail_categories = await _micro_review_assertion(
                        chunk_text=chunk_text,
                        dynamic_context=temp_context,
                        pov_character=pov_character,
                        beat=beat,
                        api_key=api_key,
                        base_url=base_url,
                        model=reasoning_model,
                        entity_spatial_ledger=entity_spatial_ledger,
                        beat_index=beat_index,
                        stats_callback=stats_callback,
                        book=book,
                        chapter=chapter,
                        entities=entities,
                    )

                    if not is_valid:
                        logger.warning(f"[Fail-Fast Parallel] Beat {beat_index} 断言失败: {fail_reason}")
                        if "文风" in fail_categories:
                            current_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
                        else:
                            current_temp = max(0.3, current_temp - 0.1)
                    else:
                        logger.info(f"[Fail-Fast Parallel] Beat {beat_index} 断言通过")
                else:
                    is_valid = True

            if enable_qc:
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
                    target_words=target_words,
                )
                prompts_history.extend(qc_prompts)

            return {
                "text": chunk_text,
                "prompts": prompts_history,
            }

        except Exception as e:
            logger.error(f"[Prose V25-Parallel] Beat {beat_index}: {e}")
            return {
                "text": "",
                "prompts": [],
            }

    # 验证输入数组长度
    if len(scene_intent_results) != len(beats) or len(subconscious_results) != len(beats):
        logger.error(f"[Prose V25-Parallel] 输入数组长度不匹配: beats={len(beats)}, scene_intent={len(scene_intent_results)}, subconscious={len(subconscious_results)}")
        # 补齐数组
        scene_intent_results = scene_intent_results + [{"intent_label": "默认", "goal": ""} for _ in range(len(beats) - len(scene_intent_results))]
        subconscious_results = subconscious_results + ["" for _ in range(len(beats) - len(subconscious_results))]

    tasks = [
        _single_prose_task(
            beat_index=i + 1,
            beat=beat,
            scene_intent=scene_intent_results[i] if i < len(scene_intent_results) else {"intent_label": "默认", "goal": beat.get("summary", "")},
            subconscious=subconscious_results[i] if i < len(subconscious_results) else "",
        )
        for i, beat in enumerate(beats)
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"[Prose V25-Parallel] Beat {i+1} 发生异常: {result}")
            processed_results.append({"text": "", "prompts": []})
        else:
            processed_results.append(result)

    logger.info(f"[Prose V25-Parallel] 并行生成完成，共 {len(processed_results)} 个 Beats")
    return processed_results


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
    """
    flags = feature_flags or DraftingFeatureFlags()
    n = len(beats)

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

    def _get_pov_profile(pov_character: str) -> str:
        if not pov_character or not entities:
            return ""
        for entity in entities:
            char = getattr(entity, 'character', None) or entity
            char_name = getattr(char, 'name', '') or ''
            if char_name and pov_character in char_name:
                raw_profile = getattr(char, 'static_prompt', '') or ''
                return raw_profile[:150] if raw_profile else ''
        return ""

    def _get_pov_perception(beat: dict) -> str:
        return beat.get("pov_perception_state") or beat.get("entry_state") or "正常"

    def _calc_target_words(beat: dict) -> int:
        t = beat.get("word_count_target") or beat.get("target_words") or max(200, word_count // n)
        return t if isinstance(t, int) and t > 0 else max(200, word_count // n)

    initial_emotional_state = "初始状态：未知"
    if beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"
    initial_relational_state = _build_initial_relational_state(relationships, entities)

    dynamic_context = DynamicContext(
        previous_tail="",
        current_emotional_state=initial_emotional_state,
        physical_state_lock=physical_state_lock or "",
        accumulated_summary="",
        relational_state_lock=initial_relational_state,
        entity_spatial_ledger=entity_spatial_ledger or {},
    )

    all_results = []

    for beat_idx_0, beat in enumerate(beats):
        beat_number = beat_idx_0 + 1
        is_first = (beat_idx_0 == 0)
        pov_ch = beat.get("pov_character", "主角")
        pov_pf = _get_pov_profile(pov_ch)
        pov_ps = _get_pov_perception(beat)
        tw = _calc_target_words(beat)
        max_att = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
        chunk = ""
        is_ok = False
        att = 0
        temp = 0.75
        prompts = []
        pending_hint = ""

        logger.info(f"[Prose Serial-Cascade] Beat {beat_number}/{n} 开始生成...")

        while att < max_att and not is_ok:
            att += 1
            try:
                sys_p, usr_p = build_prose_draft_prompt_v25(
                    chapter=chapter,
                    book=book,
                    beat=beat,
                    scene_intent=scene_intent_results[beat_idx_0],
                    subconscious_thought=subconscious_results[beat_idx_0],
                    previous_tail=dynamic_context.previous_tail,
                    target_words=tw,
                    physical_state_lock=dynamic_context.physical_state_lock,
                    current_emotional_state=dynamic_context.current_emotional_state,
                    accumulated_summary=dynamic_context.accumulated_summary,
                    relational_state_lock=dynamic_context.relational_state_lock,
                    red_lines=beat.get("red_lines"),
                    entity_spatial_ledger=dynamic_context.entity_spatial_ledger or None,
                    chapter_assets_schema=chapter_assets_schema or '',
                    pov_perception_state=pov_ps,
                    pov_character_profile=pov_pf,
                    is_first_beat=is_first,
                )
                if pending_hint:
                    usr_p = usr_p + pending_hint
                prompts.append({
                    "stage": f"PROSE_DRAFT_ATTEMPT_{att}",
                    "beat_index": beat_number,
                    "temperature": temp,
                    "system_prompt": sys_p,
                    "user_prompt": usr_p,
                })
                resp = await _call_llm_with_stats(
                    stage="prose_draft",
                    system_prompt=sys_p,
                    user_prompt=usr_p,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    temperature=temp,
                    max_tokens=_clamp_tokens(tw),
                    beat_index=beat_number,
                    stats_callback=stats_callback,
                )
                chunk = clean_llm_output(resp).strip()

                if not chunk:
                    logger.warning(f"[Prose Serial-Cascade] Beat {beat_number} 第{att}次返回空文本")
                    if att < max_att:
                        temp = min(1.0, temp + 0.1)
                        continue

                if flags.enable_fail_fast and att < max_att:
                    is_ok, fail_r, fail_c = await _micro_review_assertion(
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
                        logger.warning(f"[Prose Serial-Cascade] Beat {beat_number} 第{att}次断言失败: {fail_r}")
                        if "文风" in fail_c:
                            temp = min(1.0, temp + flags.fail_fast_temperature_step)
                        else:
                            temp = max(0.3, temp - 0.1)
                            pending_hint = f"\n\n【修正要求】上一版本存在以下问题：{fail_r}。请保持原语境，仅修复该冲突。"
                    else:
                        is_ok = True
                else:
                    is_ok = True
            except Exception as e:
                logger.error(f"[Prose Serial-Cascade] Beat {beat_number} 第{att}次异常: {type(e).__name__}: {e}")
                if att >= max_att:
                    break
                await asyncio.sleep(1)

        if enable_qc and chunk:
            try:
                chunk, qc_ps = await _quick_qc(
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
                    target_words=tw,
                )
                prompts.extend(qc_ps)
            except Exception as e:
                logger.warning(f"[Prose Serial-Cascade] Beat {beat_number} QC 失败: {e}")

        all_results.append({"text": chunk, "prompts": prompts})
        logger.info(f"[Prose Serial-Cascade] Beat {beat_number} 完成，字数={len(chunk)}")

        if beat_idx_0 < n - 1:
            next_entry = beats[beat_idx_0 + 1].get('entry_state', '未指定')
            current_exit = beat.get('exit_state', '未指定')
            pov_anchor = (
                f"\n[System Tracker: 当前主语视角强锁定为 {pov_ch} "
                f"| 当前退出状态: {current_exit} "
                f"| 下一拍进入状态: {next_entry}]"
            )
            dynamic_context.previous_tail = _extract_tail(chunk, max_chars=300) + pov_anchor

            if current_exit and current_exit != '未指定':
                dynamic_context.physical_state_lock = (
                    f"{pov_ch}当前态势（{beat.get('beat_title', f'Beat {beat_number}')}结束）：{current_exit}"
                )
                logger.debug(f"[Prose Serial-Cascade] Beat {beat_number} 更新 physical_state_lock: {current_exit[:50]}...")

            if flags.enable_emotional_scratchpad:
                state_update = await _update_dynamic_state(
                    chunk_text=chunk,
                    current_emotional_state=dynamic_context.current_emotional_state,
                    pov_character=pov_ch,
                    api_key=api_key,
                    base_url=base_url,
                    model=reasoning_model,
                    relational_state_lock=dynamic_context.relational_state_lock,
                    beat_context=beat,
                    book_genre=getattr(book, 'genre', '通用小说'),
                )
                dynamic_context.current_emotional_state = state_update.new_emotional_state
                if state_update.relational_delta:
                    dynamic_context.relational_state_lock = _merge_relational_delta(
                        dynamic_context.relational_state_lock, state_update.relational_delta)
                if state_update.beat_summary:
                    dynamic_context.update_summary(state_update.beat_summary)

    logger.info(f"[Prose Serial-Cascade] 串行 Cascade 生成完成，共 {n} 个 Beats")
    return all_results

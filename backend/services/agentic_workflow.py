import asyncio
import json
import os
import time
from typing import Union, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, PlotLedger, SceneIntent, StoryBeat, ChapterMapLocation
from backend.repositories import MemoryRepository
from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.services.llm_client import call_llm, get_embedding
from backend.services.workflows.planning import assign_pov_to_beats
from backend.services.prompts import (
    build_chunk_draft_prompt,
    build_chunk_review_prompt,
    build_chunk_refine_prompt,
    build_draft_agent_prompt,
    build_formatting_prompt,
    build_planner_agent_prompt,
    build_refine_agent_prompt,
    build_review_agent_prompt,
    build_scene_intent_prompt,
    build_stitch_prompt,
    parse_planner_result,
    parse_review_result,
    parse_scene_intent_result,
)
from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult


def _clean_llm_output(text: str) -> str:
    """
    清理 LLM 输出，尝试解析 JSON 并提取内容，或移除 Markdown 标记。
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # 尝试作为 JSON 解析 (处理 {"title": "...", "content": "..."} 的情况)
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            # 如果包含 content 字段，优先返回 content
            if isinstance(data, dict) and "content" in data:
                return str(data["content"]).strip()
            # 否则如果是纯文本的 value，可能返回整个 dict，视情况而定
            # 这里保守起见，如果解析成功但没有 content，可能不是我们要的格式，
            # 但如果是 {"chunk": "text"} 这种也可以尝试
            if isinstance(data, dict):
                # 尝试常见的字段
                for key in ["content", "text", "body", "chunk", "draft"]:
                    if key in data and isinstance(data[key], str):
                        return data[key].strip()
        except json.JSONDecodeError:
            pass

    # 移除 markdown 代码块 (``` ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            # 移除第一行和最后一行
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
            
    return text


def _clamp_int(value: int, min_value: int, max_value: int) -> int:
    return max(min_value, min(max_value, value))


def _safe_int_from_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return _clamp_int(parsed, min_value, max_value)


def _safe_bool_from_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _to_secs(elapsed: float) -> float:
    return round(max(0.0, elapsed), 3)


def _needs_formatting(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    if len(stripped) < 800:
        return False
    if "\n\n" in stripped:
        return False
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines:
        return False
    long_lines = [line for line in lines if len(line) >= 180]
    return len(long_lines) >= 2


def _is_refine_output_suspiciously_short(original_text: str, refined_text: str, revision_plan: str) -> bool:
    original = (original_text or "").strip()
    refined = (refined_text or "").strip()
    if not original or not refined:
        return False
    if len(refined) >= len(original):
        return False
    ratio = len(refined) / max(1, len(original))
    lowered_plan = str(revision_plan or "").lower()
    has_boundary_rollback = (
        "pacing_overflow" in lowered_plan
        or "回退" in lowered_plan
        or "exit_state" in lowered_plan
        or "red_lines" in lowered_plan
    )
    threshold = 0.55 if has_boundary_rollback else 0.70
    return ratio < threshold and len(original) >= 1200


def _is_minor_only_review(review_result: dict) -> bool:
    issues = review_result.get("issues")
    if not isinstance(issues, list) or not issues:
        return False
    for issue in issues:
        if not isinstance(issue, dict):
            return False
        severity = str(issue.get("severity", "")).strip().lower()
        issue_type = str(issue.get("type", "")).strip().upper()
        if severity not in {"low", "minor"}:
            return False
        if issue_type in {"STRUCTURE", "CHARACTER", "CONSISTENCY"}:
            return False
    return True


async def generate_agentic_chapter_stream(request: GenerateChapterAgenticRequest, db: AsyncSession):
    """
    代理工作流章节生成 (多轮迭代)。

    工作流步骤：
    1. 上下文组装 (ASSEMBLING_CONTEXT) - 从 DB 加载角色、关系
    2. 初稿生成 (DRAFTING) - Draft Agent 创作初稿
    3. 质量审查 (REVIEWING) - Review Agent 检查质量
    4. 迭代精修 (REFINING) - 若审查未通过，基于 revision_plan 重写
    5. 最终输出 (FINAL_TEXT_STREAM) - 输出最终文本

    状态传递：
    - iteration: 当前迭代轮次 (从1开始)
    - current_draft: 当前版本的正文 (初稿或精修稿)
    - revision_plan: 来自 Review Agent 的修改建议
    - review_passed: 审查是否通过

    上下文管理：
    - 角色和关系在首次迭代前一次性加载 (避免重复查询)
    - 章节大纲 (outline_text) 在各阶段保持不变
    - 动态状态不在此流程中更新 (需单独调用 character_state 服务)

    权衡：使用 while 循环 + break 实现迭代，最多为 max_iterations 次。
    警告：若审查一直不通过，会达到最大迭代次数后退出，可能产生低质量内容。
    """
    async for frame in _generate_agentic_chapter_stream(request=request, db=db, confirmed_beats=None):
        yield frame


async def generate_agentic_chapter_stream_with_confirmed_beats(
    request: GenerateChapterAgenticRequest,
    db: AsyncSession,
    confirmed_beats: Union[list[dict], list[ConfirmedStoryBeat]],
):
    async for frame in _generate_agentic_chapter_stream(request=request, db=db, confirmed_beats=confirmed_beats):
        yield frame


def _calculate_beat_word_counts(beats: list[dict], total_chapter_words: int) -> dict[str, int]:
    """
    Calculate target word count for each beat based on pacing and weight.
    Multipliers: Fast=0.8, Medium=1.0, Slow=1.2
    Formula: score = weight * multiplier
    Result: (score / total_score) * total_chapter_words
    """
    multipliers = {
        "Fast": 0.8,
        "Medium": 1.0,
        "Slow": 1.2,
    }
    
    # 1. Calculate scores
    beat_data = []
    total_score = 0.0
    
    for beat in beats:
        # Ensure beat_id exists (handled in caller usually, but safe check)
        beat_id = str(beat.get("beat_id") or "").strip()
        
        # Get weight (default 1.0)
        val = beat.get("weight", 1.0)
        try:
            weight = float(val)
        except (ValueError, TypeError):
            weight = 1.0
            
        # Get pacing (default Medium)
        pacing_raw = str(beat.get("pacing_type", "")).strip()
        # Handle case-insensitive match
        pacing_title = pacing_raw.title()
        if pacing_title in multipliers:
            multiplier = multipliers[pacing_title]
        else:
            multiplier = multipliers["Medium"]
            
        score = weight * multiplier
        beat_data.append({"beat_id": beat_id, "score": score})
        total_score += score

    # 2. Distribute words
    result = {}
    if total_score <= 0:
        # Fallback to even split
        count = total_chapter_words // max(1, len(beats))
        for item in beat_data:
            if item["beat_id"]:
                result[item["beat_id"]] = count
        return result
        
    current_allocated = 0
    for i, item in enumerate(beat_data):
        b_id = item["beat_id"]
        if not b_id:
            continue
            
        if i == len(beat_data) - 1:
            # Last item gets the remainder
            count = max(0, total_chapter_words - current_allocated)
        else:
            count = int((item["score"] / total_score) * total_chapter_words)
            current_allocated += count
        
        result[b_id] = count
        
    return result


def _normalize_confirmed_beats(beats: Union[list[dict], list[ConfirmedStoryBeat]], word_count: int) -> list[dict]:
    # Pre-process to list of dicts to facilitate calculation
    raw_beats: list[dict] = []
    for idx, beat in enumerate(beats, start=1):
        if isinstance(beat, ConfirmedStoryBeat):
            b_dict = beat.model_dump()
        else:
            b_dict = dict(beat or {})
        
        # Ensure beat_id exists for mapping
        if not b_dict.get("beat_id"):
             b_dict["beat_id"] = f"beat-{idx}"
        raw_beats.append(b_dict)
        
    # Calculate word counts
    word_count_map = _calculate_beat_word_counts(raw_beats, word_count)

    normalized: list[dict] = []
    for idx, beat_dict in enumerate(raw_beats, start=1):
        summary = str(beat_dict.get("summary") or "").strip()
        if not summary:
            continue
            
        position = beat_dict.get("position")
        if not isinstance(position, int) or position <= 0:
            position = idx
            
        beat_id = str(beat_dict.get("beat_id")).strip()
        
        # Assign calculated word count
        final_word_count = word_count_map.get(beat_id, 0)
        
        hook_ids = beat_dict.get("hook_ids") if isinstance(beat_dict.get("hook_ids"), list) else []
        red_lines = beat_dict.get("red_lines") if isinstance(beat_dict.get("red_lines"), list) else []
        
        pov_character = str(beat_dict.get("pov_character") or "").strip()
        location = str(beat_dict.get("location") or "").strip()
        worldbuilding_instruction = str(beat_dict.get("worldbuilding_instruction") or "").strip()
        entry_state = str(beat_dict.get("entry_state") or "").strip()
        exit_state = str(beat_dict.get("exit_state") or "").strip()

        normalized.append(
            {
                "position": position,
                "beat_id": beat_id,
                "summary": summary,
                "location": location if location else None,
                "pov_character": pov_character if pov_character else None,
                "action_summary": str(beat_dict.get("action_summary") or "").strip() or summary,
                "worldbuilding_instruction": worldbuilding_instruction if worldbuilding_instruction else None,
                "entry_state": entry_state if entry_state else None,
                "exit_state": exit_state if exit_state else None,
                "red_lines": [str(item).strip() for item in red_lines if str(item).strip()],
                "word_count_target": final_word_count,
                "target_words": final_word_count,
                "hook_ids": [str(item).strip() for item in hook_ids if str(item).strip()],
            }
        )
    return normalized


async def preview_agentic_beats(request: GenerateChapterAgenticRequest, db: AsyncSession) -> dict:
    chapter_result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.story_beats))
        .where(Chapter.id == request.chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        return {"beats": [], "debug_prompt": None}
    
    # Update chapter settings from request for preview
    if request.tension_level is not None:
        chapter.tension_level = request.tension_level
    if request.pacing_style:
        chapter.pacing_style = request.pacing_style

    word_count = request.word_count or 2000
    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()
    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == request.chapter_id)
    )
    entities = entities_result.scalars().all()
    character_ids = [e.entity_id for e in entities]
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    relationships = relationships_result.scalars().all()
    
    # 加载章节地图位置
    locations_result = await db.execute(
        select(ChapterMapLocation)
        .options(selectinload(ChapterMapLocation.location))
        .where(ChapterMapLocation.chapter_id == request.chapter_id)
    )
    locations = locations_result.scalars().all()
    
    hook_max_chapter_number = chapter.chapter_number - 1
    historical_chapter_exists = (
        select(Chapter.id)
        .where(
            Chapter.id == PlotLedger.chapter_id,
            Chapter.chapter_number <= hook_max_chapter_number,
        )
        .exists()
    )
    open_hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            or_(
                PlotLedger.created_at_chapter <= hook_max_chapter_number,
                and_(
                    PlotLedger.created_at_chapter.is_(None),
                    or_(PlotLedger.chapter_id.is_(None), historical_chapter_exists),
                ),
            ),
        )
    )
    open_hook_rows = open_hook_result.scalars().all()
    open_hooks = []
    for row in open_hook_rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        open_hooks.append(
            {
                "hook_id": hook_id,
                "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
                "content": content,
            }
        )
    
    # 获取上一章摘要
    prev_chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    previous_summary = None
    if prev_chapter:
        if prev_chapter.summary:
            previous_summary = prev_chapter.summary
        elif prev_chapter.draft_text:
            # 如果没有摘要，截取上一章最后 1000 字作为参考
            previous_summary = f"（上一章末尾原文）...{prev_chapter.draft_text[-1000:]}"

    planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=word_count,
        open_hooks=open_hooks,
        previous_chapter_summary=previous_summary,
        locations=locations,
        global_taboos=book.core_motifs_taboos if book else None,
        author_intent=request.author_intent,
    )
    planner_result_raw = await call_llm(
        system_prompt=planner_system_prompt,
        user_prompt=planner_user_prompt,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    beats = parse_planner_result(planner_result_raw, chapter.outline_text or "", word_count)
    return {
        "beats": _normalize_confirmed_beats(beats, word_count),
        "debug_prompt": {
            "system_prompt": planner_system_prompt,
            "user_prompt": planner_user_prompt
        }
    }


async def _generate_agentic_chapter_stream(
    request: GenerateChapterAgenticRequest,
    db: AsyncSession,
    confirmed_beats: Optional[Union[list[dict], list[ConfirmedStoryBeat]]],
):
    run_started_at = time.perf_counter()
    stage_seconds: dict[str, float] = {}
    llm_stage_stats: dict[str, dict[str, Union[int, float]]] = {}
    beat_stage_seconds: dict[int, dict[str, float]] = {}
    beat_concurrency = _safe_int_from_env("AGENTIC_BEAT_CONCURRENCY", default=6, min_value=1, max_value=12)

    def record_stage(stage: str, elapsed: float, beat_index: Optional[int] = None):
        stage_seconds[stage] = round(stage_seconds.get(stage, 0.0) + elapsed, 3)
        if beat_index is not None:
            beat_bucket = beat_stage_seconds.setdefault(beat_index, {})
            beat_bucket[stage] = round(beat_bucket.get(stage, 0.0) + elapsed, 3)

    def record_llm(stage: str, elapsed: float, success: bool):
        bucket = llm_stage_stats.setdefault(stage, {"calls": 0, "seconds": 0.0, "failures": 0})
        bucket["calls"] = int(bucket["calls"]) + 1
        bucket["seconds"] = round(float(bucket["seconds"]) + elapsed, 3)
        if not success:
            bucket["failures"] = int(bucket["failures"]) + 1

    def top_stage_items(source: dict[str, float], limit: int = 5) -> list[dict]:
        return [
            {"stage": stage, "seconds": secs}
            for stage, secs in sorted(source.items(), key=lambda item: item[1], reverse=True)[:limit]
        ]

    def metric_frame(label: str, iteration: Optional[int] = None, extra: Optional[dict] = None) -> str:
        llm_calls = sum(int(item["calls"]) for item in llm_stage_stats.values())
        llm_failures = sum(int(item["failures"]) for item in llm_stage_stats.values())
        llm_seconds = round(sum(float(item["seconds"]) for item in llm_stage_stats.values()), 3)
        wall_clock_stage_seconds = {
            key: value
            for key, value in stage_seconds.items()
            if not key.startswith("llm:") and key not in {"BEAT_TOTAL", "ITERATION_TOTAL"}
        }
        aggregate_stage_seconds = {
            key: value
            for key, value in stage_seconds.items()
            if key in {"BEAT_TOTAL", "ITERATION_TOTAL"}
        }
        payload = {
            "event": "METRICS",
            "label": label,
            "iteration": iteration,
            "metrics": {
                "total_seconds": _to_secs(time.perf_counter() - run_started_at),
                "top_stage_seconds": top_stage_items(wall_clock_stage_seconds, 5),
                "aggregate_stage_seconds": top_stage_items(aggregate_stage_seconds, 5),
                "llm": {
                    "calls": llm_calls,
                    "failures": llm_failures,
                    "seconds": llm_seconds,
                    "top_stage_seconds": top_stage_items(
                        {key: float(value["seconds"]) for key, value in llm_stage_stats.items()},
                        5,
                    ),
                },
                "beat_seconds": [
                    {
                        "beat_index": beat_idx,
                        "top_stage_seconds": top_stage_items(stage_map, 3),
                    }
                    for beat_idx, stage_map in sorted(beat_stage_seconds.items(), key=lambda item: item[0])
                ],
            },
        }
        if extra:
            payload["metrics"].update(extra)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def call_llm_timed(
        stage: str,
        *,
        beat_index: Optional[int] = None,
        **kwargs,
    ) -> str:
        llm_started_at = time.perf_counter()
        success = True
        try:
            return await call_llm(**kwargs)
        except Exception:
            success = False
            raise
        finally:
            elapsed = _to_secs(time.perf_counter() - llm_started_at)
            record_stage(f"llm:{stage}", elapsed, beat_index=beat_index)
            record_llm(stage, elapsed, success=success)

    chapter_result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.story_beats))
        .where(Chapter.id == request.chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        yield f"data: {json.dumps({'error': '章节不存在'}, ensure_ascii=False)}\n\n"
        return
    
    # Update chapter settings from request
    if request.tension_level is not None:
        chapter.tension_level = request.tension_level
    if request.pacing_style:
        chapter.pacing_style = request.pacing_style
    
    force_fast_mode = _safe_bool_from_env("AGENTIC_FORCE_FAST_MODE", default=False)
    effective_fast_mode = bool(request.fast_mode or force_fast_mode)
    max_iterations = 1 if effective_fast_mode else request.max_iterations
    word_count = request.word_count or 2000
    yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在从数据库抽取人物卡与关系网...'}, ensure_ascii=False)}\n\n"

    context_started_at = time.perf_counter()
    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()
    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == request.chapter_id)
    )
    entities = entities_result.scalars().all()
    character_ids = [e.entity_id for e in entities]
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    relationships = relationships_result.scalars().all()

    # 加载章节地图位置
    locations_result = await db.execute(
        select(ChapterMapLocation)
        .options(selectinload(ChapterMapLocation.location))
        .where(ChapterMapLocation.chapter_id == request.chapter_id)
    )
    locations = locations_result.scalars().all()

    yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在回顾前文与检索相关伏笔...'}, ensure_ascii=False)}\n\n"

    prev_chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    previous_summary = None
    if prev_chapter:
        if prev_chapter.summary:
            previous_summary = prev_chapter.summary
        elif prev_chapter.draft_text:
            # 如果没有摘要，截取上一章最后 1000 字作为参考
            previous_summary = f"（上一章末尾原文）...{prev_chapter.draft_text[-1000:]}"
    hook_max_chapter_number = chapter.chapter_number - 1
    historical_chapter_exists = (
        select(Chapter.id)
        .where(
            Chapter.id == PlotLedger.chapter_id,
            Chapter.chapter_number <= hook_max_chapter_number,
        )
        .exists()
    )
    open_hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            or_(
                PlotLedger.created_at_chapter <= hook_max_chapter_number,
                and_(
                    PlotLedger.created_at_chapter.is_(None),
                    or_(PlotLedger.chapter_id.is_(None), historical_chapter_exists),
                ),
            ),
        )
    )
    open_hook_rows = open_hook_result.scalars().all()
    open_hooks = []
    for row in open_hook_rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        open_hooks.append(
            {
                "hook_id": hook_id,
                "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
                "content": content,
            }
        )
    
    # Debug log for context injection
    print(f"[DEBUG] Context Injection - Chapter {chapter.chapter_number}")
    print(f"[DEBUG] Previous Summary (Ch {chapter.chapter_number - 1}): {bool(previous_summary)}")
    if previous_summary:
        print(f"[DEBUG] Summary Preview: {previous_summary[:50]}...")

    relevant_memories = []
    if chapter.outline_text:
        try:
            embedding = await get_embedding(chapter.outline_text, request.api_key, request.base_url)
            if embedding:
                memory_repo = MemoryRepository(db)
                relevant_memories = await memory_repo.search_similar(
                    embedding,
                    chapter.book_id,
                    limit=request.rag_top_k,
                    alpha=request.rag_alpha,
                    beta=request.rag_beta,
                    gamma=request.rag_gamma,
                    lambda_decay=request.rag_lambda,
                    exclude_chapter_id=chapter.id,
                    max_chapter_number=chapter.chapter_number - 1,
                )
                print(f"[DEBUG] RAG Search: Found {len(relevant_memories)} relevant memories")
                for m in relevant_memories:
                    print(f"[DEBUG] Memory: {m.chunk_text[:50]}...")
            else:
                print("[DEBUG] RAG Search: Failed to generate embedding")
        except Exception as e:
            print(f"[RAG Error] {e}")
    record_stage("ASSEMBLING_CONTEXT", _to_secs(time.perf_counter() - context_started_at))
    yield metric_frame("ASSEMBLING_CONTEXT_DONE", iteration=0, extra={"fast_mode": effective_fast_mode})

    current_draft = ""
    revision_plan = ""
    iteration = 0
    review_passed = False
    
    # 全局 Prompt 调试记录
    debug_history = []
    skip_drafting_stitching = False

    while iteration < max_iterations:
        iteration_started_at = time.perf_counter()
        iteration += 1
        if iteration == 1:
            if confirmed_beats:
                beats = _normalize_confirmed_beats(confirmed_beats, word_count)
                yield f"data: {json.dumps({'event': 'PLANNING', 'message': f'已加载并确认 {len(beats)} 个剧情节拍，准备进入正文生成...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            else:
                planning_started_at = time.perf_counter()
                yield f"data: {json.dumps({'event': 'PLANNING', 'message': 'Planner 正在拆分章节 beats...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
                planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    word_count=word_count,
                    open_hooks=open_hooks,
                    previous_chapter_summary=previous_summary,
                    locations=locations,
                    global_taboos=book.core_motifs_taboos if book else None,
                    author_intent=request.author_intent,
                )
                
                yield f"data: {json.dumps({'prompt': {'system_prompt': planner_system_prompt, 'user_prompt': planner_user_prompt}}, ensure_ascii=False)}\n\n"
                debug_history.append({
                    "stage": "PLANNING",
                    "iteration": iteration,
                    "system_prompt": planner_system_prompt,
                    "user_prompt": planner_user_prompt
                })
                planner_result_raw = await call_llm_timed(
                    "planner",
                    system_prompt=planner_system_prompt,
                    user_prompt=planner_user_prompt,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    max_tokens=1800,
                )
                beats = parse_planner_result(planner_result_raw, chapter.outline_text or "", word_count)
                beats = _normalize_confirmed_beats(beats, word_count)
                record_stage("PLANNING", _to_secs(time.perf_counter() - planning_started_at))
                yield metric_frame("PLANNING_DONE", iteration=iteration, extra={"beat_count": len(beats)})
            
            # ------------------------------------------------------------------
            # Auto-Assign POV to Beats
            # ------------------------------------------------------------------
            try:
                yield f"data: {json.dumps({'event': 'PLANNING', 'message': '正在为剧情节拍分配 POV 角色...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
                
                # Construct character list for POV assignment
                pov_candidates = []
                for entity in entities:
                    char = entity.character
                    if char:
                        role_desc = "Main Character" if char.importance_level >= 8 else "Supporting Character"
                        pov_candidates.append({
                            "name": char.name,
                            "role": role_desc,
                            "description": char.static_prompt or ""
                        })
                
                book_title = book.title if book else "Unknown Book"
                story_premise = f"Title: {book_title}\nChapter Outline: {chapter.outline_text or ''}"
                
                beats, pov_prompt_data = await assign_pov_to_beats(
                    beats=beats,
                    characters=pov_candidates,
                    story_premise=story_premise,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                )

                yield f"data: {json.dumps({'prompt': pov_prompt_data}, ensure_ascii=False)}\n\n"
                debug_history.append({
                    "stage": "POV_ASSIGNMENT",
                    "iteration": iteration,
                    "system_prompt": pov_prompt_data["system_prompt"],
                    "user_prompt": pov_prompt_data["user_prompt"]
                })
                
                # Re-normalize to ensure structure is consistent
                beats = _normalize_confirmed_beats(beats, word_count)
                
            except Exception as e:
                print(f"[POV Assignment Error] {e}")
                # Continue even if assignment fails, beats will have default/empty POV
            
            generated_chunks = [None] * len(beats)
            story_beats = []

            for beat_index, beat in enumerate(beats, start=1):
                story_beat = StoryBeat(
                    book_id=chapter.book_id,
                    chapter_id=chapter.id,
                    beat_id=beat.get("beat_id"),
                    beat_type="progression",
                    position=beat.get("position", beat_index),
                    location=beat.get("location"),
                    pov_character=beat.get("pov_character"),
                    action_summary=beat.get("action_summary"),
                    worldbuilding_instruction=beat.get("worldbuilding_instruction"),
                    entry_state=beat.get("entry_state"),
                    exit_state=beat.get("exit_state"),
                    red_lines=beat.get("red_lines", []),
                    word_count_target=beat.get("word_count_target", beat.get("target_words", 0)),
                    summary=beat.get("summary", ""),
                    meta={"target_words": beat.get("target_words", 0)},
                    status="planned",
                )
                db.add(story_beat)
                story_beats.append(story_beat)
            await db.flush()

            async def process_beat(
                beat_index: int,
                beat: dict,
                story_beat: StoryBeat,
            ) -> tuple[int, str, list[dict]]:
                """处理单个剧情节拍的生成流程。

                包含三个阶段：
                1. Scene Intent - 构建场景意图
                2. Chunk Draft - 生成草稿内容
                3. Chunk QC - 质量检查循环（可选）

                Args:
                    beat_index: 节拍索引（从1开始）
                    beat: 包含节拍信息的字典，如 summary、word_count_target、pov_character 等
                    story_beat: 数据库中的 StoryBeat 实体对象

                Returns:
                    tuple[int, str, list[dict]]:
                    - beat_index - 1: 返回索引（从0开始）
                    - chunk_text: 生成的文本内容
                    - beat_prompts: 调试用的提示词历史列表

                Raises:
                    Exception: 任何在处理过程中发生的异常都会被捕获并记录，返回空字符串
                """
                beat_started_at = time.perf_counter()
                beat_prompts = []
                try:
                    beat_hook_ids = set(beat.get("hook_ids", []))
                    beat_open_hooks = []
                    if beat_hook_ids:
                        beat_open_hooks = [
                            item
                            for item in open_hooks
                            if item["hook_id"] in beat_hook_ids or item["ledger_key"] in beat_hook_ids
                        ]
                    if not beat_open_hooks and beat_index == 1:
                        beat_open_hooks = open_hooks[:2]

                    scene_system_prompt, scene_user_prompt = build_scene_intent_prompt(
                        chapter=chapter,
                        beat=beat,
                        open_hooks=beat_open_hooks,
                    )
                    beat_prompts.append({
                        "stage": "SCENE_INTENT",
                        "beat_index": beat_index,
                        "system_prompt": scene_system_prompt,
                        "user_prompt": scene_user_prompt
                    })
                    scene_intent_raw = await call_llm_timed(
                        "scene_intent",
                        beat_index=beat_index,
                        system_prompt=scene_system_prompt,
                        user_prompt=scene_user_prompt,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                        temperature=0.2,
                        response_format={"type": "json_object"},
                        max_tokens=900,
                    )
                    scene_intent_data = parse_scene_intent_result(scene_intent_raw, beat.get("summary", ""))

                    target_words = beat.get("word_count_target")
                    if not isinstance(target_words, int) or target_words <= 0:
                        target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))

                    context_summaries = {}
                    if beat_index > 1:
                        context_summaries['prev'] = beats[beat_index - 2].get('summary', '')
                    if beat_index < len(beats):
                        context_summaries['next'] = beats[beat_index].get('summary', '')

                    chunk_system_prompt, chunk_user_prompt = build_chunk_draft_prompt(
                        chapter=chapter,
                        book=book,
                        entities=entities,
                        relationships=relationships,
                        beat=beat,
                        scene_intent=scene_intent_data,
                        target_words=target_words,
                        previous_chunks=[], 
                        previous_summary=previous_summary,
                        relevant_memories=relevant_memories,
                        hook_contexts=beat_open_hooks,
                        context_beat_summaries=context_summaries,
                        locations=locations,
                    )
                    beat_prompts.append({
                        "stage": "CHUNK_DRAFT",
                        "beat_index": beat_index,
                        "system_prompt": chunk_system_prompt,
                        "user_prompt": chunk_user_prompt
                    })

                    chunk_text = await call_llm_timed(
                        "chunk_draft",
                        beat_index=beat_index,
                        system_prompt=chunk_system_prompt,
                        user_prompt=chunk_user_prompt,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                        temperature=0.7,
                        max_tokens=_clamp_int(max(1200, target_words * 3), 1200, 5200),
                    )
                    chunk_text = _clean_llm_output(chunk_text)
                    chunk_iteration = 0
                    max_chunk_retries = 1
                    compact_chunk_text = chunk_text.strip()
                    has_abnormal_length = len(compact_chunk_text) < max(120, int(target_words * 0.5))
                    has_abnormal_structure = ("\n\n" not in compact_chunk_text) and len(compact_chunk_text) > 500
                    run_chunk_qc = has_abnormal_length or has_abnormal_structure
                    while run_chunk_qc and chunk_iteration < max_chunk_retries:
                        try:
                            c_sys, c_user = build_chunk_review_prompt(
                                chapter, book, entities, relationships, beat.get("summary", ""), chunk_text
                            )
                            beat_prompts.append({
                                "stage": "CHUNK_REVIEW",
                                "beat_index": beat_index,
                                "iteration": chunk_iteration,
                                "system_prompt": c_sys,
                                "user_prompt": c_user
                            })
                            c_res_raw = await call_llm_timed(
                                "chunk_review",
                                beat_index=beat_index,
                                system_prompt=c_sys,
                                user_prompt=c_user,
                                api_key=request.api_key,
                                base_url=request.base_url,
                                model=request.model,
                                temperature=0.1,
                                response_format={"type": "json_object"},
                                max_tokens=1000,
                            )
                            try:
                                c_res = json.loads(_clean_llm_output(c_res_raw))
                            except json.JSONDecodeError:
                                break
                            if c_res.get("pass", False):
                                break
                            instruction = c_res.get("revision_instruction", "") or "; ".join(c_res.get("issues", []))
                            if not instruction:
                                break
                            print(f"[Chunk Refine] Beat {beat_index} Refine {chunk_iteration+1}: {instruction}")
                            r_sys, r_user = build_chunk_refine_prompt(
                                chapter, book, entities, relationships, beat.get("summary", ""), chunk_text, instruction
                            )
                            beat_prompts.append({
                                "stage": "CHUNK_REFINE",
                                "beat_index": beat_index,
                                "iteration": chunk_iteration,
                                "system_prompt": r_sys,
                                "user_prompt": r_user
                            })
                            chunk_text = await call_llm_timed(
                                "chunk_refine",
                                beat_index=beat_index,
                                system_prompt=r_sys,
                                user_prompt=r_user,
                                api_key=request.api_key,
                                base_url=request.base_url,
                                model=request.model,
                                temperature=0.7,
                                max_tokens=_clamp_int(max(1200, target_words * 3), 1200, 5200),
                            )
                            chunk_text = _clean_llm_output(chunk_text)
                            chunk_iteration += 1
                        except Exception as inner_e:
                            print(f"[Chunk Loop Error] Beat {beat_index}: {inner_e}")
                            break

                    record_stage("BEAT_TOTAL", _to_secs(time.perf_counter() - beat_started_at), beat_index=beat_index)
                    return beat_index - 1, chunk_text, beat_prompts
                except Exception as e:
                    print(f"[Beat Error] Beat {beat_index} failed: {e}")
                    return beat_index - 1, "", beat_prompts

            if skip_drafting_stitching and 'beat_chunk_map' in dir() and beat_chunk_map:
                yield f"data: {json.dumps({'event': 'SKIP_DRAFTING', 'message': '局部精修后跳过 DRAFTING，使用已缓存的 chunks...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
                generated_chunks = [beat_chunk_map.get(f"beat_{i+1}", "") for i in range(len(beats))]
                all_beat_prompts = []
            else:
                # ========================================================================
                # 新架构：混合流水线（冰山模型 + Rolling Prefix）
                # ========================================================================
                drafting_started_at = time.perf_counter()
                yield f"data: {json.dumps({'event': 'DRAFTING', 'message': f'正在执行混合流水线：SceneIntent→Subconscious→Prose (Rolling Prefix)...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
                
                # 使用新的 execute_draft_stage 替代原有的并行生成
                # 双模型配置：如果提供了 reasoning_model/creative_model 则使用，否则使用默认 model
                reasoning_model = request.reasoning_model or request.model
                creative_model = request.creative_model or reasoning_model
                
                # V2.5 功能开关配置
                feature_flags = getattr(request, 'feature_flags', None)
                
                # 尝试从章节或书籍中提取物理状态锁定描述
                physical_state_lock = None
                if hasattr(chapter, 'entry_state') and chapter.entry_state:
                    physical_state_lock = chapter.entry_state
                elif beats and beats[0].get('entry_state'):
                    physical_state_lock = beats[0].get('entry_state')
                
                draft_results = await execute_draft_stage(
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    beats=beats,
                    open_hooks=open_hooks,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    reasoning_model=reasoning_model,
                    creative_model=creative_model,
                    word_count=word_count,
                    previous_summary=previous_summary,
                    relevant_memories=relevant_memories,
                    locations=locations,
                    enable_qc=True,
                    feature_flags=feature_flags,
                    physical_state_lock=physical_state_lock,
                )
                
                record_stage("DRAFTING", _to_secs(time.perf_counter() - drafting_started_at))
                yield metric_frame(
                    "DRAFTING_DONE",
                    iteration=iteration,
                    extra={
                        "beat_count": len(beats),
                        "concurrency": 1,  # Rolling Prefix 串行生成
                        "iceberg_model": True,
                    },
                )

                # 提取生成结果
                generated_chunks = [result.draft_chunk for result in draft_results]
                
                # 组装 prompts 用于 debug
                all_beat_prompts = []
                for result in draft_results:
                    all_beat_prompts.extend(result.prompts)
                    # 添加 subconscious 阶段的 prompt 记录
                    all_beat_prompts.append({
                        "stage": "SUBCONSCIOUS",
                        "beat_index": result.beat_index,
                        "beat_id": result.beat_id,
                        "subconscious_thought": result.subconscious_thought,
                    })
            
            # 将 beat prompts 按 beat_index 和 stage 排序后加入 debug_history
            all_beat_prompts.sort(key=lambda x: (x.get("beat_index", 0), x.get("stage", "")))
            debug_history.append({
                "stage": "DRAFTING",
                "iteration": iteration,
                "beat_prompts": all_beat_prompts
            })

            beat_chunk_map = {f"beat_{i+1}": chunk for i, chunk in enumerate(generated_chunks) if chunk}

            stitching_started_at = time.perf_counter()
            yield f"data: {json.dumps({'event': 'STITCHING', 'message': '统稿 Agent 正在拼接 chunks...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            stitch_system_prompt, stitch_user_prompt = build_stitch_prompt(
                chapter=chapter,
                beats=beats,
                chunks=generated_chunks,
                word_count=word_count,
            )
            yield f"data: {json.dumps({'prompt': {'system_prompt': stitch_system_prompt, 'user_prompt': stitch_user_prompt}}, ensure_ascii=False)}\n\n"
            debug_history.append({
                "stage": "STITCHING",
                "iteration": iteration,
                "system_prompt": stitch_system_prompt,
                "user_prompt": stitch_user_prompt
            })
            current_draft = await call_llm_timed(
                "stitch",
                system_prompt=stitch_system_prompt,
                user_prompt=stitch_user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.4,
                max_tokens=10000,
            )
            current_draft = _clean_llm_output(current_draft)
            if not current_draft.strip():
                current_draft = "\n\n".join(generated_chunks).strip()
            if not current_draft.strip():
                fallback_system_prompt, fallback_user_prompt = build_draft_agent_prompt(
                    chapter,
                    book,
                    entities,
                    relationships,
                    word_count,
                    previous_summary=previous_summary,
                    relevant_memories=relevant_memories,
                )
                yield f"data: {json.dumps({'prompt': {'system_prompt': fallback_system_prompt, 'user_prompt': fallback_user_prompt}}, ensure_ascii=False)}\n\n"
                debug_history.append({
                    "stage": "FALLBACK_DRAFT",
                    "iteration": iteration,
                    "system_prompt": fallback_system_prompt,
                    "user_prompt": fallback_user_prompt
                })
                current_draft = await call_llm_timed(
                    "fallback_draft",
                    system_prompt=fallback_system_prompt,
                    user_prompt=fallback_user_prompt,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                    temperature=0.7,
                    max_tokens=_clamp_int(max(2400, word_count * 3), 2400, 7000),
                )
                current_draft = _clean_llm_output(current_draft)
            record_stage("STITCHING", _to_secs(time.perf_counter() - stitching_started_at))
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
            yield metric_frame("STITCHING_DONE", iteration=iteration)
        else:
            # ============================================================
            # [暂时禁用] Refine 步骤已跳过，直接进入下一轮或结束
            # 保留代码以便后续可能的测试
            # ============================================================
            pass
            # refining_started_at = time.perf_counter()
            # yield f"data: {json.dumps({'event': 'REFINING', 'message': f'发现逻辑遗漏，正在通知责编重写 (第{iteration}次)...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            # draft_before_refine = current_draft
            # system_prompt, user_prompt = build_refine_agent_prompt(
            #     chapter, book, entities, relationships, current_draft, revision_plan, word_count
            # )
            # yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
            # debug_history.append({
            #     "stage": "REFINING",
            #     "iteration": iteration,
            #     "system_prompt": system_prompt,
            #     "user_prompt": user_prompt
            # })
            # current_draft = await call_llm_timed(
            #     "refine",
            #     system_prompt=system_prompt,
            #     user_prompt=user_prompt,
            #     api_key=request.api_key,
            #     base_url=request.base_url,
            #     model=request.model,
            #     temperature=0.7,
            #     max_tokens=10000,
            # )
            # current_draft = _clean_llm_output(current_draft)
            # if _is_refine_output_suspiciously_short(draft_before_refine, current_draft, revision_plan):
            #     retry_user_prompt = (
            #         f"{user_prompt}\n\n"
            #         "【纠偏指令】你上一版疑似发生了内容截断或过度删段。"
            #         "请基于【当前初稿】重新完整重写，必须保留关键段落信息与叙事链路，禁止大幅删段。"
            #     )
            #     current_draft_retry = await call_llm_timed(
            #         "refine_retry",
            #         system_prompt=system_prompt,
            #         user_prompt=retry_user_prompt,
            #         api_key=request.api_key,
            #         base_url=request.base_url,
            #         model=request.model,
            #         temperature=0.7,
            #         max_tokens=10000,
            #     )
            #     current_draft_retry = _clean_llm_output(current_draft_retry)
            #     if not _is_refine_output_suspiciously_short(draft_before_refine, current_draft_retry, revision_plan):
            #         current_draft = current_draft_retry
            #     else:
            #         current_draft = draft_before_refine
            # record_stage("REFINING", _to_secs(time.perf_counter() - refining_started_at))
            # chapter.draft_text = current_draft
            # chapter.revision_count = iteration
            # await db.commit()
            # yield metric_frame("REFINING_DONE", iteration=iteration)

        reviewing_started_at = time.perf_counter()
        yield f"data: {json.dumps({'event': 'REVIEWING', 'message': '审阅 Agent 正在进行逻辑校验和 OOC 排查...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
        system_prompt, user_prompt = build_review_agent_prompt(
            chapter, book, entities, relationships, chapter.outline_text or "", current_draft, beats
        )
        yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
        debug_history.append({
            "stage": "REVIEWING",
            "iteration": iteration,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt
        })
        review_result_json = await call_llm_timed(
            "review",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=1600,
        )
        review_result, _ = parse_review_result(review_result_json)
        record_stage("REVIEWING", _to_secs(time.perf_counter() - reviewing_started_at))
        chapter.review_feedback = review_result
        await db.commit()
        yield metric_frame("REVIEWING_DONE", iteration=iteration, extra={"review_pass": review_result.get("pass", True)})

        if review_result.get("pass", True):
            review_passed = True
            record_stage("ITERATION_TOTAL", _to_secs(time.perf_counter() - iteration_started_at))
            break
        if request.skip_minor_refine and _is_minor_only_review(review_result):
            review_passed = True
            record_stage("ITERATION_TOTAL", _to_secs(time.perf_counter() - iteration_started_at))
            yield metric_frame(
                "REVIEWING_MINOR_ACCEPTED",
                iteration=iteration,
                extra={"review_pass": False, "minor_only_accepted": True},
            )
            break
        revision_plan = review_result.get("revision_plan", "")
        target_beat_ids = review_result.get("target_beat_ids", [])
        all_issues = review_result.get("issues", [])

        if target_beat_ids and isinstance(target_beat_ids, list) and len(target_beat_ids) > 0:
            valid_beat_ids = [bid for bid in target_beat_ids if bid in beat_chunk_map]
            if not valid_beat_ids:
                print(f"[Refine Warning] Review returned invalid beat_ids: {target_beat_ids}. Valid keys: {list(beat_chunk_map.keys())}. Skipping localized refine.")
            else:
                refining_started_at = time.perf_counter()
                yield f"data: {json.dumps({'event': 'REFINING', 'message': f'正在对 {len(valid_beat_ids)} 个问题片段进行局部精修...', 'iteration': iteration}, ensure_ascii=False)}\n\n"

                for beat_id in valid_beat_ids:
                    original_chunk = beat_chunk_map.get(beat_id, "")
                    if not original_chunk:
                        print(f"[Refine Warning] Beat {beat_id} has no chunk text, skipping.")
                        continue

                    beat_idx = int(beat_id.split("_")[1]) - 1
                    beat_info = beats[beat_idx] if beat_idx < len(beats) else {}
                    beat_summary = beat_info.get("summary", "")

                    issue_descriptions = []
                    for issue in all_issues:
                        issue_beat_ids = issue.get("target_beat_ids", [])
                        if beat_id in issue_beat_ids:
                            issue_descriptions.append(issue.get("description", ""))

                    revision_instruction = f"【全局纠偏】{revision_plan}\n\n【问题定位】" + "; ".join(issue_descriptions) if issue_descriptions else revision_plan

                    r_sys, r_user = build_chunk_refine_prompt(
                        chapter, book, entities, relationships, beat_summary, original_chunk, revision_instruction
                    )

                    debug_history.append({
                        "stage": "CHUNK_REFINE_LOCAL",
                        "iteration": iteration,
                        "beat_id": beat_id,
                        "system_prompt": r_sys,
                        "user_prompt": r_user
                    })

                    refined_chunk = await call_llm_timed(
                        "chunk_refine_local",
                        system_prompt=r_sys,
                        user_prompt=r_user,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                        temperature=0.7,
                        max_tokens=_clamp_int(max(1200, target_words * 3), 1200, 5200),
                    )
                    refined_chunk = _clean_llm_output(refined_chunk)
                    beat_chunk_map[beat_id] = refined_chunk
                    print(f"[Local Refine] Beat {beat_id} refined successfully.")

                record_stage("REFINING", _to_secs(time.perf_counter() - refining_started_at))
                yield metric_frame("REFINING_DONE", iteration=iteration, extra={"refined_beats": valid_beat_ids})

                stitching_started_at = time.perf_counter()
                yield f"data: {json.dumps({'event': 'STITCHING', 'message': '统稿 Agent 正在重组精修后的 chunks...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
                updated_chunks = [beat_chunk_map.get(f"beat_{i+1}", "") for i in range(len(beats))]
                stitch_system_prompt, stitch_user_prompt = build_stitch_prompt(
                    chapter=chapter,
                    beats=beats,
                    chunks=updated_chunks,
                    word_count=word_count,
                )
                yield f"data: {json.dumps({'prompt': {'system_prompt': stitch_system_prompt, 'user_prompt': stitch_user_prompt}}, ensure_ascii=False)}\n\n"
                debug_history.append({
                    "stage": "STITCHING_AFTER_REFINE",
                    "iteration": iteration,
                    "system_prompt": stitch_system_prompt,
                    "user_prompt": stitch_user_prompt
                })
                current_draft = await call_llm_timed(
                    "stitch_after_refine",
                    system_prompt=stitch_system_prompt,
                    user_prompt=stitch_user_prompt,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                    temperature=0.4,
                    max_tokens=10000,
                )
                current_draft = _clean_llm_output(current_draft)
                if not current_draft.strip():
                    current_draft = "\n\n".join(updated_chunks).strip()
                record_stage("STITCHING", _to_secs(time.perf_counter() - stitching_started_at))
                chapter.draft_text = current_draft
                chapter.revision_count = iteration
                await db.commit()
                yield metric_frame("STITCHING_DONE", iteration=iteration)

                skip_drafting_stitching = True

        record_stage("ITERATION_TOTAL", _to_secs(time.perf_counter() - iteration_started_at))

    if current_draft and current_draft.strip():
        if _needs_formatting(current_draft):
            formatting_started_at = time.perf_counter()
            yield f"data: {json.dumps({'event': 'FORMATTING', 'message': '正在进行最终段落排版...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            format_system_prompt, format_user_prompt = build_formatting_prompt(current_draft)
            yield f"data: {json.dumps({'prompt': {'system_prompt': format_system_prompt, 'user_prompt': format_user_prompt}}, ensure_ascii=False)}\n\n"
            debug_history.append({
                "stage": "FORMATTING",
                "iteration": iteration,
                "system_prompt": format_system_prompt,
                "user_prompt": format_user_prompt
            })
            try:
                formatted_text = await call_llm_timed(
                    "formatting",
                    system_prompt=format_system_prompt,
                    user_prompt=format_user_prompt,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                    temperature=0.1,
                    max_tokens=_clamp_int(max(2000, word_count * 3), 2000, 7000),
                )
                formatted_text = _clean_llm_output(formatted_text)
                if formatted_text and len(formatted_text) > len(current_draft) * 0.5:
                    current_draft = formatted_text
                else:
                    print("[Format Warning] Formatted text suspiciously short or empty. Fallback to original.")
            except Exception as e:
                print(f"[Format Error] {e}")
            record_stage("FORMATTING", _to_secs(time.perf_counter() - formatting_started_at))
            yield metric_frame("FORMATTING_DONE", iteration=iteration)
        else:
            record_stage("FORMATTING_SKIPPED", 0.0)
            yield metric_frame("FORMATTING_SKIPPED", iteration=iteration)

    chapter.content_text = current_draft
    await db.commit()
    yield f"data: {json.dumps({'event': 'FINAL_TEXT_STREAM', 'message': '正在输出最终文本...', 'passed': review_passed, 'iterations': iteration}, ensure_ascii=False)}\n\n"

    # 逐字符输出 (模拟打字机效果，同时便于前端逐段接收)
    for char in current_draft:
        yield f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': char}, ensure_ascii=False)}\n\n"

    total_elapsed = _to_secs(time.perf_counter() - run_started_at)
    wall_clock_stage_seconds = {
        key: value
        for key, value in stage_seconds.items()
        if not key.startswith("llm:") and key not in {"BEAT_TOTAL", "ITERATION_TOTAL"}
    }
    aggregate_stage_seconds = {
        key: value
        for key, value in stage_seconds.items()
        if key in {"BEAT_TOTAL", "ITERATION_TOTAL"}
    }
    top_stage_seconds = top_stage_items(wall_clock_stage_seconds, 5)
    done_payload = {
        "event": "DONE",
        "passed": review_passed,
        "iterations": iteration,
        "revision_count": iteration,
        "debug_history": debug_history,
        "metrics": {
            "total_seconds": total_elapsed,
            "fast_mode": effective_fast_mode,
            "top_stage_seconds": top_stage_seconds,
            "aggregate_stage_seconds": top_stage_items(aggregate_stage_seconds, 5),
            "llm": {
                "calls": sum(int(item["calls"]) for item in llm_stage_stats.values()),
                "failures": sum(int(item["failures"]) for item in llm_stage_stats.values()),
                "seconds": round(sum(float(item["seconds"]) for item in llm_stage_stats.values()), 3),
            },
        },
    }
    yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

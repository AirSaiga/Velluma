from uuid import UUID
import json
import logging
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.core.dependencies import get_chapter_repository
from backend.core.exceptions import not_found, generation_error
from backend.repositories import ChapterRepository
from backend.models import Chapter, Book, Character, PlotLedger, PlotLedgerStatus, ChapterMapLocation
from backend.schemas import InspirationRequest, InspirationResponse
from backend.services.chapter_generation import call_llm
from backend.services.prompts.inspiration_prompts import build_inspiration_agent_prompt
from backend.services.logging_utils import ServiceLogger, LOG_PREFIX_WORKFLOW

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)

router = APIRouter(prefix="/api", tags=["inspiration"])


@router.post("/generate_inspiration", response_model=InspirationResponse)
async def generate_inspiration(
    request: InspirationRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """点子启发 API - 为作者提供后续剧情灵感

    轻量级接口，只加载最少断连的上下文：
    1. 核心世界观
    2. 前情提要
    3. 核心角色简介
    4. 开放状态的伏笔

    使用高 Temperature (默认 0.9) 增强发散性，
    强制返回结构化的 JSON 灵感卡片。
    """
    db = chapter_repo.db

    book_result = await db.execute(select(Book).where(Book.id == request.book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise not_found("书籍", str(request.book_id))

    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise not_found("章节", str(request.chapter_id))

    worldview_summary = ""
    if book.worldview_settings:
        settings = book.worldview_settings
        if isinstance(settings, dict):
            genre = settings.get("genre", "")
            timeline = settings.get("timeline", "")
            rules = settings.get("rules", "")
            locations = settings.get("locations", "")
            worldview_summary = f"题材类型：{genre}\n时间线：{timeline}\n世界规则：{rules}\n主要地点：{locations}"
    if book.global_sys_prompt:
        worldview_summary += f"\n全局设定：{book.global_sys_prompt[:500]}"
    if not worldview_summary:
        worldview_summary = "（暂无详细世界观设定）"

    prev_chapters_result = await db.execute(
        select(Chapter)
        .where(
            Chapter.book_id == request.book_id,
            Chapter.chapter_number < chapter.chapter_number
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    prev_chapter = prev_chapters_result.scalar_one_or_none()
    if prev_chapter:
        context_parts = []
        ch_title = f"第{prev_chapter.chapter_number}章"
        if prev_chapter.outline_text:
            context_parts.append(f"{ch_title}大纲：{prev_chapter.outline_text[:300]}")
        if prev_chapter.content_text:
            context_parts.append(f"{ch_title}结尾：{prev_chapter.content_text[-300:]}")
        if prev_chapter.summary:
            context_parts.append(f"{ch_title}摘要：{prev_chapter.summary[:200]}")
        recent_context = "\n".join(context_parts) if context_parts else "（暂无前情提要）"
    else:
        recent_context = "（暂无前情提要）"

    current_chapter_context = ""
    if chapter.outline_text:
        current_chapter_context = f"当前本章已有大纲：{chapter.outline_text[:500]}"
    if chapter.content_text and len(chapter.content_text) > 50:
        if current_chapter_context:
            current_chapter_context += f"\n当前本章正文已写：{chapter.content_text[-300:]}"
        else:
            current_chapter_context = f"当前本章正文已写：{chapter.content_text[-300:]}"

    characters_brief = ""
    if request.active_character_ids:
        char_ids = [char_id for char_id in request.active_character_ids if char_id]
        if char_ids:
            try:
                uuid_char_ids = [UUID(cid) for cid in char_ids]
            except ValueError:
                uuid_char_ids = []
            if uuid_char_ids:
                char_result = await db.execute(
                    select(Character).where(Character.id.in_(uuid_char_ids))
                )
                characters = char_result.scalars().all()
                if characters:
                    char_lines = []
                    for char in characters:
                        brief = char.static_prompt[:100] if char.static_prompt else "暂无设定"
                        char_lines.append(f"- {char.name}: {brief}")
                    characters_brief = "\n".join(char_lines)
    if not characters_brief:
        characters_brief = "（当前场景暂无指定角色）"

    hooks_result = await db.execute(
        select(PlotLedger)
        .where(PlotLedger.book_id == request.book_id)
        .order_by(PlotLedger.created_at.desc())
        .limit(20)
    )
    all_hooks = hooks_result.scalars().all()
    open_hooks = [h for h in all_hooks if h.status == PlotLedgerStatus.OPEN.value]
    recent_hooks = all_hooks[:10]
    hooks_to_show = open_hooks[:10] if len(open_hooks) >= 10 else (open_hooks + recent_hooks[:10 - len(open_hooks)])
    if hooks_to_show:
        hook_lines = []
        for hook in hooks_to_show:
            status_tag = "[未解决]" if hook.status == PlotLedgerStatus.OPEN.value else "[已解决]"
            hook_lines.append(f"- {hook.ledger_key} {status_tag}: {hook.content[:80]}")
        open_hooks_text = "\n".join(hook_lines)
    else:
        open_hooks_text = "（暂无伏笔记录）"

    chapter_locations_result = await db.execute(
        select(ChapterMapLocation)
        .where(ChapterMapLocation.chapter_id == request.chapter_id)
        .options(selectinload(ChapterMapLocation.location))
    )
    chapter_locations = chapter_locations_result.scalars().all()

    location_context = ""
    if chapter_locations:
        location_names = []
        for cl in chapter_locations:
            if cl.location:
                location_names.append(cl.location.name)
        if location_names:
            location_context = f"本章涉及地点：{', '.join(location_names)}"

    prompt_messages = build_inspiration_agent_prompt(
        worldview_summary=worldview_summary,
        recent_context=recent_context,
        characters_brief=characters_brief,
        open_hooks=open_hooks_text,
        location_context=location_context,
        current_chapter_context=current_chapter_context,
        chapter_title=request.chapter_title or chapter.title or "",
        global_taboos=book.core_motifs_taboos if book else None,
        author_intent=request.author_intent,
    )

    max_retries = 3
    last_error = None
    for attempt in range(max_retries):
        try:
            svc_logger.info("Generating inspiration", attempt=attempt + 1, max_retries=max_retries)
            raw_content = await call_llm(
                system_prompt=prompt_messages[0]["content"],
                user_prompt=prompt_messages[1]["content"],
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=request.temperature,
                top_p=0.9,
                response_format={"type": "json_object"},
                max_tokens=2048,
            )

            if not raw_content:
                raise ValueError("LLM 返回空内容")

            data = json.loads(raw_content)

            inspirations_data = []
            if isinstance(data, list):
                inspirations_data = data
            elif isinstance(data, dict):
                inspirations_data = data.get("inspirations", [])
                if not inspirations_data or len(inspirations_data) < 3:
                    inspirations_data = data.get("ideas", []) or data.get("results", []) or []
            else:
                raise ValueError(f"LLM 返回了不支持的 JSON 结构: {type(data)}")

            inspirations_data = [item for item in inspirations_data if isinstance(item, dict)]

            if len(inspirations_data) >= 4:
                inspirations_data = inspirations_data[:4]
            else:
                raise ValueError(f"返回的有效灵感数量不足：{len(inspirations_data)}")

            inspirations = []
            for item in inspirations_data:
                idea_type = item.get("idea_type", "plot_twist")
                if idea_type not in ["plot_twist", "key_conflict", "new_hook", "smooth_narrative"]:
                    idea_type = "plot_twist"
                inspirations.append({
                    "idea_type": idea_type,
                    "title": item.get("title", "未命名点子"),
                    "description": item.get("description", ""),
                    "impact": item.get("impact", ""),
                })

            response = InspirationResponse(inspirations=inspirations)
            return response

        except Exception as e:
            svc_logger.error("Inspiration generation failed", attempt=attempt + 1, max_retries=max_retries, error=str(e))
            last_error = e
            if attempt < max_retries - 1:
                await asyncio.sleep(1 * (attempt + 1))
                continue

    svc_logger.error("Inspiration generation ultimately failed", error=str(last_error))
    raise generation_error("生成灵感失败", last_error)

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from backend.models import Chapter, ChapterEntity, CharacterRelationship, Book, Character, PlotLedger, PlotLedgerStatus

from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.schemas import (
    GenerateChapterRequest,
    GenerateChapterAgenticRequest,
    GenerateChapterAgenticPreviewResponse,
    GenerateChapterAgenticWithBeatsRequest,
    OptimizeChapterRequest,
    FormatTextRequest,
    InspirationRequest,
    InspirationResponse,
)
from backend.services.chapter_generation import (
    build_chapter_prompt,
    generate_stream_response,
    call_llm,
    generate_agentic_chapter_stream,
    generate_agentic_chapter_stream_with_confirmed_beats,
    preview_agentic_beats,
    refine_draft,
)
from backend.services.llm_client import format_text_with_llm
from backend.services.prompts.inspiration_prompts import build_inspiration_agent_prompt
import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])


# =============================================================================
# 文本格式整理
# =============================================================================

@router.post("/format_text")
async def format_text(request: FormatTextRequest):
    """
    智能整理文本格式（分段、标点、空行等）。
    """
    if not request.text.strip():
        return {"formatted_text": ""}
        
    formatted_text = await format_text_with_llm(
        text=request.text,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    return {"formatted_text": formatted_text}


# =============================================================================
# 流式章节生成 - 实时推送生成内容
# =============================================================================

@router.post("/generate_chapter")
async def generate_chapter(
    request: GenerateChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：流式生成章节内容，用于实时展示 AI 写作过程。

    参数来源：
    - request: 请求体，包含 chapter_id（目标章节）、word_count、api_key、base_url、model

    数据流：
    1. 获取章节信息（用于上下文）
    2. 构建 prompt（包含世界观、角色设定、记忆片段等）
    3. 以 SSE（Server-Sent Events）流式返回 AI 生成内容

    副作用：
    - 不写入数据库，仅返回流式文本
    - 章节内容需用户确认后手动保存

    性能考量：
    - 流式响应降低首字节时间（TTFB），用户体验更好
    - 需要前端支持 event-stream 解析

    风险点：
    - API Key 暴露风险：前端传 vs 后端配置
    - 当前设计由前端传入，适合 SaaS 场景；内部部署应考虑后端配置
    """
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    word_count = request.word_count or 2000
    prompt_data = await build_chapter_prompt(request.chapter_id, chapter_repo.db, word_count)
    return StreamingResponse(
        generate_stream_response(
            system_prompt=prompt_data["system_prompt"],
            user_prompt=prompt_data["user_prompt"],
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# =============================================================================
# 章节优化 - 根据用户反馈调整内容
# =============================================================================

@router.post("/optimize_chapter")
async def optimize_chapter(
    request: OptimizeChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：根据用户反馈优化章节内容。

    参数来源：
    - request: 包含 chapter_id, optimization_feedback, api_key 等

    数据流：
    1. 获取章节、书籍、角色、关系上下文
    2. 调用 Refine Agent 进行重写
    3. 返回优化后的内容

    注意：此操作不会直接修改数据库，需要用户确认后保存
    """
    db = chapter_repo.db
    chapter_id = request.chapter_id

    # 1. 获取章节和书籍
    # 使用 selectinload 预加载 book，避免 session 关闭后访问出错
    result = await db.execute(
        select(Chapter).options(selectinload(Chapter.book)).where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    book = chapter.book

    # 2. 获取相关角色 (Entities)
    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()
    
    # 3. 获取角色关系
    character_ids = []
    seen_ids = set()
    for e in entities:
        if e.character and e.character.id not in seen_ids:
            seen_ids.add(e.character.id)
            character_ids.append(e.character.id)
            
    relationships = []
    if character_ids:
        relationships_result = await db.execute(
            select(CharacterRelationship)
            .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
            .where(
                CharacterRelationship.source_char_id.in_(character_ids),
                CharacterRelationship.target_char_id.in_(character_ids),
            )
        )
        relationships = relationships_result.scalars().all()

    # 4. 获取当前草稿内容
    # 优先使用 content_text (已保存内容)，其次 draft_text (生成中内容)
    current_draft = chapter.content_text or chapter.draft_text or ""
    if not current_draft:
        raise HTTPException(status_code=400, detail="当前章节没有内容可优化")
    
    # 5. 调用 Refine Agent
    # 注意：refine_draft 需要的 entities 是 ChapterEntity 对象列表
    # relationships 是 CharacterRelationship 对象列表
    refined_text = await refine_draft(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        current_draft=current_draft,
        revision_plan=request.optimization_feedback,
        word_count=request.word_count,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    
    return {"optimized_content": refined_text}


# =============================================================================
# 同步章节生成 - 一次性返回完整内容
# =============================================================================

@router.post("/generate_chapter_sync")
async def generate_chapter_sync(
    request: GenerateChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：同步生成章节内容，适用于不需要实时预览的场景。

    参数来源：
    - 与流式接口相同

    数据流：
    1-2. 同流式接口
    3. 等待完整响应后一次性返回

    权衡点 vs 流式接口：
    - 优点：实现简单，前端处理容易
    - 缺点：长文本生成时等待时间长（可能超时）
    - 适用场景：短章节、API 超时限制宽松、离线批处理

    性能考量：
    - 默认 temperature=0.7，兼顾创造性与稳定性
    - 返回完整 prompt 便于调试和追溯
    """
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    word_count = request.word_count or 2000
    prompt_data = await build_chapter_prompt(request.chapter_id, chapter_repo.db, word_count)
    content = await call_llm(
        system_prompt=prompt_data["system_prompt"],
        user_prompt=prompt_data["user_prompt"],
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
        temperature=0.7,
    )
    return {"content": content, "prompt": {"system_prompt": prompt_data["system_prompt"], "user_prompt": prompt_data["user_prompt"]}}


# =============================================================================
# Agentic 章节生成 - 多轮迭代的智能写作
# =============================================================================

@router.post("/generate_chapter_agentic")
async def generate_chapter_agentic(
    request: GenerateChapterAgenticRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：使用 Agent 模式生成章节，支持多轮反思和修订。

    参数来源：
    - request: 包含章节 ID 和 Agent 配置

    核心差异 vs 基础生成：
    - 基础生成：单次 LLM 调用，prompt → 内容
    - Agentic 生成：多轮循环，评估 → 反思 → 重写 → 再评估

    数据流：
    - build_chapter_prompt 构建初始 prompt
    - generate_agentic_chapter_stream 内部处理多轮迭代
    - 流式返回每轮输出和最终结果

    副作用：
    - 多次 LLM 调用，成本更高
    - 生成时间更长，但质量通常更好

    适用场景：
    - 重要章节需要高质量输出
    - 需要 AI 自我纠错能力
    - 复杂世界观下的内容一致性要求高
    """
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return StreamingResponse(
        generate_agentic_chapter_stream(request, chapter_repo.db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/generate_chapter_agentic_preview_beats", response_model=GenerateChapterAgenticPreviewResponse)
async def generate_chapter_agentic_preview_beats(
    request: GenerateChapterAgenticRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    beats = await preview_agentic_beats(request, chapter_repo.db)
    return {"beats": beats}


@router.post("/generate_chapter_agentic_with_beats")
async def generate_chapter_agentic_with_beats(
    request: GenerateChapterAgenticWithBeatsRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return StreamingResponse(
        generate_agentic_chapter_stream_with_confirmed_beats(request, chapter_repo.db, request.beats),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


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
        raise HTTPException(status_code=404, detail="书籍不存在")

    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

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

    recent_context = request.current_context_snippet
    if not recent_context.strip():
        if chapter.outline_text:
            recent_context = f"本章大纲：{chapter.outline_text}"
        elif chapter.summary:
            recent_context = f"本章摘要：{chapter.summary}"
        else:
            recent_context = "（暂无前情提要）"

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
        .where(
            PlotLedger.book_id == request.book_id,
            PlotLedger.status == PlotLedgerStatus.OPEN.value,
        )
        .order_by(PlotLedger.created_at.desc())
        .limit(10)
    )
    open_hooks = hooks_result.scalars().all()
    if open_hooks:
        hook_lines = []
        for hook in open_hooks:
            hook_lines.append(f"- {hook.ledger_key}: {hook.content[:100]}")
        open_hooks_text = "\n".join(hook_lines)
    else:
        open_hooks_text = "（暂无未解决的伏笔）"

    prompt_messages = build_inspiration_agent_prompt(
        worldview_summary=worldview_summary,
        recent_context=recent_context,
        characters_brief=characters_brief,
        open_hooks=open_hooks_text,
    )

    max_retries = 3
    last_error = None
    for attempt in range(max_retries):
        try:
            logger.info(f"开始生成灵感，尝试 {attempt + 1}/{max_retries}")
            raw_content = await call_llm(
                system_prompt=prompt_messages[0]["content"],
                user_prompt=prompt_messages[1]["content"],
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=request.temperature,
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
                # 既不是 list 也不是 dict，无法处理
                raise ValueError(f"LLM 返回了不支持的 JSON 结构: {type(data)}")

            # 过滤非字典项
            inspirations_data = [item for item in inspirations_data if isinstance(item, dict)]

            if len(inspirations_data) >= 3:
                inspirations_data = inspirations_data[:3]
            else:
                raise ValueError(f"返回的有效灵感数量不足：{len(inspirations_data)}")

            inspirations = []
            for item in inspirations_data:
                idea_type = item.get("idea_type", "plot_twist")
                if idea_type not in ["plot_twist", "key_conflict", "new_hook"]:
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
            logger.error(f"生成灵感失败 (尝试 {attempt + 1}/{max_retries}): {e}", exc_info=True)
            last_error = e
            if attempt < max_retries - 1:
                import asyncio
                await asyncio.sleep(1 * (attempt + 1))
                continue

    logger.error(f"生成灵感最终失败: {last_error}")
    raise HTTPException(status_code=500, detail=f"生成灵感失败: {last_error}")

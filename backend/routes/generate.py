"""
基础生成路由模块（向后兼容）。

职责：提供各类 AI 生成 API，用于智能写作辅助。

业务场景：
- 文本格式整理（分段、标点规范化）
- 流式章节生成（实时展示生成过程）
- 章节优化（基于用户反馈重写）
- 选中文本优化（局部精修）
- 同步章节生成（非流式）
- Agentic 章节生成（多轮迭代）
- 灵感生成（剧情点子启发）

设计说明：
- 此文件为向后兼容保留，新功能已拆分到独立路由文件：
  - text_formatting.py: 文本格式
  - chapter_generation.py: 章节生成
  - chapter_optimization.py: 章节优化
  - inspiration.py: 灵感生成

数据来源：
- 上下文数据来自章节、书籍、角色、关系、伏笔等数据库实体
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.models import Chapter, ChapterEntity, CharacterRelationship, Book

from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.schemas import (
    GenerateChapterRequest,
    GenerateChapterAgenticRequest,
    GenerateChapterAgenticPreviewResponse,
    OptimizeChapterRequest,
    OptimizeSelectionRequest,
    FormatTextRequest,
    InspirationRequest,
    InspirationResponse,
)
from backend.services.chapter_generation import (
    build_chapter_prompt,
    generate_stream_response,
    call_llm,
    preview_agentic_beats,
    refine_draft,
)
from backend.services.llm_client import format_text_with_llm, optimize_selection_with_llm
from backend.services.inspiration_service import (
    load_inspiration_context,
    generate_inspirations,
)
from backend.services.logging_utils import ServiceLogger, LOG_PREFIX_WORKFLOW
import json
import logging

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)

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
    from backend.services.context_loader import (
        load_chapter,
        load_book,
        load_chapter_entities,
        load_character_relationships,
    )
    
    db = chapter_repo.db
    chapter_id = request.chapter_id

    # 1. 获取章节和书籍（使用 context_loader 服务）
    chapter = await load_chapter(db, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    book = await load_book(db, chapter.book_id) if chapter.book_id else None

    # 2. 获取相关角色和关系（使用 context_loader 服务）
    entities = await load_chapter_entities(db, chapter_id)
    relationships = await load_character_relationships(db, entities)

    # 3. 获取当前草稿内容
    # 优先使用 content_text (已保存内容)，其次 draft_text (生成中内容)
    current_draft = chapter.content_text or chapter.draft_text or ""
    if not current_draft:
        raise HTTPException(status_code=400, detail="当前章节没有内容可优化")
    
    # 4. 调用 Refine Agent
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
# 选中文本优化
# =============================================================================

@router.post("/optimize_selection")
async def optimize_selection(
    request: OptimizeSelectionRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """
    对用户选中的文本进行优化。
    """
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
        
    outline = chapter.outline_text or "（暂无大纲）"
    
    optimized_text = await optimize_selection_with_llm(
        selected_text=request.selected_text,
        context_before=request.context_before,
        context_after=request.context_after,
        outline=outline,
        user_instruction=request.user_instruction,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    
    return {"optimized_text": optimized_text}


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


@router.post("/generate_chapter_agentic_preview_beats", response_model=GenerateChapterAgenticPreviewResponse)
async def generate_chapter_agentic_preview_beats(
    request: GenerateChapterAgenticRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return await preview_agentic_beats(request, chapter_repo.db)


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
    
    # 使用灵感服务加载上下文
    context = await load_inspiration_context(
        db=db,
        book_id=request.book_id,
        chapter_id=request.chapter_id,
        active_character_ids=request.active_character_ids,
    )
    
    if not context:
        raise HTTPException(status_code=404, detail="书籍或章节不存在")
    
    # 加载章节以获取标题
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    book_result = await db.execute(select(Book).where(Book.id == request.book_id))
    book = book_result.scalar_one_or_none()
    
    try:
        # 使用灵感服务生成灵感
        inspiration_items = await generate_inspirations(
            context=context,
            chapter_title=request.chapter_title or (chapter.title if chapter else ""),
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            temperature=request.temperature,
            global_taboos=book.core_motifs_taboos if book else None,
            author_intent=request.author_intent,
        )
        
        # 转换为响应格式
        inspirations = [item.to_dict() for item in inspiration_items]
        return InspirationResponse(inspirations=inspirations)
        
    except ValueError as e:
        svc_logger.error("Inspiration generation failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"生成灵感失败: {e}")

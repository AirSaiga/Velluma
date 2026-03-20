"""
章节发布流程管理路由模块。

职责：处理章节发布的相关流程，包括状态管理和发布操作。

业务场景：
- 发布章节（更新状态为已发布）
- 撤销发布（恢复为草稿状态）
- 批量发布章节
- 获取章节发布状态

设计说明：
- 章节状态：草稿(draft) → 已发布(published)
- 发布操作会触发角色动态状态更新
- 批量发布支持事务，确保原子性

数据模型：
- Chapter: 包含 status 字段
"""

import asyncio
import logging
from typing import Optional
from uuid import UUID

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_chapter_repository, get_character_repository, get_memory_repository
from backend.repositories import ChapterRepository, CharacterRepository, MemoryRepository
from backend.schemas import ChapterPublishRequest, ChapterPublishResponse, CharacterStateChange
from backend.services.chapter_generation import update_character_dynamic_state
from backend.services.llm_client import generate_summary, get_embedding
from backend.models import MemoryChunk


router = APIRouter(prefix="/api", tags=["chapter-publishing"])


@router.patch("/chapters/{chapter_id}/publish", response_model=ChapterPublishResponse)
async def publish_chapter(
    chapter_id: UUID,
    request: Optional[ChapterPublishRequest] = None,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
    memory_repo: MemoryRepository = Depends(get_memory_repository),
):
    """业务目的：将章节从草稿状态发布为正式内容，并触发角色动态状态更新和自动摘要生成。

    参数来源：
    - chapter_id: 路径参数
    - request: 可选请求体，包含 api_key 等 AI 生成参数

    核心副作用（三步执行）：
    1. 状态变更：chapter.status → "published"
    2. 自动摘要：生成摘要并存入 memory_chunks 表
    3. 角色演进（可选）：若提供 api_key，调用 AI 更新角色 dynamic_state

    数据流详解：
    - 自动摘要：基于 content_text 生成 summary，并计算 embedding 存入 MemoryChunk
    - 获取章节关联的角色列表
    - 对每个角色调用 update_character_dynamic_state
    - 收集状态变更记录用于返回
    """
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.status == "published":
        raise HTTPException(status_code=400, detail="章节已经是发布状态")
    
    chapter.status = "published"
    
    if chapter.draft_text:
        chapter.content_text = chapter.draft_text

    text_to_summarize = chapter.content_text or chapter.draft_text
    logger.debug(f"[Publish] Summarizing text length: {len(text_to_summarize) if text_to_summarize else 0}")
    
    if request and request.api_key and text_to_summarize:
        try:
            logger.debug("[Publish] Generating summary...")
            summary = await asyncio.wait_for(
                generate_summary(
                    text_to_summarize,
                    request.api_key,
                    request.base_url,
                    request.model,
                ),
                timeout=180,
            )
            logger.debug(f"[Publish] Summary generated: {bool(summary)}")
            if summary:
                chapter.summary = summary
                summary_embedding = await asyncio.wait_for(
                    get_embedding(summary, request.api_key, request.base_url),
                    timeout=120,
                )
                logger.debug(f"[Publish] Embedding generated: {bool(summary_embedding)}")
                if summary_embedding:
                    new_memory = MemoryChunk(
                        book_id=chapter.book_id,
                        chapter_id=chapter.id,
                        chunk_text=f"【第{chapter.chapter_number}章摘要】{summary}",
                        embedding=summary_embedding
                    )
                    chapter_repo.db.add(new_memory)
        except asyncio.TimeoutError:
            logger.warning("[Publish] Auto-Summary timed out")
        except Exception as e:
            logger.error(f"[Publish] Auto-Summary error: {e}")
            import traceback
            traceback.print_exc()

    character_updates = []
    if request and request.api_key:
        character_list = []
        seen_char_ids = set()

        entities = await chapter_repo.list_entities_with_character(chapter_id)
        if entities:
            for entity in entities:
                if entity.character and entity.character.id not in seen_char_ids:
                    character_list.append(entity.character)
                    seen_char_ids.add(entity.character.id)
        
        chapter_char_ids = getattr(chapter, "character_ids", None)
        if chapter_char_ids:
            missing_ids = [cid for cid in chapter_char_ids if cid not in seen_char_ids]
            if missing_ids:
                chars = await character_repo.list_by_ids(missing_ids)
                for char in chars:
                    if char.id not in seen_char_ids:
                        character_list.append(char)
                        seen_char_ids.add(char.id)

        for character in character_list:
            if character:
                try:
                    old_state = character.dynamic_state or "暂无动态状态"
                    await asyncio.wait_for(
                        update_character_dynamic_state(
                            character=character,
                            chapter=chapter,
                            db=chapter_repo.db,
                            api_key=request.api_key,
                            base_url=request.base_url,
                            model=request.model,
                            proxy_enabled=request.proxy_enabled,
                            proxy_url=request.proxy_url,
                        ),
                        timeout=180,
                    )
                    new_state = character.dynamic_state or "暂无动态状态"
                    character_updates.append(
                        CharacterStateChange(
                            character_id=character.id,
                            character_name=character.name,
                            old_state=old_state,
                            new_state=new_state,
                        )
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[Publish] Character {character.name} update timeout")
                    character_updates.append(
                        CharacterStateChange(
                            character_id=character.id,
                            character_name=character.name,
                            old_state=character.dynamic_state or "暂无动态状态",
                            new_state="更新失败: 请求超时",
                        )
                    )
                except Exception as e:
                    logger.error(f"[Publish] Character {character.name} update error: {e}")
                    character_updates.append(
                        CharacterStateChange(
                            character_id=character.id,
                            character_name=character.name,
                            old_state=character.dynamic_state or "暂无动态状态",
                            new_state=f"更新失败: {str(e)}",
                        )
                    )
    await chapter_repo.commit()
    await chapter_repo.refresh(chapter)
    return ChapterPublishResponse(
        chapter_id=chapter.id,
        status=chapter.status,
        summary=chapter.summary,
        character_updates=character_updates
    )

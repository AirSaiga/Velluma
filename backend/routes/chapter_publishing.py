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

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_chapter_repository, get_character_repository, get_memory_repository
from backend.core.exceptions import not_found, bad_request
from backend.repositories import ChapterRepository, CharacterRepository, MemoryRepository
from backend.schemas import ChapterPublishRequest, ChapterPublishResponse, CharacterStateChange
from backend.services.logging_utils import ServiceLogger, LOG_PREFIX_WORKFLOW
from backend.services.world_state_service import (
    extract_world_state_snapshot,
    generate_chapter_summary,
    generate_summary_embedding,
    update_character_states,
)
from backend.services.workflows.snapshot_extractor import extract_world_terminal_state
from backend.world_state_schemas import WorldTerminalState
from backend.models import MemoryChunk

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)


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
        raise not_found("章节", str(chapter_id))
    if chapter.status == "published":
        raise bad_request("章节已经是发布状态")
    
    chapter.status = "published"
    
    if chapter.draft_text:
        chapter.content_text = chapter.draft_text

    text_to_summarize = chapter.content_text or chapter.draft_text
    svc_logger.debug("Summarizing text", length=len(text_to_summarize) if text_to_summarize else 0)
    
    # 生成摘要和 embedding
    if request and request.api_key and text_to_summarize:
        summary = await generate_chapter_summary(
            text=text_to_summarize,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        )
        
        if summary:
            chapter.summary = summary
            summary_embedding = await generate_summary_embedding(
                summary=summary,
                api_key=request.api_key,
                base_url=request.base_url,
            )
            
            if summary_embedding:
                new_memory = MemoryChunk(
                    book_id=chapter.book_id,
                    chapter_id=chapter.id,
                    chunk_text=f"【第{chapter.chapter_number}章摘要】{summary}",
                    embedding=summary_embedding
                )
                chapter_repo.db.add(new_memory)

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

        # 使用服务批量更新角色状态
        update_results = await update_character_states(
            character_list=character_list,
            chapter=chapter,
            db=chapter_repo.db,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            proxy_enabled=request.proxy_enabled,
            proxy_url=request.proxy_url,
        )
        
        # 转换结果为 schema 格式
        for result in update_results:
            character_updates.append(
                CharacterStateChange(
                    character_id=result.character_id,
                    character_name=result.character_name,
                    old_state=result.old_state,
                    new_state=result.new_state,
                )
            )

        # ========================================================================
        # V3.6: 世界终端状态提取 (WorldTerminalState)
        # ========================================================================
        if text_to_summarize and request and request.api_key:
            try:
                # 获取上一章的状态作为参考
                prev_chapter = await chapter_repo.get_previous_chapter(chapter)
                previous_state = None
                if prev_chapter and prev_chapter.world_snapshot:
                    previous_state = WorldTerminalState.from_chapter_snapshot(
                        prev_chapter.world_snapshot
                    )

                # 使用 V3.6 SnapshotExtractorAgent
                world_state = await asyncio.wait_for(
                    extract_world_terminal_state(
                        chapter_content=text_to_summarize,
                        character_list=character_list,
                        reasoning_model=request.model,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        chapter_id=chapter.id,
                        book_id=chapter.book_id,
                        previous_state=previous_state,
                    ),
                    timeout=150,
                )
                
                if world_state:
                    chapter.world_snapshot = world_state.model_dump()
                    svc_logger.info(
                        "WorldTerminalState saved",
                        chapter_id=str(chapter_id),
                        character_count=len(world_state.characters),
                        location=world_state.scene.location_summary[:30],
                    )

                    # ========================================================================
                    # V3.6: 更新角色此刻状态 (current_state)
                    # ========================================================================
                    for character in character_list:
                        if character and str(character.id) in world_state.characters:
                            char_state = world_state.characters[str(character.id)]
                            if char_state.emotional_state:
                                character.current_state = char_state.emotional_state
                                svc_logger.debug("Updated character current_state", character=character.name)

                    # ========================================================================
                    # V3.6: 更新场景此刻状态
                    # ========================================================================
                    if world_state.scene.atmosphere:
                        chapter_locations = await chapter_repo.list_locations_with_details(chapter_id)
                        for ch_loc in chapter_locations:
                            if ch_loc.location:
                                ch_loc.location.current_state = world_state.scene.atmosphere
                                svc_logger.debug("Updated location current_state", location=ch_loc.location.name)
                
                else:
                    svc_logger.warning("WorldTerminalState extraction returned None")

            except asyncio.TimeoutError:
                svc_logger.warning("WorldTerminalState extraction timed out")
            except Exception as e:
                svc_logger.error("WorldTerminalState extraction error", error=str(e))

    await chapter_repo.commit()
    await chapter_repo.refresh(chapter)

    return ChapterPublishResponse(
        chapter_id=chapter.id,
        status=chapter.status,
        summary=chapter.summary,
        character_updates=character_updates,
        world_snapshot=chapter.world_snapshot if chapter.world_snapshot else None,
    )

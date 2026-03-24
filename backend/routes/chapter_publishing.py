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
from backend.services.llm_client import generate_summary, get_embedding, call_llm
from backend.services.prompts.world_state_prompts import (
    build_world_state_extraction_prompt,
    parse_world_state_snapshot,
)
from backend.services.prompt_logger import create_logger
from backend.services.workflows.snapshot_extractor import (
    SnapshotExtractorAgent,
    extract_world_terminal_state,
)
from backend.world_state_schemas import WorldTerminalState
from backend.models import MemoryChunk


router = APIRouter(prefix="/api", tags=["chapter-publishing"])


async def extract_world_state_snapshot(
    chapter_content: str,
    character_list: list,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
    previous_snapshot: Optional[dict] = None,
    prompt_logger=None,
) -> Optional[dict]:
    """提取章节末尾的世界状态快照。

    在章节发布阶段调用，基于正文内容提取物理状态约束。

    Args:
        chapter_content: 章节全文内容
        character_list: 角色列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 使用的模型
        previous_snapshot: 上一章的状态快照（可选）
        prompt_logger: PromptLogger 实例（可选，用于记录 prompt）

    Returns:
        Optional[dict]: 世界状态快照，失败返回 None
    """
    try:
        # 构建角色信息列表
        char_info_list = []
        for char in character_list:
            if char:
                char_info = {
                    "id": str(char.id),
                    "name": char.name,
                    "static_prompt": char.static_prompt or "",
                    "dynamic_state": char.dynamic_state or "",
                }
                char_info_list.append(char_info)

        # 构建提示词
        system_prompt, user_prompt = build_world_state_extraction_prompt(
            chapter_content=chapter_content,
            character_list=char_info_list,
            previous_snapshot=previous_snapshot,
        )

        # 记录 prompt 到日志
        if prompt_logger:
            prompt_logger.start_stage("WORLD_STATE_EXTRACTION", iteration=1)
            prompt_logger.log_inputs(
                chapter_content_length=len(chapter_content),
                character_count=len(character_list),
                has_previous_snapshot=bool(previous_snapshot)
            )
            prompt_logger.log_prompts(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=0.2,
                max_tokens=2000,
                prompt_label="WORLD_STATE_EXTRACTOR"
            )

        logger.debug("[WorldState] Extracting snapshot...")
        response = await asyncio.wait_for(
            call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                max_tokens=2000,
            ),
            timeout=120,
        )

        # 解析结果
        snapshot = parse_world_state_snapshot(response)

        # 记录输出到日志
        if prompt_logger:
            if snapshot:
                prompt_logger.log_outputs(
                    snapshot_keys=list(snapshot.keys()),
                    character_snapshots_count=len(snapshot.get("character_snapshots", {})),
                    scene_state=snapshot.get("scene_state", {})
                )
                prompt_logger.end_stage(success=True)
            else:
                prompt_logger.log_outputs(raw_response=response[:500] if response else "Empty")
                prompt_logger.end_stage(success=False)

        if snapshot:
            logger.info(f"[WorldState] Snapshot extracted successfully")
            return snapshot
        else:
            logger.warning("[WorldState] Failed to parse snapshot")
            return None

    except asyncio.TimeoutError:
        if prompt_logger:
            prompt_logger.log_outputs(error="Timeout")
            prompt_logger.end_stage(success=False)
        logger.warning("[WorldState] Extraction timed out")
        return None
    except Exception as e:
        if prompt_logger:
            prompt_logger.log_outputs(error=str(e))
            prompt_logger.end_stage(success=False)
        logger.error(f"[WorldState] Extraction error: {e}")
        return None


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
                    logger.info(
                        f"[Publish] V3.6 WorldTerminalState saved for chapter {chapter_id}: "
                        f"{len(world_state.characters)} characters, "
                        f"location: {world_state.scene.location_summary[:30]}..."
                    )

                    # ========================================================================
                    # V3.6: 更新角色此刻状态 (current_state)
                    # ========================================================================
                    for character in character_list:
                        if character and str(character.id) in world_state.characters:
                            char_state = world_state.characters[str(character.id)]
                            if char_state.emotional_state:
                                character.current_state = char_state.emotional_state
                                logger.debug(f"[Publish] Updated current_state for character {character.name}")

                    # ========================================================================
                    # V3.6: 更新场景此刻状态
                    # ========================================================================
                    if world_state.scene.atmosphere:
                        chapter_locations = await chapter_repo.list_locations_with_details(chapter_id)
                        for ch_loc in chapter_locations:
                            if ch_loc.location:
                                ch_loc.location.current_state = world_state.scene.atmosphere
                                logger.debug(f"[Publish] Updated current_state for location {ch_loc.location.name}")
                
                else:
                    logger.warning("[Publish] V3.6 WorldTerminalState extraction returned None")

            except asyncio.TimeoutError:
                logger.warning("[Publish] V3.6 WorldTerminalState extraction timed out")
            except Exception as e:
                logger.error(f"[Publish] V3.6 WorldTerminalState extraction error: {e}")

    await chapter_repo.commit()
    await chapter_repo.refresh(chapter)

    return ChapterPublishResponse(
        chapter_id=chapter.id,
        status=chapter.status,
        summary=chapter.summary,
        character_updates=character_updates,
        world_snapshot=chapter.world_snapshot if chapter.world_snapshot else None,
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
# [旧表冻结声明 2026-08-19] 本模块仍读 characters/assets 等旧表（roadmap P2.4 显式冻结）：
# 世界页（world_*）是唯一编辑源；此处旧表读取冻结不动，下次实质改造时换源 world。
# 新代码勿再新增旧表依赖。

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
import os
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

# 简单的文件日志函数，用于调试
def _log_to_file(message: str):
    """将调试信息写入日志文件"""
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, "character_extraction_debug.log")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass  # 如果日志写入失败，不要影响主流程

from backend.core.dependencies import (
    get_chapter_repository,
    get_character_repository,
    get_memory_repository,
    get_relationship_repository,
    get_book_repository,
    get_plot_ledger_repository,
)
from backend.core.exceptions import not_found, bad_request
from backend.repositories import ChapterRepository, CharacterRepository, MemoryRepository, RelationshipRepository, BookRepository, PlotLedgerRepository, ChapterCardRepository
from backend.repositories.asset_repository import ChapterAssetRepository
from backend.schemas import (
    ChapterPublishRequest,
    ChapterPublishResponse,
    CharacterStateChange,
    CharacterExtractionSummary,
)
from pydantic import BaseModel, Field
from typing import List, Dict, Any
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW
from backend.services.generation.publish import (
    generate_chapter_summary,
    generate_summary_embedding,
    update_character_states,
)
# CP3.3 状态回写强化（蓝图 §4.10 + decisions §3.5）
from backend.services.generation.publish_v2 import (
    update_character_states_incremental,
    activate_plot_ledgers,
    update_rolling_summary,
)
from backend.services.generation.character_extraction import (
    execute_character_extraction_workflow,
    CharacterExtractionResult,
)
from backend.services.world.state_service import (
    extract_world_state_snapshot,
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
    relationship_repo: RelationshipRepository = Depends(get_relationship_repository),
    book_repo: BookRepository = Depends(get_book_repository),
    plot_ledger_repo: PlotLedgerRepository = Depends(get_plot_ledger_repository),
):
    """业务目的：将章节从草稿状态发布为正式内容，并触发角色动态状态更新和自动摘要生成。

    参数来源：
    - chapter_id: 路径参数
    - request: 可选请求体（V4.1: 模型配置已从 model_config.json 读取）

    核心副作用（三步执行）：
    1. 状态变更：chapter.status → "published"
    2. 自动摘要：生成摘要并存入 memory_chunks 表
    3. 角色演进：调用 AI 更新角色 dynamic_state（配置从 model_config.json 读取）

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
        # 章节已经是发布状态，直接返回当前状态，以修复前端状态不同步的问题
        return ChapterPublishResponse(
            chapter_id=chapter.id,
            status=chapter.status,
            summary=chapter.summary,
            character_updates=[],
            world_snapshot=chapter.world_snapshot if getattr(chapter, "world_snapshot", None) else None,
        )
    
    chapter.status = "published"
    
    if chapter.draft_text:
        chapter.content_text = chapter.draft_text

    text_to_summarize = chapter.content_text or chapter.draft_text
    svc_logger.debug("Summarizing text", length=len(text_to_summarize) if text_to_summarize else 0)
    
    # 生成摘要和 embedding
    if text_to_summarize:
        summary = await generate_chapter_summary(
            text=text_to_summarize,
        )
        
        if summary:
            chapter.summary = summary
            # 摘要块照写（词法默认记忆流的最佳素材）；embedding 可空——
            # 未配置时不再整块跳过（M4 记忆流双路由）
            summary_embedding = await generate_summary_embedding(
                summary=summary,
            )
            new_memory = MemoryChunk(
                book_id=chapter.book_id,
                chapter_id=chapter.id,
                chunk_text=f"【第{chapter.chapter_number}章摘要】{summary}",
                embedding=summary_embedding if summary_embedding else None
            )
            session = chapter_repo.get_session()
            session.add(new_memory)
            await session.commit()

    character_updates = []
    character_extraction_result = None

    # ========================================================================
    # V4.0: 智能人物提取与关系推断
    # ========================================================================
    text_to_extract = chapter.content_text or chapter.draft_text or ""
    _log_to_file(f"[DEBUG] Starting character extraction for chapter {chapter_id}, content length: {len(text_to_extract)}")
    if text_to_extract:
        try:
            extraction_result = await asyncio.wait_for(
                execute_character_extraction_workflow(
                    chapter_content=text_to_extract,
                    chapter_id=chapter.id,
                    book_id=chapter.book_id,
                    character_repo=character_repo,
                    relationship_repo=relationship_repo,
                    chapter_repo=chapter_repo,
                    timeout=180,
                ),
                timeout=200,
            )
            character_extraction_result = extraction_result
            _log_to_file(f"[DEBUG] Character extraction completed: {len(extraction_result.extracted_characters)} total, {len(extraction_result.new_characters)} new")
            svc_logger.info(
                f"Character extraction completed for chapter {chapter_id}: "
                f"{len(extraction_result.extracted_characters)} total, "
                f"{len(extraction_result.new_characters)} new, "
                f"{len(extraction_result.existing_characters)} existing"
            )
        except asyncio.TimeoutError:
            _log_to_file("[DEBUG] Character extraction timed out")
            svc_logger.warning(f"Character extraction timed out for chapter {chapter_id}")
        except Exception as e:
            _log_to_file(f"[DEBUG] Character extraction error: {e}")
            svc_logger.error(f"Character extraction error for chapter {chapter_id}: {e}", exc_info=True)

    # ========================================================================
    # 原有角色状态更新流程
    # ========================================================================
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
    # CP3.3 改造（蓝图 §4.10 第 3 步，修 P0-5）：
    # 改用增量版 update_character_states_incremental：
    # - 不再逐角色重发全文（只发涉及该角色的片段）
    # - 输出含 evidence_quote（SCORE 原则），无证据的状态变更不入库
    cp33_update_results = await update_character_states_incremental(
        character_list=character_list,
        chapter=chapter,
        character_repository=character_repo,
        chapter_text=text_to_summarize,
    )

    # 转换结果为 schema 格式（保持 ChapterStateChange 契约不变）
    for result in cp33_update_results:
        character_updates.append(
            CharacterStateChange(
                character_id=result.character_id,
                character_name=result.character_name,
                old_state=result.old_state,
                new_state=result.new_state,
            )
        )

    # ========================================================================
    # V4.0: 世界终端状态提取 (WorldTerminalState)
    # ========================================================================
    if text_to_summarize:
        try:
            # 获取上一章的状态作为参考
            prev_chapter = await chapter_repo.get_previous_chapter(chapter)
            previous_state = None
            if prev_chapter and prev_chapter.world_snapshot:
                previous_state = WorldTerminalState.from_chapter_snapshot(
                    prev_chapter.world_snapshot
                )

            # 获取关联资产
            chapter_assets = await ChapterAssetRepository(chapter_repo.get_session()).list_by_chapter(chapter_id)
            assets = [ca.asset for ca in chapter_assets if ca.asset]

            # 使用 V4.0 SnapshotExtractorAgent
            world_state = await asyncio.wait_for(
                extract_world_terminal_state(
                    chapter_content=text_to_summarize,
                    character_list=character_list,
                    chapter_id=chapter.id,
                    book_id=chapter.book_id,
                    previous_state=previous_state,
                    assets=assets,
                ),
                timeout=150,
            )
                
            if world_state:
                # 使用 mode='json' 确保 datetime 等复杂类型被正确序列化为字符串
                chapter.world_snapshot = world_state.model_dump(mode='json')
                svc_logger.info(
                    "WorldTerminalState saved",
                    chapter_id=str(chapter_id),
                    character_count=len(world_state.characters),
                    location=world_state.scene.location_summary[:30],
                )

                # ========================================================================
                # V4.0: 更新角色此刻状态 (current_state)
                # ========================================================================
                for character in character_list:
                    if character and str(character.id) in world_state.characters:
                        char_state = world_state.characters[str(character.id)]
                        if char_state.emotional_state:
                            character.current_state = char_state.emotional_state
                            svc_logger.debug("Updated character current_state", character=character.name)

                # ========================================================================
                # V4.0: 更新场景此刻状态
                # ========================================================================
                if world_state.scene.atmosphere:
                    chapter_locations = await chapter_repo.list_locations_with_details(chapter_id)
                    for ch_loc in chapter_locations:
                        if ch_loc.location:
                            ch_loc.location.current_state = world_state.scene.atmosphere
                            svc_logger.debug("Updated location current_state", location=ch_loc.location.name)
                                
                # ========================================================================
                # V4.0: 更新资产此刻状态
                # ========================================================================
                if world_state.assets:
                    chapter_assets = await ChapterAssetRepository(chapter_repo.get_session()).list_by_chapter(chapter_id)
                    asset_map = {str(ca.asset.id): ca.asset for ca in chapter_assets if ca.asset}
                    for asset_state in world_state.assets:
                        asset_obj = asset_map.get(asset_state.asset_id)
                        if asset_obj:
                            asset_obj.current_state = asset_state.current_state
                            svc_logger.debug("Updated asset current_state", asset=asset_obj.name)
                
            else:
                svc_logger.warning("WorldTerminalState extraction returned None")

        except asyncio.TimeoutError:
            svc_logger.warning("WorldTerminalState extraction timed out")
        except Exception as e:
            svc_logger.error("WorldTerminalState extraction error", error=str(e))

    # ========================================================================
    # CP3.3 PlotLedger 激活（decisions §3.5）
    # ========================================================================
    # 1 次 light LLM：输入 chapter_card.foreshadow_ops + 章节文本裁剪版
    # 输出每个 op 的 status（executed/skipped/modified）+ evidence_quote
    # 无 evidence 的 op 不更新 PlotLedger（SCORE 原则）
    try:
        from backend.models import ChapterCard
        session = chapter_repo.get_session()
        # 查本章的 chapter_card
        from sqlalchemy import select
        card_result = await session.execute(
            select(ChapterCard).where(ChapterCard.chapter_id == chapter.id).limit(1)
        )
        chapter_card = card_result.scalars().first()
        foreshadow_ops = []
        if chapter_card and chapter_card.foreshadow_ops:
            foreshadow_ops = chapter_card.foreshadow_ops

        if foreshadow_ops and text_to_summarize:
            plotledger_statuses = await activate_plot_ledgers(
                foreshadow_ops=foreshadow_ops,
                chapter_text=text_to_summarize,
                plot_ledger_repository=plot_ledger_repo,
                chapter_id=chapter.id,
                chapter_number=chapter.chapter_number,
            )
            svc_logger.info(
                f"PlotLedger activated for chapter {chapter_id}: "
                f"{sum(1 for s in plotledger_statuses if s.status == 'executed')} executed, "
                f"{sum(1 for s in plotledger_statuses if s.status == 'modified')} modified, "
                f"{sum(1 for s in plotledger_statuses if s.status == 'skipped')} skipped"
            )
    except Exception as e:
        svc_logger.warning(f"CP3.3 PlotLedger activation failed (non-blocking): {e}")

    # ========================================================================
    # CP3.3 滚动摘要更新（蓝图 §4.10 第 2 步）
    # ========================================================================
    # 1 次 light LLM：合并 Book.rolling_summary（旧）+ 本章 summary → 新滚动摘要
    # 滚动摘要供下一章 ContextEngine P1 使用（CP2.3a 已加字段）
    try:
        if chapter.summary:
            await update_rolling_summary(
                book_repository=book_repo,
                book_id=chapter.book_id,
                chapter_summary=chapter.summary,
                chapter_number=chapter.chapter_number,
            )
    except Exception as e:
        svc_logger.warning(f"CP3.3 rolling summary update failed (non-blocking): {e}")

    await chapter_repo.commit()
    await chapter_repo.refresh(chapter)

    # 构建人物提取响应
    extraction_summary = None
    if character_extraction_result:
        _log_to_file(f"Building response: {len(character_extraction_result.extracted_characters)} characters")
        for c in character_extraction_result.extracted_characters:
            _log_to_file(f"  Char '{c.name}': role_type={c.role_type}, importance_level={c.importance_level}")
        
        extraction_summary = CharacterExtractionSummary(
            extracted_characters=[
                {
                    "name": c.name,
                    "is_new": c.is_new,
                    "existing_id": c.existing_id,
                    "description": c.description,
                    "role_type": c.role_type,
                    "aliases": c.aliases,
                    "first_appearance": c.first_appearance,
                    "importance_level": c.importance_level,
                }
                for c in character_extraction_result.extracted_characters
            ],
            new_characters_count=len(character_extraction_result.new_characters),
            existing_characters_count=len(character_extraction_result.existing_characters),
            inferred_relationships=[
                {
                    "source_name": r.source_name,
                    "target_name": r.target_name,
                    "relation_type": r.relation_type,
                    "description": r.description,
                    "affinity_score": r.affinity_score,
                    "is_new": r.is_new,
                }
                for r in character_extraction_result.inferred_relationships
            ],
            chapter_entity_links=character_extraction_result.chapter_entity_links,
        )

    return ChapterPublishResponse(
        chapter_id=chapter.id,
        status=chapter.status,
        summary=chapter.summary,
        character_updates=character_updates,
        world_snapshot=chapter.world_snapshot if chapter.world_snapshot else None,
        character_extraction=extraction_summary,
    )


# =============================================================================
# 调试接口：测试人物提取功能
# =============================================================================

class CharacterExtractionTestRequest(BaseModel):
    """人物提取测试请求"""
    chapter_content: str


class CharacterExtractionTestResponse(BaseModel):
    """人物提取测试响应"""
    success: bool
    extracted_characters: List[Dict[str, Any]] = Field(default_factory=list)
    new_characters: List[Dict[str, Any]] = Field(default_factory=list)
    existing_characters: List[Dict[str, Any]] = Field(default_factory=list)
    inferred_relationships: List[Dict[str, Any]] = Field(default_factory=list)
    message: str = ""
    raw_response: Optional[str] = None


@router.post("/debug/character-extraction", response_model=CharacterExtractionTestResponse)
async def test_character_extraction(
    request: CharacterExtractionTestRequest,
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """调试接口：测试人物提取功能（不保存任何数据）
    
    用于测试人物提取功能是否正常工作，返回提取结果但不创建角色。
    
    Args:
        request: 包含章节内容和API配置
        
    Returns:
        提取的人物列表和关系列表
    """
    import json
    from backend.services.prompts.character_extraction import (
        build_character_extraction_prompt,
        build_character_extraction_system_prompt,
    )
    from backend.services.llm import call_llm
    
    try:
        svc_logger.info(
            "Testing character extraction",
            content_length=len(request.chapter_content),
        )
        
        user_prompt = build_character_extraction_prompt(
            chapter_content=request.chapter_content[:8000],
            existing_character_names=[],
        )
        system_prompt = build_character_extraction_system_prompt()
        
        # 记录 Prompt 长度用于调试
        svc_logger.info("Prompt prepared", system_len=len(system_prompt), user_len=len(user_prompt))
        
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
        )
        
        svc_logger.info("LLM response received", response_length=len(response))
        
        # 解析JSON响应
        text = response.strip()
        original_text = text
        
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        
        extraction_data = json.loads(text)
        
        if not extraction_data:
            return CharacterExtractionTestResponse(
                success=False,
                message="LLM 返回空结果",
                raw_response=original_text[:1000],
            )
        
        # 解析结果（简化版，不查数据库）
        characters = extraction_data.get("characters", [])
        relationships = extraction_data.get("relationships", [])
        
        svc_logger.info("Parsed extraction result", char_count=len(characters), rel_count=len(relationships))
        
        # 分类角色
        new_chars = []
        existing_chars_result = []
        
        for char_data in characters:
            is_new = char_data.get("is_new", True)
            # 处理字符串 "true"/"false"
            if isinstance(is_new, str):
                is_new = is_new.lower() == "true"
            
            char_info = {
                "name": char_data.get("name", ""),
                "is_new": is_new,
                "description": char_data.get("description", ""),
                "role_type": char_data.get("role_type", "supporting"),
                "aliases": char_data.get("aliases", []),
                "importance_level": char_data.get("importance_level", 3),
            }
            
            if is_new:
                new_chars.append(char_info)
            else:
                existing_chars_result.append(char_info)
        
        return CharacterExtractionTestResponse(
            success=True,
            extracted_characters=characters,
            new_characters=new_chars,
            existing_characters=existing_chars_result,
            inferred_relationships=relationships,
            message=f"成功提取 {len(characters)} 个角色，其中新角色 {len(new_chars)} 个",
            raw_response=original_text[:500] if len(original_text) > 500 else original_text,
        )
        
    except json.JSONDecodeError as e:
        svc_logger.error("JSON parse error", error=str(e))
        return CharacterExtractionTestResponse(
            success=False,
            message=f"JSON 解析错误: {str(e)}",
            raw_response=text[:1000] if 'text' in locals() else None,
        )
    except Exception as e:
        svc_logger.error("Character extraction test failed", error=str(e), exc_info=True)
        return CharacterExtractionTestResponse(
            success=False,
            message=f"提取失败: {str(e)}",
        )

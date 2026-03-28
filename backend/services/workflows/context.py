"""
上下文加载模块。

职责：提供章节上下文加载功能，包括书籍、角色、关系、伏笔和 RAG 记忆。

主要功能：
- load_chapter_context: 加载章节完整上下文（旧版接口，保持兼容）
- load_chapter_context_v2: 加载章节上下文（新版，使用增强 RAG）
- load_chapter_context_v3: 加载章节上下文（V3.8，完全使用新 RAG 架构）

V3.8 重构：
- 完全迁移到新 RAG 架构（WorkflowRetrievalIntegrator）
- 统一使用 WorkflowStage 定义检索阶段
- 提供阶段化检索接口（规划/起草/审阅/精修）
- 保持旧接口向后兼容
"""

import logging
from typing import Any, Optional, Dict, List, Tuple
from uuid import UUID

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, PlotLedger
from backend.repositories import MemoryRepository
from backend.services.llm_client import get_embedding
from backend.world_state_schemas import WorldTerminalState

# V3.8: 导入新 RAG 系统
try:
    from backend.services.rag import (
        WorkflowRetrievalIntegrator,
        WorkflowIntegrationConfig,
        WorkflowStage,
        RetrievalStrategy,
        MemoryType,
        ContextPackage,
        RetrievalResult,
        generate_retrieval_report,
    )
    NEW_RAG_AVAILABLE = True
except ImportError:
    NEW_RAG_AVAILABLE = False
    logger.warning("[Context] 新 RAG 系统导入失败，使用旧版实现")


async def load_chapter_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    rag_top_k: int = 3,
    rag_alpha: float = 0.6,
    rag_beta: float = 0.2,
    rag_gamma: float = 0.2,
    rag_lambda: float = 0.1,
) -> Optional[dict[str, Any]]:
    """加载章节上下文，包括书籍、角色、关系、伏笔和 RAG 记忆。

    这是 Agentic 工作流的入口函数，负责组装生成章节所需的全部上下文信息。

    Args:
        chapter_id: 章节 UUID
        db: 数据库会话
        api_key: LLM API Key（用于 RAG 向量检索）
        base_url: LLM Base URL
        rag_top_k: RAG 检索返回的记忆条数
        rag_alpha: RAG 权重 - 向量相似度
        rag_beta: RAG 权重 - 时间衰减
        rag_gamma: RAG 权重 - 位置接近度
        rag_lambda: RAG 权重 - 章节相关性

    Returns:
        Optional[dict]: 包含以下键的字典：
        - chapter: 章节实体
        - book: 书籍实体
        - entities: 章节关联的角色实体列表
        - relationships: 角色关系列表
        - previous_summary: 上一章摘要
        - open_hooks: 开放伏笔列表
        - relevant_memories: RAG 检索到的相关记忆列表
        如果章节不存在则返回 None
    """
    basic = await _load_basic_context(chapter_id, db)
    if not basic:
        return None

    chapter, book = basic["chapter"], basic["book"]

    entities = await _load_entities(chapter_id, db)
    relationships = await _load_relationships(entities, db)
    previous_summary = await _load_previous_summary(chapter, db)
    open_hooks = await _load_open_hooks(chapter, db)
    relevant_memories = await _load_relevant_memories(
        chapter, api_key, base_url, db,
        rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda
    )

    # 构建角色物理形态映射 (entity_spatial_ledger)
    entity_spatial_ledger = {}
    for entity in entities:
        # entity 是 ChapterEntity 对象，通过 selectinload 预加载了 character
        character = entity.character
        if character and character.name:
            # 构建默认的物理状态结构，与 CharacterPhysicalState schema 对应
            entity_spatial_ledger[character.name] = {
                "is_in_vehicle": False,
                "vehicle_or_mech_name": "",
                "equipped_weapons": [],
                "movement_constraints": ""
            }

    # =================================================================
    # V3.6: 加载前一章的世界终端状态 (WorldTerminalState)
    # =================================================================
    previous_world_state = await _load_previous_world_terminal_state(chapter, db)
    if previous_world_state:
        logger.debug(f"[Context] Loaded previous world state: {previous_world_state.scene.location_summary}")
    else:
        logger.debug(f"[Context] No previous world state (chapter {chapter.chapter_number})")

    return {
        "chapter": chapter,
        "book": book,
        "entities": entities,
        "relationships": relationships,
        "previous_summary": previous_summary,
        "open_hooks": open_hooks,
        "relevant_memories": relevant_memories,
        "chapter_assets_schema": chapter.chapter_assets_schema or "",
        "entity_spatial_ledger": entity_spatial_ledger,
        "previous_world_state": previous_world_state,  # V3.6: 新增世界终端状态
    }


async def _load_basic_context(chapter_id: Any, db: AsyncSession) -> Optional[dict[str, Any]]:
    """加载章节和书籍基本信息。

    Args:
        chapter_id: 章节 UUID
        db: 数据库会话

    Returns:
        Optional[dict]: 包含 chapter 和 book 的字典
    """
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        return None

    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()

    return {"chapter": chapter, "book": book}


async def _load_entities(chapter_id: Any, db: AsyncSession) -> list[Any]:
    """加载章节关联的角色实体列表。

    Args:
        chapter_id: 章节 UUID
        db: 数据库会话

    Returns:
        list: 章节关联的角色实体列表
    """
    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    return list(entities_result.scalars().all())


async def _load_relationships(entities: list[Any], db: AsyncSession) -> list[Any]:
    """加载角色之间的关系列表。

    Args:
        entities: 章节关联的角色实体列表
        db: 数据库会话

    Returns:
        list: 角色关系列表
    """
    if not entities:
        return []

    character_ids = [e.entity_id for e in entities]
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(
            selectinload(CharacterRelationship.source_character),
            selectinload(CharacterRelationship.target_character),
        )
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    return list(relationships_result.scalars().all())


async def _load_previous_summary(chapter: Chapter, db: AsyncSession) -> Optional[str]:
    """加载上一章的摘要。

    Args:
        chapter: 当前章节实体
        db: 数据库会话

    Returns:
        Optional[str]: 上一章摘要，不存在则返回 None
    """
    if chapter.chapter_number <= 1:
        return None

    prev_chapter_result = await db.execute(
        select(Chapter).where(
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1
        )
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    return prev_chapter.summary if prev_chapter else None


async def _load_open_hooks(chapter: Chapter, db: AsyncSession) -> list[dict[str, str]]:
    """加载当前章节之前的所有开放伏笔。

    Args:
        chapter: 当前章节实体
        db: 数据库会话

    Returns:
        list[dict]: 开放伏笔列表，每项包含 hook_id, ledger_key, content
    """
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

    open_hooks = []
    for row in open_hook_result.scalars().all():
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        open_hooks.append({
            "hook_id": hook_id,
            "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
            "content": content,
        })

    return open_hooks


async def _load_relevant_memories(
    chapter: Chapter,
    api_key: Optional[str],
    base_url: Optional[str],
    db: AsyncSession,
    rag_top_k: int,
    rag_alpha: float,
    rag_beta: float,
    rag_gamma: float,
    rag_lambda: float,
) -> list[Any]:
    """使用 RAG 检索与章节大纲相关的记忆。

    Args:
        chapter: 当前章节实体
        api_key: LLM API Key
        base_url: LLM Base URL
        db: 数据库会话
        rag_top_k: 检索返回的记忆条数
        rag_alpha: 向量相似度权重
        rag_beta: 时间衰减权重
        rag_gamma: 位置接近度权重
        rag_lambda: 章节相关性权重

    Returns:
        list: 相关记忆列表
    """
    if not chapter.outline_text or not api_key:
        return []

    try:
        embedding = await get_embedding(chapter.outline_text, api_key, base_url)
        if not embedding:
            return []

        memory_repo = MemoryRepository(db)
        return await memory_repo.search_similar(
            embedding,
            chapter.book_id,
            limit=rag_top_k,
            alpha=rag_alpha,
            beta=rag_beta,
            gamma=rag_gamma,
            lambda_decay=rag_lambda,
            exclude_chapter_id=chapter.id,
            max_chapter_number=chapter.chapter_number - 1,
        )
    except Exception as e:
        logger.error(f"[RAG] {e}")
        return []


# =============================================================================
# V3.6: 世界终端状态加载函数
# =============================================================================

async def _load_previous_world_terminal_state(
    chapter: Chapter,
    db: AsyncSession
) -> Optional[WorldTerminalState]:
    """加载前一章的世界终端状态。

    在 ASSEMBLING_CONTEXT 阶段调用，用于获取前一章末尾的物理状态约束。
    如果是第一章（chapter_number <= 1），返回 None。

    Args:
        chapter: 当前章节实体
        db: 数据库会话

    Returns:
        Optional[WorldTerminalState]: 前一章的世界终端状态，不存在或第一章返回 None
    """
    # 第一章没有前一章状态
    if chapter.chapter_number <= 1:
        logger.debug(f"[WorldState] Chapter {chapter.chapter_number} is first chapter, no previous state")
        return None

    try:
        # 查询前一章
        prev_chapter_result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1
            )
        )
        prev_chapter = prev_chapter_result.scalar_one_or_none()

        if not prev_chapter:
            logger.debug(f"[WorldState] Previous chapter not found for chapter {chapter.chapter_number}")
            return None

        # 从 world_snapshot 解析 WorldTerminalState
        if prev_chapter.world_snapshot:
            world_state = WorldTerminalState.from_chapter_snapshot(prev_chapter.world_snapshot)
            if world_state:
                logger.info(
                    f"[WorldState] Loaded state from chapter {prev_chapter.chapter_number}: "
                    f"{len(world_state.characters)} characters, "
                    f"location: {world_state.scene.location_summary[:30]}..."
                )
                return world_state
            else:
                logger.warning(f"[WorldState] Failed to parse world_snapshot from chapter {prev_chapter.chapter_number}")
                return None
        else:
            logger.debug(f"[WorldState] Chapter {prev_chapter.chapter_number} has no world_snapshot")
            return None

    except Exception as e:
        logger.error(f"[WorldState] Error loading previous world state: {e}")
        return None


# =============================================================================
# V3.7: 增强型 RAG 系统集成
# =============================================================================

async def load_chapter_context_v2(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    rag_top_k: int = 5,
    rag_alpha: float = 0.6,
    rag_beta: float = 0.2,
    rag_gamma: float = 0.2,
    rag_lambda: float = 0.1,
    enable_enhanced_rag: bool = True,
) -> Optional[dict[str, Any]]:
    """
    加载章节上下文（V2 版本，使用增强型 RAG 系统）
    
    与旧版 load_chapter_context 的主要区别：
    1. 使用 WorkflowRetrievalIntegrator 执行统一检索
    2. 支持多维度评分（语义、时间衰减、伏笔关联、角色相关度）
    3. 自动构建上下文包（ContextPackage）
    4. 提供检索可解释性
    
    Args:
        chapter_id: 章节 UUID
        db: 数据库会话
        api_key: LLM API Key
        base_url: LLM Base URL
        rag_top_k: RAG 检索返回的记忆条数
        rag_alpha: 语义相似度权重
        rag_beta: 时间衰减权重
        rag_gamma: 伏笔关联权重
        rag_lambda: 衰减系数
        enable_enhanced_rag: 是否启用增强型 RAG（默认 True）
        
    Returns:
        Optional[dict]: 包含上下文的字典，新增字段：
        - rag_result: 检索结果
        - context_package: 上下文包
        - rag_explanation: 检索说明
    """
    # 如果不启用增强型 RAG，降级到旧版
    if not enable_enhanced_rag:
        logger.info("[ContextV2] 增强型 RAG 未启用，使用旧版接口")
        return await load_chapter_context(
            chapter_id, db, api_key, base_url,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda
        )
    
    # 使用旧版加载基础数据
    basic = await _load_basic_context(chapter_id, db)
    if not basic:
        return None
    
    chapter, book = basic["chapter"], basic["book"]
    
    # 加载实体和关系
    entities = await _load_entities(chapter_id, db)
    relationships = await _load_relationships(entities, db)
    previous_summary = await _load_previous_summary(chapter, db)
    previous_world_state = await _load_previous_world_terminal_state(chapter, db)
    
    # 构建开放伏笔列表（用于新 RAG）
    open_hooks = await _load_open_hooks(chapter, db)
    
    # === 使用新 RAG 系统执行检索 ===
    rag_result = None
    context_package = None
    rag_explanation = ""
    
    try:
        from backend.services.rag import (
            WorkflowRetrievalIntegrator,
            WorkflowStage,
            WorkflowIntegrationConfig,
            RetrievalStrategy,
            generate_retrieval_report,
        )
        
        # 确定检索策略
        if rag_top_k <= 3:
            strategy = RetrievalStrategy.FAST_TRACK
        elif rag_top_k >= 8:
            strategy = RetrievalStrategy.DEEP_DIVE
        else:
            strategy = RetrievalStrategy.BALANCED_REFERENCE
        
        # 配置集成器
        config = WorkflowIntegrationConfig(
            default_strategy=strategy,
            enable_vector_search=api_key is not None,
        )
        
        integrator = WorkflowRetrievalIntegrator(db, config)
        
        # 执行检索
        context_package, rag_result = await integrator.retrieve_chapter_context(
            chapter_id=chapter_id,
            api_key=api_key,
            base_url=base_url,
            stage=WorkflowStage.ASSEMBLING,
        )
        
        # 生成可解释性报告
        if rag_result:
            report = generate_retrieval_report(rag_result)
            rag_explanation = report.get_summary()
        
        logger.info(
            f"[ContextV2] RAG 检索完成: {rag_result.total_items if rag_result else 0} 项, "
            f"耗时 {rag_result.retrieval_time_ms if rag_result else 0:.1f}ms"
        )
        
    except Exception as e:
        logger.warning(f"[ContextV2] 增强 RAG 失败，降级到基础检索: {e}")
        # 降级：使用旧版记忆检索
        relevant_memories = await _load_relevant_memories(
            chapter, api_key, base_url, db,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda
        )
    
    # 构建角色物理形态映射
    entity_spatial_ledger = {}
    for entity in entities:
        character = entity.character
        if character and character.name:
            entity_spatial_ledger[character.name] = {
                "is_in_vehicle": False,
                "vehicle_or_mech_name": "",
                "equipped_weapons": [],
                "movement_constraints": ""
            }
    
    # 从 RAG 结果提取相关记忆
    relevant_memories = []
    if rag_result:
        from backend.services.rag import MemoryType
        memory_items = rag_result.get_items_by_type(MemoryType.MEMORY_CHUNK)
        relevant_memories = [
            {"content": item.content, "chapter_number": item.chapter_number}
            for item in memory_items
        ]
    
    return {
        "chapter": chapter,
        "book": book,
        "entities": entities,
        "relationships": relationships,
        "previous_summary": previous_summary,
        "open_hooks": open_hooks,
        "relevant_memories": relevant_memories,
        "chapter_assets_schema": chapter.chapter_assets_schema or "",
        "entity_spatial_ledger": entity_spatial_ledger,
        "previous_world_state": previous_world_state,
        # V3.7 新增字段
        "rag_result": rag_result,
        "context_package": context_package,
        "rag_explanation": rag_explanation,
    }


# =============================================================================
# V3.8: 完全基于新 RAG 架构的上下文加载
# =============================================================================

async def load_chapter_context_v3(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    stage: str = "assembling",
    rag_top_k: int = 5,
    rag_alpha: float = 0.6,
    rag_beta: float = 0.2,
    rag_gamma: float = 0.2,
    rag_lambda: float = 0.1,
) -> Optional[dict[str, Any]]:
    """
    加载章节上下文（V3.8 版本，完全使用新 RAG 架构）
    
    这是推荐的上下文加载方式，使用 WorkflowRetrievalIntegrator 执行统一检索。
    
    Args:
        chapter_id: 章节 UUID
        db: 数据库会话
        api_key: LLM API Key
        base_url: LLM Base URL
        stage: 工作流阶段（assembling/planning/drafting/reviewing/refining）
        rag_top_k: RAG 检索返回的记忆条数
        rag_alpha: 语义相似度权重
        rag_beta: 时间衰减权重
        rag_gamma: 伏笔关联权重
        rag_lambda: 衰减系数
        
    Returns:
        Optional[dict]: 包含上下文的字典，结构同 load_chapter_context_v2
    """
    if not NEW_RAG_AVAILABLE:
        logger.info("[ContextV3] 新 RAG 系统不可用，降级到 V2")
        return await load_chapter_context_v2(
            chapter_id, db, api_key, base_url,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda,
            enable_enhanced_rag=False
        )
    
    try:
        # 映射阶段字符串到 WorkflowStage
        stage_map = {
            "assembling": WorkflowStage.ASSEMBLING,
            "planning": WorkflowStage.PLANNING,
            "drafting": WorkflowStage.DRAFTING,
            "reviewing": WorkflowStage.REVIEWING,
            "refining": WorkflowStage.REFINING,
        }
        workflow_stage = stage_map.get(stage, WorkflowStage.ASSEMBLING)
        
        # 确定检索策略
        if rag_top_k <= 3:
            strategy = RetrievalStrategy.FAST_TRACK
        elif rag_top_k >= 8:
            strategy = RetrievalStrategy.DEEP_DIVE
        else:
            strategy = RetrievalStrategy.BALANCED_REFERENCE
        
        # 配置集成器
        config = WorkflowIntegrationConfig(
            default_strategy=strategy,
            enable_vector_search=api_key is not None,
        )
        
        integrator = WorkflowRetrievalIntegrator(db, config)
        
        # 执行检索
        context_package, rag_result = await integrator.retrieve_chapter_context(
            chapter_id=chapter_id,
            api_key=api_key,
            base_url=base_url,
            stage=workflow_stage,
        )
        
        # 获取章节和书籍信息
        chapter = None
        book = None
        chapter_result = await db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        
        if chapter:
            book_result = await db.execute(
                select(Book).where(Book.id == chapter.book_id)
            )
            book = book_result.scalar_one_or_none()
        
        
        if not chapter:
            return None
        
        # 从 RAG 结果提取各类型数据
        entities = []
        relationships = []
        
        # 提取角色
        character_items = rag_result.get_items_by_type(MemoryType.CHARACTER_STATE)
        character_ids = set()
        for item in character_items:
            if item.source_id:
                character_ids.add(item.source_id)
        
        
        if character_ids:
            entities_result = await db.execute(
                select(ChapterEntity)
                .options(selectinload(ChapterEntity.character))
                .where(ChapterEntity.chapter_id == chapter_id)
            )
            entities = list(entities_result.scalars().all())
        else:
            # 如果 RAG 没有返回角色，手动加载
            entities = await _load_entities(chapter_id, db)
        
        
        # 加载关系
        relationships = await _load_relationships(entities, db)
        
        # 从 RAG 结果提取开放伏笔
        hook_items = rag_result.get_items_by_type(MemoryType.OPEN_HOOK)
        open_hooks = [
            {
                "hook_id": item.source_id,
                "ledger_key": item.source_id,
                "content": item.content,
            }
            for item in hook_items
        ]
        
        # 从 RAG 结果提取相关记忆
        memory_items = rag_result.get_items_by_type(MemoryType.MEMORY_CHUNK)
        relevant_memories = [
            {"content": item.content, "chapter_number": item.chapter_number}
            for item in memory_items
        ]
        
        # 从 RAG 结果提取上一章摘要
        prev_items = rag_result.get_items_by_type(MemoryType.PREVIOUS_SUMMARY)
        previous_summary = prev_items[0].content if prev_items else None
        
        # 加载世界状态
        previous_world_state = await _load_previous_world_terminal_state(chapter, db)
        
        # 构建角色物理形态映射
        entity_spatial_ledger = {}
        for entity in entities:
            character = entity.character
            if character and character.name:
                entity_spatial_ledger[character.name] = {
                    "is_in_vehicle": False,
                    "vehicle_or_mech_name": "",
                    "equipped_weapons": [],
                    "movement_constraints": ""
                }
        
        # 生成可解释性报告
        rag_explanation = ""
        if rag_result:
            report = generate_retrieval_report(rag_result)
            rag_explanation = report.get_summary()
        
        logger.info(
            f"[ContextV3] 上下文加载完成: 章节 {chapter.chapter_number}, "
            f"阶段 {stage}, {rag_result.total_items if rag_result else 0} 项, "
            f"耗时 {rag_result.retrieval_time_ms if rag_result else 0:.1f}ms"
        )
        
        return {
            "chapter": chapter,
            "book": book,
            "entities": entities,
            "relationships": relationships,
            "previous_summary": previous_summary,
            "open_hooks": open_hooks,
            "relevant_memories": relevant_memories,
            "chapter_assets_schema": chapter.chapter_assets_schema or "",
            "entity_spatial_ledger": entity_spatial_ledger,
            "previous_world_state": previous_world_state,
            # V3.8 新增字段
            "rag_result": rag_result,
            "context_package": context_package,
            "rag_explanation": rag_explanation,
        }
        
    except Exception as e:
        logger.error(f"[ContextV3] 加载失败: {e}")
        # 降级到 V2
        return await load_chapter_context_v2(
            chapter_id, db, api_key, base_url,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda,
            enable_enhanced_rag=False
        )


async def get_context_for_stage(
    chapter_id: Any,
    db: AsyncSession,
    stage: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[ContextPackage], Optional[RetrievalResult]]:
    """
    获取指定阶段的上下文（便捷接口）
    
    Args:
        chapter_id: 章节 UUID
        db: 数据库会话
        stage: 工作流阶段
        api_key: API Key
        base_url: Base URL
        
    Returns:
        Tuple[ContextPackage, RetrievalResult]: 上下文包和检索结果
    """
    if not NEW_RAG_AVAILABLE:
        logger.warning("[Context] 新 RAG 系统不可用")
        return None, None
    
    stage_map = {
        "assembling": WorkflowStage.ASSEMBLING,
        "planning": WorkflowStage.PLANNING,
        "drafting": WorkflowStage.DRAFTING,
        "reviewing": WorkflowStage.REVIEWING,
        "refining": WorkflowStage.REFINING,
    }
    workflow_stage = stage_map.get(stage, WorkflowStage.ASSEMBLING)
    
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.retrieve_chapter_context(
        chapter_id=chapter_id,
        api_key=api_key,
        base_url=base_url,
        stage=workflow_stage,
    )


async def get_planning_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """获取规划阶段上下文（便捷接口）"""
    return await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="planning"
    )


async def get_drafting_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """获取起草阶段上下文（便捷接口）"""
    return await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="drafting"
    )


async def get_reviewing_context(
    chapter_id: Any,
    db: AsyncSession,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Optional[dict[str, Any]], List[Dict[str, Any]]]:
    """
    获取审阅阶段上下文（便捷接口）
    
    Returns:
        Tuple[context, omissions]: 上下文和伏笔遗漏报告
    """
    context = await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="reviewing"
    )
    
    if not context:
        return None, []
    
    # 检测伏笔遗漏
    omissions = []
    if NEW_RAG_AVAILABLE and context.get("chapter"):
        try:
            from backend.services.rag import EnhancedForeshadowingTracker, EnhancedHookOmissionDetector
            
            tracker = EnhancedForeshadowingTracker(db)
            detector = EnhancedHookOmissionDetector(tracker)
            
            chapter = context["chapter"]
            chapter_text = chapter.draft_text or ""
            
            if chapter_text:
                omissions = await detector.detect_omissions(
                    chapter_text,
                    chapter.book_id,
                    chapter.chapter_number,
                )
        except Exception as e:
            logger.warning(f"[Context] 伏笔遗漏检测失败: {e}")
    
    return context, omissions


async def get_refining_context(
    chapter_id: Any,
    db: AsyncSession,
    review_issues: List[Dict[str, Any]],
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """
    获取精修阶段上下文（便捷接口）
    
    Args:
        chapter_id: 章节 UUID
        db: 数据库会话
        review_issues: 审阅问题列表
        api_key: API Key
        base_url: Base URL
        
    Returns:
        上下文字典
    """
    return await load_chapter_context_v3(
        chapter_id, db, api_key, base_url,
        stage="refining"
    )

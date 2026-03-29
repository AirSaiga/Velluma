import logging
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.context import (
    load_chapter as _load_chapter,
    load_book as _load_book,
    load_chapter_entities as _load_chapter_entities,
)
from backend.services.workflows.context_basic import (
    load_chapter_context,
    _load_basic_context,
    _load_entities,
    _load_relationships,
    _load_previous_summary,
    _load_open_hooks,
    _load_relevant_memories,
    _load_previous_world_terminal_state,
)

logger = logging.getLogger(__name__)

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
    if not enable_enhanced_rag:
        logger.info("[ContextV2] 增强型 RAG 未启用，使用旧版接口")
        return await load_chapter_context(
            chapter_id, db, api_key, base_url,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda
        )

    basic = await _load_basic_context(chapter_id, db)
    if not basic:
        return None

    chapter, book = basic["chapter"], basic["book"]

    entities = await _load_entities(chapter_id, db)
    relationships = await _load_relationships(entities, db)
    previous_summary = await _load_previous_summary(chapter, db)
    previous_world_state = await _load_previous_world_terminal_state(chapter, db)

    open_hooks = await _load_open_hooks(chapter, db)

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

        if rag_top_k <= 3:
            strategy = RetrievalStrategy.FAST_TRACK
        elif rag_top_k >= 8:
            strategy = RetrievalStrategy.DEEP_DIVE
        else:
            strategy = RetrievalStrategy.BALANCED_REFERENCE

        config = WorkflowIntegrationConfig(
            default_strategy=strategy,
            enable_vector_search=api_key is not None,
        )

        integrator = WorkflowRetrievalIntegrator(db, config)

        context_package, rag_result = await integrator.retrieve_chapter_context(
            chapter_id=chapter_id,
            api_key=api_key,
            base_url=base_url,
            stage=WorkflowStage.ASSEMBLING,
        )

        if rag_result:
            report = generate_retrieval_report(rag_result)
            rag_explanation = report.get_summary()

        logger.info(
            f"[ContextV2] RAG 检索完成: {rag_result.total_items if rag_result else 0} 项, "
            f"耗时 {rag_result.retrieval_time_ms if rag_result else 0:.1f}ms"
        )

    except Exception as e:
        logger.warning(f"[ContextV2] 增强 RAG 失败，降级到基础检索: {e}")
        relevant_memories = await _load_relevant_memories(
            chapter, api_key, base_url, db,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda
        )

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
        "rag_result": rag_result,
        "context_package": context_package,
        "rag_explanation": rag_explanation,
    }


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
    if not NEW_RAG_AVAILABLE:
        logger.info("[ContextV3] 新 RAG 系统不可用，降级到 V2")
        return await load_chapter_context_v2(
            chapter_id, db, api_key, base_url,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda,
            enable_enhanced_rag=False
        )

    try:
        stage_map = {
            "assembling": WorkflowStage.ASSEMBLING,
            "planning": WorkflowStage.PLANNING,
            "drafting": WorkflowStage.DRAFTING,
            "reviewing": WorkflowStage.REVIEWING,
            "refining": WorkflowStage.REFINING,
        }
        workflow_stage = stage_map.get(stage, WorkflowStage.ASSEMBLING)

        if rag_top_k <= 3:
            strategy = RetrievalStrategy.FAST_TRACK
        elif rag_top_k >= 8:
            strategy = RetrievalStrategy.DEEP_DIVE
        else:
            strategy = RetrievalStrategy.BALANCED_REFERENCE

        config = WorkflowIntegrationConfig(
            default_strategy=strategy,
            enable_vector_search=api_key is not None,
        )

        integrator = WorkflowRetrievalIntegrator(db, config)

        context_package, rag_result = await integrator.retrieve_chapter_context(
            chapter_id=chapter_id,
            api_key=api_key,
            base_url=base_url,
            stage=workflow_stage,
        )

        chapter = await _load_chapter(db, str(chapter_id))
        if not chapter:
            return None

        book = await _load_book(db, str(chapter.book_id))

        entities = []
        relationships = []

        character_items = rag_result.get_items_by_type(MemoryType.CHARACTER_STATE)
        character_ids = set()
        for item in character_items:
            if item.source_id:
                character_ids.add(item.source_id)

        if character_ids:
            entities = await _load_chapter_entities(db, str(chapter_id))
        else:
            entities = await _load_entities(chapter_id, db)

        relationships = await _load_relationships(entities, db)

        hook_items = rag_result.get_items_by_type(MemoryType.OPEN_HOOK)
        open_hooks = [
            {
                "hook_id": item.source_id,
                "ledger_key": item.source_id,
                "content": item.content,
            }
            for item in hook_items
        ]

        memory_items = rag_result.get_items_by_type(MemoryType.MEMORY_CHUNK)
        relevant_memories = [
            {"content": item.content, "chapter_number": item.chapter_number}
            for item in memory_items
        ]

        prev_items = rag_result.get_items_by_type(MemoryType.PREVIOUS_SUMMARY)
        previous_summary = prev_items[0].content if prev_items else None

        previous_world_state = await _load_previous_world_terminal_state(chapter, db)

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
            "rag_result": rag_result,
            "context_package": context_package,
            "rag_explanation": rag_explanation,
        }

    except Exception as e:
        logger.error(f"[ContextV3] 加载失败: {e}")
        return await load_chapter_context_v2(
            chapter_id, db, api_key, base_url,
            rag_top_k, rag_alpha, rag_beta, rag_gamma, rag_lambda,
            enable_enhanced_rag=False
        )

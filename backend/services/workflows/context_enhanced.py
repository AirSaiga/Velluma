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

"""
增强上下文组装模块 - V4.0 版本上下文加载（含 RAG 检索）。

迁移说明 (2026-03-30)：
- 已迁移到使用 Repository 模式
- 所有函数现在接受 repositories 字典参数
- V4.0 版本现已稳定，移除 V4.0 降级逻辑

使用方式：
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        ...
    }
    context = await load_chapter_context_v3(chapter_id, repos)
"""

import logging
from typing import Any, Optional, Dict

from backend.services.context import (
    load_chapter,
    load_book,
    load_chapter_entities,
    load_character_relationships,
    load_previous_chapter_summary,
    load_open_hooks,
    load_previous_world_snapshot,
)
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

logger = logging.getLogger(__name__)


async def load_chapter_context_v3(
    chapter_id: Any,
    repositories: Dict[str, Any],
    stage: str = "assembling",
    rag_top_k: int = 5,
    rag_alpha: float = 0.6,
    rag_beta: float = 0.2,
    rag_gamma: float = 0.2,
    rag_lambda: float = 0.1,
) -> Optional[dict[str, Any]]:
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
        enable_vector_search=True,
    )

    integrator = WorkflowRetrievalIntegrator(repositories, config)

    context_package, rag_result = await integrator.retrieve_chapter_context(
        chapter_id=chapter_id,
        stage=workflow_stage,
    )

    chapter = await load_chapter(repositories, str(chapter_id))
    if not chapter:
        return None

    book = await load_book(repositories, str(chapter.book_id))

    entities = []
    relationships = []

    character_items = rag_result.get_items_by_type(MemoryType.CHARACTER_STATE)
    character_ids = set()
    for item in character_items:
        if item.source_id:
            character_ids.add(item.source_id)

    if character_ids:
        entities = await load_chapter_entities(repositories, str(chapter_id))
    else:
        entities = await load_chapter_entities(repositories, str(chapter_id))

    relationships = await load_character_relationships(repositories, entities)

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

    previous_world_state = await load_previous_world_snapshot(repositories, chapter)

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

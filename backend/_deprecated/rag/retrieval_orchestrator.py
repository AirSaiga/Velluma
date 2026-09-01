# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
检索协调器 (Retrieval Orchestrator)

职责：
- 协调多种记忆类型的检索流程
- 整合章节目标导向检索
- 实现分层检索策略
- 管理检索结果合并与去重
- 提供与章节生成流程的接口

子模块：
- retrieval_builders: 数据构建与后处理工具函数
- retrieval_phases: 各检索阶段的异步函数
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Book,
    Chapter,
    CharacterRelationship,
    ChapterEntity,
)
from backend.services.rag.retrieval_types import (
    RetrievalStrategy,
    RetrievalStrategyConfig,
    RetrievalResult,
    STRATEGY_PRESETS,
)
from backend.services.rag.enhanced_scoring import (
    EnhancedScoringConfig,
    EnhancedRetrievalScorer,
    RetrievalContextBuilder,
    OutlineKeywordExtractor,
)
from backend.services.rag.retrieval_builders import (
    build_book_setting,
    build_character_item,
    build_relationship_item,
    build_world_snapshot_item,
    deduplicate_items,
    sort_items,
    get_chapter_number_from_chunk,
    get_beat_chapter_number,
)
from backend.services.rag.retrieval_phases import (
    retrieve_mandatory,
    retrieve_exact,
    retrieve_vector,
    retrieve_hybrid,
)


logger = logging.getLogger(__name__)


class RetrievalPhase(str, Enum):
    MANDATORY = "mandatory"
    EXACT = "exact"
    VECTOR = "vector"
    HYBRID = "hybrid"
    POST_PROCESS = "post_process"


class RetrievalOrchestratorConfig:

    def __init__(
        self,
        strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE,
        max_items: int = 30,
        max_context_length: int = 8000,
        max_items_per_type: int = 5,
        enable_vector_search: bool = True,
        enable_dedup: bool = True,
        enable_explainability: bool = True,
    ):
        self.strategy = strategy
        self.max_items = max_items
        self.max_context_length = max_context_length
        self.max_items_per_type = max_items_per_type
        self.enable_vector_search = enable_vector_search
        self.enable_dedup = enable_dedup
        self.enable_explainability = enable_explainability

        self.strategy_config = STRATEGY_PRESETS.get(
            strategy, RetrievalStrategyConfig()
        )


class RetrievalOrchestrator:

    def __init__(
        self,
        db: AsyncSession,
        config: Optional[RetrievalOrchestratorConfig] = None,
        get_embedding_func: Optional[Callable] = None,
    ):
        self.db = db
        self.config = config or RetrievalOrchestratorConfig()
        self.get_embedding = get_embedding_func

        self.scorer = EnhancedRetrievalScorer(
            EnhancedScoringConfig.from_strategy(self.config.strategy_config)
        )
        self.context_builder = RetrievalContextBuilder()
        self.outline_extractor = OutlineKeywordExtractor()

        self._retrieval_trace: List[Dict[str, Any]] = []

    async def retrieve(
        self,
        chapter: Chapter,
        book: Book,
        entities: List[ChapterEntity],
        relationships: List[CharacterRelationship],
        open_hooks: List[Dict[str, Any]],
        previous_summary: Optional[str],
        previous_world_state: Optional[Any],
    ) -> RetrievalResult:
        start_time = datetime.now(timezone.utc)
        self._retrieval_trace = []

        result = RetrievalResult(
            query=chapter.outline_text or "",
            chapter_id=str(chapter.id),
            chapter_number=chapter.chapter_number,
            strategy_name=self.config.strategy.value,
            strategy_params={
                "top_k": self.config.strategy_config.top_k,
                "semantic_weight": self.config.strategy_config.semantic_weight,
                "time_decay_weight": self.config.strategy_config.time_decay_weight,
                "foreshadowing_weight": self.config.strategy_config.foreshadowing_weight,
            },
        )

        scoring_context = self.context_builder.build(
            chapter_number=chapter.chapter_number,
            outline=chapter.outline_text or "",
            entities=entities,
            relationships=relationships,
            open_hooks=open_hooks,
        )

        await retrieve_mandatory(
            chapter, book, previous_summary, result, self.scorer, scoring_context
        )
        self._trace_phase(RetrievalPhase.MANDATORY, result.total_items)

        await retrieve_exact(
            chapter, entities, relationships, open_hooks,
            previous_world_state, result, self.scorer, scoring_context,
            max_items_per_type=self.config.max_items_per_type,
        )
        self._trace_phase(RetrievalPhase.EXACT, result.total_items)

        if self.config.enable_vector_search:
            await retrieve_vector(
                chapter, book, result, self.scorer, scoring_context,
                self.config.strategy_config, self.db,
                get_embedding_func=self.get_embedding,
            )
        self._trace_phase(RetrievalPhase.VECTOR, result.total_items)

        await retrieve_hybrid(
            chapter, book, entities, result, self.scorer, scoring_context, self.db
        )
        self._trace_phase(RetrievalPhase.HYBRID, result.total_items)

        await self._post_process(result, scoring_context)
        self._trace_phase(RetrievalPhase.POST_PROCESS, result.total_items)

        end_time = datetime.now(timezone.utc)
        result.retrieval_time_ms = (end_time - start_time).total_seconds() * 1000

        logger.info(
            f"[RetrievalOrchestrator] 检索完成: "
            f"章节 {chapter.chapter_number}, "
            f"{result.total_items} 项, "
            f"耗时 {result.retrieval_time_ms:.1f}ms"
        )

        return result

    async def _post_process(
        self,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        if self.config.enable_dedup:
            result.items = deduplicate_items(result.items)

        result.items = sort_items(result.items)

        result.items = result.items[:self.config.max_items]

        result.total_items = len(result.items)
        result.by_type = {}
        result.by_priority = {}

        for item in result.items:
            type_key = item.memory_type.value
            result.by_type[type_key] = result.by_type.get(type_key, 0) + 1

            priority_key = item.priority.value
            result.by_priority[priority_key] = result.by_priority.get(priority_key, 0) + 1

    def _trace_phase(self, phase: RetrievalPhase, item_count: int) -> None:
        self._retrieval_trace.append({
            "phase": phase.value,
            "item_count": item_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def get_retrieval_trace(self) -> List[Dict[str, Any]]:
        return self._retrieval_trace.copy()


async def orchestrate_retrieval(
    chapter: Chapter,
    book: Book,
    db: AsyncSession,
    entities: List[ChapterEntity],
    relationships: List[CharacterRelationship],
    open_hooks: List[Dict[str, Any]],
    previous_summary: Optional[str],
    previous_world_state: Optional[Any],
    strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE,
) -> RetrievalResult:
    config = RetrievalOrchestratorConfig(strategy=strategy)
    orchestrator = RetrievalOrchestrator(db, config)

    return await orchestrator.retrieve(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        open_hooks=open_hooks,
        previous_summary=previous_summary,
        previous_world_state=previous_world_state,
    )

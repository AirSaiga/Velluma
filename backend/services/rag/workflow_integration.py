import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    Book,
    Chapter,
    Character,
    CharacterRelationship,
    ChapterEntity,
    PlotLedger,
    MemoryChunk,
    StoryBeat,
    ChapterMapLocation,
)

from backend.services.rag.retrieval_types import (
    MemoryType,
    RetrievalStrategy,
    RetrievalStrategyConfig,
    RetrievalResult,
    RetrievedItem,
    ContextPackage,
    ContentPriority,
    ContentType,
    RetrievalScore,
    RetrievalMethod,
    STRATEGY_PRESETS,
)
from backend.services.rag.enhanced_scoring import (
    EnhancedScoringConfig,
    EnhancedRetrievalScorer,
    RetrievalContextBuilder,
    OutlineKeywordExtractor,
)
from backend.services.rag.smart_context_packager import (
    SmartContextPackager,
    PackagerConfig,
)
from backend.services.rag.enhanced_foreshadowing import (
    EnhancedForeshadowingTracker,
    EnhancedHookOmissionDetector,
    HookPriority,
    HookStatus,
    get_hooks_for_chapter_context,
)
from backend.services.rag.workflow_types import (
    WorkflowStage,
    RetrievalFailureMode,
    WorkflowIntegrationConfig,
    RetrievalCache,
)

logger = logging.getLogger(__name__)


class WorkflowRetrievalIntegrator:

    def __init__(
        self,
        db: AsyncSession,
        config: Optional[WorkflowIntegrationConfig] = None,
        get_embedding_func: Optional[Callable] = None,
    ):
        self.db = db
        self.config = config or WorkflowIntegrationConfig()
        self.get_embedding = get_embedding_func

        self._cache = RetrievalCache(self.config.cache_ttl_seconds)

        self._scorer = EnhancedRetrievalScorer()
        self._context_builder = RetrievalContextBuilder()
        self._packager = SmartContextPackager()
        self._keyword_extractor = OutlineKeywordExtractor()

    async def retrieve_chapter_context(
        self,
        chapter_id,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        stage: WorkflowStage = WorkflowStage.ASSEMBLING,
        force_refresh: bool = False,
    ) -> Tuple[ContextPackage, RetrievalResult]:
        cache_key = f"{chapter_id}:{stage.value}"

        if not force_refresh and self.config.cache_retrieval_results:
            cached = self._cache.get(cache_key)
            if cached:
                logger.debug(f"[WorkflowIntegrator] 使用缓存结果: {cache_key}")
                package = self._packager.build(cached)
                return package, cached

        try:
            chapter, book, entities, relationships, open_hooks, previous_summary, previous_world_state = \
                await self._load_chapter_data(chapter_id)

            if not chapter:
                raise ValueError(f"章节不存在: {chapter_id}")

            strategy = self.config.stage_strategies.get(
                stage.value, self.config.default_strategy
            )
            strategy_config = STRATEGY_PRESETS.get(strategy, RetrievalStrategyConfig())

            result = await self._execute_retrieval(
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                open_hooks=open_hooks,
                previous_summary=previous_summary,
                previous_world_state=previous_world_state,
                strategy_config=strategy_config,
                api_key=api_key,
                base_url=base_url,
            )

            max_length = self.config.max_context_lengths.get(stage.value, 8000)
            packager_config = PackagerConfig(max_total_length=max_length)
            self._packager = SmartContextPackager(packager_config, stage.value)
            package = self._packager.build(result)

            if self.config.cache_retrieval_results:
                self._cache.set(cache_key, result)

            logger.info(
                f"[WorkflowIntegrator] 检索完成: 章节 {chapter.chapter_number}, "
                f"阶段 {stage.value}, {result.total_items} 项, "
                f"上下文 {package.total_length} 字"
            )

            return package, result

        except Exception as e:
            logger.error(f"[WorkflowIntegrator] 检索失败: {e}")
            return self._handle_retrieval_failure(chapter_id, stage, str(e))

    async def get_context_for_planning(
        self,
        chapter_id,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ContextPackage:
        package, _ = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.PLANNING,
        )
        return package

    async def get_context_for_drafting(
        self,
        chapter_id,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ContextPackage:
        package, _ = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.DRAFTING,
        )
        return package

    async def get_context_for_reviewing(
        self,
        chapter_id,
        chapter_text: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[ContextPackage, List[Dict[str, Any]]]:
        package, result = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.REVIEWING,
        )

        omissions = []
        if self.config.enable_hook_detection:
            chapter_result = await self.db.execute(
                select(Chapter).where(Chapter.id == chapter_id)
            )
            chapter = chapter_result.scalar_one_or_none()

            if chapter:
                tracker = EnhancedForeshadowingTracker(self.db)
                detector = EnhancedHookOmissionDetector(tracker)
                omissions = await detector.detect_omissions(
                    chapter_text,
                    chapter.book_id,
                    chapter.chapter_number,
                )

        return package, omissions

    async def get_context_for_refining(
        self,
        chapter_id,
        review_issues: List[Dict[str, Any]],
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ContextPackage:
        package, result = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.REFINING,
        )

        for issue in review_issues:
            issue_type = issue.get("type", "")
            if issue_type == "character_consistency":
                pass
            elif issue_type == "foreshadowing_omission":
                pass

        return package

    async def _load_chapter_data(
        self,
        chapter_id,
    ) -> Tuple[
        Optional[Chapter],
        Optional[Book],
        List[ChapterEntity],
        List[CharacterRelationship],
        List[Dict[str, Any]],
        Optional[str],
        Optional[Any],
    ]:
        chapter_result = await self.db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()

        if not chapter:
            return None, None, [], [], [], None, None

        book_result = await self.db.execute(
            select(Book).where(Book.id == chapter.book_id)
        )
        book = book_result.scalar_one_or_none()

        entities_result = await self.db.execute(
            select(ChapterEntity)
            .options(selectinload(ChapterEntity.character))
            .where(ChapterEntity.chapter_id == chapter_id)
        )
        entities = list(entities_result.scalars().all())

        character_ids = [e.entity_id for e in entities]
        if character_ids:
            relationships_result = await self.db.execute(
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
            relationships = list(relationships_result.scalars().all())
        else:
            relationships = []

        hook_result = await self.db.execute(
            select(PlotLedger).where(
                PlotLedger.book_id == chapter.book_id,
                PlotLedger.status.in_([HookStatus.OPEN.value, HookStatus.ADDRESSED.value]),
                PlotLedger.created_at_chapter < chapter.chapter_number,
            )
        )
        open_hooks = [
            {
                "hook_id": str(h.id),
                "ledger_key": h.ledger_key or "",
                "content": h.content or "",
                "chapter_number": h.created_at_chapter or 0,
                "priority": (h.meta or {}).get("priority", HookPriority.SUB_PLOT.value),
            }
            for h in hook_result.scalars().all()
        ]

        previous_summary = None
        if chapter.chapter_number > 1:
            prev_result = await self.db.execute(
                select(Chapter).where(
                    Chapter.book_id == chapter.book_id,
                    Chapter.chapter_number == chapter.chapter_number - 1,
                )
            )
            prev_chapter = prev_result.scalar_one_or_none()
            if prev_chapter:
                previous_summary = prev_chapter.summary

        previous_world_state = None

        return (
            chapter, book, entities, relationships,
            open_hooks, previous_summary, previous_world_state
        )

    async def _execute_retrieval(
        self,
        chapter: Chapter,
        book: Book,
        entities: List[ChapterEntity],
        relationships: List[CharacterRelationship],
        open_hooks: List[Dict[str, Any]],
        previous_summary: Optional[str],
        previous_world_state: Optional[Any],
        strategy_config: RetrievalStrategyConfig,
        api_key: Optional[str],
        base_url: Optional[str],
    ) -> RetrievalResult:
        start_time = datetime.now(timezone.utc)

        result = RetrievalResult(
            query=chapter.outline_text or "",
            chapter_id=str(chapter.id),
            chapter_number=chapter.chapter_number,
            strategy_name=strategy_config.strategy_name.value,
            strategy_params={
                "top_k": strategy_config.top_k,
                "semantic_weight": strategy_config.semantic_weight,
            },
        )

        scoring_context = self._context_builder.build(
            chapter_number=chapter.chapter_number,
            outline=chapter.outline_text or "",
            entities=entities,
            relationships=relationships,
            open_hooks=open_hooks,
        )

        await self._retrieve_mandatory(
            chapter, book, previous_summary, result, scoring_context
        )

        await self._retrieve_exact(
            chapter, entities, relationships, open_hooks,
            previous_world_state, result, scoring_context
        )

        if self.config.enable_vector_search and api_key:
            await self._retrieve_vector(
                chapter, book, result, scoring_context, api_key, base_url, strategy_config
            )

        await self._retrieve_hybrid(chapter, book, entities, result, scoring_context)

        await self._post_process(result)

        end_time = datetime.now(timezone.utc)
        result.retrieval_time_ms = (end_time - start_time).total_seconds() * 1000

        return result

    async def _retrieve_mandatory(
        self,
        chapter: Chapter,
        book: Book,
        previous_summary: Optional[str],
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        if previous_summary:
            item = RetrievedItem(
                memory_type=MemoryType.PREVIOUS_SUMMARY,
                source_id=f"chapter-{chapter.chapter_number - 1}",
                content=previous_summary,
                chapter_number=chapter.chapter_number - 1,
                priority=ContentPriority.CRITICAL,
                content_type=ContentType.SUMMARY,
                original_length=len(previous_summary),
                retrieval_method=RetrievalMethod.MANDATORY,
                retrieval_reason="跨章连贯性锚点",
            )
            item.score.total_score = 1.0
            result.add_item(item)

        if book:
            book_setting = self._build_book_setting(book)
            if book_setting:
                item = RetrievedItem(
                    memory_type=MemoryType.BOOK_SETTING,
                    source_id=f"book-{book.id}",
                    content=book_setting,
                    priority=ContentPriority.CRITICAL,
                    content_type=ContentType.STRUCTURED,
                    original_length=len(book_setting),
                    retrieval_method=RetrievalMethod.MANDATORY,
                    retrieval_reason="核心设定遵循",
                )
                item.score.total_score = 1.0
                result.add_item(item)

    async def _retrieve_exact(
        self,
        chapter: Chapter,
        entities: List[ChapterEntity],
        relationships: List[CharacterRelationship],
        open_hooks: List[Dict[str, Any]],
        previous_world_state: Optional[Any],
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        for entity in entities:
            if entity.character:
                item = self._build_character_item(entity.character)
                item.score = self._scorer.compute_score(item, scoring_context)
                result.add_item(item)

        for rel in relationships:
            item = self._build_relationship_item(rel)
            item.score = self._scorer.compute_score(item, scoring_context)
            result.add_item(item)

        sorted_hooks = sorted(
            open_hooks,
            key=lambda h: {"main_plot": 3, "sub_plot": 2, "atmosphere": 1, "detail": 0}.get(
                h.get("priority", "sub_plot"), 1
            ),
            reverse=True
        )

        for hook in sorted_hooks[:10]:
            item = RetrievedItem(
                memory_type=MemoryType.OPEN_HOOK,
                source_id=hook.get("hook_id", ""),
                content=hook.get("content", ""),
                chapter_number=hook.get("chapter_number", 0),
                priority=ContentPriority.HIGH,
                content_type=ContentType.FULL_TEXT,
                original_length=len(hook.get("content", "")),
                retrieval_method=RetrievalMethod.EXACT,
                retrieval_reason="未闭合伏笔",
            )
            item.score = self._scorer.compute_score(item, scoring_context)
            result.add_item(item)

    async def _retrieve_vector(
        self,
        chapter: Chapter,
        book: Book,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
        api_key: str,
        base_url: Optional[str],
        strategy_config: RetrievalStrategyConfig,
    ) -> None:
        if not chapter.outline_text:
            return

        try:
            if self.get_embedding:
                embedding = await self.get_embedding(
                    chapter.outline_text, api_key, base_url
                )
            else:
                from backend.services.llm_client import get_embedding
                embedding = await get_embedding(
                    chapter.outline_text, api_key, base_url
                )

            if not embedding:
                return

            from backend.repositories import MemoryRepository
            memory_repo = MemoryRepository(self.db)

            chunks = await memory_repo.search_similar(
                embedding,
                book.id,
                limit=strategy_config.top_k * 2,
                alpha=strategy_config.semantic_weight,
                beta=strategy_config.time_decay_weight,
                gamma=strategy_config.foreshadowing_weight,
                lambda_decay=strategy_config.decay_factor,
                exclude_chapter_id=chapter.id,
                max_chapter_number=chapter.chapter_number - 1,
            )

            for chunk in chunks:
                item = RetrievedItem(
                    memory_type=MemoryType.MEMORY_CHUNK,
                    source_id=str(chunk.id),
                    content=chunk.chunk_text or "",
                    priority=ContentPriority.NORMAL,
                    content_type=ContentType.SUMMARY,
                    original_length=len(chunk.chunk_text or ""),
                    retrieval_method=RetrievalMethod.VECTOR,
                    retrieval_reason="语义相关记忆",
                    created_at=chunk.created_at,
                )
                item.score = self._scorer.compute_score(item, scoring_context)
                result.add_item(item)

        except Exception as e:
            logger.error(f"[WorkflowIntegrator] 向量检索失败: {e}")

    async def _retrieve_hybrid(
        self,
        chapter: Chapter,
        book: Book,
        entities: List[ChapterEntity],
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        try:
            character_names = set()
            for entity in entities:
                if entity.character and entity.character.name:
                    character_names.add(entity.character.name)

            stmt = (
                select(StoryBeat)
                .join(Chapter, StoryBeat.chapter_id == Chapter.id)
                .where(
                    Chapter.book_id == book.id,
                    Chapter.chapter_number < chapter.chapter_number,
                    Chapter.chapter_number >= chapter.chapter_number - 5,
                )
                .limit(20)
            )

            beats_result = await self.db.execute(stmt)
            beats = beats_result.scalars().all()

            for beat in beats:
                beat_summary = beat.summary or ""
                involves_current = any(
                    name.lower() in beat_summary.lower()
                    for name in character_names
                )

                if involves_current:
                    item = RetrievedItem(
                        memory_type=MemoryType.STORY_BEAT,
                        source_id=str(beat.id),
                        content=beat_summary[:200],
                        priority=ContentPriority.NORMAL,
                        content_type=ContentType.SUMMARY,
                        original_length=len(beat_summary),
                        retrieval_method=RetrievalMethod.HYBRID,
                        retrieval_reason="涉及当前角色的历史节拍",
                    )
                    item.score = self._scorer.compute_score(item, scoring_context)
                    result.add_item(item)

        except Exception as e:
            logger.error(f"[WorkflowIntegrator] 节拍检索失败: {e}")

    async def _post_process(self, result: RetrievalResult) -> None:
        seen = set()
        unique_items = []
        for item in result.items:
            key = (item.memory_type.value, item.content[:50])
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        result.items = unique_items

        result.sort_by_score()

        result.items = result.items[:30]
        result.total_items = len(result.items)

    def _handle_retrieval_failure(
        self,
        chapter_id,
        stage: WorkflowStage,
        error: str,
    ) -> Tuple[ContextPackage, RetrievalResult]:
        logger.warning(f"[WorkflowIntegrator] 检索失败，执行降级: {error}")

        result = RetrievalResult(
            query="",
            chapter_id=str(chapter_id),
            strategy_name="fallback",
        )

        if self.config.failure_mode == RetrievalFailureMode.RAISE_ERROR:
            raise RuntimeError(f"检索失败: {error}")

        if self.config.failure_mode == RetrievalFailureMode.MINIMAL_CONTEXT:
            package = ContextPackage(chapter_id=str(chapter_id))
            return package, result

        package = ContextPackage(chapter_id=str(chapter_id))
        return package, result

    def _build_book_setting(self, book: Book) -> str:
        parts = []

        if book.global_sys_prompt:
            parts.append(f"风格指南：{book.global_sys_prompt}")

        if book.core_motifs_taboos:
            parts.append(f"主题禁忌：{book.core_motifs_taboos}")

        if book.worldview_settings:
            for key, value in book.worldview_settings.items():
                parts.append(f"{key}：{value}")

        return "\n".join(parts)

    def _build_character_item(self, character: Character) -> RetrievedItem:
        content_parts = []

        if character.name:
            content_parts.append(f"【{character.name}】")

        if character.static_prompt:
            content_parts.append(character.static_prompt[:300])

        if character.dynamic_state:
            content_parts.append(f"当前状态：{character.dynamic_state[:200]}")

        return RetrievedItem(
            memory_type=MemoryType.CHARACTER_STATE,
            source_id=str(character.id),
            content="\n".join(content_parts),
            character_names=[character.name] if character.name else [],
            priority=ContentPriority.HIGH,
            content_type=ContentType.STRUCTURED,
            original_length=len("\n".join(content_parts)),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="出场角色设定",
        )

    def _build_relationship_item(self, rel: CharacterRelationship) -> RetrievedItem:
        source_name = rel.source_character.name if rel.source_character else ""
        target_name = rel.target_character.name if rel.target_character else ""

        content = f"【{source_name} ↔ {target_name}】"
        if rel.relation_type:
            content += f"\n关系：{rel.relation_type}"
        if rel.affinity_score is not None:
            content += f"\n亲密度：{rel.affinity_score}"
        if rel.interaction_prompt:
            content += f"\n互动约束：{rel.interaction_prompt[:100]}"

        return RetrievedItem(
            memory_type=MemoryType.RELATIONSHIP_STATE,
            source_id=str(rel.id),
            content=content,
            character_names=[source_name, target_name],
            priority=ContentPriority.HIGH,
            content_type=ContentType.STRUCTURED,
            original_length=len(content),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="角色关系设定",
        )

    def clear_cache(self) -> None:
        self._cache.clear()


async def integrate_retrieval_with_workflow(
    db: AsyncSession,
    chapter_id,
    stage: WorkflowStage = WorkflowStage.ASSEMBLING,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    config: Optional[WorkflowIntegrationConfig] = None,
) -> Tuple[ContextPackage, RetrievalResult]:
    integrator = WorkflowRetrievalIntegrator(db, config)
    return await integrator.retrieve_chapter_context(
        chapter_id, api_key, base_url, stage
    )


async def prepare_planning_context(
    db: AsyncSession,
    chapter_id,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ContextPackage:
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.get_context_for_planning(chapter_id, api_key, base_url)


async def prepare_drafting_context(
    db: AsyncSession,
    chapter_id,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ContextPackage:
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.get_context_for_drafting(chapter_id, api_key, base_url)


async def prepare_reviewing_context(
    db: AsyncSession,
    chapter_id,
    chapter_text: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[ContextPackage, List[Dict[str, Any]]]:
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.get_context_for_reviewing(
        chapter_id, chapter_text, api_key, base_url
    )

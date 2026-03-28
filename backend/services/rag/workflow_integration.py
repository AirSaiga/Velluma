# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
检索与生成流程协作接口 (Workflow Integration Interface)

职责：
- 将 RAG 检索系统与章节生成工作流集成
- 提供各阶段的上下文组装接口
- 处理检索失败时的降级策略
- 协调检索结果与生成流程

设计原则：
1. 检索应插入在生成流程的关键节点
2. 检索结果影响规划、起草、审阅各阶段
3. 检索失败时优雅降级
4. 提供清晰的接口边界

工作流集成点：
┌─────────────────────────────────────────────────────────────┐
│                    章节生成工作流                            │
├─────────────────────────────────────────────────────────────┤
│   1. ASSEMBLING_CONTEXT                                      │
│      └─→ retrieve_chapter_context()                          │
│          - 加载角色、关系、伏笔                              │
│          - 执行向量检索                                      │
│          - 构建完整上下文包                                  │
├─────────────────────────────────────────────────────────────┤
│   2. PLANNING                                                │
│      └─→ get_context_for_planning()                          │
│          - 提供规划所需的精简上下文                          │
│          - 包含角色状态、伏笔、世界设定                      │
├─────────────────────────────────────────────────────────────┤
│   3. DRAFTING                                                │
│      └─→ get_context_for_drafting()                          │
│          - 提供起草所需的完整上下文                          │
│          - 包含历史记忆、场景地点                            │
├─────────────────────────────────────────────────────────────┤
│   4. REVIEWING                                               │
│      └─→ get_context_for_reviewing()                         │
│          - 提供审阅所需的参考上下文                          │
│          - 检测伏笔遗漏                                      │
├─────────────────────────────────────────────────────────────┤
│   5. REFINING                                                │
│      └─→ get_context_for_refining()                          │
│          - 提供精修所需的针对性上下文                        │
│          - 基于审阅问题定向检索                              │
└─────────────────────────────────────────────────────────────┘
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Callable, Tuple
from uuid import UUID
from dataclasses import dataclass, field
from enum import Enum

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


logger = logging.getLogger(__name__)


# =============================================================================
# 工作流阶段定义
# =============================================================================

class WorkflowStage(str, Enum):
    """工作流阶段"""
    ASSEMBLING = "assembling"       # 组装上下文
    PLANNING = "planning"           # 规划
    DRAFTING = "drafting"           # 起草
    REVIEWING = "reviewing"         # 审阅
    REFINING = "refining"           # 精修
    PUBLISHING = "publishing"       # 发布


class RetrievalFailureMode(str, Enum):
    """检索失败模式"""
    GRACEFUL_DEGRADE = "graceful_degrade"   # 优雅降级
    MINIMAL_CONTEXT = "minimal_context"     # 最小上下文
    RAISE_ERROR = "raise_error"             # 抛出错误


# =============================================================================
# 工作流集成配置
# =============================================================================

@dataclass
class WorkflowIntegrationConfig:
    """工作流集成配置"""
    # 默认检索策略
    default_strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE
    
    # 各阶段策略映射
    stage_strategies: Dict[str, RetrievalStrategy] = field(default_factory=lambda: {
        WorkflowStage.ASSEMBLING.value: RetrievalStrategy.BALANCED_REFERENCE,
        WorkflowStage.PLANNING.value: RetrievalStrategy.BALANCED_REFERENCE,
        WorkflowStage.DRAFTING.value: RetrievalStrategy.BALANCED_REFERENCE,
        WorkflowStage.REVIEWING.value: RetrievalStrategy.CHARACTER_FOCUSED,
        WorkflowStage.REFINING.value: RetrievalStrategy.DEEP_DIVE,
    })
    
    # 上下文长度限制
    max_context_lengths: Dict[str, int] = field(default_factory=lambda: {
        WorkflowStage.ASSEMBLING.value: 10000,
        WorkflowStage.PLANNING.value: 6000,
        WorkflowStage.DRAFTING.value: 8000,
        WorkflowStage.REVIEWING.value: 4000,
        WorkflowStage.REFINING.value: 5000,
    })
    
    # 检索失败处理
    failure_mode: RetrievalFailureMode = RetrievalFailureMode.GRACEFUL_DEGRADE
    
    # 功能开关
    enable_vector_search: bool = True
    enable_hook_detection: bool = True
    enable_explainability: bool = True
    
    # 性能设置
    cache_retrieval_results: bool = True
    cache_ttl_seconds: int = 300  # 5分钟缓存


# =============================================================================
# 检索结果缓存
# =============================================================================

class RetrievalCache:
    """检索结果缓存"""
    
    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, Tuple[RetrievalResult, datetime]] = {}
        self._ttl = ttl_seconds
    
    def get(self, key: str) -> Optional[RetrievalResult]:
        """获取缓存"""
        if key not in self._cache:
            return None
        
        result, timestamp = self._cache[key]
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()
        
        if age > self._ttl:
            del self._cache[key]
            return None
        
        return result
    
    def set(self, key: str, result: RetrievalResult) -> None:
        """设置缓存"""
        self._cache[key] = (result, datetime.now(timezone.utc))
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()


# =============================================================================
# 工作流检索集成器
# =============================================================================

class WorkflowRetrievalIntegrator:
    """
    工作流检索集成器
    
    职责：
    - 协调检索与生成流程
    - 管理检索结果缓存
    - 处理检索失败降级
    - 提供阶段化的检索接口
    """
    
    def __init__(
        self,
        db: AsyncSession,
        config: Optional[WorkflowIntegrationConfig] = None,
        get_embedding_func: Optional[Callable] = None,
    ):
        self.db = db
        self.config = config or WorkflowIntegrationConfig()
        self.get_embedding = get_embedding_func
        
        # 初始化缓存
        self._cache = RetrievalCache(self.config.cache_ttl_seconds)
        
        # 初始化组件
        self._scorer = EnhancedRetrievalScorer()
        self._context_builder = RetrievalContextBuilder()
        self._packager = SmartContextPackager()
        self._keyword_extractor = OutlineKeywordExtractor()
    
    async def retrieve_chapter_context(
        self,
        chapter_id: UUID,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        stage: WorkflowStage = WorkflowStage.ASSEMBLING,
        force_refresh: bool = False,
    ) -> Tuple[ContextPackage, RetrievalResult]:
        """
        检索章节上下文
        
        Args:
            chapter_id: 章节 ID
            api_key: API Key
            base_url: Base URL
            stage: 工作流阶段
            force_refresh: 是否强制刷新
            
        Returns:
            Tuple[ContextPackage, RetrievalResult]: 上下文包和检索结果
        """
        cache_key = f"{chapter_id}:{stage.value}"
        
        # 检查缓存
        if not force_refresh and self.config.cache_retrieval_results:
            cached = self._cache.get(cache_key)
            if cached:
                logger.debug(f"[WorkflowIntegrator] 使用缓存结果: {cache_key}")
                package = self._packager.build(cached)
                return package, cached
        
        try:
            # 加载基础数据
            chapter, book, entities, relationships, open_hooks, previous_summary, previous_world_state = \
                await self._load_chapter_data(chapter_id)
            
            if not chapter:
                raise ValueError(f"章节不存在: {chapter_id}")
            
            # 选择策略
            strategy = self.config.stage_strategies.get(
                stage.value, self.config.default_strategy
            )
            strategy_config = STRATEGY_PRESETS.get(strategy, RetrievalStrategyConfig())
            
            # 执行检索
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
            
            # 构建上下文包
            max_length = self.config.max_context_lengths.get(stage.value, 8000)
            packager_config = PackagerConfig(max_total_length=max_length)
            self._packager = SmartContextPackager(packager_config, stage.value)
            package = self._packager.build(result)
            
            # 缓存结果
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
        chapter_id: UUID,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ContextPackage:
        """获取规划阶段上下文"""
        package, _ = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.PLANNING,
        )
        return package
    
    async def get_context_for_drafting(
        self,
        chapter_id: UUID,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ContextPackage:
        """获取起草阶段上下文"""
        package, _ = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.DRAFTING,
        )
        return package
    
    async def get_context_for_reviewing(
        self,
        chapter_id: UUID,
        chapter_text: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> Tuple[ContextPackage, List[Dict[str, Any]]]:
        """
        获取审阅阶段上下文
        
        Args:
            chapter_id: 章节 ID
            chapter_text: 章节文本
            api_key: API Key
            base_url: Base URL
            
        Returns:
            Tuple[ContextPackage, List[Dict]]: 上下文包和伏笔遗漏报告
        """
        package, result = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.REVIEWING,
        )
        
        # 检测伏笔遗漏
        omissions = []
        if self.config.enable_hook_detection:
            # 获取章节信息
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
        chapter_id: UUID,
        review_issues: List[Dict[str, Any]],
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> ContextPackage:
        """
        获取精修阶段上下文
        
        Args:
            chapter_id: 章节 ID
            review_issues: 审阅问题列表
            api_key: API Key
            base_url: Base URL
            
        Returns:
            ContextPackage: 针对性上下文包
        """
        package, result = await self.retrieve_chapter_context(
            chapter_id, api_key, base_url,
            stage=WorkflowStage.REFINING,
        )
        
        # 根据审阅问题添加针对性内容
        for issue in review_issues:
            issue_type = issue.get("type", "")
            if issue_type == "character_consistency":
                # 添加更多角色信息
                pass
            elif issue_type == "foreshadowing_omission":
                # 添加伏笔信息
                pass
        
        return package
    
    async def _load_chapter_data(
        self,
        chapter_id: UUID,
    ) -> Tuple[
        Optional[Chapter],
        Optional[Book],
        List[ChapterEntity],
        List[CharacterRelationship],
        List[Dict[str, Any]],
        Optional[str],
        Optional[Any],
    ]:
        """加载章节数据"""
        # 加载章节
        chapter_result = await self.db.execute(
            select(Chapter).where(Chapter.id == chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        
        if not chapter:
            return None, None, [], [], [], None, None
        
        # 加载书籍
        book_result = await self.db.execute(
            select(Book).where(Book.id == chapter.book_id)
        )
        book = book_result.scalar_one_or_none()
        
        # 加载角色
        entities_result = await self.db.execute(
            select(ChapterEntity)
            .options(selectinload(ChapterEntity.character))
            .where(ChapterEntity.chapter_id == chapter_id)
        )
        entities = list(entities_result.scalars().all())
        
        # 加载关系
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
        
        # 加载开放伏笔
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
        
        # 加载上一章摘要
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
        
        # 世界状态（简化）
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
        """执行检索"""
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
        
        # 构建评分上下文
        scoring_context = self._context_builder.build(
            chapter_number=chapter.chapter_number,
            outline=chapter.outline_text or "",
            entities=entities,
            relationships=relationships,
            open_hooks=open_hooks,
        )
        
        # === 强制包含 ===
        await self._retrieve_mandatory(
            chapter, book, previous_summary, result, scoring_context
        )
        
        # === 精确检索 ===
        await self._retrieve_exact(
            chapter, entities, relationships, open_hooks,
            previous_world_state, result, scoring_context
        )
        
        # === 向量检索 ===
        if self.config.enable_vector_search and api_key:
            await self._retrieve_vector(
                chapter, book, result, scoring_context, api_key, base_url, strategy_config
            )
        
        # === 混合检索 ===
        await self._retrieve_hybrid(chapter, book, entities, result, scoring_context)
        
        # === 后处理 ===
        await self._post_process(result)
        
        # 计算耗时
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
        """强制包含内容"""
        # 上一章摘要
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
        
        # 书籍设定
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
        """精确检索"""
        # 角色状态
        for entity in entities:
            if entity.character:
                item = self._build_character_item(entity.character)
                item.score = self._scorer.compute_score(item, scoring_context)
                result.add_item(item)
        
        # 关系状态
        for rel in relationships:
            item = self._build_relationship_item(rel)
            item.score = self._scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 开放伏笔
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
        """向量检索"""
        if not chapter.outline_text:
            return
        
        try:
            # 获取查询向量
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
            
            # 执行向量检索
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
        """混合检索"""
        # 故事节拍
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
        """后处理"""
        # 去重
        seen = set()
        unique_items = []
        for item in result.items:
            key = (item.memory_type.value, item.content[:50])
            if key not in seen:
                seen.add(key)
                unique_items.append(item)
        
        result.items = unique_items
        
        # 排序
        result.sort_by_score()
        
        # 截断
        result.items = result.items[:30]
        result.total_items = len(result.items)
    
    def _handle_retrieval_failure(
        self,
        chapter_id: UUID,
        stage: WorkflowStage,
        error: str,
    ) -> Tuple[ContextPackage, RetrievalResult]:
        """处理检索失败"""
        logger.warning(f"[WorkflowIntegrator] 检索失败，执行降级: {error}")
        
        # 创建空的检索结果
        result = RetrievalResult(
            query="",
            chapter_id=str(chapter_id),
            strategy_name="fallback",
        )
        
        if self.config.failure_mode == RetrievalFailureMode.RAISE_ERROR:
            raise RuntimeError(f"检索失败: {error}")
        
        # 优雅降级或最小上下文
        if self.config.failure_mode == RetrievalFailureMode.MINIMAL_CONTEXT:
            # 创建最小上下文包
            package = ContextPackage(chapter_id=str(chapter_id))
            return package, result
        
        # 优雅降级：返回空结果
        package = ContextPackage(chapter_id=str(chapter_id))
        return package, result
    
    def _build_book_setting(self, book: Book) -> str:
        """构建书籍设定"""
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
        """构建角色检索项"""
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
        """构建关系检索项"""
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
        """清空缓存"""
        self._cache.clear()


# =============================================================================
# 便捷函数
# =============================================================================

async def integrate_retrieval_with_workflow(
    db: AsyncSession,
    chapter_id: UUID,
    stage: WorkflowStage = WorkflowStage.ASSEMBLING,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    config: Optional[WorkflowIntegrationConfig] = None,
) -> Tuple[ContextPackage, RetrievalResult]:
    """
    便捷函数：将检索集成到工作流
    
    Args:
        db: 数据库会话
        chapter_id: 章节 ID
        stage: 工作流阶段
        api_key: API Key
        base_url: Base URL
        config: 集成配置
        
    Returns:
        Tuple[ContextPackage, RetrievalResult]: 上下文包和检索结果
    """
    integrator = WorkflowRetrievalIntegrator(db, config)
    return await integrator.retrieve_chapter_context(
        chapter_id, api_key, base_url, stage
    )


async def prepare_planning_context(
    db: AsyncSession,
    chapter_id: UUID,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ContextPackage:
    """便捷函数：准备规划阶段上下文"""
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.get_context_for_planning(chapter_id, api_key, base_url)


async def prepare_drafting_context(
    db: AsyncSession,
    chapter_id: UUID,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ContextPackage:
    """便捷函数：准备起草阶段上下文"""
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.get_context_for_drafting(chapter_id, api_key, base_url)


async def prepare_reviewing_context(
    db: AsyncSession,
    chapter_id: UUID,
    chapter_text: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[ContextPackage, List[Dict[str, Any]]]:
    """便捷函数：准备审阅阶段上下文"""
    integrator = WorkflowRetrievalIntegrator(db)
    return await integrator.get_context_for_reviewing(
        chapter_id, chapter_text, api_key, base_url
    )

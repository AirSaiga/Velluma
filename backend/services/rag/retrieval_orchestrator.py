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

设计原则：
1. 分层检索：强制包含 → 精确检索 → 向量检索 → 混合检索
2. 目标导向：基于章节大纲和目标优化检索
3. 优先召回：角色状态和伏笔优先处理
4. 降级策略：检索失败时优雅降级

检索流程：
┌─────────────────────────────────────────────────────────────┐
│                    1. 初始化检索上下文                        │
│   - 解析章节大纲关键词                                        │
│   - 识别出场角色和关系                                        │
│   - 收集开放伏笔                                              │
├─────────────────────────────────────────────────────────────┤
│                    2. 强制包含内容                            │
│   - 上一章摘要 (CRITICAL)                                     │
│   - 书籍核心设定 (CRITICAL)                                   │
├─────────────────────────────────────────────────────────────┤
│                    3. 精确检索                                │
│   - 出场角色状态 (HIGH)                                       │
│   - 角色关系状态 (HIGH)                                       │
│   - 开放伏笔列表 (HIGH)                                       │
│   - 世界状态快照 (HIGH)                                       │
├─────────────────────────────────────────────────────────────┤
│                    4. 向量检索                                │
│   - 历史记忆切片 (NORMAL)                                     │
│   - 基于大纲语义相似度                                        │
├─────────────────────────────────────────────────────────────┤
│                    5. 混合检索                                │
│   - 相关故事节拍                                              │
│   - 场景地点信息                                              │
├─────────────────────────────────────────────────────────────┤
│                    6. 后处理                                  │
│   - 去重                                                      │
│   - 排序                                                      │
│   - 截断                                                      │
│   - 生成可解释报告                                            │
└─────────────────────────────────────────────────────────────┘
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Callable, Tuple
from uuid import UUID
from enum import Enum

from sqlalchemy import select, or_, and_, desc
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
    SceneIntent,
    ChapterMapLocation,
    MapLocation,
)
from backend.repositories import MemoryRepository

from backend.services.rag.retrieval_types import (
    MemoryType,
    MemoryTypeConfig,
    RetrievalMethod,
    ContentPriority,
    ContentType,
    RetrievedItem,
    RetrievalResult,
    RetrievalScore,
    RetrievalStrategyConfig,
    RetrievalStrategy,
    STRATEGY_PRESETS,
    ContextSection,
    ContextPackage,
)
from backend.services.rag.enhanced_scoring import (
    EnhancedScoringConfig,
    EnhancedRetrievalScorer,
    RetrievalContextBuilder,
    OutlineKeywordExtractor,
)


logger = logging.getLogger(__name__)


# =============================================================================
# 检索阶段定义
# =============================================================================

class RetrievalPhase(str, Enum):
    """检索阶段"""
    MANDATORY = "mandatory"     # 强制包含
    EXACT = "exact"             # 精确检索
    VECTOR = "vector"           # 向量检索
    HYBRID = "hybrid"           # 混合检索
    POST_PROCESS = "post_process"  # 后处理


# =============================================================================
# 检索配置
# =============================================================================

class RetrievalOrchestratorConfig:
    """
    检索协调器配置
    
    控制检索行为和限制
    """
    
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
        
        # 加载策略预设
        self.strategy_config = STRATEGY_PRESETS.get(
            strategy, RetrievalStrategyConfig()
        )


# =============================================================================
# 检索协调器
# =============================================================================

class RetrievalOrchestrator:
    """
    检索协调器
    
    职责：
    - 协调多类型记忆检索
    - 分层执行检索流程
    - 管理检索结果合并
    - 提供可解释性报告
    """
    
    def __init__(
        self,
        db: AsyncSession,
        config: Optional[RetrievalOrchestratorConfig] = None,
        get_embedding_func: Optional[Callable] = None,
    ):
        self.db = db
        self.config = config or RetrievalOrchestratorConfig()
        self.get_embedding = get_embedding_func
        
        # 初始化组件
        self.scorer = EnhancedRetrievalScorer(
            EnhancedScoringConfig.from_strategy(self.config.strategy_config)
        )
        self.context_builder = RetrievalContextBuilder()
        self.outline_extractor = OutlineKeywordExtractor()
        
        # 追踪检索过程
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
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> RetrievalResult:
        """
        执行完整检索流程
        
        Args:
            chapter: 目标章节
            book: 书籍
            entities: 出场角色实体
            relationships: 角色关系
            open_hooks: 开放伏笔
            previous_summary: 上一章摘要
            previous_world_state: 世界状态快照
            api_key: API Key（用于向量检索）
            base_url: Base URL
            
        Returns:
            RetrievalResult: 检索结果
        """
        start_time = datetime.now(timezone.utc)
        self._retrieval_trace = []
        
        # 初始化结果
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
        
        # 构建评分上下文
        scoring_context = self.context_builder.build(
            chapter_number=chapter.chapter_number,
            outline=chapter.outline_text or "",
            entities=entities,
            relationships=relationships,
            open_hooks=open_hooks,
        )
        
        # === 阶段 1: 强制包含 ===
        await self._retrieve_mandatory(
            chapter, book, previous_summary, result, scoring_context
        )
        self._trace_phase(RetrievalPhase.MANDATORY, result.total_items)
        
        # === 阶段 2: 精确检索 ===
        await self._retrieve_exact(
            chapter, entities, relationships, open_hooks,
            previous_world_state, result, scoring_context
        )
        self._trace_phase(RetrievalPhase.EXACT, result.total_items)
        
        # === 阶段 3: 向量检索 ===
        if self.config.enable_vector_search and api_key:
            await self._retrieve_vector(
                chapter, book, result, scoring_context, api_key, base_url
            )
        self._trace_phase(RetrievalPhase.VECTOR, result.total_items)
        
        # === 阶段 4: 混合检索 ===
        await self._retrieve_hybrid(chapter, book, entities, result, scoring_context)
        self._trace_phase(RetrievalPhase.HYBRID, result.total_items)
        
        # === 阶段 5: 后处理 ===
        await self._post_process(result, scoring_context)
        self._trace_phase(RetrievalPhase.POST_PROCESS, result.total_items)
        
        # 计算耗时
        end_time = datetime.now(timezone.utc)
        result.retrieval_time_ms = (end_time - start_time).total_seconds() * 1000
        
        logger.info(
            f"[RetrievalOrchestrator] 检索完成: "
            f"章节 {chapter.chapter_number}, "
            f"{result.total_items} 项, "
            f"耗时 {result.retrieval_time_ms:.1f}ms"
        )
        
        return result
    
    async def _retrieve_mandatory(
        self,
        chapter: Chapter,
        book: Book,
        previous_summary: Optional[str],
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """强制包含内容检索"""
        
        # 1. 上一章摘要
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
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 2. 书籍核心设定
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
        
        # 1. 角色状态
        for entity in entities:
            if entity.character:
                item = self._build_character_item(entity.character)
                item.score = self.scorer.compute_score(item, scoring_context)
                result.add_item(item)
        
        # 2. 关系状态
        for rel in relationships:
            item = self._build_relationship_item(rel)
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 3. 开放伏笔（按优先级排序）
        sorted_hooks = sorted(
            open_hooks,
            key=lambda h: h.get("priority", "sub_plot"),
            reverse=True
        )
        
        for hook in sorted_hooks[:self.config.max_items_per_type]:
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
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 4. 世界状态快照
        if previous_world_state:
            item = self._build_world_snapshot_item(
                previous_world_state, chapter.chapter_number
            )
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
    
    async def _retrieve_vector(
        self,
        chapter: Chapter,
        book: Book,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
        api_key: str,
        base_url: Optional[str],
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
            memory_repo = MemoryRepository(self.db)
            config = self.config.strategy_config
            
            chunks = await memory_repo.search_similar(
                embedding,
                book.id,
                limit=config.top_k * 2,  # 获取更多候选
                alpha=config.semantic_weight,
                beta=config.time_decay_weight,
                gamma=config.foreshadowing_weight,
                lambda_decay=config.decay_factor,
                exclude_chapter_id=chapter.id,
                max_chapter_number=chapter.chapter_number - 1,
            )
            
            # 转换为检索项
            for chunk in chunks:
                item = RetrievedItem(
                    memory_type=MemoryType.MEMORY_CHUNK,
                    source_id=str(chunk.id),
                    content=chunk.chunk_text or "",
                    chapter_number=self._get_chapter_number(chunk),
                    priority=ContentPriority.NORMAL,
                    content_type=ContentType.SUMMARY,
                    original_length=len(chunk.chunk_text or ""),
                    retrieval_method=RetrievalMethod.VECTOR,
                    retrieval_reason="语义相关记忆",
                    created_at=chunk.created_at,
                )
                item.score = self.scorer.compute_score(item, scoring_context)
                result.add_item(item)
                
        except Exception as e:
            logger.error(f"[RetrievalOrchestrator] 向量检索失败: {e}")
    
    async def _retrieve_hybrid(
        self,
        chapter: Chapter,
        book: Book,
        entities: List[ChapterEntity],
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """混合检索"""
        
        # 1. 相关故事节拍
        await self._retrieve_relevant_beats(chapter, book, entities, result, scoring_context)
        
        # 2. 场景地点
        await self._retrieve_locations(chapter, result, scoring_context)
    
    async def _retrieve_relevant_beats(
        self,
        chapter: Chapter,
        book: Book,
        entities: List[ChapterEntity],
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """检索相关故事节拍"""
        
        try:
            # 提取出场角色名称
            character_names = set()
            for entity in entities:
                if entity.character and entity.character.name:
                    character_names.add(entity.character.name)
            
            # 查询前5章的节拍
            stmt = (
                select(StoryBeat)
                .join(Chapter, StoryBeat.chapter_id == Chapter.id)
                .where(
                    Chapter.book_id == book.id,
                    Chapter.chapter_number < chapter.chapter_number,
                    Chapter.chapter_number >= chapter.chapter_number - 5,
                )
                .order_by(desc(Chapter.chapter_number))
                .limit(30)
            )
            
            beats_result = await self.db.execute(stmt)
            beats = beats_result.scalars().all()
            
            for beat in beats:
                beat_summary = beat.summary or ""
                
                # 检查是否涉及当前章节角色
                involves_current_chars = any(
                    name.lower() in beat_summary.lower()
                    for name in character_names
                )
                
                # 检查 POV 角色是否在当前章节
                pov_in_current = beat.pov_character in character_names if beat.pov_character else False
                
                if involves_current_chars or pov_in_current:
                    item = RetrievedItem(
                        memory_type=MemoryType.STORY_BEAT,
                        source_id=str(beat.id),
                        content=beat_summary[:200],
                        chapter_number=self._get_beat_chapter_number(beat),
                        character_names=[beat.pov_character] if beat.pov_character else [],
                        priority=ContentPriority.NORMAL,
                        content_type=ContentType.SUMMARY,
                        original_length=len(beat_summary),
                        retrieval_method=RetrievalMethod.HYBRID,
                        retrieval_reason="涉及当前角色的历史节拍",
                    )
                    item.score = self.scorer.compute_score(item, scoring_context)
                    result.add_item(item)
                    
        except Exception as e:
            logger.error(f"[RetrievalOrchestrator] 节拍检索失败: {e}")
    
    async def _retrieve_locations(
        self,
        chapter: Chapter,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """检索场景地点"""
        
        try:
            stmt = (
                select(ChapterMapLocation)
                .options(selectinload(ChapterMapLocation.location))
                .where(ChapterMapLocation.chapter_id == chapter.id)
            )
            
            locations_result = await self.db.execute(stmt)
            locations = locations_result.scalars().all()
            
            for loc in locations:
                if loc.location:
                    item = RetrievedItem(
                        memory_type=MemoryType.MAP_LOCATION,
                        source_id=str(loc.id),
                        content=loc.location.description or loc.location.name,
                        location_names=[loc.location.name],
                        priority=ContentPriority.LOW,
                        content_type=ContentType.STRUCTURED,
                        original_length=len(loc.location.description or ""),
                        retrieval_method=RetrievalMethod.HYBRID,
                        retrieval_reason="章节场景地点",
                    )
                    item.score = self.scorer.compute_score(item, scoring_context)
                    result.add_item(item)
                    
        except Exception as e:
            logger.error(f"[RetrievalOrchestrator] 地点检索失败: {e}")
    
    async def _post_process(
        self,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """后处理：去重、排序、截断"""
        
        # 1. 去重
        if self.config.enable_dedup:
            result.items = self._deduplicate(result.items)
        
        # 2. 排序
        result.items = self._sort_items(result.items)
        
        # 3. 截断
        result.items = result.items[:self.config.max_items]
        
        # 4. 更新统计
        result.total_items = len(result.items)
        result.by_type = {}
        result.by_priority = {}
        
        for item in result.items:
            type_key = item.memory_type.value
            result.by_type[type_key] = result.by_type.get(type_key, 0) + 1
            
            priority_key = item.priority.value
            result.by_priority[priority_key] = result.by_priority.get(priority_key, 0) + 1
    
    def _deduplicate(self, items: List[RetrievedItem]) -> List[RetrievedItem]:
        """去重"""
        seen_content: Set[str] = set()
        unique_items: List[RetrievedItem] = []
        
        for item in items:
            content_key = item.content.strip().lower()[:100]
            
            if content_key not in seen_content:
                seen_content.add(content_key)
                unique_items.append(item)
        
        return unique_items
    
    def _sort_items(self, items: List[RetrievedItem]) -> List[RetrievedItem]:
        """排序"""
        priority_order = {
            "critical": 0,
            "high": 1,
            "normal": 2,
            "low": 3,
        }
        
        return sorted(
            items,
            key=lambda x: (
                priority_order.get(x.priority.value, 2),
                -x.score.total_score,
                -(x.chapter_number or 0),
            )
        )
    
    def _build_book_setting(self, book: Book) -> str:
        """构建书籍设定内容"""
        parts = []
        
        if book.global_sys_prompt:
            parts.append(f"风格指南：{book.global_sys_prompt}")
        
        if book.core_motifs_taboos:
            parts.append(f"主题禁忌：{book.core_motifs_taboos}")
        
        if book.worldview_settings:
            world_info = book.worldview_settings
            if isinstance(world_info, dict):
                for key, value in world_info.items():
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
    
    def _build_world_snapshot_item(
        self,
        world_state: Any,
        chapter_number: int,
    ) -> RetrievedItem:
        """构建世界快照检索项"""
        content_parts = ["=== 前一章世界状态 ==="]
        
        # 场景信息
        if hasattr(world_state, "scene") and world_state.scene:
            scene = world_state.scene
            if hasattr(scene, "location_summary"):
                content_parts.append(f"场景：{scene.location_summary}")
        
        # 角色状态
        if hasattr(world_state, "characters") and world_state.characters:
            content_parts.append("角色状态：")
            for char_state in world_state.characters[:5]:
                if hasattr(char_state, "name"):
                    state_str = f"  - {char_state.name}"
                    if hasattr(char_state, "location"):
                        state_str += f" @ {char_state.location}"
                    content_parts.append(state_str)
        
        return RetrievedItem(
            memory_type=MemoryType.WORLD_SNAPSHOT,
            source_id=f"world-{chapter_number - 1}",
            content="\n".join(content_parts),
            priority=ContentPriority.HIGH,
            content_type=ContentType.STRUCTURED,
            original_length=len("\n".join(content_parts)),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="世界状态连续性",
        )
    
    def _get_chapter_number(self, chunk: MemoryChunk) -> int:
        """获取记忆块对应的章节号"""
        # 简化实现，实际应查询
        return 0
    
    def _get_beat_chapter_number(self, beat: StoryBeat) -> int:
        """获取节拍对应的章节号"""
        # 通过 chapter 关系获取
        if beat.chapter:
            return beat.chapter.chapter_number
        return 0
    
    def _trace_phase(self, phase: RetrievalPhase, item_count: int) -> None:
        """记录检索阶段"""
        self._retrieval_trace.append({
            "phase": phase.value,
            "item_count": item_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    
    def get_retrieval_trace(self) -> List[Dict[str, Any]]:
        """获取检索追踪记录"""
        return self._retrieval_trace.copy()


# =============================================================================
# 便捷函数
# =============================================================================

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
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> RetrievalResult:
    """
    便捷函数：执行完整检索
    
    Args:
        chapter: 目标章节
        book: 书籍
        db: 数据库会话
        entities: 出场角色
        relationships: 角色关系
        open_hooks: 开放伏笔
        previous_summary: 上一章摘要
        previous_world_state: 世界快照
        strategy: 检索策略
        api_key: API Key
        base_url: Base URL
        
    Returns:
        RetrievalResult: 检索结果
    """
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
        api_key=api_key,
        base_url=base_url,
    )

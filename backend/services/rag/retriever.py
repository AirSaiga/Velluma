# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
多类型记忆检索器 (Multi-Type Memory Retriever)

职责：
- 统一检索多种类型的记忆
- 协调向量检索、精确检索和混合检索
- 组装完整的检索结果
- 提供与章节生成流程的接口

设计原则：
1. 按类型选择最优检索方法
2. 优先加载必须包含的内容
3. 按需加载可选内容
4. 支持检索失败降级

迁移说明 (2026-03-30)：
- 已移除废弃的 db 参数，强制使用 repositories
- 所有数据库操作通过 Repository 执行
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Callable, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select, or_, and_
from sqlalchemy.orm import selectinload

if TYPE_CHECKING:
    from backend.repositories.memory_repository import MemoryRepository

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
)
from backend.services.rag.scoring import (
    MultiDimensionScorer,
    ScoringConfig,
    MemoryDeduplicator,
    RetrievalSorter,
)
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
)

logger = logging.getLogger(__name__)


# =============================================================================
# 检索上下文
# =============================================================================

class RetrievalContext:
    """检索上下文"""
    
    def __init__(
        self,
        chapter: Chapter,
        book: Book,
        entities: List[ChapterEntity],
        relationships: List[CharacterRelationship],
        open_hooks: List[Dict],
        previous_summary: Optional[str],
        previous_world_state: Optional[Any],
        strategy_config: RetrievalStrategyConfig,
    ):
        self.chapter = chapter
        self.book = book
        self.entities = entities
        self.relationships = relationships
        self.open_hooks = open_hooks
        self.previous_summary = previous_summary
        self.previous_world_state = previous_world_state
        self.strategy_config = strategy_config
        
        # 预计算的上下文信息
        self.character_names: List[str] = []
        self.relationship_pairs: List[tuple] = []
        self.location_names: List[str] = []
        
        self._precompute()
    
    def _precompute(self) -> None:
        """预计算上下文信息"""
        # 角色名称列表
        for entity in self.entities:
            if entity.character:
                self.character_names.append(entity.character.name)
        
        # 关系对列表
        for rel in self.relationships:
            if rel.source_character and rel.target_character:
                self.relationship_pairs.append((
                    rel.source_character.name,
                    rel.target_character.name,
                ))
    
    def get_scoring_context(self) -> Dict[str, Any]:
        """获取评分上下文"""
        return {
            "chapter_number": self.chapter.chapter_number,
            "character_names": self.character_names,
            "relationship_pairs": self.relationship_pairs,
            "open_hooks": self.open_hooks,
        }


# =============================================================================
# 多类型记忆检索器
# =============================================================================

class MultiTypeMemoryRetriever:
    """
    多类型记忆检索器
    
    职责：
    - 协调多种记忆类型的检索
    - 统一评分和排序
    - 去重和过滤
    - 组装完整结果
    
    迁移说明 (2026-03-30)：
    - 已移除废弃的 db 参数，强制使用 repositories
    - 所有数据库操作通过 Repository 执行
    """
    
    def __init__(
        self,
        memory_repository: "MemoryRepository",
        chapter_repository: Optional["Any"] = None,
        get_embedding_func: Optional[Callable] = None,
    ):
        self._memory_repo = memory_repository
        self._chapter_repo = chapter_repository
        self.get_embedding = get_embedding_func
        self.scorer = MultiDimensionScorer()
        self.deduplicator = MemoryDeduplicator()
        self.sorter = RetrievalSorter()
    
    async def retrieve(
        self,
        context: RetrievalContext,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> RetrievalResult:
        """
        执行多类型检索
        
        Args:
            context: 检索上下文
            api_key: API Key（用于向量检索）
            base_url: Base URL
        
        Returns:
            RetrievalResult: 检索结果
        """
        start_time = datetime.now(timezone.utc)
        
        result = RetrievalResult(
            query=context.chapter.outline_text or "",
            chapter_id=str(context.chapter.id),
            chapter_number=context.chapter.chapter_number,
            strategy_name=context.strategy_config.strategy_name.value,
            strategy_params={
                "top_k": context.strategy_config.top_k,
                "semantic_weight": context.strategy_config.semantic_weight,
                "time_decay_weight": context.strategy_config.time_decay_weight,
                "foreshadowing_weight": context.strategy_config.foreshadowing_weight,
            },
        )
        
        scoring_context = context.get_scoring_context()
        
        # 1. 检索必须包含的内容
        await self._retrieve_mandatory(context, result, scoring_context)
        
        # 2. 精确检索
        await self._retrieve_exact(context, result, scoring_context)
        
        # 3. 向量检索
        if api_key:
            await self._retrieve_vector(
                context, result, scoring_context,
                api_key, base_url
            )
        
        # 4. 混合检索
        await self._retrieve_hybrid(context, result, scoring_context)
        
        # 5. 去重
        if context.strategy_config.enable_dedup:
            result.items = self.deduplicator.deduplicate(result.items)
        
        # 6. 排序
        result.items = self.sorter.sort(result.items)
        
        # 7. 截断
        result.items = result.items[:context.strategy_config.top_k * 3]
        
        # 8. 更新统计
        result.total_items = len(result.items)
        result.by_type = {}
        result.by_priority = {}
        
        for item in result.items:
            type_key = item.memory_type.value
            result.by_type[type_key] = result.by_type.get(type_key, 0) + 1
            
            priority_key = item.priority.value
            result.by_priority[priority_key] = result.by_priority.get(priority_key, 0) + 1
        
        # 计算耗时
        end_time = datetime.now(timezone.utc)
        result.retrieval_time_ms = (end_time - start_time).total_seconds() * 1000
        
        logger.info(
            f"[MultiTypeRetriever] 检索完成: "
            f"{result.total_items} 项, "
            f"耗时 {result.retrieval_time_ms:.1f}ms"
        )
        
        return result
    
    async def _retrieve_mandatory(
        self,
        context: RetrievalContext,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """检索必须包含的内容"""
        
        # 1. 上一章摘要
        if context.previous_summary:
            item = RetrievedItem(
                memory_type=MemoryType.PREVIOUS_SUMMARY,
                source_id=f"chapter-{context.chapter.chapter_number - 1}",
                content=context.previous_summary,
                chapter_number=context.chapter.chapter_number - 1,
                priority=ContentPriority.CRITICAL,
                content_type=ContentType.SUMMARY,
                original_length=len(context.previous_summary),
                retrieval_method=RetrievalMethod.MANDATORY,
                retrieval_reason="跨章连贯性锚点",
            )
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 2. 书籍设定
        book_setting = self._build_book_setting(context.book)
        if book_setting:
            item = RetrievedItem(
                memory_type=MemoryType.BOOK_SETTING,
                source_id=f"book-{context.book.id}",
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
        context: RetrievalContext,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """精确检索"""
        
        # 1. 角色状态
        for entity in context.entities:
            if entity.character:
                item = self._build_character_item(entity.character)
                item.score = self.scorer.compute_score(item, scoring_context)
                result.add_item(item)
        
        # 2. 关系状态
        for rel in context.relationships:
            item = self._build_relationship_item(rel)
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 3. 开放伏笔
        for hook in context.open_hooks:
            item = RetrievedItem(
                memory_type=MemoryType.OPEN_HOOK,
                source_id=hook.get("hook_id", ""),
                content=hook.get("content", ""),
                priority=ContentPriority.HIGH,
                content_type=ContentType.FULL_TEXT,
                original_length=len(hook.get("content", "")),
                retrieval_method=RetrievalMethod.EXACT,
                retrieval_reason="未闭合伏笔",
            )
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
        
        # 4. 世界快照
        if context.previous_world_state:
            item = self._build_world_snapshot_item(context.previous_world_state)
            item.score = self.scorer.compute_score(item, scoring_context)
            result.add_item(item)
    
    async def _retrieve_vector(
        self,
        context: RetrievalContext,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
        api_key: str,
        base_url: Optional[str],
    ) -> None:
        """向量检索"""
        
        if not context.chapter.outline_text:
            return
        
        try:
            # 获取查询向量
            if self.get_embedding:
                embedding = await self.get_embedding(
                    context.chapter.outline_text,
                    api_key,
                    base_url
                )
            else:
                from backend.services.llm import get_embedding
                embedding = await get_embedding(
                    context.chapter.outline_text,
                    api_key,
                    base_url
                )
            
            if not embedding:
                return
            
            # 执行向量检索
            memory_repo = MemoryRepository(self.db)
            config = context.strategy_config
            
            chunks = await memory_repo.search_similar(
                embedding,
                context.book.id,
                limit=config.top_k,
                alpha=config.semantic_weight,
                beta=config.time_decay_weight,
                gamma=config.foreshadowing_weight,
                lambda_decay=config.decay_factor,
                exclude_chapter_id=context.chapter.id,
                max_chapter_number=context.chapter.chapter_number - 1,
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
                
                # 评分上下文添加语义相似度
                chunk_context = scoring_context.copy()
                # 从内存仓库获取相似度信息（简化）
                
                item.score = self.scorer.compute_score(item, chunk_context)
                result.add_item(item)
                
        except Exception as e:
            logger.error(f"[MultiTypeRetriever] 向量检索失败: {e}")
    
    async def _retrieve_hybrid(
        self,
        context: RetrievalContext,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """混合检索"""
        
        # 1. 检索相关故事节拍
        await self._retrieve_relevant_beats(context, result, scoring_context)
        
        # 2. 检索相关地点
        await self._retrieve_locations(context, result, scoring_context)
    
    async def _retrieve_relevant_beats(
        self,
        context: RetrievalContext,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """检索相关故事节拍"""
        
        if not self._chapter_repo:
            logger.warning("[MultiTypeRetriever] ChapterRepository 未配置，跳过节拍检索")
            return
        
        try:
            stmt = (
                select(StoryBeat)
                .join(Chapter, StoryBeat.chapter_id == Chapter.id)
                .where(
                    Chapter.book_id == context.book.id,
                    Chapter.chapter_number < context.chapter.chapter_number,
                    Chapter.chapter_number >= context.chapter.chapter_number - 5,
                )
                .order_by(Chapter.chapter_number.desc())
                .limit(20)
            )
            
            beats_result = await self._chapter_repo.execute(stmt)
            beats = beats_result.scalars().all()
            
            for beat in beats:
                beat_summary = beat.summary or ""
                involves_current_chars = any(
                    name.lower() in beat_summary.lower()
                    for name in context.character_names
                )
                
                if involves_current_chars or beat.pov_character in context.character_names:
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
            logger.error(f"[MultiTypeRetriever] 节拍检索失败: {e}")
    
    async def _retrieve_locations(
        self,
        context: RetrievalContext,
        result: RetrievalResult,
        scoring_context: Dict[str, Any],
    ) -> None:
        """检索相关地点"""
        
        if not self._chapter_repo:
            logger.warning("[MultiTypeRetriever] ChapterRepository 未配置，跳过地点检索")
            return
        
        try:
            stmt = (
                select(ChapterMapLocation)
                .options(selectinload(ChapterMapLocation.location))
                .where(ChapterMapLocation.chapter_id == context.chapter.id)
            )
            
            locations_result = await self._chapter_repo.execute(stmt)
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
            logger.error(f"[MultiTypeRetriever] 地点检索失败: {e}")
    
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
    
    def _build_world_snapshot_item(self, world_state: Any) -> RetrievedItem:
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
            source_id=f"world-{self.chapter.chapter_number - 1}" if hasattr(self, "chapter") else "world-0",
            content="\n".join(content_parts),
            priority=ContentPriority.HIGH,
            content_type=ContentType.STRUCTURED,
            original_length=len("\n".join(content_parts)),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="世界状态连续性",
        )
    
    def _get_chapter_number(self, chunk: MemoryChunk) -> int:
        """获取记忆块对应的章节号"""
        if chunk.chapter_id:
            try:
                # 简化：直接查询
                return 0  # 实际应查询章节号
            except Exception:
                pass
        return 0
    
    def _get_beat_chapter_number(self, beat: StoryBeat) -> int:
        """获取节拍对应的章节号"""
        return 0  # 实际应关联查询


# =============================================================================
# 便捷函数
# =============================================================================

async def retrieve_chapter_memories(
    chapter: Chapter,
    book: Book,
    db: AsyncSession,
    entities: List[ChapterEntity],
    relationships: List[CharacterRelationship],
    open_hooks: List[Dict],
    previous_summary: Optional[str],
    previous_world_state: Optional[Any],
    strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> RetrievalResult:
    """
    便捷函数：检索章节相关记忆
    
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
    strategy_config = STRATEGY_PRESETS.get(strategy, RetrievalStrategyConfig())
    
    context = RetrievalContext(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        open_hooks=open_hooks,
        previous_summary=previous_summary,
        previous_world_state=previous_world_state,
        strategy_config=strategy_config,
    )
    
    retriever = MultiTypeMemoryRetriever(db)
    return await retriever.retrieve(context, api_key, base_url)

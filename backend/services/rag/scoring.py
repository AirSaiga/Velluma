# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
RAG 评分系统 (RAG Scoring System)

职责：
- 计算多维度检索得分
- 实现时间衰减策略
- 实现伏笔关联评分
- 实现角色/关系相关度评分
- 提供可解释的得分分解

设计原则：
1. 得分可分解为各维度贡献
2. 每个维度有独立的权重可调节
3. 支持小说叙事场景的特殊需求
"""

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass

from backend.services.rag.retrieval_types import (
    RetrievalScore,
    RetrievedItem,
    MemoryType,
    RetrievalStrategyConfig,
)


# =============================================================================
# 评分器配置
# =============================================================================

@dataclass
class ScoringConfig:
    """评分配置"""
    # 基础权重
    semantic_weight: float = 0.6
    time_decay_weight: float = 0.2
    foreshadowing_weight: float = 0.2
    
    # 时间衰减参数
    decay_factor: float = 0.1
    chapter_proximity_bonus: float = 0.1
    
    # 角色相关度参数
    character_match_bonus: float = 0.15
    relationship_match_bonus: float = 0.1
    
    # 伏笔相关度参数
    open_hook_bonus: float = 0.3
    hook_character_bonus: float = 0.1
    
    # 类型权重
    type_weights: Dict[str, float] = None
    
    def __post_init__(self):
        if self.type_weights is None:
            self.type_weights = {
                "character_state": 1.5,
                "relationship_state": 1.3,
                "open_hook": 1.4,
                "memory_chunk": 1.0,
                "world_snapshot": 1.2,
            }
    
    @classmethod
    def from_strategy(cls, strategy: RetrievalStrategyConfig) -> "ScoringConfig":
        """从策略配置创建"""
        return cls(
            semantic_weight=strategy.semantic_weight,
            time_decay_weight=strategy.time_decay_weight,
            foreshadowing_weight=strategy.foreshadowing_weight,
            decay_factor=strategy.decay_factor,
            type_weights=strategy.type_weights,
        )


# =============================================================================
# 多维度评分器
# =============================================================================

class MultiDimensionScorer:
    """
    多维度评分器
    
    计算公式：
    total_score = 
        w_semantic * semantic_score +
        w_time * time_decay_score +
        w_foreshadowing * foreshadowing_score +
        character_relevance_bonus +
        type_weight * base_score
    
    其中各分量的计算方式：
    - semantic_score: 向量相似度 (0-1)
    - time_decay_score: exp(-decay_factor * delta_days)
    - foreshadowing_score: 与开放伏笔的关联度
    - character_relevance: 与出场角色的匹配度
    """
    
    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self._now = datetime.now(timezone.utc)
    
    def compute_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> RetrievalScore:
        """
        计算检索项得分
        
        Args:
            item: 检索项
            context: 评分上下文，包含：
                - chapter_number: 当前章节号
                - character_names: 出场角色名列表
                - relationship_pairs: 角色关系对列表
                - open_hooks: 开放伏笔列表
                - semantic_similarity: 语义相似度（如有）
        
        Returns:
            RetrievalScore: 得分详情
        """
        score = RetrievalScore()
        
        # 1. 语义相似度得分
        semantic = self._compute_semantic_score(item, context)
        score.semantic_score = semantic
        
        # 2. 时间衰减得分
        time_decay = self._compute_time_decay_score(item, context)
        score.time_decay_score = time_decay
        
        # 3. 伏笔关联得分
        foreshadowing = self._compute_foreshadowing_score(item, context)
        score.foreshadowing_score = foreshadowing
        
        # 4. 角色相关度得分
        character_rel = self._compute_character_relevance_score(item, context)
        score.character_relevance_score = character_rel
        
        # 5. 章节接近度得分
        chapter_prox = self._compute_chapter_proximity_score(item, context)
        score.chapter_proximity_score = chapter_prox
        
        # 6. 计算加权总分
        base_score = (
            self.config.semantic_weight * semantic +
            self.config.time_decay_weight * time_decay +
            self.config.foreshadowing_weight * foreshadowing
        )
        
        # 7. 添加额外加成
        bonus = character_rel + chapter_prox
        
        # 8. 应用类型权重
        type_weight = self.config.type_weights.get(
            item.memory_type.value, 1.0
        )
        
        # 9. 最终得分
        total = (base_score + bonus) * type_weight
        score.total_score = min(1.0, max(0.0, total))
        
        # 记录权重
        score.weights = {
            "semantic": self.config.semantic_weight,
            "time_decay": self.config.time_decay_weight,
            "foreshadowing": self.config.foreshadowing_weight,
            "type": type_weight,
        }
        
        return score
    
    def _compute_semantic_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """计算语义相似度得分"""
        # 如果已有语义相似度，直接使用
        if item.score.semantic_score > 0:
            return item.score.semantic_score
        
        # 否则从上下文获取
        return context.get("semantic_similarity", 0.5)
    
    def _compute_time_decay_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算时间衰减得分
        
        使用指数衰减函数：
        score = exp(-decay_factor * delta_days)
        
        其中 delta_days 是记忆创建时间到现在的天数
        """
        current_chapter = context.get("chapter_number", 1)
        item_chapter = item.chapter_number or 0
        
        # 使用章节距离代替时间距离（更适合叙事场景）
        if item_chapter > 0 and current_chapter > 0:
            delta_chapters = current_chapter - item_chapter
            # 章节衰减：越近的章节得分越高
            return math.exp(-self.config.decay_factor * delta_chapters)
        
        # 使用实际时间
        if item.created_at:
            if item.created_at.tzinfo is None:
                created = item.created_at.replace(tzinfo=timezone.utc)
            else:
                created = item.created_at
            
            delta_seconds = (self._now - created).total_seconds()
            delta_days = delta_seconds / 86400
            return math.exp(-self.config.decay_factor * delta_days)
        
        return 0.5  # 默认中等得分
    
    def _compute_foreshadowing_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算伏笔关联得分
        
        规则：
        1. 如果是开放伏笔本身，获得高分
        2. 如果内容与开放伏笔相关（关键词匹配），获得加成
        3. 如果涉及伏笔中的角色，获得额外加成
        """
        open_hooks = context.get("open_hooks", [])
        
        if not open_hooks:
            return 0.0
        
        # 如果是伏笔类型本身
        if item.memory_type == MemoryType.OPEN_HOOK:
            return self.config.open_hook_bonus
        
        # 检查内容与伏笔的关联度
        item_content = item.content.lower()
        item_keywords = set(k.lower() for k in item.keywords)
        item_characters = set(c.lower() for c in item.character_names)
        
        max_relevance = 0.0
        
        for hook in open_hooks:
            hook_content = hook.get("content", "").lower()
            hook_characters = set(
                c.lower() for c in hook.get("character_names", [])
            )
            
            # 内容相似度
            content_overlap = self._compute_text_overlap(
                item_content, hook_content
            )
            
            # 关键词匹配
            hook_keywords = set(
                w.lower() for w in hook_content.split() 
                if len(w) > 2
            )
            keyword_overlap = len(item_keywords & hook_keywords) / max(1, len(hook_keywords))
            
            # 角色匹配
            character_overlap = len(item_characters & hook_characters) / max(1, len(hook_characters))
            
            # 综合关联度
            relevance = (
                0.4 * content_overlap +
                0.3 * keyword_overlap +
                0.3 * character_overlap
            )
            
            max_relevance = max(max_relevance, relevance)
        
        return min(self.config.open_hook_bonus, max_relevance * self.config.open_hook_bonus)
    
    def _compute_character_relevance_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算角色相关度得分
        
        规则：
        1. 如果记忆涉及当前章节出场角色，获得加成
        2. 如果记忆涉及角色关系对，获得额外加成
        """
        character_names = context.get("character_names", [])
        relationship_pairs = context.get("relationship_pairs", [])
        
        if not character_names:
            return 0.0
        
        # 标准化名称
        context_chars = set(c.lower() for c in character_names)
        item_chars = set(c.lower() for c in item.character_names)
        
        # 角色匹配度
        if not item_chars:
            return 0.0
        
        match_ratio = len(context_chars & item_chars) / len(item_chars)
        character_score = match_ratio * self.config.character_match_bonus
        
        # 关系匹配
        if relationship_pairs and len(item_chars) >= 2:
            for pair in relationship_pairs:
                pair_set = set(c.lower() for c in pair)
                if pair_set & item_chars:
                    character_score += self.config.relationship_match_bonus
                    break
        
        return min(0.3, character_score)
    
    def _compute_chapter_proximity_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算章节接近度得分
        
        规则：
        - 紧邻章节（前一章）的记忆获得加成
        - 距离越远，加成越少
        """
        current_chapter = context.get("chapter_number", 1)
        item_chapter = item.chapter_number or 0
        
        if item_chapter <= 0 or item_chapter >= current_chapter:
            return 0.0
        
        distance = current_chapter - item_chapter
        
        if distance == 1:
            return self.config.chapter_proximity_bonus
        elif distance == 2:
            return self.config.chapter_proximity_bonus * 0.5
        elif distance <= 5:
            return self.config.chapter_proximity_bonus * 0.2
        
        return 0.0
    
    def _compute_text_overlap(self, text1: str, text2: str) -> float:
        """计算文本重叠度（基于词集合）"""
        words1 = set(w for w in text1.split() if len(w) > 1)
        words2 = set(w for w in text2.split() if len(w) > 1)
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union)


# =============================================================================
# 记忆去重器
# =============================================================================

class MemoryDeduplicator:
    """
    记忆去重器
    
    策略：
    1. 精确内容去重：相同内容只保留一份
    2. 语义去重：相似内容的记忆只保留得分最高的
    3. 来源去重：同一来源的多条记忆合并
    """
    
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold
    
    def deduplicate(
        self,
        items: List[RetrievedItem],
    ) -> List[RetrievedItem]:
        """
        执行去重
        
        Args:
            items: 原始检索项列表
        
        Returns:
            List[RetrievedItem]: 去重后的列表
        """
        if not items:
            return []
        
        # 1. 精确内容去重
        seen_contents: Set[str] = set()
        unique_items: List[RetrievedItem] = []
        
        for item in items:
            content_key = item.content.strip().lower()
            if content_key not in seen_contents:
                seen_contents.add(content_key)
                unique_items.append(item)
        
        # 2. 语义相似去重（简化实现：基于 Jaccard 相似度）
        deduped_items: List[RetrievedItem] = []
        
        for item in unique_items:
            is_duplicate = False
            
            for existing in deduped_items:
                similarity = self._compute_jaccard_similarity(
                    item.content, existing.content
                )
                
                if similarity >= self.similarity_threshold:
                    # 相似内容，保留得分更高的
                    if item.score.total_score > existing.score.total_score:
                        deduped_items.remove(existing)
                        deduped_items.append(item)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduped_items.append(item)
        
        return deduped_items
    
    def _compute_jaccard_similarity(self, text1: str, text2: str) -> float:
        """计算 Jaccard 相似度"""
        words1 = set(w for w in text1.lower().split() if len(w) > 1)
        words2 = set(w for w in text2.lower().split() if len(w) > 1)
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union)


# =============================================================================
# 检索结果排序器
# =============================================================================

class RetrievalSorter:
    """
    检索结果排序器
    
    排序规则：
    1. 按优先级排序（CRITICAL > HIGH > NORMAL > LOW）
    2. 同优先级按得分排序
    3. 同得分按章节号排序（近的优先）
    """
    
    PRIORITY_ORDER = {
        "critical": 0,
        "high": 1,
        "normal": 2,
        "low": 3,
    }
    
    def sort(
        self,
        items: List[RetrievedItem],
    ) -> List[RetrievedItem]:
        """排序检索结果"""
        return sorted(
            items,
            key=lambda x: (
                self.PRIORITY_ORDER.get(x.priority.value, 2),
                -x.score.total_score,
                -(x.chapter_number or 0),
            )
        )

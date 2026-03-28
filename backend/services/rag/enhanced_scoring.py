# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
增强型检索评分器 (Enhanced Retrieval Scorer)

职责：
- 章节目标导向的检索评分
- 角色状态优先召回评分
- 伏笔关联度精准评分
- 世界设定关联评分
- 时间衰减与章节距离评分
- 检索得分可解释性

设计原则：
1. 得分分解为可理解的组成部分
2. 每个维度有独立的权重可调节
3. 支持小说叙事场景的特殊需求
4. 优先级明确的分层评分机制

评分公式：
total_score = 
    base_score * type_weight +
    outline_relevance * outline_weight +
    character_priority * character_weight +
    hook_relevance * hook_weight +
    time_decay_score * time_weight +
    world_relevance * world_weight

其中：
- base_score: 基础语义相似度
- outline_relevance: 与章节大纲的关联度
- character_priority: 角色状态优先级加成
- hook_relevance: 伏笔关联度
- time_decay_score: 时间衰减得分
- world_relevance: 世界设定关联度
"""

import math
import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from pydantic import BaseModel, Field

from backend.services.rag.retrieval_types import (
    RetrievalScore,
    RetrievedItem,
    MemoryType,
    ContentPriority,
    RetrievalStrategyConfig,
)


logger = logging.getLogger(__name__)


# =============================================================================
# 评分配置
# =============================================================================

@dataclass
class EnhancedScoringConfig:
    """
    增强型评分配置
    
    设计思路：
    1. 区分不同类型的权重
    2. 支持章节目标导向
    3. 支持角色优先召回
    4. 支持伏笔精准召回
    """
    # === 基础权重 ===
    semantic_weight: float = 0.25       # 语义相似度权重
    outline_weight: float = 0.20        # 大纲关联度权重
    time_decay_weight: float = 0.15     # 时间衰减权重
    
    # === 角色相关权重 ===
    character_match_weight: float = 0.15   # 角色匹配权重
    relationship_weight: float = 0.10      # 关系匹配权重
    
    # === 伏笔相关权重 ===
    hook_relevance_weight: float = 0.15    # 伏笔关联权重
    
    # === 时间衰减参数 ===
    decay_factor: float = 0.08          # 时间衰减系数
    chapter_proximity_bonus: float = 0.12  # 章节接近度加成
    
    # === 角色相关参数 ===
    main_character_bonus: float = 0.25     # 主角加成
    appearing_character_bonus: float = 0.20  # 出场角色加成
    relationship_match_bonus: float = 0.15   # 关系匹配加成
    
    # === 伏笔相关参数 ===
    open_hook_bonus: float = 0.30           # 开放伏笔加成
    hook_character_bonus: float = 0.10      # 伏笔涉及角色加成
    hook_keyword_match_bonus: float = 0.15  # 伏笔关键词匹配加成
    
    # === 世界设定相关参数 ===
    world_setting_bonus: float = 0.10       # 世界设定匹配加成
    location_match_bonus: float = 0.08      # 地点匹配加成
    
    # === 类型权重 ===
    type_weights: Dict[str, float] = field(default_factory=lambda: {
        # 必须包含类型
        "previous_summary": 2.0,      # 上一章摘要
        "book_setting": 1.8,          # 书籍设定
        
        # 高优先级类型
        "character_state": 1.6,       # 角色状态
        "relationship_state": 1.4,    # 关系状态
        "open_hook": 1.5,             # 开放伏笔
        "world_snapshot": 1.3,        # 世界快照
        
        # 普通类型
        "memory_chunk": 1.0,          # 历史记忆
        "story_beat": 0.9,            # 故事节拍
        "plot_ledger": 1.1,           # 情节账本
        "map_location": 0.7,          # 地图地点
    })
    
    # === 功能开关 ===
    enable_outline_matching: bool = True     # 启用大纲匹配
    enable_character_priority: bool = True   # 启用角色优先
    enable_hook_boost: bool = True           # 启用伏笔加成
    enable_dedup: bool = True                # 启用去重
    
    @classmethod
    def from_strategy(cls, strategy: RetrievalStrategyConfig) -> "EnhancedScoringConfig":
        """从策略配置创建"""
        config = cls()
        
        # 应用策略权重
        config.semantic_weight = strategy.semantic_weight
        config.time_decay_weight = strategy.time_decay_weight
        config.hook_relevance_weight = strategy.foreshadowing_weight
        config.decay_factor = strategy.decay_factor
        
        # 应用类型权重
        if strategy.type_weights:
            config.type_weights.update(strategy.type_weights)
        
        return config


# =============================================================================
# 大纲关键词提取器
# =============================================================================

class OutlineKeywordExtractor:
    """
    大纲关键词提取器
    
    职责：
    - 从章节大纲提取关键词
    - 识别角色名称
    - 识别事件类型
    - 识别地点信息
    """
    
    # 中文停用词
    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这", "那", "他",
        "她", "它", "们", "这个", "那个", "什么", "怎么", "这样", "那样",
        "因为", "所以", "但是", "然而", "如果", "虽然", "还是", "或者",
    }
    
    # 事件关键词
    EVENT_KEYWORDS = {
        "战斗", "对决", "冲突", "相遇", "离别", "重逢", "发现", "觉醒",
        "突破", "修炼", "探险", "救援", "追杀", "逃亡", "复仇", "和解",
        "告白", "误会", "澄清", "揭秘", "阴谋", "背叛", "牺牲", "拯救",
    }
    
    # 情感关键词
    EMOTION_KEYWORDS = {
        "愤怒", "悲伤", "喜悦", "恐惧", "惊讶", "期待", "失望", "感动",
        "爱慕", "仇恨", "羡慕", "嫉妒", "焦虑", "平静", "激动", "绝望",
    }
    
    def extract(self, outline: str) -> Dict[str, Any]:
        """
        从大纲提取关键信息
        
        Args:
            outline: 章节大纲文本
            
        Returns:
            Dict: 包含关键词、事件类型、情感倾向等
        """
        if not outline:
            return {"keywords": [], "events": [], "emotions": []}
        
        # 提取中文词组
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,10}', outline)
        
        # 过滤停用词
        keywords = [w for w in chinese_words if w not in self.STOP_WORDS]
        
        # 去重保持顺序
        seen = set()
        unique_keywords = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique_keywords.append(w)
        
        # 识别事件类型
        events = [w for w in unique_keywords if w in self.EVENT_KEYWORDS]
        
        # 识别情感倾向
        emotions = [w for w in unique_keywords if w in self.EMOTION_KEYWORDS]
        
        return {
            "keywords": unique_keywords[:20],  # 最多保留20个关键词
            "events": events,
            "emotions": emotions,
            "keyword_set": set(unique_keywords),
        }


# =============================================================================
# 增强型评分器
# =============================================================================

class EnhancedRetrievalScorer:
    """
    增强型检索评分器
    
    职责：
    - 计算多维度检索得分
    - 实现章节目标导向评分
    - 实现角色状态优先召回
    - 实现伏笔精准关联评分
    - 提供可解释的得分分解
    
    评分流程：
    1. 计算大纲关联度
    2. 计算角色相关度
    3. 计算伏笔关联度
    4. 计算时间衰减
    5. 计算世界设定关联
    6. 加权汇总
    """
    
    def __init__(self, config: Optional[EnhancedScoringConfig] = None):
        self.config = config or EnhancedScoringConfig()
        self.outline_extractor = OutlineKeywordExtractor()
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
                - outline_keywords: 大纲关键词
                - character_names: 出场角色名列表
                - main_character_names: 主角名列表
                - relationship_pairs: 角色关系对列表
                - open_hooks: 开放伏笔列表
                - world_keywords: 世界设定关键词
                - location_names: 场景地点列表
                
        Returns:
            RetrievalScore: 得分详情
        """
        score = RetrievalScore()
        
        # 1. 大纲关联度评分
        outline_score = self._compute_outline_relevance(item, context)
        score.semantic_score = outline_score  # 复用 semantic_score 字段
        
        # 2. 时间衰减评分
        time_score = self._compute_time_decay_score(item, context)
        score.time_decay_score = time_score
        
        # 3. 伏笔关联评分
        hook_score = self._compute_hook_relevance(item, context)
        score.foreshadowing_score = hook_score
        
        # 4. 角色相关度评分
        char_score = self._compute_character_relevance(item, context)
        score.character_relevance_score = char_score
        
        # 5. 章节接近度评分
        chapter_score = self._compute_chapter_proximity(item, context)
        score.chapter_proximity_score = chapter_score
        
        # 6. 计算加权总分
        base_score = (
            self.config.semantic_weight * outline_score +
            self.config.time_decay_weight * time_score +
            self.config.hook_relevance_weight * hook_score +
            self.config.character_match_weight * char_score +
            self.config.chapter_proximity_bonus * chapter_score
        )
        
        # 7. 应用类型权重
        type_weight = self.config.type_weights.get(
            item.memory_type.value, 1.0
        )
        
        # 8. 应用优先级加成
        priority_bonus = self._get_priority_bonus(item.priority)
        
        # 9. 最终得分
        total = (base_score + priority_bonus) * type_weight
        score.total_score = min(1.0, max(0.0, total))
        
        # 记录权重
        score.weights = {
            "semantic": self.config.semantic_weight,
            "outline": self.config.outline_weight,
            "time_decay": self.config.time_decay_weight,
            "hook": self.config.hook_relevance_weight,
            "character": self.config.character_match_weight,
            "type": type_weight,
            "priority": priority_bonus,
        }
        
        return score
    
    def _compute_outline_relevance(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算大纲关联度
        
        规则：
        1. 检查内容是否包含大纲关键词
        2. 关键词匹配度越高，得分越高
        3. 事件类型匹配额外加成
        """
        outline_keywords = context.get("outline_keywords", {})
        keyword_set = outline_keywords.get("keyword_set", set())
        
        if not keyword_set:
            return 0.5  # 默认中等得分
        
        # 提取记忆项的关键词
        item_text = item.content.lower()
        item_keywords = set(re.findall(r'[\u4e00-\u9fa5]{2,10}', item_text))
        
        # 计算关键词重叠度
        if not item_keywords:
            return 0.3
        
        intersection = keyword_set & item_keywords
        overlap_ratio = len(intersection) / max(1, min(len(keyword_set), 10))
        
        # 事件类型匹配加成
        events = outline_keywords.get("events", [])
        event_match = any(e in item_text for e in events)
        if event_match:
            overlap_ratio += 0.2
        
        return min(1.0, overlap_ratio)
    
    def _compute_time_decay_score(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算时间衰减得分
        
        使用章节距离而非实际时间：
        score = exp(-decay_factor * delta_chapters)
        
        近期章节的记忆得分更高
        """
        current_chapter = context.get("chapter_number", 1)
        item_chapter = item.chapter_number or 0
        
        # 使用章节距离
        if item_chapter > 0 and current_chapter > 0:
            delta_chapters = current_chapter - item_chapter
            
            if delta_chapters <= 0:
                return 0.5  # 未来章节，默认得分
            
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
        
        return 0.5
    
    def _compute_hook_relevance(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算伏笔关联度
        
        规则：
        1. 如果是开放伏笔本身，获得高分
        2. 如果内容与开放伏笔关键词匹配，获得加成
        3. 如果涉及伏笔中的角色，获得额外加成
        """
        open_hooks = context.get("open_hooks", [])
        
        if not open_hooks:
            return 0.0
        
        # 如果是伏笔类型本身
        if item.memory_type == MemoryType.OPEN_HOOK:
            return self.config.open_hook_bonus
        
        # 检查与开放伏笔的关联度
        item_text = item.content.lower()
        item_keywords = set(re.findall(r'[\u4e00-\u9fa5]{2,10}', item_text))
        item_characters = set(c.lower() for c in item.character_names)
        
        max_relevance = 0.0
        
        for hook in open_hooks:
            hook_content = hook.get("content", "").lower()
            hook_characters = set(
                c.lower() for c in hook.get("character_names", [])
            )
            
            # 关键词匹配
            hook_keywords = set(
                w for w in re.findall(r'[\u4e00-\u9fa5]{2,10}', hook_content)
                if len(w) > 1
            )
            keyword_overlap = len(item_keywords & hook_keywords) / max(1, len(hook_keywords))
            
            # 角色匹配
            character_overlap = len(item_characters & hook_characters) / max(1, len(hook_characters)) if hook_characters else 0
            
            # 综合关联度
            relevance = (
                0.5 * keyword_overlap +
                0.3 * character_overlap +
                0.2 * self._compute_text_similarity(item_text, hook_content)
            )
            
            max_relevance = max(max_relevance, relevance)
        
        return min(self.config.open_hook_bonus, max_relevance * self.config.open_hook_bonus)
    
    def _compute_character_relevance(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算角色相关度
        
        规则：
        1. 涉及主角的记忆获得最高加成
        2. 涉及出场角色的记忆获得加成
        3. 涉及关系对的记忆获得额外加成
        """
        if not item.character_names:
            return 0.0
        
        character_names = context.get("character_names", [])
        main_characters = context.get("main_character_names", [])
        relationship_pairs = context.get("relationship_pairs", [])
        
        item_chars = set(c.lower() for c in item.character_names)
        context_chars = set(c.lower() for c in character_names)
        main_chars = set(c.lower() for c in main_characters)
        
        score = 0.0
        
        # 主角匹配
        main_match = item_chars & main_chars
        if main_match:
            score += self.config.main_character_bonus * len(main_match) / len(item_chars)
        
        # 出场角色匹配
        appearing_match = item_chars & context_chars
        if appearing_match:
            score += self.config.appearing_character_bonus * len(appearing_match) / len(item_chars)
        
        # 关系匹配
        if relationship_pairs and len(item_chars) >= 2:
            for pair in relationship_pairs:
                pair_set = set(c.lower() for c in pair)
                if pair_set & item_chars:
                    score += self.config.relationship_match_bonus
                    break
        
        return min(0.5, score)
    
    def _compute_chapter_proximity(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """
        计算章节接近度
        
        规则：
        - 紧邻章节（前1-2章）获得高加成
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
            return self.config.chapter_proximity_bonus * 0.7
        elif distance <= 5:
            return self.config.chapter_proximity_bonus * 0.4
        elif distance <= 10:
            return self.config.chapter_proximity_bonus * 0.2
        
        return 0.0
    
    def _compute_text_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度（基于 Jaccard 相似度）"""
        words1 = set(w for w in re.findall(r'[\u4e00-\u9fa5]{2,}', text1))
        words2 = set(w for w in re.findall(r'[\u4e00-\u9fa5]{2,}', text2))
        
        if not words1 or not words2:
            return 0.0
        
        intersection = words1 & words2
        union = words1 | words2
        
        return len(intersection) / len(union) if union else 0.0
    
    def _get_priority_bonus(self, priority: ContentPriority) -> float:
        """获取优先级加成"""
        priority_bonuses = {
            ContentPriority.CRITICAL: 0.3,
            ContentPriority.HIGH: 0.15,
            ContentPriority.NORMAL: 0.0,
            ContentPriority.LOW: -0.1,
        }
        return priority_bonuses.get(priority, 0.0)


# =============================================================================
# 检索上下文构建器
# =============================================================================

class RetrievalContextBuilder:
    """
    检索上下文构建器
    
    职责：
    - 从章节大纲提取关键信息
    - 构建评分所需的完整上下文
    - 预计算常用信息以提高性能
    """
    
    def __init__(self):
        self.outline_extractor = OutlineKeywordExtractor()
    
    def build(
        self,
        chapter_number: int,
        outline: str,
        entities: List[Any],
        relationships: List[Any],
        open_hooks: List[Dict],
        world_keywords: Optional[Set[str]] = None,
        location_names: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        构建检索上下文
        
        Args:
            chapter_number: 章节号
            outline: 章节大纲
            entities: 出场角色实体列表
            relationships: 角色关系列表
            open_hooks: 开放伏笔列表
            world_keywords: 世界设定关键词
            location_names: 场景地点列表
            
        Returns:
            Dict: 完整的评分上下文
        """
        # 提取大纲关键词
        outline_keywords = self.outline_extractor.extract(outline)
        
        # 提取角色名称
        character_names = []
        main_character_names = []
        
        for entity in entities:
            if hasattr(entity, 'character') and entity.character:
                name = entity.character.name
                if name:
                    character_names.append(name)
                    # 判断是否为主角
                    importance = getattr(entity.character, 'importance_level', 1)
                    if importance >= 8:
                        main_character_names.append(name)
        
        # 提取关系对
        relationship_pairs = []
        for rel in relationships:
            source_name = getattr(
                getattr(rel, 'source_character', None), 'name', None
            )
            target_name = getattr(
                getattr(rel, 'target_character', None), 'name', None
            )
            if source_name and target_name:
                relationship_pairs.append((source_name, target_name))
        
        # 构建伏笔关键词
        hook_keywords = set()
        for hook in open_hooks:
            content = hook.get("content", "")
            keywords = re.findall(r'[\u4e00-\u9fa5]{2,10}', content)
            hook_keywords.update(keywords)
        
        return {
            "chapter_number": chapter_number,
            "outline": outline,
            "outline_keywords": outline_keywords,
            "character_names": character_names,
            "main_character_names": main_character_names,
            "relationship_pairs": relationship_pairs,
            "open_hooks": open_hooks,
            "hook_keywords": hook_keywords,
            "world_keywords": world_keywords or set(),
            "location_names": location_names or [],
        }


# =============================================================================
# 便捷函数
# =============================================================================

def create_scorer_for_strategy(strategy: RetrievalStrategyConfig) -> EnhancedRetrievalScorer:
    """
    根据检索策略创建评分器
    
    Args:
        strategy: 检索策略配置
        
    Returns:
        EnhancedRetrievalScorer: 配置好的评分器
    """
    config = EnhancedScoringConfig.from_strategy(strategy)
    return EnhancedRetrievalScorer(config)


def score_retrieval_item(
    item: RetrievedItem,
    context: Dict[str, Any],
    config: Optional[EnhancedScoringConfig] = None,
) -> RetrievalScore:
    """
    便捷函数：计算单个检索项得分
    
    Args:
        item: 检索项
        context: 评分上下文
        config: 评分配置
        
    Returns:
        RetrievalScore: 得分详情
    """
    scorer = EnhancedRetrievalScorer(config)
    return scorer.compute_score(item, context)

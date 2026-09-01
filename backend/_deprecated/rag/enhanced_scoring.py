# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
增强型检索评分器 (Enhanced Retrieval Scorer)

职责：
- 章节目标导向的检索评分
- 角色状态优先召回评分
- 伏笔关联度精准评分
- 世界设定关联评分
- 时间衰减与章节距离评分
- 检索得分可解释性

本模块是 Facade 层，实际实现已拆分到：
- services/rag/enhanced/config.py: 评分配置
- services/rag/enhanced/keyword_extractor.py: 大纲关键词提取器

使用方式：
    from backend.services.rag.enhanced_scoring import (
        EnhancedScoringConfig,
        EnhancedRetrievalScorer,
        OutlineKeywordExtractor,
        RetrievalContextBuilder,
        create_scorer_for_strategy,
        score_retrieval_item,
    )
"""

import math
import re
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from backend.services.rag.retrieval_types import (
    RetrievalScore,
    RetrievedItem,
    MemoryType,
    ContentPriority,
    RetrievalStrategyConfig,
)

logger = logging.getLogger(__name__)

from backend.services.rag.enhanced import (
    EnhancedScoringConfig,
    OutlineKeywordExtractor,
)


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
        """计算检索项得分"""
        score = RetrievalScore()

        outline_score = self._compute_outline_relevance(item, context)
        score.semantic_score = outline_score

        time_score = self._compute_time_decay_score(item, context)
        score.time_decay_score = time_score

        hook_score = self._compute_hook_relevance(item, context)
        score.foreshadowing_score = hook_score

        char_score = self._compute_character_relevance(item, context)
        score.character_relevance_score = char_score

        chapter_score = self._compute_chapter_proximity(item, context)
        score.chapter_proximity_score = chapter_score

        base_score = (
            self.config.semantic_weight * outline_score +
            self.config.time_decay_weight * time_score +
            self.config.hook_relevance_weight * hook_score +
            self.config.character_match_weight * char_score +
            self.config.chapter_proximity_bonus * chapter_score
        )

        type_weight = self.config.type_weights.get(
            item.memory_type.value, 1.0
        )

        priority_bonus = self._get_priority_bonus(item.priority)

        total = (base_score + priority_bonus) * type_weight
        score.total_score = min(1.0, max(0.0, total))

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
        """计算大纲关联度"""
        outline_keywords = context.get("outline_keywords", {})
        keyword_set = outline_keywords.get("keyword_set", set())

        if not keyword_set:
            return 0.5

        item_text = item.content.lower()
        item_keywords = set(re.findall(r'[\u4e00-\u9fa5]{2,10}', item_text))

        if not item_keywords:
            return 0.3

        intersection = keyword_set & item_keywords
        overlap_ratio = len(intersection) / max(1, min(len(keyword_set), 10))

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
        """计算时间衰减得分"""
        current_chapter = context.get("chapter_number", 1)
        item_chapter = item.chapter_number or 0

        if item_chapter > 0 and current_chapter > 0:
            delta_chapters = current_chapter - item_chapter

            if delta_chapters <= 0:
                return 0.5

            return math.exp(-self.config.decay_factor * delta_chapters)

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
        """计算伏笔关联度"""
        open_hooks = context.get("open_hooks", [])

        if not open_hooks:
            return 0.0

        item_text = item.content.lower()

        max_relevance = 0.0
        for hook in open_hooks:
            hook_content = hook.get("content", "").lower()
            hook_keywords = hook.get("keywords", [])

            relevance = 0.0

            if hook_content in item_text:
                relevance += 0.5

            if hook_keywords:
                matches = sum(1 for kw in hook_keywords if kw.lower() in item_text)
                relevance += matches / len(hook_keywords) * 0.3

            char_names = context.get("character_names", [])
            if char_names:
                char_match = any(name.lower() in item_text for name in char_names)
                if char_match:
                    relevance += 0.2

            max_relevance = max(max_relevance, relevance)

        return min(1.0, max_relevance)

    def _compute_character_relevance(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """计算角色相关度"""
        item_text = item.content.lower()

        character_names = context.get("character_names", [])
        main_character_names = context.get("main_character_names", [])

        if not character_names:
            return 0.0

        match_count = sum(1 for name in character_names if name.lower() in item_text)

        relevance = match_count / len(character_names) * 0.5

        if main_character_names:
            main_match = sum(1 for name in main_character_names if name.lower() in item_text)
            relevance += main_match / len(main_character_names) * 0.5

        relationship_pairs = context.get("relationship_pairs", [])
        if relationship_pairs:
            for source, target in relationship_pairs:
                if source.lower() in item_text and target.lower() in item_text:
                    relevance += 0.1
                    break

        return min(1.0, relevance)

    def _compute_chapter_proximity(
        self,
        item: RetrievedItem,
        context: Dict[str, Any],
    ) -> float:
        """计算章节接近度"""
        current_chapter = context.get("chapter_number", 1)
        item_chapter = item.chapter_number or 0

        if item_chapter <= 0:
            return 0.0

        delta = abs(current_chapter - item_chapter)

        if delta == 0:
            return 1.0
        elif delta == 1:
            return 0.8
        elif delta == 2:
            return 0.5
        else:
            return max(0.0, 1.0 - delta * 0.1)

    def _get_priority_bonus(self, priority: ContentPriority) -> float:
        """获取优先级加成"""
        bonuses = {
            ContentPriority.CRITICAL: 0.3,
            ContentPriority.HIGH: 0.2,
            ContentPriority.MEDIUM: 0.1,
            ContentPriority.LOW: 0.0,
        }
        return bonuses.get(priority, 0.0)


# =============================================================================
# 检索上下文构建器
# =============================================================================

class RetrievalContextBuilder:
    """检索上下文构建器"""

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
        """构建检索上下文"""
        outline_keywords = self.outline_extractor.extract(outline)

        character_names = []
        main_character_names = []

        for entity in entities:
            if hasattr(entity, 'character') and entity.character:
                name = entity.character.name
                if name:
                    character_names.append(name)
                    importance = getattr(entity.character, 'importance_level', 1)
                    if importance >= 8:
                        main_character_names.append(name)

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
    """根据检索策略创建评分器"""
    config = EnhancedScoringConfig.from_strategy(strategy)
    return EnhancedRetrievalScorer(config)


def score_retrieval_item(
    item: RetrievedItem,
    context: Dict[str, Any],
    config: Optional[EnhancedScoringConfig] = None,
) -> RetrievalScore:
    """便捷函数：计算单个检索项得分"""
    scorer = EnhancedRetrievalScorer(config)
    return scorer.compute_score(item, context)

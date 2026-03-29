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
增强型检索评分器 - 配置模块。

职责：定义增强型评分配置。

包含：
- EnhancedScoringConfig: 增强型评分配置

使用场景：
- rag/enhanced/scorer.py: 评分器使用配置
"""

from dataclasses import dataclass, field
from typing import Dict

from backend.services.rag.retrieval_types import RetrievalStrategyConfig


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
    semantic_weight: float = 0.25
    outline_weight: float = 0.20
    time_decay_weight: float = 0.15

    character_match_weight: float = 0.15
    relationship_weight: float = 0.10

    hook_relevance_weight: float = 0.15

    decay_factor: float = 0.08
    chapter_proximity_bonus: float = 0.12

    main_character_bonus: float = 0.25
    appearing_character_bonus: float = 0.20
    relationship_match_bonus: float = 0.15

    open_hook_bonus: float = 0.30
    hook_character_bonus: float = 0.10
    hook_keyword_match_bonus: float = 0.15

    world_setting_bonus: float = 0.10
    location_match_bonus: float = 0.08

    type_weights: Dict[str, float] = field(default_factory=lambda: {
        "previous_summary": 2.0,
        "book_setting": 1.8,
        "character_state": 1.6,
        "relationship_state": 1.4,
        "open_hook": 1.5,
        "world_snapshot": 1.3,
        "memory_chunk": 1.0,
        "story_beat": 0.9,
        "plot_ledger": 1.1,
        "map_location": 0.7,
    })

    enable_outline_matching: bool = True
    enable_character_priority: bool = True
    enable_hook_boost: bool = True
    enable_dedup: bool = True

    @classmethod
    def from_strategy(cls, strategy: RetrievalStrategyConfig) -> "EnhancedScoringConfig":
        """从策略配置创建"""
        config = cls()

        config.semantic_weight = strategy.semantic_weight
        config.time_decay_weight = strategy.time_decay_weight
        config.hook_relevance_weight = strategy.foreshadowing_weight
        config.decay_factor = strategy.decay_factor

        if strategy.type_weights:
            config.type_weights.update(strategy.type_weights)

        return config

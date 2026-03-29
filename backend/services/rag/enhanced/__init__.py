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
增强型检索评分器子模块。

职责：提供章节目标导向的检索评分功能。

子模块：
- config.py: 评分配置
- keyword_extractor.py: 大纲关键词提取器
- scorer.py: 增强型评分器
- context_builder.py: 检索上下文构建器

使用方式：
    from backend.services.rag.enhanced import (
        EnhancedScoringConfig,
        EnhancedRetrievalScorer,
        OutlineKeywordExtractor,
        RetrievalContextBuilder,
        create_scorer_for_strategy,
        score_retrieval_item,
    )
"""

from backend.services.rag.enhanced.config import EnhancedScoringConfig
from backend.services.rag.enhanced.keyword_extractor import OutlineKeywordExtractor

__all__ = [
    "EnhancedScoringConfig",
    "OutlineKeywordExtractor",
]

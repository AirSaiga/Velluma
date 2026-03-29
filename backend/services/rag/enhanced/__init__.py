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

# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
检索可解释性模块 (Retrieval Explainability Module)

职责：
- 记录每条记忆的得分组成
- 解释"为什么检索到这条记忆"
- 提供调试接口
- 支持检索策略复用

设计原则：
1. 每个检索决策都可追溯
2. 得分分解为可理解的组成部分
3. 提供人类可读的解释文本
4. 支持开发调试与用户查看
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from enum import Enum
import json

from backend.services.rag.retrieval_types import (
    RetrievedItem,
    RetrievalResult,
    RetrievalScore,
    MemoryType,
    RetrievalMethod,
    ContentPriority,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 解释类型定义
# =============================================================================

class ExplanationLevel(str, Enum):
    """解释详细程度"""
    BRIEF = "brief"          # 简要说明
    NORMAL = "normal"        # 标准说明
    DETAILED = "detailed"    # 详细说明


class RetrievalExplanation(BaseModel):
    """检索解释"""
    # 基本信息
    item_id: str = Field(..., description="检索项 ID")
    memory_type: str = Field(..., description="记忆类型")
    
    # 解释内容
    brief_explanation: str = Field(default="", description="简要解释")
    detailed_explanation: str = Field(default="", description="详细解释")
    
    # 得分分解
    score_breakdown: Dict[str, float] = Field(
        default_factory=dict,
        description="得分分解"
    )
    
    # 决策因素
    decision_factors: List[str] = Field(
        default_factory=list,
        description="决策因素列表"
    )
    
    # 相关信息
    related_items: List[str] = Field(
        default_factory=list,
        description="相关检索项 ID"
    )
    
    # 元数据
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间"
    )


class RetrievalReport(BaseModel):
    """检索报告"""
    # 基本信息
    query: str = Field(default="", description="检索查询")
    chapter_id: str = Field(default="", description="章节 ID")
    chapter_number: int = Field(default=0, description="章节号")
    
    # 统计信息
    total_items: int = Field(default=0, description="总检索项数")
    by_type: Dict[str, int] = Field(default_factory=dict, description="按类型统计")
    by_priority: Dict[str, int] = Field(default_factory=dict, description="按优先级统计")
    
    # 各项解释
    explanations: List[RetrievalExplanation] = Field(
        default_factory=list,
        description="检索解释列表"
    )
    
    # 策略信息
    strategy_name: str = Field(default="", description="策略名称")
    strategy_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="策略参数"
    )
    
    # 性能信息
    retrieval_time_ms: float = Field(default=0.0, description="检索耗时")
    
    # 元数据
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="创建时间"
    )
    
    def get_summary(self) -> str:
        """获取摘要"""
        lines = [
            f"# 检索报告",
            f"",
            f"## 基本信息",
            f"- 章节: 第 {self.chapter_number} 章",
            f"- 查询: {self.query[:50]}{'...' if len(self.query) > 50 else ''}",
            f"- 策略: {self.strategy_name}",
            f"- 结果数: {self.total_items}",
            f"- 耗时: {self.retrieval_time_ms:.1f}ms",
            f"",
            f"## 按类型统计",
        ]
        
        for type_name, count in sorted(self.by_type.items(), key=lambda x: -x[1]):
            lines.append(f"- {type_name}: {count}")
        
        lines.append(f"")
        lines.append(f"## 高得分项 (Top 5)")
        
        # 获取高得分项
        sorted_explanations = sorted(
            self.explanations,
            key=lambda x: x.score_breakdown.get("total", 0),
            reverse=True
        )[:5]
        
        for exp in sorted_explanations:
            score = exp.score_breakdown.get("total", 0)
            lines.append(f"- [{exp.memory_type}] 得分 {score:.3f}")
            lines.append(f"  {exp.brief_explanation}")
        
        return "\n".join(lines)


# =============================================================================
# 解释生成器
# =============================================================================

class ExplanationGenerator:
    """
    解释生成器
    
    职责：
    - 为检索项生成人类可读的解释
    - 分解得分组成部分
    - 识别决策关键因素
    """
    
    # 检索方法说明模板
    METHOD_DESCRIPTIONS = {
        RetrievalMethod.MANDATORY: "必须包含的上下文",
        RetrievalMethod.EXACT: "通过精确匹配检索",
        RetrievalMethod.VECTOR: "通过语义相似度检索",
        RetrievalMethod.HYBRID: "通过混合策略检索",
    }
    
    # 记忆类型说明
    TYPE_DESCRIPTIONS = {
        MemoryType.PREVIOUS_SUMMARY: "上一章概要",
        MemoryType.BOOK_SETTING: "书籍核心设定",
        MemoryType.CHARACTER_STATE: "角色当前状态",
        MemoryType.RELATIONSHIP_STATE: "角色关系",
        MemoryType.OPEN_HOOK: "未闭合伏笔",
        MemoryType.WORLD_SNAPSHOT: "世界状态快照",
        MemoryType.MEMORY_CHUNK: "历史记忆切片",
        MemoryType.STORY_BEAT: "故事节拍",
        MemoryType.MAP_LOCATION: "场景地点",
        MemoryType.PLOT_LEDGER: "情节账本",
    }
    
    # 优先级说明
    PRIORITY_DESCRIPTIONS = {
        ContentPriority.CRITICAL: "关键内容，不可省略",
        ContentPriority.HIGH: "高优先级，应尽量包含",
        ContentPriority.NORMAL: "普通优先级",
        ContentPriority.LOW: "低优先级，空间允许时包含",
    }
    
    def generate(
        self,
        item: RetrievedItem,
        level: ExplanationLevel = ExplanationLevel.NORMAL,
    ) -> RetrievalExplanation:
        """
        生成检索解释
        
        Args:
            item: 检索项
            level: 解释详细程度
        
        Returns:
            RetrievalExplanation: 检索解释
        """
        explanation = RetrievalExplanation(
            item_id=item.source_id,
            memory_type=item.memory_type.value,
        )
        
        # 生成得分分解
        explanation.score_breakdown = self._build_score_breakdown(item.score)
        
        # 生成简要解释
        explanation.brief_explanation = self._build_brief_explanation(item)
        
        # 生成详细解释
        if level in [ExplanationLevel.NORMAL, ExplanationLevel.DETAILED]:
            explanation.detailed_explanation = self._build_detailed_explanation(item)
        
        # 识别决策因素
        explanation.decision_factors = self._identify_decision_factors(item)
        
        return explanation
    
    def _build_score_breakdown(self, score: RetrievalScore) -> Dict[str, float]:
        """构建得分分解"""
        return {
            "total": score.total_score,
            "semantic": score.semantic_score,
            "time_decay": score.time_decay_score,
            "foreshadowing": score.foreshadowing_score,
            "character_relevance": score.character_relevance_score,
            "chapter_proximity": score.chapter_proximity_score,
        }
    
    def _build_brief_explanation(self, item: RetrievedItem) -> str:
        """构建简要解释"""
        type_desc = self.TYPE_DESCRIPTIONS.get(item.memory_type, "记忆")
        method_desc = self.METHOD_DESCRIPTIONS.get(item.retrieval_method, "检索")
        
        parts = [f"{type_desc}，{method_desc}"]
        
        # 添加得分说明
        if item.score.total_score > 0.8:
            parts.append("高度相关")
        elif item.score.total_score > 0.5:
            parts.append("中等相关")
        else:
            parts.append("轻度相关")
        
        # 添加原因
        if item.retrieval_reason:
            parts.append(f"（{item.retrieval_reason}）")
        
        return "，".join(parts)
    
    def _build_detailed_explanation(self, item: RetrievedItem) -> str:
        """构建详细解释"""
        lines = []
        
        # 类型说明
        type_desc = self.TYPE_DESCRIPTIONS.get(item.memory_type, "记忆")
        lines.append(f"类型: {type_desc}")
        
        # 检索方法
        method_desc = self.METHOD_DESCRIPTIONS.get(item.retrieval_method, "检索")
        lines.append(f"检索方法: {method_desc}")
        
        # 优先级
        priority_desc = self.PRIORITY_DESCRIPTIONS.get(item.priority, "")
        lines.append(f"优先级: {item.priority.value}" + (f"（{priority_desc}）" if priority_desc else ""))
        
        # 得分详情
        lines.append("")
        lines.append("得分分解:")
        lines.append(f"  - 总分: {item.score.total_score:.3f}")
        
        if item.score.semantic_score > 0:
            lines.append(f"  - 语义相似度: {item.score.semantic_score:.3f}")
        if item.score.time_decay_score > 0:
            lines.append(f"  - 时间衰减: {item.score.time_decay_score:.3f}")
        if item.score.foreshadowing_score > 0:
            lines.append(f"  - 伏笔关联: {item.score.foreshadowing_score:.3f}")
        if item.score.character_relevance_score > 0:
            lines.append(f"  - 角色相关: {item.score.character_relevance_score:.3f}")
        if item.score.chapter_proximity_score > 0:
            lines.append(f"  - 章节接近度: {item.score.chapter_proximity_score:.3f}")
        
        # 关联信息
        if item.character_names:
            lines.append(f"涉及角色: {', '.join(item.character_names)}")
        if item.chapter_number:
            lines.append(f"来源章节: 第 {item.chapter_number} 章")
        
        # 检索原因
        if item.retrieval_reason:
            lines.append(f"检索原因: {item.retrieval_reason}")
        
        return "\n".join(lines)
    
    def _identify_decision_factors(self, item: RetrievedItem) -> List[str]:
        """识别决策因素"""
        factors = []
        
        # 优先级因素
        if item.priority == ContentPriority.CRITICAL:
            factors.append("关键内容（必须包含）")
        elif item.priority == ContentPriority.HIGH:
            factors.append("高优先级内容")
        
        # 得分因素
        if item.score.semantic_score > 0.7:
            factors.append("语义高度匹配")
        if item.score.foreshadowing_score > 0.1:
            factors.append("与开放伏笔相关")
        if item.score.character_relevance_score > 0.1:
            factors.append("涉及当前章节角色")
        if item.score.chapter_proximity_score > 0:
            factors.append("来自近期章节")
        
        # 类型因素
        if item.memory_type == MemoryType.OPEN_HOOK:
            factors.append("伏笔需要闭合")
        elif item.memory_type == MemoryType.CHARACTER_STATE:
            factors.append("角色设定需要遵循")
        
        return factors if factors else ["按检索得分排序"]


# =============================================================================
# 检索报告生成器
# =============================================================================

class RetrievalReportGenerator:
    """
    检索报告生成器
    
    职责：
    - 为完整检索结果生成报告
    - 汇总统计信息
    - 提供调试接口
    """
    
    def __init__(self, explanation_level: ExplanationLevel = ExplanationLevel.NORMAL):
        self.explanation_level = explanation_level
        self.explanation_generator = ExplanationGenerator()
    
    def generate_report(
        self,
        result: RetrievalResult,
    ) -> RetrievalReport:
        """
        生成检索报告
        
        Args:
            result: 检索结果
        
        Returns:
            RetrievalReport: 检索报告
        """
        report = RetrievalReport(
            query=result.query,
            chapter_id=result.chapter_id,
            chapter_number=result.chapter_number,
            total_items=result.total_items,
            by_type=result.by_type.copy(),
            by_priority=result.by_priority.copy(),
            strategy_name=result.strategy_name,
            strategy_params=result.strategy_params.copy(),
            retrieval_time_ms=result.retrieval_time_ms,
        )
        
        # 生成每项的解释
        for item in result.items:
            explanation = self.explanation_generator.generate(
                item, self.explanation_level
            )
            report.explanations.append(explanation)
        
        return report
    
    def generate_debug_log(
        self,
        result: RetrievalResult,
    ) -> str:
        """
        生成调试日志
        
        Args:
            result: 检索结果
        
        Returns:
            str: 调试日志文本
        """
        report = self.generate_report(result)
        return report.get_summary()
    
    def generate_json_export(
        self,
        result: RetrievalResult,
    ) -> str:
        """
        生成 JSON 导出
        
        Args:
            result: 检索结果
        
        Returns:
            str: JSON 字符串
        """
        report = self.generate_report(result)
        return report.model_dump_json(indent=2)


# =============================================================================
# 检索策略复用器
# =============================================================================

class RetrievalStrategyRecorder:
    """
    检索策略记录器
    
    职责：
    - 记录成功的检索策略
    - 支持策略复用
    - 提供策略建议
    """
    
    def __init__(self):
        self._strategy_history: List[Dict[str, Any]] = []
    
    def record(
        self,
        strategy_name: str,
        strategy_params: Dict[str, Any],
        result_stats: Dict[str, Any],
    ) -> None:
        """
        记录策略使用情况
        
        Args:
            strategy_name: 策略名称
            strategy_params: 策略参数
            result_stats: 结果统计
        """
        record = {
            "strategy_name": strategy_name,
            "params": strategy_params,
            "stats": result_stats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        self._strategy_history.append(record)
    
    def get_recommended_strategy(
        self,
        chapter_number: int,
        tension_level: int,
        open_hook_count: int,
    ) -> str:
        """
        获取推荐策略
        
        Args:
            chapter_number: 章节号
            tension_level: 张力等级
            open_hook_count: 开放伏笔数
        
        Returns:
            str: 推荐策略名称
        """
        # 基于规则推荐
        if open_hook_count > 5:
            return "resolution"
        elif tension_level >= 4:
            return "deep_dive"
        elif tension_level <= 2:
            return "fast_track"
        elif chapter_number == 1:
            return "balanced_reference"
        else:
            return "balanced_reference"
    
    def get_strategy_stats(self) -> Dict[str, Any]:
        """获取策略使用统计"""
        if not self._strategy_history:
            return {}
        
        by_strategy: Dict[str, int] = {}
        for record in self._strategy_history:
            name = record.get("strategy_name", "unknown")
            by_strategy[name] = by_strategy.get(name, 0) + 1
        
        return {
            "total_uses": len(self._strategy_history),
            "by_strategy": by_strategy,
        }


# =============================================================================
# 便捷函数
# =============================================================================

def explain_retrieval(
    item: RetrievedItem,
    level: ExplanationLevel = ExplanationLevel.NORMAL,
) -> str:
    """
    便捷函数：解释检索结果
    
    Args:
        item: 检索项
        level: 解释详细程度
    
    Returns:
        str: 解释文本
    """
    generator = ExplanationGenerator()
    explanation = generator.generate(item, level)
    return explanation.detailed_explanation or explanation.brief_explanation


def generate_retrieval_report(
    result: RetrievalResult,
    level: ExplanationLevel = ExplanationLevel.NORMAL,
) -> RetrievalReport:
    """
    便捷函数：生成检索报告
    
    Args:
        result: 检索结果
        level: 解释详细程度
    
    Returns:
        RetrievalReport: 检索报告
    """
    generator = RetrievalReportGenerator(level)
    return generator.generate_report(result)

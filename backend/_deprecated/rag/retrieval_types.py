# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
RAG 检索类型定义 (RAG Retrieval Types)

职责：
- 定义记忆类型枚举
- 定义检索优先级
- 定义检索结果结构
- 定义上下文包结构

设计原则：
1. 区分精确检索与向量检索
2. 区分必须包含与可选包含
3. 区分摘要与原文保留
"""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


# =============================================================================
# 记忆类型枚举
# =============================================================================

class MemoryType(str, Enum):
    """记忆类型"""
    # === 向量检索类型 ===
    MEMORY_CHUNK = "memory_chunk"           # 章节摘要切片（向量检索）
    
    # === 精确检索类型 ===
    CHARACTER_STATE = "character_state"     # 角色状态（精确检索）
    RELATIONSHIP_STATE = "relationship_state"  # 关系状态（精确检索）
    OPEN_HOOK = "open_hook"                 # 开放伏笔（精确检索）
    WORLD_SNAPSHOT = "world_snapshot"       # 世界快照（精确检索）
    
    # === 混合检索类型 ===
    PLOT_LEDGER = "plot_ledger"             # 情节账本（混合检索）
    STORY_BEAT = "story_beat"               # 故事节拍（混合检索）
    
    # === 上下文类型 ===
    PREVIOUS_SUMMARY = "previous_summary"   # 上一章摘要（必须包含）
    BOOK_SETTING = "book_setting"           # 书籍设定（必须包含）
    MAP_LOCATION = "map_location"           # 地图地点（上下文相关）


class RetrievalMethod(str, Enum):
    """检索方法"""
    VECTOR = "vector"           # 向量检索（语义相似度）
    EXACT = "exact"             # 精确检索（ID/名称匹配）
    HYBRID = "hybrid"           # 混合检索（向量+规则）
    MANDATORY = "mandatory"     # 强制包含（无需检索）


class ContentPriority(str, Enum):
    """内容优先级"""
    CRITICAL = "critical"       # 必须包含，不可省略
    HIGH = "high"               # 高优先级，尽量包含
    NORMAL = "normal"           # 正常优先级
    LOW = "low"                 # 低优先级，空间允许时包含


class ContentType(str, Enum):
    """内容类型（决定如何打包）"""
    FULL_TEXT = "full_text"     # 保留原文
    SUMMARY = "summary"         # 可摘要
    STRUCTURED = "structured"   # 结构化数据
    KEYWORDS = "keywords"       # 仅保留关键词


# =============================================================================
# 记忆类型配置
# =============================================================================

class MemoryTypeConfig:
    """
    记忆类型配置
    
    定义每种记忆类型的：
    - 检索方法
    - 优先级
    - 内容类型
    - 最大长度
    """
    
    CONFIGS = {
        # === 强制包含 ===
        MemoryType.PREVIOUS_SUMMARY: {
            "method": RetrievalMethod.MANDATORY,
            "priority": ContentPriority.CRITICAL,
            "content_type": ContentType.SUMMARY,
            "max_length": 500,
            "description": "上一章摘要，跨章连贯性锚点",
        },
        MemoryType.BOOK_SETTING: {
            "method": RetrievalMethod.MANDATORY,
            "priority": ContentPriority.CRITICAL,
            "content_type": ContentType.STRUCTURED,
            "max_length": 800,
            "description": "书籍核心设定（风格、禁忌、世界观）",
        },
        
        # === 精确检索 ===
        MemoryType.CHARACTER_STATE: {
            "method": RetrievalMethod.EXACT,
            "priority": ContentPriority.HIGH,
            "content_type": ContentType.STRUCTURED,
            "max_length": 300,
            "description": "出场角色当前状态",
        },
        MemoryType.RELATIONSHIP_STATE: {
            "method": RetrievalMethod.EXACT,
            "priority": ContentPriority.HIGH,
            "content_type": ContentType.STRUCTURED,
            "max_length": 200,
            "description": "出场角色间关系",
        },
        MemoryType.OPEN_HOOK: {
            "method": RetrievalMethod.EXACT,
            "priority": ContentPriority.HIGH,
            "content_type": ContentType.FULL_TEXT,
            "max_length": 150,
            "description": "未闭合伏笔",
        },
        MemoryType.WORLD_SNAPSHOT: {
            "method": RetrievalMethod.EXACT,
            "priority": ContentPriority.HIGH,
            "content_type": ContentType.STRUCTURED,
            "max_length": 400,
            "description": "前一章世界终端状态",
        },
        
        # === 向量检索 ===
        MemoryType.MEMORY_CHUNK: {
            "method": RetrievalMethod.VECTOR,
            "priority": ContentPriority.NORMAL,
            "content_type": ContentType.SUMMARY,
            "max_length": 200,
            "description": "历史记忆切片",
        },
        
        # === 混合检索 ===
        MemoryType.PLOT_LEDGER: {
            "method": RetrievalMethod.HYBRID,
            "priority": ContentPriority.HIGH,
            "content_type": ContentType.FULL_TEXT,
            "max_length": 150,
            "description": "情节账本条目",
        },
        MemoryType.STORY_BEAT: {
            "method": RetrievalMethod.HYBRID,
            "priority": ContentPriority.NORMAL,
            "content_type": ContentType.SUMMARY,
            "max_length": 100,
            "description": "历史节拍参考",
        },
        MemoryType.MAP_LOCATION: {
            "method": RetrievalMethod.HYBRID,
            "priority": ContentPriority.LOW,
            "content_type": ContentType.STRUCTURED,
            "max_length": 100,
            "description": "场景地点信息",
        },
    }
    
    @classmethod
    def get_config(cls, memory_type: MemoryType) -> Dict[str, Any]:
        """获取记忆类型配置"""
        return cls.CONFIGS.get(memory_type, {
            "method": RetrievalMethod.VECTOR,
            "priority": ContentPriority.NORMAL,
            "content_type": ContentType.SUMMARY,
            "max_length": 200,
            "description": "未知类型",
        })


# =============================================================================
# 检索结果结构
# =============================================================================

class RetrievalScore(BaseModel):
    """检索得分详情"""
    total_score: float = Field(default=0.0, ge=0.0, le=1.0)
    
    # 得分组成
    semantic_score: float = Field(default=0.0, description="语义相似度得分")
    time_decay_score: float = Field(default=0.0, description="时间衰减得分")
    foreshadowing_score: float = Field(default=0.0, description="伏笔关联得分")
    character_relevance_score: float = Field(default=0.0, description="角色相关度得分")
    chapter_proximity_score: float = Field(default=0.0, description="章节接近度得分")
    
    # 权重
    weights: Dict[str, float] = Field(default_factory=dict, description="使用的权重")
    
    def to_explanation(self) -> str:
        """生成可解释说明"""
        parts = [f"总分: {self.total_score:.3f}"]
        if self.semantic_score > 0:
            parts.append(f"语义相似度: {self.semantic_score:.3f}")
        if self.time_decay_score > 0:
            parts.append(f"时间衰减: {self.time_decay_score:.3f}")
        if self.foreshadowing_score > 0:
            parts.append(f"伏笔关联: {self.foreshadowing_score:.3f}")
        if self.character_relevance_score > 0:
            parts.append(f"角色相关: {self.character_relevance_score:.3f}")
        return " | ".join(parts)


class RetrievedItem(BaseModel):
    """检索结果项"""
    # 基本信息
    memory_type: MemoryType = Field(..., description="记忆类型")
    source_id: str = Field(..., description="来源 ID")
    content: str = Field(..., description="内容")
    
    # 元数据
    chapter_number: Optional[int] = Field(None, description="来源章节号")
    character_names: List[str] = Field(default_factory=list, description="涉及角色")
    location_names: List[str] = Field(default_factory=list, description="涉及地点")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    
    # 得分
    score: RetrievalScore = Field(default_factory=RetrievalScore, description="检索得分")
    
    # 内容属性
    priority: ContentPriority = Field(default=ContentPriority.NORMAL, description="优先级")
    content_type: ContentType = Field(default=ContentType.SUMMARY, description="内容类型")
    original_length: int = Field(default=0, description="原始长度")
    
    # 可追溯性
    retrieval_method: RetrievalMethod = Field(default=RetrievalMethod.VECTOR, description="检索方法")
    retrieval_reason: str = Field(default="", description="检索原因说明")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "memory_type": self.memory_type.value,
            "source_id": self.source_id,
            "content": self.content,
            "chapter_number": self.chapter_number,
            "character_names": self.character_names,
            "score": self.score.total_score,
            "priority": self.priority.value,
            "retrieval_reason": self.retrieval_reason,
        }


class RetrievalResult(BaseModel):
    """检索结果集合"""
    # 检索信息
    query: str = Field(default="", description="检索查询")
    chapter_id: str = Field(default="", description="目标章节 ID")
    chapter_number: int = Field(default=0, description="目标章节号")
    
    # 检索结果（按类型分组）
    items: List[RetrievedItem] = Field(default_factory=list, description="所有检索结果")
    
    # 统计信息
    total_items: int = Field(default=0, description="总检索项数")
    by_type: Dict[str, int] = Field(default_factory=dict, description="按类型统计")
    by_priority: Dict[str, int] = Field(default_factory=dict, description="按优先级统计")
    
    # 检索耗时
    retrieval_time_ms: float = Field(default=0.0, description="检索耗时（毫秒）")
    
    # 使用的策略
    strategy_name: str = Field(default="", description="使用的检索策略")
    strategy_params: Dict[str, Any] = Field(default_factory=dict, description="策略参数")
    
    def add_item(self, item: RetrievedItem) -> None:
        """添加检索项"""
        self.items.append(item)
        self.total_items = len(self.items)
        
        # 更新统计
        type_key = item.memory_type.value
        self.by_type[type_key] = self.by_type.get(type_key, 0) + 1
        
        priority_key = item.priority.value
        self.by_priority[priority_key] = self.by_priority.get(priority_key, 0) + 1
    
    def get_items_by_type(self, memory_type: MemoryType) -> List[RetrievedItem]:
        """获取指定类型的检索项"""
        return [item for item in self.items if item.memory_type == memory_type]
    
    def get_items_by_priority(self, priority: ContentPriority) -> List[RetrievedItem]:
        """获取指定优先级的检索项"""
        return [item for item in self.items if item.priority == priority]
    
    def sort_by_score(self) -> None:
        """按得分排序"""
        self.items.sort(key=lambda x: (
            # 先按优先级排序
            {"critical": 0, "high": 1, "normal": 2, "low": 3}.get(x.priority.value, 2),
            # 再按得分排序
            -x.score.total_score,
        ))
    
    def get_explanation(self) -> str:
        """获取检索结果说明"""
        lines = [
            f"检索结果: {self.total_items} 项",
            f"查询: {self.query[:50]}..." if len(self.query) > 50 else f"查询: {self.query}",
            f"策略: {self.strategy_name}",
            "",
            "按类型统计:",
        ]
        
        for type_name, count in sorted(self.by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  - {type_name}: {count}")
        
        lines.append("")
        lines.append("高分项:")
        
        for item in self.items[:5]:
            lines.append(f"  - [{item.memory_type.value}] {item.content[:30]}... (得分: {item.score.total_score:.3f})")
        
        return "\n".join(lines)


# =============================================================================
# 上下文包结构
# =============================================================================

class ContextSection(BaseModel):
    """上下文段落"""
    section_name: str = Field(..., description="段落名称")
    section_type: MemoryType = Field(..., description="段落类型")
    content: str = Field(..., description="段落内容")
    items: List[RetrievedItem] = Field(default_factory=list, description="来源项")
    total_length: int = Field(default=0, description="总长度")
    compressed: bool = Field(default=False, description="是否已压缩")
    
    def to_prompt_text(self) -> str:
        """生成 Prompt 文本"""
        if not self.content:
            return ""
        
        header = f"=== {self.section_name} ==="
        return f"{header}\n{self.content}"


class ContextPackage(BaseModel):
    """上下文包"""
    # 基本信息
    chapter_id: str = Field(default="", description="章节 ID")
    chapter_number: int = Field(default=0, description="章节号")
    target_word_count: int = Field(default=3000, description="目标字数")
    
    # 段落（按优先级排序）
    sections: List[ContextSection] = Field(default_factory=list, description="上下文段落")
    
    # 统计
    total_length: int = Field(default=0, description="总长度")
    max_length: int = Field(default=8000, description="最大长度")
    
    # 压缩信息
    compression_ratio: float = Field(default=1.0, description="压缩比例")
    truncated_items: int = Field(default=0, description="截断项数")
    
    # 检索信息
    retrieval_result: Optional[RetrievalResult] = Field(None, description="检索结果")
    
    def add_section(self, section: ContextSection) -> None:
        """添加段落"""
        self.sections.append(section)
        self._recalculate_length()
    
    def _recalculate_length(self) -> None:
        """重新计算总长度"""
        self.total_length = sum(s.total_length for s in self.sections)
    
    def to_prompt_text(self) -> str:
        """生成完整 Prompt 文本"""
        parts = []
        
        for section in self.sections:
            text = section.to_prompt_text()
            if text:
                parts.append(text)
        
        return "\n\n".join(parts)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_length": self.total_length,
            "max_length": self.max_length,
            "compression_ratio": self.compression_ratio,
            "section_count": len(self.sections),
            "truncated_items": self.truncated_items,
            "sections": [
                {
                    "name": s.section_name,
                    "length": s.total_length,
                    "type": s.section_type.value,
                }
                for s in self.sections
            ],
        }


# =============================================================================
# 检索策略定义
# =============================================================================

class RetrievalStrategy(str, Enum):
    """检索策略"""
    # 基础策略
    RECENT_ONLY = "recent_only"             # 仅最近记忆
    BALANCED_REFERENCE = "balanced_reference"  # 均衡参考
    DEEP_DIVE = "deep_dive"                 # 深度挖掘
    
    # 场景策略
    CHARACTER_FOCUSED = "character_focused"  # 角色聚焦
    PLOT_FOCUSED = "plot_focused"           # 剧情聚焦
    WORLD_FOCUSED = "world_focused"         # 世界观聚焦
    
    # 特殊策略
    RESOLUTION = "resolution"               # 伏笔收束（完结章节）
    FLASHBACK = "flashback"                 # 回忆场景
    FAST_TRACK = "fast_track"               # 快速通道（最小上下文）


class RetrievalStrategyConfig(BaseModel):
    """检索策略配置"""
    strategy_name: RetrievalStrategy = Field(
        default=RetrievalStrategy.BALANCED_REFERENCE,
        description="策略名称"
    )
    
    # RAG 参数
    top_k: int = Field(default=5, ge=1, le=20, description="检索数量")
    semantic_weight: float = Field(default=0.6, ge=0.0, le=1.0, description="语义权重")
    time_decay_weight: float = Field(default=0.2, ge=0.0, le=1.0, description="时间衰减权重")
    foreshadowing_weight: float = Field(default=0.2, ge=0.0, le=1.0, description="伏笔权重")
    decay_factor: float = Field(default=0.1, ge=0.0, description="衰减系数")
    
    # 类型权重
    type_weights: Dict[str, float] = Field(
        default_factory=lambda: {
            "character_state": 1.5,
            "relationship_state": 1.3,
            "open_hook": 1.4,
            "memory_chunk": 1.0,
            "world_snapshot": 1.2,
        },
        description="类型权重"
    )
    
    # 上下文限制
    max_context_length: int = Field(default=8000, description="最大上下文长度")
    max_items_per_type: int = Field(default=5, description="每类型最大项数")
    
    # 功能开关
    enable_character_priority: bool = Field(default=True, description="角色优先")
    enable_hook_boost: bool = Field(default=True, description="伏笔加成")
    enable_dedup: bool = Field(default=True, description="去重")
    
    def get_type_weight(self, memory_type: MemoryType) -> float:
        """获取类型权重"""
        return self.type_weights.get(memory_type.value, 1.0)


# 预定义策略配置
STRATEGY_PRESETS = {
    RetrievalStrategy.RECENT_ONLY: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.RECENT_ONLY,
        top_k=3,
        semantic_weight=0.4,
        time_decay_weight=0.5,
        foreshadowing_weight=0.1,
        decay_factor=0.3,
        max_context_length=5000,
    ),
    RetrievalStrategy.BALANCED_REFERENCE: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.BALANCED_REFERENCE,
        top_k=5,
        semantic_weight=0.6,
        time_decay_weight=0.2,
        foreshadowing_weight=0.2,
        decay_factor=0.1,
        max_context_length=8000,
    ),
    RetrievalStrategy.DEEP_DIVE: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.DEEP_DIVE,
        top_k=10,
        semantic_weight=0.5,
        time_decay_weight=0.15,
        foreshadowing_weight=0.35,
        decay_factor=0.05,
        max_context_length=12000,
    ),
    RetrievalStrategy.CHARACTER_FOCUSED: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.CHARACTER_FOCUSED,
        top_k=6,
        semantic_weight=0.5,
        time_decay_weight=0.2,
        foreshadowing_weight=0.15,
        decay_factor=0.15,
        type_weights={
            "character_state": 2.0,
            "relationship_state": 1.8,
            "open_hook": 1.2,
            "memory_chunk": 0.8,
            "world_snapshot": 0.6,
        },
        enable_character_priority=True,
    ),
    RetrievalStrategy.PLOT_FOCUSED: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.PLOT_FOCUSED,
        top_k=7,
        semantic_weight=0.5,
        time_decay_weight=0.15,
        foreshadowing_weight=0.35,
        decay_factor=0.1,
        type_weights={
            "character_state": 1.0,
            "relationship_state": 1.0,
            "open_hook": 2.0,
            "plot_ledger": 1.8,
            "memory_chunk": 1.2,
            "world_snapshot": 0.8,
        },
    ),
    RetrievalStrategy.RESOLUTION: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.RESOLUTION,
        top_k=8,
        semantic_weight=0.4,
        time_decay_weight=0.1,
        foreshadowing_weight=0.5,
        decay_factor=0.05,
        type_weights={
            "open_hook": 3.0,
            "plot_ledger": 2.0,
            "memory_chunk": 1.0,
            "character_state": 1.2,
        },
        enable_hook_boost=True,
    ),
    RetrievalStrategy.FAST_TRACK: RetrievalStrategyConfig(
        strategy_name=RetrievalStrategy.FAST_TRACK,
        top_k=3,
        semantic_weight=0.7,
        time_decay_weight=0.2,
        foreshadowing_weight=0.1,
        decay_factor=0.2,
        max_context_length=4000,
        max_items_per_type=2,
    ),
}

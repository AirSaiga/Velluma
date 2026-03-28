# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
增强型伏笔闭环机制 (Enhanced Foreshadowing Closure System)

职责：
- 智能伏笔生命周期管理：创建 → 追踪 → 部分/完全闭合 → 归档
- 多维度伏笔召回：优先级、开放时长、角色关联
- 章节审阅阶段的伏笔遗漏检测
- 未闭合伏笔自动流转到下一章上下文
- 伏笔向量化和语义检索支持

设计原则：
1. 伏笔有明确的生命周期和状态机
2. 主线伏笔必须闭合，支线可选择性闭合
3. 开放时长越长，召回优先级越高
4. 伏笔遗漏需在审阅阶段明确提示

伏笔生命周期：
┌─────────────────────────────────────────────────────────────┐
│                    伏笔状态机                                │
├─────────────────────────────────────────────────────────────┤
│   CREATED → OPEN → ADDRESSED → CLOSED                       │
│      ↓         ↓         ↓                                  │
│   DROPPED  DROPPED  DROPPED                                 │
├─────────────────────────────────────────────────────────────┤
│   状态说明：                                                 │
│   - CREATED: 刚创建，尚未在文本中出现                        │
│   - OPEN: 已埋下伏笔，等待后续章节揭示                       │
│   - ADDRESSED: 已被部分提及，但未完全闭合                    │
│   - CLOSED: 伏笔已完全揭示                                   │
│   - DROPPED: 被废弃（作者主动放弃或因情节变更）              │
└─────────────────────────────────────────────────────────────┘
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum
from pydantic import BaseModel, Field
from uuid import UUID, uuid4
from dataclasses import dataclass, field

from sqlalchemy import select, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PlotLedger, Chapter, Book, MemoryChunk
from backend.services.rag.retrieval_types import (
    RetrievedItem,
    RetrievalResult,
    MemoryType,
    ContentPriority,
    ContentType,
    RetrievalScore,
    RetrievalMethod,
)


logger = logging.getLogger(__name__)


# =============================================================================
# 伏笔状态定义
# =============================================================================

class HookStatus(str, Enum):
    """伏笔状态"""
    CREATED = "created"           # 已创建，未在文本出现
    OPEN = "open"                 # 开放中
    ADDRESSED = "addressed"       # 已被提及，未完全闭合
    CLOSED = "closed"             # 已闭合
    DROPPED = "dropped"           # 已放弃


class HookPriority(str, Enum):
    """伏笔优先级"""
    MAIN_PLOT = "main_plot"       # 主线伏笔（必须闭合）
    SUB_PLOT = "sub_plot"         # 支线伏笔
    ATMOSPHERE = "atmosphere"     # 氛围伏笔（可选闭合）
    DETAIL = "detail"             # 细节伏笔
    WORLD_BUILDING = "world_building"  # 世界观伏笔


class HookClosureType(str, Enum):
    """伏笔闭合类型"""
    EXPLICIT = "explicit"         # 明确揭示
    IMPLICIT = "implicit"         # 隐含揭示
    PARTIAL = "partial"           # 部分揭示
    ABANDONED = "abandoned"       # 放弃揭示


# =============================================================================
# 伏笔数据结构
# =============================================================================

class HookMetadata(BaseModel):
    """伏笔元数据"""
    # 基础信息
    hook_id: str = Field(default="", description="伏笔 ID")
    ledger_key: str = Field(default="", description="账本键")
    content: str = Field(default="", description="伏笔内容")
    
    # 状态信息
    status: HookStatus = Field(default=HookStatus.OPEN, description="状态")
    priority: HookPriority = Field(default=HookPriority.SUB_PLOT, description="优先级")
    closure_type: Optional[HookClosureType] = Field(None, description="闭合类型")
    
    # 章节信息
    created_at_chapter: int = Field(default=0, description="创建章节")
    addressed_at_chapters: List[int] = Field(default_factory=list, description="提及章节")
    closed_at_chapter: Optional[int] = Field(None, description="闭合章节")
    
    # 关联信息
    character_names: List[str] = Field(default_factory=list, description="涉及角色")
    location_names: List[str] = Field(default_factory=list, description="涉及地点")
    keywords: List[str] = Field(default_factory=list, description="关键词")
    
    # 追踪信息
    mention_count: int = Field(default=0, description="提及次数")
    last_mention_chapter: Optional[int] = Field(None, description="最后提及章节")
    
    # 评分
    urgency_score: float = Field(default=0.0, description="紧急度")
    relevance_score: float = Field(default=0.0, description="相关度")


class HookDetectionResult(BaseModel):
    """伏笔检测结果"""
    hook_id: str
    ledger_key: str = ""
    content: str
    
    # 检测信息
    detected_in_chapter: int = 0
    detection_confidence: float = 0.0
    detection_method: str = ""
    
    # 匹配信息
    matched_text: str = ""
    match_type: str = ""  # keyword, semantic, character
    
    # 状态变更
    suggested_status: Optional[HookStatus] = None
    is_closure: bool = False


class HookClosureCheckResult(BaseModel):
    """伏笔闭合检查结果"""
    hook_id: str
    hook_content: str
    
    # 检查结果
    is_addressed: bool = False
    is_closed: bool = False
    
    # 回应信息
    addressed_in_text: str = ""
    closure_type: str = ""
    
    # 建议
    suggestion: str = ""
    severity: str = "info"  # info, minor, major, critical


# =============================================================================
# 伏笔评分配置
# =============================================================================

@dataclass
class HookScoringConfig:
    """伏笔评分配置"""
    # 紧急度权重
    open_duration_weight: float = 0.3      # 开放时长权重
    priority_weight: float = 0.25          # 优先级权重
    mention_count_weight: float = 0.15     # 提及次数权重
    
    # 优先级得分
    main_plot_score: float = 1.0
    sub_plot_score: float = 0.7
    atmosphere_score: float = 0.4
    detail_score: float = 0.2
    
    # 开放时长阈值
    urgent_threshold: int = 10             # 紧急阈值（章节数）
    attention_threshold: int = 5           # 关注阈值
    
    # 角色关联加成
    character_match_bonus: float = 0.2


# =============================================================================
# 增强型伏笔追踪器
# =============================================================================

class EnhancedForeshadowingTracker:
    """
    增强型伏笔追踪器
    
    职责：
    - 追踪伏笔在各章节中的完整生命周期
    - 计算伏笔召回优先级
    - 检测伏笔闭合情况
    - 提供伏笔遗漏报告
    """
    
    # 闭合检测模式
    CLOSURE_PATTERNS = [
        r"原来.*是",
        r"终于.*明白",
        r"真相.*大白",
        r"终于.*知道",
        r"原来如此",
        r"一切.*都.*解释",
        r"终于.*揭开",
        r"秘密.*揭开",
        r"谜底.*揭开",
        r"原来.*一直",
        r"终于.*发现",
        r"才知道",
    ]
    
    # 部分提及模式
    ADDRESS_PATTERNS = [
        r"想起",
        r"回忆起",
        r"想起.*说过",
        r"曾.*提到",
        r"记得",
        r"依稀记得",
        r"仿佛记得",
    ]
    
    def __init__(
        self,
        db: AsyncSession,
        scoring_config: Optional[HookScoringConfig] = None,
    ):
        self.db = db
        self.config = scoring_config or HookScoringConfig()
    
    async def get_open_hooks(
        self,
        book_id: UUID,
        before_chapter: int,
        include_addressed: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        获取指定章节前的所有开放伏笔
        
        Args:
            book_id: 书籍 ID
            before_chapter: 章节号（不含）
            include_addressed: 是否包含已提及但未闭合的伏笔
            
        Returns:
            List[Dict]: 开放伏笔列表，按紧急度排序
        """
        # 构建查询条件
        statuses = [HookStatus.OPEN.value]
        if include_addressed:
            statuses.append(HookStatus.ADDRESSED.value)
        
        stmt = select(PlotLedger).where(
            PlotLedger.book_id == book_id,
            PlotLedger.status.in_(statuses),
            PlotLedger.created_at_chapter < before_chapter,
        ).order_by(PlotLedger.created_at_chapter.desc())
        
        result = await self.db.execute(stmt)
        hooks = result.scalars().all()
        
        # 转换并计算紧急度
        hook_list = []
        for hook in hooks:
            metadata = self._build_hook_metadata(hook, before_chapter)
            hook_list.append({
                "hook_id": str(hook.id),
                "ledger_key": hook.ledger_key or "",
                "content": hook.content or "",
                "chapter_number": hook.created_at_chapter or 0,
                "priority": metadata.priority.value,
                "status": metadata.status.value,
                "urgency_score": metadata.urgency_score,
                "character_names": metadata.character_names,
                "keywords": metadata.keywords,
            })
        
        # 按紧急度排序
        hook_list.sort(key=lambda x: -x.get("urgency_score", 0))
        
        return hook_list
    
    async def detect_hooks_in_text(
        self,
        text: str,
        open_hooks: List[Dict[str, Any]],
        chapter_number: int,
    ) -> List[HookDetectionResult]:
        """
        检测文本中的伏笔回应
        
        Args:
            text: 章节文本
            open_hooks: 开放伏笔列表
            chapter_number: 当前章节号
            
        Returns:
            List[HookDetectionResult]: 检测结果
        """
        results = []
        text_lower = text.lower()
        
        for hook in open_hooks:
            content = hook.get("content", "")
            if not content:
                continue
            
            # 多维度检测
            detection = await self._detect_single_hook(
                text, text_lower, hook, chapter_number
            )
            
            if detection:
                results.append(detection)
        
        return results
    
    async def _detect_single_hook(
        self,
        text: str,
        text_lower: str,
        hook: Dict[str, Any],
        chapter_number: int,
    ) -> Optional[HookDetectionResult]:
        """检测单个伏笔"""
        content = hook.get("content", "")
        hook_id = hook.get("hook_id", "")
        ledger_key = hook.get("ledger_key", "")
        
        # 1. 关键词匹配
        keywords = self._extract_keywords(content)
        matched_keywords = [kw for kw in keywords if kw.lower() in text_lower]
        
        # 2. 角色匹配
        hook_characters = hook.get("character_names", [])
        matched_characters = [c for c in hook_characters if c.lower() in text_lower]
        
        # 3. 计算匹配度
        keyword_score = len(matched_keywords) / max(1, len(keywords))
        character_score = len(matched_characters) / max(1, len(hook_characters))
        combined_score = 0.6 * keyword_score + 0.4 * character_score
        
        if combined_score < 0.2:
            return None
        
        # 4. 判断是否为闭合
        is_closure = False
        matched_text = ""
        
        for pattern in self.CLOSURE_PATTERNS:
            match = re.search(pattern, text)
            if match and combined_score > 0.3:
                is_closure = True
                matched_text = self._extract_context(text, match.start(), 50)
                break
        
        # 5. 判断是否为部分提及
        if not is_closure and combined_score > 0.3:
            for pattern in self.ADDRESS_PATTERNS:
                match = re.search(pattern, text)
                if match:
                    matched_text = self._extract_context(text, match.start(), 50)
                    break
        
        if not matched_text and matched_keywords:
            # 提取关键词上下文
            for kw in matched_keywords:
                idx = text_lower.find(kw.lower())
                if idx >= 0:
                    matched_text = self._extract_context(text, idx, 30)
                    break
        
        # 6. 确定建议状态
        suggested_status = None
        if is_closure:
            suggested_status = HookStatus.CLOSED
        elif combined_score > 0.3 and matched_text:
            suggested_status = HookStatus.ADDRESSED
        
        return HookDetectionResult(
            hook_id=hook_id,
            ledger_key=ledger_key,
            content=content,
            detected_in_chapter=chapter_number,
            detection_confidence=combined_score,
            detection_method="multi_dimension",
            matched_text=matched_text,
            match_type="closure" if is_closure else "address",
            suggested_status=suggested_status,
            is_closure=is_closure,
        )
    
    async def check_closure(
        self,
        text: str,
        open_hooks: List[Dict[str, Any]],
        chapter_number: int,
    ) -> List[HookClosureCheckResult]:
        """
        检查伏笔闭合情况
        
        Args:
            text: 章节文本
            open_hooks: 开放伏笔列表
            chapter_number: 当前章节号
            
        Returns:
            List[HookClosureCheckResult]: 闭合检查结果
        """
        results = []
        
        # 先检测伏笔提及
        detections = await self.detect_hooks_in_text(text, open_hooks, chapter_number)
        detection_map = {d.hook_id: d for d in detections}
        
        for hook in open_hooks:
            hook_id = hook.get("hook_id", "")
            content = hook.get("content", "")
            priority = hook.get("priority", HookPriority.SUB_PLOT.value)
            created_chapter = hook.get("chapter_number", 0)
            
            detection = detection_map.get(hook_id)
            
            # 计算开放时长
            open_duration = chapter_number - created_chapter
            
            # 确定严重性
            severity = self._calculate_severity(priority, open_duration, detection)
            
            result = HookClosureCheckResult(
                hook_id=hook_id,
                hook_content=content,
                is_addressed=detection is not None and detection.detection_confidence > 0.2,
                is_closed=detection is not None and detection.is_closure,
                addressed_in_text=detection.matched_text if detection else "",
                closure_type=detection.match_type if detection else "",
                suggestion=self._generate_suggestion(priority, open_duration, detection),
                severity=severity,
            )
            
            results.append(result)
        
        return results
    
    async def update_hook_status(
        self,
        hook_id: UUID,
        new_status: HookStatus,
        chapter_number: Optional[int] = None,
        closure_note: str = "",
    ) -> bool:
        """
        更新伏笔状态
        
        Args:
            hook_id: 伏笔 ID
            new_status: 新状态
            chapter_number: 相关章节号
            closure_note: 闭合说明
            
        Returns:
            bool: 是否成功
        """
        try:
            stmt = select(PlotLedger).where(PlotLedger.id == hook_id)
            result = await self.db.execute(stmt)
            hook = result.scalar_one_or_none()
            
            if not hook:
                return False
            
            hook.status = new_status.value
            
            if new_status == HookStatus.CLOSED and chapter_number:
                hook.resolved_in_chapter_id = None  # 需要查询章节 ID
            
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"[EnhancedForeshadowingTracker] 更新伏笔状态失败: {e}")
            return False
    
    def _build_hook_metadata(
        self,
        hook: PlotLedger,
        current_chapter: int,
    ) -> HookMetadata:
        """构建伏笔元数据"""
        metadata = HookMetadata(
            hook_id=str(hook.id),
            ledger_key=hook.ledger_key or "",
            content=hook.content or "",
            created_at_chapter=hook.created_at_chapter or 0,
        )
        
        # 解析状态
        metadata.status = HookStatus(hook.status) if hook.status in [s.value for s in HookStatus] else HookStatus.OPEN
        
        # 解析优先级（从 meta 字段）
        if hook.meta and isinstance(hook.meta, dict):
            priority_str = hook.meta.get("priority", "")
            if priority_str:
                try:
                    metadata.priority = HookPriority(priority_str)
                except ValueError:
                    pass
            
            metadata.character_names = hook.meta.get("characters", [])
            metadata.location_names = hook.meta.get("locations", [])
            metadata.keywords = hook.meta.get("keywords", [])
        
        # 计算紧急度
        metadata.urgency_score = self._calculate_urgency(
            metadata.priority,
            metadata.created_at_chapter,
            current_chapter,
            metadata.mention_count,
        )
        
        return metadata
    
    def _calculate_urgency(
        self,
        priority: HookPriority,
        created_chapter: int,
        current_chapter: int,
        mention_count: int,
    ) -> float:
        """计算伏笔紧急度"""
        # 开放时长得分
        open_duration = current_chapter - created_chapter
        duration_score = min(1.0, open_duration / self.config.urgent_threshold)
        
        # 优先级得分
        priority_scores = {
            HookPriority.MAIN_PLOT: self.config.main_plot_score,
            HookPriority.SUB_PLOT: self.config.sub_plot_score,
            HookPriority.ATMOSPHERE: self.config.atmosphere_score,
            HookPriority.DETAIL: self.config.detail_score,
            HookPriority.WORLD_BUILDING: self.config.atmosphere_score,
        }
        priority_score = priority_scores.get(priority, 0.5)
        
        # 提及次数得分（提及越多越紧急）
        mention_score = min(1.0, mention_count * 0.2)
        
        # 综合得分
        urgency = (
            self.config.open_duration_weight * duration_score +
            self.config.priority_weight * priority_score +
            self.config.mention_count_weight * mention_score
        )
        
        return min(1.0, urgency)
    
    def _calculate_severity(
        self,
        priority: str,
        open_duration: int,
        detection: Optional[HookDetectionResult],
    ) -> str:
        """计算问题严重性"""
        if detection and detection.is_closure:
            return "info"  # 已闭合
        
        # 主线伏笔
        if priority == HookPriority.MAIN_PLOT.value:
            if open_duration >= 8:
                return "critical"
            elif open_duration >= 5:
                return "major"
            elif open_duration >= 3:
                return "minor"
        
        # 支线伏笔
        elif priority == HookPriority.SUB_PLOT.value:
            if open_duration >= 10:
                return "major"
            elif open_duration >= 6:
                return "minor"
        
        # 其他
        else:
            if open_duration >= 15:
                return "minor"
        
        return "info"
    
    def _generate_suggestion(
        self,
        priority: str,
        open_duration: int,
        detection: Optional[HookDetectionResult],
    ) -> str:
        """生成处理建议"""
        if detection and detection.is_closure:
            return "伏笔已闭合"
        
        if detection and detection.detection_confidence > 0.3:
            return "伏笔已被提及，可考虑在后续章节完全闭合"
        
        if priority == HookPriority.MAIN_PLOT.value:
            if open_duration >= 5:
                return f"主线伏笔已开放{open_duration}章，建议优先安排闭合情节"
            return "主线伏笔需在近期章节中闭合"
        
        elif priority == HookPriority.SUB_PLOT.value:
            if open_duration >= 8:
                return f"支线伏笔已开放{open_duration}章，建议安排回应情节"
            return "建议在后续章节中逐步揭示"
        
        else:
            return "可作为背景线索或选择性处理"
    
    def _extract_keywords(self, content: str) -> List[str]:
        """提取关键词"""
        words = re.findall(r'[\u4e00-\u9fa5]{2,}', content)
        stop_words = {"这时", "那里", "这个", "那个", "什么", "怎么", "虽然", "但是", "一个"}
        return [w for w in words if w not in stop_words]
    
    def _extract_context(self, text: str, position: int, radius: int) -> str:
        """提取上下文"""
        start = max(0, position - radius)
        end = min(len(text), position + radius)
        return text[start:end]


# =============================================================================
# 伏笔遗漏检测器
# =============================================================================

class EnhancedHookOmissionDetector:
    """
    增强型伏笔遗漏检测器
    
    职责：
    - 在审阅阶段检测伏笔遗漏
    - 评估遗漏的严重性
    - 提供修复建议
    - 生成遗漏报告
    """
    
    def __init__(self, tracker: EnhancedForeshadowingTracker):
        self.tracker = tracker
    
    async def detect_omissions(
        self,
        text: str,
        book_id: UUID,
        chapter_number: int,
    ) -> List[Dict[str, Any]]:
        """
        检测伏笔遗漏
        
        Args:
            text: 章节文本
            book_id: 书籍 ID
            chapter_number: 章节号
            
        Returns:
            List[Dict]: 遗漏报告
        """
        # 获取开放伏笔
        open_hooks = await self.tracker.get_open_hooks(book_id, chapter_number)
        
        if not open_hooks:
            return []
        
        # 检查闭合情况
        closure_results = await self.tracker.check_closure(
            text, open_hooks, chapter_number
        )
        
        omissions = []
        
        for result in closure_results:
            # 获取伏笔信息
            hook_info = next(
                (h for h in open_hooks if h.get("hook_id") == result.hook_id),
                {}
            )
            
            # 已闭合，不是遗漏
            if result.is_closed:
                continue
            
            # 判断是否为遗漏
            is_omission, severity = self._is_omission(
                hook_info, result, chapter_number
            )
            
            if is_omission:
                omissions.append({
                    "hook_id": result.hook_id,
                    "content": result.hook_content,
                    "priority": hook_info.get("priority", HookPriority.SUB_PLOT.value),
                    "open_duration": chapter_number - hook_info.get("chapter_number", 0),
                    "severity": severity,
                    "is_addressed": result.is_addressed,
                    "suggestion": result.suggestion,
                    "urgency_score": hook_info.get("urgency_score", 0),
                })
        
        # 按严重性和紧急度排序
        severity_order = {"critical": 0, "major": 1, "minor": 2, "info": 3}
        omissions.sort(key=lambda x: (
            severity_order.get(x.get("severity", "info"), 3),
            -x.get("urgency_score", 0),
        ))
        
        return omissions
    
    def _is_omission(
        self,
        hook_info: Dict[str, Any],
        closure_result: HookClosureCheckResult,
        chapter_number: int,
    ) -> Tuple[bool, str]:
        """判断是否为遗漏"""
        priority = hook_info.get("priority", HookPriority.SUB_PLOT.value)
        created_chapter = hook_info.get("chapter_number", 0)
        open_duration = chapter_number - created_chapter
        
        # 主线伏笔
        if priority == HookPriority.MAIN_PLOT.value:
            if open_duration >= 5:
                return True, "critical"
            elif open_duration >= 3:
                return True, "major"
            elif open_duration >= 2 and not closure_result.is_addressed:
                return True, "minor"
        
        # 支线伏笔
        elif priority == HookPriority.SUB_PLOT.value:
            if open_duration >= 8:
                return True, "major"
            elif open_duration >= 5:
                return True, "minor"
        
        # 世界观伏笔
        elif priority == HookPriority.WORLD_BUILDING.value:
            if open_duration >= 12:
                return True, "minor"
        
        # 氛围/细节伏笔
        else:
            if open_duration >= 15:
                return True, "info"
        
        return False, "info"
    
    def get_repair_suggestion(self, omission: Dict[str, Any]) -> str:
        """获取修复建议"""
        priority = omission.get("priority", "")
        content = omission.get("content", "")
        is_addressed = omission.get("is_addressed", False)
        open_duration = omission.get("open_duration", 0)
        
        if priority == HookPriority.MAIN_PLOT.value:
            if is_addressed:
                return f"主线伏笔「{content[:20]}...」已提及，建议在下一章明确闭合"
            return f"主线伏笔「{content[:20]}...」已开放{open_duration}章，需优先安排揭示情节"
        
        elif priority == HookPriority.SUB_PLOT.value:
            if is_addressed:
                return f"支线伏笔「{content[:20]}...」已提及，可在未来2-3章内闭合"
            return f"支线伏笔「{content[:20]}...」建议在近期章节中回应"
        
        else:
            if is_addressed:
                return f"伏笔「{content[:20]}...」可作为背景线索继续铺垫"
            return f"伏笔「{content[:20]}...」可作为选择性处理或忽略"


# =============================================================================
# 伏笔记忆注入器
# =============================================================================

class EnhancedHookMemoryInjector:
    """
    增强型伏笔记忆注入器
    
    职责：
    - 将新创建的伏笔注入记忆系统
    - 为伏笔生成向量表示
    - 确保伏笔可被语义检索召回
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def inject_hook_to_memory(
        self,
        hook: PlotLedger,
        embedding_func: Optional[callable] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> bool:
        """
        将伏笔注入记忆系统
        
        Args:
            hook: 伏笔实体
            embedding_func: 向量化函数
            api_key: API Key
            base_url: Base URL
            
        Returns:
            bool: 是否成功
        """
        try:
            # 检查是否已存在
            stmt = select(MemoryChunk).where(
                MemoryChunk.book_id == hook.book_id,
                MemoryChunk.chunk_text == hook.content,
            )
            result = await self.db.execute(stmt)
            existing = result.scalar_one_or_none()
            
            if existing:
                logger.debug(f"[HookMemoryInjector] 伏笔记忆已存在: {hook.id}")
                return True
            
            # 创建记忆块
            memory = MemoryChunk(
                book_id=hook.book_id,
                chapter_id=hook.chapter_id,
                chunk_text=hook.content,
            )
            
            # 获取向量
            if embedding_func and api_key and hook.content:
                try:
                    embedding = await embedding_func(
                        hook.content, api_key, base_url
                    )
                    if embedding:
                        memory.embedding = embedding
                except Exception as e:
                    logger.warning(f"[HookMemoryInjector] 获取向量失败: {e}")
            
            self.db.add(memory)
            await self.db.commit()
            
            logger.info(f"[HookMemoryInjector] 伏笔已注入记忆系统: {hook.id}")
            return True
            
        except Exception as e:
            logger.error(f"[HookMemoryInjector] 注入失败: {e}")
            return False


# =============================================================================
# 便捷函数
# =============================================================================

async def create_and_track_hook(
    db: AsyncSession,
    book_id: UUID,
    chapter_id: Optional[UUID],
    content: str,
    created_at_chapter: int,
    ledger_key: str = "",
    priority: HookPriority = HookPriority.SUB_PLOT,
    character_names: List[str] = None,
) -> Optional[PlotLedger]:
    """
    便捷函数：创建并追踪伏笔
    
    Args:
        db: 数据库会话
        book_id: 书籍 ID
        chapter_id: 章节 ID
        content: 伏笔内容
        created_at_chapter: 创建章节号
        ledger_key: 账本键
        priority: 优先级
        character_names: 涉及角色
        
    Returns:
        Optional[PlotLedger]: 创建的伏笔实体
    """
    try:
        meta = {
            "priority": priority.value,
            "characters": character_names or [],
            "keywords": re.findall(r'[\u4e00-\u9fa5]{2,}', content),
        }
        
        hook = PlotLedger(
            book_id=book_id,
            chapter_id=chapter_id,
            content=content,
            ledger_key=ledger_key or f"hook-{uuid4().hex[:8]}",
            status=HookStatus.OPEN.value,
            created_at_chapter=created_at_chapter,
            meta=meta,
        )
        
        db.add(hook)
        await db.commit()
        
        # 注入记忆系统
        injector = EnhancedHookMemoryInjector(db)
        await injector.inject_hook_to_memory(hook)
        
        logger.info(f"[create_and_track_hook] 伏笔已创建: {hook.id}")
        return hook
        
    except Exception as e:
        logger.error(f"[create_and_track_hook] 创建失败: {e}")
        return None


async def get_hooks_for_chapter_context(
    db: AsyncSession,
    book_id: UUID,
    chapter_number: int,
    max_hooks: int = 10,
) -> List[RetrievedItem]:
    """
    获取章节上下文所需的伏笔检索项
    
    Args:
        db: 数据库会话
        book_id: 书籍 ID
        chapter_number: 章节号
        max_hooks: 最大伏笔数
        
    Returns:
        List[RetrievedItem]: 伏笔检索项列表
    """
    tracker = EnhancedForeshadowingTracker(db)
    open_hooks = await tracker.get_open_hooks(book_id, chapter_number)
    
    items = []
    for hook in open_hooks[:max_hooks]:
        item = RetrievedItem(
            memory_type=MemoryType.OPEN_HOOK,
            source_id=hook.get("hook_id", ""),
            content=hook.get("content", ""),
            chapter_number=hook.get("chapter_number", 0),
            character_names=hook.get("character_names", []),
            keywords=hook.get("keywords", []),
            priority=ContentPriority.HIGH,
            content_type=ContentType.FULL_TEXT,
            original_length=len(hook.get("content", "")),
            retrieval_method=RetrievalMethod.EXACT,
            retrieval_reason="未闭合伏笔",
        )
        
        # 设置得分
        item.score.urgency_score = hook.get("urgency_score", 0)
        item.score.total_score = hook.get("urgency_score", 0)
        
        items.append(item)
    
    return items

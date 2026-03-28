# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
伏笔闭环机制 (Foreshadowing Closure System)

职责：
- 伏笔创建时自动进入记忆系统
- 伏笔在后续章节召回与追踪
- 伏笔闭合检测与状态更新
- 审阅阶段识别伏笔遗漏
- 未闭合伏笔自动进入下一章上下文

设计原则：
1. 伏笔有明确的生命周期：创建 → 开放 → 部分/完全闭合 → 归档
2. 伏笔召回优先级高于普通记忆
3. 伏笔遗漏需要在审阅阶段明确提示
4. 伏笔闭合需要明确的章节事件
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from enum import Enum
from pydantic import BaseModel, Field
from uuid import UUID, uuid4

from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import PlotLedger, Chapter, Book
from backend.services.rag.retrieval_types import (
    RetrievedItem,
    RetrievalResult,
    MemoryType,
    ContentPriority,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 伏笔状态定义
# =============================================================================

class HookStatus(str, Enum):
    """伏笔状态"""
    OPEN = "open"                   # 开放中
    PARTIALLY_CLOSED = "partial"    # 部分闭合
    CLOSED = "closed"               # 已闭合
    ABANDONED = "abandoned"         # 已放弃


class HookPriority(str, Enum):
    """伏笔优先级"""
    MAIN_PLOT = "main_plot"         # 主线伏笔（必须闭合）
    SUB_PLOT = "sub_plot"           # 支线伏笔
    ATMOSPHERE = "atmosphere"       # 氛围伏笔（可选闭合）
    DETAIL = "detail"               # 细节伏笔


# =============================================================================
# 伏笔检测结果
# =============================================================================

class HookDetectionResult(BaseModel):
    """伏笔检测结果"""
    hook_id: str = Field(..., description="伏笔 ID")
    ledger_key: str = Field(default="", description="账本键")
    content: str = Field(..., description="伏笔内容")
    
    # 检测信息
    detected_in_chapter: int = Field(default=0, description="检测到的章节")
    detection_confidence: float = Field(default=0.0, description="检测置信度")
    detection_method: str = Field(default="", description="检测方法")
    
    # 相关角色
    character_names: List[str] = Field(default_factory=list, description="涉及角色")
    
    # 匹配信息
    matched_text: str = Field(default="", description="匹配的文本片段")
    match_location: str = Field(default="", description="匹配位置")


class HookClosureCheckResult(BaseModel):
    """伏笔闭合检查结果"""
    hook_id: str
    hook_content: str
    
    # 检查结果
    is_addressed: bool = Field(default=False, description="是否被回应")
    is_closed: bool = Field(default=False, description="是否已闭合")
    
    # 回应信息
    addressed_in_text: str = Field(default="", description="回应的文本片段")
    closure_type: str = Field(default="", description="闭合类型：explicit/implicit/partial")
    
    # 建议
    suggestion: str = Field(default="", description="处理建议")


# =============================================================================
# 伏笔追踪器
# =============================================================================

class ForeshadowingTracker:
    """
    伏笔追踪器
    
    职责：
    - 追踪伏笔在各章节中的状态
    - 检测伏笔是否被提及或闭合
    - 提供伏笔召回优先级
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_open_hooks(
        self,
        book_id: UUID,
        before_chapter: int,
    ) -> List[Dict[str, Any]]:
        """
        获取指定章节前的所有开放伏笔
        
        Args:
            book_id: 书籍 ID
            before_chapter: 章节号（不含）
        
        Returns:
            List[Dict]: 开放伏笔列表
        """
        stmt = select(PlotLedger).where(
            PlotLedger.book_id == book_id,
            PlotLedger.status == HookStatus.OPEN.value,
            PlotLedger.created_at_chapter < before_chapter,
        ).order_by(PlotLedger.created_at_chapter.desc())
        
        result = await self.db.execute(stmt)
        hooks = result.scalars().all()
        
        return [
            {
                "hook_id": str(hook.id),
                "ledger_key": hook.ledger_key or "",
                "content": hook.content or "",
                "chapter_number": hook.created_at_chapter or 0,
                "priority": getattr(hook, "priority", HookPriority.SUB_PLOT.value),
            }
            for hook in hooks
        ]
    
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
            
            # 提取关键词
            keywords = self._extract_keywords(content)
            
            # 计算匹配度
            matched_keywords = []
            matched_text = ""
            
            for kw in keywords:
                if kw.lower() in text_lower:
                    matched_keywords.append(kw)
                    # 提取匹配上下文
                    idx = text_lower.find(kw.lower())
                    if idx >= 0:
                        start = max(0, idx - 30)
                        end = min(len(text), idx + len(kw) + 30)
                        matched_text = text[start:end]
                        break
            
            if matched_keywords:
                confidence = len(matched_keywords) / max(1, len(keywords))
                
                result = HookDetectionResult(
                    hook_id=hook.get("hook_id", ""),
                    ledger_key=hook.get("ledger_key", ""),
                    content=content,
                    detected_in_chapter=chapter_number,
                    detection_confidence=confidence,
                    detection_method="keyword_match",
                    matched_text=matched_text,
                )
                results.append(result)
        
        return results
    
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
        
        for hook in open_hooks:
            content = hook.get("content", "")
            hook_id = hook.get("hook_id", "")
            
            # 检测是否被回应
            detection = await self._check_single_hook(text, content)
            
            result = HookClosureCheckResult(
                hook_id=hook_id,
                hook_content=content,
                is_addressed=detection["is_addressed"],
                is_closed=detection["is_closed"],
                addressed_in_text=detection["matched_text"],
                closure_type=detection["closure_type"],
                suggestion=detection["suggestion"],
            )
            
            results.append(result)
        
        return results
    
    async def update_hook_status(
        self,
        hook_id: UUID,
        new_status: HookStatus,
        closed_in_chapter: Optional[int] = None,
        closure_note: str = "",
    ) -> bool:
        """
        更新伏笔状态
        
        Args:
            hook_id: 伏笔 ID
            new_status: 新状态
            closed_in_chapter: 闭合章节号
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
            if closed_in_chapter:
                hook.closed_at_chapter = closed_in_chapter
            
            await self.db.commit()
            return True
            
        except Exception as e:
            logger.error(f"[ForeshadowingTracker] 更新伏笔状态失败: {e}")
            return False
    
    async def _check_single_hook(
        self,
        text: str,
        hook_content: str,
    ) -> Dict[str, Any]:
        """检查单个伏笔"""
        keywords = self._extract_keywords(hook_content)
        text_lower = text.lower()
        
        # 关键词匹配
        matched = [kw for kw in keywords if kw.lower() in text_lower]
        
        if not matched:
            return {
                "is_addressed": False,
                "is_closed": False,
                "matched_text": "",
                "closure_type": "",
                "suggestion": "伏笔未被提及，考虑在后续章节回应",
            }
        
        # 计算匹配度
        match_ratio = len(matched) / len(keywords) if keywords else 0
        
        # 检查是否有闭合性表达
        closure_patterns = [
            r"原来.*是",
            r"终于.*明白",
            r"真相.*大白",
            r"终于.*知道",
            r"原来如此",
            r"一切.*都.*解释",
        ]
        
        is_closed = False
        closure_type = "partial" if match_ratio < 0.7 else "implicit"
        
        for pattern in closure_patterns:
            if re.search(pattern, text):
                is_closed = True
                closure_type = "explicit"
                break
        
        # 提取匹配文本
        matched_text = ""
        for kw in matched:
            idx = text_lower.find(kw.lower())
            if idx >= 0:
                start = max(0, idx - 20)
                end = min(len(text), idx + len(kw) + 50)
                matched_text = text[start:end]
                break
        
        suggestion = ""
        if is_closed:
            suggestion = "伏笔已闭合"
        elif match_ratio > 0.5:
            suggestion = "伏笔部分回应，可考虑进一步闭合"
        else:
            suggestion = "伏笔轻微提及，建议后续章节明确回应"
        
        return {
            "is_addressed": True,
            "is_closed": is_closed,
            "matched_text": matched_text,
            "closure_type": closure_type,
            "suggestion": suggestion,
        }
    
    def _extract_keywords(self, content: str) -> List[str]:
        """提取关键词"""
        # 简化实现：提取中文词组
        words = re.findall(r'[\u4e00-\u9fa5]{2,}', content)
        
        # 过滤常见词
        stop_words = {"这时", "那里", "这个", "那个", "什么", "怎么", "虽然", "但是"}
        
        return [w for w in words if w not in stop_words]


# =============================================================================
# 伏笔记忆注入器
# =============================================================================

class HookMemoryInjector:
    """
    伏笔记忆注入器
    
    职责：
    - 将新创建的伏笔注入记忆系统
    - 确保伏笔可被后续章节召回
    - 管理伏笔的向量表示
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
            from backend.models import MemoryChunk
            
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
                chunk_type="foreshadowing",
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
# 伏笔遗漏检测器
# =============================================================================

class HookOmissionDetector:
    """
    伏笔遗漏检测器
    
    职责：
    - 在审阅阶段检测伏笔遗漏
    - 评估遗漏的严重性
    - 提供修复建议
    """
    
    def __init__(self, tracker: ForeshadowingTracker):
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
            # 判断是否为遗漏
            hook_info = next(
                (h for h in open_hooks if h.get("hook_id") == result.hook_id),
                {}
            )
            
            priority = hook_info.get("priority", HookPriority.SUB_PLOT.value)
            created_chapter = hook_info.get("chapter_number", 0)
            
            # 计算开放时长（章节数）
            open_duration = chapter_number - created_chapter
            
            # 判断遗漏
            is_omission = False
            severity = "info"
            
            if result.is_closed:
                # 已闭合，不是遗漏
                continue
            
            if priority == HookPriority.MAIN_PLOT.value:
                # 主线伏笔
                if open_duration >= 3:
                    is_omission = True
                    severity = "major"
                elif open_duration >= 5:
                    is_omission = True
                    severity = "critical"
            elif priority == HookPriority.SUB_PLOT.value:
                # 支线伏笔
                if open_duration >= 5:
                    is_omission = True
                    severity = "minor"
            else:
                # 氛围/细节伏笔
                if open_duration >= 10:
                    is_omission = True
                    severity = "suggestion"
            
            if is_omission:
                omissions.append({
                    "hook_id": result.hook_id,
                    "content": result.hook_content,
                    "priority": priority,
                    "open_duration": open_duration,
                    "severity": severity,
                    "is_addressed": result.is_addressed,
                    "suggestion": result.suggestion or "建议在后续章节回应此伏笔",
                })
        
        return omissions
    
    def get_repair_suggestion(
        self,
        omission: Dict[str, Any],
    ) -> str:
        """获取修复建议"""
        priority = omission.get("priority", "")
        content = omission.get("content", "")
        is_addressed = omission.get("is_addressed", False)
        
        if priority == HookPriority.MAIN_PLOT.value:
            if is_addressed:
                return f"主线伏笔「{content[:20]}...」已提及，建议在下一章明确闭合"
            return f"主线伏笔「{content[:20]}...」长期未处理，建议优先安排闭合情节"
        
        elif priority == HookPriority.SUB_PLOT.value:
            if is_addressed:
                return f"支线伏笔「{content[:20]}...」可考虑在未来2-3章内闭合"
            return f"支线伏笔「{content[:20]}...」建议在近期章节回应"
        
        else:
            return f"伏笔「{content[:20]}...」可作为背景线索或选择性忽略"


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
    
    Returns:
        Optional[PlotLedger]: 创建的伏笔实体
    """
    try:
        hook = PlotLedger(
            book_id=book_id,
            chapter_id=chapter_id,
            content=content,
            ledger_key=ledger_key or f"hook-{uuid4().hex[:8]}",
            status=HookStatus.OPEN.value,
            created_at_chapter=created_at_chapter,
        )
        
        # 尝试设置优先级（如果字段存在）
        if hasattr(hook, "priority"):
            hook.priority = priority.value
        
        db.add(hook)
        await db.commit()
        
        # 注入记忆系统
        injector = HookMemoryInjector(db)
        await injector.inject_hook_to_memory(hook)
        
        logger.info(f"[create_and_track_hook] 伏笔已创建: {hook.id}")
        return hook
        
    except Exception as e:
        logger.error(f"[create_and_track_hook] 创建失败: {e}")
        return None

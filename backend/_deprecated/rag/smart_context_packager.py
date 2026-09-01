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
智能上下文打包器 (Smart Context Packager)

职责：
- 将检索结果智能打包为适合 LLM 的上下文
- 按章节生成阶段组装不同上下文
- 实现内容压缩与智能摘要
- 控制上下文总长度
- 区分原文保留与可摘要内容
"""

import logging
import re
from typing import Any, Dict, List, Optional
from collections import defaultdict
from dataclasses import dataclass, field

from backend.services.rag.retrieval_types import (
    MemoryType,
    MemoryTypeConfig,
    ContentPriority,
    ContentType,
    RetrievedItem,
    RetrievalResult,
    ContextSection,
    ContextPackage,
)


logger = logging.getLogger(__name__)


# =============================================================================
# 配置定义
# =============================================================================

@dataclass
class PackagerConfig:
    """打包器配置"""
    max_total_length: int = 8000
    max_section_length: int = 500
    preserve_critical: bool = True
    compress_high: bool = False
    
    section_lengths: Dict[str, int] = field(default_factory=lambda: {
        "previous_summary": 500,
        "book_setting": 800,
        "character_state": 300,
        "relationship_state": 200,
        "open_hook": 150,
        "world_snapshot": 400,
        "memory_chunk": 200,
        "story_beat": 100,
        "map_location": 100,
    })
    
    stage_configs: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "planning": {
            "include_types": ["previous_summary", "book_setting", "character_state",
                           "relationship_state", "open_hook", "world_snapshot"],
            "max_length": 6000,
        },
        "drafting": {
            "include_types": ["previous_summary", "book_setting", "character_state",
                           "relationship_state", "open_hook", "world_snapshot",
                           "memory_chunk", "map_location"],
            "max_length": 8000,
        },
        "reviewing": {
            "include_types": ["character_state", "relationship_state", "open_hook"],
            "max_length": 4000,
        },
        "refining": {
            "include_types": ["previous_summary", "character_state",
                           "relationship_state", "open_hook"],
            "max_length": 5000,
        },
    })


# =============================================================================
# 智能摘要器
# =============================================================================

class SmartSummarizer:
    """智能摘要器"""
    
    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    }
    
    KEY_SENTENCE_MARKERS = [
        "但是", "然而", "因此", "于是", "最终", "突然", "就在这时",
        "原来", "没想到", "终于", "竟然",
    ]
    
    def summarize(
        self,
        content: str,
        max_length: int,
        content_type: ContentType = ContentType.SUMMARY,
        preserve_structure: bool = False,
    ) -> str:
        """智能摘要"""
        if len(content) <= max_length:
            return content
        
        if content_type == ContentType.FULL_TEXT:
            return self._truncate_with_ellipsis(content, max_length)
        elif content_type == ContentType.KEYWORDS:
            return self._extract_keywords(content, max_length)
        elif content_type == ContentType.STRUCTURED:
            return self._compress_structured(content, max_length, preserve_structure)
        else:
            return self._summarize_sentences(content, max_length)
    
    def _truncate_with_ellipsis(self, text: str, max_length: int) -> str:
        """带省略号的截断"""
        if len(text) <= max_length:
            return text
        truncated = text[:max_length - 3]
        last_end = max(truncated.rfind("。"), truncated.rfind("！"),
                       truncated.rfind("？"), truncated.rfind("."))
        if last_end > max_length * 0.6:
            return truncated[:last_end + 1]
        return truncated + "..."
    
    def _extract_keywords(self, text: str, max_length: int) -> str:
        """提取关键词"""
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', text)
        keywords = [w for w in words if w not in self.STOP_WORDS and len(w) > 1]
        seen = set()
        unique = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        result = "、".join(unique)
        return result[:max_length - 3] + "..." if len(result) > max_length else result
    
    def _compress_structured(self, text: str, max_length: int, preserve: bool = False) -> str:
        """压缩结构化内容"""
        lines = text.split("\n")
        compressed = []
        current_len = 0
        key_markers = ["【", "】", "：", ":", "角色", "关系", "状态", "设定"]
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            is_key = any(m in line for m in key_markers)
            content = line if (is_key or preserve) else self._truncate_with_ellipsis(line, 50)
            if current_len + len(content) + 1 <= max_length:
                compressed.append(content)
                current_len += len(content) + 1
            if current_len >= max_length:
                break
        return "\n".join(compressed)
    
    def _summarize_sentences(self, text: str, max_length: int) -> str:
        """句子级摘要"""
        sentences = [s.strip() for s in re.split(r'[。！？.!?]', text) if s.strip()]
        if not sentences:
            return self._truncate_with_ellipsis(text, max_length)
        
        scored = []
        for i, s in enumerate(sentences):
            score = 2 if 15 < len(s) < 80 else 0
            score += max(0, 3 - i)
            for marker in self.KEY_SENTENCE_MARKERS:
                if marker in s:
                    score += 2
                    break
            scored.append((score, s))
        
        scored.sort(key=lambda x: -x[0])
        selected = []
        current = 0
        for _, s in scored:
            if current + len(s) + 1 <= max_length:
                selected.append(s)
                current += len(s) + 1
        selected.sort(key=lambda x: text.find(x[:10]) if x[:10] in text else 999)
        return "。".join(selected) + "。"


# =============================================================================
# 内容合并器
# =============================================================================

class SmartMerger:
    """智能合并器"""
    
    def merge_items(
        self,
        items: List[RetrievedItem],
        memory_type: MemoryType,
        max_length: int = 1000,
    ) -> str:
        """合并同类型项"""
        if not items:
            return ""
        
        by_chapter: Dict[int, List[RetrievedItem]] = defaultdict(list)
        no_chapter: List[RetrievedItem] = []
        
        for item in items:
            if item.chapter_number:
                by_chapter[item.chapter_number].append(item)
            else:
                no_chapter.append(item)
        
        sections = []
        for item in no_chapter:
            sections.append(item.content)
        
        for ch_num in sorted(by_chapter.keys(), reverse=True):
            ch_items = by_chapter[ch_num]
            if memory_type == MemoryType.MEMORY_CHUNK:
                sections.append(f"[第{ch_num}章]")
                for item in ch_items:
                    sections.append(f"  {item.content}")
            else:
                for item in ch_items:
                    sections.append(item.content)
        
        result = "\n".join(sections)
        return result[:max_length - 3] + "..." if len(result) > max_length else result


# =============================================================================
# 上下文打包器
# =============================================================================

class SmartContextPackager:
    """智能上下文打包器"""
    
    SECTION_NAMES = {
        MemoryType.PREVIOUS_SUMMARY: "上一章概要",
        MemoryType.BOOK_SETTING: "核心设定",
        MemoryType.CHARACTER_STATE: "出场角色",
        MemoryType.RELATIONSHIP_STATE: "角色关系",
        MemoryType.OPEN_HOOK: "待闭合伏笔",
        MemoryType.WORLD_SNAPSHOT: "世界状态",
        MemoryType.MEMORY_CHUNK: "相关记忆",
        MemoryType.STORY_BEAT: "历史节拍",
        MemoryType.MAP_LOCATION: "场景地点",
        MemoryType.PLOT_LEDGER: "情节账本",
    }
    
    def __init__(self, config: Optional[PackagerConfig] = None, stage: str = "drafting"):
        self.config = config or PackagerConfig()
        self.stage = stage
        self.summarizer = SmartSummarizer()
        self.merger = SmartMerger()
    
    def build(self, retrieval_result: RetrievalResult) -> ContextPackage:
        """构建上下文包"""
        package = ContextPackage(
            chapter_id=retrieval_result.chapter_id,
            chapter_number=retrieval_result.chapter_number,
            retrieval_result=retrieval_result,
        )
        
        stage_config = self.config.stage_configs.get(
            self.stage, self.config.stage_configs["drafting"]
        )
        include_type_strs = set(stage_config.get("include_types", []))
        max_length = stage_config.get("max_length", self.config.max_total_length)
        
        # 按类型分组
        items_by_type: Dict[MemoryType, List[RetrievedItem]] = defaultdict(list)
        for item in retrieval_result.items:
            if item.memory_type.value in include_type_strs:
                items_by_type[item.memory_type].append(item)
        
        priority_order = [
            ContentPriority.CRITICAL, ContentPriority.HIGH,
            ContentPriority.NORMAL, ContentPriority.LOW,
        ]
        
        current_length = 0
        
        for priority in priority_order:
            for memory_type in items_by_type.keys():
                items = items_by_type.get(memory_type, [])
                priority_items = [i for i in items if i.priority == priority]
                if not priority_items:
                    continue
                
                section_length = self.config.section_lengths.get(
                    memory_type.value, self.config.max_section_length
                )
                
                merged = self.merger.merge_items(
                    priority_items, memory_type, section_length * 2
                )
                
                content_type = self._get_content_type(memory_type, priority)
                preserve = priority in [ContentPriority.CRITICAL, ContentPriority.HIGH]
                
                compressed = self.summarizer.summarize(
                    merged, section_length, content_type, preserve
                )
                
                if current_length + len(compressed) > max_length:
                    remaining = max_length - current_length
                    if remaining > 100:
                        compressed = self.summarizer.summarize(
                            merged, remaining, content_type, False
                        )
                    else:
                        break
                
                section = ContextSection(
                    section_name=self.SECTION_NAMES.get(memory_type, memory_type.value),
                    section_type=memory_type,
                    content=compressed,
                    items=priority_items,
                    total_length=len(compressed),
                    compressed=len(compressed) < len(merged),
                )
                
                package.add_section(section)
                current_length += len(compressed)
                
                if current_length >= max_length:
                    break
            
            if current_length >= max_length:
                break
        
        original_length = sum(len(item.content) for item in retrieval_result.items)
        if original_length > 0:
            package.compression_ratio = package.total_length / original_length
        
        logger.info(
            f"[SmartContextPackager] 构建: {len(package.sections)} 段落, "
            f"{package.total_length} 字, 压缩率 {package.compression_ratio:.2f}"
        )
        
        return package
    
    def build_for_planning(self, result: RetrievalResult) -> ContextPackage:
        self.stage = "planning"
        return self.build(result)
    
    def build_for_drafting(self, result: RetrievalResult) -> ContextPackage:
        self.stage = "drafting"
        return self.build(result)
    
    def build_for_reviewing(self, result: RetrievalResult) -> ContextPackage:
        self.stage = "reviewing"
        return self.build(result)
    
    def _get_content_type(self, memory_type: MemoryType, priority: ContentPriority) -> ContentType:
        if priority == ContentPriority.CRITICAL:
            return ContentType.FULL_TEXT
        config = MemoryTypeConfig.get_config(memory_type)
        return config.get("content_type", ContentType.SUMMARY)


# =============================================================================
# 便捷函数
# =============================================================================

def build_smart_context(
    retrieval_result: RetrievalResult,
    stage: str = "drafting",
    max_length: int = 8000,
) -> ContextPackage:
    """便捷函数：构建智能上下文"""
    config = PackagerConfig(max_total_length=max_length)
    packager = SmartContextPackager(config, stage)
    return packager.build(retrieval_result)

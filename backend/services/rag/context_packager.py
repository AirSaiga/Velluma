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
上下文打包与压缩器 (Context Packager and Compressor)

职责：
- 将检索结果打包为适合 LLM 的上下文
- 按章节生成阶段组装不同上下文
- 实现上下文压缩与摘要
- 控制上下文总长度
- 区分原文保留与可摘要内容

设计原则：
1. CRITICAL 内容不可压缩
2. HIGH 内容尽量保留原文
3. NORMAL/LOW 内容可摘要
4. 相似内容合并
5. 总长度控制在限制内
"""

import logging
import re
from typing import Any, Dict, List, Optional
from collections import defaultdict

from backend.services.rag.retrieval_types import (
    MemoryType,
    MemoryTypeConfig,
    ContentPriority,
    ContentType,
    RetrievedItem,
    RetrievalResult,
    ContextSection,
    ContextPackage,
    RetrievalStrategyConfig,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 内容摘要器
# =============================================================================

class ContentSummarizer:
    """
    内容摘要器
    
    策略：
    1. 关键词提取：保留重要名词和动词
    2. 句子筛选：保留核心句子
    3. 长度压缩：截断或精简
    """
    
    # 中文停用词（简化）
    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这", "那", "他",
    }
    
    def summarize(
        self,
        content: str,
        max_length: int,
        content_type: ContentType = ContentType.SUMMARY,
    ) -> str:
        """
        摘要内容
        
        Args:
            content: 原始内容
            max_length: 最大长度
            content_type: 内容类型
        
        Returns:
            str: 摘要后的内容
        """
        if len(content) <= max_length:
            return content
        
        if content_type == ContentType.FULL_TEXT:
            # 全文类型：只能截断
            return self._truncate_with_ellipsis(content, max_length)
        
        elif content_type == ContentType.KEYWORDS:
            # 关键词类型：提取关键词
            return self._extract_keywords(content, max_length)
        
        elif content_type == ContentType.STRUCTURED:
            # 结构化类型：保留关键信息
            return self._compress_structured(content, max_length)
        
        else:
            # 默认：句子筛选 + 截断
            return self._summarize_sentences(content, max_length)
    
    def _truncate_with_ellipsis(self, text: str, max_length: int) -> str:
        """带省略号的截断"""
        if len(text) <= max_length:
            return text
        
        # 尝试在句子边界截断
        truncated = text[:max_length - 3]
        
        # 找到最后一个句子结束符
        last_sentence_end = max(
            truncated.rfind("。"),
            truncated.rfind("！"),
            truncated.rfind("？"),
            truncated.rfind("."),
            truncated.rfind("!"),
            truncated.rfind("?"),
        )
        
        if last_sentence_end > max_length * 0.6:
            return truncated[:last_sentence_end + 1]
        
        return truncated + "..."
    
    def _extract_keywords(self, text: str, max_length: int) -> str:
        """提取关键词"""
        # 分词（简化：按空格和标点分割）
        words = re.findall(r'[\u4e00-\u9fa5]+|[a-zA-Z]+', text)
        
        # 过滤停用词和短词
        keywords = [
            w for w in words
            if w not in self.STOP_WORDS and len(w) > 1
        ]
        
        # 去重保持顺序
        seen = set()
        unique_keywords = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique_keywords.append(w)
        
        result = "、".join(unique_keywords)
        
        if len(result) > max_length:
            result = result[:max_length - 3] + "..."
        
        return result
    
    def _compress_structured(self, text: str, max_length: int) -> str:
        """压缩结构化内容"""
        lines = text.split("\n")
        compressed_lines = []
        current_length = 0
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # 保留关键行（包含关键标记）
            if any(marker in line for marker in ["【", "】", "：", ":", "角色", "关系", "状态", "设定"]):
                if current_length + len(line) + 1 <= max_length:
                    compressed_lines.append(line)
                    current_length += len(line) + 1
            else:
                # 其他行压缩
                compressed = self._truncate_with_ellipsis(line, 50)
                if current_length + len(compressed) + 1 <= max_length:
                    compressed_lines.append(compressed)
                    current_length += len(compressed) + 1
            
            if current_length >= max_length:
                break
        
        return "\n".join(compressed_lines)
    
    def _summarize_sentences(self, text: str, max_length: int) -> str:
        """句子级摘要"""
        # 分句
        sentences = re.split(r'[。！？.!?]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return self._truncate_with_ellipsis(text, max_length)
        
        # 按重要性排序（简化：基于长度和位置）
        scored_sentences = []
        for i, s in enumerate(sentences):
            score = 0
            # 长度适中的句子更重要
            if 20 < len(s) < 100:
                score += 2
            # 前面的句子更重要
            score += max(0, 3 - i)
            # 包含关键词的句子更重要
            if any(kw in s for kw in ["但是", "然而", "因此", "于是", "最终", "突然"]):
                score += 2
            scored_sentences.append((score, s))
        
        # 排序并选择
        scored_sentences.sort(key=lambda x: -x[0])
        
        selected = []
        current_length = 0
        
        for _, s in scored_sentences:
            if current_length + len(s) + 1 <= max_length:
                selected.append(s)
                current_length += len(s) + 1
        
        # 按原文顺序排列
        selected.sort(key=lambda x: text.find(x[:10]) if x[:10] in text else 999)
        
        return "。".join(selected) + "。"


# =============================================================================
# 内容合并器
# =============================================================================

class ContentMerger:
    """
    内容合并器
    
    策略：
    1. 相同类型的项合并
    2. 相似内容去重
    3. 按优先级组织
    """
    
    def merge_items(
        self,
        items: List[RetrievedItem],
        memory_type: MemoryType,
    ) -> str:
        """
        合并同类型项
        
        Args:
            items: 同类型检索项列表
            memory_type: 记忆类型
        
        Returns:
            str: 合并后的内容
        """
        if not items:
            return ""
        
        # 按章节号分组
        by_chapter: Dict[int, List[RetrievedItem]] = defaultdict(list)
        no_chapter: List[RetrievedItem] = []
        
        for item in items:
            if item.chapter_number:
                by_chapter[item.chapter_number].append(item)
            else:
                no_chapter.append(item)
        
        # 按章节组织内容
        sections = []
        
        # 无章节号的项（通常是设定）
        if no_chapter:
            sections.append("\n".join(item.content for item in no_chapter))
        
        # 有章节号的项（按章节号倒序）
        for chapter_num in sorted(by_chapter.keys(), reverse=True):
            chapter_items = by_chapter[chapter_num]
            section_content = "\n".join(item.content for item in chapter_items)
            sections.append(f"[第{chapter_num}章]\n{section_content}")
        
        return "\n\n".join(sections)


# =============================================================================
# 上下文打包器
# =============================================================================

class ContextPackagerBuilder:
    """
    上下文包构建器
    
    职责：
    - 将检索结果组织为上下文包
    - 控制总长度
    - 按阶段定制上下文
    """
    
    # 段落名称映射
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
    
    # 阶段上下文配置
    STAGE_CONFIGS = {
        "planning": {
            "include_types": [
                MemoryType.PREVIOUS_SUMMARY,
                MemoryType.BOOK_SETTING,
                MemoryType.CHARACTER_STATE,
                MemoryType.RELATIONSHIP_STATE,
                MemoryType.OPEN_HOOK,
                MemoryType.WORLD_SNAPSHOT,
            ],
            "max_length": 6000,
        },
        "drafting": {
            "include_types": [
                MemoryType.PREVIOUS_SUMMARY,
                MemoryType.BOOK_SETTING,
                MemoryType.CHARACTER_STATE,
                MemoryType.RELATIONSHIP_STATE,
                MemoryType.OPEN_HOOK,
                MemoryType.WORLD_SNAPSHOT,
                MemoryType.MEMORY_CHUNK,
                MemoryType.MAP_LOCATION,
            ],
            "max_length": 8000,
        },
        "reviewing": {
            "include_types": [
                MemoryType.CHARACTER_STATE,
                MemoryType.RELATIONSHIP_STATE,
                MemoryType.OPEN_HOOK,
            ],
            "max_length": 4000,
        },
        "refining": {
            "include_types": [
                MemoryType.PREVIOUS_SUMMARY,
                MemoryType.CHARACTER_STATE,
                MemoryType.RELATIONSHIP_STATE,
                MemoryType.OPEN_HOOK,
            ],
            "max_length": 5000,
        },
    }
    
    def __init__(
        self,
        max_length: int = 8000,
        stage: str = "drafting",
    ):
        self.max_length = max_length
        self.stage = stage
        self.summarizer = ContentSummarizer()
        self.merger = ContentMerger()
    
    def build(
        self,
        retrieval_result: RetrievalResult,
    ) -> ContextPackage:
        """
        构建上下文包
        
        Args:
            retrieval_result: 检索结果
        
        Returns:
            ContextPackage: 上下文包
        """
        package = ContextPackage(
            chapter_id=retrieval_result.chapter_id,
            chapter_number=retrieval_result.chapter_number,
            retrieval_result=retrieval_result,
        )
        
        # 获取阶段配置
        stage_config = self.STAGE_CONFIGS.get(self.stage, self.STAGE_CONFIGS["drafting"])
        include_types = set(stage_config["include_types"])
        stage_max_length = stage_config["max_length"]
        
        # 按类型分组
        items_by_type: Dict[MemoryType, List[RetrievedItem]] = defaultdict(list)
        for item in retrieval_result.items:
            if item.memory_type in include_types:
                items_by_type[item.memory_type].append(item)
        
        # 按优先级顺序处理
        priority_order = [
            ContentPriority.CRITICAL,
            ContentPriority.HIGH,
            ContentPriority.NORMAL,
            ContentPriority.LOW,
        ]
        
        current_length = 0
        
        for priority in priority_order:
            for memory_type in include_types:
                items = items_by_type.get(memory_type, [])
                if not items:
                    continue
                
                # 过滤当前优先级
                priority_items = [i for i in items if i.priority == priority]
                if not priority_items:
                    continue
                
                # 获取配置
                type_config = MemoryTypeConfig.get_config(memory_type)
                max_section_length = type_config.get("max_length", 200)
                
                # 合并内容
                merged_content = self.merger.merge_items(priority_items, memory_type)
                
                # 压缩
                content_type = type_config.get("content_type", ContentType.SUMMARY)
                compressed = self.summarizer.summarize(
                    merged_content,
                    max_section_length,
                    content_type,
                )
                
                # 检查总长度
                if current_length + len(compressed) > stage_max_length:
                    # 尝试进一步压缩
                    remaining = stage_max_length - current_length
                    if remaining > 100:
                        compressed = self.summarizer.summarize(
                            merged_content,
                            remaining,
                            content_type,
                        )
                    else:
                        break
                
                # 创建段落
                section = ContextSection(
                    section_name=self.SECTION_NAMES.get(memory_type, memory_type.value),
                    section_type=memory_type,
                    content=compressed,
                    items=priority_items,
                    total_length=len(compressed),
                    compressed=len(compressed) < len(merged_content),
                )
                
                package.add_section(section)
                current_length += len(compressed)
                
                if current_length >= stage_max_length:
                    break
            
            if current_length >= stage_max_length:
                break
        
        # 更新压缩信息
        original_length = sum(
            len(item.content) for item in retrieval_result.items
        )
        if original_length > 0:
            package.compression_ratio = package.total_length / original_length
        
        logger.info(
            f"[ContextPackager] 构建完成: "
            f"{len(package.sections)} 段落, "
            f"{package.total_length} 字, "
            f"压缩率 {package.compression_ratio:.2f}"
        )
        
        return package
    
    def build_for_planning(
        self,
        retrieval_result: RetrievalResult,
    ) -> ContextPackage:
        """构建规划阶段上下文"""
        self.stage = "planning"
        return self.build(retrieval_result)
    
    def build_for_drafting(
        self,
        retrieval_result: RetrievalResult,
    ) -> ContextPackage:
        """构建起草阶段上下文"""
        self.stage = "drafting"
        return self.build(retrieval_result)
    
    def build_for_reviewing(
        self,
        retrieval_result: RetrievalResult,
    ) -> ContextPackage:
        """构建审阅阶段上下文"""
        self.stage = "reviewing"
        return self.build(retrieval_result)
    
    def build_for_refining(
        self,
        retrieval_result: RetrievalResult,
    ) -> ContextPackage:
        """构建精修阶段上下文"""
        self.stage = "refining"
        return self.build(retrieval_result)


# =============================================================================
# 上下文注入器
# =============================================================================

class ContextInjector:
    """
    上下文注入器
    
    职责：
    - 将上下文包注入到 Prompt 模板
    - 处理变量替换
    - 格式化输出
    """
    
    def inject(
        self,
        package: ContextPackage,
        template: str,
        additional_vars: Optional[Dict[str, str]] = None,
    ) -> str:
        """
        注入上下文到模板
        
        Args:
            package: 上下文包
            template: Prompt 模板
            additional_vars: 额外变量
        
        Returns:
            str: 注入后的 Prompt
        """
        # 构建变量映射
        variables = {
            "CONTEXT": package.to_prompt_text(),
            "CHAPTER_NUMBER": str(package.chapter_number),
            "TOTAL_CONTEXT_LENGTH": str(package.total_length),
        }
        
        # 添加各段落作为独立变量
        for section in package.sections:
            var_name = f"SECTION_{section.section_type.value.upper()}"
            variables[var_name] = section.content
        
        # 添加额外变量
        if additional_vars:
            variables.update(additional_vars)
        
        # 执行替换
        result = template
        for key, value in variables.items():
            placeholder = f"{{{{{key}}}}}"
            result = result.replace(placeholder, value)
        
        return result


# =============================================================================
# 便捷函数
# =============================================================================

def build_context_package(
    retrieval_result: RetrievalResult,
    stage: str = "drafting",
    max_length: int = 8000,
) -> ContextPackage:
    """
    便捷函数：构建上下文包
    
    Args:
        retrieval_result: 检索结果
        stage: 生成阶段
        max_length: 最大长度
    
    Returns:
        ContextPackage: 上下文包
    """
    builder = ContextPackageBuilder(max_length=max_length, stage=stage)
    return builder.build(retrieval_result)

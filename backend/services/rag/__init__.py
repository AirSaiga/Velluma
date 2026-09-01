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
RAG 记忆检索系统（活件导出）。

2026-09-01 死代码归档：旧检索器全家（retriever/scoring/编排链/context_packager/
enhanced 子包/伏笔追踪器/explainability 等 18 文件）确认零运行路径，整体迁至
`backend/_deprecated/rag/`（静态可达性分析 + 消费方 grep 双重验证）。

在役三件：
- recall: 前情召回唯一入口（A 结构化 + V 向量增强 + B 词法，三层合并）
- lexical: 默认记忆流纯函数（jieba 关键词/覆盖分/事件回响格式化）
- memory_indexing: 章级记忆索引写入侧（章级替换语义）
"""

from backend.services.rag.recall import recall_memories, merge_echoes
from backend.services.rag.lexical import extract_keywords, keyword_coverage, format_event_echo
from backend.services.rag.memory_indexing import index_chapter_memories

__all__ = [
    "recall_memories",
    "merge_echoes",
    "extract_keywords",
    "keyword_coverage",
    "format_event_echo",
    "index_chapter_memories",
]

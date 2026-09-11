# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""记忆系统层：MemoryChunk —— RAG 检索的向量基石（pgvector 1536 维）。"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now


# ============================================================
# 记忆系统层 - MemoryChunk 是 RAG 检索的基石
# ============================================================
# 向量设计：
#   - 使用 pgvector 的 Vector(1536) 存储 OpenAI text-embedding-3-small 的输出
#   - 1536 维向量在欧氏距离和余弦相似度下均有良好表现
#
# 检索策略：
#   - chunk_text 是原始文本片段（可能来自章节正文、角色设定或关系描述）
#   - chapter_id 可选，支撑"章节内检索"和"全局检索"两种模式
#   - embedding 允许 null（手动添加的记忆可能尚未向量化）
#
# 性能权衡：
#   - 每个章节发布时自动提取 N 个记忆块，可能导致向量数据快速膨胀
#   - 建议定期清理低相似度的记忆，或采用分层存储策略
class MemoryChunk(Base):
    """
    向量记忆表 - 存储可检索的文本片段

    业务含义：
    - RAG 系统的核心数据源，章节发布时自动提取关键信息存入
    - 支持"语义检索"：根据当前上下文找到最相关的历史记忆
    - chapter_id 为空时代表"全局记忆"（如世界观设定、重要事件）

    数据流：
    - chunk_text 来源：章节正文切片、角色设定、关系描述、审阅反馈摘要
    - embedding 由 LLM 生成（text-embedding-3-small），在后台异步任务中完成
    - 检索时：用户输入 → 向量化 → 向量数据库相似度搜索 → 返回 top-K chunks

    隐性行为：
    - 删除章节时级联删除该章节的记忆块（ondelete="CASCADE"）
    - 但全局记忆（chapter_id=null）不受章节删除影响
    """
    __tablename__ = "memory_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="memories")
    chapter = relationship("Chapter", back_populates="memories")



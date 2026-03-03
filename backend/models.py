"""
SQLAlchemy ORM 模型定义
使用 SQLAlchemy 2.0 Declarative Base 定义数据库表结构
"""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, JSON, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base


def generate_uuid() -> uuid.UUID:
    """生成 UUID 主键"""
    return uuid.uuid4()


class Book(Base):
    """
    书籍表 - 叙事主干系统的根实体

    Attributes:
        id: 唯一标识符 (UUID)
        title: 书籍标题
        genre: 书籍类型/题材
        global_sys_prompt: 全局系统提示词
        created_at: 创建时间
    """
    __tablename__ = "books"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    title = Column(String(500), nullable=False)
    genre = Column(String(100), nullable=True)
    global_sys_prompt = Column(Text, nullable=True)
    worldview_settings = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="book", cascade="all, delete-orphan")
    memories = relationship("MemoryChunk", back_populates="book", cascade="all, delete-orphan")


class Chapter(Base):
    """
    章节表 - 书籍的章节结构

    Attributes:
        id: 唯一标识符 (UUID)
        book_id: 关联书籍ID
        chapter_number: 章节序号
        title: 章节标题
        outline_text: 本章大纲
        content_text: 最终正文
        draft_text: 主笔 Agent 生成的初稿
        review_feedback: 审阅 Agent 返回的结构化质检报告 (JSONB)
        revision_count: 当前章节经历的重写次数
        status: 状态 (draft/published)
        created_at: 创建时间
    """
    __tablename__ = "chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    title = Column(String(500), nullable=True)
    outline_text = Column(Text, nullable=True)
    content_text = Column(Text, nullable=True)
    draft_text = Column(Text, nullable=True)
    review_feedback = Column(JSONB, default=dict)
    revision_count = Column(Integer, default=0)
    status = Column(String(50), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)

    book = relationship("Book", back_populates="chapters")
    entities = relationship("ChapterEntity", back_populates="chapter", cascade="all, delete-orphan")
    memories = relationship("MemoryChunk", back_populates="chapter", cascade="all, delete-orphan")


class ChapterEntity(Base):
    """
    章节-实体关联表 (多对多)

    用于关联章节和角色/其他实体

    Attributes:
        id: 唯一标识符 (UUID)
        chapter_id: 章节ID
        entity_id: 关联的角色ID
        entity_type: 实体类型 (character等)
    """
    __tablename__ = "chapter_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), default="character")

    chapter = relationship("Chapter", back_populates="entities")
    character = relationship("Character", back_populates="chapter_entities")


class Character(Base):
    """
    角色表 - 世界观与关系图谱的核心实体

    Attributes:
        id: 唯一标识符 (UUID)
        book_id: 关联书籍ID
        name: 角色名称 (必填)
        aliases: 角色别名 (JSONB数组)
        static_prompt: 静态设定 (不变的角色背景)
        dynamic_state: 动态设定 (当前状态、情感等)
        importance_level: 重要程度 (1-10)
        created_at: 创建时间
    """
    __tablename__ = "characters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    aliases = Column(JSONB, default=list)
    static_prompt = Column(Text, nullable=True)
    dynamic_state = Column(Text, nullable=True)
    dynamic_state_history = Column(JSONB, default=list)
    importance_level = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    book = relationship("Book", back_populates="characters")
    chapter_entities = relationship("ChapterEntity", back_populates="character", cascade="all, delete-orphan")
    source_relationships = relationship(
        "CharacterRelationship",
        foreign_keys="CharacterRelationship.source_char_id",
        back_populates="source_character",
        cascade="all, delete-orphan"
    )
    target_relationships = relationship(
        "CharacterRelationship",
        foreign_keys="CharacterRelationship.target_char_id",
        back_populates="target_character",
        cascade="all, delete-orphan"
    )


class CharacterRelationship(Base):
    """
    角色关系推演表 - 管理角色间的关系网络

    Attributes:
        id: 唯一标识符 (UUID)
        source_char_id: 源角色ID
        target_char_id: 目标角色ID
        relation_type: 关系类型 (friend, enemy, family等)
        affinity_score: 亲密度分数 (-100到100)
        interaction_prompt: 核心互动约束
        is_public: 是否公开可见
        created_at: 创建时间
    """
    __tablename__ = "character_relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    source_char_id = Column(
        UUID(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False
    )
    target_char_id = Column(
        UUID(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False
    )
    relation_type = Column(String(100), nullable=False)
    affinity_score = Column(Integer, default=0)
    interaction_prompt = Column(Text, nullable=True)
    is_public = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    source_character = relationship(
        "Character",
        foreign_keys=[source_char_id],
        back_populates="source_relationships"
    )
    target_character = relationship(
        "Character",
        foreign_keys=[target_char_id],
        back_populates="target_relationships"
    )

    __table_args__ = (
        UniqueConstraint('source_char_id', 'target_char_id', name='uq_character_relationship'),
    )


class MemoryChunk(Base):
    """
    向量记忆表 - 存储可检索的文本片段

    使用 pgvector 的 Vector 类型存储 1536 维向量

    Attributes:
        id: 唯一标识符 (UUID)
        book_id: 关联书籍ID
        chapter_id: 关联章节ID (可选)
        chunk_text: 记忆文本内容
        embedding: 1536维向量特征
        created_at: 创建时间
    """
    __tablename__ = "memory_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    book = relationship("Book", back_populates="memories")
    chapter = relationship("Chapter", back_populates="memories")

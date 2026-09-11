# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""实体层：Character / CharacterRelationship / Asset 及章级绑定与地图坐标中间表。"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now


# ============================================================
# 关联表层 - 解决多对多关系的中间表
# ============================================================
# 权衡考量：
#   为什么不用外键数组？PostgreSQL 数组 + GIN 索引虽可行，但：
#   1. 数组不便于存储额外属性（如 entity_type）
#   2. 关联表更灵活，未来可扩展到多种实体类型（角色、地点、物品）
#   3. SQLAlchemy relationship 提供了便捷的查询接口
class ChapterEntity(Base):
    """
    章节-实体关联表 (多对多)

    业务含义：
    - 标记特定章节涉及哪些角色（用于上下文检索和关系影响分析）
    - entity_type 预留扩展性：未来可能支持 "location", "item" 等实体类型

    数据流：
    - chapter_id 来自当前编辑的章节
    - entity_id 来自用户选择的角色列表
    - 创建时需校验 entity 确实属于同一本书（业务约束，数据库层面未强制）
    """
    __tablename__ = "chapter_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False)
    entity_type = Column(String(50), default="character")
    emergent = Column(Boolean, default=False)  # NLE-ADF Loop3 涌现实体标记

    chapter = relationship("Chapter", back_populates="entities")
    character = relationship("Character", back_populates="chapter_entities")


class MapLocation(Base):
    """
    地图/地点表 - 管理世界观中的地理位置信息

    业务含义：
    - 存储地点名称和描述（用于 Prompt 上下文）
    - current_state 是"此刻状态"，从世界快照中提取的场景实时状态
    - 可在章节中被引用，作为环境约束或场景设定
    """
    __tablename__ = "map_locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    current_state = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="locations")
    chapter_locations = relationship("ChapterMapLocation", back_populates="location", cascade="all, delete-orphan")


class ChapterMapLocation(Base):
    """
    章节-地点关联表 (多对多)

    业务含义：
    - 标记特定章节涉及哪些地点
    """
    __tablename__ = "chapter_map_locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("map_locations.id", ondelete="CASCADE"), nullable=False)
    emergent = Column(Boolean, default=False)  # NLE-ADF Loop3 涌现地点标记

    chapter = relationship("Chapter", back_populates="locations")
    location = relationship("MapLocation", back_populates="chapter_locations")


# ============================================================
# 全局资产层 - Asset 是道具/物品的核心
# ============================================================
class Asset(Base):
    """
    全局资产表 - 管理世界观中的关键道具、装备、法宝等
    
    业务含义：
    - static_description: 静态设定（外观、基础功能、历史渊源）
    - current_state: 此刻状态（如"轻微破损"、"充能中"），可随章节演进更新
    - importance_level: 控制上下文注入优先级
    """
    __tablename__ = "assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    aliases = Column(JSONB, default=list)
    static_description = Column(Text, nullable=True)
    current_state = Column(Text, nullable=True)
    importance_level = Column(Integer, default=1)
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="assets")
    chapter_assets = relationship("ChapterAsset", back_populates="asset", cascade="all, delete-orphan")


class ChapterAsset(Base):
    """
    章节-资产关联表 (多对多)
    
    业务含义：
    - 标记特定章节涉及哪些关键道具
    """
    __tablename__ = "chapter_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    asset_id = Column(UUID(as_uuid=True), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    
    chapter = relationship("Chapter", back_populates="assets")
    asset = relationship("Asset", back_populates="chapter_assets")



# ============================================================
# 角色系统层 - Character 是世界观和关系图谱的核心
# ============================================================
# 双态设计：
#   static_prompt: 不变设定（出身、性格、外貌）- LLM 每次调用都注入
#   dynamic_state: 瞬时状态（情绪、位置、状态）- 随章节推进演变
#
# importance_level 的用途：
#   - 控制 LLM 上下文窗口分配（高重要性角色获得更多 token 预算）
#   - 影响记忆检索的权重排序
class Character(Base):
    """
    角色表 - 世界观与关系图谱的核心实体

    业务含义：
    - static_prompt 是"永恒设定"，每次 LLM 调用都作为 system prompt 注入
    - dynamic_state 是"瞬时快照"，记录当前章节结束时角色的情绪/状态
    - current_state 是"此刻状态"，从世界快照中提取的角色实时物理/心理状态
    - dynamic_state_history 保留所有历史状态，支持"时间回溯"或"状态追溯"
    - importance_level (1-10) 是资源分配优先级，影响上下文窗口分配策略

    表关系设计：
    - chapter_entities 实现"章节-角色"多对多（某角色可在多章出现）
    - source_relationships + target_relationships 实现有向关系图

    性能隐患：
    - 动态状态历史可能膨胀，需考虑归档策略（如只保留最近 N 个版本）
    """
    __tablename__ = "characters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False)
    aliases = Column(JSONB, default=list)
    static_prompt = Column(Text, nullable=True)
    dynamic_state = Column(Text, nullable=True)
    current_state = Column(Text, nullable=True)
    dynamic_state_history = Column(JSONB, default=list)
    importance_level = Column(Integer, default=1)
    created_at = Column(DateTime, default=utc_now)

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


# ============================================================
# 关系图谱层 - CharacterRelationship 构建角色互动网络
# ============================================================
# 关系类型设计：
#   - affinity_score (-100 ~ 100) 是数值化亲密度，影响 LLM 生成时的行为倾向
#   - interaction_prompt 是"关系约束"，如"两人交谈时 A 总是隐瞒某事"
#   - is_public 控制关系是否对 LLM 可见（隐藏关系可制造信息不对称）
#
# 唯一性约束：
#   (source_char_id, target_char_id) 唯一，避免重复创建相同关系
class CharacterRelationship(Base):
    """
    角色关系推演表 - 管理角色间的关系网络

    业务含义：
    - 有向边设计：source → target，代表"源角色对目标角色的认知"
    - 关系不对称：AB 可能是"父子"但 A 对 B 的态度与 B 对 A 不同
    - affinity_score 是数值化指标，LLM 生成对话时据此调整语气/内容倾向

    数据流：
    - source_char_id, target_char_id 来自用户创建关系时的选择
    - 关系创建后会影响 LLM 的 system prompt，注入角色互动约束

    警示：
    - 需防范自环（source == target），业务层应校验
    - 大量角色（>100）时关系查询可能成为瓶颈，考虑定期物化
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
    created_at = Column(DateTime, default=utc_now)

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



# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
SQLAlchemy ORM 模型定义
使用 SQLAlchemy 2.0 Declarative Base 定义数据库表结构
"""

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

__all__ = [
    # Enums
    "PlotLedgerStatus",
    "TaskStatus",
    # Models
    "Book",
    "Chapter",
    "ChapterEntity",
    "MapLocation",
    "ChapterMapLocation",
    "Asset",
    "ChapterAsset",
    "Character",
    "CharacterRelationship",
    "MemoryChunk",
    "StoryBeat",
    "SceneIntent",
    "PlotLedger",
    "GenerationTask",
    "GenerationRun",
    # CP2.1 新增
    "ChapterCard",
    "StyleCard",
    "AuthorSample",
    "SystemCliche",
    # CP3.1a 新增
    "QualityReport",
    # V3.1 统一引擎 tier 常量
    "TIER_CLIMAX",
    "TIER_TURN",
    "TIER_PROGRESS",
    "TIER_TRANSITION",
    "TIER_AUTO",
    "VALID_TIERS",
    # V4.0 Canon（作者脑中世界图谱）
    "CanonNode",
    "CanonEdge",
    "NODE_TYPE_CHARACTER",
    "NODE_TYPE_EVENT",
    "NODE_TYPE_OBJECT",
    "NODE_TYPE_PLACE",
    "NODE_TYPE_HOOK",
    "EDGE_TYPE_CAUSES",
    "EDGE_TYPE_BEFORE",
    "EDGE_TYPE_HINTS",
    "EDGE_TYPE_SETUPS",
    "EDGE_TYPE_CALLBACKS",
    "EDGE_TYPE_ECHOES",
    "VISIBILITY_PUBLIC",
    "VISIBILITY_PRIVATE",
    "VISIBILITY_PARTIAL",
    # V5.0 World 设定层（地图 + 时间线 + 事件溯源，独立于 Canon）
    "WorldEvent",
    "WorldLocation",
    "WorldEntity",
    "WorldMapLayer",
    "WorldMapStroke",
    "WORLD_EVENT_BIRTH",
    "WORLD_EVENT_DEATH",
    "WORLD_EVENT_MOVE",
    "WORLD_EVENT_BATTLE",
    "WORLD_EVENT_TERRITORY_CHANGE",
    "WORLD_EVENT_FOUND",
    "WORLD_EVENT_DESTROY",
    "WORLD_EVENT_ALLIANCE",
    "WORLD_EVENT_WAR_DECLARE",
    "WORLD_EVENT_CORONATION",
    "WORLD_EVENT_CUSTOM",
    "WORLD_ENTITY_CHARACTER",
    "WORLD_ENTITY_FACTION",
    "WORLD_ENTITY_ASSET",
    "WORLD_LOCATION_POINT",
    "WORLD_LOCATION_REGION",
    "WORLD_LOCATION_ROUTE",
    # Utilities
    "generate_uuid",
    "utc_now",
]


def generate_uuid() -> uuid.UUID:
    """生成 UUID 主键"""
    return uuid.uuid4()


def utc_now() -> datetime:
    """返回当前 UTC 时间（naive datetime，与 TIMESTAMP WITHOUT TIME ZONE 列兼容）"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlotLedgerStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    DROPPED = "dropped"


class TaskStatus(str, Enum):
    """生成任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================
# V3.1 统一引擎：章节定档 tier（docs/generation-v3.1-unified.md §2.1）
# ============================================================
# 四档定义：高潮章 / 转折章 / 推进章 / 过渡章
# auto 表示由定档器自主决策（规格 §2.2 决策函数，宁低勿高）
TIER_CLIMAX = "climax"        # 高潮章：大高潮/揭盅/决裂/卷尾
TIER_TURN = "turn"            # 转折章：中等转折、重要推进
TIER_PROGRESS = "progress"    # 推进章：小转折、日常推进
TIER_TRANSITION = "transition"  # 过渡章：纯过渡、衔接
TIER_AUTO = "auto"            # 自动定档（默认）

# 有效档位集合（auto 不在其中，auto 是请求参数表示"由定档器决策"）
VALID_TIERS = {TIER_CLIMAX, TIER_TURN, TIER_PROGRESS, TIER_TRANSITION}

# 档位 → 铺垫结构深度上限（规格 §2.1 表）
TIER_MAX_DEPTH = {
    TIER_CLIMAX: 6,
    TIER_TURN: 4,
    TIER_PROGRESS: 2,
    TIER_TRANSITION: 1,
}

# 档位 → 铺陈段（development 区）占比目标（规格 §2.1 表，铺陈段占全章比例）
TIER_DEVELOPMENT_RATIO = {
    TIER_CLIMAX: 0.30,
    TIER_TURN: 0.50,
    TIER_PROGRESS: 0.70,
    TIER_TRANSITION: 0.90,
}


# ============================================================
# 叙事主体层 - Book 是整个系统的根节点
# ============================================================
# 设计意图：Velluma 采用"书籍 → 章节 → 角色"的三级树状结构
# 选择 UUID 而非自增ID的原因：
#   1. 支持多实例部署时ID不会冲突
#   2. 便于前端缓存和离线场景
#   3. 避免 ID 枚举攻击（书籍ID不可预测）
class Book(Base):
    """
    书籍表 - 叙事主干系统的根实体

    业务含义：
    - 代表一个独立的创作项目，是所有其他实体的直接或间接所有者
    - worldview_settings 存储全局世界观设定（如时间线、规则、物理法则）
    - global_sys_prompt 用于注入 LLM 的系统级上下文（世界观约束）

    表关系设计依据：
    - 使用 cascade="all, delete-orphan" 确保删除书籍时级联清理所有关联数据
    - 这是数据安全的重要保障，避免"孤儿数据"堆积
    """
    __tablename__ = "books"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    title = Column(String(500), nullable=False)
    genre = Column(String(100), nullable=True)
    global_sys_prompt = Column(Text, nullable=True)
    core_motifs_taboos = Column(Text, nullable=True)
    worldview_settings = Column(JSONB, default=dict)
    golden_snippets = Column(JSONB, default=list)
    style_blacklist = Column(JSONB, default=list)
    # CP2.3a：书级大纲（章节卡生成输入）+ 滚动摘要（发布时更新，蓝图 §5.2）
    outline = Column(Text, nullable=True)
    rolling_summary = Column(Text, nullable=True)
    # V4.2 Reader Mirror：期待账本 + 张力曲线 + 信息差（JSONB 整体存储，避免新建表）
    reader_mirror = Column(JSONB, default=dict)
    # 系统陈词库本书豁免（完整落地批，设计稿 §6.4）：被豁免的 SystemCliche pattern 列表——
    # 审计/扫描/三层合并时跳过（不删全局层，只本书不生效）
    style_cliche_exemptions = Column(JSONB, default=list)
    # 地图比例尺标定（docs/map-scale-spatial.md §2.1，D4）：CRS.Simple 内部坐标 →
    # 现实距离的换算锚。{refs:[{ax,ay,bx,by,days_foot,label}], detour_factor,
    # modes:{...}}；NULL=未标定（距离功能静默降级，prompt 零变化）
    map_scale = Column(JSONB, nullable=True)
    # 时间轴 UI 状态（世界页游标时刻 + 手动视野窗口，按书服务端持久化）：
    # {cursor: 日计数 int, range: {start,end} 年份 int}；NULL/缺键=未设置（自动视野）。
    # 原 localStorage 方案随前端端口扫描换源即漂移（表现为重启后视野重置），弃用。
    timeline_view = Column(JSONB, nullable=True)
    # 学着闭嘴（2026-08-25 战略定稿）：被拒学习的宽恕时间戳 {mute_key: forgiven_at ISO}
    # ——mute_key 形如 wevt:<event_type> / hint:<kind>；键存在=该时刻前的拒绝记录
    # 一笔勾销（作者点「恢复」后重新计数）。静音状态本身不落库，永远从行为数据
    # 派生（services/adaptive/quiet_learning.py），杜绝静音态与历史漂移。
    assist_mutes = Column(JSONB, nullable=True)
    # 世界内核 B9：认知浮现总开关（三时机：泄密疑点/反讽机会/负空间清单
    # 之外的认知模型默认不可见——可见性悖论纪律，docs/world-kernel-foundation.md §8）
    cognition_surfacing = Column(Boolean, default=True, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="book", cascade="all, delete-orphan")
    locations = relationship("MapLocation", back_populates="book", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="book", cascade="all, delete-orphan")
    memories = relationship("MemoryChunk", back_populates="book", cascade="all, delete-orphan")
    story_beats = relationship("StoryBeat", back_populates="book", cascade="all, delete-orphan")
    scene_intents = relationship("SceneIntent", back_populates="book", cascade="all, delete-orphan")
    plot_ledgers = relationship("PlotLedger", back_populates="book", cascade="all, delete-orphan")


# ============================================================
# 叙事单元层 - Chapter 是创作的最小工作单元
# ============================================================
# 工作流设计：
#   draft_text (主笔生成) → review_feedback (审阅质检) → content_text (定稿)
#   revision_count 记录重写次数，用于成本控制和迭代收敛判断
#
# 隐性行为：status 字段变更会触发不同的业务逻辑
#   - "draft": 可编辑，LLM 可继续生成
#   - "published": 不可变更，触发角色状态快照
class Chapter(Base):
    """
    章节表 - 书籍的章节结构

    业务含义：
    - draft_text 是主笔 Agent 的"草稿输出"，可能包含不符合风格的表达
    - review_feedback 存储审阅 Agent 的结构化质检报告（JSONB），包含改进建议
    - content_text 是最终定稿，仅在章节发布时从 draft_text 同步（保留历史版本能力）
    - revision_count 是关键指标：若超过阈值（如 5 次）需人工介入，防止无限重写

    数据流：
    - book_id 来源于 URL path 参数或前端隐藏字段
    - chapter_number 由前端计算（max(existing) + 1），需事务保护防止并发冲突
    - status 变更时需触发：发布流程 = 内容锁定 + 角色状态快照 + 向量化记忆提取
    """
    __tablename__ = "chapters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    chapter_name = Column(String(200), nullable=True)
    title = Column(String(500), nullable=True)
    outline_text = Column(Text, nullable=True)
    content_text = Column(Text, nullable=True)
    draft_text = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    review_feedback = Column(JSONB, default=dict)
    map_activity_range = Column(Text, nullable=True)
    # 世界页章节叙事时间锚（连续日计数，与历法解耦；设计见 docs/world-unified-settings.md §2.4）
    narrative_time = Column(Integer, nullable=True)
    # 本章场景钉（W5-lite）：作者显式钉定本章发生的地点——切片「脚下」的第一优先级，
    # 缺省时回落到事件/在场推演（docs/world-writing-bridge.md §10.2）
    scene_location_id = Column(UUID(as_uuid=True), ForeignKey("world_locations.id", ondelete="SET NULL"), nullable=True)
    tension_level = Column(Integer, default=5, nullable=False)
    pacing_style = Column(String(50), default="balanced", nullable=False)
    revision_count = Column(Integer, default=0)
    status = Column(String(50), default="draft")
    generation_run_id = Column(String(64), nullable=True)
    generation_status = Column(JSONB, default=dict)
    generation_checkpoints = Column(JSONB, default=list)
    # V4.0 资产字典：存储当前场景出现的专有名词的物理定义（如机甲体积、武器形态）
    chapter_assets_schema = Column(Text, nullable=True, default="")
    # 世界状态快照：章节发布时提取，作为下一章的初始约束
    world_snapshot = Column(JSONB, default=dict)
    # 意图驱动设置：保存用户的创作意图和生成配置
    creative_intents = Column(JSONB, default=list)
    chapter_goals = Column(JSONB, default=list)
    selected_plan_type = Column(String(50), nullable=True)
    user_overrides = Column(JSONB, default=dict)
    author_intent = Column(Text, nullable=True)
    # BS-ADF：Track B 暂停时持久化的全章槽位卡（JSONB），供刷新后 / /rerender-beat 兜底恢复
    bsadf_beat_slots = Column(JSONB, default=list)
    # 章级谋篇·软脉络（docs/chapter-planning-spine.md §2.1）：{intent:{text,source},
    # anchors:[{id,text,source,status}]}。NULL=本章无脉络（一切 UI 静默缺席，D-3 可完全忽略）。
    # 章级一次性消耗品：不进正文版本历史、不触发 world-refresh（度优先）。
    spine = Column(JSONB, nullable=True)
    # 自动阅读幂等锚（2026-08-25 战略定稿「系统自己去读」）：{hash, last_run_at,
    # last_created, entities_hash, entities_last_run_at}——内容哈希不变则不重读
    # （切章触发随处发枪也安全）；entities_* 两键是全书通读阶段 A（实体候选抽取）
    # 的独立幂等/间隔键（2026-08-26 分立：认人不封锁记事）。NULL=从未读过。
    auto_read_state = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="chapters")
    entities = relationship("ChapterEntity", back_populates="chapter", cascade="all, delete-orphan")
    locations = relationship("ChapterMapLocation", back_populates="chapter", cascade="all, delete-orphan")
    assets = relationship("ChapterAsset", back_populates="chapter", cascade="all, delete-orphan")
    memories = relationship("MemoryChunk", back_populates="chapter", cascade="all, delete-orphan")
    story_beats = relationship("StoryBeat", back_populates="chapter", cascade="all, delete-orphan")
    scene_intents = relationship("SceneIntent", back_populates="chapter", cascade="all, delete-orphan")
    plot_ledgers = relationship(
        "PlotLedger",
        foreign_keys="PlotLedger.chapter_id",
        back_populates="chapter",
        cascade="all, delete-orphan",
    )
    resolved_plot_ledgers = relationship(
        "PlotLedger",
        foreign_keys="PlotLedger.resolved_in_chapter_id",
        back_populates="resolved_in_chapter",
    )


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


class StoryBeat(Base):
    """
    故事节拍表 - 章节内的剧情单元。

    业务含义：
    - 代表章节内的最小剧情单元（Beat），是 Agentic 工作流的核心数据模型
    - 每个 beat 包含：位置、视角角色、动作摘要、进入/退出状态、红线约束等
    - 用于支撑"并行生成 → 统稿"的工作流模式

    数据流：
    - 由 Planner Agent 生成，分配给 Draft Agent 并行创作
    - 每个 beat 可关联 SceneIntent（场景意图）
    - 可关联 PlotLedger（伏笔钩子）实现跨章节剧情连贯

    核心字段：
    - summary: 节拍剧情概述，用于 LLM 理解本节核心内容
    - action_summary: 动作化执行摘要，用于指导生成动作类内容
    - entry_state / exit_state: 进入/退出状态，确保剧情不越界
    - red_lines: 红线约束列表，防止生成违规内容
    - pacing_type: 节奏类型 (Fast/Medium/Slow)，影响字数分配权重
    - pov_aperture: 叙事光圈，控制 Drafting 阶段的视角景深 (V4.0)
    - persistent_state_anchors: 持久状态锚点列表 (V4.0)
    """
    __tablename__ = "story_beats"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    beat_id = Column(String(120), nullable=True)
    beat_type = Column(String(100), default="progression")
    position = Column(Integer, default=0)
    location = Column(Text, nullable=True)
    pov_character = Column(String(120), nullable=True)
    # V4.0: 叙事光圈，控制 Drafting 阶段的视角景深
    pov_aperture = Column(String(50), nullable=True, default="subjective_observation")
    # V4.0: 持久状态锚点列表，用于跨 Beat 状态连贯
    persistent_state_anchors = Column(JSONB, default=list)
    # POV 角色的知觉状态（意识清醒程度与物理行动力），由 Planner 生成
    pov_perception_state = Column(Text, nullable=True, default="正常")
    anchor_pov = Column(String(120), nullable=True)
    original_actor = Column(String(120), nullable=True)
    # CP1.4：本拍在场角色列表（EntityAuditor / 上下文引擎确定性通道依赖此字段）
    participants = Column(JSONB, default=list)
    action_summary = Column(Text, nullable=True)
    worldbuilding_instruction = Column(Text, nullable=True)
    entry_state = Column(Text, nullable=True)
    exit_state = Column(Text, nullable=True)
    red_lines = Column(JSONB, default=list)
    word_count_target = Column(Integer, default=0)
    summary = Column(Text, nullable=False)
    meta = Column("metadata", JSONB, default=dict)
    status = Column(String(50), default="planned")
    pacing_type = Column(String(50), nullable=True)
    weight = Column(Integer, default=1)
    # V3.0 引爆链：节拍作为铺垫树的阅读序分段视图（§4.4）
    # chain_node_ids: 本拍承载的 SetupNode id 列表
    chain_node_ids = Column(JSONB, default=list)
    # sets_up: 本拍埋设的引爆点/未来章节铺垫（指向 PAYLOAD 或 future chapter）
    sets_up = Column(JSONB, default=list)
    # payoff_of: 本拍兑现的旧伏笔（指向 PlotLedger.ledger_key 或 SetupNode.id）
    payoff_of = Column(JSONB, default=list)
    # assignment: 写作情绪任务（suppress/tighten/release_partial/texture）
    assignment = Column(String(50), nullable=True)
    # question_open: 本拍向读者打开的问题
    question_open = Column(Text, nullable=True)
    # question_delays: 本拍让读者抱着走、不回答的问题
    question_delays = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="story_beats")
    chapter = relationship("Chapter", back_populates="story_beats")
    scene_intents = relationship("SceneIntent", back_populates="story_beat")
    plot_ledgers = relationship("PlotLedger", back_populates="story_beat")


class SceneIntent(Base):
    """
    场景意图表 - 单个节拍内的场景级 AI 指令。

    业务含义：
    - 代表一个节拍（Beat）内的场景级 AI 生成指令
    - 包含目标（goal）、障碍（obstacle）、策略（tactic）、 stakes（风险）等元素
    - 用于在 Draft 阶段为 LLM 提供更精细的生成指导

    数据流：
    - 由 Scene Intent Agent 生成（独立于 Planner）
    - 关联到具体的 StoryBeat
    - 在生成 chunk 时作为上下文注入

    核心字段：
    - goal: 场景目标/任务
    - obstacle: 需要克服的障碍
    - tactic: 达成目标的策略/手段
    - stakes: 失败的后果/风险
    """
    __tablename__ = "scene_intents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    story_beat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("story_beats.id", ondelete="SET NULL"),
        nullable=True,
    )
    intent_label = Column(String(120), nullable=False)
    character_name = Column(String(120), nullable=True)
    goal = Column(Text, nullable=False)
    obstacle = Column(Text, nullable=True)
    tactic = Column(Text, nullable=True)
    stakes = Column(Text, nullable=True)
    constraints = Column(JSONB, default=list)
    priority = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="scene_intents")
    chapter = relationship("Chapter", back_populates="scene_intents")
    story_beat = relationship("StoryBeat", back_populates="scene_intents")


class PlotLedger(Base):
    """
    情节账本表 - 管理伏笔/钩子的生命周期。

    业务含义：
    - 跟踪跨章节的伏笔（Plot Hook）生命周期
    - 支持伏笔的创建、绑定、解决、废弃等状态流转
    - 用于实现"草蛇灰线，伏脉千里"的叙事技法

    数据流：
    - 由系统或用户创建伏笔（hook）
    - 在章节生成时绑定到 StoryBeat
    - 伏笔被解决后标记为 closed，或主动废弃标记为 dropped

    核心字段：
    - ledger_key: 伏笔的唯一标识（如 "hero-backstory-reveal"）
    - hook_id: 可读的唯一标识（如 "hk-001"）
    - entry_type: 伏笔类型（foreshadow / callback / twist 等）
    - status: 状态 (open/closed/dropped)
    - resolved_in_chapter_id: 解决伏笔的章节 ID

    状态流转：
    - open: 伏笔已创建，等待在后续章节中揭示
    - closed: 伏笔已在某章节中解决
    - dropped: 伏笔被废弃，不再需要解决
    """
    __tablename__ = "plot_ledgers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    story_beat_id = Column(
        UUID(as_uuid=True),
        ForeignKey("story_beats.id", ondelete="SET NULL"),
        nullable=True,
    )
    ledger_key = Column(String(150), nullable=False)
    hook_id = Column(String(150), nullable=True)
    entry_type = Column(String(50), default="foreshadow")
    content = Column(Text, nullable=False)
    status = Column(String(20), default=PlotLedgerStatus.OPEN.value, nullable=False)
    created_at_chapter = Column(Integer, nullable=True)
    resolved_in_chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 世界页 M3：伏笔双时间锚（连续日计数；与章节锚换算，纯设定型伏笔可不关联章节）
    world_time_planted = Column(Integer, nullable=True)
    world_time_resolved = Column(Integer, nullable=True)
    meta = Column("metadata", JSONB, default=dict)
    # C2 真相面（docs/canon-world-fusion.md §4.2）：伏笔天然是信息层对象——
    # 埋设=建立「表象—真相」差集，回收=差集收敛。canon hook 并入本表后，
    # [hook] prompt 段装配源切到此（open 取前 8，格式冻结 K3）。
    canon_text = Column(Text, default="")    # 里：作者真相（空=无双层需求）
    public_text = Column(Text, default="")   # 表：读者所见表象
    reveal_plan = Column(Text, default="")   # 揭示计划文本
    created_at = Column(DateTime, default=utc_now)

    book = relationship("Book", back_populates="plot_ledgers")
    chapter = relationship("Chapter", foreign_keys=[chapter_id], back_populates="plot_ledgers")
    story_beat = relationship("StoryBeat", back_populates="plot_ledgers")
    resolved_in_chapter = relationship("Chapter", foreign_keys=[resolved_in_chapter_id], back_populates="resolved_plot_ledgers")

    __table_args__ = (
        UniqueConstraint("book_id", "ledger_key", name="uq_plot_ledger_book_key"),
        CheckConstraint(
            "status IN ('open', 'closed', 'dropped')",
            name="ck_plot_ledgers_status_valid",
        ),
    )


class GenerationTask(Base):
    """
    章节生成任务�?- 异步任务队列

    业务含义�?
    - 支持将章节生成任务提交到队列，异步执�?
    - 用户可立即获得任务ID，通过轮询或WebSocket获取进度
    - 支持任务取消、重试、查看历�?
    """
    __tablename__ = "generation_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False)
    
    # 任务状�?
    status = Column(String(20), default=TaskStatus.PENDING, nullable=False)
    current_stage = Column(String(50), nullable=True)
    progress_percent = Column(Integer, default=0)
    
    # 任务配置
    config = Column(JSONB, default=dict)
    beats = Column(JSONB, default=list)
    
    # 结果数据
    partial_result = Column(Text, nullable=True)
    final_text = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # Celery 相关
    celery_task_id = Column(String(100), nullable=True)
    retry_count = Column(Integer, default=0)
    
    # 时间�?
    submitted_at = Column(DateTime, default=utc_now)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    # 关联关系 - 明确指定 foreign_keys 避免歧义
    chapter = relationship("Chapter", back_populates="generation_tasks", foreign_keys=[chapter_id])
    book = relationship("Book", back_populates="generation_tasks", foreign_keys=[book_id])

    def to_dict(self) -> dict:
        """转换为字典（用于API响应）"""
        return {
            "id": str(self.id),
            "chapter_id": str(self.chapter_id),
            "book_id": str(self.book_id),
            "status": self.status,
            "current_stage": self.current_stage,
            "progress": self.progress_percent,
            "config": self.config,
            "partial_result": self.partial_result,
            "final_text": self.final_text if self.status == TaskStatus.SUCCESS else None,
            "error": self.error_message if self.status == TaskStatus.FAILED else None,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# 更新关联关系 - 明确指定 foreign_keys 避免歧义
Book.generation_tasks = relationship(
    'GenerationTask', 
    back_populates='book', 
    cascade='all, delete-orphan',
    foreign_keys='GenerationTask.book_id'
)
Chapter.generation_tasks = relationship(
    'GenerationTask', 
    back_populates='chapter', 
    cascade='all, delete-orphan',
    foreign_keys='GenerationTask.chapter_id'
)


# ============================================================
# 观测层 - GenerationRun 记录单次 LLM 调用（Phase 0 观测基础设施）
# ============================================================
# 设计意图（2.0 Phase 0）：
#   - 调研报告 §2.2-13 指出全链路零 token 计量，call_llm 丢弃 response.usage。
#   - 本表是观测层的物理载体，每章生成产出 ~15-20 行（6 拍计）。
#   - 字段 model_slot 与 2.0 三槽位（reasoning/creative/light）对齐；
#     thinking_tokens 拆分用于验证 creative 槽位 thinking 确实关闭（T3 验收）。
#   - degraded 字段承接 T5 降级显式化：所有 fallback 写入 {reason, action}。
#
# 与 Chapter.generation_run_id 的关系：
#   - chapter.generation_run_id 存的是本次生成的 run_id（字符串）
#   - 本表 run_id 列与之对齐，便于按 run 聚合查询
class GenerationRun(Base):
    """
    生成调用计量表 - 记录单次 LLM 调用的 token/耗时/模型/降级。

    业务含义：
    - 观测层核心：每章可按 stage 聚合 token 成本，产出章级成本报告
    - degraded 字段承接"失败不静默"原则（2.0 设计原则 P5）
    - thinking_tokens 拆分用于验证 creative 槽位 thinking 关闭效果

    数据流：
    - 由 services/observability/run_recorder.py 在 call_llm_with_usage 包装层写入
    - chapter_id 与 Chapter 关联，run_id 与 Chapter.generation_run_id 对齐
    """
    __tablename__ = "generation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    run_id = Column(String(64), nullable=True, index=True)
    stage = Column(String(64), nullable=False)  # planning.beats / drafting.beat_3 / stitching / reviewing / refining / publish.*
    model_slot = Column(String(32), nullable=True)  # reasoning / creative / light
    model_name = Column(String(128), nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    thinking_tokens = Column(Integer, nullable=True)  # 解析 response.usage.completion_tokens_details.reasoning_tokens
    latency_ms = Column(Integer, nullable=True)
    degraded = Column(JSONB, nullable=True)  # {reason, action, detail?}
    created_at = Column(DateTime, default=utc_now)


created_at = Column(DateTime, default=utc_now)


# ============================================================
# Phase 1 CP2.1 新增模型 - 文风体系 / 章节卡 / 作者样本 / 系统禁词
# ============================================================
# 设计依据：蓝图 §4.1.3（ChapterCard）、§4.4（StyleCard）、§5.1（AuthorSample）、
# §4.4 禁词表（SystemCliche 替代 validators.py 硬编码）


class ChapterCard(Base):
    """章节卡 - 章节间胶水（蓝图 §4.1.3）。

    业务含义：
    - 填补 Sudowrite 缺失的 chapter glue：每章一张，记录本章 purpose + 必达事件
    - CP2.3 合并闸门的核心数据载体（卡 + 节拍联合预览）
    - 形成章节卡链：任意时刻可回答"第 N 章时剧情进展到哪"

    状态流转：
    - draft: AI 生成或人工创建后待确认
    - confirmed: 用户确认（CP2.3 合并闸门）
    - generating: 进入生成主流程
    - done: 章节定稿
    """
    __tablename__ = "chapter_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    chapter_number = Column(Integer, nullable=False)
    purpose = Column(Text, nullable=True)                       # 一句话主旨（场景化语言）
    must_hit_events = Column(JSONB, default=list)               # [{"event","emotion","must"}]
    involved_characters = Column(JSONB, default=list)           # [{"id","entry","exit"}]
    foreshadow_ops = Column(JSONB, default=list)                # [{"action","ledger_id","note"}]
    continuity = Column(JSONB, default=dict)                    # {"from_chapter","time_gap","location"}
    word_target = Column(Integer, default=3000)
    pacing = Column(String(50), default="medium")
    tension = Column(Integer, default=5)
    style_override_id = Column(UUID(as_uuid=True), ForeignKey("style_cards.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="draft")
    # V3.0 引爆链：章节卡生成时同步产出的引爆点候选列表（闸门 1 的输入）
    # 结构：[{"description", "emotional_target", "answers_question", "opens_question", "why_now"}]
    payload_moment = Column(JSONB, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class StyleCard(Base):
    """文风卡 - 书级一张 + 章级可覆盖（蓝图 §4.4）。

    业务含义：
    - 正面画像（positive_profile）：句长节奏 / 词汇层级 / 语域 / 开头结尾习惯
    - 负面清单（negative_list）：禁词 / 禁句式 + 每条替代规则
    - chapter_id=null → 书级（默认）；非 null → 章级覆盖
    """
    __tablename__ = "style_cards"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True)
    positive_profile = Column(JSONB, default=dict)
    negative_list = Column(JSONB, default=list)                 # [{word, alternative, severity: warning|blocker}]（severity 缺省=warning，旧数据零迁移）
    dialogue_ratio_target = Column(Float, nullable=True)        # 对话占比目标（0-1）
    paragraph_rhythm = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    # 意图旋钮档位（S4）：{knob_key: tier 1-5}——register/rhythm/density/warmth；
    # 缺键 = 自动档（不注入该维度，交给画像与样本）。对话旋钮落 dialogue_ratio_target 不在此。
    style_knobs = Column(JSONB, default=dict)
    # 画像字段锁（完整落地批）：positive_profile 中被作者锁定的键名列表——
    # 锁定字段不被「从样本提炼」结果覆盖（特殊文体/亲笔描述的保护，设计稿 §6.6）
    locked_keys = Column(JSONB, default=list)
    # 指纹写穿缓存：GET /style-fingerprint 计算后回写（读路径仍实时算保新鲜，
    # 此列供未来消费方如漂移提醒直接取用，非读缓存）
    fingerprint = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class AuthorSample(Base):
    """作者样本库 - few-shot 文风锚定（蓝图 §5.1）。

    业务含义：
    - 用户上传的作者已写文本（或从已发布章节提取）
    - 向量化后供 ContextEngine P0 检索做 few-shot（蓝图 §4.3.2）
    - 与 MemoryChunk 区分：本表是"写作风格检索"，无时间衰减，无 PlotLedger 权重

    数据流：
    - 写入：POST /api/books/{id}/samples 或自动从已发布章节提取
    - 向量化：保存时调 embedding 入库
    - 检索：ContextEngine 用本章 outline 做 embedding → cosine 检索 top-k
    """
    __tablename__ = "author_samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True)
    scene_type = Column(String(50), default="general")          # dialogue/action/lyrical/suspense/general
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536), nullable=True)
    word_count = Column(Integer, default=0)
    source = Column(String(50), default="manual")               # manual/golden_snippet/published_chapter
    # 时期标记（完整落地批）：recent=近期（语料聚合与检索兜底优先）/ early=早期（仅存档与逐条指纹）
    era = Column(String(16), default="recent")
    # 收藏（完整落地批）：检索兜底流优先取收藏样本（作者认证的最佳示范）
    favorite = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)


class SystemCliche(Base):
    """系统级禁词表 - 替代 validators.py 硬编码（蓝图 §4.4）。

    业务含义：
    - 内置默认禁词表（CP2.1c 种子化），含中英双语
    - 与 book.style_blacklist（书级）+ style_card.negative_list（书级 StyleCard）三层合并
    - severity=blocker 的硬阻断 fail-fast；warning 的仅记日志

    数据流：
    - 启动时若表为空，从 services/style/default_cliches.py 种子化
    - 用户可全局 CRUD 覆盖（POST/PUT/DELETE /api/system/cliches）
    - validators.StyleClicheValidator 通过 cliche_provider 读此表（带内存缓存）
    """
    __tablename__ = "system_cliches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    pattern = Column(String(200), nullable=False)               # 字面词或正则
    is_regex = Column(Boolean, default=False)
    language = Column(String(10), default="zh")                 # zh/en
    category = Column(String(50), default="cliche")             # cliche/house_voice/transition
    severity = Column(String(20), default="warning")            # warning/blocker
    alternative = Column(Text, nullable=True)                   # 替代建议
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)


class StyleInboxItem(Base):
    """文风收件箱 - 候选池（文风模块重构 S3，docs/style-module-redesign.md §5/§7.1）。

    业务含义：
    - 写作台「这不像我」/ 负面清单抓虫等产生的**候选**，先进收件箱待作者过目，
      绝不直接生效（红线：候选不落库生效，作者裁决即闸门）
    - 与 world_event_candidates 同构的物理隔离候选池（✓/✗/撤销契约）
    - confirm 负面候选 → 写入书级 StyleCard.negative_list（任务包 B 起不再
      同步 book.style_blacklist——该列冻结只读，负面清单唯一权威）

    kind 语义：
    - negative_candidate  禁词候选 {word, alternative?, source_text?}
    - sample_candidate    样本候选 {content, scene_type?}（预留，黄金片段自动汇入可走此）
    """
    __tablename__ = "style_inbox_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(50), default="negative_candidate")     # negative_candidate / sample_candidate
    payload = Column(JSONB, default=dict)                       # kind 对应的结构化载荷
    status = Column(String(20), default="pending")              # pending / confirmed / dismissed
    source = Column(String(50), default="writing_desk")         # writing_desk / scan / audit
    created_at = Column(DateTime, default=utc_now)
    resolved_at = Column(DateTime, nullable=True)


# ============================================================
# Phase 2 CP3.1a 新增模型 - QualityReport 双层审计报告
# ============================================================
# 设计依据：蓝图 §4.8.3（校验引擎 QualityReport 数据载体）
#
# 业务含义：
# - 承载双层审计（CP3.1b 代码级 + CP3.1c LLM 级）的结构化结果
# - metrics 列存代码级量化指标（禁词命中率/句长 CV/对话占比/字数达标率/红线违反）
# - findings 列存 LLM 级证据链问题（severity/category/quote/offset/beat_id/detail/suggestion）
# - degraded 列承接"失败不静默"原则：审计降级时填 {reason, action}
# - verdict 三态：pass / pass_with_fixes / fail / unaudited（降级时）
#
# 数据流：
# - 由 services/validation/code_auditors.py（CP3.1b）+ llm_auditor.py（CP3.1c）写入
# - 由 routes/chapter_generation/__init__.py 的 GET /quality-report 读取（CP3.1c 加）
# - chapter_id + run_id 组合定位一次生成 run 的审计结果


class QualityReport(Base):
    """质量报告表 - 章节双层审计结构化结果（蓝图 §4.8.3）。

    业务含义：
    - 每章生成后由代码级审计（7 个 Auditor）+ LLM 级审计（证据链）产出一份报告
    - metrics 承载量化指标，供前端 QualityReportPanel 展示指标卡片
    - findings 承载证据链问题，供精修阶段（CP3.2）作为证据驱动输入
    - verdict 是最终闸门结论，影响是否进入精修/重写

    数据流：
    - 写入：CP3.1b/CP3.1c 审计流程通过 QualityReportRepository.create() 写入
    - 读取：GET /api/chapters/{id}/quality-report（CP3.1c）+ 精修阶段（CP3.2）
    - 关联：chapter_id 指向被审计章节；run_id 与 Chapter.generation_run_id 对齐，
      便于按生成 run 聚合查询
    """
    __tablename__ = "quality_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    run_id = Column(String(64), nullable=True, index=True)
    # 量化指标（代码级审计产出，蓝图 §4.8.1）
    # 示例：{"cliche_hits_per_1k": 0.4, "sentence_len_cv": 0.62,
    #        "dialogue_ratio": 0.31, "word_achieve_rate": 0.97, "red_line_violations": 0}
    metrics = Column(JSONB, default=dict)
    # 发现的问题（LLM 审计产出，带证据链）
    # 每项：{"severity": "blocker|warning|info", "category": "timeline|characterization|
    #        worldview|fact|style", "quote": "原文引用", "offset": [start, end],
    #        "beat_id": int|null, "detail": "...", "suggestion": "..."}
    findings = Column(JSONB, default=list)
    # 降级标记（CP3.1c 审计降级时填充）：{reason, action, detail?}
    degraded = Column(JSONB, nullable=True)
    # 审计结论：pass / pass_with_fixes / fail / unaudited（降级时）
    verdict = Column(String(50))
    created_at = Column(DateTime, default=utc_now)


# ============================================================
# V4.0 Canon — 作者脑中世界的叙事知识图谱
# ============================================================
# 设计依据：docs/generation-v4.0-canon.md §2
#
# 核心定位：
# - Canon 是作者脑中真相的结构化存储（不依赖已发布文本推断）
# - private 字段绝不许泄露到正文（由一致性引擎 + prompt 注入保障）
# - 图谱结构（节点+边）天然支持可视化、连锁分析、路径检索
#
# 节点类型（NODE_TYPE_*）：
#   CHARACTER  角色（metadata: identity/power/motivation/arc_position）
#   EVENT      事件（metadata: when/where/who/consequence）
#   OBJECT     物件（metadata: owner/ability/origin）
#   PLACE      地点（metadata: description/inhabitants）
#   HOOK       伏笔节点（metadata: strength/bury_style/payoff_style/status）
#
# 边类型（EDGE_TYPE_*）：
#   CAUSES     因果（A 导致 B）
#   BEFORE     时序（A 在 B 之前）
#   HINTS      弱伏笔暗示
#   SETUPS     强伏笔铺设
#   CALLBACKS  回收
#   ECHOES     呼应（已回收后的二次呼应）
#
# 可见性（VISIBILITY_*）：
#   PUBLIC     已在正文写出（读者已知）
#   PRIVATE    仅作者知道（绝不许泄露到正文）
#   PARTIAL    部分揭示（读者知道一部分）
#
# 表设计决策：
# - 用邻接表 + JSONB 属性（不引入 Neo4j）
# - 图算法在前端 Cytoscape.js 做，后端只做 CRUD + 基础查询
# - 两张表通过 book_id 隔离，不与现有 Character/PlotLedger 直接关联
#   （独立层，避免迁移风险；可通过 metadata.ref_id 软关联现有实体）

# ---- 节点类型常量 ----
NODE_TYPE_CHARACTER = "character"
NODE_TYPE_EVENT = "event"
NODE_TYPE_OBJECT = "object"
NODE_TYPE_PLACE = "place"
NODE_TYPE_HOOK = "hook"
NODE_TYPES = {
    NODE_TYPE_CHARACTER, NODE_TYPE_EVENT, NODE_TYPE_OBJECT,
    NODE_TYPE_PLACE, NODE_TYPE_HOOK,
}

# ---- 边类型常量 ----
EDGE_TYPE_CAUSES = "causes"
EDGE_TYPE_BEFORE = "before"
EDGE_TYPE_HINTS = "hints"
EDGE_TYPE_SETUPS = "setups"
EDGE_TYPE_CALLBACKS = "callbacks"
EDGE_TYPE_ECHOES = "echoes"
EDGE_TYPES = {
    EDGE_TYPE_CAUSES, EDGE_TYPE_BEFORE, EDGE_TYPE_HINTS,
    EDGE_TYPE_SETUPS, EDGE_TYPE_CALLBACKS, EDGE_TYPE_ECHOES,
}

# ---- 可见性常量 ----
VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
VISIBILITY_PARTIAL = "partial"
VISIBILITIES = {VISIBILITY_PUBLIC, VISIBILITY_PRIVATE, VISIBILITY_PARTIAL}


class CanonNode(Base):
    """Canon 节点 — 作者脑中世界的一个事实/设定/伏笔。

    业务含义：
    - canon_text 是作者脑中的完整真相
    - public_text 是读者目前在正文里看到的（可能截断/伪装/完全不同）
    - visibility 控制生成时是否允许在正文出现
      · public：可直接出现
      · private：绝不许直接出现，但可作为角色行为的隐藏动机
      · partial：可出现 public_text 部分，canon_text 的其余部分仍 private

    使用场景：
    - 作者在 Canon 编辑器手动创建
    - 自动提取器从已发布文本提取（source=auto_extracted，confidence=tentative）
    - 生成流水线 Phase 0 加载，注入到 prompt 作为强约束
    - 一致性引擎对照检查新文本是否泄露 private 字段

    警示：metadata.ref_id 是软关联现有实体（Character.id 等），无外键约束。
    软关联失败时（如原实体被删），通过 metadata.ref_type 仍可识别。
    """

    __tablename__ = "canon_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(20), nullable=False, index=True)
    label = Column(String(200), nullable=False)

    # 内容双层
    canon_text = Column(Text, default="")
    public_text = Column(Text, default="")

    # 可见性
    visibility = Column(String(20), default=VISIBILITY_PUBLIC)

    # 章节追溯
    appeared_in = Column(JSONB, default=list)  # [chapter_number, ...]
    revealed_in = Column(JSONB, default=list)  # [chapter_number, ...]

    # 揭示计划
    reveal_plan = Column(Text, default="")
    expected_reveal_chapter = Column(Integer, nullable=True)

    # 元数据
    tags = Column(JSONB, default=list)
    confidence = Column(String(20), default="confirmed")  # confirmed | tentative | draft
    source = Column(String(20), default="author")  # author | auto_extracted | mixed
    metadata_ = Column("metadata", JSONB, default=dict)  # 自由扩展（避开 SQL 保留字）

    # C2 信息面挂接（docs/canon-world-fusion.md §4.1）：ref 指向世界对象
    # （entity | location | ledger），label/type 读取时由世界对象推演（根治名字漂移
    # →泄密漏检）。无单一外键（三possible 目标），唯一性与级联清理在应用层：
    # migrate-canon 建立 / world 对象删除时同步清 overlay（world_repository）。
    ref_type = Column(String(20), nullable=True)  # entity | location | ledger | NULL=自由节点
    ref_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # 关系（双向）
    out_edges = relationship(
        "CanonEdge",
        foreign_keys="CanonEdge.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    in_edges = relationship(
        "CanonEdge",
        foreign_keys="CanonEdge.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<CanonNode {self.type}:{self.label}>"


class CanonEdge(Base):
    """Canon 边 — 两个节点之间的叙事关系。

    业务含义：
    - type 决定关系语义（因果/时序/伏笔链）
    - visibility 决定该关系是否已在正文揭示
    - strength 1-10，影响连锁分析的优先级
    - established_in 记录该关系在哪些章节建立（用于追溯）

    使用场景：
    - 作者手动建立（如"兰星 → causes → 复仇动机"）
    - 自动提取（如检测到"兰星父之死"和"复仇"共现，推断因果关系）
    - 变更连锁分析的核心数据源（改一个节点，沿边追溯影响）
    """

    __tablename__ = "canon_edges"
    __table_args__ = (
        # 防止重复边（同源同目标同类型只能有一条）
        UniqueConstraint("source_id", "target_id", "type", name="uq_canon_edge_triplet"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("canon_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=True), ForeignKey("canon_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    type = Column(String(20), nullable=False)
    strength = Column(Integer, default=5)  # 1-10
    visibility = Column(String(20), default=VISIBILITY_PUBLIC)
    note = Column(Text, default="")
    established_in = Column(JSONB, default=list)  # [chapter_number, ...]
    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    source = relationship("CanonNode", foreign_keys=[source_id], back_populates="out_edges")
    target = relationship("CanonNode", foreign_keys=[target_id], back_populates="in_edges")

    def __repr__(self):
        return f"<CanonEdge {self.type} strength={self.strength}>"


# ============================================================
# V5.0 World 设定层（地图 + 时间线 + 事件溯源，独立于 Canon）
# ============================================================
# 与 Canon（关系图谱 + private 真相）并存的新设定层，通过 book_id 隔离。
# - world_events：事件事实源（append-only），时变状态全靠 computeWorldState 推演
# - world_locations：地点（带空间坐标 x/y，复杂几何放 geometry JSONB）
# - world_entities：人物/势力/资产固有属性（极简身份证，无时变状态）
# 三条决策（照搬世界绘卷）：
# ① 出生/死亡由 birth/death 事件承载，character 不存 birth_time
# ② move 事件 payload 含 path，沿弧长插值在途位置
# ③ 势力疆域写在 territory_change 事件 payload（完整 polygon），无独立快照表

# ---- 事件类型 ----
WORLD_EVENT_BIRTH = "birth"
WORLD_EVENT_DEATH = "death"
WORLD_EVENT_MOVE = "move"
WORLD_EVENT_BATTLE = "battle"
WORLD_EVENT_TERRITORY_CHANGE = "territory_change"
WORLD_EVENT_FOUND = "found"
WORLD_EVENT_DESTROY = "destroy"
WORLD_EVENT_ALLIANCE = "alliance"
WORLD_EVENT_WAR_DECLARE = "war_declare"
WORLD_EVENT_CORONATION = "coronation"
WORLD_EVENT_CUSTOM = "custom"

# ---- 实体类型 ----
WORLD_ENTITY_CHARACTER = "character"
WORLD_ENTITY_FACTION = "faction"
WORLD_ENTITY_ASSET = "asset"

# ---- 地点类型 ----
WORLD_LOCATION_POINT = "point"
WORLD_LOCATION_REGION = "region"
WORLD_LOCATION_ROUTE = "route"


class WorldEvent(Base):
    """世界事件（事实源，append-only）。时变状态的唯一来源。

    时变状态（人物位置、势力疆域、生死、归属）一律不存表，
    由 computeWorldState(events, t) 从事件流推演（事件溯源铁律）。
    """

    __tablename__ = "world_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_num = Column(Integer, nullable=False, index=True)  # 全局自增序号（回放顺序）
    event_type = Column(String(32), nullable=False, index=True)
    time_start = Column(Integer, nullable=False)  # 数值时间戳（连续日计数，与历法解耦）
    time_end = Column(Integer, nullable=False)    # 时点事件 time_end == time_start
    location_id = Column(UUID(as_uuid=True), ForeignKey("world_locations.id", ondelete="SET NULL"), nullable=True, index=True)
    participant_ids = Column(JSONB, default=list)   # [world_entity.id, ...] 角色
    faction_ids = Column(JSONB, default=list)       # [world_entity.id, ...] 势力
    payload = Column(JSONB, default=dict)           # 类型相关：birth.parent_ids / move.path / territory_change.polygon 等
    causes = Column(JSONB, default=list)            # [world_event.id, ...] 因果链
    chapter_ref = Column(String, nullable=True)     # 关联章节 id（只读，用于按章过滤世界状态）
    tags = Column(JSONB, default=list)
    note = Column(Text, default="")
    metadata_ = Column("metadata", JSONB, default=dict)
    # ---- 世界内核 v2（B1 · 决策 1 三轴分离）----
    # time_precision：叙事时间精度枚举（exact/interval/unknown）——unknown 允许
    # 事件只靠序约束边定序，不伪造默认日期（AGENTS「无叙事锚不伪造日期」的内核化）
    time_precision = Column(String(16), nullable=True)
    # supersedes：修订链（transaction time 轴）——重写旧章时新事件 supersede
    # 旧事件而非物理删改；append-only 纪律由此保持（决策 1）
    supersedes = Column(UUID(as_uuid=True), ForeignKey("world_events.id", ondelete="SET NULL"),
                        nullable=True, index=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<WorldEvent {self.event_type} seq={self.sequence_num}>"


class WorldEventEdge(Base):
    """事件间时序约束边（B1 · docs/world-kernel-foundation.md §3 决策 1）。

    与因果边（world_events.causes）分管不同语义不混用：时序边管折叠顺序与
    未知日期事件的定位（time_precision=unknown 的事件靠边定序）；因果边管
    一致性检查与连锁分析。append-only，与事件同纪律。
    """

    __tablename__ = "world_event_edges"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_event_id = Column(UUID(as_uuid=True), ForeignKey("world_events.id", ondelete="CASCADE"), nullable=False, index=True)
    object_event_id = Column(UUID(as_uuid=True), ForeignKey("world_events.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # before|after：subject 在 object 之(前|后)
    created_at = Column(DateTime, default=utc_now)

    # uow 依赖边（flush 排序按 relationship 而非裸 FK——无此声明时本表会
    # 排到 chapters/world_events 之前触发 FK 失败，见 B4 施工记录）
    subject_event = relationship("WorldEvent", foreign_keys=[subject_event_id])
    object_event = relationship("WorldEvent", foreign_keys=[object_event_id])


# 世界内核 Intent 生命周期枚举（B2 · docs/world-kernel-foundation.md §2 决策 4：
# 枚举与区间，拒绝概率浮点——意图的不确定性用生命周期+软窗口表达）
INTENT_KINDS = ("beat", "foreshadow", "expectation", "reveal", "promise")
INTENT_LIFECYCLES = (
    "declared", "tentative", "fulfilled", "abandoned", "broken_deliberately",
)


class WorldIntent(Base):
    """统一意图存储（B2 · 四域存在论的 intent 域）——「打算发生的事」。

    归一五类：伏笔(plot_ledgers)/期待(reader_mirror)/揭示计划(canon)/
    节拍(spine 锚点、大纲)/承诺。与 world_events 的模态纪律（决策 3）：
    本表是**可变规划存储**，兑现时产生真 event 并回填 realized_by——
    两张表类型级分离，统一轴不统一真值。

    双读过渡（B2）：迁移脚本幂等复制旧源（source_key 记来源去重），
    IntentRepository 读合并（新表优先/旧表兜底），旧表在全部消费方切走
    并稳定一章后冻结只读（docs/world-kernel-construction-plan.md §3）。
    """

    __tablename__ = "world_intents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False, index=True)          # INTENT_KINDS
    scope = Column(String(16), nullable=False, default="book")     # book|chapter
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    # target 三态（决策 2：逐步收敛到引用，自由文本是过渡态）
    target_type = Column(String(16), nullable=False, default="free_text")  # event_stub|proposition_ref|free_text
    target_ref = Column(String(64), nullable=True)                 # canon_node.id / world_event.id
    target_text = Column(Text, default="")
    # 软窗口（决策 4）：叙事 t 区间或章区间，均可空=不限
    window_t_start = Column(Integer, nullable=True)
    window_t_end = Column(Integer, nullable=True)
    window_chapter_start = Column(Integer, nullable=True)
    window_chapter_end = Column(Integer, nullable=True)
    lifecycle = Column(String(20), nullable=False, default="declared")  # INTENT_LIFECYCLES
    setup_event_id = Column(UUID(as_uuid=True), ForeignKey("world_events.id", ondelete="SET NULL"), nullable=True)
    realized_by = Column(UUID(as_uuid=True), ForeignKey("world_events.id", ondelete="SET NULL"), nullable=True)
    serves_anchor = Column(String(128), default="")
    provenance = Column(String(8), nullable=False, default="author")     # author|ai
    source_key = Column(String(128), nullable=True, index=True)          # 迁移来源幂等键（legacy:<表>:<id>）
    note = Column(Text, default="")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    chapter = relationship("Chapter", foreign_keys=[chapter_id])
    book = relationship("Book", foreign_keys=[book_id])


# 呈现方式枚举（B4 · fabula↔syuzhet 的桥）：发生了 vs 怎么写给读者
DEPICTION_MODES = ("shown", "told", "hinted", "symbolized")


class WorldDepiction(Base):
    """呈现关系（B4 · docs/world-kernel-foundation.md §3）——哪个事实在哪章
    以何种方式被写给读者。读者认知折叠（fold reader 域）的唯一原料；
    负空间引擎（世界真相 − 读者认知 = 可揭示戏剧资本）的数据基座。

    摄入纪律：只经候选池气闸（author 裁决后 confirmed）；status=candidate
    的是 AI/启发式提案，confirmed 才进读者折叠（诚实降级：未回填=unknown）。
    """

    __tablename__ = "world_depictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_type = Column(String(16), nullable=False)  # event | proposition
    subject_id = Column(String(64), nullable=False, index=True)  # world_event.id / canon_node.id
    chapter_id = Column(UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(16), nullable=False, default="shown")  # DEPICTION_MODES
    status = Column(String(16), nullable=False, default="candidate")  # candidate | confirmed
    source = Column(String(16), nullable=False, default="heuristic")  # heuristic | extracted | author
    created_at = Column(DateTime, default=utc_now)

    chapter = relationship("Chapter", foreign_keys=[chapter_id])
    book = relationship("Book", foreign_keys=[book_id])

    __table_args__ = (
        UniqueConstraint("book_id", "subject_type", "subject_id", "chapter_id",
                         name="uq_depiction_subject_chapter"),
    )


class WorldDigestSection(Base):
    """冷层世界总账的分节（B8 · docs/world-cognition-architecture.md §2）。

    节级键控：section_key 唯一；source_refs 未变 → frozen（逐字节冻结，
    缓存友好）；事实节 derived='code'（fold 纯代码渲染零 LLM），综合节
    derived='llm'（悬置之事/弧线张力/基调——只输出结构化 ops 由代码执行）。
    纯派生缓存（不变量 1：可全量重建，DB 是唯一事实源）。

    门控纪律（docs/world-kernel-construction-plan.md §9）：stitch 消费
    双门未开（manifest 数据 + 双模型对照）前保持关闭；kill criterion
    上线时即存在。预算分池：DIGEST_DAILY_LLM_CALLS 与 auto-read 隔离。
    """

    __tablename__ = "world_digest_sections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    section_key = Column(String(128), nullable=False)  # entity:林尘 / arc:北线 / tone
    text = Column(Text, default="")
    source_refs = Column(JSONB, default=dict)  # {entity_ids, event_seq_max, chapter_anchor}
    frozen = Column(Boolean, default=False)
    derived = Column(String(8), nullable=False, default="code")  # code | llm
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    book = relationship("Book", foreign_keys=[book_id])

    __table_args__ = (
        UniqueConstraint("book_id", "section_key", name="uq_digest_book_section"),
    )


class WorldLocation(Base):
    """世界地点（带空间坐标）。region/route 的复杂几何放 geometry JSONB。

    空间坐标用 Float x/y（内部坐标，CRS.Simple 浮点，非像素非经纬度），
    不引 PostGIS——与现有 MapLocation 风格一致，零迁移风险。
    """

    __tablename__ = "world_locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(20), default=WORLD_LOCATION_POINT)  # point/region/route
    parent_id = Column(UUID(as_uuid=True), ForeignKey("world_locations.id", ondelete="SET NULL"), nullable=True)
    coord_x = Column(Float, nullable=True)   # 内部坐标 x
    coord_y = Column(Float, nullable=True)   # 内部坐标 y
    geometry = Column(JSONB, default=dict)   # region: polygon 点[]；route: polyline 点[]
    intro = Column(Text, default="")
    tags = Column(JSONB, default=list)
    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<WorldLocation {self.name} kind={self.kind}>"


class WorldEntity(Base):
    """世界实体（人物/势力/资产固有属性）。极简身份证——无任何时变状态。

    位置/疆域/生死/归属全靠事件推演，本表只存"不变的身份证信息"。
    这是事件溯源成立的关键（与世界绘卷一致）。
    """

    __tablename__ = "world_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(20), nullable=False, index=True)  # character/faction/asset
    name = Column(String(200), nullable=False)
    # M2 档案扩展（docs/world-unified-settings.md §2.1）：别名（RAG/POV 名闸门吃它）、
    # 重要度（上下文注入优先级）、可见性（public=读者已知 / private=作者已知，防 AI 泄底）
    aliases = Column(JSONB, default=list)
    importance = Column(Integer, default=1)
    visibility = Column(String(20), default="public")
    # 画布锚位（单一画布设计）：无推演位置（无事件历史/无疆域）时在地图上的作者摆位。
    # 有故事的角色位置由事件推演（拖=录 move 事件），锚位仅服务"没故事"的实体。
    canvas_x = Column(Float, nullable=True)
    canvas_y = Column(Float, nullable=True)
    intro = Column(Text, default="")
    tags = Column(JSONB, default=list)
    props = Column(JSONB, default=dict)  # 档案字段（appearance/speech_style 等，表驱动 schema）
    # 字段级真相分层（2026-09-03）：{field_key: {level: "private"|"partial",
    # public_text?: str, reveal_chapter?: int|null}}；缺键=公开（零存储）。
    # 字段内容本身即「里」，作者不两边维护；真相层消费链（prompt 注入/泄密检测/
    # 揭示提醒）直接读此列自动感知——派生感知取代物料迁移，不建真相节点副本。
    field_layers = Column(JSONB, default=dict)
    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<WorldEntity {self.entity_type}:{self.name}>"


class WorldMapLayer(Base):
    """世界地图底图·图片层（用户导入的图片拼贴）。

    x/y 为中心点（CRS.Simple 内部坐标），w/h 为尺寸（内部坐标单位）；
    z_index 控制图片间层序（小者在下）。opacity 预留（UI 后加）。
    """

    __tablename__ = "world_map_layers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    image_url = Column(String(500), nullable=False)  # /world-images/{book_id}/{uuid}{ext}
    x = Column(Float, nullable=False)
    y = Column(Float, nullable=False)
    w = Column(Float, nullable=False)
    h = Column(Float, nullable=False)
    z_index = Column(Integer, default=0)
    opacity = Column(Float, default=1.0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<WorldMapLayer {self.image_url} @{self.x},{self.y}>"


class WorldMapStroke(Base):
    """世界地图底图·手绘笔迹（矢量点序列）。

    橡皮 = 前端命中检测后 DELETE 命中的 stroke，不存橡皮笔迹。
    """

    __tablename__ = "world_map_strokes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    color = Column(String(20), nullable=False, default="#475569")
    width = Column(Float, nullable=False, default=3.0)
    points = Column(JSONB, nullable=False, default=list)  # [[x, y], ...] 内部坐标
    created_at = Column(DateTime, default=utc_now)

    def __repr__(self):
        return f"<WorldMapStroke {len(self.points or [])}pts {self.color}>"


class WorldRelation(Base):
    """世界设定层·实体关系边（脑图透镜的边）。

    设计（docs/world-unified-settings.md §2.2）：
    - 有向边：source 对 target 的认知/态度（不对称）
    - 时间性二分：static=True 一直成立；static=False 且 event_ref 非空时
      由事件回放推演激活（锚事件 time_start≤t 才生效）——"关系随事态演变"
    - 时变不入库铁律：激活状态由 computeWorldState 推演，本表不存快照

    警示：业务层校验自环（source == target）。
    """

    __tablename__ = "world_relations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    source_entity_id = Column(
        UUID(as_uuid=True), ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_entity_id = Column(
        UUID(as_uuid=True), ForeignKey("world_entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type = Column(String(50), nullable=False, default="custom")  # ally/enemy/kin/.../custom
    label = Column(String(100), default="")  # 显示名（"义兄弟""杀父仇人"）
    affinity = Column(Integer, nullable=True)  # 可选 -100..100
    note = Column(Text, default="")
    static = Column(Boolean, default=True)  # True=一直成立；False=事件锚定
    event_ref = Column(UUID(as_uuid=True), ForeignKey("world_events.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<WorldRelation {self.source_entity_id}->{self.target_entity_id} {self.relation_type}>"


class WorldEventCandidate(Base):
    """
    候选事件表——写作回流待确认池（docs/world-writing-bridge.md §4.4，W4）。

    与 world_events 物理隔离：候选不参与推演、不进正常图层、不影响 version 主计数
    （账本零污染风险）。作者 ✓ 转正 = 创建真事件（正常分配回放序号）+ status→accepted；
    ✗ = rejected（留痕不进视图）；撤销入账 = 删事件 + reopen 回 pending。

    draft 形状（与 parse-event 输出一致）：
    {summary, event_type, time_start, time_end, participant_ids, participant_names,
     location_id, location_name, note}
    """
    __tablename__ = "world_event_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(
        UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_id = Column(
        UUID(as_uuid=True), ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )
    draft = Column(JSONB, default=dict)
    source = Column(String(20), default="settle")  # settle | finish
    status = Column(String(20), default="pending", nullable=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_world_event_candidates_status_valid",
        ),
        Index("ix_world_candidates_book_status", "book_id", "status"),
    )

    def __repr__(self):
        return f"<WorldEventCandidate {self.status} {(self.draft or {}).get('event_type', '?')}>"


# ============================================================
# NLE-ADF 3.0 世界模型（自适应写作伙伴的系统状态核心）
# ============================================================
# 三层信度的章级状态容器：
# - layer1_facts：已写事实（沉淀锁死的段落 + 涌现实体，不可变，追加式）
# - layer2_intent：意图推断（大纲转化 or 正文反推，可变，信度标注）
# - layer3_projections：未来推测（基于1+2的概率画面预测，可变）
# 组件读快照、写时创建新版本；调度器据此决定激活哪些能力。
class WorldModelORM(Base):
    """世界模型表——每章一行，承载系统对该章的全部理解。"""

    __tablename__ = "world_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    chapter_id = Column(
        UUID(as_uuid=True),
        ForeignKey("chapters.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 每章只有一个世界模型
        index=True,
    )
    # 层 1：已写事实。[{text, entities:[], state_changes:[], settled_at, word_count}]
    layer1_facts = Column(JSONB, default=list)
    # 层 2：意图推断。{source:"author"|"inferred"|"none", confidence:0-1, arc:"",
    #   emotion_curve:[], setup_points:[], must_hits:[], foreshadows:[]}
    layer2_intent = Column(JSONB, default=dict)
    # 层 3：未来推测。[{possible_beats:[{event, anchors, emotion}], confidence:0-1}]
    layer3_projections = Column(JSONB, default=list)
    # 意图重算次数（调度器节流：变化触发反推时 +1，用于判断 intent 是否 stale）
    intent_version = Column(Integer, default=0)
    # 上次反推时间戳（节流用：30s 最小间隔）
    last_inference_ts = Column(Float, default=0.0)
    # 上次挂件生成用的 projection 签名（懒加载：projection 没变就不重算挂件）
    last_dock_sig = Column(Text, default="")
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    def __repr__(self):
        return f"<WorldModel chapter={self.chapter_id} v{self.intent_version}>"

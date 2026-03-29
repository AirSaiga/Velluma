"""
SQLAlchemy ORM 模型定义
使用 SQLAlchemy 2.0 Declarative Base 定义数据库表结构
"""

import uuid
from datetime import datetime
from enum import Enum
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, UniqueConstraint, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base


def generate_uuid() -> uuid.UUID:
    """生成 UUID 主键"""
    return uuid.uuid4()


class PlotLedgerStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    DROPPED = "dropped"


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
    created_at = Column(DateTime, default=datetime.utcnow)

    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")
    characters = relationship("Character", back_populates="book", cascade="all, delete-orphan")
    locations = relationship("MapLocation", back_populates="book", cascade="all, delete-orphan")
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
    tension_level = Column(Integer, default=5, nullable=False)
    pacing_style = Column(String(50), default="balanced", nullable=False)
    revision_count = Column(Integer, default=0)
    status = Column(String(50), default="draft")
    generation_run_id = Column(String(64), nullable=True)
    generation_status = Column(JSONB, default=dict)
    generation_checkpoints = Column(JSONB, default=list)
    # V3.0 资产字典：存储当前场景出现的专有名词的物理定义（如机甲体积、武器形态）
    chapter_assets_schema = Column(Text, nullable=True, default="")
    # 世界状态快照：章节发布时提取，作为下一章的初始约束
    world_snapshot = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

    book = relationship("Book", back_populates="chapters")
    entities = relationship("ChapterEntity", back_populates="chapter", cascade="all, delete-orphan")
    locations = relationship("ChapterMapLocation", back_populates="chapter", cascade="all, delete-orphan")
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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    
    chapter = relationship("Chapter", back_populates="locations")
    location = relationship("MapLocation", back_populates="chapter_locations")



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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    - pov_aperture: 叙事光圈，控制 Drafting 阶段的视角景深 (V3.5)
    - persistent_state_anchors: 持久状态锚点列表 (V3.5)
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
    # V3.5: 叙事光圈，控制 Drafting 阶段的视角景深
    pov_aperture = Column(String(50), nullable=True, default="subjective_observation")
    # V3.5: 持久状态锚点列表，用于跨 Beat 状态连贯
    persistent_state_anchors = Column(JSONB, default=list)
    # POV 角色的知觉状态（意识清醒程度与物理行动力），由 Planner 生成
    pov_perception_state = Column(Text, nullable=True, default="正常")
    anchor_pov = Column(String(120), nullable=True)
    original_actor = Column(String(120), nullable=True)
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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    created_at = Column(DateTime, default=datetime.utcnow)

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
    meta = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)

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

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""叙事主体层：Book / Chapter / StoryBeat / SceneIntent / PlotLedger（伏笔·期待账本）。"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now, PlotLedgerStatus


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
    - global_sys_prompt 冻结列（2026-09-05 退役）：原「创作笔记」，消费方
      （V3 生成链/澄清链/精修）已全部归档或掐断，历史数据保留、代码不再读写

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
    # 写作规矩按书覆盖（2026-09 白描封杀令收编批）：系统质感契约
    # （services/style/texture_contracts.py 唯一权威）的本书定制。
    # {contract_key: {body: str, updated_at: iso}}；缺键=系统默认，
    # 列缺失/NULL/{} = 全部默认（prompt 逐字节零变化）。
    texture_contracts = Column(JSONB, default=dict)
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
    # uow 依赖边：flush 跨表排序按 relationship 而非裸 FK——同 flush 新建地点+钉场景
    # 章时插入序需显式边（world.py 同款先例）；删除语义与列 ondelete=SET NULL 一致
    scene_location = relationship("WorldLocation")
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



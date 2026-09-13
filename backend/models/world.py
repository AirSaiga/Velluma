# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""世界内核层：world_* 全家（事件源/意图/呈现/地点/实体/关系/候选池/模型缓存）。

事件溯源建模：world_events 为 append-only 事实源，任意时刻的世界状态由
compute_world_state_from_events 纯函数折叠推演（前后端同构）。
"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now


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
    title = Column(String(200), default="")  # 用户自拟标题（空=显示侧回退模板标签，不参与状态推演）
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
    book = relationship("Book")
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
    book = relationship("Book")
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
    # 单分组（2026-09-03 资产抽屉分组）：组织元数据，一个实体至多归一组；
    # 不进 prompt 档案装配、不进 field_layers——纯前端抽屉分组依据。列名通用，
    # 角色/势力日后复用同列。不用 tags 承载：tags 留给多标签语义，避免烧掉。
    group_name = Column(String(100), nullable=True)
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

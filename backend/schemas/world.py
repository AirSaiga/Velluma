# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - World 设定层 schema（地图 + 时间线 + 事件溯源）
"""
World 设定层的 Pydantic schema（独立于 Canon）。

四件套（Base/Create/Update/Response）仿 schemas/canon.py。
事件溯源的派生状态（WorldState）由 computeWorldState 推演，不经持久化。

三条决策（照搬世界绘卷）落在 payload schema：
- birth/death 事件承载生死（character 不存 birth_time）
- move 事件 payload 含 path（沿弧长插值在途位置）
- territory_change 事件 payload 含完整 polygon（疆域时变）
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def _norm_group_name(v: Optional[str]) -> Optional[str]:
    """分组名归一：去首尾空白，空串按未分组（None）。"""
    if v is None:
        return None
    v = v.strip()
    return v or None


# ============================================================
# WorldEvent（事件事实源，append-only）
# ============================================================

class WorldEventBase(BaseModel):
    event_type: str = Field(..., description="birth/move/death/battle/territory_change/found/destroy/...")
    time_start: int = Field(..., description="开始时间戳（连续日计数，与历法解耦）")
    time_end: int = Field(..., description="结束时间戳（时点事件 = time_start）")
    location_id: Optional[UUID] = Field(None, description="发生地点")
    participant_ids: List[UUID] = Field(default_factory=list, description="参与角色 entity id")
    faction_ids: List[UUID] = Field(default_factory=list, description="参与势力 entity id")
    payload: Dict[str, Any] = Field(default_factory=dict, description="类型相关：move.path / territory_change.polygon / birth.parent_ids 等")
    causes: List[UUID] = Field(default_factory=list, description="因果链事件 id")
    chapter_ref: Optional[str] = Field(None, description="关联章节 id（只读，按章过滤用）")
    tags: List[str] = Field(default_factory=list)
    title: str = Field("", description="用户自拟标题（空=前端回退模板标签；纯显示，不参与状态推演）")
    note: str = Field("")


class WorldEventCreate(WorldEventBase):
    book_id: UUID
    # 幂等重建（undo/redo 恢复路径）：指定 id 使引用该事件的边/关系不悬空
    id: Optional[UUID] = None


class WorldEventUpdate(BaseModel):
    event_type: Optional[str] = None
    time_start: Optional[int] = None
    time_end: Optional[int] = None
    location_id: Optional[UUID] = None
    participant_ids: Optional[List[UUID]] = None
    faction_ids: Optional[List[UUID]] = None
    payload: Optional[Dict[str, Any]] = None
    causes: Optional[List[UUID]] = None
    chapter_ref: Optional[str] = None
    tags: Optional[List[str]] = None
    title: Optional[str] = None
    note: Optional[str] = None


class WorldEventResponse(WorldEventBase):
    id: UUID
    book_id: UUID
    sequence_num: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ============================================================
# WorldLocation（地点，带空间坐标）
# ============================================================

class WorldLocationBase(BaseModel):
    name: str = Field(...)
    kind: str = Field("point", description="point/region/route")
    parent_id: Optional[UUID] = None
    coord_x: Optional[float] = Field(None, description="内部坐标 x（CRS.Simple 浮点）")
    coord_y: Optional[float] = Field(None, description="内部坐标 y")
    geometry: Dict[str, Any] = Field(default_factory=dict, description="region: polygon 点[]；route: polyline 点[]")
    intro: str = Field("")
    tags: List[str] = Field(default_factory=list)


class WorldLocationCreate(WorldLocationBase):
    book_id: UUID
    id: Optional[UUID] = None  # 幂等重建（undo/redo 恢复路径）


class WorldLocationUpdate(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    parent_id: Optional[UUID] = None
    coord_x: Optional[float] = None
    coord_y: Optional[float] = None
    geometry: Optional[Dict[str, Any]] = None
    intro: Optional[str] = None
    tags: Optional[List[str]] = None


class WorldLocationResponse(WorldLocationBase):
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ============================================================
# WorldEntity（人物/势力/资产 固有属性）
# ============================================================

class WorldEntityBase(BaseModel):
    entity_type: str = Field(..., description="character/faction/asset")
    name: str = Field(...)
    aliases: List[str] = Field(default_factory=list, description="别名（RAG 检索 / POV 名闸门用）")
    importance: int = Field(1, ge=1, le=10, description="重要度（上下文注入优先级）")
    visibility: str = Field("public", description="public=读者已知 / private=作者已知")
    canvas_x: Optional[float] = Field(None, description="画布锚位 x（无推演位置时的摆位）")
    canvas_y: Optional[float] = Field(None, description="画布锚位 y")
    intro: str = Field("")
    tags: List[str] = Field(default_factory=list)
    group_name: Optional[str] = Field(None, max_length=100, description="单分组（资产抽屉分组依据，组织元数据不进 prompt）")
    props: Dict[str, Any] = Field(default_factory=dict, description="档案字段（appearance/speech_style 等，表驱动 schema）")
    field_layers: Dict[str, Any] = Field(
        default_factory=dict,
        description="字段级真相分层：{field_key: {level: private|partial, public_text?, reveal_chapter?}}；缺键=公开",
    )

    _norm_group = field_validator("group_name")(_norm_group_name)


class WorldEntityCreate(WorldEntityBase):
    book_id: UUID
    id: Optional[UUID] = None  # 幂等重建（undo/redo 恢复路径）


class WorldEntityUpdate(BaseModel):
    entity_type: Optional[str] = None
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    importance: Optional[int] = Field(None, ge=1, le=10)
    visibility: Optional[str] = None
    canvas_x: Optional[float] = None
    canvas_y: Optional[float] = None
    intro: Optional[str] = None
    tags: Optional[List[str]] = None
    group_name: Optional[str] = Field(None, max_length=100)  # exclude_unset 语义：显式传 null = 移出分组
    props: Optional[Dict[str, Any]] = None
    field_layers: Optional[Dict[str, Any]] = None

    _norm_group = field_validator("group_name")(_norm_group_name)


class WorldEntityResponse(WorldEntityBase):
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ============================================================
# WorldRelation（实体关系边，脑图透镜）
# ============================================================

class WorldRelationBase(BaseModel):
    source_entity_id: UUID = Field(..., description="有向边起点（source 对 target 的认知）")
    target_entity_id: UUID = Field(..., description="有向边终点")
    relation_type: str = Field("custom", description="ally/enemy/kin/master/follower/lover/custom...")
    label: str = Field("", description="显示名（如：义兄弟 / 杀父仇人）")
    affinity: Optional[int] = Field(None, ge=-100, le=100, description="态度值 -100..100")
    note: str = Field("")
    static: bool = Field(True, description="True=一直成立；False=event_ref 事件回放后激活")
    event_ref: Optional[UUID] = Field(None, description="锚事件 id（static=False 时生效）")


class WorldRelationCreate(WorldRelationBase):
    book_id: UUID
    id: Optional[UUID] = None  # 幂等重建（undo/redo 恢复路径）


class WorldRelationUpdate(BaseModel):
    relation_type: Optional[str] = None
    label: Optional[str] = None
    affinity: Optional[int] = Field(None, ge=-100, le=100)
    note: Optional[str] = None
    static: Optional[bool] = None
    event_ref: Optional[UUID] = None


class WorldRelationResponse(WorldRelationBase):
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


# ============================================================
# WorldState（computeWorldState 派生，不持久化）
# ============================================================

class CharacterStateResponse(BaseModel):
    entity_id: str
    location_id: Optional[str] = None
    position: Optional[List[float]] = None  # [x, y] 在途插值位置
    alive: bool = True
    label: str = ""  # "驻留：X" / "在途：A→B（50%）"
    last_event_id: Optional[str] = None


class TerritoryStateResponse(BaseModel):
    faction_id: str
    polygon: List[List[float]] = Field(default_factory=list)  # [[x, y], ...]
    last_event_id: Optional[str] = None


class LocationStateResponse(BaseModel):
    location_id: str
    exists: bool = True  # found/destroy
    last_event_id: Optional[str] = None


class RelationStateResponse(BaseModel):
    """时刻 t 的关系边激活状态（static 或锚事件已回放 → active）。"""
    relation_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    label: str
    active: bool


class WorldStateResponse(BaseModel):
    """computeWorldState(events, t) 的派生状态快照（谁在哪、疆域如何、谁活着）。"""
    at_time: int
    character_states: List[CharacterStateResponse] = Field(default_factory=list)
    territory_states: List[TerritoryStateResponse] = Field(default_factory=list)
    location_states: List[LocationStateResponse] = Field(default_factory=list)
    relation_states: List[RelationStateResponse] = Field(default_factory=list)


# ============================================================
# SceneSlice（写作页「此刻此地」世界切片，docs/world-writing-bridge.md W1）
# ============================================================

class ScenePresenceItem(BaseModel):
    """在场角色（t 时刻有事态记录；位置/生死由事件推演）。"""
    entity_id: str
    name: str
    alive: bool = True
    location_name: str = ""
    # 结构化位置 id（2026-09-16 取景器双层分立）：空=位置未知——前端按当前
    # 取景/本章据点的子树闭包过滤同室名单与章范围名册（场外角色收敛世界页）
    location_id: str = ""
    label: str = ""  # "在途（进度 40%）" / "驻留" / "出生" / "已死亡"
    # 词法兜底标记（2026-09-02）：lexical=位置从事件 note 推断（结构化链接缺失）
    # ——前端渲染「据正文推断」badge，兼作补录事件参与者的建议通道
    presence_source: Optional[str] = None
    importance: int = 1
    visibility: str = "public"


class SceneChapterActorItem(BaseModel):
    """全章正文活跃名册条目（2026-09-17 方向 B）：正文有戏份的角色——含零事件者。

    与 presence（事件推演轨）并集去重后渲染「本章出场名册」：registered=已
    建档（via=对白/交互/动作/在场），guest=未建档高频人名（明姐类，jieba
    双核验）——前端以「正文活跃/未建档」微标区分。
    """
    name: str
    via: str = ""            # 判定证据：对白/交互/动作/在场/未建档
    entity_id: str = ""      # guest 无档案故空
    source: str = "registered"  # registered | guest


class SceneBlockResponse(BaseModel):
    """脚下（场景地点）。controlling_faction 仅在地点有坐标且对疆域 polygon 唯一命中时有值。"""
    location_id: str
    name: str
    path: str = ""  # 全路径「父·子」（内部构造脚下无歧义显示；顶层=裸名，docs/reports/location-interior.md）
    controlling_faction: Optional[str] = None
    pinned: bool = False  # True=作者显式钉定（chapters.scene_location_id）


class SceneForeshadowItem(BaseModel):
    """头顶的线·开放伏笔（在场实体名/别名命中提权排前）。"""
    ledger_key: str
    content: str
    chapters_open: Optional[int] = None  # 当前章号 − created_at_chapter（章号缺失则空）


class SceneExpectationItem(BaseModel):
    """头顶的线·活跃期待（books.reader_mirror，与生成侧 reader_expectations 同源）。"""
    type: str = ""
    description: str = ""
    tension: int = 5


class SceneEncounterItem(BaseModel):
    """同地相遇提示（W5-lite）：t 时刻同地点的存活角色组（戏剧机会线索）。"""
    names: List[str] = Field(default_factory=list)
    location_name: str = ""


class WorldVersionResponse(BaseModel):
    """世界数据版本：events 计数（兜底删除）+ 四表聚合 max(updated_at)。"""
    events: int = 0
    updated_at: Optional[datetime] = None


class SceneSliceResponse(BaseModel):
    """章节时刻的世界切片：写作页切片条唯一数据源，与生成桥接共用时间解析与推演。"""
    t: int = 0
    t_source: str = "zero"  # chapter_anchor | prev_anchor | max_event | zero
    # A4 叙事时间来源可见（docs/reports/foundation-hardening.md §2.2）：max_event 时附
    # time_start 最大事件摘要（note 优先、event_type 兜底，截 30 字；缺席省略）
    t_source_note: Optional[str] = None
    # A4：prev_anchor 时来源章号（「来自第N章锚」；缺席省略）
    t_source_chapter: Optional[int] = None
    presence: List[ScenePresenceItem] = Field(default_factory=list)
    scene: Optional[SceneBlockResponse] = None
    # 全章正文活跃名册（2026-09-17 方向 B）：与 presence 并集渲染出场名册
    chapter_actors: List[SceneChapterActorItem] = Field(default_factory=list)
    encounters: List[SceneEncounterItem] = Field(default_factory=list)
    foreshadows: List[SceneForeshadowItem] = Field(default_factory=list)
    expectations: List[SceneExpectationItem] = Field(default_factory=list)
    version: WorldVersionResponse = Field(default_factory=WorldVersionResponse)
    world_empty: bool = False  # 世界页无实体 → 前端显示迁移引导
    # D4-2 比例尺距离（docs/reports/map-scale-spatial.md §5）：未标定整段缺席（零变化契约）
    proximities: List[Dict] = Field(default_factory=list)  # [{a, b, text}] 异地近邻对
    nearest_anchor: Optional[Dict] = None                 # {name, text} 脚下最近锚点
    # D4-3 空间常识块（settings_bundle 消费；未标定缺席）
    spatial_brief: Optional[str] = None


# ============================================================
# ContextCard（情境浮卡，docs/world-writing-bridge.md W2 查询闭环）
# ============================================================

class ContextChronicleItem(BaseModel):
    """编年史条目：涉其/此地的事件 ≤ 叙事时刻，倒序取近（防剧透，与 RAG A 层同规则）。"""
    event_type: str
    title: str = ""
    note: str = ""
    time_start: int = 0  # 连续日计数，前端按历法格式化


class ContextCardResponse(BaseModel):
    """情境浮卡（选中文本/点击提及 → 三秒查明底细）。

    kind=entity：alive/location_name/label/chronicle（角色有事态才有状态块）；
    kind=location：controlling_faction/recent_events。t 随卡返回（深链游标用）。
    """
    kind: str  # entity | location
    id: str
    entity_type: str = "character"  # character/faction/asset/location
    name: str
    intro: str = ""
    t: int = 0
    alive: Optional[bool] = None
    location_name: str = ""
    label: str = ""
    chronicle: List[ContextChronicleItem] = Field(default_factory=list)
    controlling_faction: Optional[str] = None
    recent_events: List[ContextChronicleItem] = Field(default_factory=list)


# ============================================================
# 速记解析 / 候选事件（W3 速记入账 + W4 候选回流）
# ============================================================

class EventDraft(BaseModel):
    """事件草稿（parse-event 输出 / 候选池 draft 的形状）。只产草稿，作者确认才入账。"""
    event_type: str = "custom"
    summary: str = ""
    time_start: int = 0
    time_end: int = 0
    participant_ids: List[str] = Field(default_factory=list)
    participant_names: List[str] = Field(default_factory=list)
    unresolved_names: List[str] = Field(default_factory=list)
    location_id: Optional[str] = None
    location_name: str = ""
    note: str = ""


class NewEntityDraft(BaseModel):
    """速记里名单外的新实体草拟（关联式录入 2026-09-05）。

    只报三件事：名字（速记原词）+ 类型猜测 + 依据（速记原文逐字子串）。
    绝不草拟属性——LLM 此刻可见的信息只有一句话，任何属性都是编造。
    evidence 由后端硬闸校验（归一化后必须是原文子串且包含 name），不过闸整条丢弃。
    """
    name: str
    kind: str = "character"  # character | faction | asset（白名单外 clamp 为 character）
    evidence: str = ""


class NewLocationDraft(BaseModel):
    """速记里名单外的新地点草拟（同上三件事纪律）。"""
    name: str
    evidence: str = ""


class ParseEventRequest(BaseModel):
    chapter_id: Optional[UUID] = Field(None, description="缺省（世界页无章节上下文）时用书级此刻")
    text: str = Field(..., min_length=1, max_length=500, description="作者一句话速记")


class ParseEventResponse(BaseModel):
    """解析失败 → 空草稿 + confidence=none（前端降级为空白轻表单）。

    new_entities/new_locations：速记里名单外的名字草拟（勾选后随事件一并入账）。
    加在 response 而非 EventDraft——draft 形状被候选池复用，保持稳定。
    """
    draft: EventDraft = Field(default_factory=EventDraft)
    confidence: str = "none"  # high | low | none
    new_entities: List[NewEntityDraft] = Field(default_factory=list)
    new_locations: List[NewLocationDraft] = Field(default_factory=list)


class WorldEventCandidateResponse(BaseModel):
    """候选事件（pending 池条目；draft 形状同 EventDraft）。"""
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    draft: Dict[str, Any] = Field(default_factory=dict)
    source: str = "settle"
    status: str = "pending"
    created_at: datetime
    # 归属章号（路由侧联表补；无时间锚时前端显示「第 N 章」替代默认日期）
    chapter_number: Optional[int] = None

    class Config:
        from_attributes = True


class AcceptCandidateResponse(BaseModel):
    """✓ 转正：真事件（已分配回放序号，进入推演）+ 候选留痕。
    duplicated=True：命中重复转正闸——未建事件，候选已标 rejected 留痕。"""
    event: Optional[WorldEventResponse] = None
    candidate_id: UUID
    canon_node_id: Optional[UUID] = None
    duplicated: bool = False


# ============================================================
# WorldMapLayer（底图·图片拼贴层）
# ============================================================

class WorldMapLayerBase(BaseModel):
    image_url: str = Field(..., description="图片 URL（/world-images/{book_id}/{uuid}{ext}）")
    x: float = Field(..., description="中心 x（CRS.Simple 内部坐标）")
    y: float = Field(..., description="中心 y")
    w: float = Field(..., description="宽（内部坐标单位）")
    h: float = Field(..., description="高")
    z_index: int = Field(0, description="层序（小者在下）")
    opacity: float = Field(1.0)


class WorldMapLayerCreate(WorldMapLayerBase):
    book_id: UUID
    id: Optional[UUID] = None  # 幂等重建（2026-09-04 审计修复：undo/redo 恢复路径，同地点/实体先例）


class WorldMapLayerUpdate(BaseModel):
    x: Optional[float] = None
    y: Optional[float] = None
    w: Optional[float] = None
    h: Optional[float] = None
    z_index: Optional[int] = None
    opacity: Optional[float] = None


class WorldMapLayerResponse(WorldMapLayerBase):
    id: UUID
    book_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# WorldMapStroke（底图·手绘笔迹，矢量）
# ============================================================

class WorldMapStrokeCreate(BaseModel):
    book_id: UUID
    color: str = Field("#475569")
    width: float = Field(3.0)
    points: List[List[float]] = Field(..., description="[[x, y], ...] 内部坐标")
    id: Optional[UUID] = None  # 幂等重建（2026-09-04 审计修复：undo/redo 恢复路径，同地点/实体先例）


class WorldMapStrokeResponse(BaseModel):
    id: UUID
    book_id: UUID
    color: str
    width: float
    points: List[List[float]]
    created_at: datetime

    class Config:
        from_attributes = True

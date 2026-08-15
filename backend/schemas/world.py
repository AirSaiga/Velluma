# Velluma - World 设定层 schema（地图 + 时间线 + 事件溯源）
# AGPL-3.0
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

from pydantic import BaseModel, Field


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
    intro: str = Field("")
    tags: List[str] = Field(default_factory=list)
    props: Dict[str, Any] = Field(default_factory=dict, description="档案字段（appearance/speech_style 等，表驱动 schema）")


class WorldEntityCreate(WorldEntityBase):
    book_id: UUID
    id: Optional[UUID] = None  # 幂等重建（undo/redo 恢复路径）


class WorldEntityUpdate(BaseModel):
    entity_type: Optional[str] = None
    name: Optional[str] = None
    aliases: Optional[List[str]] = None
    importance: Optional[int] = Field(None, ge=1, le=10)
    visibility: Optional[str] = None
    intro: Optional[str] = None
    tags: Optional[List[str]] = None
    props: Optional[Dict[str, Any]] = None


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


class WorldMapStrokeResponse(BaseModel):
    id: UUID
    book_id: UUID
    color: str
    width: float
    points: List[List[float]]
    created_at: datetime

    class Config:
        from_attributes = True

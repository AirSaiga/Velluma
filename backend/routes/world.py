# Velluma - World 设定层路由（地图 + 时间线 + 事件溯源）
# AGPL-3.0
"""
World 设定层 REST API（独立于 Canon 路由，通过 book_id 隔离）。

端点前缀 /api/books/{book_id}/world/...：
- events：事件 CRUD（append-only 事实源）
- locations：地点 CRUD（带空间坐标）
- entities：人物/势力/资产 CRUD（固有属性）
- state：computeWorldState 推演（时刻 t 的世界状态）
"""
from __future__ import annotations

import os
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import WORLD_IMAGES_DIR
from backend.core.dependencies import get_db
from backend.repositories.world_repository import WorldRepository
from backend.schemas.world import (
    WorldEntityCreate,
    WorldEntityResponse,
    WorldEntityUpdate,
    WorldEventCreate,
    WorldEventResponse,
    WorldEventUpdate,
    WorldLocationCreate,
    WorldLocationResponse,
    WorldLocationUpdate,
    WorldMapLayerCreate,
    WorldMapLayerResponse,
    WorldMapLayerUpdate,
    WorldMapStrokeCreate,
    WorldMapStrokeResponse,
    WorldRelationCreate,
    WorldRelationResponse,
    WorldRelationUpdate,
    WorldStateResponse,
)

router = APIRouter(prefix="/api/books", tags=["world-v1"])


def _normalize_event_fields(fields: dict) -> dict:
    """payload 里 UUID list → str list（JSONB 存 str），location_id → str。"""
    for k in ("participant_ids", "faction_ids", "causes"):
        if fields.get(k):
            fields[k] = [str(x) for x in fields[k]]
    if fields.get("location_id"):
        fields["location_id"] = str(fields["location_id"])
    return fields


# ============================================================
# Events
# ============================================================

@router.get("/{book_id}/world/events", response_model=List[WorldEventResponse])
async def list_events(book_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    return await repo.events.list_all_by_book(str(book_id))


@router.post("/{book_id}/world/events", response_model=WorldEventResponse)
async def create_event(book_id: UUID, payload: WorldEventCreate, db: AsyncSession = Depends(get_db)):
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不匹配")
    repo = WorldRepository(db)
    fields = payload.model_dump(exclude={"book_id"}, by_alias=False)
    ev = await repo.events.create(str(book_id), **_normalize_event_fields(fields))
    await db.commit()
    return ev


@router.put("/{book_id}/world/events/{event_id}", response_model=WorldEventResponse)
async def update_event(book_id: UUID, event_id: UUID, payload: WorldEventUpdate, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    fields = _normalize_event_fields(payload.model_dump(exclude_unset=True, by_alias=False))
    ev = await repo.events.update(str(event_id), **fields)
    if ev is None:
        raise HTTPException(404, "事件不存在")
    await db.commit()
    return ev


@router.delete("/{book_id}/world/events/{event_id}")
async def delete_event(book_id: UUID, event_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    if not await repo.events.delete(str(event_id)):
        raise HTTPException(404, "事件不存在")
    await db.commit()
    return {"deleted": True}


# ============================================================
# Locations
# ============================================================

@router.get("/{book_id}/world/locations", response_model=List[WorldLocationResponse])
async def list_locations(book_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    return await repo.locations.list_by_book(str(book_id))


@router.post("/{book_id}/world/locations", response_model=WorldLocationResponse)
async def create_location(book_id: UUID, payload: WorldLocationCreate, db: AsyncSession = Depends(get_db)):
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不匹配")
    repo = WorldRepository(db)
    fields = payload.model_dump(exclude={"book_id"}, by_alias=False)
    if fields.get("parent_id"):
        fields["parent_id"] = str(fields["parent_id"])
    loc = await repo.locations.create(book_id=str(book_id), **fields)
    await db.commit()
    return loc


@router.put("/{book_id}/world/locations/{location_id}", response_model=WorldLocationResponse)
async def update_location(book_id: UUID, location_id: UUID, payload: WorldLocationUpdate, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    fields = payload.model_dump(exclude_unset=True, by_alias=False)
    if fields.get("parent_id"):
        fields["parent_id"] = str(fields["parent_id"])
    loc = await repo.locations.update(str(location_id), **fields)
    if loc is None:
        raise HTTPException(404, "地点不存在")
    await db.commit()
    return loc


@router.delete("/{book_id}/world/locations/{location_id}")
async def delete_location(book_id: UUID, location_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    if not await repo.locations.delete(str(location_id)):
        raise HTTPException(404, "地点不存在")
    await db.commit()
    return {"deleted": True}


# ============================================================
# Entities（人物/势力/资产）
# ============================================================

@router.get("/{book_id}/world/entities", response_model=List[WorldEntityResponse])
async def list_entities(
    book_id: UUID,
    entity_type: Optional[str] = Query(None, description="character/faction/asset"),
    db: AsyncSession = Depends(get_db),
):
    repo = WorldRepository(db)
    return await repo.entities.list_by_book(str(book_id), entity_type=entity_type)


@router.post("/{book_id}/world/entities", response_model=WorldEntityResponse)
async def create_entity(book_id: UUID, payload: WorldEntityCreate, db: AsyncSession = Depends(get_db)):
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不匹配")
    repo = WorldRepository(db)
    ent = await repo.entities.create(
        book_id=str(book_id), **payload.model_dump(exclude={"book_id"}, by_alias=False)
    )
    await db.commit()
    return ent


@router.put("/{book_id}/world/entities/{entity_id}", response_model=WorldEntityResponse)
async def update_entity(book_id: UUID, entity_id: UUID, payload: WorldEntityUpdate, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    ent = await repo.entities.update(str(entity_id), **payload.model_dump(exclude_unset=True, by_alias=False))
    if ent is None:
        raise HTTPException(404, "实体不存在")
    await db.commit()
    return ent


@router.delete("/{book_id}/world/entities/{entity_id}")
async def delete_entity(book_id: UUID, entity_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    if not await repo.entities.delete(str(entity_id)):
        raise HTTPException(404, "实体不存在")
    await db.commit()
    return {"deleted": True}


# ============================================================
# Relations（实体关系边，脑图透镜）
# ============================================================

@router.get("/{book_id}/world/relations", response_model=List[WorldRelationResponse])
async def list_relations(book_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    return await repo.relations.list_by_book(str(book_id))


@router.post("/{book_id}/world/relations", response_model=WorldRelationResponse)
async def create_relation(book_id: UUID, payload: WorldRelationCreate, db: AsyncSession = Depends(get_db)):
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不匹配")
    if payload.source_entity_id == payload.target_entity_id:
        raise HTTPException(422, "关系边不可自环（source == target）")
    if not payload.static and payload.event_ref is None:
        raise HTTPException(422, "事件锚定关系必须提供 event_ref（或改用 static=true）")
    repo = WorldRepository(db)
    # 实体存在性校验：给出可读错误而非 FK IntegrityError 500
    for ent_id in (payload.source_entity_id, payload.target_entity_id):
        if await repo.entities.get(str(ent_id)) is None:
            raise HTTPException(422, f"实体不存在：{ent_id}")
    fields = payload.model_dump(exclude={"book_id"}, by_alias=False)
    rel = await repo.relations.create(book_id=str(book_id), **fields)
    await db.commit()
    return rel


@router.put("/{book_id}/world/relations/{relation_id}", response_model=WorldRelationResponse)
async def update_relation(
    book_id: UUID, relation_id: UUID, payload: WorldRelationUpdate, db: AsyncSession = Depends(get_db)
):
    repo = WorldRepository(db)
    fields = payload.model_dump(exclude_unset=True, by_alias=False)
    if fields.get("static") is False:
        # 事件锚定关系必须有锚：取请求值与现有值合并后判断
        existing = await repo.relations.get(str(relation_id))
        if existing is None:
            raise HTTPException(404, "关系不存在")
        effective_ref = fields.get("event_ref", existing.event_ref)
        if effective_ref is None:
            raise HTTPException(422, "事件锚定关系必须提供 event_ref（或改用 static=true）")
    rel = await repo.relations.update(str(relation_id), **fields)
    if rel is None:
        raise HTTPException(404, "关系不存在")
    await db.commit()
    return rel


@router.delete("/{book_id}/world/relations/{relation_id}")
async def delete_relation(book_id: UUID, relation_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    if not await repo.relations.delete(str(relation_id)):
        raise HTTPException(404, "关系不存在")
    await db.commit()
    return {"deleted": True}


# ============================================================
# World State（推演：computeWorldState）
# ============================================================

@router.get("/{book_id}/world/state", response_model=WorldStateResponse)
async def get_world_state(
    book_id: UUID,
    t: int = Query(0, description="时间戳（连续日计数，与历法解耦）"),
    db: AsyncSession = Depends(get_db),
):
    """推演时刻 t 的世界状态（谁在哪、疆域如何、谁活着）——事件溯源的核心红利。"""
    repo = WorldRepository(db)
    return await repo.compute_world_state(str(book_id), t)


@router.get("/{book_id}/world/state-for-chapter/{chapter_id}", response_model=WorldStateResponse)
async def get_world_state_for_chapter(
    book_id: UUID,
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """按章节解析叙事时间（本章锚 → 前序最近锚 → 事件最大时刻 → 0）后推演世界状态。

    供编辑器「本章在场」只读展示与生成桥接共用同一时间解析（world_bridge）。
    """
    from backend.models import Chapter
    from backend.services.context.world_bridge import resolve_narrative_time

    chapter = await db.get(Chapter, str(chapter_id))
    if chapter is None or str(chapter.book_id) != str(book_id):
        raise HTTPException(404, "章节不存在")
    t = await resolve_narrative_time(db, chapter)
    repo = WorldRepository(db)
    return await repo.compute_world_state(str(book_id), t)


@router.post("/{book_id}/world/migrate-legacy")
async def migrate_legacy_settings(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """设定中心旧表一次性迁入世界页（幂等，可重复执行；详见 repository 注释）。

    副作用：只写世界页表（world_entities/relations/locations、plot_ledgers 补锚），
    不动 characters/assets/character_relationships/map_locations 旧表。
    """
    repo = WorldRepository(db)
    report = await repo.migrate_legacy_settings(str(book_id))
    await db.commit()
    return report


# ============================================================
# 底图：图片拼贴层
# ============================================================

@router.get("/{book_id}/world/map/layers", response_model=List[WorldMapLayerResponse])
async def list_map_layers(book_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    return await repo.map_layers.list_by_book(str(book_id))


@router.post("/{book_id}/world/map/layers", response_model=WorldMapLayerResponse)
async def create_map_layer(book_id: UUID, payload: WorldMapLayerCreate, db: AsyncSession = Depends(get_db)):
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不匹配")
    repo = WorldRepository(db)
    fields = payload.model_dump(exclude={"book_id"}, by_alias=False)
    z = fields.get("z_index")
    if z is None or z == 0:
        fields["z_index"] = await repo.map_layers.next_z_index(str(book_id))
    layer = await repo.map_layers.create(book_id=str(book_id), **fields)
    await db.commit()
    return layer


@router.put("/{book_id}/world/map/layers/{layer_id}", response_model=WorldMapLayerResponse)
async def update_map_layer(
    book_id: UUID, layer_id: UUID, payload: WorldMapLayerUpdate, db: AsyncSession = Depends(get_db)
):
    repo = WorldRepository(db)
    layer = await repo.map_layers.update(str(layer_id), **payload.model_dump(exclude_unset=True))
    if layer is None:
        raise HTTPException(404, "图层不存在")
    await db.commit()
    return layer


@router.delete("/{book_id}/world/map/layers/{layer_id}")
async def delete_map_layer(book_id: UUID, layer_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    if not await repo.map_layers.delete(str(layer_id)):
        raise HTTPException(404, "图层不存在")
    await db.commit()
    return {"deleted": True}


# ============================================================
# 底图：手绘笔迹
# ============================================================

@router.get("/{book_id}/world/map/strokes", response_model=List[WorldMapStrokeResponse])
async def list_map_strokes(book_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    return await repo.map_strokes.list_by_book(str(book_id))


@router.post("/{book_id}/world/map/strokes", response_model=WorldMapStrokeResponse)
async def create_map_stroke(book_id: UUID, payload: WorldMapStrokeCreate, db: AsyncSession = Depends(get_db)):
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不匹配")
    if not payload.points or len(payload.points) < 2:
        raise HTTPException(422, "笔迹至少需要 2 个点")
    repo = WorldRepository(db)
    stroke = await repo.map_strokes.create(
        book_id=str(book_id),
        color=payload.color,
        width=payload.width,
        points=payload.points,
    )
    await db.commit()
    return stroke


@router.delete("/{book_id}/world/map/strokes/{stroke_id}")
async def delete_map_stroke(book_id: UUID, stroke_id: UUID, db: AsyncSession = Depends(get_db)):
    repo = WorldRepository(db)
    if not await repo.map_strokes.delete(str(stroke_id)):
        raise HTTPException(404, "笔迹不存在")
    await db.commit()
    return {"deleted": True}


# ============================================================
# 底图：图片上传（multipart → data/world_images/{book_id}/，返回静态 URL）
# ============================================================

_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@router.post("/{book_id}/world/map/upload")
async def upload_map_image(book_id: UUID, file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    if ext not in _ALLOWED_IMAGE_EXTS:
        raise HTTPException(422, f"不支持的图片格式 {ext}（允许：{'/'.join(sorted(_ALLOWED_IMAGE_EXTS))}）")
    book_dir = os.path.join(WORLD_IMAGES_DIR, str(book_id))
    os.makedirs(book_dir, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    path = os.path.join(book_dir, filename)
    content = await file.read()
    if len(content) > 30 * 1024 * 1024:
        raise HTTPException(422, "图片过大（上限 30MB）")
    with open(path, "wb") as f:
        f.write(content)
    return {"url": f"/world-images/{book_id}/{filename}"}

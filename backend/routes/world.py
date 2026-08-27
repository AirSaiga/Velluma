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
from typing import Any, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import WORLD_IMAGES_DIR
from backend.core.dependencies import get_db
from backend.repositories.world_repository import WorldRepository
from backend.schemas.world import (
    AcceptCandidateResponse,
    ContextCardResponse,
    ParseEventRequest,
    ParseEventResponse,
    SceneSliceResponse,
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
    WorldEventCandidateResponse,
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
    # 幂等闸（同实体，2026-08-26 实测事故）：同名地点已存在则返回既有；
    # 显式 id 的 undo/redo 重建路径豁免
    if not payload.id:
        want = " ".join((payload.name or "").split())
        if want:
            for loc in await repo.locations.list_by_book(str(book_id)):
                if " ".join((loc.name or "").split()) == want:
                    return loc
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
    # C2：地点删除 → 挂接的信息面 overlay 同步清理（应用层级联，防悬空 ref）
    from sqlalchemy import delete as sa_delete
    from backend.models import CanonNode as _CanonNode
    await db.execute(sa_delete(_CanonNode).where(_CanonNode.ref_id == location_id, _CanonNode.ref_type == "location"))
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
    # 幂等闸（2026-08-26 实测事故：通读确认无防连点，14 连击建出 14 份同名实体）——
    # 同名同类（归一化空白后）已存在则返回既有，不再新建；显式 id 的
    # undo/redo 幂等重建路径豁免（它带的是同一个 id，语义就是恢复原物）
    if not payload.id:
        want = " ".join((payload.name or "").split())
        if want:
            for e in await repo.entities.list_by_book(str(book_id), payload.entity_type):
                if " ".join((e.name or "").split()) == want:
                    return e
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
    # C2：实体删除 → 挂接的信息面 overlay 同步清理（应用层级联，防悬空 ref）
    from sqlalchemy import delete as sa_delete
    from backend.models import CanonNode as _CanonNode
    await db.execute(sa_delete(_CanonNode).where(_CanonNode.ref_id == entity_id, _CanonNode.ref_type == "entity"))
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
    t = (await resolve_narrative_time(db, chapter)).t
    repo = WorldRepository(db)
    return await repo.compute_world_state(str(book_id), t)


@router.get("/{book_id}/world/scene-slice", response_model=SceneSliceResponse)
async def get_scene_slice(
    book_id: UUID,
    chapter_id: UUID = Query(..., description="章节 id（切片时刻按叙事锚四级降级解析）"),
    db: AsyncSession = Depends(get_db),
):
    """章节时刻的世界切片：在场 / 脚下 / 头顶的线（开放伏笔 + 活跃期待）+ 数据版本。

    写作页「此刻此地」切片条的唯一数据源（docs/world-writing-bridge.md §4.1）；
    与生成桥接共用 resolve_narrative_time + compute_world_state——作者所见 = AI 所见。
    """
    from backend.models import Chapter
    from backend.services.world.scene_slice import build_scene_slice

    chapter = await db.get(Chapter, str(chapter_id))
    if chapter is None or str(chapter.book_id) != str(book_id):
        raise HTTPException(404, "章节不存在")
    return await build_scene_slice(db, str(book_id), chapter)


@router.get("/{book_id}/world/context-card", response_model=ContextCardResponse)
async def get_context_card(
    book_id: UUID,
    chapter_id: UUID = Query(..., description="章节 id（编年史/状态按叙事时刻截断防剧透）"),
    entity_id: Optional[UUID] = Query(None, description="世界实体 id（提及点击直取）"),
    location_id: Optional[UUID] = Query(None, description="地点 id"),
    name: Optional[str] = Query(None, description="名字/别名（选中文本解析；实体优先，其次地点）"),
    db: AsyncSession = Depends(get_db),
):
    """情境浮卡（W2 查询闭环）：选中人名/地名或点击 @/# 提及 → 三秒查明底细。

    解析不到（选中的不是已知实体/地点）返回 404，前端浮卡静默缺席。
    """
    from backend.models import Chapter
    from backend.services.world.scene_slice import build_context_card

    chapter = await db.get(Chapter, str(chapter_id))
    if chapter is None or str(chapter.book_id) != str(book_id):
        raise HTTPException(404, "章节不存在")
    card = await build_context_card(
        db,
        str(book_id),
        chapter,
        entity_id=str(entity_id) if entity_id else None,
        location_id=str(location_id) if location_id else None,
        name=name,
    )
    if card is None:
        raise HTTPException(404, "未在世界页找到对应实体/地点")
    return card


# ============================================================
# 速记解析（W3 一句话记历史）+ 候选事件（W4 写作→世界回流）
# ============================================================

@router.post("/{book_id}/world/parse-event", response_model=ParseEventResponse)
async def parse_event(
    book_id: UUID,
    payload: ParseEventRequest,
    db: AsyncSession = Depends(get_db),
):
    """一句话速记 → 事件草稿（预填轻表单，作者过目确认）。

    契约红线：只产草稿，绝不写库；解析失败返回空草稿 + confidence=none。
    """
    from backend.models import Chapter
    from backend.services.world.event_parser import parse_event_text

    chapter = await db.get(Chapter, str(payload.chapter_id))
    if chapter is None or str(chapter.book_id) != str(book_id):
        raise HTTPException(404, "章节不存在")
    return await parse_event_text(db, str(book_id), chapter, payload.text)


def _event_fields_from_draft(draft: dict) -> dict:
    """候选 draft → world_events 创建字段（payload 按类型补齐，保证推演回放正确）。"""
    etype = draft.get("event_type") or "custom"
    participant_ids = [str(p) for p in (draft.get("participant_ids") or [])]
    location_id = draft.get("location_id") or None
    note = str(draft.get("note") or draft.get("summary") or "")
    payload: dict = {}
    if etype == "move":
        payload = {"character_ids": participant_ids}
        if location_id:
            payload["to_location_id"] = str(location_id)
    elif etype in ("birth", "death") and participant_ids:
        payload = {"character_id": participant_ids[0]}
        if etype == "birth" and location_id:
            payload["location_id"] = str(location_id)
    t0 = int(draft.get("time_start") or 0)
    return {
        "event_type": etype,
        "time_start": t0,
        "time_end": int(draft.get("time_end") or t0),
        "location_id": location_id,
        "participant_ids": participant_ids,
        "payload": payload,
        "note": note,
    }


@router.get("/{book_id}/world/candidates", response_model=List[WorldEventCandidateResponse])
async def list_candidates(
    book_id: UUID,
    chapter_id: Optional[UUID] = Query(None, description="缺省=全书（世界页待确认分区）"),
    status: str = Query("pending", description="pending | accepted | rejected"),
    db: AsyncSession = Depends(get_db),
):
    """候选事件列表（写作页收件箱只管本章；世界页待确认分区看全书）。"""
    repo = WorldRepository(db)
    rows = await repo.candidates.list_by_book(
        str(book_id), status=status, chapter_id=str(chapter_id) if chapter_id else None
    )
    # 联表补归属章号（2026-08-26 实测痛点：无叙事锚的书所有候选时间都是默认
    # 「第1年1月1日」——前端改显示「第 N 章」，章节序是诚实的已有信息）
    from sqlalchemy import select as sa_select

    from backend.models import Chapter as _Chapter

    ch_ids = [c.chapter_id for c in rows if c.chapter_id]
    num_map = {}
    if ch_ids:
        num_map = {
            str(cid): num
            for cid, num in (await db.execute(
                sa_select(_Chapter.id, _Chapter.chapter_number).where(_Chapter.id.in_(ch_ids))
            )).all()
        }
    out = []
    for c in rows:
        resp = WorldEventCandidateResponse.model_validate(c)
        resp.chapter_number = num_map.get(str(c.chapter_id)) if c.chapter_id else None
        out.append(resp)
    return out


@router.post("/{book_id}/world/candidates/{candidate_id}/accept")
async def accept_candidate(
    book_id: UUID, candidate_id: UUID, db: AsyncSession = Depends(get_db)
):
    """✓ 转正。分流（C3）：event_scout/settle 候选 → 创建真事件（进入推演）；
    canon_extract 候选 → 创建 canon 节点（tentative，不进推演）。
    候选 status→accepted。"""
    repo = WorldRepository(db)
    cand = await repo.candidates.get(str(candidate_id))
    if cand is None or str(cand.book_id) != str(book_id):
        raise HTTPException(404, "候选不存在")
    if cand.status != "pending":
        raise HTTPException(409, f"候选已处理（{cand.status}）")

    if cand.source == "canon_extract":
        from backend.models import CanonNode as _CanonNode

        d = cand.draft or {}
        node = _CanonNode(
            book_id=cand.book_id,
            type=str(d.get("type") or "event"),
            label=str(d.get("label") or "未命名真相")[:200],
            canon_text=str(d.get("canon_text") or ""),
            public_text=str(d.get("public_text") or ""),
            visibility="private",
            source="auto_extracted",
            confidence="tentative",
        )
        db.add(node)
        await repo.candidates.set_status(str(candidate_id), "accepted")
        await db.commit()
        return {"candidate_id": cand.id, "event": None, "canon_node_id": str(node.id)}

    # 重复转正闸（2026-08-26 全书通读实测）：同一事件换措辞的候选可并存于
    # pending 池（跨章抽取/历史存量），全部采纳会把账本写重。转正前对全书
    # 账本近期事件做归一化子串判重（与 event_scout 同一把尺子，勿平行实现）；
    # 命中则不建事件——候选标 rejected + draft.auto_reject="duplicate" 留痕
    # （可 reopen 翻案；quiet_learning 不计系统跳过的假拒绝，防静音学习失真）。
    d = cand.draft or {}
    summary_for_check = str(d.get("summary") or d.get("note") or "")
    if summary_for_check and cand.source != "canon_extract":
        from sqlalchemy import select as sa_select

        from backend.models import WorldEvent as _WorldEvent
        from backend.services.world.event_scout import is_ledger_duplicate

        recent_notes = [
            str(n or "")
            for n in (await db.execute(
                sa_select(_WorldEvent.note)
                .where(_WorldEvent.book_id == str(book_id))
                .order_by(_WorldEvent.sequence_num.desc())
                .limit(200)
            )).scalars().all()
        ]
        if is_ledger_duplicate(summary_for_check, recent_notes):
            cand.draft = {**d, "auto_reject": "duplicate"}
            await repo.candidates.set_status(str(candidate_id), "rejected")
            await db.commit()
            return {"candidate_id": cand.id, "event": None, "duplicated": True}

    ev = await repo.events.create(str(book_id), **_event_fields_from_draft(cand.draft or {}))
    await repo.candidates.set_status(str(candidate_id), "accepted")
    await db.commit()
    return AcceptCandidateResponse(event=ev, candidate_id=cand.id)


@router.post("/{book_id}/world/candidates/{candidate_id}/reject")
async def reject_candidate(
    book_id: UUID, candidate_id: UUID, db: AsyncSession = Depends(get_db)
):
    """✗ 丢弃：status→rejected（留痕供回溯，不进任何视图）。"""
    repo = WorldRepository(db)
    cand = await repo.candidates.get(str(candidate_id))
    if cand is None or str(cand.book_id) != str(book_id):
        raise HTTPException(404, "候选不存在")
    await repo.candidates.set_status(str(candidate_id), "rejected")
    await db.commit()
    return {"status": "rejected"}


@router.post("/{book_id}/world/candidates/{candidate_id}/reopen")
async def reopen_candidate(
    book_id: UUID, candidate_id: UUID, db: AsyncSession = Depends(get_db)
):
    """撤销入账路径：status→pending（配合删除已建事件使用）。"""
    repo = WorldRepository(db)
    cand = await repo.candidates.get(str(candidate_id))
    if cand is None or str(cand.book_id) != str(book_id):
        raise HTTPException(404, "候选不存在")
    await repo.candidates.set_status(str(candidate_id), "pending")
    await db.commit()
    return {"status": "pending"}


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
# C2：canon 信息面挂接迁移（docs/canon-world-fusion.md §4.4）
# ============================================================

class CanonMigrateDecision(BaseModel):
    node_id: UUID
    action: str = Field("auto", description="auto|link|to_ledger|create_ledger|skip")
    target_id: Optional[UUID] = None


class CanonMigrateRequest(BaseModel):
    confirm: bool = Field(False, description="false=预览（作者逐条确认）；true=落库（幂等）")
    decisions: Optional[List[CanonMigrateDecision]] = None


_CANON_TYPE_TO_ENTITY = {"character": "character", "object": "asset"}


def _match_entity(label: str, entities) -> Optional[Any]:
    for e in entities:
        if e.name == label or label in (e.aliases or []):
            return e
    return None


def _match_location(label: str, locations) -> Optional[Any]:
    for l in locations:
        if l.name == label:
            return l
    return None


@router.post("/{book_id}/world/migrate-canon")
async def migrate_canon(book_id: UUID, request: CanonMigrateRequest, db: AsyncSession = Depends(get_db)):
    """canon 信息面挂接迁移（C2）：label 匹配世界对象 → 预览 → 作者确认落库。

    动作：
    - link：character/object/place 节点 → 挂 entity/location（label/type 改由世界推演）
    - to_ledger / create_ledger：hook 节点真相面并入 plot_ledgers（节点保留为图谱
      连接器，canon/public 文本清空退场 prompt 段，ref 指向 ledger）
    - skip：不动；已挂接节点不进预览（幂等）
    """
    from sqlalchemy import select as sa_select
    from backend.models import CanonNode, PlotLedger

    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    locations = await repo.locations.list_by_book(book_id)
    ledgers = (
        await db.execute(sa_select(PlotLedger).where(PlotLedger.book_id == book_id))
    ).scalars().all()
    ledger_by_key = {l.ledger_key: l for l in ledgers}
    nodes = (
        await db.execute(sa_select(CanonNode).where(CanonNode.book_id == book_id).order_by(CanonNode.created_at))
    ).scalars().all()

    decisions = {str(d.node_id): d for d in (request.decisions or [])}

    def _suggest(node: CanonNode):
        """默认建议：label 精确匹配名/别名 → (action, target, target_name)。"""
        if node.type in _CANON_TYPE_TO_ENTITY:
            hit = _match_entity(node.label, entities)
            if hit:
                return "link", hit.id, hit.name, "entity"
            return "skip", None, None, "entity"
        if node.type == "place":
            hit = _match_location(node.label, locations)
            if hit:
                return "link", hit.id, hit.name, "location"
            return "skip", None, None, "location"
        if node.type == "hook":
            hit = ledger_by_key.get(node.label)
            if hit:
                return "to_ledger", hit.id, hit.ledger_key, "ledger"
            return "create_ledger", None, node.label, "ledger"
        return None, None, None, None  # event 自由节点：不迁移不展示

    rows = []
    applied = {"link": 0, "to_ledger": 0, "create_ledger": 0, "skip": 0}
    for node in nodes:
        if node.ref_id is not None:
            continue  # 已挂接（幂等）
        action, target_id, target_name, ref_type = _suggest(node)
        if action is None:
            continue  # 自由叙事节点无需迁移
        dec = decisions.get(str(node.id))
        if dec:
            action = dec.action if dec.action != "auto" else action
            if dec.target_id:
                target_id = dec.target_id

        if not request.confirm:
            rows.append({
                "node_id": str(node.id),
                "label": node.label,
                "type": node.type,
                "action": action,
                "ref_type": ref_type,
                "target_id": str(target_id) if target_id else None,
                "target_name": target_name,
            })
            continue

        # ---- 落库 ----
        if action == "skip":
            applied["skip"] += 1
            continue
        if action == "link" and target_id is not None:
            node.ref_type = ref_type
            node.ref_id = target_id
            applied["link"] += 1
        elif action in ("to_ledger", "create_ledger"):
            if action == "create_ledger":
                key = node.label
                n = 2
                while key in ledger_by_key:  # ledger_key 书内唯一
                    key = f"{node.label}-{n}"
                    n += 1
                ledger = PlotLedger(
                    book_id=book_id, ledger_key=key, content=node.label,
                    status="open",
                    canon_text=node.canon_text or "",
                    public_text=node.public_text or "",
                    reveal_plan=node.reveal_plan or "",
                )
                db.add(ledger)
                await db.flush()
                ledger_by_key[key] = ledger
            else:
                ledger = await db.get(PlotLedger, target_id)
                if ledger is None:
                    applied["skip"] += 1
                    continue
                # 合并守卫：账本已有真相面文本不覆盖（幂等重跑不回填）
                if not (ledger.canon_text or "").strip():
                    ledger.canon_text = node.canon_text or ""
                if not (ledger.public_text or "").strip():
                    ledger.public_text = node.public_text or ""
                if not (ledger.reveal_plan or "").strip():
                    ledger.reveal_plan = node.reveal_plan or ""
            # 节点保留为图谱连接器：文本已并入账本，从 prompt 段退场
            node.ref_type = "ledger"
            node.ref_id = ledger.id
            node.canon_text = ""
            node.public_text = ""
            node.reveal_plan = ""
            node.visibility = "public"
            applied[action] += 1

    if request.confirm:
        await db.commit()
        return {"confirmed": True, **applied}
    return {"confirmed": False, "rows": rows, "counts": {
        "linkable": sum(1 for r in rows if r["action"] == "link"),
        "ledger": sum(1 for r in rows if r["action"] in ("to_ledger", "create_ledger")),
        "unmatched": sum(1 for r in rows if r["action"] == "skip"),
    }}


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

# ============================================================
# 世界内核 B4：呈现关系（Depiction）与负空间（docs/world-kernel-foundation.md §3）
# ============================================================


class DepictionBackfillRequest(BaseModel):
    chapter_id: UUID


@router.get("/{book_id}/world/dramatic-capital")
async def get_dramatic_capital(
    book_id: UUID,
    chapter_id: Optional[UUID] = Query(None, description="以此章叙事时刻为 t；缺省 t=0"),
    db: AsyncSession = Depends(get_db),
):
    """负空间清单：可揭示戏剧资本（世界真相 − 读者已知 − 已排期揭示）。

    B9 认知浮现三时机之一的数据源；认知模型默认不可见的红线不破——
    本端点仅供前端显式入口（负空间清单）与 finish 报告消费。
    """
    from backend.services.world.negative_space import dramatic_capital

    t = 0
    if chapter_id:
        from backend.models import Chapter as _Chapter

        ch = await db.get(_Chapter, chapter_id)
        t = (getattr(ch, "narrative_time", None) or 0) if ch else 0
    capital = await dramatic_capital(db, book_id, t=t)
    return {"capital": capital, "count": len(capital)}


@router.post("/{book_id}/world/depictions/backfill")
async def backfill_depictions(
    book_id: UUID, payload: DepictionBackfillRequest, db: AsyncSession = Depends(get_db)
):
    """通读阶段 C（启发式首版）：从章正文回填呈现关系候选。

    纪律：只产 candidate（作者 confirm 才进读者折叠）；source=heuristic
    如实标注；幂等（同章同命题不重复提案）。匹配口径：canon 命题的
    label/public_text 出现在章正文 → 该命题在本章被「写出」（mode=shown）。
    """
    import re as _re

    from backend.models import Chapter as _Chapter, WorldDepiction
    from backend.services.rag.memory_indexing import _html_to_plain

    ch = await db.get(_Chapter, payload.chapter_id)
    if not ch or str(ch.book_id) != str(book_id):
        raise HTTPException(404, "章节不存在")
    text = _re.sub(r"\s+", "", _html_to_plain(ch.content_text or ""))
    if not text:
        return {"created": 0, "candidates": []}

    from backend.models import CanonNode

    nodes = (await db.execute(
        select(CanonNode).where(CanonNode.book_id == book_id)
    )).scalars().all()
    existing = {
        (str(d.subject_id))
        for d in (await db.execute(
            select(WorldDepiction).where(
                WorldDepiction.book_id == book_id,
                WorldDepiction.chapter_id == payload.chapter_id,
            )
        )).scalars().all()
    }
    created = []
    for node in nodes:
        nid = str(node.id)
        if nid in existing:
            continue
        probes = [p for p in (node.label, (node.public_text or "")[:40]) if p and len(p) >= 3]
        if any(p in text for p in probes):
            row = WorldDepiction(
                book_id=book_id, subject_type="proposition", subject_id=nid,
                chapter_id=payload.chapter_id, mode="shown",
                status="candidate", source="heuristic",
            )
            db.add(row)
            created.append({"subject_id": nid, "label": node.label})
    await db.commit()
    return {"created": len(created), "candidates": created}


@router.post("/{book_id}/world/depictions/{depiction_id}/confirm")
async def confirm_depiction(
    book_id: UUID, depiction_id: UUID, db: AsyncSession = Depends(get_db)
):
    """作者裁决：候选呈现 → confirmed（进读者折叠）。"""
    from backend.models import WorldDepiction

    row = await db.get(WorldDepiction, depiction_id)
    if not row or str(row.book_id) != str(book_id):
        raise HTTPException(404, "呈现关系不存在")
    row.status = "confirmed"
    await db.commit()
    return {"id": str(row.id), "status": row.status}


@router.post("/{book_id}/world/depictions/{depiction_id}/reject")
async def reject_depiction(
    book_id: UUID, depiction_id: UUID, db: AsyncSession = Depends(get_db)
):
    """作者裁决：否决候选呈现（留痕不进读者折叠）。"""
    from backend.models import WorldDepiction

    row = await db.get(WorldDepiction, depiction_id)
    if not row or str(row.book_id) != str(book_id):
        raise HTTPException(404, "呈现关系不存在")
    row.status = "rejected"
    await db.commit()
    return {"id": str(row.id), "status": row.status}

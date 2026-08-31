# Velluma - World 设定层 repository（事件溯源 + 推演引擎）
# AGPL-3.0
"""
World 设定层数据访问 + 事件溯源推演引擎（独立于 Canon repository）。

facade：WorldRepository 持 events/locations/entities 三个子 repo + compute_world_state。
compute_world_state(book_id, t) = 加载有序事件 → 纯函数 fold 成 WorldState。

三条决策（照搬世界绘卷）：
① 生死由 birth/death 事件推演：alive = born≤t 且 (无 death 或 death>t)
② move 沿 payload.path 弧长插值在途位置
③ 疆域 = 最近一次 time_start≤t 的 territory_change 的 polygon（lose 且空 polygon = 失去全部）

compute_world_state_from_events 是纯函数（无 DB），可与前端 engine 共用算法、独立单测。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import (
    Character,
    CharacterRelationship,
    Asset as LegacyAsset,
    MapLocation,
    Chapter,
    PlotLedger,
    WorldEvent,
    WorldEventCandidate,
    WorldLocation,
    WorldEntity,
    WorldMapLayer,
    WorldMapStroke,
    WorldRelation,
)


# ============================================================
# 子 repository
# ============================================================

class WorldEventRepository:
    """世界事件（事实源，append-only）。sequence_num 为全局自增序号。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all_by_book(self, book_id: str) -> List[WorldEvent]:
        """按 sequence_num 升序返回全书事件（回放用）。"""
        stmt = (
            select(WorldEvent)
            .where(WorldEvent.book_id == book_id)
            .order_by(WorldEvent.sequence_num.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def next_sequence_num(self, book_id: str) -> int:
        stmt = select(func.coalesce(func.max(WorldEvent.sequence_num), 0)).where(
            WorldEvent.book_id == book_id
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0) + 1

    async def create(self, book_id: str, **fields) -> WorldEvent:
        seq = await self.next_sequence_num(book_id)
        ev = WorldEvent(book_id=book_id, sequence_num=seq, **fields)
        self.db.add(ev)
        await self.db.flush()
        return ev

    async def get(self, event_id: str) -> Optional[WorldEvent]:
        return await self.db.get(WorldEvent, event_id)

    async def update(self, event_id: str, **fields) -> Optional[WorldEvent]:
        ev = await self.get(event_id)
        if ev is None:
            return None
        for k, v in fields.items():
            if v is not None:
                setattr(ev, k, v)
        await self.db.flush()
        return ev

    async def delete(self, event_id: str) -> bool:
        ev = await self.get(event_id)
        if ev is None:
            return False
        await self.db.delete(ev)
        await self.db.flush()
        return True


class WorldLocationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(self, book_id: str) -> List[WorldLocation]:
        result = await self.db.execute(
            select(WorldLocation)
            .where(WorldLocation.book_id == book_id)
            .order_by(WorldLocation.name)
        )
        return list(result.scalars().all())

    async def get(self, location_id: str) -> Optional[WorldLocation]:
        return await self.db.get(WorldLocation, location_id)

    async def create(self, **fields) -> WorldLocation:
        loc = WorldLocation(**fields)
        self.db.add(loc)
        await self.db.flush()
        return loc

    async def update(self, location_id: str, **fields) -> Optional[WorldLocation]:
        loc = await self.get(location_id)
        if loc is None:
            return None
        # 「键存在即设」：coord/parent 的显式 null 必须落库（清除坐标/脱离子树）——
        # 与其他 repo 的「跳过 None」不同，调用方（路由 exclude_unset）保证键语义
        for k, v in fields.items():
            setattr(loc, k, v)
        await self.db.flush()
        return loc

    async def delete(self, location_id: str) -> bool:
        loc = await self.get(location_id)
        if loc is None:
            return False
        await self.db.delete(loc)
        await self.db.flush()
        return True


class WorldEntityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(self, book_id: str, entity_type: Optional[str] = None) -> List[WorldEntity]:
        stmt = select(WorldEntity).where(WorldEntity.book_id == book_id)
        if entity_type:
            stmt = stmt.where(WorldEntity.entity_type == entity_type)
        stmt = stmt.order_by(WorldEntity.name)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, entity_id: str) -> Optional[WorldEntity]:
        return await self.db.get(WorldEntity, entity_id)

    async def create(self, **fields) -> WorldEntity:
        ent = WorldEntity(**fields)
        self.db.add(ent)
        await self.db.flush()
        return ent

    async def update(self, entity_id: str, **fields) -> Optional[WorldEntity]:
        ent = await self.get(entity_id)
        if ent is None:
            return None
        for k, v in fields.items():
            if v is not None:
                setattr(ent, k, v)
        await self.db.flush()
        return ent

    async def delete(self, entity_id: str) -> bool:
        ent = await self.get(entity_id)
        if ent is None:
            return False
        await self.db.delete(ent)
        await self.db.flush()
        return True


class WorldRelationRepository:
    """实体关系边（脑图透镜）。自环守卫在路由层做（source == target → 422）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(self, book_id: str) -> List[WorldRelation]:
        result = await self.db.execute(
            select(WorldRelation)
            .where(WorldRelation.book_id == book_id)
            .order_by(WorldRelation.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(self, relation_id: str) -> Optional[WorldRelation]:
        return await self.db.get(WorldRelation, relation_id)

    async def create(self, **fields) -> WorldRelation:
        rel = WorldRelation(**fields)
        self.db.add(rel)
        await self.db.flush()
        return rel

    async def update(self, relation_id: str, **fields) -> Optional[WorldRelation]:
        rel = await self.get(relation_id)
        if rel is None:
            return None
        for k, v in fields.items():
            if v is not None:
                setattr(rel, k, v)
        await self.db.flush()
        return rel

    async def delete(self, relation_id: str) -> bool:
        rel = await self.get(relation_id)
        if rel is None:
            return False
        await self.db.delete(rel)
        await self.db.flush()
        return True


# ============================================================
# 推演引擎（纯函数，事件溯源 fold）
# ============================================================

def _interpolate_on_path(
    path: List[List[float]], t_start: int, t_end: int, t: int
) -> Tuple[Optional[List[float]], str]:
    """决策②：沿 path 弧长插值。返回 (位置 [x,y], label)。"""
    if not path:
        return None, ""
    if len(path) == 1:
        return list(path[0]), ""
    if t <= t_start:
        return list(path[0]), ""
    if t >= t_end:
        return list(path[-1]), ""
    span = max(1, t_end - t_start)
    p = (t - t_start) / span  # 0..1 时间进度
    # 按弧长定位
    segs = []
    total = 0.0
    for i in range(len(path) - 1):
        dx = path[i + 1][0] - path[i][0]
        dy = path[i + 1][1] - path[i][1]
        seg_len = math.sqrt(dx * dx + dy * dy)
        segs.append(seg_len)
        total += seg_len
    if total <= 0:
        return list(path[0]), ""
    target = p * total
    acc = 0.0
    for i, seg_len in enumerate(segs):
        if acc + seg_len >= target or i == len(segs) - 1:
            seg_p = (target - acc) / max(1e-9, seg_len)
            seg_p = max(0.0, min(1.0, seg_p))
            x = path[i][0] + (path[i + 1][0] - path[i][0]) * seg_p
            y = path[i][1] + (path[i + 1][1] - path[i][1]) * seg_p
            return [x, y], f"在途（进度 {int(p * 100)}%）"
        acc += seg_len
    return list(path[-1]), ""


def compute_world_state_from_events(
    events: List[WorldEvent],
    locations_by_id: Dict[str, WorldLocation],
    t: int,
    relations: Optional[List[WorldRelation]] = None,
) -> Dict[str, Any]:
    """纯函数推演：从事件流 fold 成时刻 t 的 WorldState。

    与前端 engine/computeWorldState 同构（前后端共用算法逻辑）。
    返回 dict（at_time/character_states/territory_states/location_states/relation_states）。
    relations 可选：传入时推演关系边激活状态（决策④：static 恒活跃；
    event_ref 锚事件已回放（time_start≤t）才活跃）。
    """
    # 过滤 time_start <= t，按 sequence_num 升序（乱序输入结果稳定）
    applicable = sorted(
        [e for e in events if e.time_start <= t],
        key=lambda e: e.sequence_num,
    )

    character_states: Dict[str, Dict[str, Any]] = {}
    born: Dict[str, bool] = {}
    dead: Dict[str, int] = {}
    territory_states: Dict[str, Dict[str, Any]] = {}
    location_exists: Dict[str, bool] = {}

    def _loc_coord(loc_id: Optional[str]) -> Optional[List[float]]:
        if not loc_id:
            return None
        loc = locations_by_id.get(loc_id)
        if loc and loc.coord_x is not None and loc.coord_y is not None:
            return [loc.coord_x, loc.coord_y]
        return None

    for e in applicable:
        etype = e.event_type
        eid = str(e.id)
        if etype == "birth":
            cid = e.payload.get("character_id")
            if cid:
                born[cid] = True
                birth_loc = e.payload.get("location_id") or (
                    str(e.location_id) if e.location_id else None
                )
                character_states[cid] = {
                    "entity_id": cid,
                    "location_id": birth_loc,
                    "position": _loc_coord(birth_loc),
                    "alive": True,
                    "label": "出生",
                    "last_event_id": eid,
                }
        elif etype == "death":
            cid = e.payload.get("character_id")
            if cid:
                dead[cid] = e.time_start
                if cid in character_states:
                    character_states[cid]["alive"] = False
                    character_states[cid]["last_event_id"] = eid
                    character_states[cid]["label"] = "已死亡"
        elif etype == "move":
            cids = e.payload.get("character_ids", []) or []
            path = e.payload.get("path", []) or []
            to_loc = e.payload.get("to_location_id")
            for cid in cids:
                pos, label = _interpolate_on_path(path, e.time_start, e.time_end, t)
                if pos is None:
                    pos = _loc_coord(to_loc)
                character_states[cid] = {
                    "entity_id": cid,
                    "location_id": to_loc,
                    "position": pos,
                    "alive": cid not in dead,
                    "label": label or ("驻留" if t >= e.time_end else ""),
                    "last_event_id": eid,
                }
        elif etype == "territory_change":
            fid = e.payload.get("faction_id")
            if fid:
                polygon = e.payload.get("polygon", []) or []
                action = e.payload.get("action", "gain")
                if action == "lose" and not polygon:
                    territory_states.pop(fid, None)
                else:
                    territory_states[fid] = {
                        "faction_id": fid,
                        "polygon": polygon,
                        "last_event_id": eid,
                    }
        elif etype == "found":
            tid = e.payload.get("target_id")
            if tid:
                location_exists[tid] = True
        elif etype == "destroy":
            tid = e.payload.get("target_id")
            if tid:
                location_exists[tid] = False
        # battle/alliance/war_declare/coronation/custom：M1 不改世界状态

    # 生死最终判定（决策①）
    for cid, state in character_states.items():
        state["alive"] = born.get(cid, False) and (cid not in dead or dead[cid] > t)

    # 决策④：关系边激活状态（static 恒活跃；锚事件已回放才活跃）
    relation_states: List[Dict[str, Any]] = []
    if relations:
        applicable_ids = {str(e.id) for e in applicable}
        for r in relations:
            if r.static or not r.event_ref:
                active = True
            else:
                active = str(r.event_ref) in applicable_ids
            relation_states.append(
                {
                    "relation_id": str(r.id),
                    "source_entity_id": str(r.source_entity_id),
                    "target_entity_id": str(r.target_entity_id),
                    "relation_type": r.relation_type,
                    "label": r.label or "",
                    "active": active,
                }
            )

    return {
        "at_time": t,
        "character_states": list(character_states.values()),
        "territory_states": list(territory_states.values()),
        "location_states": [
            {"location_id": lid, "exists": ex} for lid, ex in location_exists.items()
        ],
        "relation_states": relation_states,
    }


# ============================================================
# 底图（图片拼贴层 + 手绘笔迹）
# ============================================================

class WorldMapLayerRepository:
    """底图图片层（用户导入的拼贴素材）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(self, book_id: str) -> List[WorldMapLayer]:
        result = await self.db.execute(
            select(WorldMapLayer)
            .where(WorldMapLayer.book_id == book_id)
            .order_by(WorldMapLayer.z_index.asc(), WorldMapLayer.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(self, layer_id: str) -> Optional[WorldMapLayer]:
        return await self.db.get(WorldMapLayer, layer_id)

    async def next_z_index(self, book_id: str) -> int:
        stmt = select(func.coalesce(func.max(WorldMapLayer.z_index), 0)).where(
            WorldMapLayer.book_id == book_id
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0) + 1

    async def create(self, **fields) -> WorldMapLayer:
        layer = WorldMapLayer(**fields)
        self.db.add(layer)
        await self.db.flush()
        return layer

    async def update(self, layer_id: str, **fields) -> Optional[WorldMapLayer]:
        layer = await self.get(layer_id)
        if layer is None:
            return None
        for k, v in fields.items():
            if v is not None:
                setattr(layer, k, v)
        await self.db.flush()
        return layer

    async def delete(self, layer_id: str) -> bool:
        layer = await self.get(layer_id)
        if layer is None:
            return False
        await self.db.delete(layer)
        await self.db.flush()
        return True


class WorldMapStrokeRepository:
    """底图手绘笔迹（矢量点序列；橡皮 = 删除命中 stroke）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(self, book_id: str) -> List[WorldMapStroke]:
        result = await self.db.execute(
            select(WorldMapStroke)
            .where(WorldMapStroke.book_id == book_id)
            .order_by(WorldMapStroke.created_at.asc())
        )
        return list(result.scalars().all())

    async def get(self, stroke_id: str) -> Optional[WorldMapStroke]:
        return await self.db.get(WorldMapStroke, stroke_id)

    async def create(self, **fields) -> WorldMapStroke:
        stroke = WorldMapStroke(**fields)
        self.db.add(stroke)
        await self.db.flush()
        return stroke

    async def delete(self, stroke_id: str) -> bool:
        stroke = await self.get(stroke_id)
        if stroke is None:
            return False
        await self.db.delete(stroke)
        await self.db.flush()
        return True


# ============================================================
# 候选事件（写作回流待确认池，与事件账本物理隔离）
# ============================================================

class WorldCandidateRepository:
    """候选事件草稿（settle/finish 抽取 → 作者确认转正）。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(
        self,
        book_id: str,
        status: Optional[str] = None,
        chapter_id: Optional[str] = None,
    ) -> List[WorldEventCandidate]:
        stmt = select(WorldEventCandidate).where(WorldEventCandidate.book_id == book_id)
        if status:
            stmt = stmt.where(WorldEventCandidate.status == status)
        if chapter_id:
            stmt = stmt.where(WorldEventCandidate.chapter_id == chapter_id)
        stmt = stmt.order_by(WorldEventCandidate.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, candidate_id: str) -> Optional[WorldEventCandidate]:
        return await self.db.get(WorldEventCandidate, candidate_id)

    async def create(
        self,
        book_id: str,
        chapter_id: Optional[str],
        draft: Dict[str, Any],
        source: str = "settle",
    ) -> WorldEventCandidate:
        cand = WorldEventCandidate(
            book_id=book_id,
            chapter_id=chapter_id,
            draft=draft,
            source=source,
            status="pending",
        )
        self.db.add(cand)
        await self.db.flush()
        return cand

    async def set_status(self, candidate_id: str, status: str) -> Optional[WorldEventCandidate]:
        cand = await self.get(candidate_id)
        if cand is None:
            return None
        cand.status = status
        await self.db.flush()
        return cand


# ============================================================
# Facade
# ============================================================

class WorldRepository:
    """World 设定层聚合 repository（独立于 CanonRepository，通过 book_id 隔离）。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = WorldEventRepository(db)
        self.locations = WorldLocationRepository(db)
        self.entities = WorldEntityRepository(db)
        self.relations = WorldRelationRepository(db)
        self.candidates = WorldCandidateRepository(db)
        self.map_layers = WorldMapLayerRepository(db)
        self.map_strokes = WorldMapStrokeRepository(db)

    async def compute_world_state(self, book_id: str, t: int) -> Dict[str, Any]:
        """推演时刻 t 的世界状态。加载事件 + 地点 + 关系，调纯函数 fold。"""
        events = await self.events.list_all_by_book(book_id)
        locations = await self.locations.list_by_book(book_id)
        relations = await self.relations.list_by_book(book_id)
        locations_by_id = {str(loc.id): loc for loc in locations}
        return compute_world_state_from_events(events, locations_by_id, t, relations)

    async def world_version(self, book_id: str) -> Dict[str, Any]:
        """世界数据版本（写作页切片保鲜比对；docs/world-writing-bridge.md §4.2）。

        events 计数 + events/entities/locations/relations 四表聚合 max(updated_at)。
        计数兜底「删除不 bump updated_at」的盲区。单条聚合查询，心跳附带零负担。
        """
        def _max_updated(model):
            return (
                select(func.max(model.updated_at))
                .where(model.book_id == book_id)
                .scalar_subquery()
            )

        count_sq = (
            select(func.count(WorldEvent.id))
            .where(WorldEvent.book_id == book_id)
            .scalar_subquery()
        )
        result = await self.db.execute(
            select(
                count_sq,
                _max_updated(WorldEvent),
                _max_updated(WorldEntity),
                _max_updated(WorldLocation),
                _max_updated(WorldRelation),
            )
        )
        events_count, *maxes = result.one()
        stamps = [m for m in maxes if m is not None]
        return {
            "events": int(events_count or 0),
            "updated_at": max(stamps) if stamps else None,
        }

    # ============================================================
    # 旧设定中心 → 世界页 一次性迁移（幂等）
    # ============================================================

    async def migrate_legacy_settings(self, book_id: str) -> Dict[str, Any]:
        """设定中心旧表迁入世界页（M4 前置；docs/world-unified-settings.md）。

        映射：
        - characters → WorldEntity(character)：name/aliases/importance；
          static_prompt 全文进 props.background（不机器瞎拆——作者在抽屉里自行
          拆到具体字段）；dynamic_state/current_state **不迁**（时变状态由事件推演，
          只计数告知）
        - assets → WorldEntity(asset)：static_description → intro
        - character_relationships → WorldRelation：两端实体都已迁（本次或既往）才建边；
          label=旧 relation_type 原文，note=interaction_prompt，affinity 截断到 ±100
        - map_locations → WorldLocation：旧表无坐标，coord 置空（kind=point，intro=description）
        - plot_ledgers：world_time_planted 为空且有章节叙事锚的，按章锚补 world_time_planted
          （旧伏笔由此出现在时间轴弧线带）

        幂等：实体 metadata_.migrated_from 记来源 id（重跑跳过）；地点按名查重；
        关系按 (source,target,label) 查重。全程只写世界页表，不动旧表。
        """
        report: Dict[str, Any] = {
            "characters": {"migrated": 0, "skipped_existing": 0},
            "assets": {"migrated": 0, "skipped_existing": 0},
            "locations": {"migrated": 0, "skipped_existing": 0},
            "relations": {"migrated": 0, "skipped_missing_endpoint": 0, "skipped_existing": 0},
            "foreshadows_anchored": 0,
            "dynamic_states_skipped": 0,
        }

        # 已迁实体的来源映射（含既往迁移，供关系边补迁与幂等跳过）
        result = await self.db.execute(
            select(WorldEntity).where(WorldEntity.book_id == book_id)
        )
        char_id_map: Dict[str, str] = {}  # 旧 characters.id → WorldEntity.id
        migrated_asset_ids: set = set()
        for ent in result.scalars().all():
            mf = (ent.metadata_ or {}).get("migrated_from") or {}
            if not mf.get("table") or not mf.get("id"):
                continue
            if mf["table"] == "characters":
                char_id_map[str(mf["id"])] = str(ent.id)
            elif mf["table"] == "assets":
                migrated_asset_ids.add(str(mf["id"]))

        # ---- characters ----
        result = await self.db.execute(select(Character).where(Character.book_id == book_id))
        for c in result.scalars().all():
            cid = str(c.id)
            if cid in char_id_map:
                report["characters"]["skipped_existing"] += 1
                continue
            props: Dict[str, Any] = {}
            if c.static_prompt:
                props["background"] = c.static_prompt
            ent = WorldEntity(
                book_id=book_id,
                entity_type="character",
                name=c.name,
                aliases=list(c.aliases or []),
                importance=max(1, min(10, int(c.importance_level or 1))),
                visibility="public",
                intro="",
                tags=[],
                props=props,
                metadata_={"migrated_from": {"table": "characters", "id": cid}},
            )
            self.db.add(ent)
            await self.db.flush()
            char_id_map[cid] = str(ent.id)
            report["characters"]["migrated"] += 1
            if (c.dynamic_state and c.dynamic_state.strip()) or (
                c.current_state and c.current_state.strip()
            ):
                report["dynamic_states_skipped"] += 1

        # ---- assets ----
        result = await self.db.execute(select(LegacyAsset).where(LegacyAsset.book_id == book_id))
        for a in result.scalars().all():
            aid = str(a.id)
            if aid in migrated_asset_ids:
                report["assets"]["skipped_existing"] += 1
                continue
            ent = WorldEntity(
                book_id=book_id,
                entity_type="asset",
                name=a.name,
                aliases=list(a.aliases or []),
                importance=max(1, min(10, int(a.importance_level or 1))),
                visibility="public",
                intro=(a.static_description or "")[:500],
                tags=[],
                props={},
                metadata_={"migrated_from": {"table": "assets", "id": aid}},
            )
            self.db.add(ent)
            await self.db.flush()
            migrated_asset_ids.add(aid)
            report["assets"]["migrated"] += 1

        # ---- relationships（两端都已迁才建边）----
        result = await self.db.execute(
            select(CharacterRelationship)
            .join(Character, CharacterRelationship.source_char_id == Character.id)
            .where(Character.book_id == book_id)
        )
        rels = result.scalars().all()
        existing_rel = await self.relations.list_by_book(book_id)
        existing_rel_keys = {
            (str(r.source_entity_id), str(r.target_entity_id), r.label or "") for r in existing_rel
        }
        for rel in rels:
            src = char_id_map.get(str(rel.source_char_id))
            tgt = char_id_map.get(str(rel.target_char_id))
            if not src or not tgt or src == tgt:
                report["relations"]["skipped_missing_endpoint"] += 1
                continue
            label = rel.relation_type or ""
            if (src, tgt, label) in existing_rel_keys:
                report["relations"]["skipped_existing"] += 1
                continue
            self.db.add(
                WorldRelation(
                    book_id=book_id,
                    source_entity_id=src,
                    target_entity_id=tgt,
                    relation_type="custom",
                    label=label,
                    affinity=max(-100, min(100, int(rel.affinity_score or 0))) if rel.affinity_score else None,
                    note=rel.interaction_prompt or "",
                    static=True,
                    event_ref=None,
                )
            )
            existing_rel_keys.add((src, tgt, label))
            report["relations"]["migrated"] += 1

        # ---- map_locations（无坐标 → coord 空）----
        result = await self.db.execute(select(MapLocation).where(MapLocation.book_id == book_id))
        world_locs = await self.locations.list_by_book(book_id)
        existing_loc_names = {loc.name for loc in world_locs}
        for loc in result.scalars().all():
            if loc.name in existing_loc_names:
                report["locations"]["skipped_existing"] += 1
                continue
            self.db.add(
                WorldLocation(
                    book_id=book_id,
                    name=loc.name,
                    kind="point",
                    parent_id=None,
                    coord_x=None,
                    coord_y=None,
                    geometry={},
                    intro=(loc.description or "")[:500],
                    tags=[],
                )
            )
            existing_loc_names.add(loc.name)
            report["locations"]["migrated"] += 1

        # ---- plot_ledgers：按章节叙事锚补 world_time_planted ----
        result = await self.db.execute(
            select(PlotLedger)
            .join(Chapter, PlotLedger.chapter_id == Chapter.id)
            .where(
                PlotLedger.book_id == book_id,
                PlotLedger.world_time_planted.is_(None),
                Chapter.narrative_time.isnot(None),
            )
        )
        for ledger in result.scalars().all():
            chapter = await self.db.get(Chapter, ledger.chapter_id)
            if chapter is None or chapter.narrative_time is None:
                continue
            ledger.world_time_planted = int(chapter.narrative_time)
            report["foreshadows_anchored"] += 1

        await self.db.flush()
        return report

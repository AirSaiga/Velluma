# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 世界切片服务（写作页「此刻此地」）
"""
章节时刻的世界切片（docs/world-writing-bridge.md §4.1，W1 切片上桌）。

切片即契约（P2）：写作页切片条 / 世界页游标回放 / 生成上下文三处同源——
本服务与 settings_bundle 共用 resolve_narrative_time（四级降级）与
compute_world_state（事件折叠），保证「作者看到的在场 = AI 看到的在场」。

块级缺席原则：每块（在场/脚下/头顶的线）缺原料时返回空集合，前端按块隐藏，
不造数据。

副作用：无（纯查询）。
"""
from __future__ import annotations

from hashlib import md5
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Book, PlotLedger
from backend.repositories.world_repository import (
    WorldRepository,
    compute_world_state_from_events,
)
from backend.services.context.settings_bundle import _reader_expectations_view
from backend.services.context.world_bridge import resolve_narrative_time

_PRESENCE_LIMIT = 40       # 在场角色上限（2026-09-16 双层分立：前端按取景/章范围过滤，上限只防极端长书全量倾泻）
_FORESHADOW_LIMIT = 4      # 伏笔上限（前端展示前 2 条 + 计数）
_EXPECTATION_LIMIT = 3     # 期待上限
_CHAPTER_ACTORS_MAX = 12   # 全章名册正文轨上限（事件轨另有 _PRESENCE_LIMIT）
_CHAPTER_ACTORS_CACHE_CAP = 64  # 章级扫描缓存容量（超限整体清空——书章数远小于此量级）

# 章级扫描缓存：md5(纯文本) → 扫描结果。内容不变零重扫（切片保鲜三时机反复
# 调用只付一次 md5 的钱）；内存级，进程重启即空，无失效协议负担
_CHAPTER_ACTORS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


def extract_chapter_actors(
    content_text: str,
    entities: List[Any],
) -> List[Dict[str, Any]]:
    """全章正文活跃名册（纯代码 0 LLM，方向 B · docs 通告单语义）。

    双轨并集的「正文轨」：对整章纯文本跑同一套活跃者判定——
    - 已建档角色：extract_active_actors 全章模式（对白/交互/动作/对白密度，
      闪回句豁免，别名归正名）——与微观取景器共用同一函数与名册词表
      （known_name_terms），身份判定逐字节同构；
    - 未建档角色：detect_guest_names（jieba 提名+子串计数双核验+泛称停用，
      ≤2 名）——与 dock 的临时通行证同一实现；
    输出 [{name, via, entity_id?, source: 'registered'|'guest'}]。
    md5(纯文本) 缓存：同内容零重扫（10k 字首次约 15-30ms，此后 ~0）。
    """
    from backend.services.utils.html_text import html_to_plain

    plain = html_to_plain(content_text or "")
    if not plain:
        return []
    key = md5(plain.encode("utf-8")).hexdigest()
    cached = _CHAPTER_ACTORS_CACHE.get(key)
    if cached is not None:
        return cached

    from backend.services.world.active_scene import (
        dedupe_guest_names, extract_active_actors, known_name_terms,
    )

    actors: List[Dict[str, Any]] = [
        {**a, "source": "registered"}
        for a in extract_active_actors(plain, entities, window_chars=None, max_actors=_CHAPTER_ACTORS_MAX)
    ]
    known = {a["name"] for a in actors} | set(known_name_terms(entities))
    if len(actors) < _CHAPTER_ACTORS_MAX:
        try:
            from backend.services.adaptive.components.dock_generator import detect_guest_names

            # 超长章护栏（jieba posseg 实测 ~26ms/千字）：>30k 字时 guest 提名退
            # 化为尾 8k 窗（registered 轨是纯名词表匹配仍全章——0.07ms/千字）
            guest_text = plain if len(plain) <= 30000 else plain[-8000:]
            for g in dedupe_guest_names(detect_guest_names(guest_text, sorted(known))):
                actors.append({"name": g, "via": "未建档", "entity_id": "", "source": "guest"})
        except Exception:
            pass
    actors = actors[:_CHAPTER_ACTORS_MAX]
    if len(_CHAPTER_ACTORS_CACHE) >= _CHAPTER_ACTORS_CACHE_CAP:
        _CHAPTER_ACTORS_CACHE.clear()
    _CHAPTER_ACTORS_CACHE[key] = actors
    return actors


def _point_in_polygon(x: float, y: float, polygon: List[List[float]]) -> bool:
    """射线法点包含（仓库无地理库，疆域判定的最小实现；与前端 engine 同语义）。"""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i][0], polygon[i][1]
        x2, y2 = polygon[(i + 1) % n][0], polygon[(i + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def _controlling_faction_for_location(
    state: Dict[str, Any],
    loc: Any,
    entities_by_id: Dict[str, Any],
) -> Optional[str]:
    """地点的疆域控制方：有坐标且对 territory polygon 唯一命中才有值（不造数据）。"""
    if loc is None or loc.coord_x is None or loc.coord_y is None:
        return None
    hits = []
    for ts in state.get("territory_states", []):
        polygon = ts.get("polygon") or []
        if len(polygon) >= 3 and _point_in_polygon(loc.coord_x, loc.coord_y, polygon):
            hits.append(ts.get("faction_id"))
    if len(hits) == 1:
        faction = entities_by_id.get(str(hits[0]))
        return (faction.name or "") if faction is not None else None
    return None


def _resolve_scene_location(
    events: List[Any],
    t: int,
    locations_by_id: Dict[str, Any],
    presence: List[Dict[str, Any]],
    presence_loc_ids: List[str],
) -> Optional[Dict[str, Any]]:
    """脚下判定：≤t 最新带地点事件 → 最高优先在场角色的位置 → None（整块隐藏）。"""
    # ① 最新 time_start ≤ t 且 location_id 非空的事件（时间倒序、序号倒序）
    located = [
        e for e in events
        if e.location_id and (e.time_start is not None and e.time_start <= t)
    ]
    if located:
        located.sort(key=lambda e: (e.time_start or 0, e.sequence_num or 0), reverse=True)
        loc = locations_by_id.get(str(located[0].location_id))
        if loc is not None:
            return loc

    # ② 在场主角位置（alive 在前、重要度降序的 presence 首个有地点者）
    alive_ordered = [p for p in presence if p["alive"]]
    for p in alive_ordered:
        loc = locations_by_id.get(p.get("_location_id") or "")
        if loc is not None:
            return loc
    for lid in presence_loc_ids:
        loc = locations_by_id.get(lid)
        if loc is not None:
            return loc
    return None


def _gap_logger(book_id: str, chapter: Any):
    """词法兜底缺口事件的台账回调（P1-3：数据缺口可度量；失败静默）。"""
    from backend.services.constraints.events import log_constraint_event

    chapter_id = str(getattr(chapter, "id", "") or "")

    def _log(cid, outcome, reason, detail):
        try:
            log_constraint_event(book_id, chapter_id, cid, outcome, reason=reason, detail=detail)
        except Exception:
            pass

    return _log


async def build_scene_slice(
    db: AsyncSession,
    book_id: str,
    chapter: Any,
) -> Dict[str, Any]:
    """聚合章节时刻的世界切片（GET /world/scene-slice 的实现）。

    Returns: SceneSliceResponse 的构造 dict（路由层经 response_model 校验）。
    """
    repo = WorldRepository(db)

    # 世界页无实体：旧表兜底书。返回空切片 + world_empty 旗标（前端显示迁移引导）。
    entities = await repo.entities.list_by_book(book_id)
    if not entities:
        return {
            "t": 0,
            "t_source": "zero",
            "presence": [],
            "scene": None,
            "foreshadows": [],
            "expectations": [],
            "version": await repo.world_version(book_id),
            "world_empty": True,
        }

    nt = await resolve_narrative_time(db, chapter)
    t = nt.t

    # 事件一次加载，推演与脚下判定共用（不重复拉取）
    events = await repo.events.list_all_by_book(book_id)
    locations = await repo.locations.list_by_book(book_id)
    relations = await repo.relations.list_by_book(book_id)
    locations_by_id = {str(loc.id): loc for loc in locations}
    state = compute_world_state_from_events(events, locations_by_id, t, relations)
    # 词法兜底（2026-09-02 约束治理一期）：与 repo.compute_world_state 同一
    # 增强函数——本文件三处直调点不做各自 inline（口径漂移的培养基）
    from backend.services.world.lexical_presence import enrich_state_with_lexical_presence

    enrich_state_with_lexical_presence(
        state, events, entities, locations_by_id, t, on_event=_gap_logger(book_id, chapter),
    )

    # ---- A4 叙事时间来源可见（docs/foundation-hardening.md §2.2，零行为变化）----
    # max_event：附 time_start 最大事件的摘要（note 优先、event_type 兜底，截 30 字）——
    # 让「未锚定被远期事件拉走」从隐形变可见。找不到摘要则省略字段，不报错。
    t_source_note: Optional[str] = None
    if nt.source == "max_event":
        timed = [e for e in events if e.time_start is not None]
        if timed:
            ev = max(timed, key=lambda e: (e.time_start or 0, e.sequence_num or 0))
            summary = str(getattr(ev, "note", "") or "").strip() or str(getattr(ev, "event_type", "") or "").strip()
            if summary:
                t_source_note = summary[:30]

    entities_by_id = {str(e.id): e for e in entities}

    # ---- 在场：有事件推演事态的角色（活着在前、重要度降序）----
    presence: List[Dict[str, Any]] = []
    presence_loc_ids: List[str] = []
    for cs in state.get("character_states", []):
        ent = entities_by_id.get(str(cs.get("entity_id")))
        if ent is None or ent.entity_type != "character":
            continue
        loc_id = str(cs.get("location_id") or "")
        loc = locations_by_id.get(loc_id)
        if loc_id:
            presence_loc_ids.append(loc_id)
        presence.append(
            {
                "entity_id": str(ent.id),
                "name": ent.name or "",
                "alive": bool(cs.get("alive")),
                "location_name": (loc.name or "") if loc is not None else "",
                # 结构化位置 id（2026-09-16 双层分立）：同 _location_id 对外暴露——
                # 前端按取景/章范围子树闭包过滤；_location_id/_xy 仍为内部消费
                "location_id": loc_id,
                "label": str(cs.get("label") or ""),
                # 词法兜底标记（lexical=据正文推断，前端渲染补录建议 badge）
                "presence_source": str(cs.get("presence_source") or "") or None,
                "importance": int(getattr(ent, "importance", 1) or 1),
                "visibility": getattr(ent, "visibility", "public") or "public",
                "_location_id": loc_id,
                "_xy": (loc.coord_x, loc.coord_y)
                if loc is not None and loc.coord_x is not None and loc.coord_y is not None
                else None,
            }
        )

    # ---- 同地相遇提示（W5-lite）：t 时刻同地点的存活角色两两成组（戏剧机会线索）----
    by_loc: Dict[str, List[str]] = {}
    for p in presence:
        if p["alive"] and p["_location_id"]:
            by_loc.setdefault(p["_location_id"], []).append(p["name"])
    encounters = [
        {"names": sorted(names), "location_name": (locations_by_id.get(lid).name or "")}
        for lid, names in by_loc.items()
        if len(names) >= 2
    ]
    encounters.sort(key=lambda e: -len(e["names"]))
    encounters = encounters[:3]

    presence.sort(key=lambda p: (not p["alive"], -p["importance"]))
    presence = presence[:_PRESENCE_LIMIT]

    # ---- 脚下：场景地点（钉定优先 → ≤t 最新带地点事件 → 在场主角位置 → 隐藏）----
    scene: Optional[Dict[str, Any]] = None
    pinned_loc = locations_by_id.get(str(getattr(chapter, "scene_location_id", None) or ""))
    scene_loc = pinned_loc
    scene_pinned = pinned_loc is not None
    if scene_loc is None:
        scene_loc = _resolve_scene_location(events, t, locations_by_id, presence, presence_loc_ids)
    if scene_loc is not None:
        from backend.services.world.location_tree import location_path

        scene = {
            "location_id": str(scene_loc.id),
            "name": scene_loc.name or "",
            # 全路径（内部构造脚下的无歧义显示；顶层=裸名与 name 同值）
            "path": location_path(scene_loc, locations_by_id),
            "controlling_faction": _controlling_faction_for_location(state, scene_loc, entities_by_id),
            "pinned": scene_pinned,
        }

    # ---- 头顶的线·伏笔：开放伏笔，在场实体名/别名命中提权，本章新埋必进 ----
    present_names = set()
    for p in presence:
        present_names.add(p["name"])
        ent = entities_by_id.get(p["entity_id"])
        if ent is not None:
            present_names.update(str(a) for a in (getattr(ent, "aliases", None) or []) if a)
    current_number = int(getattr(chapter, "chapter_number", 0) or 0)

    result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == book_id,
            PlotLedger.status == "open",
        )
    )
    foreshadow_rows: List[Dict[str, Any]] = []
    for hook in result.scalars().all():
        content = hook.content or ""
        boosted = any(n and n in content for n in present_names) or (
            hook.chapter_id is not None and str(hook.chapter_id) == str(chapter.id)
        )
        chapters_open = None
        if hook.created_at_chapter is not None and current_number:
            chapters_open = max(0, current_number - int(hook.created_at_chapter))
        foreshadow_rows.append(
            {
                "ledger_key": hook.ledger_key or "",
                "content": content[:60],
                "chapters_open": chapters_open,
                "_boost": 1 if boosted else 0,
            }
        )
    foreshadow_rows.sort(key=lambda r: (-r["_boost"], -(r["chapters_open"] or 0)))
    foreshadows = [
        {k: v for k, v in row.items() if not k.startswith("_")}
        for row in foreshadow_rows[:_FORESHADOW_LIMIT]
    ]

    # ---- 头顶的线·期待：reader_mirror 活跃期待（与生成侧 reader_expectations 同源）----
    book = await db.get(Book, book_id)
    expectations = _reader_expectations_view(book)[:_EXPECTATION_LIMIT]

    # ---- D4-2：比例尺标定后的诚实距离（docs/map-scale-spatial.md §5；未标定整段缺席） ----
    proximities: List[Dict[str, Any]] = []
    nearest_anchor = None
    scale = getattr(book, "map_scale", None) if book is not None else None
    if scale:
        from backend.services.world.spatial import distance_days, format_distance

        def _loc_xy(lid: str):
            l = locations_by_id.get(lid)
            if l is not None and l.coord_x is not None and l.coord_y is not None:
                return (l.coord_x, l.coord_y)
            return None

        alive = [p for p in presence if p["alive"] and _loc_xy(p["_location_id"])]
        pairs: List[tuple] = []
        for i in range(len(alive)):
            for j in range(i + 1, len(alive)):
                if alive[i]["_location_id"] == alive[j]["_location_id"]:
                    continue  # 同地组已有 encounters
                d = distance_days(_loc_xy(alive[i]["_location_id"]), _loc_xy(alive[j]["_location_id"]), scale)
                if d is not None and d <= 3.0:  # 分档：半日内/1-3 天才值得提示
                    pairs.append((d, alive[i]["name"], alive[j]["name"]))
        for d, a, b in sorted(pairs)[:3]:
            proximities.append({
                "a": a, "b": b,
                "text": f"{a}与{b}相距{format_distance(d)}，赶路可及",
            })
        # 脚下最近锚点地点（有场景坐标才算；同地排除）
        if scene and scene.get("location_id"):
            sxy = _loc_xy(str(scene["location_id"]))
            if sxy is not None:
                cands = []
                for loc in locations:
                    # 半坐标防御：coord_y 缺失时 (coord_x, None) 进距离计算会 TypeError
                    # （与上方 _loc_xy 的 x/y 双判同口径）
                    if str(loc.id) == str(scene["location_id"]) or loc.coord_x is None or loc.coord_y is None:
                        continue
                    d = distance_days(sxy, (loc.coord_x, loc.coord_y), scale)
                    if d is not None and d > 0.05:
                        cands.append((d, loc.name or ""))
                if cands:
                    d, name = min(cands)
                    nearest_anchor = {"name": name, "text": format_distance(d)}

    result = {
        "t": t,
        "t_source": nt.source,
        "presence": [{k: v for k, v in p.items() if not k.startswith("_")} for p in presence],
        "scene": scene,
        "encounters": encounters,
        "foreshadows": foreshadows,
        "expectations": expectations,
        # 全章正文活跃名册（2026-09-17 方向 B）：正文说话/交互/动作的角色（含
        # 未建档 guest）与事件推演名册并集——零事件不等于零戏份，明姐/王叔
        # 们不因没写 move 事件就从通告单上消失
        "chapter_actors": extract_chapter_actors(
            getattr(chapter, "content_text", "") or "", entities,
        ),
        "version": await repo.world_version(book_id),
        "world_empty": False,
    }
    if proximities:
        result["proximities"] = proximities
    if nearest_anchor:
        result["nearest_anchor"] = nearest_anchor
    # A4 来源可见：新字段缺席省略（旧前端不读即忽略，向后兼容）
    if t_source_note:
        result["t_source_note"] = t_source_note
    if nt.source == "prev_anchor" and nt.chapter_number is not None:
        result["t_source_chapter"] = int(nt.chapter_number)
    # D4-3：生成上下文的空间常识块（settings_bundle 消费；未标定为空串零变化）
    if scale:
        from backend.services.world.spatial import build_spatial_brief

        scene_xy = None
        if scene and scene.get("location_id"):
            scene_xy = _loc_xy(str(scene["location_id"]))
        brief = build_spatial_brief(
            [{"name": p["name"], "x": p["_xy"][0], "y": p["_xy"][1]} for p in presence if p.get("_xy")],
            ({"name": scene.get("name") or "", "x": scene_xy[0], "y": scene_xy[1]} if scene_xy else None),
            scale,
        )
        if brief:
            result["spatial_brief"] = brief
    return result


# ============================================================
# 情境浮卡（W2 查询闭环：选中文本 / 点击提及 → 三秒查明底细）
# ============================================================

_CHRONICLE_LIMIT = 3


def _events_sorted_desc(events: List[Any]) -> List[Any]:
    return sorted(events, key=lambda e: (e.time_start or 0, e.sequence_num or 0), reverse=True)


def _event_brief(ev: Any) -> Dict[str, Any]:
    return {
        "event_type": ev.event_type or "custom",
        "title": getattr(ev, "title", None) or "",
        "note": (ev.note or "")[:80],
        "time_start": ev.time_start or 0,
    }


def _entity_chronicle(events: List[Any], entity_id: str, t: int) -> List[Dict[str, Any]]:
    """实体编年史：涉其事件（participant_ids ∪ payload.character_id）≤ t 倒序取近。

    与 RAG A 层（recall._world_echoes）同规则：防剧透，只取叙事时刻之前。
    """
    out: List[Dict[str, Any]] = []
    for ev in _events_sorted_desc(events):
        if (ev.time_start or 0) > t:
            continue
        participants = {str(p) for p in (ev.participant_ids or [])}
        payload_cid = str((ev.payload or {}).get("character_id") or "")
        if entity_id in participants or (payload_cid and payload_cid == entity_id):
            out.append(_event_brief(ev))
            if len(out) >= _CHRONICLE_LIMIT:
                break
    return out


async def build_context_card(
    db: AsyncSession,
    book_id: str,
    chapter: Any,
    entity_id: Optional[str] = None,
    location_id: Optional[str] = None,
    name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """情境浮卡（GET /world/context-card 的实现）。

    解析顺序：entity_id → location_id → name（实体名/别名精确匹配 → 地点名）。
    解析不到返回 None（路由层 404，选区驱动的浮卡静默缺席）。

    Returns: ContextCardResponse 的构造 dict；t 一并返回（前端深链游标用）。
    """
    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    entities_by_id = {str(e.id): e for e in entities}

    ent = entities_by_id.get(str(entity_id)) if entity_id else None
    loc = await repo.locations.get(str(location_id)) if location_id else None
    if ent is None and loc is None and name:
        for e in entities:
            if e.name == name or name in [str(a) for a in (getattr(e, "aliases", None) or [])]:
                ent = e
                break
        if ent is None:
            for l in await repo.locations.list_by_book(book_id):
                if l.name == name:
                    loc = l
                    break
    if ent is None and loc is None:
        return None

    nt = await resolve_narrative_time(db, chapter)
    t = nt.t
    events = await repo.events.list_all_by_book(book_id)

    if ent is not None:
        eid = str(ent.id)
        alive: Optional[bool] = None
        location_name = ""
        label = ""
        presence_source = ""
        if ent.entity_type == "character":
            locations = await repo.locations.list_by_book(book_id)
            locations_by_id = {str(l.id): l for l in locations}
            state = compute_world_state_from_events(events, locations_by_id, t)
            # 词法兜底（同 build_scene_slice：三处直调点共用同一增强函数）
            from backend.services.world.lexical_presence import enrich_state_with_lexical_presence

            enrich_state_with_lexical_presence(
                state, events, await repo.entities.list_by_book(book_id), locations_by_id, t,
                on_event=_gap_logger(book_id, chapter),
            )
            cs = next(
                (c for c in state.get("character_states", []) if str(c.get("entity_id")) == eid),
                None,
            )
            if cs:
                alive = bool(cs.get("alive"))
                loc_obj = locations_by_id.get(str(cs.get("location_id") or ""))
                location_name = (loc_obj.name or "") if loc_obj is not None else ""
                label = str(cs.get("label") or "")
                presence_source = str(cs.get("presence_source") or "")
        return {
            "kind": "entity",
            "id": eid,
            "entity_type": ent.entity_type or "character",
            "name": ent.name or "",
            "intro": (ent.intro or "")[:100],
            "t": t,
            "alive": alive,
            "location_name": location_name,
            "label": label,
            "presence_source": presence_source or None,
            "chronicle": _entity_chronicle(events, eid, t),
        }

    # 地点卡
    locations = await repo.locations.list_by_book(book_id)
    locations_by_id = {str(l.id): l for l in locations}
    relations = await repo.relations.list_by_book(book_id)
    state = compute_world_state_from_events(events, locations_by_id, t, relations)
    # 词法兜底（第三处直调点，同口径）
    from backend.services.world.lexical_presence import enrich_state_with_lexical_presence

    enrich_state_with_lexical_presence(
        state, events, await repo.entities.list_by_book(book_id), locations_by_id, t,
        on_event=_gap_logger(book_id, chapter),
    )
    recent: List[Dict[str, Any]] = []
    for ev in _events_sorted_desc(events):
        if (ev.time_start or 0) > t:
            continue
        if ev.location_id and str(ev.location_id) == str(loc.id):
            recent.append(_event_brief(ev))
            if len(recent) >= _CHRONICLE_LIMIT:
                break
    return {
        "kind": "location",
        "id": str(loc.id),
        "entity_type": "location",
        "name": loc.name or "",
        "intro": (loc.intro or "")[:100],
        "t": t,
        "controlling_faction": _controlling_faction_for_location(state, loc, entities_by_id),
        "recent_events": recent,
    }

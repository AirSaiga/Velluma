# Velluma - 速记解析器（W3 一句话记历史）
# AGPL-3.0
"""
作者一句口语 → 结构化事件草稿（docs/world-writing-bridge.md §4.3）。

红线：本模块只产草稿、绝不写库——入账走既有事件创建端点（作者过目确认）。
解析失败/低置信 → 返回空草稿 + confidence 标记，前端降级为空白轻表单。

副作用：无。LLM 调用 1×creative（REASONING_DISABLED + 小预算 + temp 0.1）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.world_repository import WorldRepository
from backend.services.context.world_bridge import resolve_narrative_time
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.prompts.world_event_prompts import _safe_json, build_parse_event_prompt

_MAX_DAY_OFFSET = 3650  # ±10 年，超出视为幻觉夹回
_VALID_TYPES = {
    "birth", "death", "move", "battle", "territory_change", "found",
    "destroy", "alliance", "war_declare", "coronation", "custom",
}


def _resolve_names(names: List[Any], entities: List[Any]) -> Dict[str, Any]:
    """名字（含别名）→ {name: entity} 精确匹配表。"""
    table: Dict[str, Any] = {}
    for e in entities:
        table[e.name or ""] = e
        for a in (getattr(e, "aliases", None) or []):
            if a:
                table[str(a)] = e
    out = {}
    for n in names:
        ent = table.get(str(n or "").strip())
        if ent is not None:
            out[str(n)] = ent
    return out


def _clamp_int(v: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _location_lookup(locations: List[Any], name: str) -> Optional[Any]:
    """名字 → 地点：全路径（父·子）精确优先，裸名兜底。

    树形化后跨父同名合法（两个基地各有一个「拘留室」）——全路径无歧义；
    裸名多命中时取先建者（速记口语通常只说裸名，歧义留作者在表单里改）。
    """
    from backend.services.world.location_tree import location_path, locations_by_id

    want = name.strip()
    if not want:
        return None
    by_id = locations_by_id(locations)
    bare: Dict[str, Any] = {}
    for l in locations:
        path = location_path(l, by_id)
        if path == want:
            return l
        bare.setdefault(l.name or "", l)
    return bare.get(want)


def normalize_draft(
    parsed: Dict[str, Any],
    t: int,
    entities: List[Any],
    locations: List[Any],
) -> Dict[str, Any]:
    """LLM 输出 → 前端友好的草稿形状（id 与名字都带，表单可改）。"""
    etype = str(parsed.get("event_type") or "").strip()
    if etype not in _VALID_TYPES:
        etype = "custom"
    resolved = _resolve_names(list(parsed.get("participants") or []), entities)
    loc = _location_lookup(locations, str(parsed.get("location") or ""))
    time_start = t + _clamp_int(parsed.get("day_offset"), 0, -t, _MAX_DAY_OFFSET)
    time_start = max(0, time_start)
    duration = _clamp_int(parsed.get("duration_days"), 0, 0, 3650)
    return {
        "event_type": etype,
        "summary": str(parsed.get("summary") or "")[:30],
        "time_start": time_start,
        "time_end": time_start + duration,
        "participant_ids": [str(e.id) for e in resolved.values()],
        "participant_names": [e.name or "" for e in resolved.values()],
        "unresolved_names": [
            str(n) for n in (parsed.get("participants") or []) if str(n) not in resolved
        ],
        "location_id": str(loc.id) if loc is not None else None,
        "location_name": (loc.name or "") if loc is not None else "",
        "note": str(parsed.get("note") or "")[:80],
    }


async def parse_event_text(
    db: AsyncSession,
    book_id: str,
    chapter: Any,
    text: str,
) -> Dict[str, Any]:
    """一句话速记 → {draft, confidence}。失败返回空草稿 + confidence=none。"""
    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    if not entities:
        return {"draft": _empty_draft(), "confidence": "none"}
    locations = await repo.locations.list_by_book(book_id)
    t = (await resolve_narrative_time(db, chapter)).t

    system_prompt, user_prompt = build_parse_event_prompt(text.strip()[:400], t, entities, locations)
    try:
        from backend.services.utils.json_safe import parse_json_safe

        resp = await call_llm_with_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="creative",
            temperature=0.1,
            max_tokens=800,
            reasoning_config=REASONING_DISABLED,
        )
        # 生产形态 LLMResult(.content)；测试 mock 形态 (text, usage) 二元组（对齐 memory_ingestion）
        if isinstance(resp, tuple):
            raw = str(resp[0]) if resp[0] is not None else ""
        else:
            raw = getattr(resp, "content", "") or ""
        parsed = parse_json_safe(str(raw)) or _safe_json(str(raw))
    except Exception:
        parsed = {}

    if not isinstance(parsed, dict) or not parsed:
        return {"draft": _empty_draft(t), "confidence": "none"}

    draft = normalize_draft(parsed, t, entities, locations)
    if draft["event_type"] == "custom" and not draft["participant_ids"]:
        confidence = "low"
    elif draft["participant_ids"] or draft["location_id"]:
        confidence = "high"
    else:
        confidence = "low"
    return {"draft": draft, "confidence": confidence}


def _empty_draft(t: int = 0) -> Dict[str, Any]:
    return {
        "event_type": "custom",
        "summary": "",
        "time_start": t,
        "time_end": t,
        "participant_ids": [],
        "participant_names": [],
        "unresolved_names": [],
        "location_id": None,
        "location_name": "",
        "note": "",
    }

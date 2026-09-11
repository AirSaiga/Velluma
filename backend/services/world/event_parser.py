# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 速记解析器（W3 一句话记历史）
"""
作者一句口语 → 结构化事件草稿（docs/world-writing-bridge.md §4.3）。

红线：本模块只产草稿、绝不写库——入账走既有事件创建端点（作者过目确认）。
解析失败/低置信 → 返回空草稿 + confidence 标记，前端降级为空白轻表单。

副作用：无。LLM 调用 1×creative（REASONING_DISABLED + 小预算 + temp 0.1）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
_VALID_KINDS = {"character", "faction", "asset"}
_MAX_NEW_ENTITIES = 4
_MAX_NEW_LOCATIONS = 2


def _norm(s: Any) -> str:
    """名字/依据比对用归一化：去全部空白（中文句子无空格，英文两侧同规则即可）。"""
    return "".join(str(s or "").split())


def _resolve_names(names: List[Any], entities: List[Any]) -> Dict[str, Any]:
    """名字（含别名）→ {name: entity} 三级匹配（约束治理一期 2026-09-02）。

    LLM 报的参与者名常带修饰（「阿晚姑娘」「老王头」），纯精确匹配必然漏——
    漏掉的进 unresolved → participant_ids 缺失 → 在场推演断链（数据缺口 B6
    的写入侧根源）。三级依次收敛：
    1. 精确：strip 后等于名或别名（零误报）；
    2. 包含/被包含：双向子串且 ≥2 字（「阿晚姑娘」⊃「阿晚」；「阿晚」⊃「晚姑娘」
       这类短修饰也可挂上）；
    3. jieba token 边界：LLM 名的连续 token 拼接恰为实体名（防嵌词假阳性，
       canon_watch._name_in_text 同款纪律；jieba 缺失跳过此级）。
    同级多实体命中=歧义，不猜（宁缺勿滥，留作者在表单里改）。
    """
    table: Dict[str, List[Any]] = {}
    for e in entities:
        ent_names = [str(e.name or "").strip()]  # ⚠ 不可叫 names——会遮蔽同名参数
        ent_names += [str(a).strip() for a in (getattr(e, "aliases", None) or []) if a]
        for n in ent_names:
            if n:
                table.setdefault(n, []).append(e)

    def _unambiguous(cands: List[Any]) -> Optional[Any]:
        uniq = {str(e.id): e for e in cands}
        return next(iter(uniq.values())) if len(uniq) == 1 else None

    def _level2(reported: str) -> Optional[Any]:
        hits = [
            e for n, es in table.items()
            if len(n) >= 2 and (n in reported or reported in n)
            for e in es
        ]
        return _unambiguous(hits)

    def _level3(reported: str) -> Optional[Any]:
        try:
            import jieba as _jieba

            tokens = [t for t in _jieba.cut(reported) if t.strip()]
        except Exception:
            return None
        if not tokens:
            return None
        accs = set()
        for i in range(len(tokens)):
            acc = ""
            for j in range(i, min(i + 6, len(tokens))):
                acc += tokens[j]
                accs.add(acc)
        hits = [e for n, es in table.items() if len(n) >= 2 and n in accs for e in es]
        return _unambiguous(hits)

    out: Dict[str, Any] = {}
    for raw in names:
        n = str(raw or "").strip()
        if not n:
            continue
        ent = _unambiguous(table.get(n, [])) or _level2(n) or _level3(n)
        if ent is not None:
            out[str(raw)] = ent
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


def _collect_new_drafts(
    parsed: Dict[str, Any],
    text: str,
    entities: List[Any],
    locations: List[Any],
    resolved: Dict[str, Any],
    location_name: str,
) -> Tuple[List[Dict[str, str]], List[Dict[str, str]], List[str]]:
    """速记里名单外的名字 → 新实体/新地点草拟（关联式录入 2026-09-05）。

    LLM 只有提名权没有落笔权——每条过三道闸，任一不过整条丢弃：
    1. evidence 硬闸：归一化后必须是速记原文的子串且包含 name（逐字摘录失败=改写/编造）；
    2. 名单闸：与既有实体/地点（名+别名）、本次已解析参与者、发生地同名的跳过——
       同名说明匹配层漏了（该修匹配）或 LLM 违规重复报告（不该二次建档）；
    3. 形状闸：kind 白名单外 clamp 为 character；数量 clamp（实体 ≤4 / 地点 ≤2）。

    被闸掉的实体名回落 unresolved_names（诚实兜底不蒸发；地点不回落——
    地点下拉就在过目单上，且原文仍在 note 里）。
    """
    raw_text = _norm(text)
    known_names: set = set()
    for e in entities:
        for n in [e.name] + list(getattr(e, "aliases", None) or []):
            if n:
                known_names.add(_norm(n))
    known_locs = {_norm(l.name) for l in locations if l.name}
    claimed = {_norm(n) for n in resolved} | {_norm(location_name)}

    new_entities: List[Dict[str, str]] = []
    fallen: List[str] = []
    seen: set = set()
    for item in list(parsed.get("new_entities") or [])[:_MAX_NEW_ENTITIES * 2]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        ne, ee = _norm(name), _norm(evidence)
        ok = (
            ne and ne in ee and ee in raw_text
            and ne not in known_names and ne not in claimed and ne not in seen
        )
        if not ok:
            if ne and ne not in seen and ne not in known_names and ne not in claimed:
                fallen.append(name)
            continue
        seen.add(ne)
        kind = str(item.get("kind") or "").strip()
        new_entities.append({
            "name": name,
            "kind": kind if kind in _VALID_KINDS else "character",
            "evidence": evidence[:60],
        })
    new_entities = new_entities[:_MAX_NEW_ENTITIES]

    new_locations: List[Dict[str, str]] = []
    seen_loc: set = set()
    for item in list(parsed.get("new_locations") or [])[:_MAX_NEW_LOCATIONS * 2]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        ne, ee = _norm(name), _norm(evidence)
        ok = (
            ne and ne in ee and ee in raw_text
            and ne not in known_locs and ne not in known_names
            and ne not in claimed and ne not in seen_loc
        )
        if not ok:
            continue
        seen_loc.add(ne)
        new_locations.append({"name": name, "evidence": evidence[:60]})
    new_locations = new_locations[:_MAX_NEW_LOCATIONS]

    return new_entities, new_locations, fallen


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


async def _book_now_t(db: AsyncSession, book_id: str) -> int:
    """书级此刻（世界页速记无章节上下文时）：最大章锚 → 事件流最远处 → 0。

    与前端 futureEventWarning 的输入同源（resolve_narrative_time 的
    ②③④级是「某章视角」的降级；这里是整本书写到哪算哪）。
    """
    from sqlalchemy import func, select

    from backend.models import Chapter, WorldEvent

    row = await db.execute(
        select(func.max(Chapter.narrative_time)).where(
            Chapter.book_id == book_id, Chapter.narrative_time.isnot(None)
        )
    )
    nt = row.scalar()
    if nt is not None:
        return int(nt)
    row = await db.execute(
        select(func.max(WorldEvent.time_start)).where(WorldEvent.book_id == book_id)
    )
    return int(row.scalar() or 0)


async def parse_event_text(
    db: AsyncSession,
    book_id: str,
    chapter: Any,
    text: str,
) -> Dict[str, Any]:
    """一句话速记 → {draft, confidence, new_entities, new_locations}。

    失败返回空草稿 + confidence=none。chapter=None（世界页入口）用书级此刻。
    """
    repo = WorldRepository(db)
    entities = await repo.entities.list_by_book(book_id)
    locations = await repo.locations.list_by_book(book_id)
    # 空名册不再早退（2026-09-05 关联式录入）：新书最需要速记建世界——
    # 名单为空时解析照跑，句子里所有名字自然全部进 new_entities
    if chapter is not None:
        t = (await resolve_narrative_time(db, chapter)).t
    else:
        t = await _book_now_t(db, book_id)

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
        return {
            "draft": _empty_draft(t),
            "confidence": "none",
            "new_entities": [],
            "new_locations": [],
        }

    draft = normalize_draft(parsed, t, entities, locations)
    new_entities, new_locations, fallen = _collect_new_drafts(
        parsed, text, entities, locations,
        _resolve_names(list(parsed.get("participants") or []), entities),
        draft["location_name"],
    )
    # P1-2 收口（审查 2026-09-05）：LLM 常把名单外名字同时报进 participants 和
    # new_entities——已采纳为新建草稿的名字从 unresolved_names 剔除（勾选行已在
    # 过目单上，双显示让作者困惑哪条生效）。被闸的 fallen 保留（诚实兜底）。
    adopted = {_norm(d["name"]) for d in new_entities} | {_norm(d["name"]) for d in new_locations}
    if adopted:
        draft["unresolved_names"] = [
            n for n in draft["unresolved_names"] if _norm(n) not in adopted
        ]
    if fallen:
        seen_unresolved = {_norm(n) for n in draft["unresolved_names"]}
        draft["unresolved_names"] = draft["unresolved_names"] + [
            n for n in fallen if _norm(n) not in seen_unresolved
        ]
    if draft["event_type"] == "custom" and not draft["participant_ids"]:
        confidence = "low"
    elif draft["participant_ids"] or draft["location_id"]:
        confidence = "high"
    else:
        confidence = "low"
    return {
        "draft": draft,
        "confidence": confidence,
        "new_entities": new_entities,
        "new_locations": new_locations,
    }


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

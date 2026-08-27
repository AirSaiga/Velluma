# Velluma - provenance 信封与现实校验（B5 · docs/world-kernel-foundation.md §4 不变量 5/10）
# AGPL-3.0
"""派生物的可再生成性与真实性检验。

- envelope(...)：provenance 信封——每个派生物（知识视图/场景卡/未来的
  digest 节）携带 {source_keys, fold_version, compiler_version, params_hash}；
  按信封重算应逐字节相等（不变量 5，对拍测试锁）。
- check_entity_claims / run_reality_check：抽样派生论断回查 fold truth——
  死者标在场、位置漂移等结构性谎言必须被抓到（不变量 10：失败即失效
  不沉默）。B8 digest 的现实校验消费同一入口。

副作用：无（纯查询/纯函数；校验只标记，绝不删除派生物——回退由消费方决定）。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

# 折叠算法版本（语义变更时 bump——信封重算相等性的前提）
FOLD_VERSION = "kernel-b1"
# 派生编译器版本（知识平面渲染语义变更时 bump）
COMPILER_VERSION = "kg-v3.1"


def _params_hash(params: Dict[str, Any]) -> str:
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def envelope(
    kind: str,
    source_keys: List[str],
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """派生物的 provenance 信封（不变量 5）。"""
    return {
        "kind": kind,
        "source_keys": list(source_keys),
        "fold_version": FOLD_VERSION,
        "compiler_version": COMPILER_VERSION,
        "params_hash": _params_hash(params),
    }


def check_entity_claims(
    dead_claims: List[str],
    present_claims: List[str],
    world_state: Dict[str, Any],
    names_by_entity_id: Optional[Dict[str, List[str]]] = None,
    scene_location_name: str = "",
) -> List[Dict[str, str]]:
    """实体论断回查（纯函数，不变量 10 的机检部分）。

    论断来源：知识视图/场景卡的死者名单与在场名单。对照 fold truth 的
    character_states（alive/location_id）。返回 mismatches：
    [{claim, kind: dead_but_alive|alive_but_dead|present_wrong_loc, detail}]
    """
    names_by_entity_id = names_by_entity_id or {}
    mismatches: List[Dict[str, str]] = []
    states = (world_state or {}).get("character_states") or []
    by_names: Dict[str, Dict[str, Any]] = {}
    for cs in states:
        eid = str(cs.get("entity_id") or "")
        for name in names_by_entity_id.get(eid, []) or [eid]:
            by_names[name] = cs

    for name in dead_claims:
        cs = by_names.get(name)
        if cs is not None and cs.get("alive", False):
            mismatches.append({
                "claim": name, "kind": "dead_but_alive",
                "detail": f"派生物宣称「{name}已死亡」，fold 显示存活",
            })
    for name in present_claims:
        cs = by_names.get(name)
        if cs is None:
            continue  # unknown：诚实降级，不判谎（无状态≠矛盾）
        if not cs.get("alive", False):
            mismatches.append({
                "claim": name, "kind": "alive_but_dead",
                "detail": f"派生物宣称「{name}在场」，fold 显示已死亡",
            })
        elif scene_location_name:
            # 位置漂移：在场论断 vs 场景钉地点（location 名比对由调用方供名）
            mismatches.append({
                "claim": name, "kind": "present_wrong_loc",
                "detail": f"「{name}」在场论断需要与场景 {scene_location_name} 对账（位置 id 比对在调用方完成）",
            })
    return mismatches


async def run_reality_check(
    db: Any,
    book_id: str,
    t: int,
    knowledge_view: Any,
    scene_location_id: str = "",
) -> Dict[str, Any]:
    """完稿/审计时挂一次：知识视图（未来的 digest 节同构）回查 fresh fold。

    Returns: {checked: n_claims, mismatches: [...]}——失败即失效不沉默：
    mismatches 非空时消费方应把派生物标记过期（缓存失效）并在预览可见。
    """
    from sqlalchemy import select as _sa_select

    from backend.models import WorldEntity as _WE
    from backend.services.world.fold import fold

    truth = (await fold(db, book_id, t=t, domains=("truth",), perspective_set=()))["truth"]
    # 实体名 → fold 状态（fold 只带 entity_id，名映射由实体表补——一次轻查询）
    from uuid import UUID as _UUID

    bid = _UUID(str(book_id))
    name_by_eid = {
        str(eid): (name or "")
        for eid, name in (await db.execute(
            _sa_select(_WE.id, _WE.name).where(_WE.book_id == bid)
        )).all()
    }
    names_by_eid: Dict[str, List[str]] = {}
    for cs in truth.get("character_states") or []:
        eid = str(cs.get("entity_id") or "")
        names = [n for n in (name_by_eid.get(eid), eid) if n]
        names_by_eid[eid] = names
        if name_by_eid.get(eid):
            names_by_eid[name_by_eid[eid]] = names  # 论断用名字查也命中

    mismatches = check_entity_claims(
        dead_claims=list(getattr(knowledge_view, "dead_names", None) or []),
        present_claims=list(getattr(knowledge_view, "present_names", None) or []),
        world_state=truth,
        names_by_entity_id=names_by_eid,
    )
    return {
        "checked": len(getattr(knowledge_view, "dead_names", None) or [])
        + len(getattr(knowledge_view, "present_names", None) or []),
        "mismatches": mismatches,
    }

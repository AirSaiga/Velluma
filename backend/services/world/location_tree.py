# Velluma - 地点树工具（内部构造 · docs/reports/location-interior.md）
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
地点层级（parent_id 自引用树）的纯函数工具，路由 / 速记解析 / prompt 共用。

不变量（渲染契约）：上图权 = parent_id IS NULL——有父级的地点一律不上地图，
只在父地点详情抽屉与地点列表缩进子树中呈现。

前端 engine/locationTree.ts 与本文件同构（改口径两侧同步 + 各配单测）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

_PATH_SEP = "·"


def _key(loc: Any) -> str:
    """对象键：id 优先；无 id（测试 mock 造型）退内存地址——只求唯一，不入数据。"""
    v = getattr(loc, "id", None)
    return str(v) if v is not None else f"@{id(loc)}"


def locations_by_id(locations: Iterable[Any]) -> Dict[str, Any]:
    return {_key(l): l for l in locations}


def children_index(locations: Iterable[Any]) -> Dict[str, List[Any]]:
    """parent_id → 直接子级列表（保持传入顺序；无父级不入表）。"""
    out: Dict[str, List[Any]] = {}
    for l in locations:
        pid = getattr(l, "parent_id", None)
        if pid:
            out.setdefault(str(pid), []).append(l)
    return out


def collect_subtree_ids(locations: List[Any], root_id: str) -> List[str]:
    """以 root_id 为根的整棵子树 id 列表（含根，BFS 父前子后）。

    根不在列表中 → 空列表（调用方据此 404）。顺序保证父先子后——
    删除按序执行时 DB 的 ondelete=SET NULL 不会把未删子级悬空成顶层孤儿。
    """
    by_id = locations_by_id(locations)
    if root_id not in by_id:
        return []
    kids = children_index(locations)
    out: List[str] = []
    queue = [root_id]
    while queue:
        cur = queue.pop(0)
        out.append(cur)
        queue.extend(_key(c) for c in kids.get(cur, []))
    return out


def location_path(loc: Any, by_id: Dict[str, Any]) -> str:
    """地点全路径「统合局基地·B2 拘留层」（顶层 = 裸名）。

    防环：已见 id 不再向上爬（脏数据护栏，正常树不触发）。
    速记解析与 prompt 名单用它消歧——两个基地各有一个「拘留室」时
    全路径可精确指认，裸名只作兜底。
    """
    parts: List[str] = [loc.name or ""]
    seen = {_key(loc)}
    cur = loc
    while True:
        pid = getattr(cur, "parent_id", None)
        if not pid:
            break
        pid = str(pid)
        if pid in seen:
            break
        parent = by_id.get(pid)
        if parent is None:
            break
        parts.append(parent.name or "")
        seen.add(pid)
        cur = parent
    return _PATH_SEP.join(reversed(parts))


def ancestor_chain(by_id: Dict[str, Any], loc_id: str) -> List[Any]:
    """从 loc_id 自内向外爬到顶层 [自身, 父, 祖父, ...]；缺失/环 → 截断。"""
    chain: List[Any] = []
    seen: set = set()
    cur = by_id.get(loc_id)
    while cur is not None:
        key = _key(cur)
        if key in seen:
            break
        seen.add(key)
        chain.append(cur)
        pid = getattr(cur, "parent_id", None)
        cur = by_id.get(str(pid)) if pid else None
    return chain


def scene_scope_ids(locations: List[Any], scene_loc_id: str) -> set:
    """场景作用域（docs/reports/location-interior.md 二期）：场景地点自身 + 全部祖先 id。

    场景钉到房间时，钉在基地（祖先）的角色也算在场——「在建筑物里」是
    「在这个房间的场景里」的合理上界。消费方：world_bridge 在场提权、
    knowledge_plane present 判定（两侧同口径）。
    空 id → 空集（无场景钉=旧精确匹配行为逐字节不变）。
    """
    if not scene_loc_id:
        return set()
    by_id = locations_by_id(locations)
    return {_key(l) for l in ancestor_chain(by_id, scene_loc_id)}

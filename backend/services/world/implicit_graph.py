# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""事件流隐式图谱投影器（原型实装 · docs/reports/implicit-graph-projection-feasibility.md §3）。

定位：确定性的结构化历史提取引擎——以在场实体（onstage）为根，从
world_events 事件流投影 1~2 跳关联子图，产出「事件卡（超边原子）」。
零 LLM、零 IO（纯函数，事件/实体由调用方装入）；与 RAG 散文回响分工：
本通道给结构化事实因果，RAG 给 prose 质感，提及扫描兜稀疏。

防爆纪律（红线）：
- 超边表示：多参与者事件（battle 十人混战）只产出 1 张 EventCard，
  绝不展开 N² 点对连线；
- 三道帽：每根 ≤ per_root_cards 张近史卡 / 2 跳每成员 ≤1 张且总数 ≤
  second_hop_cards_cap / 全局节点 ≤ node_cap；
- 2 跳只走 MAJOR_TYPES ∪ 近 90 天窗（普通 custom 绝不外扩——主角挂三百
  事件时 custom 外扩=全书半数节点进图）。

时态纪律（与 fold 同构）：只看 time_start <= t 且未被 supersede 的事件，
按 (time_start, sequence_num) 倒序取「最新优先」——同一成员的最近一张卡
即当前有效历史（last-write-wins 在边集合上的推广）。

年月日换算与前端 engine/timeFormat.ts 同构（365 日/年、30 日/月、创世
元年、年末余 5 天如实记 13 月）——prompt 里的时刻与世界页时间轴所见一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

# 2 跳外扩的重大类型（普通 custom/move 等不外扩）
MAJOR_TYPES = frozenset({"death", "battle", "territory_change", "destroy", "coronation"})
# 2 跳近窗：非重大类型若发生在 |t - time_start| <= 90 天内也允许外扩
SECOND_HOP_RECENT_WINDOW_DAYS = 90
# note 摘要截断（事件卡因果描述的人话上限）
NOTE_EXCERPT_CHARS = 40

# 事件类型显示标签（与前端 eventTemplates.ts 同词根——标题回退链的显示侧）
EVENT_TYPE_LABELS: Dict[str, str] = {
    "birth": "出生",
    "death": "死亡",
    "move": "移动",
    "battle": "战役",
    "territory_change": "疆域变更",
    "found": "建立",
    "destroy": "毁灭",
    "alliance": "结盟",
    "war_declare": "宣战",
    "coronation": "即位",
    "custom": "自定义",
}


# ============================================================
# 数据契约（docs/reports/implicit-graph-projection-feasibility.md §3.1）
# ============================================================

@dataclass
class EventCard:
    """事件卡（超边原子）：包含 11 类事件的结构化时空胶囊。

    永不拆成点对边——一张卡引用 N 个参与者，这是防爆的本质。
    """

    event_id: str
    event_type: str            # battle / move / death / custom 等 11 类
    title: str                 # 事件标题（自拟优先，空回退类型标签）
    time_start: int            # 叙事时刻（连续日计数，与历法解耦）
    note_excerpt: str          # 核心因果摘要（截 ≤40 字）
    participant_ids: List[str] = field(default_factory=list)  # 超边参与者
    location_id: Optional[str] = None


@dataclass
class SubgraphNode:
    """入图节点。"""

    entity_id: str
    name: str
    hop: int                   # 0=在场根 / 1=共现邻 / 2=重大历史带出
    why: str                   # 入图理由（人话，如「第 217 天与林尘共同经历 战役」）


@dataclass
class SubgraphSlice:
    """在场连通子图完整切片（knowledge_plane 事件卡通道的原料）。"""

    roots: List[str] = field(default_factory=list)     # 传入的 onstage 实体 id
    nodes: List[SubgraphNode] = field(default_factory=list)  # 入图实体（上限 node_cap）
    cards: List[EventCard] = field(default_factory=list)     # 重大事件卡（按时间倒序）
    generated_at_t: int = 0     # 投影时刻 t（前缀签名的组成键）


# ============================================================
# 内部工具
# ============================================================

def _entity_name(entities_by_id: Dict[str, Any], eid: str) -> str:
    ent = entities_by_id.get(str(eid))
    if ent is None:
        return str(eid)[:8]
    return str(getattr(ent, "name", "") or "").strip() or str(eid)[:8]


def _participants(ev: Any) -> set:
    """事件的全部实体引用（超边成员）：一等列 + payload 类型键，纯字典解析。

    地点不作为节点（另有 location_id 承载）；faction_id 同时是一等列与
    territory_change payload 键，取并集天然去重。
    """
    ids: set = set()
    for pid in (getattr(ev, "participant_ids", None) or []):
        ids.add(str(pid))
    for fid in (getattr(ev, "faction_ids", None) or []):
        ids.add(str(fid))
    payload = getattr(ev, "payload", None) or {}
    if isinstance(payload, dict):
        for key in ("character_id", "character_ids", "faction_id", "target_id"):
            v = payload.get(key)
            if isinstance(v, (list, tuple)):
                ids.update(str(x) for x in v)
            elif v:
                ids.add(str(v))
    return ids


def _superseded_ids(events: Iterable[Any]) -> set:
    """被修订链取代的事件 id 集（读侧防御——repo 层已过滤，此处双保险）。"""
    return {
        str(ev.supersedes)
        for ev in events
        if getattr(ev, "supersedes", None)
    }


def _display_title(ev: Any) -> str:
    """标题回退链：自拟 title > 类型标签 > 原文 event_type（同前端 eventDisplayName 口径）。"""
    title = str(getattr(ev, "title", "") or "").strip()
    if title:
        return title
    etype = str(getattr(ev, "event_type", "") or "")
    return EVENT_TYPE_LABELS.get(etype, etype)


def _card(ev: Any) -> EventCard:
    note = str(getattr(ev, "note", "") or "").strip()
    loc = getattr(ev, "location_id", None)
    return EventCard(
        event_id=str(getattr(ev, "id", "")),
        event_type=str(getattr(ev, "event_type", "") or ""),
        title=_display_title(ev),
        time_start=int(getattr(ev, "time_start", 0) or 0),
        note_excerpt=note[:NOTE_EXCERPT_CHARS],
        participant_ids=sorted(_participants(ev)),
        location_id=str(loc) if loc else None,
    )


def _format_day(t: int) -> str:
    """连续日 → 第N年M月D日（与前端 timeFormat.ts 同构：365/30、创世元年、
    年末余 5 天记 13 月——prompt 时刻与世界页时间轴同一张脸）。"""
    remaining = max(0, int(t))
    year = remaining // 365 + 1
    remaining -= (year - 1) * 365
    month = remaining // 30 + 1
    day = remaining - (month - 1) * 30 + 1
    return f"第{year}年{month}月{day}日"


# ============================================================
# 核心投影算法
# ============================================================

def project_active_subgraph(
    events: List[Any],
    entities_by_id: Dict[str, Any],
    roots: List[str],
    t: int,
    max_hops: int = 2,
    per_root_cards: int = 6,
    second_hop_cards_cap: int = 6,
    node_cap: int = 40,
) -> SubgraphSlice:
    """事件流 → 在场连通子图（纯函数，零 LLM 零 IO）。

    Args:
        events: 全书事件（ORM 行或鸭子类型桩均可——只读 id/event_type/
            time_start/sequence_num/participant_ids/faction_ids/payload/
            note/title/location_id/supersedes）。
        entities_by_id: 实体名册（id → 有 .name 的对象），节点命名与 why 用。
        roots: 在场实体 id（onstage_projection 的输出——下层拓扑提供者定位，
            根集语义=执法名单，本函数不重算在场）。
        t: 叙事时刻（只看 time_start <= t 的历史）。
        max_hops: 2=完整（1 跳共现+2 跳重大历史）；1=只做 1 跳。
        per_root_cards: 每根近史卡配额（1 跳总帽 = per_root_cards × 根数）。
        second_hop_cards_cap: 2 跳卡片总数帽。
        node_cap: 全局节点帽。

    Returns:
        SubgraphSlice：cards 按时间倒序；nodes 按 roots → hop1 → hop2 序，
        截断在 node_cap；无根或无历史 → 空切片（零变化契约的原料）。
    """
    root_set = {str(r) for r in roots if r}
    slice_ = SubgraphSlice(roots=sorted(root_set), generated_at_t=int(t))
    if not root_set:
        return slice_

    superseded = _superseded_ids(events)
    live = sorted(
        (ev for ev in events
         if int(getattr(ev, "time_start", 0) or 0) <= int(t)
         and str(getattr(ev, "id", "")) not in superseded),
        key=lambda ev: (int(getattr(ev, "time_start", 0) or 0),
                        int(getattr(ev, "sequence_num", 0) or 0)),
        reverse=True,  # 最新优先
    )

    cards: List[EventCard] = []
    card_event_ids: set = set()

    # ---- 1 跳（在场共现）：含任一 root 的事件，最近优先 ----
    hop1_order: List[str] = []
    hop1_set: set = set()
    why_hop1: Dict[str, str] = {}
    first_cards_cap = max(1, per_root_cards * len(root_set))
    for ev in live:
        if len(cards) >= first_cards_cap:
            break
        parts = _participants(ev)
        hit_roots = parts & root_set
        if not hit_roots:
            continue
        card = _card(ev)
        cards.append(card)
        card_event_ids.add(card.event_id)
        label = EVENT_TYPE_LABELS.get(card.event_type, card.event_type)
        root_name = _entity_name(entities_by_id, sorted(hit_roots)[0])
        for pid in parts - root_set:
            if pid not in hop1_set:
                hop1_set.add(pid)
                hop1_order.append(pid)
                why_hop1[pid] = f"第{card.time_start}天与{root_name}共同经历{label}"

    # ---- 2 跳（重大历史与近窗）：含 hop1 成员的事件外扩 ----
    hop2_order: List[str] = []
    hop2_set: set = set()
    why_hop2: Dict[str, str] = {}
    if max_hops >= 2 and hop1_set:
        attributed: set = set()  # 已带出过 2 跳卡的 hop1 成员（每成员至多 1 张）
        taken = 0
        for ev in live:
            if taken >= second_hop_cards_cap:
                break
            if str(getattr(ev, "id", "")) in card_event_ids:
                continue
            if (str(getattr(ev, "event_type", "") or "") not in MAJOR_TYPES
                    and abs(int(t) - int(getattr(ev, "time_start", 0) or 0)) > SECOND_HOP_RECENT_WINDOW_DAYS):
                continue
            parts = _participants(ev)
            hit_members = parts & hop1_set
            if not hit_members or hit_members <= attributed:
                continue
            card = _card(ev)
            cards.append(card)
            card_event_ids.add(card.event_id)
            attributed |= hit_members
            label = EVENT_TYPE_LABELS.get(card.event_type, card.event_type)
            member_name = _entity_name(entities_by_id, sorted(hit_members)[0])
            for pid in parts - root_set - hop1_set:
                if pid not in hop2_set:
                    hop2_set.add(pid)
                    hop2_order.append(pid)
                    why_hop2[pid] = f"第{card.time_start}天与{member_name}关联（{label}）"
            taken += 1

    # ---- 节点组装（roots → hop1 → hop2，全局截断） ----
    nodes: List[SubgraphNode] = []
    for rid in sorted(root_set):
        nodes.append(SubgraphNode(
            entity_id=rid, name=_entity_name(entities_by_id, rid),
            hop=0, why="在场（投影根）",
        ))
    for pid in hop1_order:
        nodes.append(SubgraphNode(
            entity_id=pid, name=_entity_name(entities_by_id, pid),
            hop=1, why=why_hop1.get(pid, ""),
        ))
    for pid in hop2_order:
        nodes.append(SubgraphNode(
            entity_id=pid, name=_entity_name(entities_by_id, pid),
            hop=2, why=why_hop2.get(pid, ""),
        ))
    slice_.nodes = nodes[:max(1, node_cap)]

    # 卡片统一按时间倒序（1/2 跳合并后重排——注入序列=新→旧）
    cards.sort(key=lambda c: c.time_start, reverse=True)
    slice_.cards = cards
    return slice_


# ============================================================
# 提示词格式化器
# ============================================================

def format_subgraph_for_prompt(
    slice_: SubgraphSlice,
    entities_by_id: Optional[Dict[str, Any]] = None,
) -> str:
    """SubgraphSlice → 紧凑注入文本块（时间前缀 + 卡片行）。

    零变化契约：cards 为空返回空串（无标题无残留）。note 缺失时回退
    参与者名单（entities_by_id 提供时解析真名，否则 id 短码）。
    """
    if not slice_.cards:
        return ""
    lines = ["# 在场近史与因果（仅限在场者参与的历史事实）"]
    for c in slice_.cards:
        body = c.note_excerpt
        if not body and entities_by_id is not None:
            names = "、".join(_entity_name(entities_by_id, p) for p in c.participant_ids[:6])
            body = f"涉及：{names}" if names else ""
        if not body:
            body = f"涉及：{len(c.participant_ids)} 方（无记述）"
        lines.append(f"- [{_format_day(c.time_start)}·{c.title}] {body}")
    return "\n".join(lines)

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 在场推演的词法兜底（约束治理一期 · 数据缺口 B6）
"""
世界状态折叠后的读侧增强：事件缺结构化链接（participant_ids 空、
battle/custom 不改世界状态）时，从事件 note 的实体名命中补在场。

背景（2026-09-02，流光穿帮事故的深层土壤）：折叠核心
compute_world_state_from_events 只认 birth/move 两类事件定位，实例书事件
participant_ids 全空 → character_states 恒空 → 在场实体档案块永远空，
模型拿不到「谁在此刻在场」的事实。schema 校验保形状不保完整性——完整性
靠「词法兜底（本模块）+ 切片 badge（据正文推断）+ 回填脚本」三角。

纪律（导师审查定档）：
- 只填**无任何 character_state** 的实体（有状态者以折叠为准，不覆盖）；
- 死者不吃词法在场（任何 death 事件引用过的实体跳过——宁可缺席不可复活）；
- 只取 ≤t 且带 location_id 的事件；同名命中多实体（歧义）不填；同名多事件
  取 sequence_num 最新；
- **匹配判据=token 边界**（2026-09-17 加固，与写入侧 event_parser 三级匹配
  同款纪律：连续 token 拼接恰为该名才命中，嵌词「流光溢彩」不再凭空造在场；
  jieba 缺失退子串柔性红线）；名表注册进 jieba 词典（jieba_lexicon），
  专名恒为单 token 后命中稳定——进程级幂等副作用，不破函数的结果确定性；
- **不回写 participant_ids**（append-only 事实源保持纯洁，只读面 enrich）；
- 命中标 presence_source="lexical"——切片条渲染「据正文推断」badge（补录
  建议的载体），台账记数据缺口（event-participant-gap 由回填脚本/调用方计）。

幂等：对已增强的 state 重复调用是 no-op（缺失集为空）。纯函数零 IO（jieba
词典注册为进程级幂等副作用，不读写外部状态）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from backend.services.context.scene_visibility import _token_accs
from backend.services.world.jieba_lexicon import register_entity_terms

_WS_RE = re.compile(r"\s+")


def _norm_note(text: str) -> str:
    return _WS_RE.sub("", str(text or ""))


def enrich_state_with_lexical_presence(
    state: Dict[str, Any],
    events: List[Any],
    entities: List[Any],
    locations_by_id: Dict[str, Any],
    t: int,
    on_event=None,
) -> Dict[str, Any]:
    """fold 之后组合调用：给无状态实体从事件 note 词法命中补在场（原地修改）。

    Args:
        state: compute_world_state_from_events 的返回 dict（就地增强）。
        events: 全部事件（函数内部按 ≤t 与 location_id 过滤）。
        entities: 世界实体列表（读 name/aliases/entity_type/id）。
        locations_by_id: 地点表（算 position 坐标）。
        t: 叙事时刻。
        on_event: (constraint_id, outcome, reason, detail) 回调——每个词法
            补填落一条 event-participant-gap 事件（数据缺口可度量，导师审查
            P1-3：「违规是需求信号」的数据层对偶）；None = 不埋（纯函数性）。
    """
    try:
        if not isinstance(state, dict) or not entities:
            return state
        states = state.setdefault("character_states", [])
        have = {str(cs.get("entity_id")) for cs in states if isinstance(cs, dict)}

        # 名 → 实体（名+别名）；命中多实体=歧义，不填（宁缺勿滥）。
        # 只收 character——在场语义是「谁在这」（P2-8：势力/资产命中会稀释
        # character_states 语义；资产在场由 slice/knowledge_plane 各自口径处理）。
        name_table: Dict[str, List[Any]] = {}
        for e in entities:
            eid = str(getattr(e, "id", "") or "")
            if not eid or eid in have:
                continue
            if str(getattr(e, "entity_type", "") or "") != "character":
                continue
            names = [str(getattr(e, "name", "") or "").strip()]
            names += [str(a).strip() for a in (getattr(e, "aliases", None) or []) if str(a).strip()]
            for n in names:
                if len(n) >= 2:
                    name_table.setdefault(n, []).append(e)
        unambiguous = {n: ents[0] for n, ents in name_table.items() if len(ents) == 1}
        if not unambiguous:
            return state

        # 专名注入 jieba 词典（2026-09-17）：名表恒为单 token 后 token 边界
        # 命中稳定；幂等进程级副作用，失败静默（jieba 缺失时匹配退子串）
        register_entity_terms(entities)

        # 死者排除：任何 death 事件引用过的实体（≤t 或未来都不复活）
        dead_ids = set()
        for e in events:
            if getattr(e, "event_type", "") == "death":
                cid = (getattr(e, "payload", None) or {}).get("character_id")
                if cid:
                    dead_ids.add(str(cid))

        # 候选事件：≤t、带 location_id、note 非空；按 sequence_num 降序（同名取最新）
        candidate_events = sorted(
            [
                e for e in events
                if (getattr(e, "time_start", None) is not None and e.time_start <= t
                    and getattr(e, "location_id", None)
                    and str(getattr(e, "note", "") or "").strip())
            ],
            key=lambda e: e.sequence_num or 0,
            reverse=True,
        )

        def _coord(loc_id: str):
            loc = locations_by_id.get(loc_id)
            if loc is not None and getattr(loc, "coord_x", None) is not None and getattr(loc, "coord_y", None) is not None:
                return [loc.coord_x, loc.coord_y]
            return None

        for ev in candidate_events:
            note = _norm_note(getattr(ev, "note", ""))
            # token 边界判据：每事件切一次词查整张名表；None=jieba 缺失退子串
            accs = _token_accs(note)
            loc_id = str(ev.location_id)
            for name, ent in unambiguous.items():
                eid = str(getattr(ent, "id", ""))
                if eid in have or eid in dead_ids:
                    continue
                if accs is not None:
                    if name not in accs:
                        continue
                elif name not in note:
                    continue
                states.append({
                    "entity_id": eid,
                    "location_id": loc_id,
                    "position": _coord(loc_id),
                    "alive": True,
                    "label": "据正文推断",
                    "last_event_id": str(getattr(ev, "id", "") or ""),
                    "presence_source": "lexical",
                })
                have.add(eid)
                if on_event is not None:
                    try:
                        on_event("event-participant-gap", "hit", "lexical_presence_fill",
                                 {"entity_id": eid, "name": name, "event_id": str(getattr(ev, "id", "") or "")})
                    except Exception:
                        pass  # 埋点绝不阻塞兜底
        return state
    except Exception:
        return state  # 读侧兜底绝不阻塞推演主链

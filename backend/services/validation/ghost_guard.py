# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

from __future__ import annotations

"""
幽灵草稿上屏前轻量前置校验（P5 批次 4 C1，docs/foundation-hardening.md §5.1）。

职责：
- stitch-ghost 完整文本生成后、GHOST_DONE 帧前跑纯算法快检（<10ms，零 LLM）
- 四类疑点（宁漏勿误，全部只提示不拦截——§9 红线「提示不拦截」）：
  1. dead_speak：新文本实体名（含别名）命中 world_state 里 alive=False 的角色
     （死者开口；回忆/闪回属合法用法，故只提示）
  2. canon_leak：canon_private_labels（Canon [private] 标签词，settings_bundle
     正则抽取，A1 同源）在正文子串命中
  3. secret_leak：A1 私有通道 character_secrets 文本的 ≥4 字连续片段
     （按标点/换行切段）在正文子串命中——整段复现才算命中，宁可漏报
  4. cliche_hit：禁忌面命中（任务包 A）——bundle.prohibitions
     （services/style/prohibitions.py 四源合并）非空时对 text 跑 finditer，
     任一 blocker 或总命中数 ≥ GHOST_GUARD_CLICHE_MIN_TOTAL 报一条 warning
     （命中 pattern 去重前 5 进 detail）

输入两种形态：直接传 SettingsBundle（stitch 路由在用），或显式传
canon_private_labels / character_secrets / world_state + entity_names_by_id
（单测与未来复用方）。无世界数据/无私有/无 canon 时返回空列表，任何内部
异常吞掉返回空列表——快检绝不阻塞生成（柔性信号，非闸门）。

副作用：无（纯函数）。警示：本模块绝不调 LLM / 绝不写库 / 绝不抛异常。
"""

import re
from typing import Any, Dict, List, Optional

# 实体名/别名最短长度（1 字名在中文正文里子串误报率不可接受，宁漏勿误）
NAME_MIN_CHARS = 2
# secret 短语最短长度（spec：≥4 字连续片段；太短的常见词会大面积误报）
SECRET_PHRASE_MIN_CHARS = 4
# secret 短语匹配上限（超长片段要求整段复现反而永不命中；截前 20 字 =
# 仍要求 20 字逐字复现才报，保守档）
SECRET_PHRASE_MAX_CHARS = 20
# warnings 总量上限（防 DONE 帧膨胀；同一触发词只报一次）
MAX_WARNINGS = 10
# cliche_hit 总命中数下限（任务包 A）：静态反 AI 词在正常叙事里也会出现，
# 单发命中不报；任一 blocker 严重级的条目命中则立即报（不受此阈值调节）
GHOST_GUARD_CLICHE_MIN_TOTAL = 3
# cliche_hit 命中 pattern 去重上报上限（detail 列表长度）
GHOST_GUARD_CLICHE_MAX_PATTERNS = 5

# secret 文本切段：按换行与中英文标点/空白切成连续片段（标签前缀如「背景：」
# 的「背景」二字低于 4 字门槛自然淘汰，剩余即关键短语）
_SECRET_SPLIT_RE = re.compile(r"[\s，。；：:、！？!?,.;~—…·\"'「」『』()（）\[\]{}<>|-]+")


def check_ghost_text(
    text: str,
    bundle: Optional[Any] = None,
    *,
    canon_private_labels: Optional[List[str]] = None,
    character_secrets: Optional[List[Dict[str, str]]] = None,
    world_state: Optional[Dict[str, Any]] = None,
    entity_names_by_id: Optional[Dict[str, List[str]]] = None,
    canon_node_ids_by_label: Optional[Dict[str, str]] = None,
    visible_names: Optional[List[str]] = None,
    all_names: Optional[List[str]] = None,
    on_event=None,
) -> List[Dict[str, str]]:
    """幽灵草稿快检：返回 warnings: [{kind, span_text, message}]。

    Args:
        text: 生成的幽灵正文（完整文本，含 stitch 拼回的碎片）
        bundle: SettingsBundle（优先；其 hard_constraints/character_secrets/
            world_state/entities 自动取用）
        canon_private_labels: 显式覆盖——Canon [private] 标签词表
        character_secrets: 显式覆盖——A1 私有通道 [{name, text}]
        world_state: 显式覆盖——t 时刻推演快照（character_states 的 alive）
        entity_names_by_id: 显式覆盖——实体 id → [主名, *别名]（dead_speak 用）
        visible_names: 在场/提及白名单（scene_visible_proper_nouns 同一产物，
            路由透传不重算）；None = 第五检不跑（零变化契约）
        all_names: 书级实体+资产名全集（第五检候选宇宙；bundle 形态自动取用）
        on_event: 约束事件回调 (constraint_id, outcome, reason, detail)——
            out_of_scene 命中/闪回豁免的台账埋点；None = 不埋

    Returns:
        [{kind: dead_speak|canon_leak|secret_leak|cliche_hit|out_of_scene,
        span_text, message, detail?, local_only?}], 上限 MAX_WARNINGS；
        无输入/无命中/内部异常一律空列表（零报错契约）。detail 仅
        cliche_hit/out_of_scene 携带；out_of_scene 带 local_only=True（shadow
        出生——路由过滤后不进 GHOST_DONE 帧，只落 constraint_events）。
    """
    try:
        if not text or not isinstance(text, str):
            return []

        # ---- bundle 形态：抽参（显式参数优先，允许局部覆盖）----
        if bundle is not None:
            if canon_private_labels is None:
                canon_private_labels = _bundle_canon_labels(bundle)
            if character_secrets is None:
                character_secrets = _bundle_secrets(bundle)
            if world_state is None:
                world_state = getattr(bundle, "world_state", None) or None
            if entity_names_by_id is None:
                entity_names_by_id = _bundle_entity_names(bundle)

        warnings: List[Dict[str, Any]] = []
        seen_spans: set = set()

        def _hit(kind: str, span: str, message: str, detail: Any = None) -> None:
            key = (kind, span)
            if key in seen_spans or len(warnings) >= MAX_WARNINGS:
                return
            seen_spans.add(key)
            warning: Dict[str, Any] = {"kind": kind, "span_text": span, "message": message}
            if detail is not None:
                warning["detail"] = detail
            warnings.append(warning)

        def _hit_dict(warning: Dict[str, Any]) -> None:
            """带扩展字段（如 canon_node_id）的命中——去重/上限纪律同 _hit。"""
            key = (warning.get("kind"), warning.get("span_text"))
            if key in seen_spans or len(warnings) >= MAX_WARNINGS:
                return
            seen_spans.add(key)
            warnings.append(warning)

        # ---- 1. dead_speak：死者名（含别名）出现 ----
        for name in _dead_entity_names(world_state, entity_names_by_id):
            if len(name) >= NAME_MIN_CHARS and name in text:
                _hit(
                    "dead_speak", name,
                    f"「{name}」在此刻的世界状态中已死亡，却在续写中出现"
                    f"（若是有意的回忆/闪回可忽略）",
                )

        # ---- 2. canon_leak：私有标签词出现（B3 命题精确化：携带 canon_node_id，
        # 调用方经 canon_node_ids_by_label 供 label→命题注册表 id 的映射——
        # 泄密疑点从「词命中」升格为「命题命中」，B9 认知浮现消费同一证据链）----
        for label in (canon_private_labels or []):
            label = (label or "").strip()
            if len(label) >= NAME_MIN_CHARS and label in text:
                warning = {
                    "kind": "canon_leak",
                    "span_text": label,
                    "message": f"疑似泄底：正文直接写出了真相层私有标签「{label}」",
                }
                node_id = (canon_node_ids_by_label or {}).get(label)
                if node_id:
                    warning["canon_node_id"] = node_id
                _hit_dict(warning)

        # ---- 3. secret_leak：私有实体档案关键短语复现 ----
        for secret in (character_secrets or []):
            if not isinstance(secret, dict):
                continue
            owner = str(secret.get("name") or "").strip()
            for phrase in _secret_phrases(secret.get("text") or ""):
                if phrase in text:
                    owner_note = f"「{owner}」的" if owner else ""
                    _hit(
                        "secret_leak", phrase,
                        f"疑似泄底：正文与{owner_note}私有设定片段「{phrase}」重合",
                    )

        # ---- 4. cliche_hit：禁忌面命中（任务包 A，只提示不拦截）----
        # bundle.prohibitions（settings_bundle 禁忌面归一）非空时对 text 跑
        # finditer；任一 blocker 或总命中 ≥ GHOST_GUARD_CLICHE_MIN_TOTAL 报
        # 一条 warning（命中 pattern 去重前 5 进 detail）。静态反 AI 词计入
        # ——上屏快检是呈现面（与 fail-fast validate 的静态源排除策略不同）。
        # 本段自带异常兜底：禁忌面快检失败不吞掉前面三类已产出的 warnings。
        try:
            if bundle is not None:
                ps = getattr(bundle, "prohibitions", None)
                if ps:
                    total_hits = 0
                    has_blocker = False
                    hit_patterns: List[str] = []
                    for _m, entry in ps.finditer(text):
                        total_hits += 1
                        if entry.severity == "blocker":
                            has_blocker = True
                        pattern = entry.pattern
                        if pattern and pattern not in hit_patterns:
                            hit_patterns.append(pattern)
                    if has_blocker or total_hits >= GHOST_GUARD_CLICHE_MIN_TOTAL:
                        top = hit_patterns[:GHOST_GUARD_CLICHE_MAX_PATTERNS]
                        _hit(
                            "cliche_hit", "、".join(top),
                            f"草稿命中禁忌词：{'、'.join(top)}"
                            f"（若是有意的引语/戏仿可忽略）",
                            detail=top,
                        )
        except Exception:
            pass  # 零报错契约：本类快检失败静默跳过

        # ---- 5. out_of_scene：非在场/提及名单实体 × 上手级动词框架（shadow 出生，
        # 2026-09-02 约束治理一期）——流光穿帮的输出侧镜像。白名单与称呼表同一
        # 产物（路由透传 ctx.proper_nouns，不重算）；命中带 local_only=True 由
        # 路由过滤出 SSE 帧；闪回豁免只落台账（outcome=exempt）连 warning 都不产。
        if visible_names is not None:
            try:
                from backend.services.context.scene_visibility import find_out_of_scene_hits

                candidates = all_names
                if candidates is None and bundle is not None:
                    candidates = _bundle_all_names(bundle)
                for h in find_out_of_scene_hits(text, visible_names, candidates or []):
                    if on_event is not None:
                        try:
                            if h.get("exempt"):
                                on_event("ghost-guard-out-of-scene", "exempt", "flashback",
                                         {"name": h.get("name"), "sentence": h.get("sentence")})
                            else:
                                on_event("ghost-guard-out-of-scene", "hit", "handling_verb_frame",
                                         {"name": h.get("name"), "verb": h.get("verb")})
                        except Exception:
                            pass  # 埋点失败不阻塞快检
                    if h.get("exempt"):
                        continue
                    _hit_dict({
                        "kind": "out_of_scene",
                        "span_text": str(h.get("name") or ""),
                        "message": (
                            f"「{h.get('name')}」不在此刻在场/提及名单，却被写成可上手对象"
                            f"（动词「{h.get('verb')}」；若是有意的预告/回忆可忽略）"
                        ),
                        "detail": {"verb": h.get("verb")},
                        "local_only": True,
                    })
            except Exception:
                pass  # 零报错契约：本类快检失败静默跳过

        return warnings
    except Exception:
        # 零报错契约：快检是柔性信号，任何异常静默为空（绝不阻塞生成）
        return []


# ============================================================
# 内部工具
# ============================================================

def _bundle_all_names(bundle: Any) -> List[str]:
    """从 bundle 取书级实体+资产名全集（out_of_scene 检测候选宇宙；去重保序）。

    只收可被「上手」的实体类：character/asset（势力是组织不是物件，编不进
    「拧流光的螺栓」这类物理操纵帧；事故语料实证「统合局×检修」是纯碰撞）。
    world 适配器带 world_entity.entity_type；legacy ChapterEntity 无类型信息
    放行（宁多勿漏，shadow 形态下误报无用户代价）。与 proper_nouns 同口径
    （bundle 形态下路由已透传 visible/all，此处只服务显式参数形态的测试）。
    """
    names: List[str] = []
    for ent in (getattr(bundle, "entities", None) or []):
        we = _get_nested(ent, "world_entity", None)
        etype = str(getattr(we, "entity_type", "") or "") if we is not None else ""
        if etype and etype not in ("character", "asset"):
            continue
        name = str(_get_nested(ent, "character", "name") or "").strip()
        if name and name not in names:
            names.append(name)
    for a in (getattr(bundle, "assets", None) or []):
        name = str(getattr(a, "name", "") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _bundle_canon_labels(bundle: Any) -> List[str]:
    """从 bundle 取 canon 私有标签（与 A1 抽取同源——hard_constraints 唯一权威）。"""
    try:
        labels = bundle.hard_constraints().get("canon_private_labels")
        return [l for l in (labels or []) if isinstance(l, str)]
    except Exception:
        return []


def _bundle_secrets(bundle: Any) -> List[Dict[str, str]]:
    """从 bundle 取 A1 私有通道 secrets（结构化 [{name, text}]）。"""
    secrets = getattr(bundle, "character_secrets", None) or []
    return [s for s in secrets if isinstance(s, dict)]


def _bundle_entity_names(bundle: Any) -> Dict[str, List[str]]:
    """从 bundle.entities 建 实体id → [主名, *别名] 表。

    算法轨（A1 双轨纪律的另一侧）：适配器携带全量——private 实体的名字也
    参与 dead_speak 判定（私有角色的生死矛盾同样是疑点）。兼容 world 适配器
    （world_entity.id/aliases 与 character.aliases 双路）与旧表 ChapterEntity
    （无 world_entity / 无 id → 无从对上 character_states，自然跳过）。
    """
    names: Dict[str, List[str]] = {}
    for ent in (getattr(bundle, "entities", None) or []):
        eid = str(_get_nested(ent, "world_entity", "id") or "")
        if not eid or eid in names:
            continue
        name = str(_get_nested(ent, "character", "name") or "").strip()
        aliases = _get_nested(ent, "character", "aliases") or []
        if not isinstance(aliases, (list, tuple)):
            aliases = []
        candidates = [name] + [str(a or "").strip() for a in aliases]
        names[eid] = [c for c in candidates if c]
    return names


def _dead_entity_names(
    world_state: Optional[Dict[str, Any]],
    entity_names_by_id: Optional[Dict[str, List[str]]],
) -> List[str]:
    """world_state.character_states 中 alive=False 的实体名+别名（去重保序）。"""
    if not isinstance(world_state, dict) or not entity_names_by_id:
        return []
    states = world_state.get("character_states")
    if not isinstance(states, (list, tuple)):
        return []
    out: List[str] = []
    for cs in states:
        if not isinstance(cs, dict) or cs.get("alive") is not False:
            continue
        eid = str(cs.get("entity_id") or "")
        for name in entity_names_by_id.get(eid, []):
            if name not in out:
                out.append(name)
    return out


def _secret_phrases(secret_text: str) -> List[str]:
    """secret 文本 → 关键短语表（≥4 字连续片段，去重保序，截 20 字）。

    切段而非滑窗：滑窗会把任意 4 字组合都变成探针（海量误报，违背宁漏勿误）；
    切段要求整段短语逐字复现才报——AI 真把秘密写出来时必然触发，改写复述则
    宁可放过（快检不是防泄底的强制力，真相层审计才是）。
    """
    if not secret_text or not isinstance(secret_text, str):
        return []
    phrases: List[str] = []
    for seg in _SECRET_SPLIT_RE.split(secret_text):
        seg = seg.strip()
        if len(seg) < SECRET_PHRASE_MIN_CHARS:
            continue
        phrase = seg[:SECRET_PHRASE_MAX_CHARS]
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _get_nested(obj: Any, *attrs: str) -> Any:
    """链式安全取属性（ORM 对象或 dict；None 链路返回 None）。"""
    cur = obj
    for a in attrs:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(a)
        else:
            cur = getattr(cur, a, None)
    return cur

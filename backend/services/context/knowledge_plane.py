# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 知识检索平面一期（Knowledge Retrieval Plane v3.1 · 一期）
"""
正文生成的统一知识供给层（docs/knowledge-retrieval-plane.md §4-§7 施工落地）。

设计意图（四条公理的代码化）：
- 任务平权：本模块产出的知识视图被 stitch 五模式 / dock / 推测 / 预览共同消费，
  任何生成调用不再有「轻档少知道」的合法路径；
- 选中即完整：条目是注入原子，本模块内不存在任何字符级截断——知识增长由
  选择精度吸收（场景恒选/在场/提及/作者显式），不由截断吸收；
- 时态标注 + 折叠态优先：时变条目带【此刻】前缀，档案静态文本与事件折叠态
  并存时明示以「此刻」为准（防「完整注入矛盾」）；
- 逃逸阀丢整条：唯一体量约束是 KG_BUDGET_CHARS，超限按 养料→软 顺序丢弃
  整条（硬层永不丢），丢弃记录进 unselected（原因=预算），对作者可见。

一期选择器集（§9）：场景恒选 / 在场 / 提及（本章全文）/ 时刻（world_bridge
上游已按 t 过滤活跃关系）/ 作者显式（legacy 章级绑定）。检索选择与二次激活
扫描属二期，数据量验证后再接（当前书规模下选择器≈全选，先拿完备注入收益）。

零变化契约：无实体/无世界观/无伏笔的书，全部渲染产物为空串（块缺席，
prompt 逐字节不变）。

性能注记（设计 §9 条目 7 的落地口径）：本模块纯 CPU 渲染、零新增 DB 查询
（bundle 由调用方既有路径加载），TTL 装配缓存推迟到实测证明需要时再加——
当前每次装配成本在微秒级，先缓存是过度工程。

副作用：无（纯函数；bundle 只读）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from backend.services.adaptive.paragraph_source import written_text


# ============================================================
# 常量（唯一体量约束，逃逸阀）
# ============================================================

# 知识条目总体预算（字符）。设计值依据：p75 填写度 300 章厚书的选择集
# ≈6.5-13k 字（docs/knowledge-retrieval-plane.md §8）；当前两本书全量
# 2-4k 字，此阀在正常数据量下不触发，仅为厚书安全网。丢整条、永不腰斩。
KG_BUDGET_CHARS = 16000


# ============================================================
# 数据容器
# ============================================================

@dataclass
class KnowledgeEntry:
    """知识条目：选择与注入的原子单位（永不劈开）。

    kind: entity / asset / worldview / relation / hook
    present: 在场（场景钉 + t 时刻折叠命中；硬层）
    temporal: 时态前缀（如「t=3520·位于北岸要塞」；空=静态条目）
    selector: 选中原因（场景恒选/在场/提及/作者显式/恒选/邻近一跳）
    hard: 硬层条目（逃逸阀永不丢）
    """
    kind: str
    key: str
    title: str
    body: str = ""
    present: bool = False
    dead: bool = False
    temporal: str = ""
    selector: str = ""
    hard: bool = False
    aliases: List[str] = field(default_factory=list)
    # 世界实体 id（world 模式 entity 条目携带；2026-09-03 线 D 信念泄漏检的
    # 命题视角集数据源——不在渲染面出现，纯审计/判定用）
    entity_id: str = ""


@dataclass
class KnowledgeView:
    """选择+渲染后的知识视图（五模式/dock/预览共同消费）。"""
    scene_identity: str = ""            # 场景身份块（事实层头部）
    entities_text: str = ""             # 在场与相关人物块（含档案全文+此刻状态）
    worldview_text: str = ""            # 世界观块（条目完整）
    relations_text: str = ""            # 关系块（t 时刻活跃）
    negative_constraints: str = ""      # 负面清单约束块（四源合并全量）
    warm_card: str = ""                 # 计划层温卡（spine 意图+锚点，章内冻结——B6）
    mentioned_names: List[str] = field(default_factory=list)  # 热层雏形：本章提及（后缀）
    recency_pin: str = ""               # user 尾部「此刻·切记」重钉（3-5 行）
    previous_summary: str = ""          # 紧前一章摘要（恒选，不截断）
    # 审计面（预览「未选清单」与 trace 选择集记录的数据源）
    provenance: Dict[str, Any] = field(default_factory=dict)  # B5 信封
    selected_keys: List[str] = field(default_factory=list)
    present_names: List[str] = field(default_factory=list)
    dead_names: List[str] = field(default_factory=list)
    # 在场世界实体 id 表（2026-09-03 线 D：信念泄漏检的命题视角集——
    # 「在场者是否有人知道这条真相」的判定输入；与 present_names 同点产出）
    present_entity_ids: List[str] = field(default_factory=list)
    unselected: List[Dict[str, str]] = field(default_factory=list)

    def total_chars(self) -> int:
        return sum(len(x) for x in (
            self.scene_identity, self.entities_text, self.worldview_text,
            self.relations_text, self.negative_constraints, self.warm_card,
        ))


# ============================================================
# 条目化（bundle → KnowledgeEntry 池）
# ============================================================

def _entity_name(ent: Any) -> str:
    char = getattr(ent, "character", None)
    if char is None and isinstance(ent, dict):
        char = ent.get("character")
    if char is None:
        return ""
    return getattr(char, "name", "") or (char.get("name", "") if isinstance(char, dict) else "") or ""


def _entity_is_private(ent: Any) -> bool:
    """私有实体不进正文知识块（走 secrets 通道，双轨纪律与 settings_bundle 同口径）。"""
    we = getattr(ent, "world_entity", None)
    if we is not None and (getattr(we, "visibility", None) or "") == "private":
        return True
    char = getattr(ent, "character", None)
    if char is not None and (getattr(char, "visibility", None) or "") == "private":
        return True
    return False


def _worldview_items(book: Any) -> List[Tuple[str, str]]:
    """books.worldview_settings → [(title, content)]（兼容 {items:[…]} 新结构与纯字符串旧格式）。"""
    raw = getattr(book, "worldview_settings", None) if book is not None else None
    items: List[Tuple[str, str]] = []
    if isinstance(raw, dict):
        for it in raw.get("items") or []:
            if isinstance(it, dict):
                title = str(it.get("title") or "").strip()
                content = str(it.get("content") or "").strip()
                if title or content:
                    items.append((title or "世界观", content))
    elif isinstance(raw, str) and raw.strip():
        items.append(("世界观", raw.strip()))
    return items


def build_knowledge_entries(bundle: Any) -> List[KnowledgeEntry]:
    """把 bundle 的五类知识源归一为条目池（不选择、不截断）。

    死亡/在场判定：world 模式吃 world_state 折叠（含 scene_location_id 的
    在场判定与 alive=False 的死亡判定）；legacy 模式无折叠数据，present/dead
    恒 False，动态文本按作者录入原样进 temporal 行。
    """
    entries: List[KnowledgeEntry] = []

    chapter = getattr(bundle, "chapter", None)
    scene_loc_id = str(getattr(chapter, "scene_location_id", None) or "")
    # 场景作用域（location-interior 二期）：钉房间时祖先上的角色算在场，与 world_bridge 提权同口径
    from backend.services.world.location_tree import scene_scope_ids

    scene_scope = scene_scope_ids(getattr(bundle, "locations", None) or [], scene_loc_id)
    world_state = getattr(bundle, "world_state", None) or {}
    states: Dict[str, Dict[str, Any]] = {}
    if isinstance(world_state, dict):
        states = {
            str(cs.get("entity_id")): (cs or {})
            for cs in world_state.get("character_states", []) or []
        }
    world_time = getattr(bundle, "world_time", 0) or 0

    # ---- 实体条目（角色；world 模式含全部书级实体，legacy 为章级绑定）----
    world_sourced = bool(getattr(bundle, "world_sourced", False))
    for ent in (getattr(bundle, "entities", None) or []):
        if _entity_is_private(ent):
            continue  # 私有档案走 secrets 块，正文知识块不重复注入
        name = _entity_name(ent)
        if not name:
            continue
        char = getattr(ent, "character", None)
        if char is None and isinstance(ent, dict):
            char = ent.get("character")

        def _cattr(attr: str) -> Any:
            if char is None:
                return ""
            return getattr(char, attr, None) or (char.get(attr) if isinstance(char, dict) else None) or ""

        static = str(_cattr("static_prompt") or "")
        dynamic = str(_cattr("dynamic_state") or "")
        aliases = [str(a) for a in (_cattr("aliases") or []) if str(a).strip()]

        present = False
        dead = False
        temporal = ""
        we = getattr(ent, "world_entity", None)
        eid = str(getattr(we, "id", "") or "") if we is not None else ""
        cs = states.get(eid) if eid else None
        if cs:
            if not cs.get("alive", False):
                dead = True
                temporal = f"t={world_time}·已死亡"
            else:
                if scene_scope and str(cs.get("location_id") or "") in scene_scope:
                    present = True
                bits = []
                if str(cs.get("location_id") or ""):
                    loc_name = _location_name(bundle, str(cs.get("location_id")))
                    if loc_name:
                        bits.append(f"位于{loc_name}")
                if str(cs.get("label") or "").strip():
                    bits.append(str(cs.get("label")).strip())
                if bits:
                    temporal = f"t={world_time}·" + "，".join(bits)
        elif dynamic:
            temporal = f"作者标注·{dynamic}"

        entries.append(KnowledgeEntry(
            kind="entity", key=f"entity:{name}", title=name, body=static,
            present=present, dead=dead, temporal=temporal,
            aliases=aliases,
            selector="",  # 选择阶段填
            hard=False,
            entity_id=eid,
        ))

    # ---- 资产条目（legacy bundle.assets；world 模式资产已在 world 实体集，此处兜底去重）----
    known = {e.key for e in entries}
    for a in (getattr(bundle, "assets", None) or []):
        if _entity_is_private(a):
            continue
        name = str(getattr(a, "name", "") or "")
        if not name or f"entity:{name}" in known:
            continue
        desc = str(getattr(a, "static_description", "") or "")
        entries.append(KnowledgeEntry(
            kind="asset", key=f"asset:{name}", title=name, body=desc,
            aliases=[], selector="", hard=False,
        ))

    # ---- 世界观条目（恒选，事实层）----
    for i, (title, content) in enumerate(_worldview_items(getattr(bundle, "book", None))):
        entries.append(KnowledgeEntry(
            kind="worldview", key=f"worldview:{i}", title=title,
            body=(f"{title}：{content}" if title != "世界观" else content),
            selector="恒选·世界观", hard=True,
        ))

    # ---- 势力条目（2026-09-04 审计修复：faction 此前对生成层完全不存在）----
    # 恒选软条目：势力是一本书的少数派（量级 ≤10、体量有界），作为「舞台归属」
    # 应与世界观同权常驻；逃逸阀超预算时可整条丢（rank 同 entity 档）。
    # 无 faction 书 bundle.factions 恒空 → 零条目（零变化契约）。
    for f in (getattr(bundle, "factions", None) or []):
        name = str(getattr(f, "name", "") or "")
        body = str(getattr(f, "static_prompt", "") or "")
        if not name or not body:
            continue
        entries.append(KnowledgeEntry(
            kind="faction", key=f"faction:{name}", title=name, body=body,
            aliases=[str(a) for a in (getattr(f, "aliases", None) or []) if str(a).strip()],
            selector="恒选·势力", hard=False,
        ))

    # ---- 关系条目（world 模式上游已按 t 过滤活跃边=时刻选择；legacy 原样）----
    for r in (getattr(bundle, "relationships", None) or []):
        src = getattr(r, "source_character", None)
        tgt = getattr(r, "target_character", None)
        src_name = (getattr(src, "name", "") or "") if src is not None else ""
        tgt_name = (getattr(tgt, "name", "") or "") if tgt is not None else ""
        rel = str(getattr(r, "relationship_type", "") or "")
        desc = str(getattr(r, "description", "") or "")
        if src_name and tgt_name and (rel or desc):
            body = desc or rel
            entries.append(KnowledgeEntry(
                kind="relation", key=f"relation:{src_name}~{tgt_name}",
                title=f"{src_name}↔{tgt_name}", body=body,
                aliases=[], selector="", hard=False,
            ))

    # ---- 开放伏笔条目（恒选；open 态有界）----
    for h in (getattr(bundle, "open_hooks", None) or []):
        if isinstance(h, dict):
            content = str(h.get("content", "") or "")
        else:
            content = str(getattr(h, "content", "") or "")
        if content.strip():
            entries.append(KnowledgeEntry(
                kind="hook", key=f"hook:{content[:24]}", title=content,
                body=content, aliases=[], selector="恒选·开放伏笔", hard=False,
            ))

    return entries


def _location_name(bundle: Any, loc_id: str) -> str:
    """地点显示名：内部构造（有父级）返回全路径「统合局基地·B2 拘留层」——
    上下文里「位于X·Y」比裸房间名无歧义；顶层无父返回裸名（零变化契约）。"""
    from backend.services.world.location_tree import location_path, locations_by_id

    locs = getattr(bundle, "locations", None) or []
    by_id = locations_by_id(locs)
    loc = by_id.get(loc_id)
    if loc is None:
        return ""
    return location_path(loc, by_id)


# ============================================================
# 选择器引擎（一期：场景恒选 / 在场 / 提及 / 作者显式；宁多勿漏）
# ============================================================

def select_knowledge(
    entries: List[KnowledgeEntry],
    bundle: Any,
    chapter_text: str,
) -> Tuple[List[KnowledgeEntry], List[Dict[str, str]], List[str]]:
    """对条目池跑一期选择器，返回 (选中条目有序列表, 未选清单, 提及名单)。

    选择器不对称原则（公理四）：宁多勿漏——误选由逃逸阀兜住，漏选无兜底。
    B6 前缀纪律（docs/world-cognition-architecture.md §3）：**提及驱动的注入
    逐出前缀**——提及者不再展开为前缀实体条目（那会让每次打字都作废整个
    前缀缓存），改为返回提及名单（热层后缀，recency 位旁重钉）；前缀实体
    块=进章冻结版（在场/死亡/作者绑定），刷新点=切章/沉淀/场景钉/世界编辑。
    """
    world_sourced = bool(getattr(bundle, "world_sourced", False))
    plain_text = re.sub(r"\s+", "", written_text(chapter_text or ""))

    selected: List[KnowledgeEntry] = []
    unselected: List[Dict[str, str]] = []
    selected_entity_titles: set = set()
    mentioned: List[str] = []

    for e in entries:
        if e.kind in ("worldview", "hook", "faction"):
            # 恒选条目（选择器已标）；faction 为软恒选——逃逸阀超预算时可整条丢
            selected.append(e)
            continue
        if e.kind in ("entity", "asset"):
            if e.present or e.dead:
                e.selector = "在场" if e.present else "在场·死亡"
                e.hard = True
                selected.append(e)
                selected_entity_titles.add(e.title)
                continue
            names = [e.title] + [a for a in e.aliases if a]
            if any(n in plain_text for n in names if n):
                mentioned.append(e.title)  # 热层后缀（前缀冻结纪律）
                continue
            if not world_sourced:
                # legacy 模式：entities 本身就是作者章级绑定 = 作者显式选择
                e.selector = "作者显式·章级绑定"
                selected.append(e)
                selected_entity_titles.add(e.title)
                continue
            unselected.append({"key": e.key, "title": e.title, "reason": "未在场未提及（提及时进后缀）"})
            continue
        if e.kind == "relation":
            # 邻近选择：两端点均在前缀选中集才进（提及者的边随后缀走，不进前缀）
            parts = e.title.split("↔")
            if len(parts) == 2 and parts[0] in selected_entity_titles and parts[1] in selected_entity_titles:
                e.selector = "邻近·在场一跳"
                selected.append(e)
            else:
                unselected.append({"key": e.key, "title": e.title, "reason": "端点未选中"})

    # 逃逸阀（丢整条，永不腰斩；硬层永不丢）：养料序=hook → relation → 提及实体
    # （2026-08-28 审计修复：原 reversed() 与注释/设计相反——实体最先丢、hook
    # 最后受保护；升序遍历才是「养料最先丢」的本意，对拍测试已锁顺序）
    total = sum(len(e.body) + len(e.title) for e in selected)
    if total > KG_BUDGET_CHARS:
        soft_order = [e for e in selected if not e.hard]
        # 丢弃序：hook 最先（rank 0）、faction/relation 次之、提及实体最后
        rank = {"hook": 0, "faction": 1, "relation": 2, "entity": 3, "asset": 3, "worldview": 4}
        soft_order.sort(key=lambda e: rank.get(e.kind, 2))
        dropped_keys = set()
        for e in soft_order:  # 从最不重要的一端（hook）开始丢
            if total <= KG_BUDGET_CHARS:
                break
            total -= len(e.body) + len(e.title)
            dropped_keys.add(e.key)
            unselected.append({"key": e.key, "title": e.title, "reason": "预算整条丢弃"})
        selected = [e for e in selected if e.key not in dropped_keys]

    # 渲染序：在场 → 死亡 → 绑定（资产/势力随实体序）→ 关系 → 伏笔；世界观单独块
    order_rank = {
        "entity": 0, "asset": 1, "faction": 1, "relation": 2, "hook": 3, "worldview": 4,
    }
    selected.sort(key=lambda e: (
        order_rank.get(e.kind, 5),
        0 if (e.present or e.dead) else 1,
    ))
    return selected, unselected, mentioned


# ============================================================
# UKV 渲染（时态标注 + 折叠态优先声明）
# ============================================================

def _indent_body(body: str, prefix_first: str) -> str:
    """多行档案体的缩进拼接（首行带标签，后续行两空格缩进）。"""
    lines = [ln for ln in (body or "").split("\n") if ln.strip()]
    if not lines:
        return ""
    return prefix_first + "\n".join([" " + lines[0]] + ["  " + ln for ln in lines[1:]])


def _render_warm_card(bundle: Any) -> str:
    """计划层温卡（B6 · docs/world-cognition-architecture.md §1 第四层）。

    spine 意图 + 锚点（作者亲笔方向，章内稳定——天然住前缀；就近节拍
    不进此处：它已经由 user 侧「章节意图」携带，避免重复注入）。
    无 spine → 空串（零变化契约）。
    """
    chapter = getattr(bundle, "chapter", None)
    spine = getattr(chapter, "spine", None) if chapter is not None else None
    if not isinstance(spine, dict):
        return ""
    lines = []
    intent = spine.get("intent") or {}
    text = str((intent.get("text") if isinstance(intent, dict) else intent) or "").strip()
    if text:
        lines.append(f"本章打算：{text}")
    anchors = [
        str(a.get("text") or "").strip()
        for a in (spine.get("anchors") or [])
        if isinstance(a, dict) and str(a.get("status") or "") != "dropped"
        and str(a.get("text") or "").strip()
    ]
    if anchors:
        lines.append("非写不可的情节：" + "；".join(anchors))
    return ("# 本章打算（作者定的方向，软约束）\n" + "\n".join(lines)) if lines else ""


def render_knowledge_view(bundle: Any, selected: List[KnowledgeEntry],
                          unselected: List[Dict[str, str]],
                          chapter_text: str = "",
                          mentioned: Optional[List[str]] = None,
                          active_scene: Optional[Dict] = None) -> KnowledgeView:
    """渲染知识视图（完整注入；空数据=空串=块缺席=零变化）。

    active_scene（第三弹 · 光标派生取景框）：非空且 derived=True 时，场景身份
    块的首行换「当前场景：X（按正文推导）」并保留本章钉定行；地点档案链跟随
    派生地点（AI 知道整条进路以当前取景为准）。None/未派生/与钉一致 → 与旧
    渲染逐字节一致（零变化契约——preview/dock 等无光标语境的调用方不受影响）。
    """
    kv = KnowledgeView(unselected=unselected)
    kv.previous_summary = str(getattr(bundle, "previous_summary", "") or "")
    kv.warm_card = _render_warm_card(bundle)
    kv.mentioned_names = list(mentioned or [])

    # ---- 场景身份（场景恒选集的渲染面）----
    chapter = getattr(bundle, "chapter", None)
    scene_loc_id = str(getattr(chapter, "scene_location_id", None) or "")
    world_time = getattr(bundle, "world_time", 0) or 0
    world_time_source = str(getattr(bundle, "world_time_source", "zero") or "zero")
    # 第三弹：派生取景生效时，取景地点=派生地（档案链/首行随它走），钉退居注脚
    derived = bool(active_scene and active_scene.get("derived")) and str(active_scene.get("loc_id") or "")
    view_loc_id = (derived or scene_loc_id)
    loc_name = _location_name(bundle, view_loc_id) if view_loc_id else ""
    pinned_name = _location_name(bundle, scene_loc_id) if scene_loc_id else ""
    # 第四批（2026-09-16 微观空间姿态）：正文有空间动势但名册无此房时，
    # 宏观据点叠加微观场态——AI 知道镜头在「室内生活/桌边」而非悬在村口
    posture = (active_scene or {}).get("posture") if active_scene else None
    scene_bits = []
    if derived and loc_name:
        if isinstance(posture, dict) and posture.get("label"):
            scene_bits.append(
                f"当前场景：{loc_name}（当前镜头位于{posture['label']}，正文推导）"
            )
        else:
            scene_bits.append(f"当前场景：{loc_name}（按正文推导）")
        if pinned_name and view_loc_id != scene_loc_id:
            scene_bits.append(f"本章钉定：{pinned_name}（取景已随笔尖流转）")
    elif loc_name:
        scene_bits.append(f"本章场景：{loc_name}（作者钉定）")
    elif view_loc_id:
        scene_bits.append("本章场景：已钉定（地点档案缺失）")
    # 场景地点档案（location-interior 二期）：场景地点及其祖先链的 intro，从外到内——
    # 钉到「B2 拘留层」时 AI 知道整条进路（基地是什么、这一层是什么）。
    # 全链无 intro 不追加任何行（零变化契约：无内部构造的书 prompt 逐字节不变）。
    if view_loc_id:
        from backend.services.world.location_tree import ancestor_chain, locations_by_id

        by_id = locations_by_id(getattr(bundle, "locations", None) or [])
        archive = [
            f"{l.name}：{str(getattr(l, 'intro', '') or '').strip()}"
            for l in reversed(ancestor_chain(by_id, view_loc_id))
            if str(getattr(l, "intro", "") or "").strip()
        ]
        if archive:
            scene_bits.append("地点档案：" + "；".join(archive))
    if world_time_source != "zero":
        source_label = {
            "chapter_anchor": "本章锚", "prev_anchor": "前序最近锚", "max_event": "事件最大时刻",
        }.get(world_time_source, world_time_source)
        scene_bits.append(f"叙事时刻：t={world_time}（{source_label}）")
    if scene_bits:
        kv.scene_identity = "# 场景身份（事实层，生成以此为准）\n" + "｜".join(scene_bits)

    # ---- 在场与相关人物（档案全文 + 此刻状态；时态标注 + 折叠态优先声明）----
    ent_lines: List[str] = []
    present_names: List[str] = []
    present_entity_ids: List[str] = []
    dead_names: List[str] = []
    for e in selected:
        if e.kind == "entity":
            if e.dead:
                dead_names.append(e.title)
                line = f"- {e.title}【已死亡·不得出场、不得开口】"
                if e.body:
                    line += "\n" + _indent_body(e.body, "  档案（作者录入，未删节）：")
                ent_lines.append(line)
            else:
                if e.present:
                    present_names.append(e.title)
                    if e.entity_id:
                        present_entity_ids.append(e.entity_id)
                tag = "〔在场〕" if e.present else ""
                moment = f"【此刻·{e.temporal}】" if e.temporal else ""
                head = f"- {e.title}{tag}{moment}"
                if e.aliases:
                    head += f"（别名：{'、'.join(e.aliases)}）"
                if e.body:
                    head += "\n" + _indent_body(e.body, "  档案（作者录入，未删节）：")
                ent_lines.append(head)
        elif e.kind == "asset":
            if e.body:
                ent_lines.append(f"- {e.title}（物件）：{e.body}")
            else:
                ent_lines.append(f"- {e.title}（物件）")
    if ent_lines:
        kv.entities_text = (
            "# 在场与相关人物·物件（事实层，档案为作者录入原文，一字未删）\n"
            + "\n".join(ent_lines)
            + "\n注：条目内【此刻】由事件推演得出；与档案描述冲突时，以【此刻】为准。"
        )
    kv.present_names = present_names
    kv.dead_names = dead_names
    kv.present_entity_ids = present_entity_ids

    # ---- 世界观（条目完整）----
    wv = [e for e in selected if e.kind == "worldview"]
    if wv:
        kv.worldview_text = "# 世界观（完整注入，未删节）\n" + "\n".join(f"- {e.body}" for e in wv)

    # ---- 关系（t 时刻活跃）----
    rel = [e for e in selected if e.kind == "relation"]
    if rel:
        kv.relations_text = "# 人物关系（此刻活跃）\n" + "\n".join(f"- {e.title}：{e.body}" for e in rel)

    # ---- 负面清单约束块（四源合并；P0 2026-08-29 分档：块内只留 warning 档）----
    # 三平面分权（docs/style-paradigm.md）：负面块的执法职能移交呈现平面洗层
    # （wash_ghost_text），prompt 只承担偏置——blocker 档抽走去 user 尾部重钉
    # （模型对 prompt 头尾服从最高，作者最硬的禁忌不该埋在第 8 块遗忘区），
    # warning 档维持提醒语义留原位。无 blocker 条目的书逐字节零变化。
    prohibitions = getattr(bundle, "prohibitions", None)
    blocker_bits: List[str] = []
    if prohibitions is not None:
        try:
            warn_words, blocker_bits = split_prohibition_tiers(prohibitions)
            if warn_words:
                kv.negative_constraints = "# 本书禁词（提醒档，尽量避开）\n" + "、".join(warn_words)
        except Exception:
            pass  # 降级空串（块缺席），不阻塞装配

    # ---- recency 位重钉（user 尾部 3-5 行，lost-in-the-middle 双锚的 recency 端）----
    pin_bits = []
    if present_names:
        pin_bits.append("在场：" + "、".join(present_names))
    if dead_names:
        pin_bits.append("已死亡（不得出场）：" + "、".join(dead_names))
    if loc_name:
        pin_bits.append(f"场景：{loc_name}")
    if world_time_source != "zero":
        pin_bits.append(f"t={world_time}")
    if pin_bits:
        kv.recency_pin = "【此刻·切记】" + "｜".join(pin_bits)
        # 名单语义重框（2026-09-03 质感批次第三层，trace 实证「在场：流光」被
        # 当登场指令——幽灵把流光拉上观察台站着没事干）：在场名单是供一致性
        # 核对的资料（别写错），不是要点名的演员表（不必写）。
        if present_names:
            kv.recency_pin += (
                "\n（在场名单只供核对一致性——别让不在场的人登场、别让死者开口；"
                "它不是登场名单，没有谁此刻必须出场，没戏份的一个都不必写）"
            )
    # P0 blocker 重钉（三平面分权）：作者硬禁忌正面化编译进 user 尾部——
    # recency 位是模型服从最高区，与「此刻」行同屏重钉
    if blocker_bits:
        kv.recency_pin = (kv.recency_pin + "\n" if kv.recency_pin else "") + "【作者禁忌】" + "；".join(blocker_bits)
    # B6 热层后缀：本章提及（前缀冻结纪律——随段落变的部分只住后缀）
    if kv.mentioned_names:
        kv.recency_pin += "\n本章提及：" + "、".join(kv.mentioned_names[:12])

    kv.selected_keys = [e.key for e in selected]
    # B5 provenance 信封（不变量 5）：按 (章/t/场景钉/正文长) 参数哈希——
    # 同信封重算应逐字节相等（对拍测试锁）；digest/场景卡接入时复用同构
    from backend.services.world.reality_check import envelope

    kv.provenance = envelope(
        kind="knowledge_view",
        source_keys=kv.selected_keys,
        params={
            "book_id": str(getattr(bundle, "book_id", "") or ""),
            "chapter_id": str(getattr(getattr(bundle, "chapter", None), "id", "") or ""),
            "world_time": world_time,
            "scene_loc": scene_loc_id,
            "content_len": len(chapter_text),
        },
    )
    return kv


def split_prohibition_tiers(prohibitions: Any) -> Tuple[List[str], List[str]]:
    """P0 分档纯函数：负面清单按 severity 拆两路。

    返回 (warning 词表——负面块渲染用, blocker 正面化重钉行——user 尾部用)。
    blocker 行格式「不用「X」——改用 Y」：有 alternative 给正路，无 alternative
    给通用正路（具体动作/物件）。≤6 行（重钉是 3-5 行的 recency 位，不是清单墙）。
    """
    warn = prohibitions.words(10 ** 6, severity="warning")
    bits: List[str] = []
    for e in getattr(prohibitions, "entries", ()) or ():
        if (getattr(e, "severity", "") or "warning") != "blocker" or not e.pattern:
            continue
        alt = e.alternative or "换成具体的动作或物件"
        bits.append(f"不用「{e.pattern}」——{alt}")
        if len(bits) >= 6:
            break
    return warn, bits


def kg_block_kwargs(kv: Any) -> Dict[str, str]:
    """知识视图 → render_system_blocks / builder 的块参数 dict。

    独立成函数（非仅 KnowledgeView 方法）：路由侧对装配结果做防御式
    取用（测试桩可能用 SimpleNamespace 伪造 ctx），任何缺失属性降级
    空串=块缺席=零变化。
    """
    return dict(
        scene_identity=str(getattr(kv, "scene_identity", "") or ""),
        warm_card=str(getattr(kv, "warm_card", "") or ""),
        entities_text=str(getattr(kv, "entities_text", "") or ""),
        worldview_text=str(getattr(kv, "worldview_text", "") or ""),
        relations_text=str(getattr(kv, "relations_text", "") or ""),
        negative_constraints=str(getattr(kv, "negative_constraints", "") or ""),
    )


# ---- B6 章内冻结前缀缓存（WCA §3 前缀纪律）----
# 键=世界侧输入签名（章/t/场景钉/spine/各知识源内容哈希/折叠态摘要），
# **不含正文内容**——作者打字不再作废前缀；刷新点=切章/世界编辑/场景钉/
# spine 变更/锚定时刻变化（全部落在键里）。提及扫描每调用重跑（纯 CPU）。
# 2026-08-28 审计修复：签名从「数量/长度」升级为内容哈希——同数量的内容级
# 世界编辑（改档案/改关系描述/改世界观条目/同长 canon）此前不换签名，冻结
# 前缀会继续供旧档案到切章为止；哈希开销微秒~毫秒级，远低于一次 bundle 加载。
_PREFIX_CACHE: Dict[Any, tuple] = {}
_PREFIX_CACHE_MAX = 64


def _sig_hash(text: str) -> str:
    """前缀签名用稳定短哈希（内容级失效——数量/长度只在巧合时才失配）。"""
    return hashlib.sha1((text or "").encode("utf-8", "ignore")).hexdigest()[:12]


def _entity_sig_line(ent: Any) -> str:
    """实体进签名的字段行（名/档案/此刻标注/别名/可见性——渲染产物的内容源）。"""
    char = getattr(ent, "character", None)
    if char is None and isinstance(ent, dict):
        char = ent.get("character")

    def c(attr: str) -> str:
        if char is None:
            return ""
        v = getattr(char, attr, None)
        if v is None and isinstance(char, dict):
            v = char.get(attr)
        return str(v or "")

    we = getattr(ent, "world_entity", None)
    vis = str(getattr(we, "visibility", "") or "") if we is not None else ""
    return "|".join([c("name"), c("static_prompt"), c("dynamic_state"), c("aliases"), vis])


def _asset_sig_line(a: Any) -> str:
    we = getattr(a, "world_entity", None)
    vis = str(getattr(we, "visibility", "") or "") if we is not None else ""
    return "|".join([
        str(getattr(a, "name", "") or ""),
        str(getattr(a, "static_description", "") or ""),
        vis,
    ])


def _rel_sig_line(r: Any) -> str:
    src = getattr(r, "source_character", None)
    tgt = getattr(r, "target_character", None)
    return "|".join([
        (getattr(src, "name", "") or "") if src is not None else "",
        (getattr(tgt, "name", "") or "") if tgt is not None else "",
        str(getattr(r, "relationship_type", "") or ""),
        str(getattr(r, "description", "") or ""),
    ])


def _hook_sig_line(h: Any) -> str:
    if isinstance(h, dict):
        return str(h.get("content", "") or "")
    return str(getattr(h, "content", "") or "")


def _prefix_signature(bundle: Any) -> tuple:
    import json as _json

    chapter = getattr(bundle, "chapter", None)
    spine = getattr(chapter, "spine", None) if chapter is not None else None
    try:
        spine_hash = _json.dumps(spine, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        spine_hash = str(spine)
    return (
        str(getattr(bundle, "book_id", "") or ""),
        str(getattr(chapter, "id", "") or ""),
        getattr(bundle, "world_time", 0) or 0,
        str(getattr(chapter, "scene_location_id", None) or ""),
        spine_hash,
        _sig_hash("\n".join(_entity_sig_line(e) for e in (getattr(bundle, "entities", None) or []))),
        _sig_hash("\n".join(_asset_sig_line(a) for a in (getattr(bundle, "assets", None) or []))),
        # 势力通路（2026-09-04）：势力档案是恒选前缀内容源——改势力设定必须换签名，
        # 否则就是「改了设定舱/前缀不刷新」事故的下一个同类
        _sig_hash("\n".join(
            "|".join([
                str(getattr(f, "name", "") or ""),
                str(getattr(f, "static_prompt", "") or ""),
                "|".join(str(a) for a in (getattr(f, "aliases", None) or [])),
            ])
            for f in (getattr(bundle, "factions", None) or [])
        )),
        _sig_hash("\n".join(_rel_sig_line(r) for r in (getattr(bundle, "relationships", None) or []))),
        _sig_hash("\n".join(_hook_sig_line(h) for h in (getattr(bundle, "open_hooks", None) or []))),
        _sig_hash(_json.dumps(_worldview_items(getattr(bundle, "book", None)), ensure_ascii=False)),
        _sig_hash(str(getattr(bundle, "canon_context", "") or "")),
        _sig_hash(str(getattr(bundle, "previous_summary", "") or "")),
        # 折叠态摘要（在场/死亡判定输入——world_state 变化必须换前缀；
        # label 一并入键：状态行文案变化也是前缀渲染输入）
        _json.dumps(
            sorted(
                (str(cs.get("entity_id")), str(cs.get("alive")),
                 str(cs.get("location_id") or ""), str(cs.get("label") or ""))
                for cs in ((getattr(bundle, "world_state", None) or {}).get("character_states") or [])
            ),
            ensure_ascii=False,
        ),
    )


def build_knowledge_view(bundle: Any, active_scene: Optional[Dict] = None) -> KnowledgeView:
    """装配入口：条目化 → 选择（前缀冻结）→ 渲染（纯 CPU，零 DB 查询）。

    前缀部分（选择+渲染）走章内冻结缓存；提及扫描与 provenance 每调用
    新鲜——「什么随段变、什么章内冻结」在此落锚（B6 验收=prefix byte-equal）。
    active_scene（第三弹）：光标派生取景框——只影响**渲染面**的场景身份块/
    地点档案链（渲染每调用新鲜，不进前缀缓存）；选择面（场景恒选集）仍按
    本章钉（前缀冻结纪律不破）。
    """
    sig = _prefix_signature(bundle)
    cached = _PREFIX_CACHE.get(sig)
    if cached is None:
        entries = build_knowledge_entries(bundle)
        # 前缀选择不吃正文（提及走后缀）——空 text 选择=冻结语义
        selected, unselected, _ = select_knowledge(entries, bundle, "")
        cached = (selected, unselected, entries)
        if len(_PREFIX_CACHE) >= _PREFIX_CACHE_MAX:
            _PREFIX_CACHE.clear()
        _PREFIX_CACHE[sig] = cached
    selected, unselected, entries = cached
    # 渲染每调用新鲜（纯 CPU 且免跨调用污染：负面清单/温卡等 bundle 派生
    # 字段不进缓存）；提及扫描用当前正文——「随段变」只影响后缀行
    chapter_text = str(getattr(bundle, "content_text", "") or "")
    _, _, mentioned = select_knowledge(entries, bundle, chapter_text)
    kv = render_knowledge_view(bundle, selected, unselected, "", mentioned=mentioned,
                               active_scene=active_scene)
    # provenance 信封（B5）：同参同哈希
    from backend.services.world.reality_check import envelope

    kv.provenance = envelope(
        kind="knowledge_view",
        source_keys=kv.selected_keys,
        params={"sig": list(sig)},
    )
    return kv

# Velluma - 知识检索平面一期（Knowledge Retrieval Plane v3.1 · 一期）
# AGPL-3.0
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


@dataclass
class KnowledgeView:
    """选择+渲染后的知识视图（五模式/dock/预览共同消费）。"""
    scene_identity: str = ""            # 场景身份块（事实层头部）
    entities_text: str = ""             # 在场与相关人物块（含档案全文+此刻状态）
    worldview_text: str = ""            # 世界观块（条目完整）
    relations_text: str = ""            # 关系块（t 时刻活跃）
    negative_constraints: str = ""      # 负面清单约束块（四源合并全量）
    recency_pin: str = ""               # user 尾部「此刻·切记」重钉（3-5 行）
    previous_summary: str = ""          # 紧前一章摘要（恒选，不截断）
    # 审计面（预览「未选清单」与 trace 选择集记录的数据源）
    provenance: Dict[str, Any] = field(default_factory=dict)  # B5 信封
    selected_keys: List[str] = field(default_factory=list)
    present_names: List[str] = field(default_factory=list)
    dead_names: List[str] = field(default_factory=list)
    unselected: List[Dict[str, str]] = field(default_factory=list)

    def total_chars(self) -> int:
        return sum(len(x) for x in (
            self.scene_identity, self.entities_text, self.worldview_text,
            self.relations_text, self.negative_constraints,
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
                if scene_loc_id and str(cs.get("location_id") or "") == scene_loc_id:
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
    for loc in (getattr(bundle, "locations", None) or []):
        if str(getattr(loc, "id", "") or "") == loc_id:
            return str(getattr(loc, "name", "") or "")
    return ""


# ============================================================
# 选择器引擎（一期：场景恒选 / 在场 / 提及 / 作者显式；宁多勿漏）
# ============================================================

def select_knowledge(
    entries: List[KnowledgeEntry],
    bundle: Any,
    chapter_text: str,
) -> Tuple[List[KnowledgeEntry], List[Dict[str, str]]]:
    """对条目池跑一期选择器，返回 (选中条目有序列表, 未选清单)。

    选择器不对称原则（公理四）：宁多勿漏——误选由逃逸阀兜住，漏选无兜底。
    提及扫描窗=本章全文（docs §5 选择器 3：实体类临场事实的主要缓解手段）。
    """
    world_sourced = bool(getattr(bundle, "world_sourced", False))
    plain_text = re.sub(r"\s+", "", written_text(chapter_text or ""))

    selected: List[KnowledgeEntry] = []
    unselected: List[Dict[str, str]] = []
    selected_entity_titles: set = set()

    for e in entries:
        if e.kind == "worldview" or e.kind == "hook":
            # 恒选条目（选择器已标）
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
                e.selector = "提及（本章）"
                selected.append(e)
                selected_entity_titles.add(e.title)
                continue
            if not world_sourced:
                # legacy 模式：entities 本身就是作者章级绑定 = 作者显式选择
                e.selector = "作者显式·章级绑定"
                selected.append(e)
                selected_entity_titles.add(e.title)
                continue
            unselected.append({"key": e.key, "title": e.title, "reason": "未在场且未提及"})
            continue
        if e.kind == "relation":
            # 邻近选择：两端点均被选中才进（单端命中已在 world_bridge 排序提前）
            parts = e.title.split("↔")
            if len(parts) == 2 and parts[0] in selected_entity_titles and parts[1] in selected_entity_titles:
                e.selector = "邻近·在场一跳"
                selected.append(e)
            else:
                unselected.append({"key": e.key, "title": e.title, "reason": "端点未选中"})

    # 逃逸阀（丢整条，永不腰斩；硬层永不丢）：养料序=hook → relation → 提及实体
    total = sum(len(e.body) + len(e.title) for e in selected)
    if total > KG_BUDGET_CHARS:
        soft_order = [e for e in selected if not e.hard]
        # 丢弃序：hook 最先、relation 次之、提及实体最后
        rank = {"hook": 0, "relation": 1, "entity": 2, "asset": 2, "worldview": 3}
        soft_order.sort(key=lambda e: rank.get(e.kind, 2))
        dropped_keys = set()
        for e in reversed(soft_order):  # 从最不重要的一端开始丢
            if total <= KG_BUDGET_CHARS:
                break
            total -= len(e.body) + len(e.title)
            dropped_keys.add(e.key)
            unselected.append({"key": e.key, "title": e.title, "reason": "预算整条丢弃"})
        selected = [e for e in selected if e.key not in dropped_keys]

    # 渲染序：在场 → 死亡 → 提及/绑定（资产随实体序）→ 关系 → 伏笔；世界观单独块
    order_rank = {
        "entity": 0, "asset": 1, "relation": 2, "hook": 3, "worldview": 4,
    }
    selected.sort(key=lambda e: (
        order_rank.get(e.kind, 5),
        0 if (e.present or e.dead) else 1,
    ))
    return selected, unselected


# ============================================================
# UKV 渲染（时态标注 + 折叠态优先声明）
# ============================================================

def _indent_body(body: str, prefix_first: str) -> str:
    """多行档案体的缩进拼接（首行带标签，后续行两空格缩进）。"""
    lines = [ln for ln in (body or "").split("\n") if ln.strip()]
    if not lines:
        return ""
    return prefix_first + "\n".join([" " + lines[0]] + ["  " + ln for ln in lines[1:]])


def render_knowledge_view(bundle: Any, selected: List[KnowledgeEntry],
                          unselected: List[Dict[str, str]],
                          chapter_text: str = "") -> KnowledgeView:
    """渲染知识视图（完整注入；空数据=空串=块缺席=零变化）。"""
    kv = KnowledgeView(unselected=unselected)
    kv.previous_summary = str(getattr(bundle, "previous_summary", "") or "")

    # ---- 场景身份（场景恒选集的渲染面）----
    chapter = getattr(bundle, "chapter", None)
    scene_loc_id = str(getattr(chapter, "scene_location_id", None) or "")
    world_time = getattr(bundle, "world_time", 0) or 0
    world_time_source = str(getattr(bundle, "world_time_source", "zero") or "zero")
    loc_name = _location_name(bundle, scene_loc_id) if scene_loc_id else ""
    scene_bits = []
    if loc_name:
        scene_bits.append(f"本章场景：{loc_name}（作者钉定）")
    elif scene_loc_id:
        scene_bits.append("本章场景：已钉定（地点档案缺失）")
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

    # ---- 世界观（条目完整）----
    wv = [e for e in selected if e.kind == "worldview"]
    if wv:
        kv.worldview_text = "# 世界观（完整注入，未删节）\n" + "\n".join(f"- {e.body}" for e in wv)

    # ---- 关系（t 时刻活跃）----
    rel = [e for e in selected if e.kind == "relation"]
    if rel:
        kv.relations_text = "# 人物关系（此刻活跃）\n" + "\n".join(f"- {e.title}：{e.body}" for e in rel)

    # ---- 负面清单约束块（四源合并，全量；现状五 builder 不消费禁词的同构洞收编）----
    prohibitions = getattr(bundle, "prohibitions", None)
    if prohibitions is not None:
        try:
            words = prohibitions.words(10 ** 6)
            if words:
                kv.negative_constraints = "# 本书禁词（作者负面清单与系统陈词合并，硬约束）\n" + "、".join(words)
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


def kg_block_kwargs(kv: Any) -> Dict[str, str]:
    """知识视图 → render_system_blocks / builder 的块参数 dict。

    独立成函数（非仅 KnowledgeView 方法）：路由侧对装配结果做防御式
    取用（测试桩可能用 SimpleNamespace 伪造 ctx），任何缺失属性降级
    空串=块缺席=零变化。
    """
    return dict(
        scene_identity=str(getattr(kv, "scene_identity", "") or ""),
        entities_text=str(getattr(kv, "entities_text", "") or ""),
        worldview_text=str(getattr(kv, "worldview_text", "") or ""),
        relations_text=str(getattr(kv, "relations_text", "") or ""),
        negative_constraints=str(getattr(kv, "negative_constraints", "") or ""),
    )


def build_knowledge_view(bundle: Any) -> KnowledgeView:
    """装配入口：条目化 → 选择 → 渲染（纯 CPU，零 DB 查询）。"""
    entries = build_knowledge_entries(bundle)
    chapter_text = str(getattr(bundle, "content_text", "") or "")
    selected, unselected = select_knowledge(entries, bundle, chapter_text)
    return render_knowledge_view(bundle, selected, unselected, chapter_text)

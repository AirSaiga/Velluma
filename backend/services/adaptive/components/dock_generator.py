# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 挂件生发组件
"""
基于层 3 推测 + 设定养料，LLM 生发 3-4 个镜头特写挂件。

挂件是 6-12 字的物理画面碎片（"老烟用残手砸灭油灯"），不是角色名罗列、
不是抽象建议。作者吸附挂件 + Space 微缝合。

校对：挂件 vs 禁词/canon private/character static_prompt——违规挂件丢弃。
懒加载：projection 签名没变就不重算（orchestrator 据此判断）。
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from backend.services.context.settings_bundle import load_chapter_settings_bundle
from backend.services.llm.client import REASONING_DISABLED, call_llm_with_usage
from backend.services.adaptive.observing import get_adaptive_recorder
# 就近节拍共享判据（2026-08-25 提取：stitch 意图块同消费），私有别名保既有引用
from backend.services.adaptive.outline_nearby import (
    outline_line_written as _outline_line_written,
    outline_nearby as _outline_nearby,
)
from backend.services.prompts.adaptive_prompts import build_dock_generator_prompt
from backend.services.utils.json_safe import parse_json_safe

logger = logging.getLogger(__name__)


# 流水线版本盐值（2026-09-08 僵尸缓存修复）：挂件缓存持久化在
# WorldModelORM.layer3_projections（跨进程存活），而编排器签名只有文本/意图/
# 在场维度——代码重构后历史章节文本未变即命中库里的旧零件。此后任何规则
# 大改（槽位分类学/prompt 编译/在场制）递增本版本号，即可让库中陈旧
# __dock__ 缓存全量安全失效（签名侧 + 读取侧双侧生效）。
# v2.2（2026-09-13 B2 输入减肥批）：statics 注入整体移除 + 推测块降 1 条。
DOCK_PIPELINE_VERSION = "v2.3_suffix300_20260913"

# 意图衰老阈值（2026-09-09 时序冻结修复）：反推后正文推进超此字数未刷新
# → dock 视意图为陈旧（intent_stale），不绑定旧意图副行
INTENT_STALE_CHARS = 100


# ============================================================
# 在场宇宙投影（2026-09-08 红队「地面」——docs 溯源报告 R3）
# ============================================================
# dock 此前是五条生成路径里唯一不注入场景身份的：养料全池投喂（排序不裁剪），
# 「水泥灰/脚手架」凭空道具有三条合法逃逸（氛围件豁免/上手件出处含全书养料
# 池/模型不知道作者在哪）。本节为轻量消费侧投影——数据全部来自已加载的
# bundle（world_state 推演快照 + 场景钉 + 段落提及），零新增查询、零 knowledge_
# plane 全渲染（红队 R1 轻路径纪律：压缩投影 + 硬上限）。

ONSTAGE_MAX_ENTITIES = 8
ONSTAGE_MAX_PROPS = 6


def _adapter_name(e) -> str:
    """适配器/ORM/字典三态取名（world 桥适配器 / legacy 对象 / 快照 dict）。

    ⚠ 角色适配器（WorldEntityAdapter）**没有顶层 .name**——名字挂在
    ent.character.name 访问链（资产适配器才有顶层 .name）。2026-09-09 实测
    事故：只读顶层致在册人物恒空（在册只剩场景行），AGENTS 2026-08-26
    canon_watch 同款坑的复发（「勿再读顶层」）。口径对齐 settings_bundle.
    _entity_name，顶层优先、character 链兜底（资产/混合形态零破坏）。
    """
    n = getattr(e, "name", "") or ""
    if not n:
        ch = getattr(e, "character", None)
        if ch is not None:
            n = getattr(ch, "name", "") or (ch.get("name", "") if isinstance(ch, dict) else "") or ""
    if not n and isinstance(e, dict):
        n = e.get("name", "") or ""
    return str(n).strip()


def _adapter_aliases(e) -> List[str]:
    """别名三态读取（角色适配器的 aliases 同挂在 character 命名空间下）。"""
    al = getattr(e, "aliases", None)
    if al is None:
        ch = getattr(e, "character", None)
        al = getattr(ch, "aliases", None) if ch is not None else None
    if al is None and isinstance(e, dict):
        al = e.get("aliases")
    return [str(a).strip() for a in (al or []) if str(a).strip()]


def _adapter_private(e) -> bool:
    """整人私有判定（A1 双轨：private 实体不进在册名单——其档案走 secrets 通道）。"""
    we = getattr(e, "world_entity", None)
    vis = getattr(we, "visibility", None) if we is not None else None
    if vis is None:
        vis = e.get("visibility") if isinstance(e, dict) else None
    return (vis or "public") == "private"


def _adapter_entity_id(e) -> str:
    eid = getattr(e, "entity_id", "") or ""
    if not eid:
        we = getattr(e, "world_entity", None)
        eid = getattr(we, "id", "") if we is not None else ""
    if not eid and isinstance(e, dict):
        eid = e.get("entity_id") or e.get("id") or ""
    return str(eid or "")


def _adapter_dyn(e) -> str:
    """此刻状态行（适配器 character.dynamic_state；world 桥推演产物）。"""
    ch = getattr(e, "character", None)
    if ch is None and isinstance(e, dict):
        ch = e.get("character")
    dyn = getattr(ch, "dynamic_state", None)
    if dyn is None and isinstance(ch, dict):
        dyn = ch.get("dynamic_state")
    return str(dyn or "").strip()


def onstage_projection(bundle, scene_loc_id: str, recent_text: str):
    """本场在册压缩投影（纯函数）——T3 白名单 + anchor_ref 坐标系的原料。

    构成（红队 R3 三档物质性的 T3 界）：
    - 人物 = 场景钉作用域（含祖先链）内存活（world_state 推演）∪ 当前段落提及
      （名字或 ≥2 字别名命中）；私有实体不进册；
    - 物件 = 当前段落提及的资产（世界 fold 不携带资产位置——提及即在场）；
    - 场景行 = 钉定地点名 + intro 截 40 字（panorama 模板的定场质感来源）。

    退化梯子（红队 R4）：legacy 书（world_sourced=False）恒 None；在册/场景行
    全空 → None——onstage=None 时 prompt 走 legacy 形态（零变化契约）。
    """
    if not getattr(bundle, "world_sourced", False):
        return None
    recent = recent_text or ""
    world_state = getattr(bundle, "world_state", None) or {}
    char_states = {
        str(cs.get("entity_id")): cs
        for cs in (world_state.get("character_states") or [])
        if isinstance(cs, dict)
    }
    scene_scope = set()
    if scene_loc_id:
        try:
            from backend.services.world.location_tree import scene_scope_ids
            scene_scope = scene_scope_ids(getattr(bundle, "locations", None) or [], str(scene_loc_id))
        except Exception:
            scene_scope = set()

    def _mentioned(e) -> bool:
        if not recent:
            return False
        n = _adapter_name(e)
        if n and n in recent:
            return True
        return any(a in recent for a in _adapter_aliases(e) if len(a) >= 2)

    entities: List[Dict] = []
    off_chars: List[str] = []
    for e in (getattr(bundle, "entities", None) or []):
        name = _adapter_name(e)
        if not name or _adapter_private(e):
            continue
        cs = char_states.get(_adapter_entity_id(e)) or {}
        present = (
            bool(scene_scope)
            and bool(cs.get("alive", False))
            and str(cs.get("location_id") or "") in scene_scope
        )
        if present or _mentioned(e):
            if len(entities) < ONSTAGE_MAX_ENTITIES:
                entities.append({"name": name, "state": _adapter_dyn(e)})
        else:
            off_chars.append(name)

    props: List[Dict] = []
    off_assets: List[str] = []
    for a in (getattr(bundle, "assets", None) or []):
        name = _adapter_name(a)
        if not name or _adapter_private(a):
            continue
        if _mentioned(a):
            if len(props) < ONSTAGE_MAX_PROPS:
                desc = str(getattr(a, "static_description", "") or "").strip()
                props.append({"name": name, "desc": desc})
        else:
            off_assets.append(name)

    scene_line = ""
    if scene_loc_id:
        for loc in (getattr(bundle, "locations", None) or []):
            if str(getattr(loc, "id", "") or "") == str(scene_loc_id):
                intro = str(getattr(loc, "intro", "") or "").strip()
                scene_line = _adapter_name(loc) + (f"——{intro[:40]}" if intro else "")
                break

    # 临时在场通行证（2026-09-09）：正文高频未建档人名（明姐类）入册——
    # 标 is_guest，前端据此出「录入档案」入口；不占在册实体配额（附额 ≤2）
    _known = (
        {e["name"] for e in entities}
        | set(off_chars)
        | {p["name"] for p in props}
        | set(off_assets)
        | {_adapter_name(l) for l in (getattr(bundle, "locations", None) or [])}
    )
    # 注册别名并入抑制面（2026-09-13 别名一等公民补口）：非昵称形的注册
    # 别名此前不在 _known——正文提及时 _mentioned 让主实体经别名入册，但
    # guest 名单不认识别名 → 照发通行证 → 同台双身份（在册「流光」+guest
    # 「白露」）。别名是「已知名」，与主名同权进抑制面（≥2 字口径对齐
    # _mentioned 的别名命中）。
    for _src in (getattr(bundle, "entities", None) or [], getattr(bundle, "assets", None) or []):
        for _e in _src:
            _known.update(a for a in _adapter_aliases(_e) if len(a) >= 2)
    for g in detect_guest_names(recent, _known):
        entities.append({
            "name": g,
            "state": "正文高频出现 · 未建档（临时在场）",
            "is_guest": True,
        })

    if not entities and not props and not scene_line:
        return None
    return {
        "entities": entities,
        "props": props,
        "scene_line": scene_line,
        "offstage_characters": off_chars,
        "offstage_assets": off_assets,
    }


def presence_fingerprint(scene_loc_id, world_time) -> str:
    """dock 缓存签名的低频在场键（红队 R2）：钉 id + 叙事锚时刻。

    禁入 dynamic_state 全文（随沉淀抖动）与全章提及集（随他段打字高频失效）
    ——cur_text_sig 已覆盖最高频维度（当前段前 100 字+长度），本键只补
    「换景/换锚」两个人工节奏事件。纯函数；空值恒定（无钉书零失效增量）。
    """
    return f"{str(scene_loc_id or '-')}:{int(world_time or 0)}"


# ---- 末句对白判定（2026-09-09 末句优先原则）----
# 实测事故：段内夹杂回忆叙述把尾 300 字整窗的对话占比稀释到 0.2，段尾明明
# 停在对白上却降级 default。末句优先：最后一个非空行**整行以开引号起、闭引号
# 收** → 无条件 dialogue。名言引用（「他想起那句“人定胜天”」引号在句中）不
# 满足「行首开引号」——中文小说的对白行惯例整行以引号起，这是天然鉴别位。
_DIALOGUE_OPEN = ("“", "「", "『", "\"")
_DIALOGUE_CLOSE = ("”", "」", "』", "\"")


def ends_in_dialogue(text: str) -> bool:
    """末句对白判定（末句优先原则）：最后一个非空行以开引号起、闭引号收。"""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return False
    last = lines[-1]
    return len(last) >= 2 and last[0] in _DIALOGUE_OPEN and last[-1] in _DIALOGUE_CLOSE


# ---- 临时在场通行证（Guest Pass，2026-09-09 涌现角色闭环）----
# 实测事故：「明姐」只活在正文里（世界页无此实体），在册/场外永远看不见她
# ——分镜主体失明。此函数从当前段识别高频未建档人名：jieba NR 词性 或 中文
# 称谓后缀模式（X姐/X哥/X叔/X婶/X爷/X嫂…），≥2 次出现，排除已知名与泛称。
# 污染防线（红队 R4）：村子/路灯类普通名词不携 NR 词性也不称谓后缀，天然
# 排除；泛称亲属词（姐姐/哥哥…）停用；≤2 名封顶；通行证只是 prompt 素材
# （is_guest 标记 + 前端「录入档案」入口），不落库、不污染世界模型。
_GUEST_MAX = 2
_GUEST_MIN_FREQ = 2
_ADDRESS_SUFFIXES = ("姐", "哥", "叔", "婶", "姨", "爷", "嫂", "嫂", "婆", "郎")
_GUEST_STOPWORDS = {
    "姐姐", "哥哥", "弟弟", "妹妹", "阿姨", "大叔", "奶奶", "爷爷",
    "妈妈", "爸爸", "姑娘", "媳妇", "老人", "老头", "女人", "男人",
}


# 昵称前缀（阿X/小X/老X）：中文口语里最常见的人物指称变体——「阿尘啊」
# 说的就是林尘，不是第三个人
_NICK_PREFIXES = ("阿", "小", "老")


def _is_alias_or_ambiguous(name: str, known_names) -> bool:
    """别名与昵称归一化拦截（2026-09-11 排毒批「阿尘≠第三人」事故）。

    候选人名若是已知人物的昵称/尊称变体 → True（不发通行证）：
    - 阿X/小X/老X：核心字取**尾字**匹配（昵称取名字末字是中文惯例——
      阿尘→尾字「尘」命中林尘）；三字形式（阿明轩）核心两字取包含匹配。
    - X姐/X叔类尊称：剥后缀取前名，单字同样只配尾字（王叔→「王」命中
      「工头老王」；不会错绑「王阿婆」——尾字是婆）。
    **唯一命中才绑定；多命中=歧义（林尘/周尘并存时阿尘不知是谁）同样
    抑制通行证**——发证必致实体分裂+虚假建档，静默压制的最坏结果只是
    漏一枚芯片（作者仍可手动建档）；零命中返回 False（真·新人物照发，
    明姐流程不受染——「明」不命中任何尾字）。纯函数。
    """
    known = [str(k) for k in (known_names or []) if k]
    if not known or not name:
        return False
    core = None
    if len(name) == 2 and name[0] in _NICK_PREFIXES:
        core = name[1]
    elif len(name) == 3 and name[0] in _NICK_PREFIXES:
        core = name[1:]
    elif 2 <= len(name) <= 3 and name[-1] in _ADDRESS_SUFFIXES:
        core = name[:-1]
    if not core:
        return False
    if len(core) == 1:
        owners = [k for k in known if k.endswith(core)]
    else:
        owners = [k for k in known if core in k]
    return len(owners) >= 1


def detect_guest_names(recent_text: str, known_names) -> List[str]:
    """正文高频未建档人名识别（临时在场通行证）。纯算法，jieba 缺失退空。"""
    try:
        import jieba.posseg as pseg
    except Exception:
        return []
    # 已知名注入 jieba 词典（幂等）：专名恒为单 token，提名不被默认碎切拖累
    from backend.services.world.jieba_lexicon import register_terms
    register_terms(known_names or [])
    # 词性/称谓只负责**提名**；频次用子串计数核验——jieba 会把同一名字切成
    # 不同 token（实测第二处「明姐」被切成「明姐端」nr），token 频次对分词
    # 漂移零免疫，text.count 稳定（污染防线不变：提名人形仍须过 NR/称谓闸）
    candidates: List[str] = []
    for w, flag in pseg.cut(recent_text or ""):
        w = str(w).strip()
        if not (2 <= len(w) <= 4):
            continue
        is_name = (flag == "nr") or (len(w) <= 3 and w[-1] in _ADDRESS_SUFFIXES)
        if not is_name or w in _GUEST_STOPWORDS or w in set(known_names or []):
            continue
        # 别名归一拦截（2026-09-11）：昵称/尊称变体归入主实体或歧义压制，
        # 不发独立通行证——「阿尘啊」不把林尘分裂成两个人
        if _is_alias_or_ambiguous(w, known_names or []):
            continue
        if w not in candidates:
            candidates.append(w)
    text = recent_text or ""
    guests = [n for n in candidates if text.count(n) >= _GUEST_MIN_FREQ]
    guests.sort(key=lambda n: (-text.count(n), n))
    return guests[:_GUEST_MAX]


# 搏杀手势字（红队 R4 combat 判定；小而狠，勿堆叠——CAMERA_STOCK 同纪律）
_COMBAT_GESTURE_CHARS = ("砸", "劈", "踹", "撞", "扑", "掀", "掐", "掷", "揪", "摔")
# 入场手势（panorama 判定：初入新地的转场动作/视野词）
_ENTRY_GESTURES = ("推门", "走进", "踏入", "踏进", "抵达", "穿过", "眼前", "映入")


def pick_shot_template(recent_text: str, scene_line: str = "", suffix_anchor: str = "") -> str:
    """情境分镜模板选择（红队 R4；纯算法 0 LLM，异常/不确定回落 default）。

    优先序（2026-09-09 扩充）：**bridge（光标后有正文=中插桥接，位置事实最硬）
    > dialogue·末句优先（末行整行以引号起收——无条件点燃，防前文叙述稀释）
    > dialogue·占比（同一把尺子：对话占比>0.35，尾 300 字）> combat > panorama
    > default**。bridge 不依赖在场制（骨架跳写是光标位置事实，legacy 书同样
    受益）；其余场景模板仍仅在场制下分派（调用方纪律）。
    """
    try:
        if str(suffix_anchor or "").strip():
            return "bridge"
        tail = (recent_text or "")[-300:]
        if not tail.strip():
            return "default"
        if ends_in_dialogue(tail):
            return "dialogue"   # 末句优先：叙述稀释救不了末行整行引号
        from backend.services.style.scene_hint import SCENE_DIALOGUE, detect_scene_type
        if detect_scene_type(tail) == SCENE_DIALOGUE:
            return "dialogue"
        if sum(tail.count(c) for c in _COMBAT_GESTURE_CHARS) >= 3:
            return "combat"
        if (
            scene_line
            and any(g in tail for g in _ENTRY_GESTURES)
            and len(tail.strip()) <= 160
        ):
            return "panorama"
        return "default"
    except Exception:
        return "default"


# 上手动词族（T3 在场边界检的交互动词；与 prompt 上手件定义、ghost_guard
# out_of_scene 动词框架同族——小而狠）
_INTERACTION_VERBS = ("握", "拿", "放", "捡", "掏", "开", "抓", "拎", "举", "抄")


def find_onstage_boundary_hits(text: str, universe_names, onstage_names, recent_text: str):
    """T3 在场边界影子检（registry: dock-onstage-boundary，shadow 只落台账）。

    判据 = 非在册实体/资产名（≥2 字）× 上手动词共现（挂件 8-16 字，共现窗天然
    小于 ghost_guard 的 ±10 字口径）；正文已提及的名字豁免——作者自己写进来
    的不算模型编造。返回 [(name, verb)]。
    """
    hits: List[tuple] = []
    onstage = set(onstage_names or [])
    for name in (universe_names or []):
        if not name or len(name) < 2 or name in onstage or name in (recent_text or ""):
            continue
        if name in text:
            for v in _INTERACTION_VERBS:
                if v in text:
                    hits.append((name, v))
                    break
    return hits


async def _spine_intent(chapter_id: str, db) -> str:
    """章级谋篇意图一行（P1.4 M2；chapters 主键单行取，开销可忽略）。

    只在意图存在时返回；无脉络/查询失败返回空串（prompt 零变化）。
    """
    try:
        from backend.models import Chapter as _Chapter
        ch = await db.get(_Chapter, chapter_id)
        if ch is not None and isinstance(ch.spine, dict):
            return (ch.spine.get("intent") or {}).get("text", "") or ""
    except Exception:
        pass
    return ""


async def run(chapter_id: str, db, model_snapshot: Dict, budget_tokens: int = 1500, **kw) -> Dict:
    """挂件生发。由 orchestrator 调度，产出写回世界模型缓存。

    kw 可带 salience_hints（B7 热层具名提示，SALIENCE_DOCK_LANE 单车道注入）；
    direction_weights 已退役（B7 忽略；direction 标注仅存分析面）。
    """
    direction_weights = kw.get("direction_weights") or None  # 已退役（B7 忽略）
    # B7 热层单车道：dock 消费 salience 六槽热集的具名提示（A/B 闸：
    # SALIENCE_DOCK_LANE 常量翻转即回退；影子 trace 由 orchestrator 常开）
    salience_hints = kw.get("salience_hints") or None
    bundle = await load_chapter_settings_bundle(chapter_id, db)

    # 取作者当前段落：心跳实时段（orchestrator 停顿心跳透传）→ 正文尾部（剥 HTML）。
    # ⚠ 不用层 1 事实——历史沉淀在作者删改后即过期，曾致挂件锚定已删除文本。
    from backend.services.adaptive.paragraph_source import (
        resolve_current_paragraph, written_text,
    )
    recent_text = resolve_current_paragraph(kw.get("recent_text") or "", bundle.content_text or "")
    if not recent_text or len(recent_text) < 30:
        return {"skipped": True, "reason": "正文不足"}

    # 接缝裁剪（2026-08-27 导师裁决）：beat/after 素材不进挂件 prompt——
    # 对服从度有限的模型，切断供给比命令拒绝可靠（LLM 没见过的素材漏不出来；
    # 同哲学先例：serves_anchor 代码闸门「不信任 prompt 约束」）
    projections = _prebeat_projections(model_snapshot.get("projections", []))
    nutrients = bundle.nutrients()
    hard = bundle.hard_constraints()
    soft = bundle.soft_constraints()

    # 前情召回（记忆倒灌）：让「呼应前情细节」类零件有素材；失败降级为空不阻塞
    # k=2 见 budget 表（A3a 收编：挂件轻路径回响条数与 stitch 分档）
    # B3 分流去敏（2026-09-13）：V/B 流抹在场实体名（与 stitch 同口径）
    from backend.services.rag.recall import bundle_mask_names, recall_memories
    from backend.services.context.budget import ECHOES_K_DOCK
    memory_echoes = await recall_memories(
        db,
        book_id=bundle.book_id or "",
        chapter_id=chapter_id,
        chapter_number=bundle.chapter_number,
        query_text=recent_text[-300:],
        k=ECHOES_K_DOCK,
        mask_names=bundle_mask_names(bundle),
    )
    # 读者期待 + 大纲就近节拍：prompt 素材与 _finalize_parts 的 note 拼装共用
    reader_expectations = soft.get("reader_expectations") or None
    outline_nearby = _outline_nearby(
        getattr(bundle, "outline_text", "") or "",
        written_text(bundle.content_text or ""),
    )

    # 意图入舱（2026-09-03 意图加固批次）：无大纲就近节拍时，层 2 反推的
    # 下一步方向顶上 toward_beat 的「目的地」位。三级源链——作者写的
    #（spine_intent 行进 prompt / outline_nearby 供节拍）> 作者纠正的
    #（纠正手势落 spine.intent，同走作者道）> AI 猜的（此处，证据回查
    # 过了信度闸才放行；note 如实标注「AI 猜的」不伪装成作者材料）
    intent_guess = ""
    if not outline_nearby:
        from backend.services.adaptive.components.intent_inference import (
            DOCK_INTENT_MIN_CONFIDENCE,
        )
        _intent = model_snapshot.get("intent") or {}
        if _intent.get("source") == "inferred":
            # 意图衰老闸（2026-09-09 时序冻结修复）：反推后正文推进超 100 字
            # 未刷新 → 陈旧，不强行绑定旧意图（实测：跨场景 11 分钟，旧「往
            # 明姐家走」端给了室内场景）。word_count 来自心跳实时上报。
            _wc = kw.get("word_count")
            _pc = _intent.get("prose_chars")
            stale = (
                isinstance(_wc, int) and isinstance(_pc, int)
                and _wc - _pc > INTENT_STALE_CHARS
            )
            if not stale and float(_intent.get("confidence") or 0) >= DOCK_INTENT_MIN_CONFIDENCE:
                intent_guess = str(_intent.get("next_direction") or "").strip()

    # ---- 在场宇宙投影 + 情境模板（2026-09-08 红队「地面+重力场」）----
    # 场景取景框（第三弹 · 光标派生）：优先 orchestrator 派生结果（同函数同输入
    # 防重复算），缺省自算——本章钉作安全回退，正文最近转场命中则随笔尖流转
    # （docs/scene-transit-feasibility.md §3.1）。db 不可用（测试 None）时静默
    # 空钉——投影退化为纯提及制，梯子不塌。
    scene_loc_id = ""
    active_scene = None
    pre_cursor = ""
    try:
        from backend.models import Chapter as _Chapter
        _ch = await db.get(_Chapter, chapter_id)
        if _ch is not None:
            base_pin = str(getattr(_ch, "scene_location_id", "") or "")
            override = str(kw.get("active_loc_id") or "")
            if override:
                scene_loc_id = override
                active_scene = None  # orchestrator 已定景；via 不再重算（微标走心跳响应）
            else:
                from backend.services.utils.html_text import html_to_plain
                from backend.services.world.active_scene import (
                    pre_cursor_window, resolve_active_scene,
                )

                pre_cursor = pre_cursor_window(
                    html_to_plain(getattr(_ch, "content_text", "") or ""),
                    str(kw.get("recent_text") or ""),
                )
                active_scene = resolve_active_scene(
                    pre_cursor, getattr(bundle, "locations", None) or [], base_pin,
                )
                scene_loc_id = active_scene.loc_id
    except Exception:
        scene_loc_id = ""
    # 中插桥接锚（2026-09-09 FIM）：光标停在上下文之间时前端透传的后文边界窗
    # （2026-09-13 扩窗 120→300：旧窗+前端省略号截尾让后文物证缺席，幽灵写出
    # 与之矛盾的「路边有灯」；与 build_dock_generator_prompt 的 [:300] 同口径）
    suffix_anchor = str(kw.get("suffix_anchor") or "").strip()[:300]
    # 桥接供给切断（同 build_dock_generator_prompt 的 is_bridge 口径）：意图
    # 猜测以全文为坐标系推导，桥接态=后文剧透——prompt 猜测块与 toward_beat
    # 的 note 拼装兜底一并断供（实测：猜测端给的全是文末饭桌场景）
    if suffix_anchor:
        intent_guess = ""
    # 随行物延续（第三弹「上手即随行」）：在场投影的提及窗从「当前段 500」扩为
    # 「光标前扫描窗」——上一场被提及/上手的工具包换场后仍在册，脸盆与热饭随
    # 取景框合法入册；人物 fold 判定（scene_scope）不受影响，只是提及面变宽。
    mention_window = pre_cursor or recent_text
    onstage = onstage_projection(bundle, scene_loc_id, mention_window)
    # bridge 是光标位置事实，不依赖在场制——legacy 书（onstage None）同样分派
    if suffix_anchor:
        template = "bridge"
    elif onstage is not None:
        template = pick_shot_template(recent_text, (onstage or {}).get("scene_line", ""))
    else:
        template = "default"

    sys_p, usr_p = build_dock_generator_prompt(
        recent_text, projections, nutrients, hard,
        direction_weights=direction_weights,
        salience_hints=salience_hints,
        reader_expectations=reader_expectations,
        memory_echoes=memory_echoes or None,
        spine_intent=await _spine_intent(chapter_id, db),
        outline_nearby=outline_nearby,
        intent_guess=intent_guess,
        onstage=onstage,
        template=template,
        suffix_anchor=suffix_anchor,
    )

    try:
        result = await call_llm_with_usage(
            system_prompt=sys_p,
            user_prompt=usr_p,
            # 槽位归位（2026-09-15）：在场白名单匹配/三档物质性/结构化 JSON 编译
            # 是强逻辑任务，归分析槽（reasoning），与 intent_inference 同判据。
            # Tab 毫秒级唤醒要求延迟敏感：REASONING_DISABLED 必须保持——推理
            # 模型把脑力聚焦在「遵守在场约束与输出 JSON」而非深度思考链。
            model_type="reasoning",
            temperature=0.75,
            # 预算下限 1600（state_tracker 同款先例）：实测 deepseek 类推理模型
            # 无视 REASONING_DISABLED 照样烧 800-1000 隐藏思考 tokens，1500 下限
            # 会被思考挤占致 content 空 → 空舱。
            max_tokens=max(1600, budget_tokens),
            reasoning_config=REASONING_DISABLED,
        )
        get_adaptive_recorder(str(chapter_id)).record_result(
            "adaptive.dock_generator", result, model_slot="reasoning")
        parsed = parse_json_safe(result.content or "") or {}
        raw_parts = parsed.get("parts", [])

        # ---- 校对：丢弃违规挂件 + 功能槽位规整（source/note 贯通）----
        # 约束治理一期（2026-09-02）：camera/psych/rehash/beat_overlap 下沉为
        # 枚举原因的代码闸（violates 只剩 canon/blocker 禁词），丢件落
        # constraint_events 台账（丢什么、为什么——剂量与服从率度量的数据源）。
        _DROP_CONSTRAINT_IDS = {
            "not_dict": "dock-part-shape",
            "too_short": "dock-part-shape",
            "overflow_tail": "dock-part-shape",
            "violates_hard": "dock-banned-words",
            "camera_stock": "dock-camera-stock",
            "psych_word": "dock-no-psych",
            "rehash": "dock-rehash",
            "beat_overlap": "dock-beat-overlap",
            # 二期 shadow 双跑（只落台账不丢件）：语义抢拍 / ≥3 字面收紧候选
            "beat_rush_semantic": "dock-beat-rush-semantic",
            "beat_overlap_n3": "dock-beat-overlap",
            # T3 在场边界（2026-09-08 红队「地面」）：shadow 出生只落台账
            "onstage_violation": "dock-onstage-boundary",
            # 桥接撞车（2026-09-09 FIM）：live 丢件——下文事实是禁区
            "suffix_overlap": "dock-bridge-overlap",
        }

        def _on_drop(reason: str, text: str = "", outcome: str = "drop") -> None:
            try:
                from backend.services.constraints.events import log_constraint_event

                log_constraint_event(
                    str(bundle.book_id or ""), str(chapter_id),
                    _DROP_CONSTRAINT_IDS.get(reason, "dock-part-shape"),
                    outcome, reason=reason,
                    detail={"text": text[:20], "model": (model_snapshot.get("meta") or {}).get("model_name", "") if isinstance(model_snapshot, dict) else ""},
                )
            except Exception:
                pass  # 埋点绝不阻塞校对环

        valid_parts = _finalize_parts(
            raw_parts,
            outline_nearby=outline_nearby,
            intent_guess=intent_guess,
            reader_expectations=reader_expectations,
            memory_echoes=memory_echoes,
            violates=lambda t: _violates(t, hard),
            recent_text=recent_text,
            projections=projections,
            check_beat_overlap=True,
            on_drop=_on_drop,
            onstage=onstage,
            suffix_anchor=suffix_anchor,
        )

        # ---- 抢拍 shadow 双跑（约束治理二期，2026-09-02）：只落台账不丢件——
        # 与 live 的 ≥4 字面闸对拍攒校准数据，转正（改 registry status）后才执法。
        # ① 语义版：卡片 vs 就近节拍的向量重合（抓改写式抢拍：零字面重合但剧情
        #    被推完）；② ≥3 字面加强版：现役闸的收紧候选。未配置 embedding /
        #    任何失败静默跳过（菜单件生成绝不阻塞）。
        try:
            if outline_nearby and valid_parts:
                from backend.services.validation.semantic_overlap import (
                    BEAT_RUSH_SHADOW_THRESHOLD,
                    semantic_overlap_hits,
                )

                for _p in valid_parts:
                    _pt = str(_p.get("text") or "")
                    if not _pt:
                        continue
                    _sem = await semantic_overlap_hits(
                        _pt, outline_nearby, threshold=BEAT_RUSH_SHADOW_THRESHOLD)
                    if _sem:
                        _on_drop("beat_rush_semantic", _pt, outcome="hit")
                    if _beats_overlap_hit(_pt, outline_nearby, n=3):
                        _on_drop("beat_overlap_n3", _pt, outcome="hit")
        except Exception:
            pass  # shadow 埋点绝不阻塞校对环

        # ---- T3 在场边界影子检（2026-09-08 红队「地面」；shadow 只落台账不丢件）----
        # 非在册实体/资产名 × 上手动词共现 → 越界疑点进约束台账攒精确率
        # （FP<10% 且语料对拍全对才转 live 丢件——registry 生命周期纪律）。
        try:
            if onstage is not None and valid_parts:
                _onstage_names = (
                    [e["name"] for e in onstage.get("entities") or []]
                    + [p["name"] for p in onstage.get("props") or []]
                )
                _universe = [
                    n for n in (
                        _adapter_name(e)
                        for e in (getattr(bundle, "entities", None) or [])
                        if not _adapter_private(e)
                    ) if n
                ] + [
                    n for n in (
                        _adapter_name(a)
                        for a in (getattr(bundle, "assets", None) or [])
                        if not _adapter_private(a)
                    ) if n
                ]
                for _p in valid_parts:
                    _pt = str(_p.get("text") or "")
                    for _name, _verb in find_onstage_boundary_hits(
                        _pt, _universe, _onstage_names, recent_text,
                    ):
                        _on_drop("onstage_violation", _pt, outcome="hit")
        except Exception:
            pass  # shadow 埋点绝不阻塞校对环

        # 挂件产出缓存到世界模型（前端 heartbeat 响应里取）
        from backend.services.adaptive.world_model import WorldModelRepository
        repo = WorldModelRepository(db)
        sig = "|".join(p["key"] for p in valid_parts)
        await repo.set_dock_sig(chapter_id, sig)

        # 临时缓存挂件（写到一个临时字段供心跳读取——复用 layer3 的 metadata 思路）
        # 这里直接通过 db session 写一个内存 dict 给路由层取（路由层会重新拉一次）
        # 实际上前端拿挂件是通过 heartbeat 响应，我们把挂件存进 ORM 的临时字段
        _guest_names = [
            e["name"] for e in (onstage or {}).get("entities") or []
            if isinstance(e, dict) and e.get("is_guest")
        ]
        await _cache_dock_parts(db, chapter_id, valid_parts, guests=_guest_names)

        return {"count": len(valid_parts)}
    except Exception as e:
        logger.warning(f"[dock_generator] 失败: {e}")
        return {"error": str(e)}


# ============================================================
# 功能槽位规整（2026-08-29「不知所云」重构：provenance 贯通）
# ============================================================
# 四槽位与作者决策一一对应（导师裁决：内容分类学 → 功能分类学——
# 「这枚是什么题材」对选择毫无帮助，「选这枚会发生什么」才是答案）：
#   landing     接着写：作者最后一句的物理落点（固定 note，首位）
#   toward_beat 通往节拍：通往大纲就近节拍的第一步（note=节拍原文）
#   echo        呼应：前情/读者期待（note 按模型报的 echo_ref 回查素材原文拼装）
#   ambient     氛围：无叙事包袱（note 留白——留白本身是信息）
# note 一律后端拼装不经 LLM（mimo 服从度教训：模型自由创作出处=编造风险）；
# 槽位拿不到出处文本就降级 ambient（标签必须承载真实出处，否则不标）。
# 对白模板新增槽位（2026-09-08 红队 R4 分镜组）：reply=受话人接话微前兆
# （固定 note，无出处义务——锚的是对白本身）；prop=在场道具/人物特写
# （anchor_ref 指认在册序号，后端回查拼 note——echo_ref 同一防御哲学）。
# 前端 Phase 1 零改动：未知槽位值运行时自然降级（排序沉底/符号空/note 兜底）。
SOURCE_PRIORITY = {"landing": 0, "toward_beat": 1, "reply": 1, "echo": 2, "prop": 2, "ambient": 3}
_SLOTS = ("landing", "toward_beat", "reply", "echo", "prop", "ambient")


def _normalize_slot(p: Dict) -> str:
    """槽位归一：显式 slot 优先；旧契约 from_expectation → echo；其余 ambient。"""
    s = p.get("slot")
    if isinstance(s, str) and s in _SLOTS:
        return s
    if p.get("from_expectation"):
        return "echo"
    return "ambient"


def _clean_echo_note(raw: str) -> str:
    """把记忆/前情素材清洗成作者语言（2026-08-29 二轮实测：note 透传机器格式
    【前情事件·物品】第三章：… 对作者是乱码，还常被截断在格式中间）。

    剥【…】账本标签 → 「第N章：」规整为「第N章·」→ 去首尾杂 punctuation。
    【前情事件·物品】第三章：扳手砸中脚边铁屑 → 第三章·扳手砸中脚边铁屑
    """
    s = str(raw).strip()
    s = re.sub(r"^【[^】]*】", "", s)
    s = re.sub(r"^第([一二三四五六七八九十百零\d]+)章\s*[:：]\s*", r"第\1章·", s)
    return s.strip(" \t:：,，、;；")


def _assemble_note(slot: str, p: Dict, outline_nearby, reader_expectations, memory_echoes,
                   intent_guess: str = "", onstage: Dict = None) -> str:
    """按槽位拼装后果短语（后端权威，模型不经手出处文本）。

    文案纪律（2026-08-29 二轮）：副行必须回答「选它之后那一百字会写成什么」
    ——来历词（呼应/出处）只作谓语，不单独成句。
    意图入舱（2026-09-03）：无大纲节拍时 toward_beat 由方向猜测供料，
    note 如实标注「AI 猜的方向」——标签必须承载真实出处，猜测不伪装成大纲。
    分镜组（2026-09-08 红队 R4）：reply 固定 note（锚对白本身，无出处义务）；
    prop 由 anchor_ref 回查在册名单拼 note——指认失败即降级 ambient（勿谎标）。
    """
    if slot == "landing":
        return "接着刚才那句往下写"
    if slot == "reply":
        return "受话人先接住那句话"
    if slot == "prop":
        anchors = list((onstage or {}).get("entities") or []) + list((onstage or {}).get("props") or [])
        try:
            ref = int(p.get("anchor_ref") or 0)
        except (TypeError, ValueError):
            ref = 0
        if 1 <= ref <= len(anchors):
            return f"镜头对准「{anchors[ref - 1].get('name')}」"
        return ""
    if slot == "toward_beat":
        beats = [str(b).strip() for b in (outline_nearby or []) if b and str(b).strip()]
        if beats:
            return f"往「{beats[0][:10]}」那拍走的第一步"
        guess = (intent_guess or "").strip()
        if guess:
            # 优雅截断（2026-09-09 修复）：旧 guess[:10] 硬切曾断在「往明|姐家」
            # 人名中间读作乱码——改为 12 字窗内向句读/助词回退，仍超长补省略号
            cut = guess[:12].rstrip("，。、；：的着了在向往和去把被")
            return f"往「{cut}{'…' if len(guess) > len(cut) else ''}」那个方向试试（AI 猜的）"
        return ""
    if slot == "echo":
        try:
            ref = int(p.get("echo_ref") or 0)
        except (TypeError, ValueError):
            ref = 0
        if ref >= 1:
            if p.get("from_expectation"):
                descs = [
                    (e.get("description") or "").strip()
                    for e in (reader_expectations or [])
                    if isinstance(e, dict) and (e.get("description") or "").strip()
                ]
                if ref <= len(descs):
                    return f"暗示读者在等：{descs[ref - 1][:12]}"
            elif p.get("from_memory"):
                echoes = [str(e).strip() for e in (memory_echoes or []) if e and str(e).strip()]
                if ref <= len(echoes):
                    cleaned = _clean_echo_note(echoes[ref - 1])
                    if cleaned:
                        return f"顺笔带出前情：{cleaned[:12]}"
        return ""
    return ""


def _finalize_parts(
    raw_parts: List,
    *,
    outline_nearby=None,
    intent_guess: str = "",
    reader_expectations=None,
    memory_echoes=None,
    violates=None,
    recent_text: str = "",
    projections=None,
    check_beat_overlap: bool = False,
    on_drop=None,
    onstage: Dict = None,
    suffix_anchor: str = "",
) -> List[Dict]:
    """校对 + 槽位规整 + note 拼装 + 槽位序排序（landing 首位）。

    violates(text) → True 的碎片丢弃（canon private/blocker 禁词，调用方
    注入判定）。旧形状（无 slot）碎片照常通过：槽位归一 ambient、无
    note——缓存里的历史零件/旧模型产出零破坏。

    约束治理一期（2026-09-02）：校对环从单一 violates 扩为枚举原因链——
    camera_stock / psych_word / rehash / beat_overlap 依次判定，on_drop
    (reason, text[, outcome]) 回调供台账埋点（None = 不埋，纯函数性不变）。
    reason 枚举：not_dict/too_short/violates_hard/camera_stock/psych_word/
    rehash/beat_overlap/overflow_head/overflow_tail；overflow_* 的 outcome
    =trim（过采样配额消化），与 drop=违规 分列（P2-1）。
    """
    icon_map = {"action": "👤", "scene": "⚙️", "line": "💬"}
    valid_parts: List[Dict] = []

    def _drop(reason: str, text: str = "", outcome: str = "drop") -> None:
        if on_drop is not None:
            try:
                on_drop(reason, text, outcome)
            except Exception:
                pass  # 埋点绝不阻塞校对环

    raw_all = raw_parts or []
    for overflow in raw_all[6:]:  # 输入截断（P2-1：过采样时代 7+ 枚不再静默消失）
        _drop("overflow_head", str(getattr(overflow, "get", lambda *_: "")("text") or "")[:20]
              if isinstance(overflow, dict) else "", outcome="trim")
    for p in raw_all[:6]:
        if not isinstance(p, dict):
            _drop("not_dict")
            continue
        text = (p.get("text", "") or "").strip()
        if not text or len(text) < 2:
            _drop("too_short", text)
            continue
        if violates and violates(text):
            _drop("violates_hard", text)
            continue
        if _has_camera_stock(text):
            _drop("camera_stock", text)
            continue
        if _has_psych_stock(text):
            _drop("psych_word", text)
            continue
        if recent_text and _is_rehash(text, recent_text, projections):
            _drop("rehash", text)
            continue
        if check_beat_overlap and _beats_overlap_hit(text, outline_nearby):
            _drop("beat_overlap", text)
            continue
        # 桥接撞车闸（2026-09-09 FIM 红队 R2）：机位文本与后文锚重叠 = 提前
        # 消耗下文已写的事实 → 丢件。2026-09-13 换动词门判据（_suffix_overlap_
        # hit）：纯景物名词的 4-5 字共现豁免——旧 n=4 无差别复用曾致卡片舱
        # 选项饥饿（后文「窗纸透出」× 卡片「望向窗纸透出的微光」即丢件）
        if suffix_anchor and _suffix_overlap_hit(
            text, suffix_anchor,
            onstage_names=[e.get("name") for e in ((onstage or {}).get("entities") or [])]
            + [p.get("name") for p in ((onstage or {}).get("props") or [])],
        ):
            _drop("suffix_overlap", text)
            continue
        kind = p.get("type", "action")
        # direction 校验：必须是 5 方向之一，否则回退到"环境"（分析面元数据，
        # 前端已不渲染——2026-08-29 不知所云重构：退役字段不再上屏）
        direction = p.get("direction", "环境")
        if direction not in ("主线", "伏笔", "刻画", "环境", "关系"):
            direction = "环境"
        slot = _normalize_slot(p)
        note = _assemble_note(slot, p, outline_nearby, reader_expectations, memory_echoes,
                              intent_guess=intent_guess, onstage=onstage)
        # 槽位拿不到出处 → 降级 ambient（留白而非谎标）；prop 指认失败同判
        if slot in ("toward_beat", "echo", "prop") and not note:
            slot = "ambient"
            note = ""
        # 截断到 16 字（prompt 允许 8-14 字，留余量防超长产出被生生截断）
        safe_text = text[:16]
        valid_parts.append({
            "key": f"{slot}:{safe_text[:12]}",
            "kind": kind,
            "icon": icon_map.get(kind, "✨"),
            "text": safe_text,
            "direction": direction,
            "source": slot,
            **({"note": note} if note else {}),
            # 期待账本衍生件标记（分析面；前端 echo note 取代了旧「期待」tag）
            **({"origin": "expectation"} if p.get("from_expectation") else {}),
        })
    # 槽位序排序（landing 首位 → toward_beat → echo → ambient；稳定排序）
    valid_parts.sort(key=lambda p: SOURCE_PRIORITY.get(p["source"], 3))
    for overflow in valid_parts[4:]:
        # outcome=trim（P2-1）：保 4 截断是过采样的配额消化，与 drop=违规 分列
        _drop("overflow_tail", overflow.get("text") or "", outcome="trim")
    return valid_parts[:4]


# 大纲就近节拍已提取共享（services/adaptive/outline_nearby.py，2026-08-25：
# stitch 意图块同消费）。保留私有别名——test_dock_nearby.py 等既有引用零改动。

# ---- 接缝裁剪（2026-08-27 导师裁决）：节拍边界是挂件取材的时间锚线 ----
# 推测组件按 prompt 契约为每幅画面标 stage（now/approach/beat/after）；
# beat/after（节拍事件本身及其后）不进挂件取材池——碎片 3「工头拍肩」+
# 4「弯腰捡书」曾把整条节拍弧预写完，作者连吸两枚一次 Space 就把自己的
# 转折点写穿了。切断供给 > 命令拒绝。
def _prebeat_projections(projs: list) -> list:
    """过滤掉节拍侧（beat/after）的推测，只留此刻（now）与逼近（approach）。

    降级策略：显式 beat/after 标注可信（直接丢弃，不占「首幅宽容」位）；
    缺标/乱标时首幅宽容视为 now（推测契约首幅必为 now）、其余保守视为
    节拍侧丢弃——宁可菜单薄，不可抢拍。
    纯函数：编排器的 dock 缓存签名同源消费（签名必须基于过滤后集合，
    否则裁剪变化不触发重算）。
    """
    keep: list = []
    seen = 0
    for p in projs or []:
        if not isinstance(p, dict) or p.get("__dock__") or p.get("__canon_watch__"):
            continue
        beats = p.get("possible_beats") or []
        stage = beats[0].get("stage") if beats and isinstance(beats[0], dict) else None
        if stage in ("beat", "after"):
            seen += 1
            continue
        if stage not in ("now", "approach") and seen > 0:
            seen += 1
            continue
        seen += 1
        keep.append(p)
    return keep


# 陈词嗅探清单（2026-08-27）：走神镜头/远景虚化家族——感知层菜单的第一眼
# 不能带生成层都在禁的库存词。保持小而狠（<10），勿堆叠。
CAMERA_STOCK_PHRASES = (
    "目光失焦", "望向远处", "望向远方", "轮廓模糊", "视线模糊",
    "瞳孔", "目光深邃", "目光空洞",
)

# 心理词族嗅探（2026-09-02 约束治理一期）：prompt 铁律「禁心理描写」的代码
# 侧执法（同一约束双层执法，registry 用同一 constraint_id 关联——
# dock-no-psych layers=[prompt, code_gate]）。与 CAMERA_STOCK 同构，小而狠。
PSYCH_STOCK_PHRASES = (
    "心中一紧", "感到不安", "心头一沉", "心里发慌", "暗自庆幸",
    "心中窃喜", "涌起一股", "不由得害怕",
)


def _has_camera_stock(text: str) -> bool:
    """碎片文本是否命中镜头陈词库存（命中即弃，校对环消费）。"""
    return any(w in text for w in CAMERA_STOCK_PHRASES)


def _has_psych_stock(text: str) -> bool:
    """碎片文本是否命中心理描写词族（命中即弃，校对环消费）。"""
    return any(w in text for w in PSYCH_STOCK_PHRASES)


def _is_rehash(text: str, recent_text: str, projections: list) -> bool:
    """碎片是否照搬推测原文/复述刚写的画面（dock-rehash 代码闸）。

    prompt 侧「不得整句照搬推测/不复述已写」对中档模型服从不足（2026-08-25
    实测 mimo 把推测逐条压缩成挂件）——下沉为 n-gram 重叠判定：碎片对
    最近正文或任一推测原文的 3 字片段命中率 ≥0.5（或整串捷径）即判照搬。
    text_match.matches 共享判据，无素材时返回 False（不误伤）。
    """
    from backend.services.adaptive.text_match import matches

    if recent_text and matches(text, recent_text, threshold=0.5):
        return True
    for p in (projections or []):
        if not isinstance(p, dict):
            continue
        for b in (p.get("possible_beats") or [])[:2]:
            if not isinstance(b, dict):
                continue
            event_text = str(b.get("event") or "").strip()
            if event_text and matches(text, event_text, threshold=0.5):
                return True
    return False


def _beats_overlap_hit(text: str, outline_nearby: list, n: int = 4) -> bool:
    """碎片与就近节拍原文去标点后存在 ≥n 字连续重叠（dock-beat-overlap 闸）。

    抢拍 = 碎片把节拍事件本身的措辞写出来了（「写完它，那一拍就被消费掉」）。
    供给侧切断（_prebeat_projections）后模型仍看得到就近节拍文本——这是
    残余风险的确定性兜底。任何 n 字滑窗命中即等价于 ≥n 连续公共子串。
    n=4 为现役 live 口径；n=3 仅供二期 shadow 收紧候选对拍（不落执法）。
    ⚠ 2026-09-13 起 suffix 闸不再复用本函数（改 _suffix_overlap_hit 动词
    门）——节拍没有「合法引用」语义，n=4 无差别判据对本闸维持。
    """
    from backend.services.adaptive.text_match import FRAGMENT_INVALID_CHARS

    def _clean(s: str) -> str:
        return "".join(c for c in (s or "") if c not in FRAGMENT_INVALID_CHARS)

    cleaned = _clean(text)
    if len(cleaned) < n:
        return False
    for beat in (outline_nearby or []):
        beat_clean = _clean(str(beat))
        if not beat_clean:
            continue
        for i in range(len(cleaned) - (n - 1)):
            if cleaned[i: i + n] in beat_clean:
                return True
    return False


# ---- suffix_overlap 动词门（2026-09-13 卡片舱选项饥饿修复）----
# 旧判据复用 _beats_overlap_hit n=4 无差别：后文常规景物名词（「窗纸透出」）
# 被卡片当环境锚点引用（「望向窗纸透出的微光」）即丢件——无补采机制下
# 卡片舱严重饥饿（仅剩 1-2 枚）。分诊判据见 _suffix_overlap_hit。
_SUFFIX_OVERLAP_N_STRICT = 4
_SUFFIX_OVERLAP_N_NOUN = 6
# 情节动作字（事件骨架——抢拍的本质是把后文事件提前演）。感知动词（望/看/
# 瞧/听）不入表：主体感知不推进事件，且正是「引用后文景物」的合法动作。
_SUFFIX_ACTION_CHARS = set(
    "端拿放递接抛甩拽拖推抢砸劈踹撞扑掀掐掷揪摔追赶奔跑窜逃攀登跨踩踢"
    "握拎抄揉搓洗擦拂扛挑背抱搂扶拉扯牵挽解扣喊叫骂说答问吼嚷咳喘吃喝"
    "念读写画涂点摇头低头弯俯仰靠倚蹲站坐躺卧翻身冲钻挤翻越跳落坠滚跌"
    "爬起收拾扎捆缠绕点烧浇泼洒吹敲塞填挖刨撬拧旋按捏掐摩揉"
)
# 安全字符（景物名词/器物/虚词——窗口完全由此构成=场景锚点共现）；运行期
# 并入在册实体名字符（_suffix_overlap_hit 的 onstage_names 参数）。
_SUFFIX_SAFE_CHARS = set(
    "的了着是在与和及之于上下中里外前后左右进出开关闭合门窗纸光灯光影"
    "声风雪霜雾烟尘土沙石砖瓦木铁铜钢锡铝锌路桥墙院顶棚檐板桌椅凳床柜"
    "灶锅碗盆瓶罐壶杯烛火柴禾草树花叶枝根藤天云星月日山河溪泉井田地村"
    "庄镇街道缝隙洼积透映照飘浮沉亮暗黄白黑红青蓝灰绿紫褐湿干冷热暖旧"
    "新半满空玉金银珠玻璃晶翡翠玛瑙钻线绳布帛绸缎皮革毛羽翅爪尾角骨血"
    "肉皮衣袍袖裤鞋袜帽冠带扣环链盒"
)


def _suffix_overlap_hit(text: str, suffix: str, onstage_names=None) -> bool:
    """dock 卡片 vs 后文锚的抢拍判定（动词门 + 名词豁免，2026-09-13）。

    分诊：
    ① 任一 ≥4 字重合窗口含情节动作字 → 事件抢跑，丢件（「明姐端来脸盆」）；
    ② 任一重合窗口 ≥6 字 → 难以「巧合引用」解释，丢件；
    ③ 4-5 字窗口完全由安全字符（_SUFFIX_SAFE_CHARS ∪ 在册实体名字符）
       构成 → 场景锚点共现，豁免——后文景物被卡片当环境锚引用是合法行为；
    ④ 其余 4-5 字窗口保守丢件（非安全构成=性质不明的重合）。

    onstage_names：在册实体/资产名（调用方从 onstage 投影传入）——名字
    字符并入安全集，卡片引用在册物件不因后文提及同一物件而丢件。
    """
    from backend.services.adaptive.text_match import FRAGMENT_INVALID_CHARS

    def _clean(s: str) -> str:
        return "".join(c for c in (s or "") if c not in FRAGMENT_INVALID_CHARS)

    t = _clean(text)
    s = _clean(str(suffix or ""))
    n = _SUFFIX_OVERLAP_N_STRICT
    if len(t) < n or len(s) < n:
        return False
    safe = set(_SUFFIX_SAFE_CHARS)
    for name in (onstage_names or []):
        for ch in _clean(str(name or "")):
            if ch:
                safe.add(ch)
    for i in range(len(t) - n + 1):
        if s.find(t[i: i + n]) < 0:
            continue
        length = n
        while i + length < len(t) and s.find(t[i: i + length + 1]) >= 0:
            length += 1
        window = t[i: i + length]
        if length >= _SUFFIX_OVERLAP_N_NOUN:
            return True
        if any(ch in _SUFFIX_ACTION_CHARS for ch in window):
            return True
        if all(ch in safe for ch in window):
            continue  # 场景锚点共现，豁免
        return True
    return False


def _violates(text: str, hard: Dict) -> bool:
    """校对挂件是否违规（canon private 泄密 / blocker 级硬禁词）。

    severity 分级（2026-08-25 A2）：提醒级词只进 prompt 软提醒与审计统计，
    不在生成侧硬拦——曾因提醒级词（角色名误录负面清单）把锚定挂件全部
    静默丢弃。banned_words_blocker 键缺失（手工构造的 hard dict）回退
    banned_words 全量，保持旧行为。
    """
    for label in hard.get("canon_private_labels", []):
        if label and len(label) >= 2 and label in text:
            return True
    if "banned_words_blocker" in hard:
        banned = hard.get("banned_words_blocker") or []
    else:
        banned = hard.get("banned_words", [])
    for word in banned:
        if word and len(word) >= 2 and word in text:
            return True
    return False


async def _cache_dock_parts(db, chapter_id: str, parts: List[Dict], guests: List[str] = None):
    """把挂件缓存到世界模型（存 layer3_projections 的伴生字段）。

    由于 WorldModelORM 没有专门的 dock_parts 字段，复用 layer3_projections
    的最后一项作为缓存载体（带 __dock__ 标记，前端/路由据此识别）。
    guests（2026-09-09 临时通行证）：在册里的 is_guest 名单随件缓存——路由侧
    提取进心跳响应 onstage_guests，前端出「录入档案」直达入口。
    """
    from sqlalchemy import select
    from backend.models import WorldModelORM
    result = await db.execute(select(WorldModelORM).where(WorldModelORM.chapter_id == chapter_id))
    model = result.scalar_one_or_none()
    if model is None:
        return
    # 挂件缓存放进 layer3_projections 末尾的特殊项（带流水线版本章——读取侧
    # _extract_dock_parts 据此过滤陈旧版本，签名侧 orchestrator 同源比对）
    projections = list(model.layer3_projections or [])
    # 移除旧 dock 缓存
    projections = [p for p in projections if not (isinstance(p, dict) and p.get("__dock__"))]
    projections.append({
        "__dock__": True, "parts": parts, "ver": DOCK_PIPELINE_VERSION,
        "guests": list(guests or []),
        "ts": __import__("time").time(),
    })
    model.layer3_projections = projections

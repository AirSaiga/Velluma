# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""光标派生取景框（Intra-Chapter Scene Transit · 2026-09-14 第三弹）。

文学的空间单元是场景/镜头而非章节——一章一地（chapters.scene_location_id）
在 500 字跨三地时白名单与穿越闸严重错位（docs/reports/scene-transit-feasibility.md
第二期报告）。本模块把「当前写的是哪场」做成**光标位置的派生视图**：

    resolve_active_scene(光标前文本, 地点名册, 本章钉) -> ActiveScene

设计不变量（第二期 §3.1 的穿透审查结论）：
- **无状态纯函数**——从光标向前扫最近一次「转场动词×名册地点名」命中；
  删改/回滚/FIM 分叉天然正确（重算即得），不做漂移状态机；
- **目标必须在名册内**——「回到过去」类比喻目标不在地点表，命中失败保持
  原景（专名约束是天然防漂闸）；
- **命中句须已完结**——地名之后到文本尾存在句末标点才算转场成立（作者正在
  写的「走进明姐家厨」半截短语不引发切换；这是无状态滞回，配合 dock 只在
  停顿档重算的 4s 天然节流，三层防抖不需要跨请求状态）；
- **闪回豁免**——命中所在句含回忆词（scene_visibility.FLASHBACK_WORDS 同源）
  则跳过该命中继续向左找更早的非闪回转场；
- 无命中 → 安全回退本章显式钉（base_loc_id），再无 → 无景（derived=False）。

判定复用纪律：转场动词表以 scene_visibility.LOCATION_JUMP_VERBS 为基
（11 词，本为幽灵稿穿越「报警」用途——第二期审计指出它是守门员不是导航员，
此处给它导航职责并扩充室内转场动词）；边界复核/闪回词/归一化全部 import
共享实现，禁止另写滑窗（text_match 前车之鉴）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.services.context.scene_visibility import (
    FLASHBACK_WORDS,
    _FLASHBACK_YEARS_RE,
    _norm,
)

# 基础转场动词（与幽灵稿穿越闸同源——导航与守门共用一张表，语义天然一致）
from backend.services.context.scene_visibility import LOCATION_JUMP_VERBS

# 室内/微观转场扩充（第二期任务书点名）：正文高频进门动词，穿越闸不管它们
# （守门只拦「跨作用域的大地点名」），导航需要。
TRANSIT_EXTRA_VERBS: Tuple[str, ...] = ("推门", "跨进", "拐进", "摸进", "闪进")
TRANSIT_VERBS: Tuple[str, ...] = LOCATION_JUMP_VERBS + TRANSIT_EXTRA_VERBS

# 动词与地点名之间允许的填充字数（「走进了北岸」「赶回那座要塞」）——与
# scene_visibility.LOCATION_JUMP_FILLER_CHARS 同值，此处独立声明防跨模块耦合
_FILLER_CHARS = 2

# 光标前扫描窗：覆盖 2-3 次场内转场；更早的转场属于更早场景（回退本章钉）。
# 性能：名册 ≤100 名 × 2000 字 C 级扫描 + 少量边界复核，微秒~毫秒级。
ACTIVE_SCENE_WINDOW_CHARS = 2000

# 句末标点（命中句完结判定；与 fingerprint 切句同族但含分号/换行——转场句
# 用分号收束同样算成立）
_SENTENCE_END_RE = re.compile(r"[。！？；;!?…\n]")

NAME_MIN_CHARS = 2  # 与 scene_visibility.NAME_MIN_CHARS 同口径

# ---- 微观空间姿态（Spatial Posture · 2026-09-16 双层修正第四批）----
# 名册匹配的死板性补丁：作者只建宏观据点（村子），正文写「推开门」时名册里
# 根本没有「厨房」——地名匹配必然失败。姿态层从正文逆扫**微观空间动势词**，
# 叠加在宏观据点之上（村子 · 室内生活），作者不为任何房间建档即自然换景。
# 纯词表 0 LLM；最右命中绝对优先（后期「进屋」覆盖早期「修车棚」）。
POSTURE_KINDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # 室内/居所 → 室内生活
    ("indoor_living", ("推开门", "推门", "进了屋", "进屋", "屋内", "屋里", "房里", "室内", "灶台", "桌边", "桌前", "床沿", "炕上", "掀帘")),
    # 工棚/维修 → 维修工位
    ("workshop", ("修车棚", "工棚", "车间", "机箱", "机房", "扳手", "柴油")),
    # 室外/街巷 → 室外街巷
    ("street", ("巷口", "街上", "路上", "泥泞", "冷风", "夜色", "大路", "门外")),
)
POSTURE_LABELS: Dict[str, str] = {
    "indoor_living": "室内生活",
    "workshop": "维修工位",
    "street": "室外街巷",
}

# ---- 正文活跃者（Active Actors · 2026-09-16 双轨在场）----
# 世界事件推演只认有显式事件的角色——正文里端水端饭说了四段话的明姐被物理
# 抹杀。本组词表把「光标窗内作为说话人/交互对象/动作主」的已知角色无条件
# 计入镜头前名单（纯代码 0 LLM；闪回句豁免防「想起远方的老张」误入镜）。
_ACTOR_WINDOW_CHARS = 500   # 任务书口径：光标前 500 字窗
_ACTOR_MAX = 6
_SPEAK_VERBS: Tuple[str, ...] = ("说", "道", "问", "答", "喊", "叫", "骂", "笑", "叹", "应", "开口", "嘀咕", "嘟囔", "低声")
_INTERACT_PREPS: Tuple[str, ...] = ("给", "向", "对", "朝", "替", "帮", "跟", "与", "拉", "扶")
_ACT_VERBS: Tuple[str, ...] = ("端", "递", "拿", "放", "提", "搬", "倒", "盛", "夹", "添", "斟", "坐", "站", "转", "抬头", "低头", "点头", "摇头")
_QUOTE_CHARS: Tuple[str, ...] = ("“", "「", "『", "《")
_POSTURE_KIND_BY_CUE: Dict[str, str] = {cue: kind for kind, cues in POSTURE_KINDS for cue in cues}


@dataclass
class ActiveScene:
    """派生结果：loc_id 空串 = 无景（derived=False 且无钉）。

    posture（2026-09-16）：微观空间姿态 {kind,label,cue}——地名匹配失败但正文
    有空间动势时叠加在宏观据点上（此时 derived=True，宏观回退钉）；有地名命中
    且姿态 cue 更靠后时作为补充后缀。None = 无姿态信息（逐字节旧语义）。
    """

    loc_id: str = ""
    loc_name: str = ""
    derived: bool = False  # True=正文推导；False=回退本章钉/无钉
    via: str = ""          # 触发证据（「走进·明姐家厨房」），台账/微标用
    posture: Optional[dict] = None

    def as_dict(self) -> dict:
        return {
            "loc_id": self.loc_id,
            "loc_name": self.loc_name,
            "derived": self.derived,
            "via": self.via,
            "posture": self.posture,
        }


def _verb_prefix_match(prefix: str) -> Optional[str]:
    """名前缀是否以「转场动词（+≤2 字填充）」结尾；返回命中的动词。

    与 scene_visibility._match_jump_verb 同语义、动词表参数化为 TRANSIT_VERBS
    （含室内扩充）——不改动原函数（约束治理纪律：守门口径零变化）。
    """
    for v in TRANSIT_VERBS:
        if prefix.endswith(v):
            return v
        for filler in range(1, _FILLER_CHARS + 1):
            if len(prefix) > filler and prefix[:-filler].endswith(v):
                return v
    return None


def _sentence_of(text: str, pos: int, end: int) -> str:
    """切出包含 [pos, end) 的句子（按句末标点向两侧扩；闪回豁免的扫描单元）。"""
    left = 0
    for m in _SENTENCE_END_RE.finditer(text[:pos]):
        left = m.end()
    m_right = _SENTENCE_END_RE.search(text, end)
    right = m_right.start() if m_right else len(text)
    return text[left:right]


def _location_name_index(locations: Iterable[Any]) -> List[Tuple[str, str]]:
    """名册展开：(名, loc_id) 列表——正名 + ≥2 字别名，别名归主。

    无坐标地点（内部构造房间）同样入册：取景框跟的是叙事位置，不是上图与否。
    """
    index: List[Tuple[str, str]] = []
    for loc in locations or []:
        loc_id = str(getattr(loc, "id", "") or "")
        name = str(getattr(loc, "name", "") or "").strip()
        if not loc_id or len(name) < NAME_MIN_CHARS:
            continue
        index.append((name, loc_id))
        for a in getattr(loc, "aliases", None) or []:
            alias = str(a or "").strip()
            if len(alias) >= NAME_MIN_CHARS and alias != name:
                index.append((alias, loc_id))
    return index


# 动词紧邻检查的前缀窗：最长动词 + 填充上限（预计算，热路径免 max()）
_VERB_LOOKBEHIND = max(len(v) for v in TRANSIT_VERBS) + _FILLER_CHARS


def _scan_posture(text: str) -> Optional[Tuple[int, str, str]]:
    """微观姿态逆扫（纯函数）：全词表最右命中 → (pos, cue, kind)。

    三道闸与地名转场同纪律：
    - **最右绝对优先**——不分类别取位置最大者（后期「进屋」覆盖早期「修车棚」）；
    - **命中句须已完结**——cue 之后到文本尾须有句末标点（正在写的半截不动）；
    - **闪回豁免**——命中句含回忆词/「N年前」则跳过、向左找次右命中。
    """
    hits: List[Tuple[int, str, str]] = []
    for cue, kind in _POSTURE_KIND_BY_CUE.items():
        start = 0
        while True:
            pos = text.find(cue, start)
            if pos < 0:
                break
            hits.append((pos, cue, kind))
            start = pos + 1
    if not hits:
        return None
    for pos, cue, kind in sorted(hits, key=lambda h: h[0], reverse=True):
        if not _SENTENCE_END_RE.search(text, pos + len(cue)):
            continue  # 半截句防抖
        sentence = _sentence_of(text, pos, pos + len(cue))
        if any(w in sentence for w in FLASHBACK_WORDS) or _FLASHBACK_YEARS_RE.search(sentence):
            continue  # 闪回里的空间不算当前镜头
        return pos, cue, kind
    return None


def resolve_active_scene(
    pre_cursor_text: str,
    locations: Iterable[Any],
    base_loc_id: Optional[str] = None,
) -> ActiveScene:
    """光标派生取景框（纯函数）：最近一次合法转场命中 → 活动地点。

    Args:
        pre_cursor_text: 光标前文本（调用方负责取窗，见 pre_cursor_window）。
        locations: 地点名册（bundle.locations / WorldRepository 行均可，鸭子类型）。
        base_loc_id: 本章显式钉（无命中时的安全回退）。

    Returns:
        ActiveScene——derived=True 表示正文推导命中（地名转场，或名册无此房
        但姿态词成立）；False 表示回退钉（loc_id=base_loc_id，名册里查得到名
        则带名）或无景。姿态（posture）在有地名命中且 cue 更靠后时作为补充。
    """
    text = _norm(pre_cursor_text)
    if not text:
        return _fallback_scene(locations, base_loc_id)

    posture_hit = _scan_posture(text)

    index = _location_name_index(locations)
    if not index:
        # 名册为空（或名册里根本没有「厨房」这类房间）——姿态层独立成立：
        # 宏观回退钉/无景，微观姿态照常派生（derived=True）
        return _posture_scene(posture_hit, locations, base_loc_id)

    # 收集全部命中并按位置聚组：同位置的嵌名（「明姐家」⊂「明姐家厨房」）取最长
    hits: dict = {}
    for name, loc_id in index:
        start = 0
        while True:
            pos = text.find(name, start)
            if pos < 0:
                break
            start = pos + 1
            end = pos + len(name)
            prev = hits.get(pos)
            if prev is None or len(name) > len(prev[0]):
                hits[pos] = (name, loc_id, end)

    # 从最右命中向左找第一个「动词紧邻 + 句已完结 + 非闪回」的合法转场
    for pos in sorted(hits.keys(), reverse=True):
        name, loc_id, end = hits[pos]
        verb = _verb_prefix_match(text[max(0, pos - _VERB_LOOKBEHIND):pos])
        if verb is None:
            continue
        # 命中句须已完结：地名之后到文本尾存在句末标点（正在写的半截短语不切换）
        if not _SENTENCE_END_RE.search(text, end):
            continue
        # 闪回豁免：命中所在句含回忆词/「N年前」→ 跳过，继续向左找非闪回转场
        sentence = _sentence_of(text, pos, end)
        if any(w in sentence for w in FLASHBACK_WORDS) or _FLASHBACK_YEARS_RE.search(sentence):
            continue
        scene = ActiveScene(loc_id=loc_id, loc_name=name, derived=True, via=f"{verb}·{name}")
        # 地名命中后作者继续往里走（cue 位置更靠后）→ 姿态作为补充后缀
        if posture_hit and posture_hit[0] > pos:
            scene.posture = _posture_dict(posture_hit)
        return scene

    return _posture_scene(posture_hit, locations, base_loc_id)


def _posture_dict(hit: Tuple[int, str, str]) -> dict:
    _, cue, kind = hit
    return {"kind": kind, "label": POSTURE_LABELS[kind], "cue": cue}


def _posture_scene(
    posture_hit: Optional[Tuple[int, str, str]],
    locations: Iterable[Any],
    base_loc_id: Optional[str],
) -> ActiveScene:
    """无合法地名命中时的收尾：姿态成立 → 宏观回退钉 + 微观姿态（derived=True）。

    被闪回/半截句否决的地名命中**不**约束姿态参评——姿态只凭自身三闸成立
    （曾有 loc_hit_pos 约束参数，两个调用点恒传 -1 沦为死代码，2026-09-17
    随文档与实现对齐一并摘除）。
    """
    if posture_hit is None:
        return _fallback_scene(locations, base_loc_id)
    scene = _fallback_scene(locations, base_loc_id)
    scene.derived = True
    scene.posture = _posture_dict(posture_hit)
    scene.via = f"{posture_hit[1]}·{POSTURE_LABELS[posture_hit[2]]}"
    return scene


def _fallback_scene(locations: Iterable[Any], base_loc_id: Optional[str]) -> ActiveScene:
    """无命中：回退本章钉（名册查名，查不到名也给 id——调用方各自容忍）。"""
    if not base_loc_id:
        return ActiveScene()
    base = str(base_loc_id)
    for loc in locations or []:
        if str(getattr(loc, "id", "") or "") == base:
            return ActiveScene(loc_id=base, loc_name=str(getattr(loc, "name", "") or ""), derived=False)
    return ActiveScene(loc_id=base, derived=False)


def pre_cursor_window(
    chapter_plain_text: str,
    anchor_text: str,
    window_chars: int = ACTIVE_SCENE_WINDOW_CHARS,
) -> str:
    """从章节纯文本取「光标前扫描窗」（尾部锚定协议）。

    前端心跳的 recent_text 是光标段前 500 字（段级口径，dock 生发语义不能动），
    本函数用它做**尾部锚定**：在章文本里找 anchor 尾段的最后出现，锚点前
    ≤window_chars 字即光标前窗。锚为空/找不到 → 章尾窗（写作通常在章尾，
    FIM 中插的锚是光标前文同样适用）。

    纯文本由调用方剥好（html_to_plain 唯一权威）；两侧都走 _norm 归一，
    空白差异不影响锚定。
    """
    plain = _norm(chapter_plain_text)
    if not plain:
        return ""
    anchor = _norm(anchor_text)
    tail = anchor[-80:] if len(anchor) > 80 else anchor
    end = -1
    if len(tail) >= 8:  # 尾段过短无区分度（跨段重复短语易锚错），走整锚/章尾
        i = plain.rfind(tail)
        if i >= 0:
            end = i + len(tail)
    if end < 0 and len(anchor) >= 8:
        i = plain.rfind(anchor)
        if i >= 0:
            end = i + len(anchor)
    if end < 0:
        end = len(plain)  # 找不到锚（改写中/异步未落库）→ 章尾窗
    return plain[max(0, end - window_chars):end]


# ============================================================
# 正文活跃者（Active Actors · 2026-09-16 双轨在场第四批）
# ============================================================

def _entity_display_terms(e: Any) -> Tuple[str, List[str]]:
    """(显示名, 匹配词表)——正名 + ≥2 字别名；非角色/私有实体返回空名。"""
    if str(getattr(e, "entity_type", "character") or "character") != "character":
        return "", []
    if str(getattr(e, "visibility", "public") or "public") == "private":
        return "", []
    name = str(getattr(e, "name", "") or "").strip()
    if len(name) < NAME_MIN_CHARS:
        return "", []
    terms = [name]
    for a in getattr(e, "aliases", None) or []:
        alias = str(a or "").strip()
        if len(alias) >= NAME_MIN_CHARS and alias != name:
            terms.append(alias)
    return name, terms


def known_name_terms(entities: Iterable[Any]) -> List[str]:
    """已建档角色名册词表（正名+别名展平）——**双轨身份同构的单一来源**：

    微观取景器（orchestrator 实时 guest 识别）与宏观名册（scene_slice 全章
    扫描）都必须用它喂 detect_guest_names 的 known_names——同一份词表保证
    两层对「明姐」的判定（是否未建档/是否别名归主）逐字节一致，不发生
    一层当 guest 一层不当的分裂。
    """
    terms: List[str] = []
    seen: set = set()
    for e in entities or []:
        display, ts = _entity_display_terms(e)
        if not display:
            # 非角色/私有实体不入角色名册词表（资产名撞人名的边界各调用方自理）
            continue
        for t in ts:
            if t not in seen:
                seen.add(t)
                terms.append(t)
    return terms


def dedupe_guest_names(guests: List[str]) -> List[str]:
    """guest 名单包含去重（分词伪影治理）：「明姐端」是 jieba 把「明姐+端来」
    切成 nr 词的伪影（子串计数对它免疫——count(明姐端) 也 ≥2，与真名同时
    拿到通行证）。规则：一个 guest 完整包含另一个 guest → 丢长留短。
    微观/宏观两调用点共用本函数（身份同构的一部分），dock 内部行为不动。
    """
    items = [str(g or "").strip() for g in guests or [] if g]
    out: List[str] = []
    for g in items:
        if any(g != k and k in g for k in items):
            continue  # 被更短的真名包含 → 伪影出局
        out.append(g)
    return out


def extract_active_actors(
    window_text: str,
    entities: Iterable[Any],
    window_chars: Optional[int] = _ACTOR_WINDOW_CHARS,
    max_actors: int = _ACTOR_MAX,
) -> List[Dict[str, str]]:
    """光标窗内的正文活跃者（纯函数 0 LLM，双轨在场的「正文轨」）。

    判定=正向模式门槛（纯提及不够，防「想起远方的老张」式误入镜）：
    - **对白**：名后 ≤2 字内是说话动词（明姐说/明姐道…），或紧跟冒号引号；
    - **交互**：名前 ≤3 字内是交互介词（给/向/对/朝/替/帮/跟/与/拉/扶）；
    - **动作**：名后 ≤3 字内是身体动作动词（端/递/拿/放…——明姐端肉即入镜）；
    - **在场**：窗内出现 ≥2 次且窗内有引号（对白语境的高频在场者）。

    闪回防线：出现所在句含 FLASHBACK_WORDS/「N年前」→ 该次出现不计（与地名
    转场同闸）；泛称路人天然出局（不在实体名册）。别名命中归正名显示。
    window_chars=None → 全章模式（不截尾，宏观名册用）；max_actors 同步放宽。
    """
    text = _norm(window_text or "")
    if window_chars:
        text = text[-window_chars:]
    if not text:
        return []
    has_dialogue = any(q in text for q in _QUOTE_CHARS)
    out: List[Dict[str, str]] = []
    seen: set = set()
    for e in entities or []:
        display, terms = _entity_display_terms(e)
        if not display or display in seen:
            continue
        occ_total = 0
        via = ""
        for term in terms:
            start = 0
            while True:
                pos = text.find(term, start)
                if pos < 0:
                    break
                start = pos + 1
                occ_total += 1
                if via:
                    continue
                end = pos + len(term)
                sentence = _sentence_of(text, pos, end)
                if any(w in sentence for w in FLASHBACK_WORDS) or _FLASHBACK_YEARS_RE.search(sentence):
                    continue  # 回忆里的人不在镜头前
                after = text[end:end + 2]
                act_after = text[end:end + 3]  # 动作允许宾语提前（「把碗递」「将茶端」）
                before = text[max(0, pos - 3):pos]
                if any(v in after for v in _SPEAK_VERBS) or text[end:end + 1] in ("：", ":"):
                    via = "对白"
                elif any(p in before for p in _INTERACT_PREPS):
                    via = "交互"
                elif any(v in act_after for v in _ACT_VERBS):
                    via = "动作"
        if not via and occ_total >= 2 and has_dialogue:
            via = "在场"
        if via:
            seen.add(display)
            out.append({
                "name": display,
                "via": via,
                "entity_id": str(getattr(e, "id", "") or ""),
            })
            if len(out) >= max_actors:
                break
    return out

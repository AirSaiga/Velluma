# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""光标派生取景框（Intra-Chapter Scene Transit · 2026-09-14 第三弹）。

文学的空间单元是场景/镜头而非章节——一章一地（chapters.scene_location_id）
在 500 字跨三地时白名单与穿越闸严重错位（docs/scene-transit-feasibility.md
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
from typing import Any, Iterable, List, Optional, Tuple

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


@dataclass
class ActiveScene:
    """派生结果：loc_id 空串 = 无景（derived=False 且无钉）。"""

    loc_id: str = ""
    loc_name: str = ""
    derived: bool = False  # True=正文推导；False=回退本章钉/无钉
    via: str = ""          # 触发证据（「走进·明姐家厨房」），台账/微标用

    def as_dict(self) -> dict:
        return {
            "loc_id": self.loc_id,
            "loc_name": self.loc_name,
            "derived": self.derived,
            "via": self.via,
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
        ActiveScene——derived=True 表示正文推导命中；False 表示回退钉
        （loc_id=base_loc_id，名册里查得到名则带名）或无景。
    """
    text = _norm(pre_cursor_text)
    if not text:
        return _fallback_scene(locations, base_loc_id)

    index = _location_name_index(locations)
    if not index:
        return _fallback_scene(locations, base_loc_id)

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
        return ActiveScene(loc_id=loc_id, loc_name=name, derived=True, via=f"{verb}·{name}")

    return _fallback_scene(locations, base_loc_id)


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

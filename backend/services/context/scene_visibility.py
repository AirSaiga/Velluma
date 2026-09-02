# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 场景可见性共享判据（2026-09-02 约束治理一期）
"""
输入侧专名过滤与输出侧越界检测的**同一份判据源**。

- scene_visible_proper_nouns：称呼表白名单（原 stitch_context 内联函数迁入，
  原处 re-export 保持引用面；2026-09-01 穿帮修复的输入侧）。
- out_of_scene 检测判据（ghost_guard 第五检消费）：非白名单实体名 × 上手级
  动词框架共现——与 dock「氛围件/上手件」两分法同一份动词表（导师审查：
  判定库共用，杜绝两侧口径漂移）。

输入侧（喂什么）与输出侧（收什么）用同一个函数算白名单——运行期数据流走
参数透传（stitch 路由把 ctx.proper_nouns 递给 check_ghost_text），不重算。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# 上手级动词框架（导师定档 12-16 个）：实体名被写成「可上手对象」的物理
# 操纵动词。负面清单纪律：光/运动类动词（闪过/划过/亮起/流转）**永不进表**
# ——它们挡住普通名词型实体名（流光/曙光/繁星）的绝大部分误报。
HANDLING_VERBS: Tuple[str, ...] = (
    "握", "攥", "拿", "拎", "放", "捡", "掏", "拧", "修", "砸",
    "按", "推", "拉", "驾驶", "登上",
)
# 名字与动词的最大距离（去空白归一文本上计）。±8 是「典型 2-6 字」的理论
# 估计；事故语料实证：标志样本「把流光左腿关节的螺栓给我拧紧了」名-动距离
# =9——按真实数据定 10（regression_corpus 准入即测试，改窗口先跑语料库）。
VERB_WINDOW_CHARS = 10
# 名字最短长度（1 字名子串误报率不可接受，与 ghost_guard.NAME_MIN_CHARS 同口径）
NAME_MIN_CHARS = 2

# 闪回豁免词：命中即降级 log-only（outcome=exempt, reason=flashback），连
# shadow warning 都不产——信号流里豁免命中与真命中分两列，promote 评估对照。
FLASHBACK_WORDS: Tuple[str, ...] = (
    "那年", "当年", "从前", "曾经", "记忆中", "回忆起", "想起",
    "当时", "仿佛", "梦里", "听说",
)
_FLASHBACK_YEARS_RE = re.compile(r"\d+年前|[一二三四五六七八九十]+年前")
# 豁免扫描窗：命中所在句（按句末标点切）——回指词通常与越界句同句
_SENTENCE_SPLIT_RE = re.compile(r"[。！？；;!?]+")
# jieba 可选（缺失退子串柔性红线——与 canon_watch._name_in_text 同纪律）
try:
    import jieba as _jieba

    _jieba.initialize()
except Exception:  # pragma: no cover - jieba 缺失环境
    _jieba = None


def _norm(text: str) -> str:
    """去空白归一（与知识平面提及扫描同口径；窗口/重叠计算都在归一文本上）。"""
    return re.sub(r"\s+", "", text or "")


def _name_in_text(name: str, text: str) -> bool:
    """专有名词 vs 分词边界匹配（canon_watch._name_in_text 同款纪律）：
    连续 token 拼接恰为该词才算命中，杜绝「流光石」「流光溢彩」嵌词误报；
    jieba 缺失退子串匹配（柔性红线，宁多勿漏）。"""
    if not name or not text:
        return False
    if _jieba is not None:
        tokens = [t for t in _jieba.cut(text) if t.strip()]
        for i in range(len(tokens)):
            acc = ""
            for j in range(i, min(i + 6, len(tokens))):
                acc += tokens[j]
                if acc == name:
                    return True
                if len(acc) > len(name):
                    break
        return False
    return name in text


def scene_visible_proper_nouns(
    bundle: Any,
    kg: Any,
    intent_text: str = "",
    rolling_prefix: str = "",
    fragment: str = "",
    after_text: str = "",
) -> List[str]:
    """专名称呼表按「模型可见文本」过滤（2026-09-01 穿帮修复）。

    事故：旧实现 bundle.proper_nouns() 是书级全量（全部角色名+资产名），块头
    却写「在场实体专名（硬约束）：必须原样使用」——小模型把名单当登场指令，
    把不在场的敌方机甲硬编成主角正在修的螺丝（trace 实证：《最终武装》第 1 章
    开篇工头喊「把流光左腿关节的螺栓拧紧」；8-20 起十几轮稳定复现）。修复后
    与知识平面同口径：

    - world 书：保留 在场（present_names）∪ 已死亡（dead_names——闪回提及时
      称呼仍须一致）∪ 本章提及（mentioned_names——画布全文扫描）∪ 点名在
      本次模型可见文本（就近节拍/滚窗/碎片）的名字。
    - **after_text 泄漏手术（2026-09-02）**：知识平面的提及扫描吃全章画布，
      细纲胶囊文中部扩写时光标**后**的文本会把「未来实体」泄进 mentioned
      名单——仅在 after 区出现、光标前可见文本未出现的名字从名单剔除。
    - legacy 书（world_sourced=False）：实体即作者章级显式绑定，全量保留
      （零变化契约）。
    - kg 视图为空（构建失败降级 / 无任何实体信息）时回退全量——降级不劣于
      旧行为。

    挂账残留（docs/constraint-governance.md）：①recency_pin「本章提及」行
    同样带 after-only 名（knowledge_plane 侧，本期不动）；②outline user
    prompt 本就含 after_text 原文（双端锚定，预期行为）。

    副作用：无（纯函数；bundle/kg 只读）。
    """
    candidates = bundle.proper_nouns()
    if not candidates:
        return []
    if not getattr(bundle, "world_sourced", False):
        return candidates
    if not (list(getattr(kg, "selected_keys", None) or []) or list(getattr(kg, "unselected", None) or [])):
        return candidates
    base = set(getattr(kg, "present_names", None) or [])
    base.update(getattr(kg, "dead_names", None) or [])
    mentioned = set(getattr(kg, "mentioned_names", None) or [])
    visible_norm = _norm("".join([intent_text or "", rolling_prefix or "", fragment or ""]))
    visible_hits = {n for n in candidates if n in visible_norm}
    if after_text:
        # P2-3（导师实施审查）：剔除条件收紧为「仅出现于 after 区」——画布
        # **前文**（光标之前的全部正文，可见窗只是它的尾部）出现过的名字是
        # 既定事实，即使同时出现在 after 区也保留（称呼一致性锚）。
        from backend.services.adaptive.paragraph_source import written_text

        after_norm = _norm(after_text)
        full_norm = _norm(written_text(getattr(bundle, "content_text", "") or ""))
        pos = full_norm.rfind(after_norm)
        before_norm = full_norm[:pos] if pos >= 0 else full_norm  # 定位失败=保守不剔
        mentioned -= {
            n for n in mentioned
            if n in after_norm and n not in visible_hits and n not in base
            and n not in before_norm
        }
    allowed = base | visible_hits | mentioned
    return [n for n in candidates if n in allowed]


# ============================================================
# out_of_scene 检测判据（ghost_guard 第五检消费；shadow 出生）
# ============================================================

def find_out_of_scene_hits(
    text: str,
    visible_names: List[str],
    all_names: List[str],
) -> List[Dict[str, Any]]:
    """越界实体登场检测：非白名单实体名 × 上手级动词框架共现。

    - 白名单 = visible_names（与称呼表同一份过滤产物，路由透传不重算）；
    - 候选全集 = all_names（书级实体+资产名）；裸查名字命中必死（谈论/转述/
      预告合法）——只有「名字 × 上手动词」邻接才算越界登场形态；
    - 闪回豁免：命中所在句含时间回指词 → 不产疑点（由调用方记 exempt 事件）。

    返回 [{name, verb, sentence, exempt}]；纯函数零 IO。
    """
    hits: List[Dict[str, Any]] = []
    norm_text = _norm(text)
    if not norm_text:
        return hits
    visible = {n for n in (visible_names or []) if n}
    hidden = [
        n for n in (all_names or [])
        if n and len(n) >= NAME_MIN_CHARS and n not in visible
    ]
    # 句切一次复用（豁免判定按命中所在句）
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(norm_text) if s]
    for name in hidden:
        start = 0
        while True:
            idx = norm_text.find(name, start)
            if idx < 0:
                break
            start = idx + 1
            # P1-1（导师实施审查）：token 边界复核——裸 substring 会把「流光石/
            # 流光溢彩」这类嵌词放进候选；对命中邻域复跑分词边界判据。
            # （已知残余：jieba 把「流光溢彩」切成「流光+溢彩」时边界复核放行，
            # 普通名词义残余属一期声明接受的误伤面，shadow 数据说话。）
            if not _name_in_text(name, norm_text[max(0, idx - 2): idx + len(name) + 2]):
                continue
            window = norm_text[max(0, idx - VERB_WINDOW_CHARS): idx + len(name) + VERB_WINDOW_CHARS]
            verb = next((v for v in HANDLING_VERBS if v in window), None)
            if verb is None:
                continue
            sentence = next((s for s in sentences if name in s), "")
            exempt = any(
                w in sentence or _FLASHBACK_YEARS_RE.search(sentence)
                for w in FLASHBACK_WORDS
            ) if sentence else False
            hits.append({
                "name": name,
                "verb": verb,
                "sentence": sentence[:40],
                "exempt": exempt,
            })
            break  # 同名只报首个命中（宁漏勿误，防同段反复报）
    return hits


# ============================================================
# location_jump 检测判据（ghost_guard 第六检消费；shadow 出生，2026-09-02 二期）
# ============================================================

# 转场动词框架：「动词+地点名」邻接才算空间跳转形态——裸查地点名必死
# （谈论/回忆/远眺合法）。与 HANDLING_VERBS 同纪律：小而狠，光/运动类词不进表。
LOCATION_JUMP_VERBS: Tuple[str, ...] = (
    "回到", "来到", "走进", "走入", "进入", "踏入", "迈进",
    "抵达", "赶回", "赶到", "前往",
)
# 动词与地点名之间允许的填充字数（「走进了北岸」「赶回那座要塞」）
LOCATION_JUMP_FILLER_CHARS = 2


def _match_jump_verb(prefix: str) -> Optional[str]:
    """名前缀是否以「转场动词 + ≤2 字填充」结尾（「走进了北岸」「赶回要塞」）；
    返回命中的动词，未命中 None。填充窗窄化是防误报主闸（转场语义由动宾
    紧邻承载，宽窗必误报）。"""
    for v in LOCATION_JUMP_VERBS:
        if prefix.endswith(v):
            return v
        for filler in range(1, LOCATION_JUMP_FILLER_CHARS + 1):
            if len(prefix) > filler and prefix[:-filler].endswith(v):
                return v
    return None


def find_location_jump_hits(
    text: str,
    off_scene_locations: List[str],
) -> List[Dict[str, Any]]:
    """地点穿越检测：转场动词 × 场景作用域外已知地点名邻接共现。

    - 候选 = 作用域外地点名表（调用方算好闭包传入：自身+祖先+后裔合法，
      其余世界地点为候选——本函数不感知树结构）；
    - 判据 = 地点名紧跟转场动词（≤2 字填充）——「走进北岸要塞」。距离窗
      比 out_of_scene 窄得多：转场语义由动宾紧邻承载，宽窗必误报；
    - 边界复核与闪回豁免同 out_of_scene 同一份判据（嵌词/回忆不命中）。

    返回 [{name, verb, sentence, exempt}]；纯函数零 IO。
    """
    hits: List[Dict[str, Any]] = []
    norm_text = _norm(text)
    if not norm_text:
        return hits
    names = [
        n for n in (off_scene_locations or [])
        if n and len(n) >= NAME_MIN_CHARS
    ]
    if not names:
        return hits
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(norm_text) if s]
    for name in names:
        start = 0
        while True:
            idx = norm_text.find(name, start)
            if idx < 0:
                break
            start = idx + 1
            if not _name_in_text(name, norm_text[max(0, idx - 2): idx + len(name) + 2]):
                continue
            verb = _match_jump_verb(norm_text[max(0, idx - 6): idx])
            if verb is None:
                continue
            sentence = next((s for s in sentences if name in s), "")
            exempt = any(
                w in sentence or _FLASHBACK_YEARS_RE.search(sentence)
                for w in FLASHBACK_WORDS
            ) if sentence else False
            hits.append({
                "name": name,
                "verb": verb,
                "sentence": sentence[:40],
                "exempt": exempt,
            })
            break  # 同名只报首个命中（同 out_of_scene 纪律）
    return hits

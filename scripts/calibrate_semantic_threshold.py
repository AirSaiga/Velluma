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

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
语义阈值校准脚本（约束治理 F3，手动小工具，不进 CI；报告落
docs/reports/semantic-threshold-calibration.md）。

覆盖三个语义阈值（均为拍脑袋占位，本脚本用真实语料测分离度定档）：
1. style        文风语义扫描  SEMANTIC_HIT_THRESHOLD = 0.78
                （services/style/semantic_match.py，挂 /adaptive/finish）
2. beat-rush    抢拍 shadow    BEAT_RUSH_SHADOW_THRESHOLD = 0.80
                （services/validation/semantic_overlap.py，dock/幽灵 vs 大纲节拍）
3. suffix-overlap 桥接后文撞车 shadow SUFFIX_OVERLAP_SHADOW_THRESHOLD = 0.80
                （同文件，dock 碎片 vs 后文分句）

语料来源（全部真实数据，绝不虚构「真实」二字）：
- style：default_cliches 种子陈词 × 手写换字变体（正例）+ 真实章节正文段
  （负例——误报基线要用真文，手写六句太少）；
- beat-rush：velluma.db 的 story_beats.action_summary + 章大纲行（目标侧，
  与生产同口径截 60 字）；正例分两类——①正文里真实搬演该节的段落（对齐挖掘
  text_match 片段命中率），②手写改写式抢拍（<4 字连续重合，词法闸抓不住的
  那类）；负例=同章不覆盖任何节的正文段（同景硬负例）+ 他书正文段（易负例）；
- suffix-overlap：真实章节前半句群 → 桥接碎片池（8-16 字，负例——桥合法
  写新内容不该撞后文）；后半句群 → 后文目标；正例分两类——①逐字撞车碎片
  （词法闸已能抓的那类），②手写改写式预演（<4 字连续重合）。

embedding 走 get_embeddings_api_only（与 semantic_overlap 消费面同入口：
纯 API 余弦比对不需要 pgvector，SQLite 默认部署可用；**不要**换回
get_embeddings——它受 is_embedding_configured() 的 SQLite 存储门控，
本机即使配好 Key 也会拿到全空向量，这是 2026-09 修掉的旧 bug）。

用法：
    python scripts/calibrate_semantic_threshold.py              # 三模式全跑
    python scripts/calibrate_semantic_threshold.py --mode style
    python scripts/calibrate_semantic_threshold.py --mode beat-rush
    python scripts/calibrate_semantic_threshold.py --mode suffix-overlap
    python scripts/calibrate_semantic_threshold.py --selftest   # 离线自检，零网络
    python scripts/calibrate_semantic_threshold.py --json out.json
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows 控制台 GBK 防御
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from backend.core.model_config import get_embedding_connection
from backend.services.adaptive.outline_nearby import (
    OUTLINE_NEARBY_LINE_MAX,
    outline_line_is_meta,
)
from backend.services.adaptive.paragraph_source import written_text
from backend.services.adaptive.text_match import fragment_hit_rate
from backend.services.llm.embedding import (
    cosine_similarity,
    get_embeddings_api_only,
    is_embedding_api_configured,
)
from backend.services.style.default_cliches import (
    ZH_CLICHE_BLOCKER,
    ZH_CLICHE_WARNING,
    ZH_HOUSE_VOICE_WARNING,
)
from backend.services.style.fingerprint import split_sentences
from backend.services.style.semantic_match import (
    SEMANTIC_HIT_THRESHOLD,
    _split_segments,
)
from backend.services.validation.semantic_overlap import (
    BEAT_RUSH_SHADOW_THRESHOLD,
    SUFFIX_OVERLAP_SHADOW_THRESHOLD,
)


# ============================================================
# 手写语料一：文风扫描——种子陈词 × 换字变体（沿用任务包 D 原语料）
# ============================================================
# 变体句刻意贴近「换字逃逸」实景：句式语义与陈词同型，但逐字不含 pattern
# 本身（自检 assert；语料自己犯规会退化成精确匹配，校准就失真了）。

VARIANTS: dict = {
    "眼底闪过一丝": ["她的眼底掠过一抹讶异。", "他目光深处闪过些许不耐。"],
    "嘴角勾起一抹": ["他嘴角扬起一丝弧度。", "她唇角勾出一点笑意。"],
    "深邃的眼眸": ["那双眼睛深不见底。", "她有着幽深的双眸。"],
    "难以言喻的": ["一种说不清楚的感觉涌了上来。", "那是种无法形容的滋味。"],
    "命运的齿轮": ["命运开始悄然转动。", "宿命的巨轮缓缓启动。"],
    "时间的长河": ["在岁月的洪流里，什么都会淡。", "时光的长流冲淡了一切。"],
    "心如刀绞": ["心口像被利刃绞着。", "他心里像被刀割一样疼。"],
    "不动声色地": ["他面无表情地继续说。", "她神色未变地收回手。"],
    "意味深长": ["这话里有话。", "他话中别有所指。"],
    "仿佛在诉说着": ["像在低声讲述什么。", "似乎正倾诉着往事。"],
}

UNRELATED: list = [
    "他把柴火劈好，码在墙角。",
    "锅里炖着萝卜牛肉，汤面浮着一层油花。",
    "船在第三天清晨靠了岸，缆绳勒得木桩咯吱作响。",
    "她数了数铜板，还差三文。",
    "雨下了整夜，屋顶漏下一线水，正好滴在门槛内侧。",
    "老周把烟袋在鞋底磕了磕，起身去关鸡笼。",
]


# ============================================================
# 手写语料二：抢拍——真实节拍 × 改写式抢拍（<4 字连续重合）
# ============================================================
# target_prefix 用于在库内定位真实目标句（startswith 前缀匹配，抗重切分）；
# preplay 是手写「抢拍幽灵」：把节拍剧情提前演完但换一套措辞——词法闸
# （≥4 字连续重合）抓不住、只能靠语义闸的那类正例。自检强制 max_common
# run < 4。

BEAT_PARAPHRASES: list = [
    ("兰星低头检查学徒袍", "兰星垂首看了看身上学徒长衫齐不齐整，缓缓吸足一口气便举步汇进人潮，视线掠过锦衣公子们时稍稍一顿"),
    ("兰星停步，冷冷盯着折扇", "兰星止住脚，寒着视线钉住那柄扇子，两手悄悄攥紧终究忍下，四下看客纷纷侧目"),
    ("兰星深吸一口气，集中精神凝聚", "兰星缓吸一气敛住心神，凝出一枚幽黑光团，刻意把威压压在星芒中段水准，偏偏收尾刹那真元一荡，光团深处紫芒一闪，他当即收拳把光团掐灭"),
    ("兰星快步穿过人群", "兰星疾行越过人堆，转进考评场方向的廊道，浑然不觉楼上有道视线；老人逗小孙女玩的手停了停，望着那道远去的背影"),
    ("兰星确认周围无人", "兰星看清四下无人，往墙上轻轻磕了磕拳头，阖眼匀了三口气，再度凝出枚稳当的星芒阶黑球验过无误，这才推门走进考核间"),
    ("第1章大纲：暴风城魔法师协会", "本章：风暴之城的法师行会开始每年一次的联合魔力考核，各路好手与世家少年齐聚一堂"),
]


# ============================================================
# 手写语料三：桥接后文撞车——真实后文句 × 改写式预演（<4 字连续重合）
# ============================================================
# 语料章节：弦上灰 ch9（本书最长真实章）。target_prefix 定位后半句群的
# 真实句子；preplay 是手写「桥接碎片提前预演后文」——2026-09-23 shadow
# 要抓的那类（词法 ≥4 字闸全盲）。

SUFFIX_PARAPHRASES: list = [
    ("舱门", "陈朗解开安全装置，摇摇晃晃扑到门口，用力把父女两个拖出机舱"),
    ("推进器的轰鸣突然变哑", "引擎的嘶吼戛然而止，飞行器像断线风筝般往下栽，李岩心口一紧，女儿的哭喊与警铃一并炸响在耳边"),
    ("他缓缓降落，战甲的关节", "那身影徐徐落向地面，装甲接缝处传来几不可闻的轻响，视线一寸不差地钉在父亲怀抱里的女孩身上"),
    ("一道无形的冲击波", "一股看不见的力量猛然砸在陈朗身上，整个人像被丢弃的玩偶般抛出去，狠狠摔落数米开外的瓦砾间"),
    ("李岩抱着小雅冲进舱门", "李岩搂着女儿一头扎进机舱口，动力装置猛然拔升的嘶鸣刺得他耳内生疼"),
    ("透过舷窗，他看见基地的穹顶", "隔着舱玻璃，基地顶盖正一点点碎开，外层护罩残余的幽光好似垂危虫火般明灭"),
    ("几道银色的身影撕裂云层", "数道银影破开云海悬停在空中，寒意森森的装甲于日光下泛着凶兆般的冷芒"),
    ("李岩紧握小雅的手，望着天空", "李岩攥紧女儿的手抬头上望，头一回离弦裔这么近，那身银亮铠甲的反光落进他眼底，像要刺入魂魄"),
]


# ============================================================
# 语料预算（embedding 是真金白银，全部封顶）
# ============================================================

STYLE_NEG_SEGMENTS_CAP = 100     # 文风负例真实正文段上限
BEAT_NEG_SAME_CHAPTER_CAP = 30   # 同景硬负例上限
BEAT_NEG_OTHER_BOOK_CAP = 30     # 他书易负例上限
SUFFIX_TARGETS_CAP = 40          # 后文目标句上限
SUFFIX_CRASH_PICKS = 12          # 逐字撞车正例数（正例①）
SUFFIX_NEG_FRAGMENTS_CAP = 36    # 桥接碎片负例上限
_EMBED_BATCH = 20                 # 单次批量请求上限——实测 DashScope
                                  # qwen3.7-text-embedding 批量上限 20（超限
                                  # 400 InvalidParameter；生产 get_embeddings*
                                  # 不分批，>20 段的扫描在同模型下会整体
                                  # 静默降级为空，见报告「遗留风险」）


# ============================================================
# 通用工具
# ============================================================

def _db_path() -> str:
    root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return str(data_dir / "velluma.db")


def _connect_ro():
    """只读连接真实库（mode=ro；库不存在/缺表返回 None，调用方软跳过）。"""
    path = _db_path()
    if not os.path.exists(path):
        return None
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    return conn


def _max_common_run(a: str, b: str) -> int:
    """两串最长连续公共子串长度（词法闸 n-gram 重合的近似口径，≤4 即词法盲区）。"""
    a, b = a or "", b or ""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def _stride_sample(items: list, cap: int) -> list:
    """等距确定性采样（不引入随机性，报告可复现）。"""
    if len(items) <= cap:
        return list(items)
    step = len(items) / cap
    return [items[int(i * step)] for i in range(cap)]


def _chapter_plain(conn, book_id: str, chapter_number: int):
    row = conn.execute(
        "SELECT content_text FROM chapters WHERE book_id=? AND chapter_number=?",
        (book_id, chapter_number),
    ).fetchone()
    if not row or not row[0]:
        return None
    return written_text(row[0])


def _beats_from_db(conn) -> list:
    """真实节拍目标侧：story_beats.action_summary（生产口径截 60 字）。"""
    try:
        rows = conn.execute(
            "SELECT action_summary FROM story_beats "
            "WHERE action_summary IS NOT NULL AND length(trim(action_summary))>=8 "
            "ORDER BY book_id, chapter_id, position"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0].strip()[:OUTLINE_NEARBY_LINE_MAX] for r in rows]


def _outline_beat_lines(conn, chapter_id: str) -> list:
    """章大纲节拍行（与 outline_nearby 同过滤：≥8 字、非元信息行、截 60）。"""
    row = conn.execute(
        "SELECT outline_text FROM chapters WHERE id=?", (chapter_id,)
    ).fetchone()
    if not row or not row[0]:
        return []
    lines = []
    for line in (row[0] or "").splitlines():
        l = line.strip()
        if len(l) >= 8 and not outline_line_is_meta(l):
            lines.append(l[:OUTLINE_NEARBY_LINE_MAX])
    return lines


async def _embed(texts: list) -> list:
    """分批批量向量化（每批 ≤ _EMBED_BATCH；批纯属分组，向量与单发一致）。"""
    out: list = []
    for i in range(0, len(texts), _EMBED_BATCH):
        out.extend(await get_embeddings_api_only(texts[i:i + _EMBED_BATCH], timeout=180))
    return out


def _percentile(sorted_vals: list, q: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def _fmt_stats(values: list) -> str:
    if not values:
        return "（空）"
    s = sorted(values)
    return (f"n={len(s)} min={s[0]:.3f} p10={_percentile(s,0.10):.3f} "
            f"p50={_percentile(s,0.50):.3f} p90={_percentile(s,0.90):.3f} "
            f"max={s[-1]:.3f} mean={sum(s)/len(s):.3f}")


def _print_mode_report(name: str, current: float, pos_groups: dict, neg_vals: list) -> dict:
    """单模式分布报告 + 定档建议。pos_groups: {组名: [(text, target, sim)]}。

    定标基准 = 组名以 semantic_only 开头的组（改写式正例——词法闸盲区、
    语义闸存在理由的那类）；其余正例组（词法多可抓）只作分布参照，
    不进分离度计算。
    """
    print("=" * 78)
    print(f"◆ 模式 {name}   当前阈值 = {current}")
    for gname, pairs in pos_groups.items():
        sims = [p[2] for p in pairs]
        print(f"  正例·{gname}: {_fmt_stats(sims)}")
    print(f"  负例: {_fmt_stats(neg_vals)}")

    base_pairs = [p for g, ps in pos_groups.items() if g.startswith("semantic_only")
                  for p in ps]
    if not base_pairs:
        base_pairs = [p for ps in pos_groups.values() for p in ps]
    ref_sims = [p[2] for p in base_pairs]
    if not ref_sims or not neg_vals:
        print("  [错误] 正例或负例为空（embedding 整体失败？），本模式无结论")
        return {"current": current, "error": "empty corpus sims",
                "positive_groups": {}}

    pos_min, neg_max = min(ref_sims), max(neg_vals)
    separation = pos_min - neg_max
    miss = sum(1 for v in ref_sims if v < current)
    fp = sum(1 for v in neg_vals if v >= current)
    print(f"  定标基准（semantic-only 正例）n={len(ref_sims)}: "
          f"min={pos_min:.3f} mean={sum(ref_sims)/len(ref_sims):.3f}")
    for gname, pairs in pos_groups.items():
        gmiss = sum(1 for p in pairs if p[2] < current)
        print(f"    按当前阈值 {current}: [{gname}] 漏抓 {gmiss}/{len(pairs)}")
    print(f"  负例最大: {neg_max:.3f}   分离度（基准正例min−负例max）: {separation:+.3f}")
    print(f"  负例误报（≥当前阈值）: {fp}/{len(neg_vals)}")
    if separation > 0:
        mid = (pos_min + neg_max) / 2
        conservative = max(neg_max + 0.05, _percentile(sorted(neg_vals), 0.95) + 0.03)
        sug = min(max(mid, conservative), pos_min - 0.02)
        caught = sum(1 for v in ref_sims if v >= sug)
        print(f"  建议: {sug:.3f}（两簇中点 {mid:.3f}，保守下限 "
              f"{conservative:.3f}，≤基准正例min−0.02；该档抓 {caught}/{len(ref_sims)}）")
    else:
        print(f"  ⚠ 基准正例与负例重叠：该模型/维度下分辨力不足，建议 ≥ 负例max+0.05 "
              f"（≥ {neg_max + 0.05:.3f}），宁可漏抓勿误报")
    return {
        "current": current,
        "positive_groups": {
            g: [{"text": t, "target": tg, "similarity": round(s, 4)} for t, tg, s in pairs]
            for g, pairs in pos_groups.items()
        },
    }


# ============================================================
# 模式一：style —— 文风语义扫描阈值
# ============================================================

def _load_patterns() -> list:
    seeds = {
        item["pattern"]: item
        for item in ZH_CLICHE_BLOCKER + ZH_CLICHE_WARNING + ZH_HOUSE_VOICE_WARNING
    }
    patterns = []
    for pattern in VARIANTS:
        if pattern not in seeds:
            print(f"[警告] 种子库中找不到陈词「{pattern}」，请同步更新 VARIANTS 语料")
            continue
        patterns.append(pattern)
    return patterns


def _style_corpus(conn):
    patterns = _load_patterns()
    positives = [(s, p) for p in patterns for s in VARIANTS[p]]
    negatives = [(s, "hand") for s in UNRELATED]
    if conn is not None:
        segs = []
        for book_id, ch in (("e392da83a5dd4565ac45a9be6fe514d0", 9),
                            ("e392da83a5dd4565ac45a9be6fe514d0", 4),
                            ("e392da83a5dd4565ac45a9be6fe514d0", 15),
                            ("15b68595e29441239a05f325045ca02b", 1)):
            try:
                plain = _chapter_plain(conn, book_id, ch)
            except sqlite3.OperationalError:
                plain = None
            if plain:
                segs.extend(_split_segments(plain))
        negatives += [(s, "real_prose") for s in _stride_sample(segs, STYLE_NEG_SEGMENTS_CAP)]
    return patterns, positives, negatives


async def run_style(conn, report: dict) -> None:
    patterns, positives, negatives = _style_corpus(conn)
    if not patterns:
        print("[style] 无可用种子陈词，跳过")
        return
    for p in patterns:
        for s in VARIANTS[p]:
            assert p not in s, f"变体句含原词面：{p} ∈ {s}"

    uniq = list(dict.fromkeys(patterns + [s for s, _ in positives] + [s for s, _ in negatives]))
    vecs = await _embed(uniq)
    vm = dict(zip(uniq, vecs))

    pos_pairs = []
    for s, p in positives:
        v = vm.get(s)
        if v:
            pos_pairs.append((s, p, cosine_similarity(v, vm[p])))
    neg_rows = []
    for s, label in negatives:
        v = vm.get(s)
        if not v:
            continue
        best, bt = -1.0, ""
        for p in patterns:
            if vm.get(p):
                sim = cosine_similarity(v, vm[p])
                if sim > best:
                    best, bt = sim, p
        if bt:
            neg_rows.append((s, bt, best, label))

    print(f"\n[style] 模型: {_conn_info()}")
    for label in dict.fromkeys(r[3] for r in neg_rows):
        sims = [r[2] for r in neg_rows if r[3] == label]
        print(f"  负例·{label}: {_fmt_stats(sims)}")
    res = _print_mode_report(
        "style 文风语义扫描（SEMANTIC_HIT_THRESHOLD）",
        SEMANTIC_HIT_THRESHOLD,
        {"semantic_only 换字变体": pos_pairs},
        [r[2] for r in neg_rows],
    )
    res["negatives"] = [{"text": t, "target": tg, "similarity": round(s, 4), "source": lb}
                        for t, tg, s, lb in neg_rows]
    res["negative_note"] = "手写无关句 + 真实章节正文段（生产同口径切段）"
    report["style"] = res


def _conn_info() -> str:
    c = get_embedding_connection()
    return f"{c['model']}  维度: {c['dimensions']}  连接: {c['source']} ({c['base_url']})"


# ============================================================
# 模式二：beat-rush —— 抢拍 shadow 阈值
# ============================================================

BEAT_BOOK = "15b68595e29441239a05f325045ca02b"   # 我！魔法之巅（有真实节拍+大纲）
BEAT_CHAPTER = "68d8257b9edc438880bf58515fb701c0"
OTHER_BOOK = "e392da83a5dd4565ac45a9be6fe514d0"  # 弦上灰（他书负例）


def _uncapped_segments(text: str) -> list:
    """生产切段（semantic_match 同尺：句切→超长按逗号类细切）但不截 200 段上限。

    上限是扫描预算（防超长章拖爆批量），不是语料语义——校准挖掘要看全章。
    """
    import re as _re

    from backend.services.style.semantic_match import (
        _SEGMENT_MIN_CHARS,
        _SEGMENT_SUB_SPLIT,
        SEMANTIC_SEGMENT_MAX_CHARS,
    )

    segments: list = []
    for sentence in split_sentences(text or ""):
        if len(sentence) <= SEMANTIC_SEGMENT_MAX_CHARS:
            segments.append(sentence)
        else:
            for frag in _SEGMENT_SUB_SPLIT.split(sentence):
                frag = frag.strip()
                if len(frag) > _SEGMENT_MIN_CHARS:
                    segments.append(frag)
    return segments


# ============================================================
# 抢拍对位锚（正文搬演区的定位词：beat 前缀 → (锚词, 第几次出现)）
# ============================================================
# 锚词取自节拍内最具场景辨识度的名词，已在本书正文中核实命中；锚失配时
# 回退章序等分对位，再失配跳过该节拍（报告如实标注挖掘方法）。

BEAT_ANCHORS: dict = {
    "兰星低头检查学徒袍": ("学徒袍", 0),
    "兰星停步，冷冷盯着折扇": ("折扇", 0),
    "兰星深吸一口气，集中精神凝聚": ("光球", 0),
    "兰星快步穿过人群": ("走廊", 0),
    "兰星确认周围无人": ("走廊", 1),
}


def _beat_rush_corpus(conn):
    """返回 (targets, aligned_windows, hand_pairs, negatives)。

    aligned_windows 是 list[(窗口内段列表, beat)]。挖掘两法并用（都在报告里
    如实标注）：
    - 词法窗口：片段命中率 ≥1/3 的最佳 3 段窗口（对本库大纲行有效；实测
      story_beats 的搬演正文改写彻底、3 字片段命中率≈0——这正是词法闸失效、
      语义闸存在的实证）；
    - 锚定位：BEAT_ANCHORS 锚词命中处取前后各 1 段窗口（失配回退章序等分，
      正文按 progression 1..N 顺序生成的假设）。
    """
    if conn is None:
        return [], [], [], []
    story_beats = _beats_from_db(conn)
    beats = list(story_beats)
    beats += [b for b in _outline_beat_lines(conn, BEAT_CHAPTER) if b not in beats]
    if not beats:
        return [], [], [], []

    plain = _chapter_plain(conn, BEAT_BOOK, 1)
    segs = _uncapped_segments(plain) if plain else []

    aligned = []
    covered = set()
    if segs:
        windows = [(i, segs[i:i + 3]) for i in range(max(1, len(segs) - 2))]
        # 法一：词法窗口对齐（≥1/3）
        for beat in beats:
            scored = [
                (fragment_hit_rate(beat, "。".join(w), size=3, max_fragments=6) or 0.0,
                 i, w)
                for i, w in windows
            ]
            scored = [t for t in scored if t[0] >= 1 / 3]
            if not scored:
                continue
            scored.sort(key=lambda x: (-x[0], -len("。".join(x[2]))))
            _, wi, w = scored[0]
            aligned.append((w, beat))
            covered.update(range(wi, wi + len(w)))
        # 法二：锚定位（仅 story_beats；失配回退章序等分）
        anchored = {b for _, b in aligned}
        for k, beat in enumerate(story_beats):
            if beat in anchored:
                continue
            anchor, occ = next(
                ((a, o) for p, (a, o) in BEAT_ANCHORS.items() if beat.startswith(p)),
                (None, 0),
            )
            mid = None
            if anchor:
                hits = [i for i, s in enumerate(segs) if anchor in s]
                if len(hits) > occ:
                    mid = max(0, hits[occ] - 1)
            elif len(segs) >= len(story_beats) * 3:
                mid = int((k + 0.5) * len(segs) / len(story_beats))
            if mid is not None:
                w = segs[mid:mid + 3]
                if w:
                    aligned.append((w, beat))
                    covered.update(range(mid, mid + len(w)))

    # 正例②：手写改写式抢拍（定位真实目标句）
    hand = []
    for prefix, preplay in BEAT_PARAPHRASES:
        target = next((b for b in beats if b.startswith(prefix)), None)
        if target is None:
            # 大纲行截断后可能不再以 prefix 开头，退化为包含匹配
            target = next((b for b in beats if prefix in b), None)
        if target is not None:
            hand.append((preplay, target))

    # 负例：同章不在任何对齐窗口内、且与全部节拍 <1/6 片段命中的段（同景硬负例）
    def _uncovered(s):
        return all((fragment_hit_rate(b, s, size=3, max_fragments=6) or 0.0) < 1 / 6
                   for b in beats)

    same_ch = _stride_sample(
        [s for i, s in enumerate(segs) if i not in covered and _uncovered(s)],
        BEAT_NEG_SAME_CHAPTER_CAP)
    # 负例：他书正文段（易负例）
    other_plain = _chapter_plain(conn, OTHER_BOOK, 4)
    other = _stride_sample(_uncapped_segments(other_plain) if other_plain else [],
                           BEAT_NEG_OTHER_BOOK_CAP)
    return beats, aligned, hand, ([(s, "same_chapter") for s in same_ch]
                                  + [(s, "other_book") for s in other])


async def run_beat_rush(conn, report: dict) -> None:
    beats, aligned, hand, negatives = _beat_rush_corpus(conn)
    if not beats:
        print("[beat-rush] 库中无真实节拍（story_beats/outline_text 均空），跳过")
        return
    if not hand:
        print("[beat-rush] 手写抢拍语料未匹配到目标句，检查 BEAT_PARAPHRASES 前缀")

    window_segs = list(dict.fromkeys(s for w, _ in aligned for s in w))
    uniq = list(dict.fromkeys(
        beats + window_segs + [s for s, _ in hand] + [s for s, _ in negatives]))
    vecs = await _embed(uniq)
    vm = dict(zip(uniq, vecs))

    def _sim(s, b):
        v, bv = vm.get(s), vm.get(b)
        return cosine_similarity(v, bv) if v and bv else float("nan")

    def _best(s):
        v = vm.get(s)
        if not v:
            return "", float("nan")
        best, bt = -1.0, ""
        for b in beats:
            if vm.get(b):
                sim = cosine_similarity(v, vm[b])
                if sim > best:
                    best, bt = sim, b
        if not bt:
            return "", float("nan")
        return bt, best

    # 正例①按生产语义：窗口内最佳段 × 该节拍（段×目标取 max）
    aligned_pairs = []
    for w, beat in aligned:
        seg_sims = [(_sim(s, beat), s) for s in w]
        seg_sims = [t for t in seg_sims if t[0] == t[0]]
        if seg_sims:
            sim, s = max(seg_sims, key=lambda t: t[0])
            aligned_pairs.append((s, beat, sim))
    hand_pairs = [(s, *_best(s)) for s, _ in hand]
    hand_pairs = [p for p in hand_pairs if p[2] == p[2]]
    neg_rows = [(s, *_best(s), lb) for s, lb in negatives]
    neg_rows = [r for r in neg_rows if r[2] == r[2]]

    print(f"\n[beat-rush] 目标节拍 {len(beats)} 条（story_beats+大纲行，截60字）")
    for b in beats:
        print(f"  · {b}")
    for label in dict.fromkeys(r[3] for r in neg_rows):
        sims = [r[2] for r in neg_rows if r[3] == label]
        print(f"  负例·{label}: {_fmt_stats(sims)}")
    res = _print_mode_report(
        "beat-rush 抢拍 shadow（BEAT_RUSH_SHADOW_THRESHOLD）",
        BEAT_RUSH_SHADOW_THRESHOLD,
        {"①真实搬演段（词法窗口+锚定位挖掘）": aligned_pairs,
         "semantic_only ②改写式抢拍（词法盲）": hand_pairs},
        [r[2] for r in neg_rows],
    )
    res["negatives"] = [{"text": t, "target": tg, "similarity": round(s, 4), "source": lb}
                        for t, tg, s, lb in neg_rows]
    res["negative_note"] = "同章不覆盖任何节拍的正文段（硬负例）+ 他书正文段（易负例）"
    res["targets"] = beats
    report["beat_rush"] = res


# ============================================================
# 模式三：suffix-overlap —— 桥接后文撞车 shadow 阈值
# ============================================================

SUFFIX_BOOK = "e392da83a5dd4565ac45a9be6fe514d0"  # 弦上灰
SUFFIX_CHAPTER = 9                                 # 本书最长真实章


def _suffix_corpus(conn):
    """返回 (targets, crash_pairs, hand_pairs, neg_fragments)。"""
    if conn is None:
        return [], [], [], []
    plain = _chapter_plain(conn, SUFFIX_BOOK, SUFFIX_CHAPTER)
    if not plain:
        return [], [], [], []
    sents = [s for s in split_sentences(plain) if len(s) >= 4]
    if len(sents) < 20:
        return [], [], [], []
    half = len(sents) // 2
    first_half, second_half = sents[:half], sents[half:]
    targets = _stride_sample(second_half, SUFFIX_TARGETS_CAP)

    # 正例①：逐字撞车碎片（从目标句本身取 8-16 字窗口——词法闸已能抓）
    crash = []
    for t in _stride_sample(targets, SUFFIX_CRASH_PICKS):
        start = max(0, (len(t) - 12) // 3)
        frag = t[start:start + 12]
        if 8 <= len(frag) <= 16:
            crash.append((frag, t))

    # 正例②：手写改写式预演（<4 字连续重合）
    hand = []
    for prefix, preplay in SUFFIX_PARAPHRASES:
        target = next((s for s in second_half if s.startswith(prefix)), None)
        if target is None:
            target = next((s for s in sents if s.startswith(prefix)), None)
        if target is not None and target not in targets:
            targets.append(target)  # 手写对的目标句必须进目标集（生产语义：
            # 比对对象是全部后文分句）                      # suffix_anchor 分句全集）
        if target is not None:
            hand.append((preplay, target))

    # 负例：前半句群的 8-16 字碎片（桥合法写新内容；与任一目标 ≥4 字连续
    # 重合的剔除——那是真撞车不是负例）
    negs = []
    for s in first_half:
        for start in (0, max(0, len(s) - 14)):
            frag = s[start:start + 14]
            if not (8 <= len(frag) <= 16):
                continue
            if any(_max_common_run(frag, t) >= 4 for t in targets):
                continue
            negs.append(frag)
        if len(negs) >= SUFFIX_NEG_FRAGMENTS_CAP * 2:
            break
    negs = _stride_sample(list(dict.fromkeys(negs)), SUFFIX_NEG_FRAGMENTS_CAP)
    return targets, crash, hand, [(s, "first_half") for s in negs]


async def run_suffix_overlap(conn, report: dict) -> None:
    targets, crash, hand, negs = _suffix_corpus(conn)
    if not targets:
        print("[suffix-overlap] 语料章节为空，跳过")
        return
    uniq = list(dict.fromkeys(
        targets + [s for s, _ in crash] + [s for s, _ in hand] + [s for s, _ in negs]))
    vecs = await _embed(uniq)
    vm = dict(zip(uniq, vecs))

    def _best(s):
        v = vm.get(s)
        if not v:
            return "", float("nan")
        best, bt = -1.0, ""
        for t in targets:
            if vm.get(t):
                sim = cosine_similarity(v, vm[t])
                if sim > best:
                    best, bt = sim, t
        if not bt:
            return "", float("nan")
        return bt, best

    crash_pairs = [(s, *_best(s)) for s, _ in crash]
    crash_pairs = [p for p in crash_pairs if p[2] == p[2]]
    hand_pairs = [(s, *_best(s)) for s, _ in hand]
    hand_pairs = [p for p in hand_pairs if p[2] == p[2]]
    neg_rows = [(s, *_best(s), lb) for s, lb in negs]
    neg_rows = [r for r in neg_rows if r[2] == r[2]]

    print(f"\n[suffix-overlap] 语料: 弦上灰 ch9 前半 {len(negs)} 碎片 vs "
          f"后半 {len(targets)} 目标句")
    res = _print_mode_report(
        "suffix-overlap 桥接后文撞车 shadow（SUFFIX_OVERLAP_SHADOW_THRESHOLD）",
        SUFFIX_OVERLAP_SHADOW_THRESHOLD,
        {"①逐字撞车碎片（词法可抓）": crash_pairs,
         "semantic_only ②改写式预演（词法盲）": hand_pairs},
        [r[2] for r in neg_rows],
    )
    res["negatives"] = [{"text": t, "target": tg, "similarity": round(s, 4), "source": lb}
                        for t, tg, s, lb in neg_rows]
    res["negative_note"] = "同章前半 8-16 字碎片（与后文 ≥4 字重合者已剔除）"
    res["targets"] = targets[:SUFFIX_TARGETS_CAP]
    report["suffix_overlap"] = res


# ============================================================
# 离线自检（零网络）：语料不变量 + 库内语料装配
# ============================================================

def selftest() -> int:
    print("== 自检（离线，零网络零 embedding）==")
    failed = 0

    # 1. 文风变体句不含原词面（防语料自己犯规变精确匹配）
    for p in _load_patterns():
        for s in VARIANTS[p]:
            if p in s:
                print(f"  [FAIL] 变体句含原词面：{p} ∈ {s}")
                failed += 1
    print(f"  [ok] 文风变体句词面检查（{len(_load_patterns())} 组）")

    # 2. 手写改写语料与目标 <4 字连续重合（词法盲区，语义闸专属正例）
    conn = _connect_ro()
    beats = _beats_from_db(conn) if conn else []
    if conn:
        beats += [b for b in _outline_beat_lines(conn, BEAT_CHAPTER) if b not in beats]
    for prefix, preplay in BEAT_PARAPHRASES:
        target = next((b for b in beats if b.startswith(prefix) or prefix in b), None)
        if target is None:
            print(f"  [FAIL] 抢拍手写语料未定位到目标句：{prefix}")
            failed += 1
            continue
        run_len = _max_common_run(preplay, target)
        if run_len >= 4:
            print(f"  [FAIL] 抢拍手写句与目标 ≥4 字连续重合（{run_len}）：{preplay[:20]}")
            failed += 1
    print(f"  [ok] 抢拍手写语料定位+词面盲区检查（{len(BEAT_PARAPHRASES)} 对）")

    # 3. suffix 手写语料：定位真实句 + <4 字重合
    if conn:
        targets, crash, hand, negs = _suffix_corpus(conn)
        plain_ok = bool(targets)
        for prefix, preplay in SUFFIX_PARAPHRASES:
            target = next((s for s in targets if s.startswith(prefix)), None)
            if target is None:
                print(f"  [FAIL] 预演手写语料未定位到目标句：{prefix}")
                failed += 1
                continue
            run_len = _max_common_run(preplay, target)
            if run_len >= 4:
                print(f"  [FAIL] 预演手写句与目标 ≥4 字连续重合（{run_len}）：{preplay[:20]}")
                failed += 1
        print(f"  [ok] 预演手写语料定位+词面盲区检查（{len(SUFFIX_PARAPHRASES)} 对）")

        # 4. 逐字撞车碎片方向性（必须 ≥4 字重合，否则挖反了）
        for frag, t in crash:
            if _max_common_run(frag, t) < 4:
                print(f"  [FAIL] 撞车碎片与目标 <4 字重合（挖反）：{frag}")
                failed += 1
        print(f"  [ok] 逐字撞车碎片方向性检查（{len(crash)} 条）")

        # 5. 负例碎片与目标 <4 字重合（剔除逻辑生效）
        leaked = [f for f, _lb in negs
                  if any(_max_common_run(f, t) >= 4 for t in targets)]
        if leaked:
            print(f"  [FAIL] {len(leaked)} 条负例碎片与后文 ≥4 字重合未剔除")
            failed += 1
        print(f"  [ok] 负例碎片词法隔离检查（{len(negs)} 条）")

        # 6. 装配规模（阈值报告要有统计意义）
        beats2, aligned, hand2, negs2 = _beat_rush_corpus(conn)
        checks = [
            ("目标节拍", len(beats2), 4),
            ("对齐搬演正例", len(aligned), 4),
            ("抢拍手写正例", len(hand2), 4),
            ("抢拍负例", len(negs2), 20),
            ("suffix 目标句", len(targets), 20),
            ("suffix 手写正例", len(hand), 4),
            ("suffix 负例碎片", len(negs), 20),
            ("style 真实负例段", len(_stride_sample(
                _split_segments(_chapter_plain(conn, OTHER_BOOK, 4) or ""),
                STYLE_NEG_SEGMENTS_CAP)), 20),
        ]
        for label, n, floor in checks:
            mark = "ok" if n >= floor else "FAIL"
            if n < floor:
                failed += 1
            print(f"  [{mark}] {label}: {n}（下限 {floor}）")
    else:
        print("  [SKIP] 未找到 velluma.db，库内语料装配检查跳过（手写语料检查已跑）")

    # 7. 目标侧生产口径：节拍截 60、suffix 目标 ≥4 字
    if conn:
        for b in beats:
            if len(b) > OUTLINE_NEARBY_LINE_MAX:
                print(f"  [FAIL] 节拍目标超 60 字未截断：{b[:20]}…")
                failed += 1
        print(f"  [ok] 节拍目标生产口径（截 {OUTLINE_NEARBY_LINE_MAX} 字）")
        conn.close()

    print(f"== 自检结果: {'通过' if failed == 0 else f'{failed} 项失败'} ==")
    print(f"当前阈值: style={SEMANTIC_HIT_THRESHOLD} "
          f"beat_rush={BEAT_RUSH_SHADOW_THRESHOLD} "
          f"suffix={SUFFIX_OVERLAP_SHADOW_THRESHOLD}（均占位，待本脚本定档）")
    return 0 if failed == 0 else 1


# ============================================================
# 入口
# ============================================================

async def run(modes: list, json_path: str | None) -> int:
    if not is_embedding_api_configured():
        print("未配置 embedding（model_config.json 的 embedding 节缺 api_key）。")
        print("解锁步骤：设置弹窗→向量分区（或直接编辑 model_config.json 的 embedding 节")
        print("填 api_key/model/base_url）→ 保存后重跑本脚本（无需重启，纯 API 入口即时生效）。")
        print("注意：SQLite 默认部署即可跑（本脚本走 get_embeddings_api_only 纯 API 比对，")
        print("不依赖 pgvector；不要用 get_embeddings——它受 SQLite 存储门控恒返回空向量）。")
        return 1

    print(f"模型: {_conn_info()}")
    conn = _connect_ro()
    if conn is None:
        print(f"[警告] 未找到 {_db_path()}——库内真实语料模式将全部跳过")

    report: dict = {"db": _db_path(), "modes_run": modes}
    try:
        if "style" in modes:
            await run_style(conn, report)
        if "beat-rush" in modes:
            await run_beat_rush(conn, report)
        if "suffix-overlap" in modes:
            await run_suffix_overlap(conn, report)
    finally:
        if conn is not None:
            conn.close()

    print("=" * 78)
    print("纪律提醒：本脚本只出报告与建议，不改任何阈值常量；shadow 转 live 仍走")
    print("原门槛（回归语料全对 + ≥20 次真实命中 FP<10%，见 constraint-governance §5）。")
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        print(f"原始逐对数据已落: {json_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="语义阈值校准（三阈值分离度定标，手动小工具不进 CI；"
                    "先跑 --selftest 验语料，再无参跑全量）")
    parser.add_argument("--mode", default="all",
                        choices=["all", "style", "beat-rush", "suffix-overlap"],
                        help="校准哪个阈值（默认 all）")
    parser.add_argument("--selftest", action="store_true",
                        help="离线自检：语料不变量+装配，零网络零成本")
    parser.add_argument("--json", default=None, metavar="PATH",
                        help="逐对原始数据落盘路径（写报告用）")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    modes = ["style", "beat-rush", "suffix-overlap"] if args.mode == "all" else [args.mode]
    return asyncio.run(run(modes, args.json))


if __name__ == "__main__":
    sys.exit(main())

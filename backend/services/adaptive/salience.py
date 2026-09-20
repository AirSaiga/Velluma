# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 热层显著性引擎（B7 · docs/world-cognition-architecture.md §4）
"""注意力窗：三族信号 × 段距指数衰减 + 六槽配额（纯代码，参数个位数）。

取代方向权重引擎（尸检：18 次恒常量输出——抽象向量无观测无回路）。
信号转世关系（docs/reports/world-kernel-construction-plan.md §8）：
- 期待张力（原读者力）→ 世界信号一票；
- 未兑现伏笔计数（原推动力）→ 「被冷落的重要」槽；
- 采纳反馈（原负反馈）→ 行为乘子（quiet_learning 纪律：一次肯定胜过
  三次否定——乘子只升不降由采纳驱动，蒸发/忽略走降权且需多次）。

衰减模型：score = Σ wᵢ·exp(-Δ段/τᵢ)；提及 τ=3 段；开放环 τ=∞（闭环才衰减）。
段距而非墙钟（写作有 idle，墙钟衰减会在作者喝水回来时清空注意力）。

影子模式纪律：先 log-only（trace salience_shadow），A/B 过闸后才供 dock 单车道。
副作用：无（纯函数）。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 参数表（个位数纪律——调参只走实测回收流程）
MENTION_TAU_PARAGRAPHS = 3.0     # 提及信号的段距衰减常数
NEGLECTED_K_PARAGRAPHS = 8       # 「被冷落的重要」：高先验且 K 段未提
SALIENCE_SLOTS = 6               # 六槽配额：≤3 top + ≥1 被冷落 + ≥1 在场沉默 + 1 系统


@dataclass
class SalientEntry:
    title: str
    score: float = 0.0
    reasons: List[str] = field(default_factory=list)
    slot: str = ""  # top | neglected | present_silent | system


def _paragraphs(text: str) -> List[str]:
    """画布文本 → 段落列表（剥标签后按空行/换行切，保序）。"""
    plain = re.sub(r"<[^>]+>", "\n", text or "")
    return [p.strip() for p in re.split(r"\n+", plain) if p.strip()]


def compute_salience(
    canvas_text: str,
    entity_names: Dict[str, List[str]],
    priors: Optional[Dict[str, int]] = None,
    present_names: Optional[List[str]] = None,
    open_loops: Optional[List[str]] = None,
    behavior_mult: Optional[Dict[str, float]] = None,
) -> List[SalientEntry]:
    """三族信号 → 六槽热集（纯函数）。

    Args:
        canvas_text: 画布全文（段落切分在内部做）。
        entity_names: 实体 id → [主名, *别名]（提及扫描的目标词表）。
        priors: 名字 → 先验重要度 1-10（「被冷落的重要」判据）。
        present_names: 在场名单（在场沉默者槽）。
        open_loops: 开放环文本列表（伏笔/未兑现——转世信号，τ=∞）。
        behavior_mult: 名字 → 行为乘子（采纳>1、忽略<1；默认 1.0）。

    Returns:
        六槽 SalientEntry 列表（按槽序：top×3 → neglected → present_silent → system）。
    """
    priors = priors or {}
    present_names = present_names or []
    open_loops = open_loops or []
    behavior_mult = behavior_mult or {}
    paragraphs = _paragraphs(canvas_text)
    n = len(paragraphs)

    name_to_titles: Dict[str, List[str]] = {}
    for titles in entity_names.values():
        for t in titles:
            if t:
                name_to_titles.setdefault(t, []).append(t)

    # ---- 文本流信号：提及频次（log 饱和）× 段距衰减 ----
    scores: Dict[str, float] = {}
    reasons: Dict[str, List[str]] = {}
    for title in name_to_titles:
        probes = [title] + [
            a for a in (name_to_titles.get(title) or [title]) if a and a != title
        ]
        hit_paras = []
        for i, para in enumerate(paragraphs):
            if any(p in para for p in probes if p):
                hit_paras.append(n - 1 - i)  # 距段尾的段距
        if hit_paras:
            s = sum(math.exp(-d / MENTION_TAU_PARAGRAPHS) for d in hit_paras)
            s = 1.0 + math.log1p(s - 1.0) if s > 1 else s  # log(1+count) 防刷屏
            scores[title] = scores.get(title, 0.0) + s
            reasons.setdefault(title, []).append(
                f"近{n - hit_paras[-1] if hit_paras else n}段提及{len(hit_paras)}次")

    # ---- 世界信号：开放环（τ=∞ 的转世信号）----
    # 先验重要度不进 top 评分——它的正当位置是「被冷落的重要」槽（高先验
    # 且未提及者恰不该因先验而被顶进热区；docs §4 六槽分工）
    for loop in open_loops:
        # 开放环按文本匹配到相关实体（粗粒度：文本含实体名才挂）
        for title in name_to_titles:
            if title in (loop or ""):
                scores[title] = scores.get(title, 0.0) + 0.5
                reasons.setdefault(title, []).append("挂着开放伏笔")

    # ---- 行为乘子 ----
    for title, mult in behavior_mult.items():
        if title in scores:
            scores[title] *= max(0.1, mult)

    # ---- 六槽配额 ----
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out: List[SalientEntry] = []
    taken = set()
    for title, s in ranked[:3]:
        out.append(SalientEntry(title=title, score=round(s, 3),
                                reasons=reasons.get(title, []), slot="top"))
        taken.add(title)
    # 被冷落的重要：高先验且近期（K 段内）未提及
    for title, imp in sorted(priors.items(), key=lambda kv: -kv[1]):
        if title in taken or imp < 7:
            continue
        mentioned_recent = any(
            title in para for para in paragraphs[-NEGLECTED_K_PARAGRAPHS:]
        )
        if not mentioned_recent:
            out.append(SalientEntry(
                title=title, score=round(float(imp) / 10, 3),
                reasons=[f"重要度{imp}且{NEGLECTED_K_PARAGRAPHS}段未提"], slot="neglected"))
            taken.add(title)
            break
    # 在场沉默者：在场且热集未覆盖
    for title in present_names:
        if title not in taken:
            out.append(SalientEntry(
                title=title, score=0.3, reasons=["在场但久无镜头"], slot="present_silent"))
            taken.add(title)
            break
    # 系统槽：开放环整体（揭示临近/伏笔到期——由消费方带具体内容）
    if open_loops:
        out.append(SalientEntry(
            title=open_loops[0][:24], score=0.4,
            reasons=["开放伏笔/揭示临近"], slot="system"))
    return out[:SALIENCE_SLOTS]

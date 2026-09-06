# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 3.0 Canon 纯算法检测（共享 utils）
"""
Canon 相关的纯算法（零 LLM）检测函数。

从 post_process.py 抽出，供 canon_watch（写中心跳感知）与 post_process
（完稿审计）共用。两个函数都是纯算法、无副作用，输入 (text, bundle) 输出 dict。

- check_must_hit_coverage：章节卡必达事件关键词覆盖率
- check_canon_compliance：Canon private 标签泄露检测

警示：这两个函数被写中心跳（4s 停顿）高频调用，必须保持零 LLM、零 DB 写。
所有需要 LLM 或 DB 查询的检测不要加到这里——交给调用方（canon_watch 自行调
check_consistency 等）。
"""
from __future__ import annotations

from typing import Dict, List


def check_must_hit_coverage(text: str, bundle) -> Dict:
    """章节卡必达事件覆盖率（纯算法）。

    取 must_hit_events 描述的核心词，子串匹配正文。
    """
    cc = bundle.chapter_card
    if not cc or not cc.must_hit_events:
        return {"checked": False, "reason": "无章节卡"}
    hits = []
    misses = []
    for event in cc.must_hit_events:
        event_str = event.get("event", "") if isinstance(event, dict) else str(event)
        # 简单关键词匹配（取事件描述的核心词）
        keywords = [w for w in event_str.replace("，", " ").split() if len(w) >= 2]
        if keywords and any(kw in text for kw in keywords[:3]):
            hits.append(event_str[:40])
        else:
            misses.append(event_str[:40])
    return {
        "checked": True,
        "hit_count": len(hits),
        "miss_count": len(misses),
        "misses": misses[:5],
    }


def check_canon_compliance(text: str, bundle) -> Dict:
    """Canon public 一致性 / private 泄露（纯算法）。

    private 标签直接子串匹配正文——命中即「可能泄露 private 设定」。
    public 事实只统计数量（语义一致性需 LLM，留给完稿审阅）。
    """
    hard = bundle.hard_constraints()
    breaches: List[str] = []
    # private 泄露
    for label in hard.get("canon_private_labels", []):
        if label and len(label) >= 3 and label in text:
            breaches.append(f"⚠️ 可能泄露 private 设定：{label}")
    # public 事实（简单检查——只标注，不做语义一致性判断）
    return {
        "private_breaches": breaches[:5],
        "public_fact_count": len(hard.get("canon_public_facts", [])),
    }

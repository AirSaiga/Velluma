# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 默认记忆流纯函数（结构化+词法，无 embedding）
"""
默认记忆流的无依赖算法部分（embedding 未配置时的召回路径）。

- extract_keywords：jieba TF-IDF 抽查询关键词（书级查询文本，top 8）
- keyword_coverage：关键词命中覆盖分（单关键词命中数封顶，防单一专名刷屏）
- format_event_echo：世界事件 → 前情回响文本（结构化层输出，喂 memory_echoes）

纯函数、零 DB/LLM 依赖，独立单测（test_recall_helpers.py）。
"""
from __future__ import annotations

from typing import List

# 单关键词命中数封顶：防止某个人名在同一块里出现十次把其他关键词挤掉
_KEYWORD_HIT_CAP = 3


def extract_keywords(text: str, top_k: int = 8) -> List[str]:
    """从查询文本抽关键词（jieba TF-IDF；短文本/异常降级为空）。"""
    if not text or len(text.strip()) < 2:
        return []
    try:
        import jieba.analyse

        return [w for w in jieba.analyse.extract_tags(text, topK=top_k) if len(w) >= 2][:top_k]
    except Exception:
        return []


def keyword_coverage(text: str, keywords: List[str]) -> float:
    """关键词命中覆盖分：每个命中关键词记 min(次数, 3)/3 分，满分 = len(keywords)。

    计分语义：命中 1 次给 1/3、2 次给 2/3、≥3 次给满 1 分——命中的关键词
    「广度」比单名反复出现的「深度」更重要。
    """
    if not text or not keywords:
        return 0.0
    score = 0.0
    for kw in keywords:
        if not kw:
            continue
        n = text.count(kw)
        if n:
            score += min(n, _KEYWORD_HIT_CAP) / _KEYWORD_HIT_CAP
    return score


def format_event_echo(
    event_type: str,
    names: List[str],
    note: str,
    time_start=None,
) -> str:
    """世界事件 → 前情回响文本（与向量召回的 chunk 片段同格式注入 memory_echoes）。"""
    who = "、".join(names[:3]) if names else ""
    head = f"【前情事件·{event_type}】"
    body = f"{who}：" if who else ""
    detail = (note or "").strip()[:80] or event_type
    tail = f"（第 {time_start} 日）" if isinstance(time_start, int) else ""
    return f"{head}{body}{detail}{tail}"

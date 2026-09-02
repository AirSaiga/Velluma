# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - B5 人称漂移检测（report-only · 约束治理一期）
"""
幽灵叙述段第一人称密度检测——「尊重作者主权不切视角」prompt 约束的度量面。

report-only 纪律（导师裁决）：只落 constraint_events 台账不上屏——先攒分布
数据，再决定是否进感知带。剥对白引号后统计叙述段的第一人称字频密度：
- 中文小说第三人称叙述里「我」高频出现通常是视角漂移信号；
- 对白里的「我」完全合法，按引号段剔除（“…”/「…」/『…』）；
- 阈值由消费方定（调用方传 baseline 或用常量兜底），本模块只产密度。

纯函数零依赖。
"""
from __future__ import annotations

import re
from typing import Dict

# 对白段：中英文引号包裹的内容（跨行惰性匹配）
_QUOTED_RE = re.compile(r"“[^”]*”|「[^」]*」|『[^』]*』|\"[^\"]*\"|'[^']*'")
_FIRST_PERSON = ("我", "咱")
_NARRATIVE_MIN_CHARS = 20  # 叙述段太短时密度噪声大，返回 0 并标 insufficient


def narrative_first_person_density(text: str) -> Dict[str, float]:
    """剥对白后统计叙述段第一人称密度。

    返回 {"density": 每百字第一人称次数, "narrative_chars": 叙述段字数,
    "sufficient": 0/1}。空文本/无叙述段 density=0。
    """
    if not text:
        return {"density": 0.0, "narrative_chars": 0, "sufficient": 0}
    narrative = _QUOTED_RE.sub("", text)
    narrative = re.sub(r"\s+", "", narrative)
    n = len(narrative)
    if n < _NARRATIVE_MIN_CHARS:
        return {"density": 0.0, "narrative_chars": n, "sufficient": 0}
    count = sum(narrative.count(w) for w in _FIRST_PERSON)
    return {"density": round(count * 100 / n, 2), "narrative_chars": n, "sufficient": 1}

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
deai 运行时事实闸（契约§6 运行时保底的判定侧）。

唯一权威实现：`deai/scripts/validate_pairs.py` 的 `check_gates`（fact=None
路径）。本文件是它的**运行时移植副本**——Electron 打包只带 backend/，
后端不能 import 仓库根的 deai/，改判据必须先改权威实现并跑其 --selftest，
再把本文件同步过来，最后跑 test_deai_client.py 对拍（用例取自 selftest）。

契约语义（deai/docs/contract.md §6，运行时同规则）：
- 事实类失败（数字闸/专名闸/新增事实闸）= 模型动了事实 → **回退原文**；
- 非事实类失败（长度/套话/像人）→ 仍返回改写，但携带 warnings 由调用方裁决；
- 引号不配对等「无法自动判定」项在运行时直接忽略（权威实现中转人工，
  运行时没有人工，宁按可判定项处置）。
"""
from __future__ import annotations

import difflib
import re
from collections import Counter
from typing import List, Sequence, Tuple

# 与 deai/contracts/forbidden_words.txt 逐字对应的运行时副本（10 词）。
# 改词表流程：用户确认后改 deai/contracts/forbidden_words.txt → 同步此处。
FORBIDDEN_WORDS: Tuple[str, ...] = (
    "综上所述", "值得注意的是", "赋能", "闭环", "抓手",
    "全链路", "多维度", "显著提升", "夯实基础", "生态化反",
)

INPUT_MAX = 100          # 契约 C1：输入上限（字 = len()，strip 后计数）
RATIO_NUM, RATIO_DEN = 12, 10  # 输出 ≤ 原长 120%，整数运算避免浮点误差
MIN_DIFF = 0.10          # 像人闸最低改写幅度（与权威实现默认一致）

# 事实闸名称（失败即回退原文）——与权威实现 FACT_GATES 同集
FACT_GATES = ("数字闸", "专名闸", "新增事实闸")

NUMBER_RE = re.compile(r"[0-9０-９]+(?:\.[0-9０-９]+)?%?")
LATIN_RE = re.compile(r"[A-Za-z]+")
SPAN_RES = (
    re.compile(r"“([^”]*)”"),
    re.compile(r"「([^」]*)」"),
    re.compile(r"『([^』]*)』"),
    re.compile(r"《([^》]*)》"),
    re.compile(r'"([^"]*)"'),
    re.compile(r"'([^']*)'"),
)


def quote_spans(text: str) -> List[str]:
    spans: List[str] = []
    for rx in SPAN_RES:
        spans.extend(s for s in rx.findall(text) if s)
    return spans


def runtime_gates(
    source: str,
    rewritten: str,
    forbidden: Sequence[str] = FORBIDDEN_WORDS,
    min_diff: float = MIN_DIFF,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """对「原文 vs 模型改写」跑六闸（无 facts 卡路径）。

    返回 (fact_failures, warnings)：
    - fact_failures 非空 → 调用方必须回退原文（契约§6）；
    - warnings = 非事实闸失败明细（长度/套话/像人），改写仍可用。
    """
    source, rewritten = source.strip(), rewritten.strip()
    fact_failures: List[Tuple[str, str]] = []
    warnings: List[str] = []

    # ---- 长度闸（非事实：超长仍返回但告警）----
    limit = len(source) * RATIO_NUM // RATIO_DEN
    if len(rewritten) > limit:
        warnings.append(f"长度闸: 改写{len(rewritten)}字超上限{limit}(原文{len(source)}×120%)")

    # ---- 数字闸（事实）----
    num_s, num_r = Counter(NUMBER_RE.findall(source)), Counter(NUMBER_RE.findall(rewritten))
    lost_nums = dict(num_s - num_r)
    if lost_nums:
        fact_failures.append(("数字闸", f"数字缺失或减少: {lost_nums}"))

    # ---- 专名闸（事实）----
    span_s, span_r = quote_spans(source), quote_spans(rewritten)
    lost_spans = [s for s in span_s if s not in rewritten]
    latin_s, latin_r = Counter(LATIN_RE.findall(source)), Counter(LATIN_RE.findall(rewritten))
    lost_latin = dict(latin_s - latin_r)
    if lost_spans or lost_latin:
        parts = []
        if lost_spans:
            parts.append(f"引文/书名内容被改: {lost_spans}")
        if lost_latin:
            parts.append(f"英文专名丢失: {lost_latin}")
        fact_failures.append(("专名闸", "；".join(parts)))

    # ---- 新增事实闸（事实）----
    new_nums = dict(num_r - num_s)
    new_latin = dict(latin_r - latin_s)
    new_spans = [s for s in span_r if s not in source]
    if new_nums or new_latin or new_spans:
        parts = []
        if new_nums:
            parts.append(f"新增数字: {new_nums}")
        if new_latin:
            parts.append(f"新增英文: {new_latin}")
        if new_spans:
            parts.append(f"新增引文/书名: {new_spans}")
        fact_failures.append(("新增事实闸", "；".join(parts)))

    # ---- 套话闸（非事实）----
    hits = [w for w in forbidden if w in rewritten]
    if hits:
        warnings.append(f"套话闸: 含禁词 {hits}")

    # ---- 像人闸（非事实）----
    diff = 1.0 - difflib.SequenceMatcher(None, source, rewritten, autojunk=False).ratio()
    if diff < min_diff:
        warnings.append(f"像人闸: 与原文差异率{diff:.2f}低于{min_diff}，改写幅度不足")

    return fact_failures, warnings

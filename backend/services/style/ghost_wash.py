# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
幽灵草稿确定性洗层（三平面分权·呈现平面 P1，2026-08-29，导师方案）。

执法哲学：字数闸已证明的路——**prompt 管不住的确定性约束下沉代码层**。
中档模型对禁令服从度差（实测禁词表命中仍漏），洗层用 100% 命中率的
正则替代模型服从，作用域严格限定在「采纳线前」的 AI 提案（幽灵草稿），
永不碰作者正文。

三条铁律（导师方案 §四，代码化）：
1. **只洗命中点，永不全局改写**：仅 severity=blocker 且精确命中且有
   alternative 的条目做替换；无 alternative 只记录（chip 呈现）；
   warning 档永不动手（提醒语义，动手即越权）。
2. **全透明**：返回 hits 清单 + 原稿快照，调用方据此出 diff chip
   （「已规避 N 处你的禁忌词 · 查看原稿」），无 chip 不改文。
3. **防复合词误伤**：命中若被同表更长的 pattern 覆盖（「深邃」落在
   「深邃的眼」里），短词让位——只按最长命中条目处理。

纯函数、零 LLM、零 IO。测试：test_ghost_wash.py。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from backend.services.style.prohibitions import ProhibitionSet


@dataclass
class WashHit:
    """一次命中记录（前端 chip 与 P2 修补重试的依据）。"""
    pattern: str
    span: str              # 命中片段原文
    start: int             # 命中起点（原稿坐标，仅供展示排序）
    replaced: bool         # True=已替换 False=仅记录（无替代词）
    alternative: str = ""


@dataclass
class WashResult:
    text: str
    hits: List[WashHit] = field(default_factory=list)
    # 原稿快照：发生任何替换时保留洗前全文（前端「查看原稿/用原稿」用）
    original_text: str = ""

    @property
    def replaced_hits(self) -> List[WashHit]:
        return [h for h in self.hits if h.replaced]

    @property
    def residual_hits(self) -> List[WashHit]:
        """未替换的 blocker 命中（无替代词）——P2 句级修补重试的触发依据。"""
        return [h for h in self.hits if not h.replaced]


def wash_ghost_text(text: str, ps: Optional[ProhibitionSet]) -> WashResult:
    """对幽灵草稿执行确定性洗（见模块 docstring 三铁律）。

    ps 为空集合 / None → 原样返回零命中（无负面清单的书逐字节零变化）。
    """
    if ps is None or not ps or not text:
        return WashResult(text=text)

    # 1. 收集 blocker 命中（含重叠），按「最长 pattern 让位」去重叠
    blocker_entries = [
        (m, e) for m, e in ps.finditer(text)
        if (e.severity or "warning") == "blocker" and e.pattern
    ]
    if not blocker_entries:
        return WashResult(text=text)

    kept: List[Tuple] = []
    for m, e in blocker_entries:
        overlapped = False
        for i, (km, ke) in enumerate(kept):
            # 区间重叠：短 pattern 让位长 pattern；等长同区间保先到
            if m.start() < km.end() and km.start() < m.end():
                if len(e.pattern) > len(ke.pattern):
                    kept[i] = (m, e)
                overlapped = True
                break
        if not overlapped:
            kept.append((m, e))
    kept.sort(key=lambda t: t[0].start())

    # 2. 逐命中处置：有 alternative 且非 regex → 替换；否则仅记录
    pieces: List[str] = []
    hits: List[WashHit] = []
    cursor = 0
    replaced_any = False
    for m, e in kept:
        hits.append(WashHit(
            pattern=e.pattern, span=text[m.start():m.end()],
            start=m.start(), replaced=False, alternative=e.alternative or "",
        ))
        if e.alternative and not e.is_regex:
            pieces.append(text[cursor:m.start()])
            pieces.append(e.alternative)
            cursor = m.end()
            hits[-1].replaced = True
            replaced_any = True
    pieces.append(text[cursor:])
    washed = "".join(pieces)

    return WashResult(
        text=washed,
        hits=hits,
        original_text=text if replaced_any else "",
    )


def build_repair_prompt(text: str, residual_hits: List[WashHit]) -> str:
    """P2 句级修补指令（单次重试用；整段原文带回，只改含禁词的句子）。

    设计：不是重生成——把命中的禁词与替代方向明示，要求其余原文照出。
    无 residual 时不该被调用（调用方守门）。
    """
    lines = ["以下续写稿中含有作者明令回避的词，请逐处修改："]
    for h in residual_hits[:5]:
        if h.alternative:
            lines.append(f"- 「{h.pattern}」→ 改用「{h.alternative}」或同义具体表达")
        else:
            lines.append(f"- 「{h.pattern}」→ 删除或换成具体的动作、物件、对话")
    lines.append("只修改含这些词的句子，其余句子一字不改。保持原文字数与语气，只输出修改后的完整正文。")
    lines.append("")
    lines.append("--- 原稿 ---")
    lines.append(text)
    return "\n".join(lines)

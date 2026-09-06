# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 大纲就近节拍（共享判据：dock 挂件与 stitch 意图块共用）
"""
就近铁律的数据面（2026-08-25 治理 + 实测修复）。

来源：挂件曾一步跳到高潮场面（意图/养料天然指向章末）——dock_generator 为此
把作者大纲里「接下来一两拍」递给 prompt，LLM 贴着生发。同日实测复盘发现
stitch/continue 的章节意图块有同型病（整章大纲前 N 字粗暴截断，模型直奔终点
冲章 + 截在半截词），遂提取为共享模块：就近判定只有一处定义。

已写判定走 text_match 共享判据（3 字片段命中率 ≥2/3）：不取更长片段——大纲是
速记、作者成文常改写，4 字片段对改写容差过狠，会把真已写误判未写、就近节拍
回退重推旧拍（反向噪声）。无可判片段按已写跳过（结构性短行不携带画面信息）。
"""
from __future__ import annotations

from typing import List

from backend.services.adaptive import text_match

# 大纲就近节拍：结构性行标签太短不携带画面信息，跳过
# （片段过滤表统一为 text_match.FRAGMENT_INVALID_CHARS——标点+数字，P2 治理）
OUTLINE_NEARBY_MIN_LINE = 8
OUTLINE_NEARBY_LINE_MAX = 60  # 每拍注入上限（速记原文截断，防超长行挤占预算）

# 非剧情行判定的引号字符集（整行被引号包裹=引语原文，不是本章剧情）
_QUOTE_WRAP_CHARS = "「」『』“”\"'"


def outline_line_is_meta(line: str) -> bool:
    """该行是否非剧情的元信息行（卷首致辞/引语/作品引用/超短指示）。

    2026-09-03 实测：大纲常以「以罗曼·罗兰的巨著《约翰·克利斯朵夫》……
    名言开篇」这类行开头——不过滤会被当就近节拍喂进 stitch 意图块与 dock
    挂件取材池，模型照着写进正文（致辞进意图块与进猜测行是两个通道同一个
    洞，intent_inference._extract_arc_from_outline 与本函数共用此判据）。
    三选一即元信息：整行引语 / 含《》（作品引用）/ strip 后 <6 字（指示短行）。
    """
    l = (line or "").strip()
    if not l:
        return True
    if l[0] in _QUOTE_WRAP_CHARS and l[-1] in _QUOTE_WRAP_CHARS:
        return True
    if "《" in l:
        return True
    return len(l) < 6


def outline_line_written(line: str, written: str) -> bool:
    """大纲行是否已写进正文（共享判据 text_match；无可判片段按已写跳过防噪音）。

    命中率 ≥2/3（6 片段须中 4）：治通用三字组散落正文造成的误判已写。
    """
    return text_match.matches(
        line, written,
        threshold=2 / 3,        # 6 片段须中 4：治通用三字组散落误判已写
        size=3, max_fragments=6,  # 片段数与旧实现一致
        no_fragments=True,      # 无可判片段按已写跳过（结构性短行，旧兜底保持）
    )


def outline_nearby(outline_text: str, written: str, take: int = 2) -> List[str]:
    """大纲就近节拍：从头扫作者大纲，跳过已写行，取接下来 1-2 拍原文。

    已写判定纯算法（outline_line_written）；全部已写（章近尾声）/ 无大纲 →
    空列表（零注入零变化契约）。元信息行（引语/作品引用/指示短行）不进
    候选（outline_line_is_meta，2026-09-03 卷首致辞进意图块事故）。
    """
    lines = [
        l.strip()
        for l in (outline_text or "").splitlines()
        if len(l.strip()) >= OUTLINE_NEARBY_MIN_LINE and not outline_line_is_meta(l)
    ]
    if not lines:
        return []
    out: List[str] = []
    for i, line in enumerate(lines):
        if outline_line_written(line, written):
            continue
        out.append(line[:OUTLINE_NEARBY_LINE_MAX])
        for nxt in lines[i + 1:]:
            if not outline_line_written(nxt, written):
                out.append(nxt[:OUTLINE_NEARBY_LINE_MAX])
                break
        break
    return out[:take]

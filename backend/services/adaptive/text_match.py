# Velluma - NLE-ADF 3.0 文本匹配共享判据
# AGPL-3.0
"""
「3 字滑窗」一族噪声匹配的共享判据（P2 治理，2026-08-25）。

设计意图：must_hit 已达成判定（direction_weights._is_met）、大纲行已写判定
（dock_generator._outline_line_written）等消费方曾各自为政地用
「任一 / 过半 3 字片段命中全文即算匹配」——常用三字组（「他没有」「不多时」）
几乎必然散落在任何长文本里，系统性产生两类反向噪声：

- 未达成的叙事任务被判已达成 → 推动力提前熄火（方向权重信号失真）；
- 未写的大纲行被判已写 → 就近节拍跳到更远的拍子（挂件就近铁律被抵消）。

统一收紧为「片段命中率阈值」：把条目拆成滑窗片段、过滤含标点/数字的
片段，命中率达到调用方给的阈值才算匹配；整串直接命中可作捷径；可选
「就近窗口」只看文本尾部 N 字（判「写得近不近」的消费方用，默认全文——
must_hit 写在章首也算达成，范围语义由调用方决定，本模块只提供窗口参数）。

纯函数、零依赖（仅标准库；不 import LLM / DB / jieba）——保证任何心跳
路径都能零成本调用与单测。B4（canon_watch 词边界）是另一族匹配
（专有名词 vs 分词边界），不在此模块，见 canon_watch._name_in_text。
"""
from __future__ import annotations

from typing import List, Optional

# 片段含这些字符即弃：标点/数字/空白既不稳定（虚词连接处）也易撞通用搭配。
# 取 B1（direction_weights 旧表）与 B3（dock_generator 旧表 _PUNCT）两套
# 过滤字符的并集——统一判据后两处消费方共用一张表。
FRAGMENT_INVALID_CHARS = set(
    "，。、；：！？“”‘’「」『』（）《》·…—0123456789 \n\t\r"
)


# ============================================================
# 片段提取与命中率
# ============================================================

def sliding_fragments(item: str, size: int = 3, max_fragments: int = 6) -> List[str]:
    """把条目拆成 size 字滑窗片段（保序去重、过滤含标点/数字/空白的片段）。

    至多保留前 max_fragments 个——条目是短语/大纲行，前几个片段已够判，
    全量取片只会让长条目在短正文上必然「命中率不足」之外再添偶发噪声。
    """
    frags: List[str] = []
    seen = set()
    for i in range(len(item) - size + 1):
        frag = item[i:i + size]
        if any(c in FRAGMENT_INVALID_CHARS for c in frag):
            continue
        if frag not in seen:
            seen.add(frag)
            frags.append(frag)
            if len(frags) >= max_fragments:
                break
    return frags


def fragment_hit_rate(
    item: str,
    text: str,
    *,
    size: int = 3,
    max_fragments: int = 6,
    tail_chars: Optional[int] = None,
) -> Optional[float]:
    """片段命中率（0-1）；无可判片段返回 None（由调用方决定兜底语义）。

    Args:
        tail_chars: 非 None 时只在文本尾部 N 字内判（「就近窗口」——
            消费方要判「写得近不近」时用；None = 全文）。
    """
    if tail_chars is not None and tail_chars > 0 and len(text) > tail_chars:
        text = text[-tail_chars:]
    frags = sliding_fragments(item, size=size, max_fragments=max_fragments)
    if not frags:
        return None
    hits = sum(1 for f in frags if f in text)
    return hits / len(frags)


def matches(
    item: str,
    text: str,
    *,
    threshold: float = 0.5,
    size: int = 3,
    max_fragments: int = 6,
    tail_chars: Optional[int] = None,
    exact_shortcut: bool = True,
    no_fragments: bool = False,
) -> bool:
    """统一判据入口：整串捷径 + 片段命中率 ≥ threshold 才算匹配。

    Args:
        threshold: 命中率阈值（0-1）。比较带 1e-9 容差，2/3 这类浮点
            阈值下 4/6 命中稳定判真。
        exact_shortcut: 整串直接命中（item in 判定窗口）直接算匹配——
            逐字写过的条目没必要再走片段统计。
        no_fragments: 条目无可判片段（纯标点/数字/过短）时的兜底语义。
            B1 取 False（无关键词即无证据，判未达成）；B3 取 True
            （结构性短行按已写跳过防噪音）——两处旧兜底语义原样保留。
    """
    if not (item or "").strip():
        # 空条目交由调用方短路（B1 判已达成）；此处防御性返回 no_fragments
        return no_fragments
    if tail_chars is not None and tail_chars > 0 and len(text) > tail_chars:
        text = text[-tail_chars:]
    if exact_shortcut and item in text:
        return True
    rate = fragment_hit_rate(item, text, size=size, max_fragments=max_fragments)
    if rate is None:
        return no_fragments
    return rate + 1e-9 >= threshold

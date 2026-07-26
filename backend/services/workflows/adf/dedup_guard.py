"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
去重守卫（Dedup Guard）—— 剧情回路护栏（纯代码 0 LLM）。

职责：
- 字符级 shingle（n 字滑窗）+ Jaccard 相似度，度量两段/两段的文字重复度
- 在整章段落序列中找"非相邻的连续重复块"（块 A 与块 A′ 逐段相同）
- 删除后出现的重复块，保留先出现的，重拼正文

设计意图（针对真实故障）：
- 一次真实生成中，第 1 段写了仓库对峙（块 A，14 段），第 3 段把块 A 近乎逐字
  重写一遍（块 A′，13 段），最终文本含 ~600 字重复。锚点审计（头尾采样）、
  OOC 裁判、一致性审计全都漏掉了它——它们都不做"全文自我相似"检查。
- 纯代码检测：重复块是字面级近乎复制，shingle Jaccard 是最直接的度量，
  不需要 LLM 判断，零成本、零误伤风险可控。
- 短段（< min_para_chars）不参与锚定配对：防"灰尘还没散。"这类短句在
  不同场景自然重现导致误报；但短段可以是被长段锚定的重复块的一部分。

业务场景：
- segment_writer.py Phase 4：每段写完做段级回路检测（segment_too_similar）
- consistency_guard.py Phase 7 第 0 步：全文重复块清除（remove_duplicate_blocks）

使用方式：
    if segment_too_similar(new_segment, prev_segment):
        ...  # 触发重写
    new_text, removed = remove_duplicate_blocks(final_text)

依赖项：
- 无（纯算法，标准库）
"""

import logging
import re
from difflib import SequenceMatcher
from typing import List, Set, Tuple

logger = logging.getLogger(__name__)

# 半角标点 → 全角标点（标点统一，防"。,"差异稀释相似度）
_PUNCT_TABLE = str.maketrans({
    ",": "，", ".": "。", "!": "！", "?": "？",
    ";": "；", ":": "：", "(": "（", ")": "）",
})
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """归一化文本：去全部空白/换行 + 半角标点转全角。"""
    if not text:
        return ""
    return _WHITESPACE_RE.sub("", text).translate(_PUNCT_TABLE)


def char_shingles(text: str, n: int = 10) -> Set[str]:
    """把文本归一化后切 n 字符滑窗集合（shingles）。

    Args:
        text: 原始文本
        n: 滑窗长度（默认 10 字，对中文足够区分场景）

    Returns:
        shingle 集合；归一化后不足 n 字时返回单元素集合（整串）或空集合
    """
    norm = _normalize(text)
    if not norm:
        return set()
    if len(norm) <= n:
        return {norm}
    return {norm[i:i + n] for i in range(len(norm) - n + 1)}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    """Jaccard 相似度 |A∩B| / |A∪B|；任一为空返回 0。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / (len(a) + len(b) - inter)


def segment_too_similar(
    a: str,
    b: str,
    threshold: float = 0.5,
    min_chars: int = 200,
) -> bool:
    """判断两段正文是否"内容重复"（段级回路护栏用）。

    条件：两段归一化后都 >= min_chars（短段不判，防短句自然重现误报）
    且 Jaccard(10-char shingles) >= threshold。

    Args:
        a / b: 两段正文
        threshold: 相似度阈值（默认 0.5，段级判重宜严）
        min_chars: 参与判重的最小长度（默认 200 字）

    Returns:
        True = 高度重复
    """
    norm_a, norm_b = _normalize(a), _normalize(b)
    if len(norm_a) < min_chars or len(norm_b) < min_chars:
        return False
    return _jaccard(char_shingles(a), char_shingles(b)) >= threshold


def find_duplicate_blocks(
    paras: List[str],
    threshold: float = 0.55,
    min_para_chars: int = 30,
    min_block: int = 2,
    min_isolated_block_chars: int = 200,
) -> List[Tuple[int, int]]:
    """在段落序列中找"非相邻的连续重复块"，返回应删除的【后出现】块范围。

    算法：
    1. 两两计算段落相似度，长段对（双方 >= min_para_chars）相似度 >= threshold
       且 j - i >= 2（非相邻）→ 锚定配对 (i, j)
    2. 从锚定向后延伸：para[i+k] 与 para[j+k] 持续"匹配"（长段对走相似度；
       涉及短段时退化为归一化全等——短段可以是块的一部分，但不能锚定）
    3. 连续匹配 >= min_block 段 → 块 A′ = [j, j+len-1] 标记删除（保留先出现的 A）

    孤立锚定删除（修跨段重复漏检事故）：若锚定命中但无法向后延伸（length=1、
    back=0），即"孤立跨段重复"——两段几乎逐字相同但中间被别的段落隔开——
    原本的 min_block=2 会把它直接丢弃不删。此类形态在真实生成中很常见（一段
    战斗描写把两个本应被判重的段落拆开）。此处补一条路径：当且仅当被删段（A′）
    归一化长度 >= min_isolated_block_chars 时，允许 min_block=1 删除该孤立段。
    长度门槛防误删"短句重现"（如人物口头禅、场景定场白短句的合理复现）。

    相似度度量：max(Jaccard(10-char shingles), SequenceMatcher ratio)。
    仅用 shingle Jaccard 会被"删一个字导致后续滑窗全错位"的近乎逐字复制击穿
    （真实 A′ 块常见单字增删），SequenceMatcher 对错位鲁棒，二者取 max 互补。

    Args:
        paras: 段落列表（已按 \\n\\n 切分）
        threshold: 段落级相似度阈值（默认 0.55，近乎逐字复制才会命中）
        min_para_chars: 锚定配对的最小段长（短段不锚定）
        min_block: 构成"连续块"的最少匹配段数（默认 2，防短句误删）
        min_isolated_block_chars: 孤立单段锚定允许删除的最小被删段长度（归一化后）；
            低于此长度的孤立锚定不删，避免误删短句重现。设为很大可禁用此路径。

    Returns:
        删除范围列表 [(start, end), ...]，inclusive 段号，按起点升序、不重叠
    """
    n = len(paras)
    if n < 2:
        return []

    norms = [_normalize(p) for p in paras]
    shingles = [char_shingles(p) for p in paras]
    is_long = [len(nm) >= min_para_chars for nm in norms]

    def _long_pair_similar(i: int, j: int) -> bool:
        return (
            _jaccard(shingles[i], shingles[j]) >= threshold
            or SequenceMatcher(None, norms[i], norms[j]).ratio() >= threshold
        )

    def _match(i: int, j: int) -> bool:
        """两段是否"相同"：长段对走相似度；涉及短段退化为归一化全等。"""
        if is_long[i] and is_long[j]:
            return _long_pair_similar(i, j)
        return bool(norms[i]) and norms[i] == norms[j]

    # 找锚定配对（长段对 + 非相邻），按 (j, i) 排序保证先处理靠前的块
    anchors: List[Tuple[int, int]] = []
    for i in range(n):
        if not is_long[i]:
            continue
        for j in range(i + 2, n):
            if not is_long[j]:
                continue
            if _long_pair_similar(i, j):
                anchors.append((i, j))

    delete_ranges: List[Tuple[int, int]] = []
    covered = [False] * n  # 已被标记删除的段（A′ 段不再作为新锚点的 A 侧延伸依据）

    for i, j in anchors:
        if covered[j]:
            continue  # 该块已被更早的锚点覆盖
        # 向后延伸连续匹配
        length = 1
        while (
            j + length < n
            and i + length < j  # A 侧不能越过 A′ 起点（防自重叠）
            and not covered[j + length]
            and _match(i + length, j + length)
        ):
            length += 1
        # 向前对齐块头：锚点之前也匹配的段并入（真实案例：重复块开头共同的短句
        # "灰尘还没散。" 是短段不能锚定，但属于重复块的一部分，不删会留下悬挂残句）
        back = 0
        while (
            i - back - 1 >= 0
            and j - back - 1 > i - back - 1  # 两侧不重叠
            and not covered[j - back - 1]
            and _match(i - back - 1, j - back - 1)
        ):
            back += 1
        # 判定是否构成可删除块。
        # 正常路径：连续匹配段数 >= min_block（默认 2，防短句重现误删）。
        # 孤立锚定路径（length=1 且 back=0）：两段几乎逐字相同但被中间段落隔开，
        # 无法向后延伸连续匹配。此情况下若被删段足够长（>= min_isolated_block_chars），
        # 仍允许删除——这正是跨段重复漏检事故的典型形态。
        block_len = back + length
        isolated = (length == 1 and back == 0)
        a_prime_chars = sum(len(norms[k]) for k in range(j - back, j + length))
        if block_len >= min_block or (isolated and a_prime_chars >= min_isolated_block_chars):
            delete_ranges.append((j - back, j + length - 1))
            for k in range(j - back, j + length):
                covered[k] = True

    if not delete_ranges:
        return []

    # 合并重叠/相邻范围（不同锚点可能标出同一块的相邻部分）
    delete_ranges.sort()
    merged: List[List[int]] = [list(delete_ranges[0])]
    for start, end in delete_ranges[1:]:
        if start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def remove_duplicate_blocks(
    text: str,
    threshold: float = 0.55,
    min_para_chars: int = 30,
    min_block: int = 2,
    min_isolated_block_chars: int = 200,
) -> Tuple[str, List[Tuple[int, int]]]:
    """删除正文中的非相邻连续重复块（保留先出现的块），重拼。

    Args:
        text: 整章正文（按 \\n\\n 分段）
        其余参数同 find_duplicate_blocks

    Returns:
        (新文本, 删除范围列表)；无重复时新文本 == 原文、范围为空
    """
    paras = [p for p in (text or "").split("\n\n") if p.strip()]
    if len(paras) < 2:
        return text, []

    removed = find_duplicate_blocks(
        paras,
        threshold=threshold,
        min_para_chars=min_para_chars,
        min_block=min_block,
        min_isolated_block_chars=min_isolated_block_chars,
    )
    if not removed:
        return text, []

    removed_set = set()
    for start, end in removed:
        removed_set.update(range(start, end + 1))
    kept = [p for idx, p in enumerate(paras) if idx not in removed_set]
    removed_chars = sum(len(paras[idx]) for idx in removed_set)
    logger.info(
        f"[DedupGuard] 删除 {len(removed)} 个重复块（段 {removed}），"
        f"共 {removed_chars} 字，{len(paras)} 段 → {len(kept)} 段"
    )
    return "\n\n".join(kept), removed

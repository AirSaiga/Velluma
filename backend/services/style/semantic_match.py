# -*- coding: utf-8 -*-
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
语义匹配器（任务包 D）——embedding 相似度抓「换字逃逸」。

职责：
- 精确匹配（prohibitions.finditer）只能抓逐字命中；作者/AI 把「眼底闪过
  一丝」改写成「眼底掠过一抹」即逃逸。本模块用 embedding 余弦相似度把
  变体句从正文段里捞出来，挂进完稿审计报告（/adaptive/finish 的
  semantic_hits），由作者裁决——只提示，绝不拦截、绝不改正文。

边界（⚠ 红线）：
- 只进 finish 报告；不进任何 SSE 流式路径、不进收件箱、不进 scan-negative
  （那边是精确匹配的领地）。
- embedding 未配置（is_embedding_configured() False，SQLite 默认后端恒
  False）→ 立即返回 []，零网络调用零成本——SQLite 默认路径行为逐字节
  不变。
- 全程 try/except：任何失败返回 []，绝不阻塞完稿审计。
- 阈值/上限常量未经真实写作校准（见校准脚本
  scripts/calibrate_semantic_threshold.py），命中一律按「疑似」呈现。

切段口径：与文风指纹同一把尺子（fingerprint.split_sentences 句切），
超长句再按逗号类标点二次细分——段太长会稀释 embedding 信号。
"""

import hashlib
import logging
import re
from typing import Dict, List, Tuple

from backend.services.llm.embedding import (
    cosine_similarity,
    get_embeddings,
    is_embedding_configured,
)
from backend.services.style.fingerprint import split_sentences
from backend.services.style.prohibitions import ProhibitionSet

logger = logging.getLogger(__name__)


# ============================================================
# 常量（待实测校准——scripts/calibrate_semantic_threshold.py）
# ============================================================

SEMANTIC_HIT_THRESHOLD = 0.78        # 命中阈值（变体句/无关句分离度待校准）
SEMANTIC_SCAN_MAX_SEGMENTS = 200     # 单次扫描段数上限（防超长章拖爆批量）
SEMANTIC_MIN_PATTERN_CHARS = 4       # 更短的词靠精确匹配已覆盖，不进语义流
SEMANTIC_SEGMENT_MAX_CHARS = 60      # 超长段按逗号类标点二次细切的门槛
SEMANTIC_MAX_HITS_PER_PATTERN = 3    # 每 pattern 最多报 3 段（防刷屏）
SEMANTIC_MAX_TOTAL_HITS = 20         # 总命中截断（按相似度降序取前 20）

# 二次细切标点（长句内的自然停顿；句末标点已由 split_sentences 处理）
_SEGMENT_SUB_SPLIT = re.compile(r"[，；、：]")

# 长句细切后的碎片下限（与 split_sentences 的 >2 字口径一致）
_SEGMENT_MIN_CHARS = 2


# ============================================================
# 模式向量缓存（进程生命周期，无 TTL——仿 adaptive._STYLE_HINT_CACHE 先例）
# ============================================================
# 禁忌 pattern 集合是低频变动数据（负面清单编辑/系统陈词增删才变），
# 而段向量每次扫描都不同。key 由 model|dims|sorted(patterns) 派生：
# 任一要素变（含换 embedding 模型/维度）即 miss 重算，天然失效。
# value 存 (entry 在传入列表中的下标, 向量) 以保持与调用序对齐。
_PATTERN_EMB_CACHE: Dict[str, List[Tuple[int, list]]] = {}

# 缓存条目上限（FIFO 淘汰）：防长跑进程里高频改负面清单导致无界增长
_PATTERN_EMB_CACHE_MAX_SETS = 32


async def _pattern_vectors(patterns: List[str]) -> List[list]:
    """取一组 pattern 的向量（按传入序对齐），miss 才批量请求一次。

    全空向量（整体请求失败）不落缓存——瞬时网络故障不应毒化进程缓存。
    """
    from backend.core.model_config import get_embedding_connection

    connection = get_embedding_connection()
    cache_key = hashlib.sha1(
        (
            f"{connection['model']}|{connection['dimensions']}|"
            + "|".join(sorted(patterns))
        ).encode("utf-8")
    ).hexdigest()

    cached = _PATTERN_EMB_CACHE.get(cache_key)
    if cached is not None:
        # (idx, vec) 对按 idx 排序还原成与传入序对齐的向量列表
        return [vec for _, vec in sorted(cached, key=lambda t: t[0])]

    vectors = await get_embeddings(patterns)
    if any(vectors):
        if len(_PATTERN_EMB_CACHE) >= _PATTERN_EMB_CACHE_MAX_SETS:
            _PATTERN_EMB_CACHE.pop(next(iter(_PATTERN_EMB_CACHE)))
        _PATTERN_EMB_CACHE[cache_key] = list(enumerate(vectors))
    return vectors


def _split_segments(text: str) -> List[str]:
    """正文切段：句切（同一把尺子）→ 超长句按逗号类标点细切 → 截段数上限。"""
    segments: List[str] = []
    for sentence in split_sentences(text):
        if len(sentence) <= SEMANTIC_SEGMENT_MAX_CHARS:
            segments.append(sentence)
        else:
            for frag in _SEGMENT_SUB_SPLIT.split(sentence):
                frag = frag.strip()
                if len(frag) > _SEGMENT_MIN_CHARS:
                    segments.append(frag)
    return segments[:SEMANTIC_SCAN_MAX_SEGMENTS]


async def semantic_scan_text(text: str, prohibitions: ProhibitionSet) -> List[Dict]:
    """语义扫描：正文段 × 禁忌 pattern 的 embedding 余弦相似度匹配。

    Returns:
        [{"segment", "pattern", "similarity", "severity", "alternative",
          "source"}]——按 similarity 降序、每 pattern ≤3 段、总 ≤20 条；
        未配置 embedding / 空输入 / 无候选模式 / 任何异常 → []。
    """
    try:
        # 红线：未配置（SQLite 默认恒 False）第一时刻短路，零网络调用
        if not is_embedding_configured():
            return []
        if not prohibitions or not text:
            return []

        # 候选模式：非正则（正则的语义是句式形状而非词面）且长度达门槛
        candidates: List[Tuple[int, object]] = [
            (idx, e) for idx, e in enumerate(prohibitions.entries)
            if not e.is_regex and len(e.pattern) >= SEMANTIC_MIN_PATTERN_CHARS
        ]
        if not candidates:
            return []

        segments = _split_segments(text)
        if not segments:
            return []

        pattern_vecs = await _pattern_vectors([e.pattern for _, e in candidates])
        segment_vecs = await get_embeddings(segments)

        # 每段取全模式最大相似度；空向量位（embedding 失败条）跳过比较
        hits: List[Dict] = []
        for segment, seg_vec in zip(segments, segment_vecs):
            if not seg_vec:
                continue
            best_sim = -1.0
            best_entry = None
            for (_, entry), pat_vec in zip(candidates, pattern_vecs):
                if not pat_vec:
                    continue
                sim = cosine_similarity(seg_vec, pat_vec)
                if sim > best_sim:
                    best_sim = sim
                    best_entry = entry
            if best_entry is not None and best_sim >= SEMANTIC_HIT_THRESHOLD:
                hits.append({
                    "segment": segment,
                    "pattern": best_entry.pattern,
                    "similarity": round(best_sim, 3),
                    "severity": best_entry.severity,
                    "alternative": best_entry.alternative,
                    "source": best_entry.source,
                })

        # 每 pattern 按相似度取前 3 → 全局降序截 20
        by_pattern: Dict[str, List[Dict]] = {}
        for hit in hits:
            by_pattern.setdefault(hit["pattern"], []).append(hit)
        capped: List[Dict] = []
        for pattern_hits in by_pattern.values():
            pattern_hits.sort(key=lambda h: h["similarity"], reverse=True)
            capped.extend(pattern_hits[:SEMANTIC_MAX_HITS_PER_PATTERN])
        capped.sort(key=lambda h: h["similarity"], reverse=True)
        return capped[:SEMANTIC_MAX_TOTAL_HITS]
    except Exception as e:
        # 红线：语义扫描绝不阻塞调用方（完稿审计）
        logger.warning(f"[SemanticMatch] 扫描失败（静默降级为空）: {e}")
        return []


def invalidate_pattern_cache() -> None:
    """清空模式向量缓存（负面清单/系统陈词批量变更后可手动调用；正常流程无需）。"""
    _PATTERN_EMB_CACHE.clear()

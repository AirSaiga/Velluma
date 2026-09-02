# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 通用语义重合检测（约束治理二期 · 抢拍语义闸底座）
"""
「文本 A vs 目标文本集 B」的向量相似度检测（2026-09-02 二期）。

为什么需要它：既有 semantic_match.semantic_scan_text 写死为「文本 vs 禁词
模式集」（入参 ProhibitionSet、返回带 severity/alternative），抢拍检测要的是
「幽灵/挂件 vs 大纲就近节拍」的通用比对——本模块是那个通用件，复用
semantic_match 的切段（_split_segments 同一把尺子）与 embedding.py 的
get_embeddings_api_only（纯 API 入口：SQLite 默认部署可用，产物不落库）
/cosine_similarity，向量缓存模式同源（key=model|dims|目标集）。

纪律：
- 门控用 is_embedding_api_configured()（存储无关窄判定——纯 API 比对不需要
  pgvector，SQLite 默认部署可用）；未配置/任何失败一律返回 []（零变化契约）；
- 本期全部消费方均为 shadow（只落台账不动作），阈值是待校准占位——转正
  前必须先跑校准（scripts/calibrate_semantic_threshold.py 同思路）。

副作用：配置在场时发一次批量 embedding 请求；进程级目标向量缓存（FIFO）。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Tuple

from backend.services.llm.embedding import (
    cosine_similarity,
    get_embeddings_api_only,
    is_embedding_api_configured,
)
from backend.services.style.semantic_match import _split_segments

logger = logging.getLogger(__name__)

# 抢拍 shadow 阈值占位（未经实测校准——分离度校准后定档；shadow 期只攒分布）
BEAT_RUSH_SHADOW_THRESHOLD = 0.80
# 目标文本最短长度（更短的片段向量语义噪声大，不进比对）
_MIN_TARGET_CHARS = 4
# 命中上报上限（按相似度降序）
_MAX_HITS = 10

# 目标向量进程级缓存（与 semantic_match._PATTERN_EMB_CACHE 同模式：
# key=model|dims|sorted(目标集)，FIFO 淘汰；全空向量不落缓存）
_TARGET_EMB_CACHE: Dict[str, List[Tuple[int, list]]] = {}
_TARGET_EMB_CACHE_MAX_SETS = 32


async def _target_vectors(targets: List[str]) -> List[list]:
    """目标集向量（按传入序对齐），miss 才批量请求一次。"""
    from backend.core.model_config import get_embedding_connection

    connection = get_embedding_connection()
    cache_key = hashlib.sha1(
        (
            f"{connection['model']}|{connection['dimensions']}|"
            + "|".join(sorted(targets))
        ).encode("utf-8")
    ).hexdigest()
    cached = _TARGET_EMB_CACHE.get(cache_key)
    if cached is not None:
        return [vec for _, vec in sorted(cached, key=lambda t: t[0])]
    vectors = await get_embeddings_api_only(targets)
    if any(vectors):
        if len(_TARGET_EMB_CACHE) >= _TARGET_EMB_CACHE_MAX_SETS:
            _TARGET_EMB_CACHE.pop(next(iter(_TARGET_EMB_CACHE)))
        _TARGET_EMB_CACHE[cache_key] = list(enumerate(vectors))
    return vectors


async def semantic_overlap_hits(
    text: str,
    targets: List[str],
    *,
    threshold: float,
) -> List[Dict[str, Any]]:
    """文本与目标集的语义重合命中（[{segment, target, similarity}] 降序）。

    切段 = semantic_match 同一把尺子（句切→超长细切→段数上限）；相似度 =
    段向量 × 目标向量余弦，≥ threshold 记命中。未配置/空输入/任何异常 → []。
    """
    try:
        if not text or not targets or not is_embedding_api_configured():
            return []
        clean_targets = [str(t).strip() for t in targets
                         if t and len(str(t).strip()) >= _MIN_TARGET_CHARS]
        if not clean_targets:
            return []
        segments = _split_segments(text)
        if not segments:
            return []
        # 段向量每次新鲜（文本不同）；目标向量走缓存（目标集低频变动——
        # 大纲节拍在一章内基本稳定）
        seg_vectors = await get_embeddings_api_only(segments)
        if not seg_vectors or len(seg_vectors) != len(segments):
            return []
        target_vectors = await _target_vectors(clean_targets)

        hits: List[Dict[str, Any]] = []
        for seg, seg_vec in zip(segments, seg_vectors):
            if not seg_vec:
                continue
            best_sim = 0.0
            best_target = ""
            for target, t_vec in zip(clean_targets, target_vectors):
                if not t_vec:
                    continue
                sim = cosine_similarity(seg_vec, t_vec)
                if sim > best_sim:
                    best_sim, best_target = sim, target
            if best_target and best_sim >= threshold:
                hits.append({
                    "segment": seg,
                    "target": best_target,
                    "similarity": round(best_sim, 3),
                })
        hits.sort(key=lambda h: h["similarity"], reverse=True)
        return hits[:_MAX_HITS]
    except Exception as e:
        logger.debug(f"[semantic_overlap] 检测失败（静默降级为空）: {e}")
        return []

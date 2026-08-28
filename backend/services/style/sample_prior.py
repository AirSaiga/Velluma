# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

"""
P5 采纳率回流——样本先验（三平面分权·选择平面，2026-08-29 导师方案 §3.2）。

数据链：GHOST_DONE 帧带 ghost_token + sample_ids → 前端 ghost_adopt /
ghost_discard 埋点回传同 token → 本模块从 data/collab_events.jsonl 派生
每样本「注入后被采纳」的贝叶斯平滑先验，作为检索排序的**乘性微调因子
（±20% 封顶，只调序不筛选）**——改变的是「AI 看到哪几条示范」，不动作家
文本、不改 prompt 契约、零新增 LLM 调用。

纪律（与 scene_hint 软加成同款）：先验永不具备排他性；冷启动（无事件）
均匀先验 = 因子恒 1.0，行为与现状逐一致。归因噪声（采纳与否受内容/心情
影响）由平滑 + 封顶吸收。

缓存：按事件文件 mtime 失效——检索路径不能每次全文件扫（5MB 上限）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# 因子区间：prior=0 → 0.8，prior=1 → 1.2（线性，±20% 封顶）
PRIOR_FACTOR_MIN = 0.8
PRIOR_FACTOR_MAX = 1.2
# 拉普拉斯平滑：prior = (adopted + 1) / (total + 2)——冷启动 0.5 → 因子 1.0
_SMOOTH_A = 1
_SMOOTH_B = 2

_stats_cache: Dict[str, Tuple[int, int]] = {}
_stats_cache_mtime: float = -1.0


def _collab_events_path() -> Path:
    """协作埋点 JSONL（与 routes/chapter_generation/adaptive.py 同款锚定：
    项目根/data，尊重 VELLUMA_DATA_DIR；本文件上三级即项目根）。"""
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return data_dir / "collab_events.jsonl"


def _rotated_path() -> Path:
    base = _collab_events_path()
    return base.with_name(base.name + ".1")


def load_adoption_stats() -> Dict[str, Tuple[int, int]]:
    """读 collab 事件派生 {(book_id, sample_id): (adopted, discarded)}。

    ghost_adopt / ghost_discard 事件 detail 携带 sample_ids（GHOST_DONE 帧回传）
    ——同一次幽灵注入的每条样本记一票采纳/弃用。文件缺失/损坏/无相关事件
    → 空 dict（均匀先验，零变化）。带 mtime 缓存。
    """
    global _stats_cache, _stats_cache_mtime
    paths = [_collab_events_path(), _rotated_path()]
    try:
        mtime = max((p.stat().st_mtime for p in paths if p.exists()), default=-1.0)
    except Exception:
        mtime = -1.0
    if _stats_cache is not None and mtime == _stats_cache_mtime and _stats_cache_mtime >= 0:
        return _stats_cache

    stats: Dict[str, Tuple[int, int]] = {}
    for path in paths:
        try:
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    kind = ev.get("kind") or ""
                    if kind not in ("ghost_adopt", "ghost_discard"):
                        continue
                    book = str(ev.get("book_id") or "")
                    ids = ((ev.get("detail") or {}).get("sample_ids")) or []
                    if not book or not isinstance(ids, list):
                        continue
                    for sid in ids:
                        key = f"{book}:{sid}"
                        a, d = stats.get(key, (0, 0))
                        stats[key] = (a + 1, d) if kind == "ghost_adopt" else (a, d + 1)
        except Exception as e:
            logger.debug(f"[SamplePrior] 读 {path.name} 失败（跳过）: {e}")

    _stats_cache = stats
    _stats_cache_mtime = mtime
    return stats


def sample_prior_factor(book_id: str, sample_id: str) -> float:
    """单样本采纳先验因子（0.8~1.2；无数据恒 1.0）。向量流除距离、兜底流作
    排序末位键——只调序不筛选。"""
    stats = load_adoption_stats()
    entry = stats.get(f"{book_id}:{sample_id}")
    if not entry:
        return 1.0
    adopted, discarded = entry
    prior = (adopted + _SMOOTH_A) / (adopted + discarded + _SMOOTH_B)
    factor = PRIOR_FACTOR_MIN + (PRIOR_FACTOR_MAX - PRIOR_FACTOR_MIN) * prior
    # prior=0.5（冷启动/一比一）应恰为 1.0：线性映射天然满足
    return factor

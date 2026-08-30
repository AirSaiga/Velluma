# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
B3 · 用量可见 —— adaptive 流的 token 消耗聚合端点（P5 地基加固期批次 1）。

数据源：generation_runs 表（P0-2 已落库；run_id = adaptive_{chapter_id}，
stage 按组件拆账——命名口径见 services/adaptive/observing.py 模块头注释）。
本模块只做 SELECT 聚合，零写。

端点：
- GET /api/chapters/{chapter_id}/adaptive/usage ：本章 adaptive 调用消耗
  （total_calls / prompt_tokens / completion_tokens / by_stage 拆账）
- GET /api/books/{book_id}/adaptive/usage ：按书聚合——按日趋势（date →
  calls/tokens）+ 按 stage 汇总

聚合口径：
- token 总量 = prompt + completion + thinking（与既有 /cost-report 端点
  口径一致，两视图数字可互相印证）
- None token 字段按 0 计（降级行 record_degraded 只记 stage 不记用量）
- by_stage 按 total_tokens 降序（用量视图：大头在前）
- by_date 按 created_at 的 UTC 日期分桶（created_at 为 naive UTC，
  models.utc_now）——本地时区视角可能横跨相邻两天，属可接受的展示粒度
- 空数据（无 adaptive 调用/章节不存在）返回零值结构，不 404 不 500：
  用量视图是镜子不是闸门
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter, GenerationRun
from backend.services.utils.logging import get_runtime_logger

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api", tags=["adaptive-usage"])


# ============================================================
# stage → 作者可读标签（唯一权威来源：observing.py 模块头 + 各组件
# record_result 调用点。新增组件 stage 时同步补这里）
# ============================================================

_STAGE_LABELS: Dict[str, str] = {
    # ---- 心跳组件（heartbeat 触发，后台异步）----
    "adaptive.intent_inference": "意图反推",
    "adaptive.future_projection": "未来推测（走向卡）",
    "adaptive.dock_generator": "挂件生发",
    # ---- 完稿后处理 ----
    "adaptive.post_process.critique": "完稿审阅",
    # ---- 候选事件回流（settle / finish 各触发一次）----
    "adaptive.event_scout.settle": "候选事件（沉淀）",
    "adaptive.event_scout.finish": "候选事件（完稿）",
    # ---- stitch-ghost 五模式 + 压缩重试 ----
    "adaptive.stitch_ghost.stitch": "续写·缝合",
    "adaptive.stitch_ghost.continue": "续写·顺句",
    "adaptive.stitch_ghost.burst": "续写·连写",
    "adaptive.stitch_ghost.open": "续写·开篇",
    "adaptive.stitch_ghost.outline": "续写·细纲扩写",
    "adaptive.stitch_ghost.compress": "续写·压缩重试",
    # ---- 谋篇 ----
    "adaptive.spine_suggest": "谋篇建议",
    # ---- 沉淀涌现抽取（历史名：BS-ADF Loop3，adaptive 沿用未改名）----
    "loop3.emergent_facts": "涌现抽取（沉淀）",
}

# 前缀规则（带序号/动态后缀的 stage）
_STAGE_LABEL_PREFIXES: Tuple[Tuple[str, str], ...] = (
    # 残句修复（/adaptive/fix-sentence，批处理上限 5 → sentence_fix.0..4）
    ("sentence_fix.", "残句修复"),
)


def _stage_label(stage: str) -> str:
    """stage 标识 → 作者可读标签；未登记的原样返回（新增组件不炸视图）。"""
    label = _STAGE_LABELS.get(stage)
    if label:
        return label
    for prefix, prefix_label in _STAGE_LABEL_PREFIXES:
        if stage.startswith(prefix):
            return prefix_label
    return stage


# ============================================================
# 聚合（纯函数，单测直接打这里）
# ============================================================

def _new_bucket() -> Dict[str, Any]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
    }


def _accumulate(bucket: Dict[str, Any], run: GenerationRun) -> None:
    """单行 generation_runs 累入桶（None token 按 0 计）。"""
    bucket["calls"] += 1
    bucket["prompt_tokens"] += run.prompt_tokens or 0
    bucket["completion_tokens"] += run.completion_tokens or 0
    bucket["thinking_tokens"] += run.thinking_tokens or 0


def _finalize(bucket: Dict[str, Any]) -> Dict[str, Any]:
    """桶收尾：补 total_tokens（口径 = prompt+completion+thinking）。"""
    out = dict(bucket)
    out["total_tokens"] = (
        out["prompt_tokens"] + out["completion_tokens"] + out["thinking_tokens"]
    )
    return out


def _zero_totals() -> Dict[str, int]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
    }


def aggregate_by_stage(runs: List[GenerationRun]) -> Tuple[Dict[str, int], List[Dict[str, Any]]]:
    """按 stage 聚合行集 → (totals, by_stage 降序)。"""
    stage_buckets: Dict[str, Dict[str, Any]] = {}
    totals = _zero_totals()
    for run in runs:
        stage = run.stage or "unknown"
        bucket = stage_buckets.setdefault(stage, _new_bucket())
        _accumulate(bucket, run)
        totals["calls"] += 1
        totals["prompt_tokens"] += run.prompt_tokens or 0
        totals["completion_tokens"] += run.completion_tokens or 0
        totals["thinking_tokens"] += run.thinking_tokens or 0

    by_stage: List[Dict[str, Any]] = []
    for stage, bucket in stage_buckets.items():
        entry = {"stage": stage, "label": _stage_label(stage)}
        entry.update(_finalize(bucket))
        by_stage.append(entry)
    # 用量视图：大头在前；同量按 stage 名稳定排序
    by_stage.sort(key=lambda e: (-e["total_tokens"], e["stage"]))

    # 总账收尾（与 by_stage 同一口径：p+c+t）
    totals["total_tokens"] = (
        totals["prompt_tokens"] + totals["completion_tokens"] + totals["thinking_tokens"]
    )
    return totals, by_stage


def aggregate_by_date(runs: List[GenerationRun]) -> List[Dict[str, Any]]:
    """按 UTC 日期分桶 → date 升序列表（created_at 为 None 的行跳过日期桶，
    但 totals/by_stage 不受影响——由 aggregate_by_stage 另行计入）。"""
    date_buckets: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        if run.created_at is None:
            continue
        day = run.created_at.date().isoformat()
        bucket = date_buckets.setdefault(day, _new_bucket())
        _accumulate(bucket, run)
    return [
        {"date": day, **_finalize(bucket)}
        for day, bucket in sorted(date_buckets.items())
    ]


# ============================================================
# 端点
# ============================================================

@router.get("/chapters/{chapter_id}/adaptive/usage")
async def get_chapter_adaptive_usage(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """本章 adaptive 写作消耗（generation_runs 聚合，只读）。

    过滤口径：chapter_id 匹配 + run_id = adaptive_{chapter_id}（observing.py
    的 chapter 级常驻 recorder 约定）——其他引擎（adf/refinery）的 run 不计入。

    Returns:
        {
            "chapter_id": "...",
            "totals": {"calls", "prompt_tokens", "completion_tokens",
                       "thinking_tokens", "total_tokens"},
            "by_stage": [{"stage", "label", "calls", "prompt_tokens",
                          "completion_tokens", "thinking_tokens", "total_tokens"}]
        }
    """
    stmt = (
        select(GenerationRun)
        .where(GenerationRun.chapter_id == chapter_id)
        .where(GenerationRun.run_id == f"adaptive_{chapter_id}")
        .order_by(GenerationRun.created_at.asc())
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()

    totals, by_stage = aggregate_by_stage(list(runs))
    return {"chapter_id": chapter_id, "totals": totals, "by_stage": by_stage}


@router.get("/books/{book_id}/adaptive/usage")
async def get_book_adaptive_usage(
    book_id: str,
    db: AsyncSession = Depends(get_db),
):
    """本书 adaptive 写作消耗：按日趋势 + 按 stage 汇总（generation_runs
    聚合，只读）。

    过滤口径：经 chapters.book_id 归书 + run_id 前缀 adaptive_（autoescape
    防 LIKE 通配符歧义）。

    Returns:
        {
            "book_id": "...",
            "totals": {...同章端点...},
            "by_stage": [...同章端点...],
            "by_date": [{"date": "YYYY-MM-DD", "calls", "prompt_tokens",
                         "completion_tokens", "thinking_tokens", "total_tokens"}]
        }
    """
    stmt = (
        select(GenerationRun)
        .join(Chapter, GenerationRun.chapter_id == Chapter.id)
        .where(Chapter.book_id == book_id)
        .where(GenerationRun.run_id.startswith("adaptive_", autoescape=True))
        .order_by(GenerationRun.created_at.asc())
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()

    totals, by_stage = aggregate_by_stage(list(runs))
    by_date = aggregate_by_date(list(runs))
    return {"book_id": book_id, "totals": totals, "by_stage": by_stage, "by_date": by_date}

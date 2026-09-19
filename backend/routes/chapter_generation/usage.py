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
本模块聚合零写；唯一的写是 DELETE 测试端点（见下）。

端点：
- GET /api/chapters/{chapter_id}/adaptive/usage ：本章 adaptive 调用消耗
  （totals / by_stage 拆账 / by_lane 链路汇总）
- GET /api/books/{book_id}/adaptive/usage ：按书聚合——按日趋势（date →
  calls/tokens）+ 按 stage/链路汇总
- DELETE /api/chapters/{chapter_id}/adaptive/usage ：清空本章用量台账
  （测试用；flush→drain→delete 防 pending 复活）

链路（lane）分组（2026-09-10 真实调用流程对齐）：by_stage 每条带
lane/lane_label，by_lane 按流程序（写作中感知→续写→沉淀与完稿→系统
自己去读→其他）给组头小计与占比——面板读到的结构 = 写作时真实发生的
链路，而非 13+ 个平铺 stage 按量排序。stage→标签/链路唯一权威在本文件
（_STAGE_LABELS / _stage_lane），新增组件 stage 时同步补两组映射。

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

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.core.model_config import get_model_prices
from backend.models import Chapter, GenerationRun
from backend.services.llm.pricing import (
    PriceTable,
    accumulate_cost,
)
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
    "adaptive.canon_watch": "矛盾检测",
    # ---- 完稿后处理 ----
    "adaptive.post_process.critique": "完稿审阅",
    # ---- 候选事件回流（settle / finish 各触发一次）----
    "adaptive.event_scout.settle": "候选事件（沉淀）",
    "adaptive.event_scout.finish": "候选事件（完稿）",
    # ---- 系统自己去读（切章自动读事件 / 通读向导认人）----
    "adaptive.event_scout.auto_read": "自动阅读·记事",
    "adaptive.read_entities": "自动阅读·认人",
    # ---- stitch-ghost 五模式 + 压缩重试 ----
    "adaptive.stitch_ghost.stitch": "续写·缝合",
    "adaptive.stitch_ghost.continue": "续写·顺句",
    "adaptive.stitch_ghost.burst": "续写·连写",
    "adaptive.stitch_ghost.open": "续写·开篇",
    "adaptive.stitch_ghost.outline": "续写·细纲扩写",
    "adaptive.stitch_ghost.compress": "续写·压缩重试",
    "adaptive.stitch_ghost.repair": "续写·硬伤返修",
    # ---- 谋篇 ----
    "adaptive.spine_suggest": "谋篇建议",
    "adaptive.spine_suggest.retry": "谋篇建议（重试）",
    # ---- 沉淀涌现抽取（历史名：BS-ADF Loop3，adaptive 沿用未改名；
    #      手动沉淀专用——自动认人走 adaptive.read_entities）----
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
# stage → 链路（lane）分组：用量视图按真实调用流程分組呈现——
# 作者在面板上读到的结构 = 写作时真实发生的四条链路，而不是 13+ 个
# 平铺 stage 按量排序。lane 顺序即流程顺序（面板分组渲染序）。
# ============================================================

_LANE_PERCEIVE = "perceive"    # 写作中感知（心跳停顿触发，后台）
_LANE_GHOST = "ghost"          # 续写（Space/Tab/Ctrl+Space/细纲胶囊）
_LANE_SETTLE = "settle"        # 沉淀与完稿（作者显式动作触发）
_LANE_AUTO_READ = "auto_read"  # 系统自己去读（切章/通读向导，全自动）
_LANE_OTHER = "other"          # 未登记 stage 的兜底组

_LANE_ORDER: Tuple[str, ...] = (
    _LANE_PERCEIVE, _LANE_GHOST, _LANE_SETTLE, _LANE_AUTO_READ, _LANE_OTHER,
)
_LANE_LABELS: Dict[str, str] = {
    _LANE_PERCEIVE: "写作中感知",
    _LANE_GHOST: "续写",
    _LANE_SETTLE: "沉淀与完稿",
    _LANE_AUTO_READ: "系统自己去读",
    _LANE_OTHER: "其他",
}

_STAGE_LANE_EXACT: Dict[str, str] = {
    "adaptive.intent_inference": _LANE_PERCEIVE,
    "adaptive.future_projection": _LANE_PERCEIVE,
    "adaptive.dock_generator": _LANE_PERCEIVE,
    "adaptive.canon_watch": _LANE_PERCEIVE,
    "adaptive.event_scout.settle": _LANE_SETTLE,
    "adaptive.event_scout.finish": _LANE_SETTLE,
    "adaptive.post_process.critique": _LANE_SETTLE,
    "loop3.emergent_facts": _LANE_SETTLE,
    "adaptive.spine_suggest": _LANE_SETTLE,
    "adaptive.event_scout.auto_read": _LANE_AUTO_READ,
    "adaptive.read_entities": _LANE_AUTO_READ,
}

_STAGE_LANE_PREFIXES: Tuple[Tuple[str, str], ...] = (
    # 五模式 + compress/repair（含未来新模式后缀）
    ("adaptive.stitch_ghost.", _LANE_GHOST),
    # 残句修复（sentence_fix.0..4）
    ("sentence_fix.", _LANE_SETTLE),
    # 谋篇建议 + .retry
    ("adaptive.spine_suggest.", _LANE_SETTLE),
)


def _stage_lane(stage: str) -> str:
    """stage 标识 → 链路键；未登记的落 other（新增组件不炸视图）。"""
    lane = _STAGE_LANE_EXACT.get(stage)
    if lane:
        return lane
    for prefix, lane_key in _STAGE_LANE_PREFIXES:
        if stage.startswith(prefix):
            return lane_key
    return _LANE_OTHER


# ============================================================
# 聚合（纯函数，单测直接打这里）
# ============================================================

def _new_bucket() -> Dict[str, Any]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "cost": 0.0,
        "unpriced_tokens": 0,
    }


def _accumulate(bucket: Dict[str, Any], run: GenerationRun, prices: PriceTable) -> None:
    """单行 generation_runs 累入桶（None token 按 0 计；成本按价目表累加）。"""
    bucket["calls"] += 1
    bucket["prompt_tokens"] += run.prompt_tokens or 0
    bucket["completion_tokens"] += run.completion_tokens or 0
    bucket["thinking_tokens"] += run.thinking_tokens or 0
    accumulate_cost(bucket, prices, run)


def _finalize(bucket: Dict[str, Any]) -> Dict[str, Any]:
    """桶收尾：补 total_tokens（口径 = prompt+completion+thinking）+ 成本取整。"""
    out = dict(bucket)
    out["total_tokens"] = (
        out["prompt_tokens"] + out["completion_tokens"] + out["thinking_tokens"]
    )
    out["cost"] = round(out.get("cost") or 0.0, 6)
    return out


def _zero_totals() -> Dict[str, Any]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "thinking_tokens": 0,
        "total_tokens": 0,
        "cost": 0.0,
        "unpriced_tokens": 0,
    }


def aggregate_by_stage(
    runs: List[GenerationRun], prices: Optional[PriceTable] = None
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """按 stage 聚合行集 → (totals, by_stage 降序)。

    by_stage 条目带 lane/lane_label（链路分组键，见 _stage_lane）——
    用量面板按真实调用流程分组渲染的依据。prices 传入时逐行计价
    （cost 元 / unpriced_tokens 未计价 token 量；None=空表=全部未计价）。
    """
    prices = prices or {}
    stage_buckets: Dict[str, Dict[str, Any]] = {}
    totals = _zero_totals()
    for run in runs:
        stage = run.stage or "unknown"
        bucket = stage_buckets.setdefault(stage, _new_bucket())
        _accumulate(bucket, run, prices)
    totals["calls"] = sum(b["calls"] for b in stage_buckets.values())
    totals["prompt_tokens"] = sum(b["prompt_tokens"] for b in stage_buckets.values())
    totals["completion_tokens"] = sum(b["completion_tokens"] for b in stage_buckets.values())
    totals["thinking_tokens"] = sum(b["thinking_tokens"] for b in stage_buckets.values())

    by_stage: List[Dict[str, Any]] = []
    for stage, bucket in stage_buckets.items():
        lane = _stage_lane(stage)
        entry = {
            "stage": stage,
            "label": _stage_label(stage),
            "lane": lane,
            "lane_label": _LANE_LABELS[lane],
        }
        entry.update(_finalize(bucket))
        by_stage.append(entry)
    # 用量视图：大头在前；同量按 stage 名稳定排序
    by_stage.sort(key=lambda e: (-e["total_tokens"], e["stage"]))

    # 总账收尾（与 by_stage 同一口径：p+c+t；成本由各桶累加）
    totals["total_tokens"] = (
        totals["prompt_tokens"] + totals["completion_tokens"] + totals["thinking_tokens"]
    )
    totals["cost"] = round(sum(e["cost"] for e in by_stage), 6)
    totals["unpriced_tokens"] = sum(e["unpriced_tokens"] for e in by_stage)
    return totals, by_stage


def aggregate_by_lane(
    by_stage: List[Dict[str, Any]], totals: Dict[str, int]
) -> List[Dict[str, Any]]:
    """by_stage → 按链路汇总（流程顺序：感知→续写→沉淀完稿→自动阅读→其他）。

    每条含 calls/total_tokens 小计与 share（占本书 total 的百分比，
    total 为 0 时 share=0）。空 by_stage 返回空列表（零值结构约定不变）。
    """
    grand = totals.get("total_tokens") or 0
    lane_buckets: Dict[str, Dict[str, Any]] = {}
    for entry in by_stage:
        lane = entry["lane"]
        bucket = lane_buckets.setdefault(
            lane, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "thinking_tokens": 0}
        )
        bucket["calls"] += entry["calls"]
        bucket["prompt_tokens"] += entry["prompt_tokens"]
        bucket["completion_tokens"] += entry["completion_tokens"]
        bucket["thinking_tokens"] += entry["thinking_tokens"]

    by_lane: List[Dict[str, Any]] = []
    for lane in _LANE_ORDER:
        bucket = lane_buckets.get(lane)
        if bucket is None:
            continue
        subtotal = (
            bucket["prompt_tokens"] + bucket["completion_tokens"] + bucket["thinking_tokens"]
        )
        lane_cost = 0.0
        lane_unpriced = 0
        for entry in by_stage:
            if entry["lane"] == lane:
                lane_cost += entry["cost"]
                lane_unpriced += entry["unpriced_tokens"]
        by_lane.append({
            "lane": lane,
            "label": _LANE_LABELS[lane],
            "calls": bucket["calls"],
            "total_tokens": subtotal,
            "share": round(subtotal * 100 / grand, 1) if grand > 0 else 0,
            "cost": round(lane_cost, 6),
            "unpriced_tokens": lane_unpriced,
        })
    return by_lane


def aggregate_by_date(
    runs: List[GenerationRun], prices: Optional[PriceTable] = None
) -> List[Dict[str, Any]]:
    """按 UTC 日期分桶 → date 升序列表（created_at 为 None 的行跳过日期桶，
    但 totals/by_stage 不受影响——由 aggregate_by_stage 另行计入）。"""
    prices = prices or {}
    date_buckets: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        if run.created_at is None:
            continue
        day = run.created_at.date().isoformat()
        bucket = date_buckets.setdefault(day, _new_bucket())
        _accumulate(bucket, run, prices)
    return [
        {"date": day, **_finalize(bucket)}
        for day, bucket in sorted(date_buckets.items())
    ]


def aggregate_by_model(
    runs: List[GenerationRun], prices: Optional[PriceTable] = None
) -> List[Dict[str, Any]]:
    """按 model_name 聚合 → total_tokens 降序（价目表编辑入口的数据面：
    面板据此显示「哪些模型在用、配没配价」）。"""
    prices = prices or {}
    buckets: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        model = run.model_name or "(未知模型)"
        bucket = buckets.setdefault(model, _new_bucket())
        _accumulate(bucket, run, prices)
    by_model: List[Dict[str, Any]] = []
    for model, bucket in buckets.items():
        entry = {"model": model}
        entry.update(_finalize(bucket))
        entry["priced"] = model in prices
        by_model.append(entry)
    by_model.sort(key=lambda e: (-e["total_tokens"], e["model"]))
    return by_model


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
                       "thinking_tokens", "total_tokens",
                       "cost", "unpriced_tokens"},
            "by_stage": [{"stage", "label", "lane", "lane_label", "calls",
                          "prompt_tokens", "completion_tokens",
                          "thinking_tokens", "total_tokens",
                          "cost", "unpriced_tokens"}],
            "by_lane": [{"lane", "label", "calls", "total_tokens", "share",
                         "cost", "unpriced_tokens"}],
            "by_model": [{"model", "calls", "total_tokens", "cost",
                          "unpriced_tokens", "priced"}]
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

    prices = get_model_prices()
    totals, by_stage = aggregate_by_stage(list(runs), prices)
    return {
        "chapter_id": chapter_id,
        "totals": totals,
        "by_stage": by_stage,
        "by_lane": aggregate_by_lane(by_stage, totals),
        "by_model": aggregate_by_model(list(runs), prices),
    }


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
            "by_lane": [...同章端点...],
            "by_model": [...同章端点...],
            "by_date": [{"date": "YYYY-MM-DD", "calls", "prompt_tokens",
                         "completion_tokens", "thinking_tokens", "total_tokens",
                         "cost", "unpriced_tokens"}]
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

    prices = get_model_prices()
    totals, by_stage = aggregate_by_stage(list(runs), prices)
    by_date = aggregate_by_date(list(runs), prices)
    return {
        "book_id": book_id,
        "totals": totals,
        "by_stage": by_stage,
        "by_lane": aggregate_by_lane(by_stage, totals),
        "by_model": aggregate_by_model(list(runs), prices),
        "by_date": by_date,
    }


@router.delete("/chapters/{chapter_id}/adaptive/usage")
async def reset_chapter_adaptive_usage(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """清空本章 adaptive 用量台账（测试用，2026-09-11）。

    动机：面板/预算闸调试需要干净的起点。只删 generation_runs 里本章的
    adaptive 行——正文、世界数据、其他引擎（adf/refinery）的 run 一概不碰。

    防复活三步（内存 recorder 是 chapter 常驻的，直接删表会被下次
    flush 把 pending 记录塞回来）：
    1. 先 flush_adaptive_records——在飞行中的账落库（与常规 flush 同锁）；
    2. 再 drain 本章 recorder——丢弃落库后新攒的 pending；
    3. 最后 DELETE 表行并 commit。
    残余竞态：drain 与 commit 之间若有心跳刚好记了一笔，该笔会在下次
    flush 复活（个位数行）——测试场景可接受，不再加锁。

    Returns:
        {"chapter_id", "deleted": 删除行数, "totals": 清零后的零值结构}
    """
    from backend.services.adaptive.observing import (
        flush_adaptive_records,
        get_adaptive_recorder,
    )

    await flush_adaptive_records(chapter_id)
    get_adaptive_recorder(chapter_id).drain()
    result = await db.execute(
        delete(GenerationRun)
        .where(GenerationRun.chapter_id == chapter_id)
        .where(GenerationRun.run_id == f"adaptive_{chapter_id}")
    )
    await db.commit()
    deleted = int(result.rowcount or 0)
    logger.info(f"[adaptive/usage] 清空本章用量台账（测试）：chapter={chapter_id} 删除 {deleted} 行")
    return {
        "chapter_id": chapter_id,
        "deleted": deleted,
        "totals": _zero_totals(),
        "by_stage": [],
        "by_lane": [],
        "by_model": [],
    }


@router.delete("/books/{book_id}/adaptive/collab-events")
async def clear_book_collab_events(book_id: str):
    """清空本书协作埋点（测试用，2026-09-11；05 瘦身后保留——机制数据的重置口）。

    05 埋点瘦身（2026-09-18）拆掉了 insights 协作面板与 events/summary 端点，
    本端点保留：data/collab_events.jsonl（当前份 + 轮转 .1，跨书共存）现在是
    四个机制零件的数据源（静音/文风先验/意图纠正/幽灵收编），重置它们的历史
    仍需此口。滤除本书事件、他书保留，两份文件都重写（临时文件 + 原子替换）。
    损坏行不是本书事件，原样保留。挂在 usage 路由而非 adaptive.py——那边
    router 前缀是 /api/chapters，书级路径放不进去。

    连带效应（如实声明）：
    - 「学着闭嘴」的 hint_dismiss 拒收史派生源被清——该书静音集合回到
      无拒收史状态（宽恕锚点 books.assist_mutes 不动）；两级派生缓存
      经 invalidate_quiet_caches 即时失效。
    - 重写与并发追加的竞态：清空瞬间恰好落笔的一两条埋点可能随旧文件
      一起被丢弃（测试场景可接受，与用量清空端点同款残余竞态口径）。

    Returns: {"book_id", "deleted": 删除条数}
    """
    import json as _json

    # 路径推导与写侧轮转逻辑在 adaptive.py（埋点写读的家）——本端点只是
    # 借它的文件坐标，不复制路径规则
    from backend.routes.chapter_generation.adaptive.events import (
        _collab_events_path,
        _collab_events_rotated_path,
    )

    deleted = 0
    for path in (_collab_events_path(), _collab_events_rotated_path()):
        if not path.exists():
            continue
        kept_lines: list = []
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        ev = _json.loads(line)
                    except Exception:
                        kept_lines.append(line)  # 损坏行不判归属，原样保留
                        continue
                    if str(ev.get("book_id") or "") == str(book_id):
                        deleted += 1
                    else:
                        kept_lines.append(line)
        except Exception as e:
            logger.warning(f"[collab-events] 清空读取失败（跳过 {path.name}）: {e}")
            continue
        try:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("".join(kept_lines), encoding="utf-8")
            tmp.replace(path)  # 原子替换（os.replace 在 Windows 下覆盖目标）
        except Exception as e:
            logger.warning(f"[collab-events] 清空重写失败（{path.name} 保持原样）: {e}")

    try:
        from backend.services.adaptive.quiet_learning import invalidate_quiet_caches

        invalidate_quiet_caches(book_id)
    except Exception as e:
        logger.debug(f"[collab-events] 静音缓存失效失败（30s TTL 自然过期）: {e}")

    logger.info(f"[collab-events] 清空本书协作埋点（测试）：book={book_id} 删除 {deleted} 条")
    return {"book_id": book_id, "deleted": deleted}

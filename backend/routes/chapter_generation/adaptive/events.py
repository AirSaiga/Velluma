# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：event / constraints/summary —— 协作埋点写侧与约束台账读面。

本地 JSONL 零上报；路径推导/轮转写在这里，usage.py 的清空端点
借同一份文件坐标（勿复制路径规则）。

05 埋点瘦身（2026-09-18，docs/next-phase/05-telemetry-slimming.md）：
分析层（GET /events/summary 聚合端点 + insights 协作面板）已拆；事件总线
保留——上面还接着四个运行时机制零件。现役事件词表（机制消费，勿删发射侧）：
  hint_dismiss {kind,label}     感知带提醒收起 → quiet_learning 30 天窗静音
  ghost_adopt {text,...}        幽灵落地 → sample_prior 文风采纳率先验 +
                                feedback 幽灵收编池（detail.text 供收编，必带）
  ghost_discard {...}           幽灵蒸发 → sample_prior 先验
  intent_correct {from,to}      打算「不对」纠正手势 → intent_inference 纠正史教材
  ghost_discard_reason {reason} 蒸发理由 chips——失败分类学传感器采集（暂无
                                后端消费方，nle-adf 档案在册的未来机制）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.utils.logging import get_runtime_logger

from .schemas import CollabEventRequest

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])


# ============================================================
# 端点 6：event — 协作交互埋点写侧（P0-3 → 05 瘦身后仅机制消费）
# ============================================================
# 用途定位：机制零件的数据水管（词表见模块 docstring）；分析层已拆。
# ============================================================

# 埋点文件路径锚定项目根（与 backend/database.py 的 _sqlite_db_path 同款推导）：
# 相对路径 "data/…" 会随服务启动 CWD 漂移（不同目录启动各写一份）。惰性函数而非
# 模块常量——尊重 VELLUMA_DATA_DIR 运行时覆盖（打包/便携场景启动后才注入）。
# 注：本文件位于 backend/routes/chapter_generation/，上三级即项目根。
_COLLAB_EVENTS_MAX_BYTES = 5 * 1024 * 1024  # 单文件 5MB 上限：超出轮转一份（个人镜子只需近期数据）


def _collab_events_path() -> Path:
    """协作埋点 JSONL 路径（<data>/collab_events.jsonl，锚定项目根不随 CWD 漂移）。"""
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return data_dir / "collab_events.jsonl"


def _collab_events_rotated_path() -> Path:
    """轮转文件路径（collab_events.jsonl.1，写侧超限时当前文件 rename 过来）。"""
    base = _collab_events_path()
    return base.with_name(base.name + ".1")



def _append_collab_event(book_id: str, chapter_id: str, kind: str, detail: Dict) -> None:
    """追加事件到本地 JSONL（失败静默——埋点绝不阻塞业务）。

    无界增长防护：追加前检查当前文件超 5MB 则先轮转（当前 → .1，覆盖旧 .1——
    单文件曾承载所有书所有章，不轮转会无限膨胀）。读侧（quiet_learning /
    sample_prior / intent_inference / usage 清空端点）对称读两份。轮转自身
    失败随外层静默契约吞掉（继续追加原文件）。
    """
    import json as _json
    from datetime import datetime, timezone as _tz

    try:
        path = _collab_events_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists() and path.stat().st_size > _COLLAB_EVENTS_MAX_BYTES:
                rotated = _collab_events_rotated_path()
                rotated.unlink(missing_ok=True)  # Windows 下 rename 目标存在会报错，先清位
                path.rename(rotated)
        except Exception as e:
            logger.debug(f"[CollabEvent] 轮转失败（继续追加原文件）: {e}")
        with path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps({
                "ts": datetime.now(_tz.utc).isoformat(),
                "book_id": book_id,
                "chapter_id": chapter_id,
                "kind": kind,
                "detail": detail or {},
            }, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        logger.debug(f"[CollabEvent] 写入失败（静默）: {e}")


def _log_constraint_event(
    book_id: str,
    chapter_id: str,
    constraint_id: str,
    outcome: str,
    reason: str = "",
    detail: Optional[Dict] = None,
) -> None:
    """约束事件台账薄包装（2026-09-02 约束治理一期）。

    与 collab 埋点同级静默契约：失败绝不阻塞生成。schema 与轮转在
    services/constraints/events.py（照抄本文件 collab_events 模式）。
    """
    try:
        from backend.services.constraints.events import log_constraint_event

        log_constraint_event(book_id, chapter_id, constraint_id, outcome,
                             reason=reason, detail=detail)
    except Exception as e:
        logger.debug(f"[ConstraintEvent] 埋点失败（静默）: {e}")


@router.post("/{chapter_id}/adaptive/event", status_code=204)
async def log_collab_event(
    chapter_id: str,
    payload: CollabEventRequest,
    db: AsyncSession = Depends(get_db),
):
    """记录协作交互事件（book_id 服务端从章节解析，前端不传防伪）。"""
    book_id = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
    except Exception:
        pass
    _append_collab_event(book_id, chapter_id, payload.kind, payload.detail)


@router.get("/{chapter_id}/adaptive/constraints/summary")
async def constraints_summary(
    chapter_id: str,
):
    """约束执法事件汇总（约束治理一期 2026-09-02：信用分/服从率度量的读面）。

    形状：{chapter_id, total, by_constraint, by_outcome, recent(最新 20 条)}。
    前端「约束健康」面板等数据体量后再接线。failure 静默返回空结构。
    """
    try:
        from backend.services.constraints.events import read_constraint_events

        data = read_constraint_events(chapter_id=chapter_id)
    except Exception:
        data = {"total": 0, "by_constraint": {}, "by_outcome": {}, "recent": []}
    return {
        "chapter_id": chapter_id,
        "total": data.get("total", 0),
        "by_constraint": data.get("by_constraint", {}),
        "by_outcome": data.get("by_outcome", {}),
        "recent": data.get("recent", []),
    }

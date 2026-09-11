# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：event / constraints/summary / events/summary —— 协作埋点与约束台账读面。

本地 JSONL 零上报（个人镜子）；路径推导/轮转写在这里，usage.py 的清空端点
借同一份文件坐标（勿复制路径规则）。
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
# 端点 6：event — 协作交互埋点（P0-3，本地 JSONL 零上报）
# ============================================================
# 用途定位（roadmap §0.1/§1）：个人镜子——自我可见性（协作质量与 token 成本），
# 非增长分析。事件词表（前端 dispatchCollabEvent / logCollabEvent）：
#   cards_delivered {count}      走向卡亮出（前端按卡集签名去重，防心跳重复计）
#   card_burst {event}           走向卡连写（Ctrl+Space 选卡）
#   ghost_request {mode}         Space 续写/缝合触发
#   ghost_adopt / ghost_discard  Enter 落地 / Esc 蒸发
#   capsule_create / capsule_expand {note_id}  细纲胶囊创建 / 落笔扩写
#   slice_mode {mode}            切片条读者视角档切换
#   context_card                 情境浮卡打开
#   quick_note {action}          世界速记 commit / undo
#   batch_accept {count, undone} 批量采纳候选（A5b；undone=1 表示整批已撤销）
#   ignition / settle {commit} / finish / sentence_fix {action: propose|adopt|reject}
#   spine_intent_set / spine_anchor_add|drop|remove / spine_suggest /
#   spine_suggest_adopt {part} / spine_suggest_discard（P1.4 章级谋篇）
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
    单文件曾承载所有书所有章，不轮转会无限膨胀且 summary 全文件逐行扫越扫越慢）。
    读侧 summary 对称读两份。轮转自身失败随外层静默契约吞掉（继续追加原文件）。
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


@router.get("/{chapter_id}/adaptive/events/summary")
async def collab_events_summary(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """协作交互汇总（个人镜子：走向卡/幽灵稿/胶囊的采纳率——P0 出口标准）。"""
    import json as _json
    from collections import Counter as _Counter

    book_id = ""
    try:
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
    except Exception:
        pass

    counts: Dict = _Counter()
    # quick_note 的 action 拆分计数（独立于 counts）：前端同 kind 发 commit/undo
    # 两种 action，quick_note_commit 出口只应计入落账动作。不并入 counts——
    # total/by_kind 保持纯 kind 口径（insights「协作」面板消费 by_kind['quick_note']
    # 总数，并入会双计 total 且污染 by_kind）。
    quick_note_actions: Dict = _Counter()
    # quick_note 连带建档求和（关联式录入 2026-09-05）：commit 埋点 detail 携带
    # created_entities/created_locations——「关联录入到底用没用」的度量面
    quick_note_created = [0, 0]
    # batch_accept 的 count 求和（独立于 counts）：A5b 批量裁决采纳条数总量
    batch_accept_count = 0
    encounter_cards = 0
    encounter_bursts = 0
    try:
        # 读侧与写侧轮转对称：当前文件 + 单份 .1 轮转（两次 open 复用同一段逐行统计）
        for path in (_collab_events_path(), _collab_events_rotated_path()):
            if not path.exists():
                continue
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = _json.loads(line)
                        if ev.get("chapter_id") == chapter_id:
                            kind = ev.get("kind", "?")
                            counts[kind] += 1
                            detail = ev.get("detail") or {}
                            if kind == "quick_note":
                                quick_note_actions[detail.get("action") or "commit"] += 1
                                if not detail.get("undone"):
                                    quick_note_created[0] += int(detail.get("created_entities") or 0)
                                    quick_note_created[1] += int(detail.get("created_locations") or 0)
                            if kind == "batch_accept" and not detail.get("undone"):
                                batch_accept_count += int(detail.get("count") or 0)
                            # W5 桥验证指标：地图来源卡的亮出/连写（roadmap §3.2）
                            if kind == "cards_delivered":
                                encounter_cards += int(detail.get("encounter_count") or 0)
                            elif kind == "card_burst" and detail.get("from_encounter"):
                                encounter_bursts += 1
                    except Exception:
                        continue
    except Exception:
        pass

    def _rate(num: str, den: str):
        n, d = counts.get(num, 0), counts.get(den, 0)
        return round(n / d, 3) if d > 0 else None

    return {
        "chapter_id": chapter_id,
        "book_id": book_id,
        "total": sum(counts.values()),
        "by_kind": dict(counts),
        "card_burst_rate": _rate("card_burst", "cards_delivered"),
        "ghost_adopt_rate": _rate("ghost_adopt", "ghost_request"),
        "capsule_expand_count": counts.get("capsule_expand", 0),
        # 只含 action=='commit'（世界速记落账）；undo 不计（防误计拉高采纳面貌）
        "quick_note_commit": quick_note_actions.get("commit", 0),
        # 关联式录入度量：速记连带新建的实体/地点个数（entities, locations）
        "quick_note_created_entities": quick_note_created[0],
        "quick_note_created_locations": quick_note_created[1],
        # A5b 批量裁决：累计采纳条数（by_kind['batch_accept'] 是操作次数，这是条数）
        "batch_accept_count": batch_accept_count,
        "encounter_card_burst_rate": round(encounter_bursts / encounter_cards, 3) if encounter_cards > 0 else None,
    }

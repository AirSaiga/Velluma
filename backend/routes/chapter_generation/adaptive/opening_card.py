# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：opening-card —— 开章卡（空章开写前的四面镜子，01 下一阶段设计稿 M1）。

零 LLM、零剧情建议、零修改建议——只折作者自己录的数据
（docs/next-phase/01-opening-card-and-reader-ledger.md §2）。
读者清单（功能二）不走本模块：挂在 /adaptive/finish 响应 reader_ledger 键。

专用极简计数（05 埋点瘦身后口径：不接协作事件总线、不做面板，独立 jsonl
`data/opening_card_metrics.jsonl`；杀伐阈值在 01 稿 §5——长期零交互整块撤）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.services.utils.logging import get_runtime_logger

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["adaptive"])

_METRICS_MAX_BYTES = 1024 * 1024  # 两个计数器撑不到 1MB；超限轮转一份防无限膨胀


def _metrics_path() -> Path:
    """开章卡专用计数台账路径（<data>/opening_card_metrics.jsonl，锚定项目根）。

    路径推导与 collab_events 同款（events.py 的坑：相对路径随启动 CWD 漂移）。
    """
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(os.getenv("VELLUMA_DATA_DIR") or (root / "data"))
    return data_dir / "opening_card_metrics.jsonl"


@router.get("/{chapter_id}/adaptive/opening-card")
async def get_opening_card(chapter_id: str, db: AsyncSession = Depends(get_db)):
    """开章卡数据（空章「打算」页消费；每行独立空集消失，全空返回 {}）。"""
    try:
        chapter = await db.get(Chapter, chapter_id)
    except Exception:
        return {}  # 非 UUID 入参等坏路径——镜子静默缺席，不 500
    if chapter is None:
        return {}
    from backend.services.world.reader_ledger import build_opening_card

    return await build_opening_card(db, str(chapter.book_id), chapter)


class OpeningCardTouch(BaseModel):
    """shown=进章卡渲染过一次；expand=任一行被展开过（各计一次，零细节）。"""

    action: Literal["shown", "expand"]


@router.post("/{chapter_id}/adaptive/opening-card/touch", status_code=204)
async def touch_opening_card(
    chapter_id: str,
    payload: OpeningCardTouch,
    db: AsyncSession = Depends(get_db),
):
    """专用计数（01 §5 度量：显示/展开两个数，本地 jsonl 零上报、失败静默）。"""
    try:
        book_id = ""
        chapter = await db.get(Chapter, chapter_id)
        if chapter is not None:
            book_id = str(chapter.book_id)
        path = _metrics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if path.exists() and path.stat().st_size > _METRICS_MAX_BYTES:
                rotated = path.with_name(path.name + ".1")
                rotated.unlink(missing_ok=True)
                path.rename(rotated)
        except Exception as e:
            logger.debug(f"[OpeningCard] 计数轮转失败（继续追加）: {e}")
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now(timezone.utc).isoformat(),
                "book_id": book_id,
                "chapter_id": chapter_id,
                "action": payload.action,
            }, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.debug(f"[OpeningCard] 计数写入失败（静默）: {e}")

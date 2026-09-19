# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
deai 子项目路由（docs/deai-integration.md）。

写作台「记改前/记改后」手动配对的收集端点——行为数据飞轮手动起点。
账本落 data/deai_pairs.jsonl（本地零上报），入库走 deai/scripts/
ingest_behavior_pairs.py 六闸校验，本路由不做闸门执法（宁可少入库的
把关在入库侧统一做）。
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.deai.pairs import (
    PairValidationError,
    count_pairs,
    delete_pair,
    save_pair,
)

router = APIRouter(prefix="/api/deai", tags=["deai"])
logger = logging.getLogger(__name__)


class DeaiPairCreate(BaseModel):
    """一条训练对：bad = 卡片舱生成原样文本，good = 作者改定版本。"""
    bad: str
    good: str
    book_id: Optional[str] = None
    chapter_id: Optional[str] = None
    # 03 下一阶段 §5：manual_mark（手动两步）/ auto_ghost（书签自动捕获）/
    # capsule（细纲扩写采纳）——同池不同源，入库侧分组统计质量
    source: Optional[str] = None


@router.post("/pairs")
async def create_deai_pair(payload: DeaiPairCreate):
    """存一对训练样本。返回 {id, total}——id 供 6 秒撤销胶囊删除用。"""
    try:
        result = save_pair(
            bad=payload.bad,
            good=payload.good,
            book_id=payload.book_id,
            chapter_id=payload.chapter_id,
            source=payload.source or "manual_mark",
        )
    except PairValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.delete("/pairs/{pair_id}")
async def remove_deai_pair(pair_id: str):
    """撤销一对（写作台 6 秒撤销胶囊）。"""
    deleted = delete_pair(pair_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="对子不存在或已删除")
    return {"deleted": True, "total": count_pairs()}

# Velluma - 辅助层「学着闭嘴」静音查询与宽恕复位端点
# AGPL-3.0
"""
2026-08-25 战略定稿「学着闭嘴」的作者可见面：

- GET  /api/books/{book_id}/assist-mutes          当前生效的静音清单（派生值 + 作者语言标签）
- POST /api/books/{book_id}/assist-mutes/forgive  {key} → 宽恕复位：该键此前的拒绝记录
                                                   一笔勾销，重新计数（作者主权的恢复阀）

静音集合不落库、永远从行为数据派生（services/adaptive/quiet_learning.py 唯一权威）；
本模块只做读面与宽恕写入（books.assist_mutes 宽恕时间戳）。
"""
from __future__ import annotations

from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.services.adaptive.quiet_learning import (
    describe_mute_keys,
    forgive_mute,
    load_muted_keys,
)

router = APIRouter(prefix="/api/books", tags=["assist-quiet"])


class AssistMuteItem(BaseModel):
    key: str
    label: str
    channel: str


class AssistMutesResponse(BaseModel):
    mutes: List[AssistMuteItem]


class ForgiveMuteRequest(BaseModel):
    key: str


@router.get("/{book_id}/assist-mutes", response_model=AssistMutesResponse)
async def get_assist_mutes(book_id: str, db: AsyncSession = Depends(get_db)):
    """当前生效的静音清单（绕过 60s 缓存直取派生值——设置式读取要的是准确）。"""
    keys = await load_muted_keys(db, book_id, use_cache=False)
    return AssistMutesResponse(mutes=[AssistMuteItem(**d) for d in describe_mute_keys(keys)])


@router.post("/{book_id}/assist-mutes/forgive", response_model=AssistMutesResponse)
async def forgive_assist_mute(
    book_id: str,
    payload: ForgiveMuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """宽恕复位某条静音（该键此前的拒绝记录一笔勾销）。返回复位后的清单。"""
    key = (payload.key or "").strip()
    if not key:
        raise HTTPException(status_code=422, detail="key 不能为空")
    keys = await forgive_mute(db, book_id, key)
    return AssistMutesResponse(mutes=[AssistMuteItem(**d) for d in describe_mute_keys(keys)])

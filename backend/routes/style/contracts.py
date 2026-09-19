# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""端点：/books/{id}/texture-contracts —— 写作规矩（质感契约按书覆盖）。

收编批（2026-09）：白描封杀令迁入 services/style/texture_contracts.py 后，
系统契约支持按书定制——本组端点供文风页「写作规矩」区读写。语义：

- GET：系统契约全集 × 本书覆盖合并后的生效视图（含系统默认全文，
  「恢复默认」按钮据此回填）；
- PUT：整体覆盖写 books.texture_contracts 列（JSON {key: {body, updated_at}}）。
  缺键 / body 空串 = 恢复系统默认；传 {} = 全部恢复默认。未知键静默丢弃
  （契约键集以 CONTRACTS 为准，客户端版本漂移不脏库）。

零变化契约：列缺失/NULL/{} 时 prompt 逐字节走系统默认——本端点不写
prompt 任何字面量，只写覆盖层。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories import BookRepository
from backend.schemas import (
    TextureContractItem,
    TextureContractsResponse,
    TextureContractsUpdate,
    TextureRuleItem,
)
from backend.services.style.texture_contracts import (
    CONTRACTS,
    _disabled_rule_set,
    normalize_texture_overrides,
    resolve_contract_body,
)

from ._deps import get_book_repo

router = APIRouter(prefix="/api", tags=["style"])


def _read_overrides(book: Any) -> Optional[Dict[str, Any]]:
    """读本书覆盖层；列缺失/形态非法 → None（=全部系统默认）。"""
    raw = getattr(book, "texture_contracts", None)
    return raw if isinstance(raw, dict) and raw else None


def _customized_via(key: str, overrides: Optional[Dict[str, Any]]) -> str:
    """本书定制方式：\"\"=默认 / "body"=整文覆盖 / "rules"=规矩开关。"""
    if not overrides:
        return ""
    ov = overrides.get(key)
    if not isinstance(ov, dict):
        return ""
    body = ov.get("body")
    if isinstance(body, str) and bool(body.strip()):
        return "body"
    if _disabled_rule_set(key, overrides):
        return "rules"
    return ""


def _build_view(book: Any) -> TextureContractsResponse:
    """系统契约全集 × 本书覆盖 → 生效视图（GET/PUT 共用同一份合并逻辑）。"""
    overrides = _read_overrides(book)
    items = []
    for key, contract in CONTRACTS.items():
        body = resolve_contract_body(key, overrides)
        via = _customized_via(key, overrides)
        disabled = _disabled_rule_set(key, overrides)
        items.append(TextureContractItem(
            key=key,
            title=contract.title,
            modes=list(contract.modes),
            body=body,
            is_default=not via,
            default_body=contract.body,
            customized_via=via,
            rules=[
                TextureRuleItem(key=r.key, title=r.title, enabled=r.key not in disabled)
                for r in contract.rules
            ],
        ))
    return TextureContractsResponse(contracts=items)


@router.get("/books/{book_id}/texture-contracts", response_model=TextureContractsResponse)
async def get_texture_contracts(
    book_id: UUID,
    book_repo: BookRepository = Depends(get_book_repo),
):
    """本书写作规矩生效视图（系统默认 + 本书覆盖合并）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return _build_view(book)


@router.put("/books/{book_id}/texture-contracts", response_model=TextureContractsResponse)
async def put_texture_contracts(
    book_id: UUID,
    payload: TextureContractsUpdate,
    db: AsyncSession = Depends(get_db),
    book_repo: BookRepository = Depends(get_book_repo),
):
    """整体覆盖写本书写作规矩（缺键/空 body=恢复系统默认；{}=全部恢复）。"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    now = datetime.now(timezone.utc).isoformat()
    new_overrides: Dict[str, Any] = {
        key: {**ov, "updated_at": now}
        for key, ov in normalize_texture_overrides(
            {k: (v.model_dump() if v is not None else None) for k, v in (payload.overrides or {}).items()},
        ).items()
    }

    book.texture_contracts = new_overrides
    db.add(book)
    await db.commit()
    return _build_view(book)

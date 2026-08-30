# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
# [旧表冻结声明 2026-08-19] 本模块仍读 characters/assets 等旧表（roadmap P2.4 显式冻结）：
# 世界页（world_*）是唯一编辑源；此处旧表读取冻结不动，下次实质改造时换源 world。
# 新代码勿再新增旧表依赖。

"""
正文逆向提取路由（两阶段 SSE，仿 Refinery 模式）。

职责：
- analyze：LLM 提取结构化数据，不落库，存内存待确认队列
- confirm：凭 run_id 取回用户确认的子集，串行落库

SSE 事件序列（analyze）：
  EXTRACTION_STAGE("analyzing") → EXTRACTION_RESULT({run_id, ...提取结果}) → 流结束

SSE 事件序列（confirm）：
  EXTRACTION_STAGE("committing") → EXTRACTION_PROGRESS({step, created})×N → COMPLETE({created})
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.repositories.character_repository import CharacterRepository
from backend.repositories.chapter_repository import ChapterRepository
from backend.repositories.plot_ledger_repository import PlotLedgerRepository
from backend.schemas.extraction import ConfirmExtractionRequest
from backend.services.extraction import (
    ExtractionResult,
    extract_from_chapter,
    commit_extraction,
)
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW
from backend.services.utils.sse import build_sse_error, build_sse_event

import logging

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)

router = APIRouter(prefix="/api/chapters", tags=["content-extraction"])

# ============================================================
# 内存待确认队列（同 refinery 模式，单实例、非持久化）
# ============================================================
_PENDING_EXTRACTIONS: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = timedelta(hours=1)


def _cleanup_expired() -> None:
    """惰性清理过期的待确认记录。"""
    now = datetime.now(timezone.utc)
    expired = [rid for rid, data in _PENDING_EXTRACTIONS.items() if data.get("expires", now) < now]
    for rid in expired:
        _PENDING_EXTRACTIONS.pop(rid, None)


def _store_pending(run_id: str, result: Dict[str, Any], chapter_id: str, raw_text: str, book_id: str, chapter_number: int) -> None:
    """存入待确认队列。"""
    _cleanup_expired()
    _PENDING_EXTRACTIONS[run_id] = {
        "result": result,
        "chapter_id": chapter_id,
        "raw_text": raw_text,
        "book_id": book_id,
        "chapter_number": chapter_number,
        "expires": datetime.now(timezone.utc) + _PENDING_TTL,
    }


def _load_pending(run_id: str) -> Optional[Dict[str, Any]]:
    """读取待确认记录（不删除）。"""
    _cleanup_expired()
    return _PENDING_EXTRACTIONS.get(run_id)


def _pop_pending(run_id: str) -> Optional[Dict[str, Any]]:
    """取出并删除待确认记录。"""
    _cleanup_expired()
    return _PENDING_EXTRACTIONS.pop(run_id, None)


# ============================================================
# 端点 1：analyze（SSE 第一阶段）
# ============================================================
@router.post("/{chapter_id}/extraction/analyze")
async def analyze_chapter(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    正文逆向提取 - 第一阶段：LLM 分析。

    SSE 流：
    - EXTRACTION_STAGE("analyzing")
    - EXTRACTION_RESULT({run_id, characters, relationships, locations, assets, foreshadows, stats})
    - 流结束

    不落库，结果存内存待确认队列（TTL 1h）。
    """
    handler = _AnalyzeHandler(chapter_id=chapter_id, db=db)
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


class _AnalyzeHandler:
    def __init__(self, chapter_id: str, db: AsyncSession):
        self.chapter_id = chapter_id
        self.db = db

    async def stream(self):
        run_id = f"extract_{uuid.uuid4().hex[:12]}"

        try:
            # 加载章节
            chapter_repo = ChapterRepository(self.db)
            chapter = await chapter_repo.get_by_id(self.chapter_id)
            if not chapter:
                yield build_sse_error("章节不存在")
                return

            raw_text = chapter.content_text or chapter.draft_text or ""
            if not raw_text.strip():
                yield build_sse_error("章节正文为空，无法提取")
                return

            # 推送开始事件
            yield build_sse_event("EXTRACTION_STAGE", "正在分析正文", stage="analyzing")

            # 加载已有实体名（避免重复提取）
            char_repo = CharacterRepository(self.db)
            existing_chars = await char_repo.list_by_book(chapter.book_id)
            existing_char_names = [c.name for c in existing_chars]

            ledger_repo = PlotLedgerRepository(self.db)
            existing_ledgers = await ledger_repo.get_by_book(chapter.book_id, status="open")
            existing_ledger_keys = [lg.ledger_key for lg in existing_ledgers]

            # LLM 提取
            result = await extract_from_chapter(
                chapter_content=raw_text,
                chapter_number=chapter.chapter_number,
                existing_character_names=existing_char_names,
                existing_ledger_keys=existing_ledger_keys,
            )
            result_dict = result.to_dict()

            # 存入待确认队列
            _store_pending(
                run_id,
                result_dict,
                self.chapter_id,
                raw_text,
                str(chapter.book_id),
                chapter.chapter_number,
            )

            # 推送提取结果（带 run_id 供 confirm 阶段引用）
            payload = {
                "run_id": run_id,
                **result_dict,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            svc_logger.warning("Extraction analyze failed", error=str(e))
            yield build_sse_error(f"分析失败：{e}")


# ============================================================
# 端点 2：confirm（SSE 第二阶段）
# ============================================================
@router.post("/{chapter_id}/extraction/confirm")
async def confirm_extraction(
    chapter_id: str,
    request: ConfirmExtractionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    正文逆向提取 - 第二阶段：确认入库。

    SSE 流：
    - EXTRACTION_STAGE("committing")
    - EXTRACTION_PROGRESS({step, created})×N
    - COMPLETE({created})

    凭 run_id 取回提取结果 + 用户确认的子集，串行落库。
    """
    handler = _ConfirmHandler(chapter_id=chapter_id, request=request, db=db)
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


class _ConfirmHandler:
    def __init__(self, chapter_id: str, request: ConfirmExtractionRequest, db: AsyncSession):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        try:
            # 取回待确认数据
            pending = _load_pending(self.request.run_id)
            if not pending:
                yield build_sse_error("提取记录已过期或不存在，请重新分析")
                return

            # 校验 chapter_id 一致
            if pending["chapter_id"] != self.chapter_id:
                yield build_sse_error("章节不匹配")
                return

            # 推送开始事件
            yield build_sse_event("EXTRACTION_STAGE", "正在写入数据库", stage="committing")

            # 构造用户确认的 ExtractionResult 子集
            confirmed_data = self.request.confirmed
            confirmed = ExtractionResult(
                characters=confirmed_data.get("characters", []),
                relationships=confirmed_data.get("relationships", []),
                locations=confirmed_data.get("locations", []),
                assets=confirmed_data.get("assets", []),
                foreshadows=confirmed_data.get("foreshadows", []),
            )

            # 进度回调 → SSE 推送
            progress_queue: list = []

            def progress_callback(step: str, created: int):
                progress_queue.append((step, created))

            # 执行落库
            from uuid import UUID
            book_id = UUID(pending["book_id"])
            ch_id = UUID(pending["chapter_id"])
            chapter_number = pending["chapter_number"]
            raw_text = pending["raw_text"]

            created_counts = await commit_extraction(
                db=self.db,
                book_id=book_id,
                chapter_id=ch_id,
                chapter_number=chapter_number,
                confirmed=confirmed,
                raw_text=raw_text,
                progress_callback=progress_callback,
            )

            # 推送每步进度
            for step, count in progress_queue:
                yield build_sse_event(
                    "EXTRACTION_PROGRESS",
                    f"{step}: {count}",
                    step=step,
                    created=count,
                )

            # 弹出待确认
            _pop_pending(self.request.run_id)

            # 推送完成
            complete_payload = {
                "event": "COMPLETE",
                "created": created_counts,
            }
            yield f"data: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            svc_logger.warning("Extraction confirm failed", error=str(e))
            yield build_sse_error(f"入库失败：{e}")

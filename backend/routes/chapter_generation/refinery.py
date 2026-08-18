"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors (AGPL-3.0)
"""

"""
精修流水线路由（V4.1 新建）。

职责：暴露 Refinery 的两阶段 API（诊断 + 精修）。

API 端点（前缀 /api/chapters/{chapter_id}）：
- POST /refinery/diagnose    SSE：启动精修，先发 REFINERY_ISSUES 事件（含问题清单）
                              返回 run_id，作者确认后用 run_id 调 confirm
- POST /refinery/confirm     SSE：作者确认问题清单后，执行手术+回读+抛光

SSE v4.1 事件序列：
- REFINERY_STAGE             阶段切换（DIAGNOSTIC/DIALOGUE/SURGERY/REREAD/POLISH/COMPLETE）
- REFINERY_ISSUES            诊断产出的问题清单（前端渲染为可确认列表）
- REFINERY_OPERATION         单个手术开始
- REFINERY_SURGERY           单个手术完成（含 diff）
- REFINERY_REREAD            整体回读结论
- REFINERY_POLISH            抛光完成
- REFINERY_COMPLETE          精修完成（含 stats）
- REFINERY_DEGRADED          降级事件

设计依据：docs/generation-v4.1-refinery.md §5

两阶段实现：
- /refinery/diagnose 完成诊断后，把 raw_text + issues 存到内存（pending_refineries）
  并返回 run_id，SSE 流结束
- /refinery/confirm 接收 run_id + 作者决策，继续手术+回读+抛光，SSE 流式推送进度
"""

import json
import logging
import uuid
import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter
from backend.repositories import ChapterRepository, CanonRepository
from backend.schemas import ConfirmRefineryRequest, StartRefineryRequest
from backend.services.canon import build_canon_context_for_prompt
from backend.services.observability.run_recorder import RunRecorder
from backend.services.refinery import Refinery, RefineryContext, generate_reader_feedback
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import build_sse_event, build_sse_text_chunk, build_sse_error

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["refinery-v4.1"])


# ============================================================
# 内存存储：诊断后的 pending refinement
# ============================================================
# 结构：{run_id: {"raw_text": str, "issues": list, "ctx": RefineryContext, "expires": datetime}}
# 60 分钟过期
_PENDING_REFINERIES: Dict[str, Dict[str, Any]] = {}
_PENDING_TTL = timedelta(hours=1)


def _cleanup_expired() -> None:
    """清理过期的 pending refinement。"""
    now = datetime.now()
    expired = [k for k, v in _PENDING_REFINERIES.items() if v.get("expires", now) < now]
    for k in expired:
        _PENDING_REFINERIES.pop(k, None)


def _store_pending(run_id: str, raw_text: str, issues: List[Dict[str, Any]], ctx: RefineryContext) -> None:
    _cleanup_expired()
    _PENDING_REFINERIES[run_id] = {
        "raw_text": raw_text,
        "issues": issues,
        "ctx": ctx,
        "expires": datetime.now() + _PENDING_TTL,
    }


def _load_pending(run_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired()
    return _PENDING_REFINERIES.get(run_id)


def _pop_pending(run_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_expired()
    return _PENDING_REFINERIES.pop(run_id, None)


# ============================================================
# 工具：构建 RefineryContext
# ============================================================

async def _build_refinery_context(
    db: AsyncSession,
    chapter: Chapter,
    mode: str = "deep",
    enable_polish: bool = True,
) -> RefineryContext:
    """构建精修上下文（从 chapter + Canon + 文风卡/样本）。

    S2 E5：抛光 prompt 的 author_samples 不再恒空（polisher 签名早就支持，
    头注释承诺的"文风指纹"今日兑现）——按章大纲检索 2 条样本拼接成文本；
    负面清单禁词进 forbidden_terms（手术 prompt 同步生效）。
    无样本/无文风卡 → 空串，行为与原先一致。
    """
    # Canon 上下文
    try:
        canon_context = await build_canon_context_for_prompt(
            db, chapter.book_id, chapter_number=getattr(chapter, "chapter_number", None),
        )
    except Exception as e:
        logger.warning(f"[Refinery] Canon 加载失败: {e}")
        canon_context = ""

    # 章节主旨
    purpose = (getattr(chapter, "outline_text", "") or "")[:300]

    # 文风卡（书级）+ 作者样本（S2 E5）
    style_negative_terms = ""
    try:
        from backend.models import StyleCard as StyleCardModel
        sc_result = await db.execute(
            select(StyleCardModel).where(
                StyleCardModel.book_id == chapter.book_id,
                StyleCardModel.chapter_id.is_(None),
            ).limit(1)
        )
        style_card = sc_result.scalar_one_or_none()
        if style_card and style_card.negative_list:
            style_negative_terms = "、".join(
                (item.get("word") or item.get("phrase") or "")
                for item in style_card.negative_list
                if isinstance(item, dict) and (item.get("word") or item.get("phrase"))
            )
    except Exception as e:
        logger.warning(f"[Refinery] 文风卡加载失败（降级为空）: {e}")

    author_samples_text = ""
    try:
        from backend.services.style.retrieval import retrieve_author_samples
        samples = await retrieve_author_samples(
            db, str(chapter.book_id),
            (getattr(chapter, "outline_text", "") or "")[:200],
            k=2, max_chars=1200,
        )
        author_samples_text = "\n\n".join(samples)
    except Exception as e:
        logger.warning(f"[Refinery] 作者样本加载失败（降级为空）: {e}")

    ctx = RefineryContext(
        purpose=purpose,
        emotion_curve="",  # 第 2 期接入 Reader Mirror
        canon_constraints=canon_context,
        canon_summary=canon_context,
        character_states="",
        active_hooks="",
        forbidden_terms=style_negative_terms,
        author_intent="",
        author_samples=author_samples_text,
        enable_polish=enable_polish,
        mode=mode,
    )
    return ctx


# ============================================================
# 端点 1：诊断（SSE）
# ============================================================

@router.post("/{chapter_id}/refinery/diagnose")
async def refinery_diagnose(
    chapter_id: str,
    request: Optional[StartRefineryRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """启动精修 - 第一阶段：诊断。

    SSE 流：
    - REFINERY_STAGE(DIAGNOSTIC)
    - REFINERY_ISSUES（含问题清单 + run_id）
    - 流结束

    作者收到问题清单后，在前端确认，然后调 /refinery/confirm。
    """
    req = request or StartRefineryRequest(chapter_id=chapter_id)
    handler = _DiagnoseHandler(chapter_id=chapter_id, request=req, db=db)
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


class _DiagnoseHandler:
    def __init__(self, chapter_id: str, request: StartRefineryRequest, db: AsyncSession):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        run_id = f"refinery_{uuid.uuid4().hex[:12]}"

        try:
            # 加载章节
            chapter_repo = ChapterRepository(self.db)
            chapter = await chapter_repo.get_by_id(self.chapter_id)
            if not chapter:
                yield build_sse_error("章节不存在")
                return

            # 取文本
            raw_text = self.request.raw_text or chapter.draft_text or chapter.content_text or ""
            if not raw_text.strip():
                yield build_sse_error("章节正文为空")
                return

            # 构建上下文
            ctx = await _build_refinery_context(
                self.db, chapter,
                mode=self.request.mode,
                enable_polish=self.request.enable_polish,
            )
            # 注入 request 带来的 canon_context（如有）
            if self.request.canon_context:
                ctx.canon_constraints = self.request.canon_context
                ctx.canon_summary = self.request.canon_context

            # 初始化 recorder
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)
            yield build_sse_event("GENERATION_RUN", "精修已初始化", generation_run_id=run_id)

            # 阶段 1：诊断
            yield build_sse_event("REFINERY_STAGE", "进入阶段：DIAGNOSTIC", stage="DIAGNOSTIC")

            refinery = Refinery(recorder=recorder)
            issues = await refinery.diagnose(raw_text=raw_text, ctx=ctx)

            # 持久化 recorder
            try:
                await recorder.flush_to_db(self.db)
                await self.db.commit()
            except Exception as e:
                logger.warning(f"[Refinery] recorder 落库失败: {e}")

            # 存 pending（作者确认后用）
            _store_pending(run_id, raw_text, issues, ctx)

            # 推送问题清单
            yield build_sse_event(
                "REFINERY_ISSUES",
                f"诊断完成：{len(issues)} 个问题",
                run_id=run_id,
                issues=issues,
                stats={
                    "total": len(issues),
                    "high": sum(1 for i in issues if i.get("severity") == "high"),
                    "medium": sum(1 for i in issues if i.get("severity") == "medium"),
                    "low": sum(1 for i in issues if i.get("severity") == "low"),
                },
            )

            yield build_sse_event(
                "REFINERY_STAGE",
                "等待作者确认（DIALOGUE）",
                stage="DIALOGUE",
                run_id=run_id,
                message="请确认问题清单后调 /refinery/confirm",
            )

        except Exception as e:
            logger.exception(f"[Refinery] diagnose 异常: {e}")
            yield build_sse_error(f"诊断失败: {type(e).__name__}: {str(e)[:200]}")


# ============================================================
# 端点 2：确认 + 精修（SSE）
# ============================================================

@router.post("/{chapter_id}/refinery/confirm")
async def refinery_confirm(
    chapter_id: str,
    request: ConfirmRefineryRequest,
    db: AsyncSession = Depends(get_db),
):
    """作者确认问题清单后，执行手术+回读+抛光。

    需要 run_id（从 diagnose 阶段获得），从内存 pending 取出 raw_text + issues + ctx。
    """
    handler = _ConfirmHandler(chapter_id=chapter_id, request=request, db=db)
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


class _ConfirmHandler:
    def __init__(self, chapter_id: str, request: ConfirmRefineryRequest, db: AsyncSession):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        try:
            run_id = self.request.run_id
            if not run_id:
                yield build_sse_error("缺少 run_id")
                return

            pending = _load_pending(run_id)
            if not pending:
                yield build_sse_error(f"无效或已过期的 run_id: {run_id}")
                return

            raw_text = pending["raw_text"]
            issues = pending["issues"]
            ctx: RefineryContext = pending["ctx"]

            # 应用 mode（confirm 时可覆盖）
            if self.request.mode:
                ctx.mode = self.request.mode

            # 初始化 recorder（复用 run_id）
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)

            # 阶段 2：手术
            yield build_sse_event("REFINERY_STAGE", "进入阶段：SURGERY", stage="SURGERY")

            refinery = Refinery(recorder=recorder)

            # 把 decisions 转为 dict list
            decisions_data = []
            for d in self.request.decisions:
                decisions_data.append({
                    "issue_id": d.issue_id,
                    "decision": d.decision,
                })
            # custom_issues 加进 decisions（作为 custom_issue）
            for ci in self.request.custom_issues:
                decisions_data.append({
                    "issue_id": ci.id,
                    "decision": "confirmed",
                    "custom_issue": ci.model_dump(),
                })

            # V4.3 真·流式：asyncio.Queue 把 refine 的事件实时推到 SSE
            sse_queue: asyncio.Queue = asyncio.Queue()
            refine_done = asyncio.Event()
            refine_result_holder: Dict[str, Any] = {"result": None}

            async def _on_progress(event: str, data: dict) -> None:
                await sse_queue.put((event, data))

            async def _run_refine():
                try:
                    result = await refinery.refine(
                        raw_text=raw_text,
                        decisions=decisions_data,
                        ctx=ctx,
                        original_issues=issues,
                        progress_callback=_on_progress,
                    )
                    refine_result_holder["result"] = result
                except Exception as e:
                    await sse_queue.put(("__ERROR__", {"message": str(e)[:200]}))
                finally:
                    refine_done.set()

            # 启动 refine 后台任务
            refine_task = asyncio.create_task(_run_refine())

            # 实时推 refine 的事件
            while not (refine_done.is_set() and sse_queue.empty()):
                try:
                    event, data = await asyncio.wait_for(sse_queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if event == "__ERROR__":
                    yield build_sse_error(f"精修失败: {data.get('message', '')}")
                    refine_task.cancel()
                    return
                elif event == "OPERATION_START":
                    yield build_sse_event(
                        "REFINERY_OPERATION",
                        f"手术 {data.get('operation_index')}/{data.get('total_operations')}",
                        **data,
                    )
                elif event == "SURGERY_DONE":
                    yield build_sse_event(
                        "REFINERY_SURGERY",
                        f"手术完成：{data.get('diff_summary', '')}",
                        **data,
                    )

            # 等 refine 完全结束
            await refine_task
            result = refine_result_holder["result"]
            if result is None:
                yield build_sse_error("精修失败：无结果")
                return

            # 推回读
            yield build_sse_event(
                "REFINERY_REREAD",
                f"整体回读：{result.holistic_verdict.get('verdict', '?')}",
                **result.holistic_verdict,
            )

            # 推抛光（如果启用）
            if ctx.enable_polish:
                yield build_sse_event("REFINERY_POLISH", "抛光完成")

            # 推降级事件
            for deg in result.degraded:
                yield build_sse_event(
                    "REFINERY_DEGRADED",
                    f"阶段 {deg.get('phase', '?')} 降级",
                    **deg,
                )

            # 持久化到 chapter
            if result.polished_text:
                try:
                    chapter_repo = ChapterRepository(self.db)
                    chapter = await chapter_repo.get_by_id(self.chapter_id)
                    if chapter:
                        chapter.draft_text = result.polished_text
                        chapter.generation_run_id = run_id
                        await self.db.commit()
                except Exception as e:
                    logger.warning(f"[Refinery] 持久化失败: {e}")

            # recorder 落库
            try:
                await recorder.flush_to_db(self.db)
                await self.db.commit()
            except Exception as e:
                logger.warning(f"[Refinery] recorder 落库失败: {e}")

            # 弹出 pending
            _pop_pending(run_id)

            # 推送最终正文（分块）
            if result.polished_text:
                yield build_sse_event("FINAL_TEXT_STREAM", "正在输出最终文本")
                chunk_size = 200
                for i in range(0, len(result.polished_text), chunk_size):
                    yield build_sse_text_chunk(result.polished_text[i:i+chunk_size])

            # COMPLETE
            complete_payload = {
                "event": "COMPLETE",
                "polished_text": result.polished_text,
                "stats": result.stats,
                "generation_run_id": run_id,
                "issues_total": len(issues),
                "issues_confirmed": len(result.confirmed_issues),
                "operations_executed": result.stats.get("operations_executed", 0),
                "holistic_verdict": result.holistic_verdict.get("verdict"),
            }
            yield f"data: {json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception(f"[Refinery] confirm 异常: {e}")
            yield build_sse_error(f"精修失败: {type(e).__name__}: {str(e)[:200]}")


# ============================================================
# V4.3 对话式介入点 3：读者反馈
# ============================================================

class ReaderFeedbackRequest(BaseModel):
    """读者反馈请求。"""
    raw_text: Optional[str] = None  # None 时用 chapter.draft_text


@router.post("/{chapter_id}/reader-feedback")
async def get_reader_feedback(
    chapter_id: str,
    request: Optional[ReaderFeedbackRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """对话式介入点 3：成品后的读者反馈。

    1 次 reasoning LLM 扮演读者，写一段叙述性感受（不是检查清单）。
    """
    try:
        chapter_repo = ChapterRepository(db)
        chapter = await chapter_repo.get_by_id(chapter_id)
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")

        text = (request.raw_text if request and request.raw_text else chapter.draft_text or chapter.content_text or "")
        if not text.strip():
            raise HTTPException(status_code=400, detail="章节正文为空")

        chapter_number = getattr(chapter, "chapter_number", 1) or 1
        purpose = (getattr(chapter, "outline_text", "") or "")[:300]

        run_id = f"feedback_{uuid.uuid4().hex[:12]}"
        recorder = RunRecorder(chapter_id=chapter_id, run_id=run_id)

        result = await generate_reader_feedback(
            full_text=text,
            chapter_number=chapter_number,
            purpose=purpose,
            recorder=recorder,
        )

        # recorder 落库
        try:
            await recorder.flush_to_db(db)
            await db.commit()
        except Exception as e:
            logger.warning(f"[ReaderFeedback] recorder 落库失败: {e}")

        return {
            "chapter_id": chapter_id,
            "feedback": result.get("feedback", ""),
            "word_count": result.get("word_count", 0),
            "generation_run_id": run_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[ReaderFeedback] 异常: {e}")
        raise HTTPException(status_code=500, detail=f"读者反馈失败: {e}")

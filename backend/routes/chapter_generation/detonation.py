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

"""
引爆链闸门路由（V3.0 新建）。

职责（设计文档 §6）：
提供 3.0 引爆链的全部闸门端点，与现有 /generate-chapter（双轨）并存。

API 端点（前缀 /api/chapters/{chapter_id}）：
- GET  /detonation-state                恢复未完成链
- POST /card-v3                          章节卡 + 引爆候选（闸门 1）
- POST /detonation-chain                 首次创建链 + 选定 payload
- GET  /detonation-chain                 读取链
- PUT  /detonation-chain                 编辑/确认链（闸门 2）
- POST /detonation-chain/grow            树生长/局部重长
- POST /payload/write                    引爆点双候选写作
- GET  /payload/text                     读取引爆段成文
- PUT  /payload/text                     选定/编辑/冻结（闸门 3）
- POST /generate-v3                      SSE 全流程（引线写作+组装+审计）
- GET  /detonation-chain/report          落地报告

与现有路由的关系：
- /generate-chapter（双轨）保留不动
- /card-v3 复用现有 /plan 的章节卡生成逻辑，扩展 payload_candidates
- SSE 帧沿用 TEXT_CHUNK / COMPLETE / ERROR / HEARTBEAT，新增 DETONATION_STAGE / FUSE_PROGRESS / DETONATION_METRIC
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import Chapter, DetonationChain
from backend.repositories import (
    ChapterRepository, BookRepository, PlotLedgerRepository,
    ChapterCardRepository, StyleCardRepository,
    DetonationChainRepository,
)
from backend.schemas import (
    CardV3Request,
    CardV3Response,
    DetonationChainCreateRequest,
    DetonationChainGrowRequest,
    DetonationChainUpdateRequest,
    DetonationChainResponse,
    PayloadWriteRequest,
    PayloadWriteResponse,
    PayloadTextUpdateRequest,
    GenerateV3Request,
    DetonationReportResponse,
    PayloadCandidate,
    PayloadMoment,
    SetupNode,
)
from backend.services.context.loader import load_full_chapter_context
from backend.services.utils.logging import get_runtime_logger
from backend.services.utils.sse import (
    build_sse_event, build_sse_done, build_sse_text_chunk, build_sse_error,
)

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/chapters", tags=["chapter-generation-detonation-v3"])


# ============================================================
# 辅助：上下文加载
# ============================================================

async def _load_detonation_context(
    db: AsyncSession,
    chapter_id: str,
) -> Dict[str, Any]:
    """加载引爆链所需的完整上下文（章节/书/章节卡/文风卡/角色/伏笔/前章摘要）。

    返回 dict 含：chapter / book / chapter_card / style_card / entities /
                open_hooks / previous_summary / rolling_summary
    """
    chapter_repo = ChapterRepository(db)
    book_repo = BookRepository(db)
    cc_repo = ChapterCardRepository(db)
    style_card_repo = StyleCardRepository(db)
    plot_ledger_repo = PlotLedgerRepository(db)

    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    book = await book_repo.get_by_id(chapter.book_id) if chapter.book_id else None

    chapter_card = await cc_repo.get_by_chapter(chapter.id)

    # 书级 StyleCard
    from backend.models import StyleCard
    style_specs = await style_card_repo.find_all(
        conditions=[
            StyleCard.book_id == chapter.book_id,
            StyleCard.chapter_id.is_(None),
        ],
        limit=1,
    )
    style_card = style_specs[0] if style_specs else None

    # 加载完整上下文（角色/伏笔/前章摘要）—— repos 字典需补全所有 loader 依赖
    from backend.repositories import (
        ChapterAssetRepository, AssetRepository, MapLocationRepository,
        MemoryRepository, RelationshipRepository,
    )
    repos = {
        "chapter": chapter_repo,
        "book": book_repo,
        "plot_ledger": plot_ledger_repo,
        "chapter_asset": ChapterAssetRepository(db),
        "asset": AssetRepository(db),
        "map_location": MapLocationRepository(db),
        "memory": MemoryRepository(db),
        "relationship": RelationshipRepository(db),
    }
    try:
        context = await load_full_chapter_context(chapter.id, repos)
        entities = context.entities if context else []
        open_hooks = context.open_hooks if context else []
        previous_summary = context.previous_summary if context else None
    except Exception as e:
        logger.warning(f"[Detonation] load_full_chapter_context 失败，降级空上下文: {e}")
        entities = []
        open_hooks = []
        previous_summary = None

    rolling_summary = getattr(book, "rolling_summary", None) if book else None

    return {
        "chapter": chapter,
        "book": book,
        "chapter_card": chapter_card,
        "style_card": style_card,
        "entities": entities,
        "open_hooks": open_hooks,
        "previous_summary": previous_summary,
        "rolling_summary": rolling_summary,
    }


def _chain_to_response(chain: DetonationChain) -> Dict[str, Any]:
    """DetonationChain ORM → 响应 dict。

    V3.1：包含 tier/tier_reason/zones 字段（3.0 旧数据此字段为 None/{}）。
    """
    return {
        "id": str(chain.id),
        "book_id": str(chain.book_id),
        "chapter_id": str(chain.chapter_id) if chain.chapter_id else None,
        "version": chain.version,
        "payload": chain.payload or {},
        "nodes": chain.nodes or [],
        "reading_order": chain.reading_order or [],
        "status": chain.status,
        "confirmed_by": chain.confirmed_by,
        # V3.1 新字段（getattr 兜底旧 ORM 实例未刷新的情况）
        "tier": getattr(chain, "tier", None),
        "tier_reason": getattr(chain, "tier_reason", None),
        "zones": getattr(chain, "zones", None) or {},
        "meta": chain.meta or {},
        "created_at": chain.created_at.isoformat() if chain.created_at else None,
        "updated_at": chain.updated_at.isoformat() if chain.updated_at else None,
    }


# ============================================================
# GET /detonation-state —— 恢复未完成链
# ============================================================

@router.get("/{chapter_id}/detonation-state")
async def get_detonation_state(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取章节当前引爆链状态（用于前端恢复未完成的闸门流程）。"""
    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        return {"chain": None, "chapter_card_payload_moment": await _get_card_payload_moment(db, chapter_id)}
    return {"chain": _chain_to_response(chain)}


async def _get_card_payload_moment(db: AsyncSession, chapter_id: str) -> Optional[List[Dict[str, Any]]]:
    """读取章节卡的 payload_moment（候选列表，供闸门 1 恢复）。"""
    cc_repo = ChapterCardRepository(db)
    cc = await cc_repo.get_by_chapter(chapter_id)
    if cc and cc.payload_moment:
        return cc.payload_moment
    return None


# ============================================================
# POST /card-v3 —— 章节卡 + 引爆候选（闸门 1）
# ============================================================

@router.post("/{chapter_id}/card-v3", response_model=CardV3Response)
async def generate_card_v3(
    chapter_id: str,
    payload: Optional[CardV3Request] = None,
    db: AsyncSession = Depends(get_db),
):
    """生成章节卡 + 引爆点候选（闸门 1 输入）。

    业务流程：
    1. 复用现有 /plan 的章节卡生成逻辑（preview_plan_service）
    2. 额外调用 detonation_prompts.build_payload_candidate_prompt 生成 payload_candidates
    3. 把 payload_candidates 写入 ChapterCard.payload_moment（持久化供闸门恢复）
    """
    from backend.services.orchestration.agentic import preview_plan as preview_plan_service
    from backend.services.llm import call_llm_with_usage
    from backend.services.prompts.detonation_prompts import (
        build_payload_candidate_prompt,
        parse_payload_candidate_response,
    )

    ctx = await _load_detonation_context(db, chapter_id)
    chapter = ctx["chapter"]
    chapter_card = ctx["chapter_card"]

    # ---- 1. 章节卡生成（复用 preview_plan_service）----
    repositories = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "chapter_entity": None,
        "chapter_asset": None,
        "asset": None,
        "map_location": None,
        "memory": None,
        "relationship": None,
    }
    edited_card = payload.edited_card_fields if payload else None
    try:
        plan_result = await preview_plan_service(
            chapter_id=chapter_id,
            repositories=repositories,
            edited_card_fields=edited_card,
        )
    except Exception as e:
        logger.exception(f"[Detonation] preview_plan_service 失败: {e}")
        raise HTTPException(status_code=500, detail=f"章节卡生成失败: {type(e).__name__}")

    chapter_card_fields = plan_result.get("chapter_card", {}) or {}

    # ---- 2. 引爆点候选生成 ----
    payload_count = payload.payload_count if payload else 3
    system_prompt, user_prompt = build_payload_candidate_prompt(
        chapter=chapter,
        chapter_card=type("_CC", (), {k: v for k, v in chapter_card_fields.items()})() if chapter_card_fields else chapter_card,
        previous_summary=ctx["previous_summary"],
        rolling_summary=ctx["rolling_summary"],
        open_hooks=ctx["open_hooks"],
        entities=ctx["entities"],
        count=payload_count,
    )

    candidates: List[Dict[str, Any]] = []
    degraded: Optional[Dict[str, Any]] = None
    try:
        result = await call_llm_with_usage(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model_type="reasoning",
            temperature=0.5,
            max_tokens=4096,
        )
        candidates, degraded = parse_payload_candidate_response(result.content, expected_count=payload_count)
    except Exception as e:
        logger.warning(f"[Detonation] 引爆候选生成失败: {e}")
        degraded = {
            "reason": "payload_candidate_exception",
            "action": "empty_candidates",
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }

    # ---- 3. 持久化 payload_candidates 到 ChapterCard.payload_moment ----
    if candidates:
        try:
            cc_repo = ChapterCardRepository(db)
            existing = await cc_repo.get_by_chapter(chapter.id)
            if existing:
                # 直接 setattr + commit（mutable JSONB 需重新赋值）
                existing.payload_moment = candidates
                await db.commit()
                await db.refresh(existing)
            elif chapter_card_fields:
                # 章节卡尚未落库（用户尚未 /plan/confirm）；候选暂存到 plan_result，不强制建卡
                pass
        except Exception as e:
            logger.warning(f"[Detonation] 持久化 payload_moment 失败（不阻塞响应）: {e}")

    return CardV3Response(
        chapter_card=chapter_card_fields,
        payload_candidates=[PayloadCandidate(**c) for c in candidates],
        degraded=degraded,
        debug_prompt=None,
    )


# ============================================================
# POST /detonation-chain —— 首次创建链 + 选定 payload
# ============================================================

@router.post("/{chapter_id}/detonation-chain")
async def create_detonation_chain(
    chapter_id: str,
    payload: DetonationChainCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """首次创建引爆链（用户从候选中选定 payload）。

    业务流程：
    1. 校验章节存在
    2. 若已有活跃链，标记为 done（版本废弃）
    3. 新建 chain（status=draft，nodes/reading_order 为空，待 /grow 填充）
    """
    ctx = await _load_detonation_context(db, chapter_id)
    chapter = ctx["chapter"]

    repo = DetonationChainRepository(db)
    # 若已有活跃链，标记为 done
    existing = await repo.get_active_by_chapter(chapter.id)
    if existing:
        await repo.update_status(existing, status="done")

    payload_dict = payload.payload.model_dump()
    chain = await repo.create_for_chapter(
        book_id=chapter.book_id,
        chapter_id=chapter.id,
        payload=payload_dict,
        status="draft",
        confirmed_by=payload.confirmed_by,
    )
    return _chain_to_response(chain)


# ============================================================
# GET /detonation-chain —— 读取链
# ============================================================

@router.get("/{chapter_id}/detonation-chain")
async def get_detonation_chain(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """读取章节当前活跃链。"""
    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无活跃引爆链")
    return _chain_to_response(chain)


# ============================================================
# PUT /detonation-chain —— 编辑/确认链（闸门 2）
# ============================================================

@router.put("/{chapter_id}/detonation-chain")
async def update_detonation_chain(
    chapter_id: str,
    payload: DetonationChainUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """编辑/确认引爆链（闸门 2：作者审树后确认）。

    业务流程：
    - 更新 payload/nodes/reading_order（任一非空字段）
    - 更新 status（如 confirmed 表示树闸门通过）
    - 更新 confirmed_by
    """
    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无活跃引爆链")

    update_fields: Dict[str, Any] = {}
    if payload.payload is not None:
        update_fields["payload"] = payload.payload.model_dump()
    if payload.nodes is not None:
        update_fields["nodes"] = [n.model_dump() for n in payload.nodes]
    if payload.reading_order is not None:
        update_fields["reading_order"] = payload.reading_order
    if payload.status is not None:
        update_fields["status"] = payload.status
    if payload.confirmed_by is not None:
        update_fields["confirmed_by"] = payload.confirmed_by

    if not update_fields:
        return _chain_to_response(chain)

    updated = await repo.update(chain, update_fields)
    return _chain_to_response(updated)


# ============================================================
# POST /detonation-chain/grow —— 树生长/局部重长
# ============================================================

@router.post("/{chapter_id}/detonation-chain/grow")
async def grow_detonation_chain_endpoint(
    chapter_id: str,
    payload: Optional[DetonationChainGrowRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """铺垫树生长（逆向递归，1-2 次 reasoning + Layer 0 校验 + 带反馈重试）。

    业务流程：
    1. 加载活跃链的 payload
    2. 加载上下文（established_facts / open_hooks / entities / previous_summary）
    3. 调 chain_grower.grow_detonation_chain
    4. 把 nodes/reading_order 写回 chain
    5. 返回更新后的链
    """
    from backend.services.workflows.detonation import (
        grow_detonation_chain as grow_chain,
        extract_established_facts,
    )

    ctx = await _load_detonation_context(db, chapter_id)
    chapter = ctx["chapter"]

    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无活跃引爆链，请先创建")

    grow_params = payload or DetonationChainGrowRequest()

    # 构造 established_facts
    established_facts = extract_established_facts(
        entities=ctx["entities"],
        open_hooks=ctx["open_hooks"],
        previous_summary=ctx["previous_summary"],
        rolling_summary=ctx["rolling_summary"],
    )

    # 构造 chapter_card 代理（chain 可能尚未绑定 chapter_card，但 grow 需要 purpose 等字段）
    chapter_card_obj = ctx["chapter_card"]
    if chapter_card_obj is None:
        # fallback：用 chain.payload 构造最小化 chapter_card 代理
        chapter_card_obj = type("_CCProxy", (), {
            "purpose": chain.payload.get("description", ""),
            "must_hit_events": [],
        })()

    grow_result = await grow_chain(
        payload=chain.payload,
        chapter=chapter,
        chapter_card=chapter_card_obj,
        established_facts=established_facts,
        open_hooks=ctx["open_hooks"],
        entities=ctx["entities"],
        previous_summary=ctx["previous_summary"],
        max_depth=grow_params.max_depth,
        texture_budget_ratio=grow_params.texture_budget_ratio,
        existing_nodes=chain.nodes or [],
        partial_from_node_id=grow_params.partial_from_node_id,
    )

    # 写回 chain（即使有违规也写回，让用户在闸门里看到并编辑）
    update_fields: Dict[str, Any] = {
        "nodes": grow_result.nodes,
        "reading_order": grow_result.reading_order,
        "status": "growing",
    }
    # 把校验结论存到 meta
    meta_update = {"last_grow_validation": grow_result.validation}
    if grow_result.degraded:
        meta_update["last_grow_degraded"] = grow_result.degraded
    existing_meta = dict(chain.meta or {})
    existing_meta.update(meta_update)
    update_fields["meta"] = existing_meta

    updated = await repo.update(chain, update_fields)
    response = _chain_to_response(updated)
    response["grow_validation"] = grow_result.validation
    response["grow_degraded"] = grow_result.degraded
    return response


# ============================================================
# POST /payload/write —— 引爆点双候选写作
# ============================================================

@router.post("/{chapter_id}/payload/write", response_model=PayloadWriteResponse)
async def write_payload_endpoint(
    chapter_id: str,
    payload: Optional[PayloadWriteRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    """引爆点双候选写作（复用 fortress_candidate）。

    前置：detonation-chain.status ∈ {growing, confirmed}（payload 已选定）。
    """
    from backend.services.workflows.detonation import write_payload_dual_candidates

    ctx = await _load_detonation_context(db, chapter_id)
    chapter = ctx["chapter"]

    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无活跃引爆链")

    # 收集 distance ≤ 2 的直接引线节点
    nodes = chain.nodes or []
    direct_setup_nodes = [
        n for n in nodes
        if isinstance(n, dict) and int(n.get("distance_to_payload", 99) or 99) <= 2
    ]

    write_params = payload or PayloadWriteRequest()

    # 作者样本（从 AuthorSample 表加载，Slice A 简化为 None）
    author_samples: Optional[List[str]] = None

    result = await write_payload_dual_candidates(
        payload=chain.payload,
        direct_setup_nodes=direct_setup_nodes,
        chapter=chapter,
        chapter_card=ctx["chapter_card"],
        entities=ctx["entities"],
        style_card=ctx["style_card"],
        author_samples=author_samples,
        preceding_tail=write_params.preceding_tail,
        target_length=write_params.target_length,
    )

    return PayloadWriteResponse(
        candidates=result.candidates,
        scores=result.scores,
        winner_label=result.winner_label,
        degraded=result.degraded,
    )


# ============================================================
# GET / PUT /payload/text —— 读取 / 选定·冻结引爆段
# ============================================================

@router.get("/{chapter_id}/payload/text")
async def get_payload_text(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """读取引爆段成文。"""
    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无活跃引爆链")
    payload = chain.payload or {}
    return {
        "text": payload.get("text") or "",
        "approved": payload.get("approved", False),
    }


@router.put("/{chapter_id}/payload/text")
async def update_payload_text(
    chapter_id: str,
    payload: PayloadTextUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """选定/编辑/冻结引爆段（闸门 3：人审冻结）。"""
    repo = DetonationChainRepository(db)
    chain = await repo.get_active_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无活跃引爆链")

    updated = await repo.save_payload_text(chain, text=payload.text, approved=payload.approved)

    # 冻结后若 status 还是 growing，推进到 confirmed（树 + payload 都就绪）
    if payload.approved and updated.status in ("draft", "growing"):
        updated = await repo.update_status(updated, status="confirmed", confirmed_by="user")

    return _chain_to_response(updated)


# ============================================================
# POST /generate-v3 —— SSE 全流程（引线写作 + 组装 + 审计）
# ============================================================

@router.post("/{chapter_id}/generate-v3", deprecated=True)
async def generate_v3_stream(
    chapter_id: str,
    request: Optional[GenerateV3Request] = None,
    db: AsyncSession = Depends(get_db),
):
    """引爆链 SSE 生成主流程（引线写作 → 组装 → 图校验 → 文本流）。

    [V3.1 DEPRECATED] 本端点已标记废弃。请改用统一入口：
        POST /api/chapters/{id}/generate  （tier=auto 默认，自主定档；
        或 tier=climax 强制走高潮倒推全礼）

    本端点在 deprecation 期内保留，行为不变（需先完成三个人工闸门）。
    统一引擎（V3.1）把高潮倒推升格为贯穿全程的骨架，自主完成定档+九个 Phase。

    前置：detonation-chain.status=confirmed 且 payload.text 已冻结。
    """
    handler = _DetonationStreamHandler(
        chapter_id=chapter_id,
        request=request or GenerateV3Request(),
        db=db,
    )
    return StreamingResponse(handler.stream(), media_type="text/event-stream")


# ============================================================
# GET /detonation-chain/report —— 落地报告
# ============================================================

@router.get("/{chapter_id}/detonation-chain/report", response_model=DetonationReportResponse)
async def get_detonation_report(
    chapter_id: str,
    db: AsyncSession = Depends(get_db),
):
    """引爆链落地报告（含图校验 + 有锚审计结论）。

    注意：用 get_latest_by_chapter（含 done）而非 get_active_by_chapter，
    因为生成完成后链 status=done，但仍要能查报告。
    """
    from backend.services.workflows.detonation import audit_chain_graph

    repo = DetonationChainRepository(db)
    chain = await repo.get_latest_by_chapter(chapter_id)
    if not chain:
        raise HTTPException(status_code=404, detail="该章节尚无引爆链")

    graph_audit = audit_chain_graph(
        nodes=chain.nodes or [],
        reading_order=chain.reading_order or [],
        payload=chain.payload,
    )
    # 从 meta 读取有锚审计结论（Slice B 写入）
    meta = chain.meta or {}
    anchored_audit = meta.get("anchored_audit")

    return DetonationReportResponse(
        chapter_id=chapter_id,
        chain_id=str(chain.id),
        graph_audit=graph_audit,
        anchored_audit=anchored_audit,
        degraded=meta.get("last_grow_degraded"),
    )


# ============================================================
# SSE 流处理器（内部类）
# ============================================================

class _DetonationStreamHandler:
    """引爆链 SSE 流处理器。

    职责：
    - 校验前置条件（chain.status=confirmed, payload.text 已冻结）
    - 初始化 RunRecorder
    - 执行 DetonationWorkflow
    - 把阶段进度 + 文本块通过 SSE 推给前端
    - 持久化生成结果到 Chapter.draft_text
    """

    def __init__(
        self,
        chapter_id: str,
        request: GenerateV3Request,
        db: AsyncSession,
    ):
        self.chapter_id = chapter_id
        self.request = request
        self.db = db

    async def stream(self):
        """SSE 流生成器。"""
        from backend.services.workflows.detonation import DetonationWorkflow
        from backend.services.observability.run_recorder import RunRecorder
        from uuid import uuid4

        run_id = f"detonation_{uuid4().hex[:12]}"

        try:
            # ---- 前置校验 ----
            ctx = await _load_detonation_context(self.db, self.chapter_id)
            chapter = ctx["chapter"]

            repo = DetonationChainRepository(self.db)
            chain_orm = await repo.get_active_by_chapter(self.chapter_id)
            if not chain_orm:
                yield build_sse_error("该章节尚无活跃引爆链，请先完成闸门流程")
                return

            if chain_orm.status != "confirmed":
                yield build_sse_error(
                    f"引爆链状态为 {chain_orm.status}，需先确认树（status=confirmed）才能生成"
                )
                return

            payload = chain_orm.payload or {}
            if not (payload.get("text") or "").strip():
                yield build_sse_error("引爆段尚未冻结，请先通过 /payload/text 选定成文")
                return

            # 标记链进入 writing
            await repo.update_status(chain_orm, status="writing")

            # ---- 初始化 RunRecorder ----
            recorder = RunRecorder(chapter_id=self.chapter_id, run_id=run_id)

            # ---- 发送 GENERATION_RUN ----
            yield build_sse_event("GENERATION_RUN", "引爆链生成已初始化", generation_run_id=run_id)
            yield build_sse_event("DETONATION_STAGE", "进入阶段：FUSE_WRITING", stage="FUSE_WRITING")

            # ---- 构造 chain dict 供 workflow 使用 ----
            chain_dict = {
                "payload": payload,
                "nodes": chain_orm.nodes or [],
                "reading_order": chain_orm.reading_order or [],
                "status": chain_orm.status,
            }

            # 作者样本（Slice A 简化为 None）
            author_samples: Optional[List[str]] = None

            workflow = DetonationWorkflow(
                chain=chain_dict,
                chapter=chapter,
                chapter_card=ctx["chapter_card"],
                entities=ctx["entities"],
                style_card=ctx["style_card"],
                author_samples=author_samples,
                recorder=recorder,
            )

            # ---- progress_callback 转 SSE ----
            from backend.routes.chapter_generation.progress_tracker import StreamEventBuilder

            async def _on_progress(event: str, data: dict) -> None:
                if event == "FUSE_PROGRESS":
                    pass  # 通过下方 yield 推送（callback 不能直接 yield，用队列）
                elif event == "DETONATION_STAGE":
                    pass  # 同上

            # 简化策略：workflow 内部已经串行执行；这里直接 await 拿结果，再分块推送
            # Slice A 不做实时流式文本（引线段较短，整体生成后再推）；
            # Slice B 可改造为真·流式（每段 yield）

            result = await workflow.execute(progress_callback=None)

            # ---- 持久化 RunRecorder ----
            try:
                count = await recorder.flush_to_db(self.db)
                await self.db.commit()
                logger.info(f"[Detonation] RunRecorder 落库 {count} 条")
            except Exception as e:
                logger.warning(f"[Detonation] RunRecorder 落库失败（不阻塞）: {e}")

            # ---- 持久化正文到 Chapter.draft_text ----
            if result.final_text:
                try:
                    chapter.draft_text = result.final_text
                    chapter.generation_run_id = run_id
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[Detonation] 持久化 draft_text 失败: {e}")

            # ---- Slice B3: 伏笔自动落账（D5 伏笔即产物）----
            ledger_result = None
            try:
                from backend.services.workflows.detonation.ledgers import plant_ledgers_from_chain
                chapter_number = getattr(chapter, "chapter_number", None)
                ledger_result = await plant_ledgers_from_chain(
                    db=self.db,
                    chain_id=chain_orm.id,
                    book_id=chapter.book_id,
                    chapter_id=chapter.id,
                    nodes=chain_orm.nodes or [],
                    full_text=result.final_text,
                    chapter_number=chapter_number,
                )
                if ledger_result.get("planted"):
                    await self.db.commit()
                    logger.info(
                        f"[Detonation] 伏笔自动落账 {len(ledger_result['planted'])} 条"
                    )
            except Exception as e:
                logger.warning(f"[Detonation] 伏笔落账失败（不阻塞）: {e}")
                ledger_result = {"planted": [], "skipped": 0, "degraded": {"reason": "exception", "action": "skip"}}

            # ---- 把有锚审计结论写入 chain.meta ----
            if result.anchored_audit:
                try:
                    meta_update = {
                        "anchored_audit": result.anchored_audit,
                        "ledger_plant": ledger_result,
                    }
                    existing_meta = dict(chain_orm.meta or {})
                    existing_meta.update(meta_update)
                    chain_orm.meta = existing_meta
                    await self.db.commit()
                except Exception as e:
                    logger.warning(f"[Detonation] 写入 chain.meta 失败: {e}")

            # ---- 标记链 done ----
            try:
                chain_orm_latest = await repo.get_active_by_chapter(self.chapter_id)
                if chain_orm_latest:
                    await repo.update_status(chain_orm_latest, status="done")
            except Exception as e:
                logger.warning(f"[Detonation] 标记 chain done 失败: {e}")

            # ---- 推送降级事件（失败不静默）----
            for deg in result.degraded:
                yield build_sse_event(
                    "DEGRADED",
                    f"阶段 {deg.get('reason', '?')} 降级",
                    stage=deg.get("reason", ""),
                    reason=deg.get("reason", ""),
                    action=deg.get("action", ""),
                    detail=str(deg.get("detail", ""))[:200],
                )

            # ---- 推送审计指标（Slice A 图校验 + Slice B 有锚审计）----
            if result.graph_audit or result.anchored_audit:
                yield StreamEventBuilder.build_detonation_metric({
                    "graph_audit": result.graph_audit,
                    "anchored_audit": result.anchored_audit,
                    "stats": result.stats,
                    "ledger_plant": ledger_result,
                })

            # ---- 流式推送正文（按段切块，模拟 TEXT_CHUNK）----
            if result.final_text:
                # 按段落切块（每 ~200 字一块）
                text = result.final_text
                chunk_size = 200
                yield build_sse_event("FINAL_TEXT_STREAM", "正在输出最终文本")
                for i in range(0, len(text), chunk_size):
                    chunk = text[i:i + chunk_size]
                    yield build_sse_text_chunk(chunk)

            # ---- COMPLETE（前端 streamSse 监听 COMPLETE 事件）----
            import json as _json
            complete_payload = {
                "event": "COMPLETE",
                "text": result.final_text,
                "stats": result.stats,
                "generation_run_id": run_id,
                "chain_id": str(chain_orm.id),
                "graph_audit_verdict": result.graph_audit.get("verdict") if result.graph_audit else None,
            }
            yield f"data: {_json.dumps(complete_payload, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception(f"[Detonation] SSE 流异常: {e}")
            yield build_sse_error(f"生成失败: {type(e).__name__}: {str(e)[:200]}")

# Velluma - NLE-ADF Stepping Runtime
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""
NLE-ADF 步进状态机运行时。

职责：
- 持有单个步进生成运行的可恢复状态（SteppingRun）
- 管理 run 的内存存储 + TTL 清理（与 _PENDING_BEAT_SLOTS 同模式）
- 提供 action_queue / event_queue 两个并发原语
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SteppingRun:
    """单个步进生成运行的可恢复状态。"""

    run_id: str
    chapter_id: str  # UUID 字符串（与 Chapter.id 一致）
    cards: List[Any]
    workflow: Any

    current_beat_index: int = 0
    locked_segments: List[Any] = field(default_factory=list)
    state_card_chain: List[Any] = field(default_factory=list)
    decision_set: Dict[str, Any] = field(default_factory=dict)

    action_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)

    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    status: str = "stepping"
    final_result: Optional[Dict[str, Any]] = None
    # 当前段是否已 BEAT_RENDER_READY（等作者裁决）。
    # stepping_loop emit READY 时置 True；收到 action 时置 False。
    # advance-beat 据此判断是否可推进（防止段未 ready 就 pass 的时序错乱）。
    current_segment_ready: bool = False
    # 岔路门挂起标记：stepping_loop 在分支门等作者选走向时置 True，
    # 收到动作后置 False。advance-beat 据此放行分支裁决（此时渲染尚未
    # 开始，current_segment_ready 恒为 False，不能按常规 ready 等待拦截）。
    awaiting_branch_choice: bool = False
    # 岔路门挂起时的完整待选信息（供 state 端点返回给前端轮询自愈）。
    # 结构：{"beat_id", "segment_index", "node": {...}, "card_snapshot": {...}}
    pending_branch: Optional[Dict[str, Any]] = None
    # NLE-ADF 2.0 作者模式：True 时到每个新拍不自动渲染，发 BEAT_AUTHORING_OPEN
    # 挂起等作者（写碎片微缝合 / render 召唤代笔 / lock_with_text 直接定稿）。
    authoring_mode: bool = False
    # 作者模式挂起标记（与 awaiting_branch_choice 同构）：advance-beat 据此放行
    # 作者动作（此时渲染尚未开始，current_segment_ready 恒为 False）。
    awaiting_authoring: bool = False
    # 作者模式挂起时的拍卡快照（供 state 端点轮询自愈重建画布导演意图）。
    pending_authoring: Optional[Dict[str, Any]] = None
    # NLE-ADF 2.0 懒增强完成标记：轻卡通道下 Loop1/enrich/DDE 后台续跑完毕
    # 后置 True；state 端点暴露（前端慢查补齐增强卡与决策集）。
    cards_enhanced: bool = False
    # 懒增强产出的 Loop1 自检结果（供 state 端点；非懒通道走 debug_info）
    loop1_result: Optional[Dict[str, Any]] = None
    # P3 回退快照栈：每次 pass/lock_with_text 推进前压栈一份"该段渲染前"的
    # (current_beat_index, locked_segments, state_card_chain) 浅拷贝。
    # back action 弹栈恢复这三者，使循环重渲上一段时状态卡链正确。
    # 约束：back 只在 status=="stepping" 且栈非空时生效；末段 lock 进入
    # post_processing 后不可 back（循环已退出）。
    snapshot_stack: List[Dict[str, Any]] = field(default_factory=list)


class SteppingRunStore:
    """SteppingRun 的内存存储 + TTL 清理。"""

    def __init__(self, ttl_seconds: int = 3600):
        self._runs: Dict[str, SteppingRun] = {}
        self._ttl = ttl_seconds

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            rid for rid, run in self._runs.items()
            if now - run.last_activity > self._ttl
        ]
        for rid in expired:
            del self._runs[rid]

    def set(self, run: SteppingRun) -> None:
        self._cleanup_expired()
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> Optional[SteppingRun]:
        self._cleanup_expired()
        run = self._runs.get(run_id)
        if run is not None:
            run.last_activity = time.time()
        return run

    def pop(self, run_id: str) -> Optional[SteppingRun]:
        self._cleanup_expired()
        return self._runs.pop(run_id, None)

    def touch(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is not None:
            run.last_activity = time.time()


# TTL 12 小时：岔路门/段裁决挂起期间前端轮询按设计停止（等作者），
# last_activity 无人续期——1h 旧值会让作者离开一会儿再回来提交时
# 撞 404 RUN_NOT_FOUND（真实事故）。12h 覆盖隔夜写作间隙；
# 单机桌面应用内存开销可忽略，泄漏防护语义不变。
_STEPPING_RUNS = SteppingRunStore(ttl_seconds=43200)


def _find_branch_for_beat(decision_set: Optional[dict], beat_id: str) -> Optional[dict]:
    """从 DDE 决策集找挂在该 beat 上的岔路节点。无则 None。"""
    if not decision_set or not decision_set.get("has_story_branch"):
        return None
    for node in decision_set.get("decision_nodes", []):
        if node.get("beat_id") == beat_id:
            return node
    return None


def _default_directive(branch_node: Optional[dict]) -> str:
    """取默认走向的 directive 文本（label。plot_impact 格式）。"""
    if not branch_node:
        return ""
    options = branch_node.get("options", [])
    default_id = branch_node.get("default_option", "A")
    opt = next((o for o in options if o.get("option_id") == default_id), options[0] if options else None)
    if not opt:
        return ""
    label = opt.get("label", "")
    impact = opt.get("plot_impact", "")
    return f"{label}。{impact}" if impact else label


async def _emit_event(run: "SteppingRun", event: str, data: dict) -> None:
    await run.event_queue.put((event, data))


async def _resolve_branch_gate(run: "SteppingRun", card: Any, i: int) -> None:
    """岔路门公共逻辑：有未决 DDE 岔路 → 发 BEAT_BRANCH_CHOICE 挂起等走向 → 注入 directive。

    两个调用点（NLE-ADF 2.0 JIT 化）：
    - 非作者模式：拍开始前调用（老流程，渲染前必须定走向）；
    - 作者模式：延迟到代笔前门调用（作者自己写拍不需要走向答案，
      directive 只影响 AI 渲染；lock_with_text/skip/back 永不触发本门）。
    无岔路或 directive 已注入时直接返回（不重复触发）。
    """
    branch_node = _find_branch_for_beat(run.decision_set, card.beat_id)
    if not branch_node or getattr(card, "branch_directive", ""):
        return
    await _emit_event(run, "BEAT_BRANCH_CHOICE", {
        "beat_id": card.beat_id,
        "segment_index": i,
        "node": branch_node,
        "card_snapshot": _card_to_dict_safe(card),
    })
    run.current_segment_ready = False
    # 挂起等作者选走向前打标记：advance-beat 据此放行分支裁决，
    # generate-bsadf 桥接据此知道"无事件"是正常暂停而非渲染卡死。
    run.awaiting_branch_choice = True
    # 存储待选信息供 state 端点返回（前端轮询自愈用）。
    # SSE 断流时 BEAT_BRANCH_CHOICE 事件丢失，前端靠轮询 state
    # 发现 awaiting_branch_choice=true 重建 branchChoicePending。
    run.pending_branch = {
        "beat_id": card.beat_id,
        "segment_index": i,
        "node": branch_node,
        "card_snapshot": _card_to_dict_safe(card),
    }
    branch_action = await _next_action_for_beat(run, card.beat_id)
    run.awaiting_branch_choice = False
    run.pending_branch = None
    run.last_activity = time.time()
    branch_act = branch_action.get("action")
    if branch_act == "branch":
        choice = branch_action.get("branch_choice", {})
        directive = choice.get("plot_impact") or choice.get("label", "")
        if directive:
            card.branch_directive = directive
    elif branch_act in ("pass", "skip"):
        # 接受默认走向 / 跳过选择 → 用默认走向注入；
        # 但 Loop1 缺口提示节点（source=loop1_gap）的唯一"选项"是给作者的
        # 补充提示语而非走向——pass/skip 表示作者放弃补充，按原大纲渲染，
        # 不注入（否则提示语被当走向污染渲染 prompt）
        if branch_node.get("source") != "loop1_gap":
            card.branch_directive = _default_directive(branch_node)


async def _pop_back_snapshot(run: "SteppingRun", current_card: Any, current_i: int) -> Optional[int]:
    """back action 公共逻辑：弹 P3 快照栈恢复三字段 + 复位目标卡状态 + 发 BEAT_BACKED。

    返回目标段索引；栈空（第 0 段）时发 rejected 标记并返回 None（调用方
    continue 后循环自然回到当前段——渲染态重渲，作者模式重开 AUTHORING_OPEN）。
    渲染路径与作者模式路径共用，防两处回退语义漂移。
    """
    if run.snapshot_stack:
        snap = run.snapshot_stack.pop()
        run.locked_segments = snap["locked_segments"]
        run.state_card_chain = snap["state_card_chain"]
        target_i = snap["beat_index"]
        target_card = run.cards[target_i] if target_i < len(run.cards) else current_card
        target_card.status = "pending"
        target_card.render_attempts = 0
        await _emit_event(run, "BEAT_BACKED", {
            "beat_id": target_card.beat_id,
            "segment_index": target_i,
        })
        return target_i
    await _emit_event(run, "BEAT_BACKED", {
        "beat_id": current_card.beat_id,
        "segment_index": current_i,
        "rejected": True,
    })
    return None


async def _next_action_for_beat(run: "SteppingRun", beat_id: str) -> Dict[str, Any]:
    """从 action_queue 取下一条属于当前段的动作，陈旧动作丢弃。

    advance-beat 路由层只按提交瞬间的 current_beat_index 校验 beat_id，
    双击/失步重试可让两条动作并发入队——不校验的话，属于上一段的陈旧动作
    会在下一段被静默消费（作者未审阅的段被自动 pass/skip/back，真实事故）。
    beat_id 缺省（旧客户端）时放行，保持兼容。
    """
    while True:
        action = await run.action_queue.get()
        action_beat = action.get("beat_id")
        if not action_beat or action_beat == beat_id:
            return action
        logger.warning(
            f"[SteppingRun] 丢弃陈旧动作 run={run.run_id} "
            f"action={action.get('action')} beat={action_beat}（当前段 {beat_id}）"
        )


def _card_to_dict_safe(card: Any) -> dict:
    if hasattr(card, "beat_id"):
        try:
            from backend.services.workflows.bsadf.types import beat_slot_to_dict
            return beat_slot_to_dict(card)
        except Exception:
            pass
    return {"beat_id": getattr(card, "beat_id", ""), "segment_index": getattr(card, "segment_index", 0)}


def _degraded_to_dict_safe(degraded: Any) -> Optional[dict]:
    if degraded is None:
        return None
    return {
        "beat_id": getattr(degraded, "beat_id", ""),
        "segment_index": getattr(degraded, "segment_index", 0),
        "reason": getattr(degraded, "reason", ""),
        "attempts": getattr(degraded, "attempts", 0),
    }


def _apply_edited_slot(card: Any, edited_slot: dict) -> None:
    """把作者编辑后的卡字段应用到运行时卡上（edit action）。

    白名单与 BeatSlotSchema 的可编辑内容字段对齐（此前只放 5 个字段，
    作者对 branch_directive/句式/情绪/景别/目标字数的修改被静默丢弃）。
    身份字段（beat_id/segment_index）与运行时状态字段（status/edited/
    edit_count/render_attempts）不放行。
    """
    for field_name in (
        "core_plot_event", "key_anchors", "text_carrier", "outline_beat",
        "branch_directive", "negative_bounds", "sentence_rhythm",
        "emotion_register", "emotion_energy", "landed_preconditions",
        "shot_type", "transition", "target_word_count", "beat_type",
    ):
        if field_name in edited_slot:
            setattr(card, field_name, edited_slot[field_name])


async def stepping_loop(
    run: "SteppingRun",
    enable_memory_ingestion: bool = True,
) -> None:
    """stepping_loop 的异常安全包装。

    本协程由 asyncio.ensure_future 启动、无人观察返回值——任何未捕获异常都会
    静默死亡：event_queue 从此无事件，advance-beat 的 SSE 流空等 120s 才超时，
    前端表现为"点了推进没反应"。兜底：置 error 态 + 发 ERROR 事件让前端立即感知。
    """
    try:
        await _stepping_loop_impl(run, enable_memory_ingestion)
    except Exception as e:
        run.status = "error"
        logger.exception(f"[SteppingRun] 步进循环未捕获异常 run={run.run_id}: {e}")
        try:
            await _emit_event(run, "ERROR", {"error": f"步进循环异常: {e}"})
        except Exception:
            pass


async def _stepping_loop_impl(
    run: "SteppingRun",
    enable_memory_ingestion: bool = True,
) -> None:
    """Phase 4 步进主循环。

    逐段：渲染 → BEAT_RENDER_READY → 挂起等 action →
    pass/edit/branch/skip → 下一段。末段锁死后跑 Phase 4.5-7.5，发 COMPLETE。
    """
    run.status = "stepping"
    i = 0
    while i < len(run.cards):
        run.current_beat_index = i
        card = run.cards[i]

        # ===== 岔路门（非作者模式）：渲染前检查是否有 DDE 走向选择 =====
        # 有岔路且尚未选定走向 → 暂停等作者选；作者选或接受默认后注入 branch_directive，保证渲染时走向真正生效
        # 作者模式下岔路门 JIT 化：拍前不问（作者自己写拍不需要走向答案），
        # 延迟到代笔前门——见下方作者模式门内的 _resolve_branch_gate 调用。
        if not run.authoring_mode:
            await _resolve_branch_gate(run, card, i)

        # ===== 作者模式门（NLE-ADF 2.0）：到拍不自动渲染，挂起等作者 =====
        # 作者在画布写碎片 + /stitch 微缝合填拍（纯前端，与本循环无交互）；
        # 只有显式动作才推进：render=召唤 AI 整段代笔（落到下方正常渲染路径）、
        # lock_with_text=整拍直接定稿、skip=跳过本拍、back=回退上一拍、
        # edit=改卡后代笔。渲染路径的全部闸门（降级/字数/岔路）原样保留。
        if run.authoring_mode:
            await _emit_event(run, "BEAT_AUTHORING_OPEN", {
                "beat_id": card.beat_id,
                "segment_index": i,
                "target_word_count": getattr(card, "target_word_count", 500),
                "card_snapshot": _card_to_dict_safe(card),
            })
            run.current_segment_ready = False
            # 挂起标记（与 awaiting_branch_choice 同构）：advance-beat 据此跳过
            # ready 等待直接放行作者动作；state 端点据此供前端轮询自愈。
            run.awaiting_authoring = True
            run.pending_authoring = {
                "beat_id": card.beat_id,
                "segment_index": i,
                "target_word_count": getattr(card, "target_word_count", 500),
                "card_snapshot": _card_to_dict_safe(card),
            }
            author_action = await _next_action_for_beat(run, card.beat_id)
            run.awaiting_authoring = False
            run.pending_authoring = None
            run.last_activity = time.time()
            a_act = author_action.get("action")
            if a_act == "lock_with_text":
                author_text = (author_action.get("author_text") or "").strip()
                if author_text:
                    # 整拍作者定稿：跳渲染（与下方 lock_with_text 路径同构）。
                    # ⚠ 压栈必须在 lock_segment_with_author_text 之前（它会 mutate
                    # state_card_chain），否则 back 无法撤销状态卡漂移。
                    run.snapshot_stack.append({
                        "beat_index": i,
                        "locked_segments": run.locked_segments.copy(),
                        "state_card_chain": run.state_card_chain.copy(),
                    })
                    author_segment, _ = await run.workflow.lock_segment_with_author_text(
                        card=card, author_text=author_text, segment_index=i,
                        locked_segments=run.locked_segments,
                        state_card_chain=run.state_card_chain, run=run,
                    )
                    facts = None
                    if enable_memory_ingestion:
                        facts = await run.workflow.ingest_memory(
                            segment=author_segment, card=card, segment_index=i,
                        )
                    run.locked_segments.append(author_segment)
                    await _emit_event(run, "BEAT_LOCKED", {
                        "beat_id": card.beat_id,
                        "segment_index": i,
                        "extracted_facts": facts,
                        "author_locked": True,
                    })
                    i += 1
                    continue
                # 空定稿（作者删光）→ skip 语义（作者模式下无已渲染段可退化 pass）
                run.snapshot_stack.append({
                    "beat_index": i,
                    "locked_segments": run.locked_segments.copy(),
                    "state_card_chain": run.state_card_chain.copy(),
                })
                await _emit_event(run, "BEAT_SKIPPED", {
                    "beat_id": card.beat_id,
                    "segment_index": i,
                })
                i += 1
                continue
            if a_act == "skip":
                run.snapshot_stack.append({
                    "beat_index": i,
                    "locked_segments": run.locked_segments.copy(),
                    "state_card_chain": run.state_card_chain.copy(),
                })
                await _emit_event(run, "BEAT_SKIPPED", {
                    "beat_id": card.beat_id,
                    "segment_index": i,
                })
                i += 1
                continue
            if a_act == "back":
                target_i = await _pop_back_snapshot(run, card, i)
                i = target_i if target_i is not None else i
                continue
            if a_act == "edit" and author_action.get("edited_slot") is not None:
                _apply_edited_slot(card, author_action["edited_slot"])
                card.edited = True
                card.edit_count = getattr(card, "edit_count", 0) + 1
                card.status = "pending"
                card.render_attempts = 0
                # 改卡后落到下方渲染路径（代笔）
            elif a_act == "branch":
                choice = author_action.get("branch_choice", {})
                directive = choice.get("plot_impact") or choice.get("label", "")
                if directive:
                    card.branch_directive = directive
                # 选完走向落到下方渲染路径（代笔）
            # a_act ∈ render/pass/edit/branch：代笔类动作。
            # 岔路门 JIT：作者写拍不需要走向；AI 代笔才需要——渲染前此刻才问。
            # directive 已注入（如刚 branch 过）时门自动跳过。
            await _resolve_branch_gate(run, card, i)

        await _emit_event(run, "BEAT_RENDER_START", {
            "beat_id": card.beat_id,
            "segment_index": i,
            "target_word_count": getattr(card, "target_word_count", 500),
            "card_snapshot": _card_to_dict_safe(card),
        })
        # 懒通道按需增强：后台增强还没轮到这张卡时先单卡即时扩写（0-LLM 闸门禁）
        _ensure_enrich = getattr(run.workflow, "ensure_card_enriched", None)
        if _ensure_enrich is not None:
            await _ensure_enrich(card)
        segment, degraded = await run.workflow.render_one(
            card=card,
            segment_index=i,
            locked_segments=run.locked_segments,
            state_card_chain=run.state_card_chain,
            run=run,
        )        # 缓存当前段正文，供 state 端点轮询读取（IAB 等短 SSE 环境的备用通道）
        run._pending_segment_text = getattr(segment, "text", "") or ""
        await _emit_event(run, "BEAT_RENDER_READY", {
            "beat_id": card.beat_id,
            "segment_index": i,
            "word_count": len(getattr(segment, "text", "") or ""),
            "degraded": _degraded_to_dict_safe(degraded),
            "card_snapshot": _card_to_dict_safe(card),
        })
        run.current_segment_ready = True

        action = await _next_action_for_beat(run, card.beat_id)
        run.current_segment_ready = False
        run.last_activity = time.time()

        act = action.get("action")
        if act == "pass":
            # P3：推进前压栈"本段渲染前"的快照（current_beat_index/locked_segments/state_card_chain），
            # 供 back action 弹栈恢复。浅拷贝 list 即可（段对象/状态卡对象本身不动）。
            run.snapshot_stack.append({
                "beat_index": i,
                "locked_segments": run.locked_segments.copy(),
                "state_card_chain": run.state_card_chain.copy(),
            })
            facts = None
            if enable_memory_ingestion:
                facts = await run.workflow.ingest_memory(
                    segment=segment, card=card, segment_index=i,
                )
            run.locked_segments.append(segment)
            await _emit_event(run, "BEAT_LOCKED", {
                "beat_id": card.beat_id,
                "segment_index": i,
                "extracted_facts": facts,
            })
            i += 1
        elif act == "lock_with_text":
            # P2：作者直接定稿段正文（跳过 LLM）。author_text 来自 advance-beat payload。
            author_text = (action.get("author_text") or "").strip()
            if not author_text:
                # 无作者文本则退化为 pass（用已渲染的 segment）
                run.snapshot_stack.append({
                    "beat_index": i,
                    "locked_segments": run.locked_segments.copy(),
                    "state_card_chain": run.state_card_chain.copy(),
                })
                # 与正常 pass 一致跑记忆倒灌（此前退化路径漏跑，涌现实体丢失）
                facts = None
                if enable_memory_ingestion:
                    facts = await run.workflow.ingest_memory(
                        segment=segment, card=card, segment_index=i,
                    )
                run.locked_segments.append(segment)
                await _emit_event(run, "BEAT_LOCKED", {
                    "beat_id": card.beat_id, "segment_index": i, "extracted_facts": facts,
                })
                i += 1
            else:
                # 用作者文本构造段 + 抽状态卡（保证链连续），见 workflow.lock_segment_with_author_text
                # ⚠ 压栈必须在调用之前：lock_segment_with_author_text 内部会
                # state_card_chain.append(new_card) mutate run.state_card_chain，
                # 若压在其后，快照已含作者注入的新卡，back 回退无法撤销（状态卡漂移）。
                # 与 pass 路径（先压栈再 append）保持一致。
                run.snapshot_stack.append({
                    "beat_index": i,
                    "locked_segments": run.locked_segments.copy(),
                    "state_card_chain": run.state_card_chain.copy(),
                })
                author_segment, _ = await run.workflow.lock_segment_with_author_text(
                    card=card, author_text=author_text, segment_index=i,
                    locked_segments=run.locked_segments, state_card_chain=run.state_card_chain, run=run,
                )
                facts = None
                if enable_memory_ingestion:
                    facts = await run.workflow.ingest_memory(
                        segment=author_segment, card=card, segment_index=i,
                    )
                run.locked_segments.append(author_segment)
                await _emit_event(run, "BEAT_LOCKED", {
                    "beat_id": card.beat_id,
                    "segment_index": i,
                    "extracted_facts": facts,
                    "author_locked": True,
                })
                i += 1
        elif act == "back":
            # P3：回退到上一段（公共逻辑见 _pop_back_snapshot）。
            # 栈空 rejected 时 continue 让外层重渲当前段回到 READY，
            # 前端据此恢复裁决态并提示"已是第一段"。
            target_i = await _pop_back_snapshot(run, card, i)
            i = target_i if target_i is not None else i
            continue
        elif act == "skip":
            # skip 也压快照栈（此前不压：skip 后 back 弹的是更早 pass 的快照，
            # 连带丢弃其间已锁正文，且被 skip 的段会被循环重渲"复活"）。
            # 压栈后 back 到本段 = 作者明确"把跳过的段救回来重渲"，语义一致。
            run.snapshot_stack.append({
                "beat_index": i,
                "locked_segments": run.locked_segments.copy(),
                "state_card_chain": run.state_card_chain.copy(),
            })
            await _emit_event(run, "BEAT_SKIPPED", {
                "beat_id": card.beat_id,
                "segment_index": i,
            })
            i += 1
        elif act in ("edit", "branch"):
            edited_slot = action.get("edited_slot")
            if edited_slot is not None and act == "edit":
                _apply_edited_slot(card, edited_slot)
                card.edited = True
                card.edit_count = getattr(card, "edit_count", 0) + 1
            elif act == "branch":
                choice = action.get("branch_choice", {})
                directive = choice.get("plot_impact") or choice.get("label", "")
                if directive:
                    card.branch_directive = directive
            card.status = "pending"
            card.render_attempts = 0
            continue

    await _emit_event(run, "ALL_BEATS_LOCKED", {
        "segment_count": len(run.cards),
        "total_word_count": sum(
            len(getattr(s, "text", "") or "") for s in run.locked_segments
        ),
    })
    run.status = "post_processing"
    final_text = "\n\n".join(
        getattr(s, "text", "") for s in run.locked_segments if getattr(s, "text", "").strip()
    )
    result = await run.workflow.run_post_step_phases(
        final_text=final_text,
        locked_segments=run.locked_segments,
        run=run,
    )
    run.status = "done"
    run.final_result = result
    await _emit_event(run, "COMPLETE", result)


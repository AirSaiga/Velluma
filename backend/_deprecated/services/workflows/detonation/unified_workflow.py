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
统一引擎工作流（V3.1 §3 + §9 新建）。

职责（规格 §3 一章的生命周期 + §9.2 代码复用映射）：
把高潮倒推（3.0）与双轨（2.0）合并为一条管线，程序自主定档，按档位参数表执行。

九个 Phase（规格 §3）：
- Phase 0: 上下文组装（沿用：双通道召回 + established_facts）
- Phase 1: 章节卡 + 高潮候选（含强度自评） + 章节定档     ← TIER_DECIDED 通知
- Phase 2: 铺垫结构生长（逆向递归，深度随档）
- Phase 3: 高潮段先写（规格随档：climax 双候选+人选；其余单发+代码初筛）
- Phase 4: 蓄势段写作（朝已成稿高潮写，带高潮距离标注）
- Phase 5: 铺陈段写作（双轨工艺：去约束前向扩写 + 自由速写对照）
- Phase 6: 组装（阅读序拼接 + 接缝打磨）
- Phase 7: 审校（图校验 → 有锚审校 → 高潮验收/泄底检查）
- Phase 8: 局部修改（漏埋补写 / 泄底压低调子 / 高潮段重写）
- Phase 9: 定稿回写（伏笔自动登记）

写作顺序：高潮段 → 蓄势段 → 铺陈段（规格 §3）。

代码复用映射（规格 §9.2）：
- 3.0 全链（card/chain/payload/audit/refine/publish）→ 主链，按 tier 调参
- fuse_writer → 铺陈段写作（development 区去约束）+ 蓄势段写作（buildup 区带约束）
- SketchGenerator → 自由速写对照（sketch_baseline）
- 上下文引擎/文风体系/回写/观测 → 不变

飞行中调节（规格 §8，Step 5）：
- 中途升档（蓄势段发现高潮更强）
- 高潮验收 <7 重写高潮段
- 自由速写对照判定"压抑过度" → 注入小波折
- 铺陈段节点全 trivial → 并章建议

业务场景：
- POST /api/chapters/{id}/generate（统一入口）
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.models import (
    TIER_CLIMAX, TIER_TURN, TIER_PROGRESS, TIER_TRANSITION,
    TIER_MAX_DEPTH,
)
from backend.services.workflows.detonation.types import FuseSegment
from backend.services.workflows.detonation.graph_auditor import audit_chain_graph
from backend.services.workflows.detonation.chain_grower import (
    grow_detonation_chain,
    extract_established_facts,
)
from backend.services.workflows.detonation.payload_writer import write_payload_dual_candidates
from backend.services.workflows.detonation.fuse_writer import write_fuse_segments
from backend.services.workflows.detonation.assembler import assemble_chapter
from backend.services.workflows.detonation.anchored_auditor import (
    run_anchored_audit,
    derive_refinement_targets,
    DETONATION_SCORE_THRESHOLD,
)
from backend.services.workflows.detonation.refiner import refine_full
from backend.services.workflows.detonation.tier_classifier import (
    classify_tier,
    classify_from_user_forced,
    assign_zones,
)
from backend.services.workflows.detonation.sketch_baseline import (
    run_sketch_baseline,
    DIAGNOSIS_CONSISTENT,
    DIAGNOSIS_PREMATURE_SUSPICION,
    DIAGNOSIS_OVER_SUPPRESSED,
    ACTION_NONE,
    ACTION_TONE_DOWN,
    ACTION_MICRO_TWIST,
)
from backend.services.workflows.fail_fast import build_draft_validator

logger = logging.getLogger(__name__)


# Sketch baseline 启用的档位（规格 §5：转折章以下档位可关闭）
SKETCH_BASELINE_ENABLED_TIERS = {TIER_CLIMAX, TIER_TURN}


@dataclass
class UnifiedResult:
    """统一管线完整结果（对应 SSE 流的最终产物）。"""

    # 定档决策（Phase 1 产出）
    tier_decision: Dict[str, Any] = field(default_factory=dict)
    # 铺垫结构（Phase 2 产出）
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    reading_order: List[str] = field(default_factory=list)
    zones: Dict[str, List[str]] = field(default_factory=dict)
    # 高潮段（Phase 3 产出）
    payload: Dict[str, Any] = field(default_factory=dict)
    payload_text: str = ""
    # 写作段（Phase 4/5 产出）
    fuse_segments: List[FuseSegment] = field(default_factory=list)
    # 组装正文（Phase 6 产出）
    final_text: str = ""
    # 审校结论（Phase 7 产出）
    graph_audit: Dict[str, Any] = field(default_factory=dict)
    anchored_audit: Optional[Dict[str, Any]] = None
    # 飞行中调节事件（Step 5）
    sketch_baselines: List[Dict[str, Any]] = field(default_factory=list)
    inflight_events: List[Dict[str, Any]] = field(default_factory=list)
    # 统计与降级
    stats: Dict[str, Any] = field(default_factory=dict)
    degraded: List[Dict[str, Any]] = field(default_factory=list)
    debug_info: Dict[str, Any] = field(default_factory=dict)


class UnifiedWorkflow:
    """统一引擎工作流主类（V3.1）。

    使用模式：
        workflow = UnifiedWorkflow(
            chapter=chapter, book=book, chapter_card=cc, entities=entities,
            style_card=sc, recorder=recorder, tier="auto",
            candidates=payload_candidates,  # Phase 1 已生成
        )
        result = await workflow.execute(progress_callback=cb)
        # result.final_text 是完整正文；result.tier_decision 含定档结果

    设计要点：
    - 不持有 DB session（工作流层约定；持久化由调用方负责）
    - 九个 Phase 顺序执行，每阶段产出可观测（recorder + progress_callback）
    - 飞行中调节在各 Phase 内 hook（Step 5）
    - 所有降级显式标记（规格 P5 失败不静默）
    """

    def __init__(
        self,
        chapter: Any,
        book: Any,
        chapter_card: Any,
        entities: List[Any],
        style_card: Any = None,
        author_samples: Optional[List[str]] = None,
        recorder: Optional[Any] = None,
        # Phase 1 输入
        tier: str = "auto",
        candidates: Optional[List[Dict[str, Any]]] = None,
        user_tier_hint: Optional[str] = None,
        # 上下文（Phase 0 产出）
        established_facts: Optional[List[Dict[str, Any]]] = None,
        open_hooks: Optional[List[Any]] = None,
        previous_summary: Optional[str] = None,
        rolling_summary: Optional[str] = None,
        # 选项开关
        enable_sketch_baseline: bool = True,
        enable_anchored_audit: bool = True,
        enable_refinement: bool = True,
        enable_inflight_regulation: bool = True,
    ):
        """初始化。

        Args:
            chapter: Chapter ORM
            book: Book ORM
            chapter_card: ChapterCard ORM
            entities: 本章关联角色
            style_card: 可选 StyleCard ORM
            author_samples: 可选作者样本
            recorder: 可选 RunRecorder
            tier: auto|climax|turn|progress|transition
            candidates: Phase 1 已生成的高潮候选（含 climax_score）
            user_tier_hint: 用户预期档位提示
            established_facts: 已成立事实清单
            open_hooks: 开放伏笔
            previous_summary: 前章摘要
            rolling_summary: 滚动摘要
            enable_*: 各阶段开关
        """
        self.chapter = chapter
        self.book = book
        self.chapter_card = chapter_card
        self.entities = entities or []
        self.style_card = style_card
        self.author_samples = author_samples
        self.recorder = recorder

        self.tier_request = tier
        self.candidates = candidates or []
        self.user_tier_hint = user_tier_hint
        self.established_facts = established_facts or []
        self.open_hooks = open_hooks or []
        self.previous_summary = previous_summary
        self.rolling_summary = rolling_summary

        self.enable_sketch_baseline = enable_sketch_baseline
        self.enable_anchored_audit = enable_anchored_audit
        self.enable_refinement = enable_refinement
        self.enable_inflight_regulation = enable_inflight_regulation

    async def execute(
        self,
        progress_callback: Optional[Callable[..., Any]] = None,
    ) -> UnifiedResult:
        """执行统一管线九个 Phase。

        Args:
            progress_callback: 可选回调，签名为 async (event: str, data: dict) -> None

        Returns:
            UnifiedResult
        """
        result = UnifiedResult()

        async def _emit(event: str, data: dict) -> None:
            if progress_callback is not None:
                try:
                    await progress_callback(event, data)
                except Exception as e:
                    logger.warning(f"[UnifiedWorkflow] progress_callback 异常: {e}")

        # ============================================================
        # Phase 1: 章节定档（高潮候选已在调用方生成）
        # ============================================================
        await _emit("UNIFIED_STAGE", {"stage": "TIER_CLASSIFY"})

        if self.tier_request != "auto":
            # 用户强制指定
            tier_decision = classify_from_user_forced(
                forced_tier=self.tier_request,
                tension_level=self._get_tension_level(),
            )
        else:
            # 自动定档
            tier_decision = classify_tier(
                candidates=self.candidates,
                chapter_number=getattr(self.chapter, "chapter_number", None),
                total_chapters_in_volume=self._infer_volume_length(),
                tension_level=self._get_tension_level(),
                word_count=self._get_word_target(),
                user_tier_hint=self.user_tier_hint,
            )

        result.tier_decision = tier_decision
        tier = tier_decision["tier"]

        # 透明化通知（规格 §2.3）
        await _emit("TIER_DECIDED", tier_decision)
        logger.info(f"[UnifiedWorkflow] 定档={tier} reason={tier_decision['reason']}")

        # 选定 payload：取候选中 climax_score 最高的，或第一个
        chosen_payload = self._select_payload_candidate()
        if chosen_payload is None:
            # 无候选：构造最小 payload
            chosen_payload = {
                "description": "（未生成高潮候选，自动构造）",
                "emotional_target": "本章推进",
                "answers_question": "（未指定）",
                "opens_question": "（未指定）",
            }
            result.degraded.append({
                "reason": "no_payload_candidate",
                "action": "auto_minimal_payload",
            })
        result.payload = {
            "id": "PAYLOAD",
            "description": chosen_payload.get("description", ""),
            "emotional_target": chosen_payload.get("emotional_target", ""),
            "answers_question": chosen_payload.get("answers_question", ""),
            "opens_question": chosen_payload.get("opens_question"),
            "must_land": True,
            "candidate_index": 0,
            "text": None,
            "approved": False,
            "climax_score": chosen_payload.get("climax_score"),
        }

        # ============================================================
        # Phase 2: 铺垫结构生长（逆向递归，深度随档）
        # ============================================================
        await _emit("UNIFIED_STAGE", {"stage": "SETUP_GROW"})

        max_depth = tier_decision["max_depth"]
        try:
            grow_result = await grow_detonation_chain(
                payload=result.payload,
                chapter=self.chapter,
                chapter_card=self.chapter_card,
                established_facts=self.established_facts,
                open_hooks=self.open_hooks,
                entities=self.entities,
                previous_summary=self.previous_summary,
                max_depth=max_depth,
                recorder=self.recorder,
            )
            result.nodes = grow_result.nodes
            result.reading_order = grow_result.reading_order
            if grow_result.degraded:
                result.degraded.append({
                    "reason": "setup_grow_degraded",
                    "action": "proceed_with_violations",
                    "detail": grow_result.degraded,
                })
        except Exception as e:
            logger.exception(f"[UnifiedWorkflow] Phase 2 铺垫结构生长异常: {e}")
            result.degraded.append({
                "reason": "setup_grow_exception",
                "action": "minimal_chain",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            })
            # fallback：最小化单节点树
            result.nodes = [{
                "id": "n1", "type": "development", "content": chosen_payload.get("description", ""),
                "sets_up": ["PAYLOAD"], "distance_to_climax": 1, "assignment": "tighten",
            }]
            result.reading_order = ["n1", "PAYLOAD"]

        # 三分区分配（V3.1 §6）
        result.zones = assign_zones(result.nodes, result.reading_order, tier)
        await _emit("ZONE_ASSIGNED", {"zones": result.zones, "tier": tier})

        # ============================================================
        # Phase 3: 高潮段先写（规格随档）
        # ============================================================
        await _emit("UNIFIED_STAGE", {"stage": "CLIMAX_WRITE"})

        # 收集 distance ≤ 2 的直接铺垫节点
        direct_setup_nodes = [
            n for n in result.nodes
            if isinstance(n, dict) and self._node_distance(n) <= 2
        ]

        try:
            payload_result = await write_payload_dual_candidates(
                payload=result.payload,
                direct_setup_nodes=direct_setup_nodes,
                chapter=self.chapter,
                chapter_card=self.chapter_card,
                entities=self.entities,
                style_card=self.style_card,
                author_samples=self.author_samples,
                target_length=self._payload_target_length(tier),
                recorder=self.recorder,
            )
            # 自动选 winner（统一管线不做人工闸门，规格 §9.1）
            if payload_result.winner_text:
                result.payload_text = payload_result.winner_text
                result.payload["text"] = payload_result.winner_text
                result.payload["approved"] = True
            elif payload_result.candidates:
                result.payload_text = payload_result.candidates[0]
                result.payload["text"] = result.payload_text
                result.payload["approved"] = True
            else:
                result.degraded.append({
                    "reason": "payload_write_empty",
                    "action": "skip_climax",
                    "detail": "高潮段写作失败，跳过高潮段",
                })
            if payload_result.degraded:
                result.degraded.append(payload_result.degraded)
        except Exception as e:
            logger.exception(f"[UnifiedWorkflow] Phase 3 高潮段写作异常: {e}")
            result.degraded.append({
                "reason": "climax_write_exception",
                "action": "skip_climax",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            })

        # ============================================================
        # Phase 4 + 5: 蓄势段 + 铺陈段写作（统一调 write_fuse_segments，按 zone 分流）
        # ============================================================
        await _emit("UNIFIED_STAGE", {"stage": "ZONE_WRITE"})

        fuse_validator = self._build_fuse_validator()

        async def _fuse_progress(idx: int, total: int, segment: FuseSegment) -> None:
            await _emit("ZONE_PROGRESS", {
                "segment_index": idx,
                "total_segments": total,
                "node_id": segment.node_id,
                "word_count": segment.word_count,
                "zone": self._node_zone(segment.node_id, result.zones),
            })

        try:
            result.fuse_segments = await write_fuse_segments(
                nodes=result.nodes,
                reading_order=result.reading_order,
                payload_text=result.payload_text,
                chapter=self.chapter,
                chapter_card=self.chapter_card,
                entities=self.entities,
                style_card=self.style_card,
                author_samples=self.author_samples,
                fail_fast_validator=fuse_validator,
                recorder=self.recorder,
                progress_callback=_fuse_progress,
                zones=result.zones,
            )
        except Exception as e:
            logger.exception(f"[UnifiedWorkflow] Phase 4/5 写作异常: {e}")
            result.degraded.append({
                "reason": "zone_write_exception",
                "action": "partial_abort",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            })

        # ============================================================
        # 飞行中调节 1: 自由速写对照（仅 buildup 区，转折章以上档位，规格 §5）
        # ============================================================
        if (self.enable_sketch_baseline
            and tier in SKETCH_BASELINE_TIERS_TO_RUN
            and result.zones.get("buildup")):
            await _emit("UNIFIED_STAGE", {"stage": "SKETCH_BASELINE"})
            await self._run_sketch_baselines(result, _emit)

        # ============================================================
        # Phase 6: 组装（阅读序拼接 + 接缝打磨）
        # ============================================================
        await _emit("UNIFIED_STAGE", {"stage": "ASSEMBLING"})

        try:
            full_text, seam_info = await assemble_chapter(
                fuse_segments=result.fuse_segments,
                payload_text=result.payload_text,
                recorder=self.recorder,
            )
            result.final_text = full_text
            result.debug_info["seam_info"] = seam_info
        except Exception as e:
            logger.exception(f"[UnifiedWorkflow] Phase 6 组装异常: {e}")
            result.degraded.append({
                "reason": "assemble_exception",
                "action": "raw_concat_fallback",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            })
            fuse_text = "\n\n".join(s.text for s in result.fuse_segments if s.text)
            result.final_text = f"{fuse_text}\n\n{result.payload_text}".strip()

        # ============================================================
        # Phase 7: 审校（图校验 → 有锚审校 → 高潮验收）
        # ============================================================
        await _emit("UNIFIED_STAGE", {"stage": "GRAPH_AUDIT"})
        result.graph_audit = audit_chain_graph(
            nodes=result.nodes,
            reading_order=result.reading_order,
            payload=result.payload,
        )
        if result.graph_audit.get("verdict") != "pass":
            result.degraded.append({
                "reason": "graph_audit_failed",
                "action": "return_with_violations",
                "violations": result.graph_audit.get("violations", [])[:5],
            })

        if self.enable_anchored_audit and result.final_text:
            await _emit("UNIFIED_STAGE", {"stage": "ANCHORED_AUDIT"})
            try:
                result.anchored_audit = await run_anchored_audit(
                    nodes=result.nodes,
                    reading_order=result.reading_order,
                    full_text=result.final_text,
                    payload_text=result.payload_text,
                    recorder=self.recorder,
                )
                if result.anchored_audit.get("verdict") == "unaudited":
                    result.degraded.append({
                        "reason": "anchored_audit_unaudited",
                        "action": "return_unaudited",
                    })

                # ============================================================
                # 飞行中调节 2: 高潮验收 <7 重写高潮段（规格 §8）
                # ============================================================
                if (self.enable_inflight_regulation
                    and result.anchored_audit.get("detonation_score") is not None
                    and result.anchored_audit["detonation_score"] < DETONATION_SCORE_THRESHOLD):
                    await _emit("UNIFIED_STAGE", {"stage": "CLIMAX_REWRITE"})
                    await self._rewrite_climax(result, _emit)

            except Exception as e:
                logger.exception(f"[UnifiedWorkflow] Phase 7 有锚审校异常: {e}")
                result.degraded.append({
                    "reason": "anchored_audit_exception",
                    "action": "skip_audit",
                    "detail": f"{type(e).__name__}: {str(e)[:200]}",
                })

        # ============================================================
        # Phase 8: 局部修改（漏埋补写 / 泄底降调）
        # ============================================================
        if (self.enable_refinement
            and result.anchored_audit
            and result.anchored_audit.get("verdict") == "needs_refinement"
            and result.final_text):
            await _emit("UNIFIED_STAGE", {"stage": "REFINING"})
            try:
                refine_result = await refine_full(
                    full_text=result.final_text,
                    nodes=result.nodes,
                    audit_result=result.anchored_audit,
                    recorder=self.recorder,
                )
                if refine_result.get("refined_text") and refine_result["refined_text"] != result.final_text:
                    result.final_text = refine_result["refined_text"]
                    result.debug_info["refine_actions"] = refine_result.get("actions", [])
                for deg in refine_result.get("degraded", []):
                    result.degraded.append(deg)
            except Exception as e:
                logger.exception(f"[UnifiedWorkflow] Phase 8 精修异常: {e}")
                result.degraded.append({
                    "reason": "refine_exception",
                    "action": "skip_refine",
                    "detail": f"{type(e).__name__}: {str(e)[:200]}",
                })

        # ============================================================
        # 飞行中调节 3: 并章建议（铺陈段节点全 trivial，规格 §8）
        # ============================================================
        if self.enable_inflight_regulation:
            await self._check_merge_suggestion(result, _emit)

        # ============================================================
        # 统计
        # ============================================================
        result.stats = {
            "tier": tier,
            "tier_reason": tier_decision["reason"],
            "zones": {
                zname: len(nids) for zname, nids in result.zones.items()
            },
            "setup_node_count": len(result.nodes),
            "fuse_segment_count": len(result.fuse_segments),
            "fuse_total_words": sum(s.word_count for s in result.fuse_segments),
            "payload_words": len(result.payload_text.replace(" ", "")) if result.payload_text else 0,
            "total_words": len(result.final_text.replace(" ", "")) if result.final_text else 0,
            "graph_audit_verdict": result.graph_audit.get("verdict"),
            "anchored_audit_verdict": result.anchored_audit.get("verdict") if result.anchored_audit else None,
            "climax_check_score": result.anchored_audit.get("detonation_score") if result.anchored_audit else None,
            "sketch_baseline_count": len(result.sketch_baselines),
            "inflight_event_count": len(result.inflight_events),
        }
        # 同步 climax_check_score 到 payload（供下游使用）
        if result.anchored_audit and result.anchored_audit.get("detonation_score") is not None:
            result.payload["climax_check_score"] = result.anchored_audit["detonation_score"]

        logger.info(
            f"[UnifiedWorkflow] 完成 tier={tier} "
            f"节点={len(result.nodes)} 段={len(result.fuse_segments)} "
            f"总字={result.stats['total_words']} "
            f"高潮验收={result.stats['climax_check_score']} "
            f"降级={len(result.degraded)}"
        )

        return result

    # ============================================================
    # 飞行中调节实现（Step 5）
    # ============================================================

    async def _run_sketch_baselines(self, result: UnifiedResult, _emit) -> None:
        """自由速写对照（规格 §5）：对 buildup 区跑对照，压抑过度则注入小波折。"""
        # 把 buildup 区的 fuse_segments 提取出来对照
        buildup_node_ids = set(result.zones.get("buildup", []))
        buildup_segments = [s for s in result.fuse_segments if s.node_id in buildup_node_ids]

        if not buildup_segments:
            return

        # 合并 buildup 区文本作为对照目标
        buildup_text = "\n\n".join(s.text for s in buildup_segments if s.text)
        if not buildup_text or len(buildup_text) < 100:
            return

        # 节点摘要（供速写对齐）
        node_summaries = [
            {"content": n.get("content", ""), "restraint_note": n.get("restraint_note")}
            for n in result.nodes if n.get("id") in buildup_node_ids
        ]

        baseline = await run_sketch_baseline(
            zone="buildup",
            zone_text=buildup_text,
            payload_anchor=result.payload_text,
            node_summaries=node_summaries,
            style_card=self.style_card,
            author_samples=self.author_samples,
            recorder=self.recorder,
        )
        result.sketch_baselines.append(baseline)
        await _emit("SKETCH_BASELINE", baseline)

        # 处置：压抑过度 → 标记建议（实际小波折注入留待 Phase 8 精修，规格 §12 二次复核）
        if baseline.get("diagnosis") == DIAGNOSIS_OVER_SUPPRESSED:
            result.inflight_events.append({
                "type": "over_suppressed_detected",
                "zone": "buildup",
                "action": "suggest_micro_twist",
                "reason": baseline.get("diagnosis_reason", ""),
            })
            await _emit("INFLIGHT_REGULATION", {
                "type": "over_suppressed_detected",
                "action": ACTION_MICRO_TWIST,
                "reason": baseline.get("diagnosis_reason", ""),
            })
        elif baseline.get("diagnosis") == DIAGNOSIS_PREMATURE_SUSPICION:
            result.inflight_events.append({
                "type": "premature_suspicion_detected",
                "zone": "buildup",
                "action": "suggest_tone_down",
                "reason": baseline.get("diagnosis_reason", ""),
            })
            await _emit("INFLIGHT_REGULATION", {
                "type": "premature_suspicion_detected",
                "action": ACTION_TONE_DOWN,
                "reason": baseline.get("diagnosis_reason", ""),
            })

    async def _rewrite_climax(self, result: UnifiedResult, _emit) -> None:
        """高潮验收 <7 时重写高潮段（规格 §8 表）。

        策略：换候选/换角度重写高潮段，仅波及高潮段 + 邻近蓄势段。
        巡航的铺陈段不动——高潮重写的波及面被结构局部化。
        """
        current_score = result.anchored_audit.get("detonation_score")
        logger.info(
            f"[UnifiedWorkflow] 高潮验收 {current_score} < {DETONATION_SCORE_THRESHOLD}，触发重写"
        )
        result.inflight_events.append({
            "type": "climax_rewrite",
            "from_score": current_score,
            "threshold": DETONATION_SCORE_THRESHOLD,
        })
        await _emit("INFLIGHT_REGULATION", {
            "type": "climax_rewrite",
            "from_score": current_score,
            "threshold": DETONATION_SCORE_THRESHOLD,
        })

        # 重写高潮段：换一个温度（提高创意）
        try:
            from backend.services.llm import call_llm_with_usage
            from backend.services.prompts.detonation_prompts import build_fuse_write_prompt
            # 取 buildup 区第一段作为前文
            buildup_node_ids = result.zones.get("buildup", [])
            tail = ""
            for seg in result.fuse_segments:
                if seg.node_id in buildup_node_ids and seg.text:
                    tail = seg.text[-500:]
                    break

            # 构造重写 prompt（强调"情绪顶起来"）
            system_prompt = """你是一位技艺精湛的小说家，正在【重写】一章小说的高潮段。

之前写过的版本情绪不够顶（验收分低）。这次要：
1. 情绪强度拉满——让读者心头一震
2. 但克制最深——靠具体动作/细节而非堆形容词
3. 专属性最强——这段只能属于此刻此人物

只输出高潮段正文，不要任何前言/解释。"""

            user_prompt = f"""## 高潮点
- 描述：{result.payload.get('description', '')}
- 情绪目标：{result.payload.get('emotional_target', '')}
- 回答的问题：{result.payload.get('answers_question', '')}

## 验收反馈
上次版本验收分 {current_score}/10，理由：{result.anchored_audit.get('detonation_reason', '情绪未顶起')}

## 前文末尾（衔接）
{tail or '（无）'}

请重写高潮段（约 {len(result.payload_text.replace(' ', ''))} 字），把情绪顶起来："""

            if self.recorder is not None:
                async with self.recorder.record_call(
                    stage="detonation.unified.climax_rewrite",
                    model_slot="creative",
                ) as ctx:
                    rewrite_result = await call_llm_with_usage(
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        model_type="creative",
                        temperature=0.9,  # 提高温度换角度
                        max_tokens=4096,
                    )
                    ctx.set_result(rewrite_result)
            else:
                rewrite_result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=0.9,
                    max_tokens=4096,
                )

            new_text = (rewrite_result.content or "").strip()
            if new_text and len(new_text) > 100:
                # 替换高潮段（重新组装）
                old_payload = result.payload_text
                result.payload_text = new_text
                result.payload["text"] = new_text
                # 重组正文（铺陈段+蓄势段不变，仅替换高潮段）
                fuse_text = "\n\n".join(s.text for s in result.fuse_segments if s.text)
                result.final_text = f"{fuse_text}\n\n{new_text}".strip()
                logger.info(f"[UnifiedWorkflow] 高潮段重写完成：{len(old_payload)}→{len(new_text)} 字")
            else:
                result.degraded.append({
                    "reason": "climax_rewrite_empty",
                    "action": "keep_original",
                })
        except Exception as e:
            logger.exception(f"[UnifiedWorkflow] 高潮段重写异常: {e}")
            result.degraded.append({
                "reason": "climax_rewrite_exception",
                "action": "keep_original",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            })

    async def _check_merge_suggestion(self, result: UnifiedResult, _emit) -> None:
        """并章建议（规格 §8 表）：铺陈段节点全 trivial → 建议并章/删章。

        通知式：管线第一次能反过来教作者做减法（用户决定）。
        """
        if not result.nodes:
            return
        # 检查 development 区节点是否全 trivial
        dev_node_ids = set(result.zones.get("development", []))
        if not dev_node_ids:
            return
        dev_nodes = [n for n in result.nodes if n.get("id") in dev_node_ids]
        trivial_count = sum(1 for n in dev_nodes if n.get("trivial"))
        if dev_nodes and trivial_count == len(dev_nodes) and len(dev_nodes) >= 2:
            # 全 trivial：建议并章
            suggestion = {
                "suggestion_type": "merge",
                "reason": f"铺陈段 {len(dev_nodes)} 个节点全部 trivial（本章确实无事发生）",
                "detail": "建议与相邻章节合并，或删除本章。这是通知式建议，最终由用户决定。",
            }
            result.inflight_events.append({
                "type": "merge_suggestion",
                **suggestion,
            })
            await _emit("MERGE_SUGGESTION", suggestion)
            logger.info(f"[UnifiedWorkflow] 触发并章建议：{suggestion['reason']}")

    # ============================================================
    # 辅助方法
    # ============================================================

    def _select_payload_candidate(self) -> Optional[Dict[str, Any]]:
        """从候选中选 climax_score 最高的（统一管线不做人工闸门）。"""
        if not self.candidates:
            return None
        valid = [c for c in self.candidates if isinstance(c, dict)]
        if not valid:
            return None
        # 按 climax_score 降序（None 视为 0）
        return max(valid, key=lambda c: c.get("climax_score") or 0)

    def _node_distance(self, node: Dict[str, Any]) -> int:
        """读取节点距离（双键兼容）。"""
        d = node.get("distance_to_climax")
        if d is None:
            d = node.get("distance_to_payload", 1)
        try:
            return int(d)
        except (TypeError, ValueError):
            return 1

    def _node_zone(self, node_id: str, zones: Dict[str, List[str]]) -> str:
        """查询节点所属 zone。"""
        for zname, nids in zones.items():
            if node_id in nids:
                return zname
        return "unknown"

    def _get_tension_level(self) -> Optional[int]:
        if self.chapter_card is not None:
            return getattr(self.chapter_card, "tension", None)
        return getattr(self.chapter, "tension_level", None)

    def _get_word_target(self) -> Optional[int]:
        if self.chapter_card is not None:
            return getattr(self.chapter_card, "word_target", None)
        return None

    def _infer_volume_length(self) -> Optional[int]:
        """推断卷长（用于位置加权）。

        简化策略：从 chapter_number 推断（>10 视为长卷）。
        真实卷长需 book.outline 解析，这里保守返回 None（不做卷长加权）。
        """
        return None

    def _payload_target_length(self, tier: str) -> int:
        """高潮段目标长度（按档位，规格 §2.1 + §4.1）。"""
        return {
            TIER_CLIMAX: 1200,    # 全章 15-25%
            TIER_TURN: 1000,
            TIER_PROGRESS: 800,
            TIER_TRANSITION: 600,  # 过渡章"一笔"
        }.get(tier, 1000)

    def _build_fuse_validator(self):
        """构造 fail-fast 校验闭包。"""
        minimal_beat = {"red_lines": [], "pacing_type": "medium"}

        class _BookProxy:
            def __init__(self, style_card_obj: Any):
                negative = getattr(style_card_obj, "negative_list", []) or [] if style_card_obj else []
                self.style_blacklist = negative
                self.core_motifs_taboos = ""

        book_proxy = _BookProxy(self.style_card)
        try:
            return build_draft_validator(
                beat=minimal_beat,
                book=book_proxy,
                pov_character="",
            )
        except Exception as e:
            logger.warning(f"[UnifiedWorkflow] 构造 validator 失败: {e}")
            return None


# Sketch baseline 实际运行的档位（转折章以上，规格 §5）
SKETCH_BASELINE_TIERS_TO_RUN = SKETCH_BASELINE_ENABLED_TIERS

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
爆发链工作流主类（V3.0 新建）。

职责（设计文档 §5 Phase 4-7）：
编排铺垫写作 → 组装 → Layer 0 图校验（→ Slice B 有锚审计 → 精修）。

业务流程：
1. 加载已确认的 DetonationChain（payload 已冻结 + nodes/reading_order 已确认）
2. 加载上下文（ContextEngine 复用，文风卡/章节卡/角色）
3. write_fuse_segments（串行 Rolling Prefix 链，朝爆炸写）
4. assemble_chapter（阅读序拼接 + 接缝打磨）
5. Layer 0 图校验（graph_auditor，零 token）
6. [Slice B] Layer 1 有锚审计 + 局部精修
7. 返回 DetonationResult

与 DualTrackWorkflow 的隔离：
- 完全独立类，不共享任何状态
- 共享层（ContextEngine / RunRecorder / 文风体系）通过参数注入
- 入口端点 /generate-v3 调用本类；/generate-chapter 仍走 DualTrackWorkflow

业务场景：
- 闸门 3 之后：POST /api/chapters/{id}/generate-v3（SSE 流）
"""

import logging
from typing import Any, Dict, List, Optional

from backend.services.workflows.detonation.assembler import assemble_chapter
from backend.services.workflows.detonation.fuse_writer import write_fuse_segments
from backend.services.workflows.detonation.graph_auditor import audit_chain_graph
from backend.services.workflows.detonation.types import DetonationResult, FuseSegment
from backend.services.workflows.fail_fast import build_draft_validator

logger = logging.getLogger(__name__)


class DetonationWorkflow:
    """爆发链工作流主类。

    使用模式：
        workflow = DetonationWorkflow(
            chain=chain_dict,           # 已确认的爆发链（payload 已冻结）
            chapter=chapter,
            chapter_card=chapter_card,
            entities=entities,
            style_card=style_card,
            author_samples=samples,
            recorder=recorder,
        )
        result = await workflow.execute(progress_callback=cb)
        # result.final_text 是完整正文

    设计要点：
    - 不持有 DB session（工作流层约定；持久化由调用方负责）
    - 串行执行（呼吸连续性要求；与 DualTrack 的并行 Track A/B 本质不同）
    - 每阶段产出可观测（recorder + progress_callback）
    """

    def __init__(
        self,
        chain: Dict[str, Any],
        chapter: Any,
        chapter_card: Any,
        entities: List[Any],
        style_card: Any = None,
        author_samples: Optional[List[str]] = None,
        recorder: Optional[Any] = None,
        enable_seam_polish: bool = True,
        enable_anchored_audit: bool = True,
        enable_refinement: bool = True,
    ):
        """初始化。

        Args:
            chain: DetonationChain dict（含 payload/nodes/reading_order/status）
                   要求 payload.text 已冻结（approved=True）
            chapter: Chapter ORM 对象
            chapter_card: ChapterCard ORM 对象
            entities: 本章关联角色列表（ChapterEntity，含 .character）
            style_card: 可选 StyleCard ORM 对象
            author_samples: 可选作者样本列表
            recorder: 可选 RunRecorder
            enable_seam_polish: 是否打磨接缝（默认 True）
            enable_anchored_audit: 是否启用 Layer 1 有锚审计（Slice B，默认 True）
            enable_refinement: 是否启用局部精修（Slice B，默认 True）
        """
        self.chain = chain
        self.chapter = chapter
        self.chapter_card = chapter_card
        self.entities = entities or []
        self.style_card = style_card
        self.author_samples = author_samples
        self.recorder = recorder
        self.enable_seam_polish = enable_seam_polish
        self.enable_anchored_audit = enable_anchored_audit
        self.enable_refinement = enable_refinement

        # 从 chain 提取核心字段
        self.payload: Dict[str, Any] = chain.get("payload", {}) or {}
        self.nodes: List[Dict[str, Any]] = chain.get("nodes", []) or []
        self.reading_order: List[str] = chain.get("reading_order", []) or []
        self.payload_text: str = (self.payload.get("text") or "").strip()

    async def execute(
        self,
        progress_callback: Optional[Any] = None,
    ) -> DetonationResult:
        """执行爆发链工作流（铺垫写作 → 组装 → 图校验）。

        Args:
            progress_callback: 可选回调，签名为 async (event: str, data: dict) -> None

        Returns:
            DetonationResult
        """
        result = DetonationResult()
        result.payload_text = self.payload_text

        # ---- 前置校验：payload.text 必须已冻结 ----
        if not self.payload_text:
            degraded = {
                "reason": "payload_text_not_frozen",
                "action": "abort",
                "detail": "爆发段尚未通过人审冻结，无法进入铺垫写作",
            }
            result.degraded.append(degraded)
            logger.error(f"[DetonationWorkflow] {degraded['detail']}")
            return result

        # ---- fail-fast 校验闭包（铺垫段即时校验）----
        fuse_validator = self._build_fuse_validator()

        # ============================================================
        # Phase 4: 铺垫写作（串行 Rolling Prefix 链）
        # ============================================================
        async def _fuse_progress(idx: int, total: int, segment: FuseSegment) -> None:
            if progress_callback is not None:
                await progress_callback("FUSE_PROGRESS", {
                    "segment_index": idx,
                    "total_segments": total,
                    "node_id": segment.node_id,
                    "word_count": segment.word_count,
                })

        try:
            fuse_segments = await write_fuse_segments(
                nodes=self.nodes,
                reading_order=self.reading_order,
                payload_text=self.payload_text,
                chapter=self.chapter,
                chapter_card=self.chapter_card,
                entities=self.entities,
                style_card=self.style_card,
                author_samples=self.author_samples,
                fail_fast_validator=fuse_validator,
                recorder=self.recorder,
                progress_callback=_fuse_progress,
            )
        except Exception as e:
            degraded = {
                "reason": "fuse_write_exception",
                "action": "partial_abort",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            }
            result.degraded.append(degraded)
            logger.exception(f"[DetonationWorkflow] 铺垫写作异常: {e}")
            return result

        result.fuse_segments = fuse_segments

        # 检查是否有空段（降级标记）
        empty_segments = [s for s in fuse_segments if not s.text]
        if empty_segments:
            for s in empty_segments:
                result.degraded.append({
                    "reason": "empty_fuse_segment",
                    "action": "skip_in_assembly",
                    "node_id": s.node_id,
                })

        # ============================================================
        # Phase 5: 组装（阅读序拼接 + 接缝打磨）
        # ============================================================
        if progress_callback is not None:
            await progress_callback("DETONATION_STAGE", {"stage": "ASSEMBLING"})

        try:
            full_text, seam_info = await assemble_chapter(
                fuse_segments=fuse_segments,
                payload_text=self.payload_text,
                seam_polish=self.enable_seam_polish,
                recorder=self.recorder,
            )
        except Exception as e:
            degraded = {
                "reason": "assemble_exception",
                "action": "raw_concat_fallback",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            }
            result.degraded.append(degraded)
            logger.exception(f"[DetonationWorkflow] 组装异常，降级 raw 拼接: {e}")
            # fallback：raw 拼接
            fuse_text = "\n\n".join(s.text for s in fuse_segments if s.text)
            full_text = f"{fuse_text}\n\n{self.payload_text}".strip()
            seam_info = {"polished": False, "reason": "assemble_exception"}

        result.final_text = full_text
        result.debug_info["seam_info"] = seam_info

        # ============================================================
        # Phase 6 Layer 0: 图校验（零 token）
        # ============================================================
        if progress_callback is not None:
            await progress_callback("DETONATION_STAGE", {"stage": "GRAPH_AUDIT"})

        graph_audit = audit_chain_graph(
            nodes=self.nodes,
            reading_order=self.reading_order,
            payload=self.payload,
        )
        result.graph_audit = graph_audit

        if graph_audit.get("verdict") != "pass":
            result.degraded.append({
                "reason": "graph_audit_failed",
                "action": "return_with_violations",
                "violations": graph_audit.get("violations", [])[:5],
            })

        # ============================================================
        # Phase 6 Layer 1 + Phase 7: 有锚审计 + 局部精修（Slice B）
        # ============================================================
        if self.enable_anchored_audit:
            if progress_callback is not None:
                await progress_callback("DETONATION_STAGE", {"stage": "ANCHORED_AUDIT"})

            try:
                from backend.services.workflows.detonation.anchored_auditor import run_anchored_audit
                audit_result = await run_anchored_audit(
                    nodes=self.nodes,
                    reading_order=self.reading_order,
                    full_text=full_text,
                    payload_text=self.payload_text,
                    recorder=self.recorder,
                )
                result.anchored_audit = audit_result

                if audit_result.get("verdict") == "unaudited":
                    result.degraded.append({
                        "reason": "anchored_audit_unaudited",
                        "action": "return_unaudited",
                        "detail": str(audit_result.get("degraded", {})),
                    })
                elif audit_result.get("verdict") == "needs_refinement" and self.enable_refinement:
                    # Phase 7: 局部精修
                    if progress_callback is not None:
                        await progress_callback("DETONATION_STAGE", {"stage": "REFINING"})

                    from backend.services.workflows.detonation.refiner import refine_full
                    refine_result = await refine_full(
                        full_text=full_text,
                        nodes=self.nodes,
                        audit_result=audit_result,
                        recorder=self.recorder,
                    )
                    if refine_result.get("refined_text") and refine_result["refined_text"] != full_text:
                        full_text = refine_result["refined_text"]
                        result.final_text = full_text
                        result.debug_info["refine_actions"] = refine_result.get("actions", [])
                        for deg in refine_result.get("degraded", []):
                            result.degraded.append(deg)
            except Exception as e:
                logger.exception(f"[DetonationWorkflow] 有锚审计/精修异常: {e}")
                result.degraded.append({
                    "reason": "anchored_audit_exception",
                    "action": "skip_audit",
                    "detail": f"{type(e).__name__}: {str(e)[:200]}",
                })

        # ============================================================
        # 统计信息
        # ============================================================
        result.stats = {
            "fuse_segment_count": len(fuse_segments),
            "fuse_total_words": sum(s.word_count for s in fuse_segments),
            "payload_words": len(self.payload_text.replace(" ", "")),
            "total_words": len(full_text.replace(" ", "")),
            "empty_segment_count": len(empty_segments),
            "graph_audit_verdict": graph_audit.get("verdict"),
            "graph_audit_violations": len(graph_audit.get("violations", [])),
            # Slice B 有锚审计指标
            "anchored_audit_verdict": result.anchored_audit.get("verdict") if result.anchored_audit else None,
            "detonation_score": result.anchored_audit.get("detonation_score") if result.anchored_audit else None,
            "broken_node_count": len(result.anchored_audit.get("broken", [])) if result.anchored_audit else 0,
            "premature_segment_count": len(result.anchored_audit.get("premature", [])) if result.anchored_audit else 0,
            "restraint_violation_count": len(result.anchored_audit.get("restraint_violations", [])) if result.anchored_audit else 0,
        }

        logger.info(
            f"[DetonationWorkflow] 完成：铺垫 {result.stats['fuse_segment_count']} 段 "
            f"{result.stats['fuse_total_words']} 字 + 爆发 {result.stats['payload_words']} 字 "
            f"= 总 {result.stats['total_words']} 字；"
            f"降级事件 {len(result.degraded)} 条"
        )

        return result

    def _build_fuse_validator(self):
        """构造铺垫段 fail-fast 校验闭包。"""
        # 复用 build_draft_validator（与 payload_writer 同样的最小化策略）
        minimal_beat = {
            "red_lines": [],
            "pacing_type": "medium",
        }

        class _BookProxy:
            def __init__(self, style_card_obj: Any):
                negative = getattr(style_card_obj, "negative_list", []) or [] if style_card_obj else []
                self.style_blacklist = negative
                self.core_motifs_taboos = ""

        book_proxy = _BookProxy(self.style_card)
        try:
            validator = build_draft_validator(
                beat=minimal_beat,
                book=book_proxy,
                pov_character="",
            )
            return validator
        except Exception as e:
            logger.warning(f"[DetonationWorkflow] 构造 validator 失败，铺垫写作不校验: {e}")
            return None

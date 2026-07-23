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
ADF（Anchor-Driven Flow）工作流主类（V3.2 §4 新建）。

职责（设计文档 §4 七个 Phase）：
- Phase 0: 上下文组装（调用方负责，本类接收）
- Phase 1: 脉络轨构建（spine_track_builder）
- Phase 2: 远端锚设计（anchor_designer，1 次 reasoning）
- Phase 3: 定档（tier_decider，0 LLM）
- Phase 4: 正向流写作（forward_flow_writer，N 次 creative）★ 核心
- Phase 5: 锚点审计（anchor_auditor，1 次 reasoning）
- Phase 6: 条件补埋（refiner，0-K 次 creative）

设计要点：
- 不持有 DB session（工作流层约定；持久化由调用方负责）
- 每个 Phase 显式推送 progress 事件
- 所有降级显式标记（失败不静默）

业务场景：
- POST /api/chapters/{id}/generate-adf（routes/chapter_generation/adf.py）

使用示例：
    workflow = ADFWorkflow(
        chapter=chapter, book=book, chapter_card=cc, entities=entities,
        style_card=sc, recorder=recorder, request=req,
        previous_summary=..., rolling_summary=..., open_hooks=...,
    )
    result = await workflow.execute(progress_callback=cb)
    # result.final_text 是完整正文
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from backend.services.observability.run_recorder import RunRecorder
from backend.services.workflows.adf.story_context_builder import build_story_context
from backend.services.workflows.adf.climax_designer import design_chapter_climax
from backend.services.workflows.adf.tier_decider import decide_tier
from backend.services.workflows.adf.segment_writer import (
    write_chapter_segments,
    _build_style_contract,
    _build_author_samples,
    _build_characters_text,
)
from backend.services.workflows.adf.structure_checker import run_structure_check
from backend.services.workflows.adf.refiner import refine_missing_preconditions
from backend.services.workflows.adf.pruner import run_prune_pass
from backend.services.workflows.adf.types import GenerationResult

logger = logging.getLogger(__name__)


class ADFWorkflow:
    """ADF 工作流主类（V3.2）。

    使用模式：
        workflow = ADFWorkflow(
            chapter=chapter, book=book, chapter_card=cc, entities=entities,
            style_card=sc, recorder=recorder, request=req,
            previous_summary=ps, rolling_summary=rs, open_hooks=oh,
        )
        result = await workflow.execute(progress_callback=cb)

    设计要点：
    - 不持有 DB session（工作流层约定；持久化由调用方负责）
    - 七个 Phase 顺序执行，每阶段产出可观测（recorder + progress_callback）
    - 所有降级显式标记
    """

    def __init__(
        self,
        chapter: Any,
        book: Any,
        chapter_card: Any,
        entities: List[Any],
        style_card: Any,
        author_samples: Optional[List[Any]] = None,
        recorder: Optional[RunRecorder] = None,
        request: Any = None,
        previous_summary: Any = None,
        rolling_summary: Any = None,
        open_hooks: Any = None,
        canon_context: str = "",
        author_intent: Optional[str] = None,
        expectation_actions: Optional[Dict[str, str]] = None,
        # V3.5 新增：设定感知层数据（用户章级显式指定的设定）
        locations: Optional[List[Any]] = None,
        assets: Optional[List[Any]] = None,
        relationships: Optional[List[Any]] = None,
        worldview_text: str = "",
    ):
        self.chapter = chapter
        self.book = book
        self.chapter_card = chapter_card
        self.entities = entities or []
        self.style_card = style_card
        self.author_samples = author_samples
        self.recorder = recorder
        self.request = request
        self.previous_summary = previous_summary
        self.rolling_summary = rolling_summary
        self.open_hooks = open_hooks or []
        self.canon_context = canon_context or ""  # V4.0 作者脑中世界图谱
        self.author_intent = author_intent or ""  # V4.2 介入点 1 作者意图
        self.expectation_actions = expectation_actions or {}  # V4.2 期待决策
        # V3.5：设定感知层数据
        self.locations = locations or []
        self.assets = assets or []
        self.relationships = relationships or []
        self.worldview_text = worldview_text or ""

    async def execute(
        self,
        progress_callback: Optional[Callable[[str, dict], Any]] = None,
    ) -> GenerationResult:
        """执行 ADF 七个 Phase。

        Args:
            progress_callback: 进度回调，签名 (event: str, data: dict) -> Any
                事件类型：ADF_STAGE / ADF_SPINE_BUILT / ADF_ANCHOR_DESIGNED /
                TIER_DECIDED / ADF_PROGRESS / ADF_PRECONDITION_LANDED /
                ADF_AUDIT

        Returns:
            GenerationResult
        """
        result = GenerationResult()
        request = self.request

        async def _emit(event: str, data: dict) -> None:
            if progress_callback:
                try:
                    await progress_callback(event, data)
                except Exception as e:
                    logger.warning(f"[ADF] progress_callback {event} 失败: {e}")

        # ============================================================
        # Phase 1: 脉络轨构建（SPINE_BUILDING）
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "SPINE_BUILDING"})

        enable_spine = getattr(request, "enable_spine", True)
        if enable_spine:
            try:
                spine = await build_story_context(
                    chapter=self.chapter,
                    book=self.book,
                    chapter_card=self.chapter_card,
                    entities=self.entities,
                    previous_summary=self.previous_summary,
                    rolling_summary=self.rolling_summary,
                    open_hooks=self.open_hooks,
                )
            except Exception as e:
                logger.warning(f"[ADF] Phase 1 脉络轨构建异常，降级空 spine: {e}")
                from backend.services.workflows.adf.types import StoryContext
                spine = StoryContext()
                result.degraded.append({"phase": "spine", "reason": "exception", "detail": str(e)[:200]})
        else:
            from backend.services.workflows.adf.types import StoryContext
            spine = StoryContext()

        result.spine_track = spine
        await _emit("ADF_SPINE_BUILT", {
            "must_plant_hooks": spine.must_plant_hooks,
            "must_resolve_hooks": spine.must_resolve_hooks,
            "offset_from_volume_climax": spine.chapter_position.offset_from_volume_climax,
            "pacing_tempo": spine.chapter_position.pacing_tempo,
        })

        # ============================================================
        # Phase 2: 远端锚设计（ANCHOR_DESIGN，1 次 reasoning）
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "ANCHOR_DESIGN"})

        try:
            anchor = await design_chapter_climax(
                chapter=self.chapter,
                chapter_card=self.chapter_card,
                spine=spine,
                previous_summary=self.previous_summary,
                rolling_summary=self.rolling_summary,
                open_hooks=self.open_hooks,
                entities=self.entities,
                recorder=self.recorder,
                canon_context=self.canon_context,
                author_intent=self.author_intent,
                expectation_actions=self.expectation_actions,
            )
        except Exception as e:
            logger.exception(f"[ADF] Phase 2 远端锚设计异常: {e}")
            from backend.services.workflows.adf.types import (
                ChapterClimax, ClimaxSpec, EmotionCurve, EmotionCurveSample,
            )
            anchor = ChapterClimax(
                climax=ClimaxSpec(description="（设计失败，降级默认）", intensity=5),
                preconditions=[],
                emotion_curve=EmotionCurve(samples=[
                    EmotionCurveSample(progress=0.0, register="入口", energy=2),
                    EmotionCurveSample(progress=1.0, register="收束", energy=5),
                ]),
            )
            result.degraded.append({"phase": "anchor_design", "reason": "exception", "detail": str(e)[:200]})

        result.distal_anchor = anchor
        await _emit("ADF_ANCHOR_DESIGNED", {
            "climax_intensity": anchor.climax.intensity,
            "climax_description": anchor.climax.description[:200],
            "setup_point_count": len(anchor.preconditions),
            "setup_points": [
                {
                    "id": pc.id,
                    "category": pc.category,
                    "description": pc.description,
                    "must_use_terms": pc.must_use_terms,
                }
                for pc in anchor.preconditions
            ],
            "emotion_flow_samples": [
                {"progress": s.progress, "register": s.register, "energy": s.energy}
                for s in anchor.emotion_curve.samples
            ],
        })

        # ============================================================
        # Phase 3: 定档（TIER_DECIDE，0 LLM）
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "TIER_DECIDE"})

        requested_tier = getattr(request, "tier", "auto")
        user_hint = getattr(request, "user_tier_hint", None)
        user_target_wc = getattr(request, "target_word_count", None)
        user_max_segments = getattr(request, "max_segments", 6)

        tier, tier_reason, auto_word_count, auto_max_segments = decide_tier(
            requested_tier=requested_tier,
            climax_intensity=anchor.climax.intensity,
            offset_from_volume_climax=spine.chapter_position.offset_from_volume_climax,
            user_tier_hint=user_hint,
        )
        target_word_count = user_target_wc or auto_word_count
        max_segments = min(user_max_segments, auto_max_segments)

        result.tier_decision = {
            "tier": tier,
            "reason": tier_reason,
            "climax_score": anchor.climax.intensity,
            "target_word_count": target_word_count,
            "max_segments": max_segments,
        }
        await _emit("TIER_DECIDED", {
            "tier": tier,
            "reason": tier_reason,
            "climax_score": anchor.climax.intensity,
            "target_word_count": target_word_count,
            "max_segments": max_segments,
        })

        # ============================================================
        # Phase 4: 正向流写作（FORWARD_FLOW，N 次 creative）★ 核心
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "FORWARD_FLOW"})

        try:
            segments, anchor = await write_chapter_segments(
                anchor=anchor,
                spine=spine,
                chapter=self.chapter,
                chapter_card=self.chapter_card,
                entities=self.entities,
                style_card=self.style_card,
                author_samples=self.author_samples,
                tier=tier,
                target_word_count=target_word_count,
                max_segments=max_segments,
                recorder=self.recorder,
                progress_callback=progress_callback,
                canon_context=self.canon_context,
                author_intent=self.author_intent,
                # V3.5：设定感知层数据
                locations=self.locations,
                assets=self.assets,
                relationships=self.relationships,
                worldview_text=self.worldview_text,
                genre=getattr(self.book, "genre", None),
            )
        except Exception as e:
            logger.exception(f"[ADF] Phase 4 正向流写作异常: {e}")
            segments = []
            result.degraded.append({"phase": "forward_flow", "reason": "exception", "detail": str(e)[:200]})

        result.segments = segments

        # 拼接完整正文
        final_text = "\n\n".join(s.text for s in segments if s.text)
        result.final_text = final_text

        if not final_text.strip():
            logger.error("[ADF] 正向流产出空正文，跳过审计与精修")
            result.audit.verdict = "fail"
            result.audit.spine_violations = ["正文为空"]
            result.stats = {
                "segment_count": len(segments),
                "word_count": 0,
                "setup_point_total": len(anchor.preconditions),
                "setup_point_landed": sum(1 for pc in anchor.preconditions if pc.landed),
            }
            return result

        # ============================================================
        # Phase 4.5: 去 AI 味剪枝（PRUNE，N 次 creative + 1 次 OOC 裁判）
        # ============================================================
        # 全章无条件触发：重构剪枝（破匀速句式/删逻辑过渡词/心理转物理），
        # 但保留叙事密度。precondition 安全网：误删 must_use_terms 则翻 landed=False
        # 交下游 Phase 5/6 补埋。OOC 安全线：角色崩坏则整章回退。
        # 失败不阻塞（仿 Phase 6 模式），保留未剪枝文本。
        await _emit("ADF_STAGE", {"stage": "PRUNE"})
        try:
            # 复用 segment_writer 的构建函数，保证剪枝用的角色/文风/样本
            # 与正文生成时注入的完全一致（OOC/文风红线基准一致）
            characters_setting = _build_characters_text(self.entities)
            style_contract = _build_style_contract(self.style_card)
            author_samples = _build_author_samples(self.author_samples)

            pruned_segments, pruned_text, prune_report = await run_prune_pass(
                segments=segments,
                anchor=anchor,
                characters_setting=characters_setting,
                style_contract=style_contract,
                author_samples=author_samples,
                recorder=self.recorder,
                progress_callback=progress_callback,
            )
            result.segments = pruned_segments
            result.final_text = pruned_text
            final_text = pruned_text  # 关键：同步本地变量，Phase 5 审计要读它
            if prune_report.ooc_triggered:
                result.degraded.append({
                    "phase": "prune",
                    "reason": "ooc_fallback",
                    "detail": f"OOC 安全线触发，整章回退未剪枝文本：{prune_report.ooc_issues}",
                })
            if prune_report.pruned_count > 0:
                logger.info(
                    f"[ADF] Phase 4.5 剪枝完成：{prune_report.pruned_count} 段重构，"
                    f"{len(prune_report.flipped_precondition_ids)} 个 precondition 关键词被误删交补埋"
                )
        except Exception as e:
            logger.warning(f"[ADF] Phase 4.5 剪枝异常（不阻塞）: {e}")
            result.degraded.append({"phase": "prune", "reason": "exception", "detail": str(e)[:200]})
            # 保留未剪枝的 segments/final_text（已在 302/306 行设置）

        # ============================================================
        # Phase 5: 锚点审计（ANCHOR_AUDIT，1 次 reasoning）
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "ANCHOR_AUDIT"})

        purpose = ""
        if self.chapter_card is not None:
            purpose = (getattr(self.chapter_card, "purpose", "") or "").strip()
        if not purpose:
            purpose = (getattr(self.chapter, "outline_text", "") or "")[:300]

        enable_audit = getattr(request, "enable_anchor_audit", True)
        if enable_audit:
            try:
                audit = await run_structure_check(
                    anchor=anchor,
                    spine=spine,
                    purpose=purpose,
                    tier=tier,
                    full_text=final_text,
                    recorder=self.recorder,
                )
            except Exception as e:
                logger.warning(f"[ADF] Phase 5 审计异常，降级 unaudited: {e}")
                from backend.services.workflows.adf.types import StructureCheck
                audit = StructureCheck(verdict="unaudited")
                result.degraded.append({"phase": "audit", "reason": "exception", "detail": str(e)[:200]})
        else:
            from backend.services.workflows.adf.types import StructureCheck
            audit = StructureCheck(verdict="unaudited")

        result.audit = audit
        await _emit("ADF_AUDIT", {
            "verdict": audit.verdict,
            "missing_setup_points": audit.missing_preconditions,
            "emotion_mismatches": audit.emotion_mismatches,
            "structure_issues": audit.spine_violations,
            "climax_score": audit.climax_score,
            "fix_targets": audit.refinement_targets,
        })

        # ============================================================
        # Phase 6: 条件补埋（REFINE，0-K 次 creative）
        # ============================================================
        enable_refine = getattr(request, "enable_refinement", True)
        if enable_refine and audit.verdict == "needs_refinement" and audit.refinement_targets:
            await _emit("ADF_STAGE", {"stage": "REFINE"})
            try:
                segments, refined_ids = await refine_missing_preconditions(
                    audit=audit,
                    anchor=anchor,
                    segments=segments,
                    style_card=self.style_card,
                    recorder=self.recorder,
                )
                # 重拼正文
                result.segments = segments
                result.final_text = "\n\n".join(s.text for s in segments if s.text)
                result.stats["refined_setup_points"] = refined_ids
                logger.info(f"[ADF] Phase 6 精修完成：补埋 {len(refined_ids)} 个 preconditions")
            except Exception as e:
                logger.warning(f"[ADF] Phase 6 精修异常（不阻塞）: {e}")
                result.degraded.append({"phase": "refine", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # 统计与结束
        # ============================================================
        result.stats.update({
            "segment_count": len(segments),
            "word_count": len(result.final_text),
            "setup_point_total": len(anchor.preconditions),
            "setup_point_landed": sum(1 for pc in anchor.preconditions if pc.landed),
            "tier": tier,
            "target_word_count": target_word_count,
            "climax_intensity": anchor.climax.intensity,
            "audit_climax_score": audit.climax_score,
            "audit_verdict": audit.verdict,
        })

        logger.info(
            f"[ADF] 工作流完成：{result.stats['segment_count']} 段，"
            f"{result.stats['word_count']} 字，"
            f"audit={audit.verdict}, "
            f"setup points {result.stats['setup_point_landed']}/{result.stats['setup_point_total']}"
        )
        return result

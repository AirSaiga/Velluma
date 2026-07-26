"""
BS-ADF（Beat-Slot Anchor-Driven Flow）工作流主类。

职责：BS-ADF 是 ADF 的并行引擎，替换 Phase 4（自由写作 → 槽位化流水线），
     复用 ADF 的 Phase 1-3 与 Phase 4.5-7。

Phase 编排（与 ADFWorkflow 平行，仅 Phase 4 自写）：
- Phase 1: 脉络轨构建（复用 build_story_context）
- Phase 2: 远端锚设计（复用 design_chapter_climax）
- Phase 3: 定档（复用 decide_tier）
- Phase 4: BS-ADF 槽位化流水线（build_beat_slots + enrich_slots + render_with_downgrade）
  - 4a: 构建槽位卡（纯算法）
  - 4b: 可选 LLM 扩写（enrich_slots）
  - 4c: 逐段渲染（render_with_downgrade，串行）
  - 4d: 降级追踪（连续失败产 DegradedBeat）
- Phase 4.5: 去 AI 味剪枝（复用 run_prune_pass）
- Phase 5: 锚点审计（复用 run_structure_check）
- Phase 6: 条件补埋（复用 refine_missing_preconditions）
- Phase 6.5: 缺失节拍补写（复用 patch_missing_beats）
- Phase 7: 一致性守卫（复用 run_consistency_guard）

设计要点：
- 不持有 DB session（工作流层约定；持久化由调用方负责）
- BSAdfWorkflow.__init__ 与 ADFWorkflow.__init__ 签名完全一致（route 层同样构造）
- 所有降级显式标记（Phase 6.5/7 失败不阻塞，记 result.degraded）
- Phase 4 产出的 BeatSlotCard 保留在 result.debug_info["beat_slots"]，供 Track B 暂停恢复
"""

import logging
from typing import Any, Callable, Dict, List, Optional

from backend.services.observability.run_recorder import RunRecorder
from backend.services.workflows.adf.story_context_builder import build_story_context
from backend.services.workflows.adf.climax_designer import design_chapter_climax
from backend.services.workflows.adf.tier_decider import decide_tier
from backend.services.workflows.adf.segment_writer import (
    _build_style_contract,
    _build_author_samples,
    _build_characters_text,
    _build_knowledge_constraints,
)
from backend.services.workflows.adf.structure_checker import run_structure_check
from backend.services.workflows.adf.refiner import refine_missing_preconditions
from backend.services.workflows.adf.pruner import run_prune_pass
from backend.services.workflows.adf.name_registry import (
    build_name_registry,
    registry_to_prompt_block,
)
from backend.services.workflows.adf.setting_resolver import (
    build_scene_setting_text,
    resolve_characters,
    resolve_hidden_constraints,
)
from backend.services.workflows.adf.state_tracker import (
    card_to_prompt_block,
    extract_state_card,
    SceneStateCard,
)
from backend.services.workflows.adf.types import (
    ChapterClimax,
    GenerationResult,
    StoryContext,
)
from backend.services.prompts.adf_prompts import (
    format_climax_anchor,
    format_emotion_curve,
)
from backend.services.workflows.bsadf.slot_builder import (
    build_beat_slots,
    enrich_slots,
)
from backend.services.workflows.bsadf.downgrade import render_with_downgrade
from backend.services.workflows.bsadf.types import (
    beat_slot_to_dict,
    BeatSlotCard,
    DegradedBeat,
)

logger = logging.getLogger(__name__)


class BSAdfWorkflow:
    """BS-ADF 工作流主类。

    使用模式（与 ADFWorkflow 完全一致）：
        workflow = BSAdfWorkflow(
            chapter=chapter, book=book, chapter_card=cc, entities=entities,
            style_card=sc, recorder=recorder, request=req,
            previous_summary=ps, rolling_summary=rs, open_hooks=oh,
        )
        result = await workflow.execute(progress_callback=cb)

    设计要点：
    - 不持有 DB session（工作流层约定；持久化由调用方负责）
    - 七个 Phase 顺序执行，每阶段产出可观测（recorder + progress_callback）
    - 所有降级显式标记
    - 与 ADFWorkflow 唯一差异：Phase 4 用 BS-ADF 自己的槽位化流水线
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
        pause_after_slot_build: bool = False,
    ) -> GenerationResult:
        """执行 BS-ADF 七个 Phase（Phase 4 用槽位化流水线）。

        Args:
            progress_callback: 进度回调，签名 (event: str, data: dict) -> Any
                事件类型：ADF_STAGE / ADF_SPINE_BUILT / ADF_ANCHOR_DESIGNED /
                TIER_DECIDED / BSADF_STAGE / BEAT_SLOTS_BUILT /
                BEAT_RENDER_PROGRESS / BEAT_DOWNGRADED / ADF_PROGRESS /
                ADF_PRECONDITION_LANDED / ADF_AUDIT / ADF_CONSISTENCY
            pause_after_slot_build: True 时跑到 Phase 4a 之后、4c 之前返回（Track B
                作者介入握手）。返回的 result.debug_info 含：
                paused=True / beat_slots / paused_spine / paused_anchor /
                paused_tier / paused_target_word_count / paused_max_segments。
                route 层据此暂存 _PENDING_BEAT_SLOTS，等 /confirm-beats 恢复。

        Returns:
            GenerationResult（debug_info 内含 beat_slots / degraded_beats 供 Track B）
        """
        result = GenerationResult()
        request = self.request

        async def _emit(event: str, data: dict) -> None:
            if progress_callback:
                try:
                    await progress_callback(event, data)
                except Exception as e:
                    logger.warning(f"[BSADF] progress_callback {event} 失败: {e}")

        # ============================================================
        # Phase 1: 脉络轨构建（SPINE_BUILDING）—— 与 ADF 一致
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
                logger.warning(f"[BSADF] Phase 1 脉络轨构建异常，降级空 spine: {e}")
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
        # Phase 2: 远端锚设计（ANCHOR_DESIGN）—— 与 ADF 一致
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
            logger.exception(f"[BSADF] Phase 2 远端锚设计异常: {e}")
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
        # Phase 3: 定档（TIER_DECIDE）—— 与 ADF 一致
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

        # 保存 tier_reason 供 Track B 暂停时重建 tier_decision（resume 不再算档）
        tier_reason_for_resume = tier_reason

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
        # Phase 4: BS-ADF 槽位化流水线 ★ 核心差异（自写）
        # ============================================================
        await _emit("BSADF_STAGE", {"stage": "SLOT_BUILD"})

        cards: List = []
        segments: List = []
        degraded_beats: List[DegradedBeat] = []

        try:
            # 4a. 构建槽位卡（纯算法）
            cards = build_beat_slots(
                anchor=anchor,
                spine=spine,
                total_segments=max_segments,
                target_word_count=target_word_count,
                chapter_number=getattr(self.chapter, "number", 1) or 1,
                locations=self.locations,
                assets=self.assets,
                chapter=self.chapter,
            )

            # 4b. 可选 LLM 扩写（enrichment，失败保留种子）
            enable_slot_enrichment = getattr(request, "enable_slot_enrichment", True)
            await enrich_slots(cards, recorder=self.recorder, enable=enable_slot_enrichment)

            await _emit("BEAT_SLOTS_BUILT", {
                "count": len(cards),
                "beat_ids": [c.beat_id for c in cards],
            })

        except Exception as e:
            logger.exception(f"[BSADF] Phase 4a/4b 槽位构建异常: {e}")
            result.degraded.append({
                "phase": "slot_pipeline",
                "reason": "exception",
                "detail": str(e)[:200],
            })

        # 保留槽位卡（无论是否暂停都写）
        result.debug_info["beat_slots"] = [beat_slot_to_dict(c) for c in cards]

        # ============================================================
        # Track B 暂停点：Phase 4a 之后、4c 之前
        # ============================================================
        if pause_after_slot_build:
            result.debug_info["paused"] = True
            # 把 resume_from_slots 所需的上下文塞进 debug_info（route 层据此暂存）
            result.debug_info["paused_spine"] = spine
            result.debug_info["paused_anchor"] = anchor
            result.debug_info["paused_tier"] = tier
            result.debug_info["paused_target_word_count"] = target_word_count
            result.debug_info["paused_max_segments"] = max_segments
            result.distal_anchor = anchor
            result.spine_track = spine
            result.tier_decision = {
                "tier": tier,
                "reason": tier_reason_for_resume,
                "climax_score": anchor.climax.intensity,
                "target_word_count": target_word_count,
                "max_segments": max_segments,
            }
            logger.info(
                f"[BSADF] Track B 暂停：{len(cards)} 张槽位卡已构建，等待作者编辑后 /confirm-beats 恢复"
            )
            return result

        # ============================================================
        # Phase 4c-7：渲染与后处理（共享方法，resume_from_slots 复用）
        # ============================================================
        await self._run_render_and_postprocess(
            result=result,
            cards=cards,
            spine=spine,
            anchor=anchor,
            tier=tier,
            target_word_count=target_word_count,
            max_segments=max_segments,
            progress_callback=progress_callback,
        )
        return result

    async def resume_from_slots(
        self,
        edited_cards: List[BeatSlotCard],
        spine: "StoryContext",
        anchor: "ChapterClimax",
        tier: str,
        target_word_count: int,
        max_segments: int,
        progress_callback: Optional[Callable[[str, dict], Any]] = None,
    ) -> GenerationResult:
        """Track B 恢复：从作者编辑后的槽位卡继续 Phase 4c-7。

        与 execute 共享 4c-7 逻辑（_run_render_and_postprocess），跳过 Phase 1-3 + 4a/b
        （已在前一请求完成，槽位卡由作者编辑后传入）。

        Args:
            edited_cards: 作者编辑后的全章槽位卡（覆盖服务端暂存的卡）
            spine: 前一请求（Track B 暂停时）保留的脉络轨
            anchor: 前一请求保留的远端锚
            tier: 前一请求的定档
            target_word_count: 前一请求的目标字数
            max_segments: 前一请求的最大段数
            progress_callback: 同 execute

        Returns:
            GenerationResult（与 execute 跑完全程等价，segments/final_text/audit/degraded 齐全）
        """
        result = GenerationResult()
        result.distal_anchor = anchor
        result.spine_track = spine
        result.tier_decision = {
            "tier": tier,
            "climax_score": anchor.climax.intensity,
            "target_word_count": target_word_count,
            "max_segments": max_segments,
        }
        result.debug_info["beat_slots"] = [beat_slot_to_dict(c) for c in edited_cards]

        async def _emit(event: str, data: dict) -> None:
            if progress_callback:
                try:
                    await progress_callback(event, data)
                except Exception as e:
                    logger.warning(f"[BSADF] resume progress_callback {event} 失败: {e}")

        await _emit("BSADF_STAGE", {"stage": "RENDER_RESUMED", "count": len(edited_cards)})

        await self._run_render_and_postprocess(
            result=result,
            cards=edited_cards,
            spine=spine,
            anchor=anchor,
            tier=tier,
            target_word_count=target_word_count,
            max_segments=max_segments,
            progress_callback=progress_callback,
        )
        return result

    async def _run_render_and_postprocess(
        self,
        result: GenerationResult,
        cards: List,
        spine: "StoryContext",
        anchor: "ChapterClimax",
        tier: str,
        target_word_count: int,
        max_segments: int,
        progress_callback: Optional[Callable[[str, dict], Any]] = None,
    ) -> None:
        """Phase 4c-7：渲染 + 后处理（execute Track A 与 resume_from_slots Track B 共享）。

        副作用：直接修改传入的 result（填充 segments/final_text/audit/degraded/stats 等）。
        Phase 4c 异常会记入 result.degraded 但不抛出（与原 execute 一致）。
        """
        request = self.request
        segments: List = []
        degraded_beats: List[DegradedBeat] = []

        async def _emit(event: str, data: dict) -> None:
            if progress_callback:
                try:
                    await progress_callback(event, data)
                except Exception as e:
                    logger.warning(f"[BSADF] progress_callback {event} 失败: {e}")

        # ============================================================
        # Phase 4c+4d: 逐段渲染（串行，带降级回退）
        # ============================================================
        await _emit("BSADF_STAGE", {"stage": "RENDER"})

        try:
            # 预构建渲染所需的共享上下文（每段都用，避免循环内重复构建）
            style_contract = _build_style_contract(self.style_card)
            emotion_curve_text = format_emotion_curve([
                {"progress": s.progress, "register": s.register, "energy": s.energy}
                for s in anchor.emotion_curve.samples
            ])
            scene_setting_text = build_scene_setting_text(
                self.entities, self.locations, self.assets, self.relationships,
            )
            name_registry = build_name_registry(
                self.entities, self.locations, self.assets, self.canon_context,
            )
            name_registry_block = registry_to_prompt_block(name_registry)
            genre = getattr(self.book, "genre", None)
            enable_state_tracker = getattr(request, "enable_state_tracker", True)

            state_card = SceneStateCard()  # 空，自举
            ROLLING_PREFIX_TAIL = 500

            for i, card in enumerate(cards):
                # 准备 rolling_prefix（前段尾段）
                if segments:
                    prev_text = segments[-1].text
                    rolling_prefix = (
                        prev_text[-ROLLING_PREFIX_TAIL:]
                        if len(prev_text) > ROLLING_PREFIX_TAIL
                        else prev_text
                    )
                else:
                    rolling_prefix = (
                        getattr(spine.entry_state, "last_scene_image", "")
                        or "（本章开篇）"
                    )

                state_card_block = (
                    card_to_prompt_block(state_card) if enable_state_tracker else ""
                )

                segment, card, degraded = await render_with_downgrade(
                    card=card,
                    rolling_prefix=rolling_prefix,
                    scene_setting_text=scene_setting_text,
                    name_registry_block=name_registry_block,
                    state_card_block=state_card_block,
                    emotion_curve_text=emotion_curve_text,
                    style_contract=style_contract,
                    genre=genre,
                    recorder=self.recorder,
                    prev_card_state=state_card if enable_state_tracker else None,
                    progress_callback=progress_callback,
                )
                segments.append(segment)
                if degraded is not None:
                    degraded_beats.append(degraded)

                # 段定稿后抽状态卡（非末段、启用 state_tracker、段非空）
                if (
                    enable_state_tracker
                    and segment.text.strip()
                    and i < len(cards) - 1
                ):
                    try:
                        state_card = await extract_state_card(
                            prev_card=state_card,
                            segment_text=segment.text,
                            registry=name_registry,
                            recorder=self.recorder,
                            segment_index=i,
                        )
                    except Exception as e:
                        logger.warning(
                            f"[BSAdfWorkflow] 状态卡抽取失败（不阻塞）：{e}"
                        )
        except Exception as e:
            logger.exception(f"[BSADF] Phase 4c 渲染异常: {e}")
            result.degraded.append({
                "phase": "slot_pipeline",
                "reason": "exception",
                "detail": str(e)[:200],
            })

        result.segments = segments
        result.final_text = "\n\n".join(s.text for s in segments if s.text.strip())
        result.degraded.extend([
            {
                "phase": "render",
                "beat_id": db.beat_id,
                "reason": db.reason,
                "attempts": db.attempts,
            }
            for db in degraded_beats
        ])

        # 降级记录（与槽位卡一同供 Track B / /rerender-beat）
        result.debug_info["degraded_beats"] = [
            {
                "beat_id": db.beat_id,
                "segment_index": db.segment_index,
                "reason": db.reason,
            }
            for db in degraded_beats
        ]

        final_text = result.final_text
        if not final_text.strip():
            logger.error("[BSADF] Phase 4 产出空正文，跳过审计与精修")
            result.audit.verdict = "fail"
            result.audit.spine_violations = ["正文为空"]
            result.stats = {
                "segment_count": len(segments),
                "word_count": 0,
                "setup_point_total": len(anchor.preconditions),
                "setup_point_landed": sum(1 for pc in anchor.preconditions if pc.landed),
                "slot_count": len(cards),
                "degraded_beat_count": len(degraded_beats),
            }
            return

        # ============================================================
        # Phase 4.5: 去 AI 味剪枝（PRUNE）—— 与 ADF 一致
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "PRUNE"})
        try:
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
                    f"[BSADF] Phase 4.5 剪枝完成：{prune_report.pruned_count} 段重构，"
                    f"{len(prune_report.flipped_precondition_ids)} 个 precondition 关键词被误删交补埋"
                )
        except Exception as e:
            logger.warning(f"[BSADF] Phase 4.5 剪枝异常（不阻塞）: {e}")
            result.degraded.append({"phase": "prune", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 5: 锚点审计（ANCHOR_AUDIT）—— 与 ADF 一致
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "ANCHOR_AUDIT"})

        purpose = ""
        if self.chapter_card is not None:
            purpose = (getattr(self.chapter_card, "purpose", "") or "").strip()
        if not purpose:
            purpose = (getattr(self.chapter, "outline_text", "") or "")[:300]

        enable_audit = getattr(request, "enable_anchor_audit", True)

        # 维度 6 输入：大纲节拍清单 + 代码级覆盖预判（0 LLM，suspect 模式）
        enable_beats = getattr(request, "enable_beat_coverage", True)
        outline_beats: List[str] = []
        beat_suspects: List[Dict[str, Any]] = []
        if enable_beats:
            try:
                from backend.services.workflows.adf.beat_patcher import (
                    parse_outline_beats,
                    score_beat_coverage,
                )
                outline_beats = parse_outline_beats(
                    getattr(self.chapter, "outline_text", "") or ""
                )
                if outline_beats:
                    beat_suspects = score_beat_coverage(outline_beats, final_text)
            except Exception as e:
                logger.warning(f"[BSADF] 大纲节拍解析失败（跳过节拍校验）: {e}")
                outline_beats, beat_suspects = [], []

        if enable_audit:
            try:
                audit = await run_structure_check(
                    anchor=anchor,
                    spine=spine,
                    purpose=purpose,
                    tier=tier,
                    full_text=final_text,
                    recorder=self.recorder,
                    outline_beats=outline_beats,
                    beat_suspects=beat_suspects,
                )
            except Exception as e:
                logger.warning(f"[BSADF] Phase 5 审计异常，降级 unaudited: {e}")
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
            "missing_beats": audit.missing_beats,
        })

        if outline_beats:
            result.stats["beat_coverage"] = {
                "total": len(outline_beats),
                "covered": len(outline_beats) - len(audit.missing_beats),
                "missing": len(audit.missing_beats),
                "patched": 0,
            }

        # ============================================================
        # Phase 6: 条件补埋（REFINE）—— 与 ADF 一致
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
                logger.info(f"[BSADF] Phase 6 精修完成：补埋 {len(refined_ids)} 个 preconditions")
            except Exception as e:
                logger.warning(f"[BSADF] Phase 6 精修异常（不阻塞）: {e}")
                result.degraded.append({"phase": "refine", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 6.5: 缺失节拍补写（BEAT_PATCH）—— 与 ADF 一致
        # ============================================================
        patchable_beats = [b for b in audit.missing_beats if b.get("patchable")]
        if enable_beats and enable_refine and patchable_beats:
            await _emit("ADF_STAGE", {"stage": "BEAT_PATCH"})
            try:
                from backend.services.workflows.adf.beat_patcher import patch_missing_beats
                try:
                    registry_block = registry_to_prompt_block(
                        build_name_registry(
                            self.entities, self.locations, self.assets, self.canon_context,
                        )
                    )
                except Exception as reg_err:
                    logger.warning(f"[BSADF] 节拍补写专名表构建失败（降级无专名约束）: {reg_err}")
                    registry_block = ""
                patch_result = await patch_missing_beats(
                    final_text=result.final_text,
                    missing_beats=audit.missing_beats,
                    purpose=purpose,
                    style_contract=_build_style_contract(self.style_card),
                    name_registry_block=registry_block,
                    recorder=self.recorder,
                )
                result.final_text = patch_result.new_text
                final_text = patch_result.new_text  # 同步本地变量，Phase 7 读它
                if "beat_coverage" in result.stats:
                    result.stats["beat_coverage"]["patched"] = len(patch_result.patched)
                if patch_result.patched:
                    logger.info(
                        f"[BSADF] Phase 6.5 节拍补写完成：补写 {len(patch_result.patched)} 个节拍"
                    )
                if patch_result.failed:
                    result.degraded.append({
                        "phase": "beat_patch",
                        "reason": "patch_incomplete",
                        "detail": "; ".join(
                            f"{f['beat'][:20]}({f['reason']})" for f in patch_result.failed
                        )[:200],
                    })
            except Exception as e:
                logger.warning(f"[BSADF] Phase 6.5 节拍补写异常（不阻塞）: {e}")
                result.degraded.append({"phase": "beat_patch", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 7: 一致性守卫（CONSISTENCY_GUARD）—— 与 ADF 一致
        # ============================================================
        enable_guard = getattr(request, "enable_consistency_guard", True)
        if enable_guard:
            await _emit("ADF_STAGE", {"stage": "CONSISTENCY_GUARD"})
            try:
                from backend.services.workflows.adf.consistency_guard import (
                    run_consistency_guard,
                )

                registry = build_name_registry(
                    self.entities, self.locations, self.assets, self.canon_context,
                )
                scene_setting_text = build_scene_setting_text(
                    self.entities, self.locations, self.assets, self.relationships,
                )
                knowledge_constraints = _build_knowledge_constraints(
                    self.canon_context,
                    resolve_hidden_constraints(
                        self.relationships, resolve_characters(self.entities),
                    ),
                )
                guard = await run_consistency_guard(
                    final_text=result.final_text,
                    registry=registry,
                    canon_context=self.canon_context,
                    scene_setting_text=scene_setting_text,
                    knowledge_constraints=knowledge_constraints,
                    anchor=anchor,
                    purpose=purpose,
                    recorder=self.recorder,
                    progress_callback=progress_callback,
                    enable_edit_verify=getattr(request, "enable_edit_verify", True),
                )
                result.final_text = guard.new_text
                result.stats["consistency"] = {
                    "issues_found": guard.issues_found,
                    "issues_fixed": guard.issues_fixed,
                    "surgeries_applied": guard.surgeries_applied,
                    "dedup_removed": [list(r) for r in guard.dedup_removed],
                    "rolled_back": guard.rolled_back,
                }
                result.degraded.extend(guard.degraded)
                await _emit("ADF_CONSISTENCY", {
                    "issues_found": guard.issues_found,
                    "issues_fixed": guard.issues_fixed,
                    "surgeries_applied": guard.surgeries_applied,
                    "dedup_removed": [list(r) for r in guard.dedup_removed],
                    "rolled_back": len(guard.rolled_back),
                })
                logger.info(
                    f"[BSADF] Phase 7 一致性守卫完成：发现 {guard.issues_found} 处，"
                    f"修复 {guard.issues_fixed} 处"
                )
            except Exception as e:
                logger.warning(f"[BSADF] Phase 7 一致性守卫异常（不阻塞，保留原文）: {e}")
                result.degraded.append({"phase": "consistency_guard", "reason": "exception", "detail": str(e)[:200]})

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
            # BS-ADF 专属统计
            "slot_count": len(cards),
            "degraded_beat_count": len(degraded_beats),
        })

        logger.info(
            f"[BSADF] 渲染+后处理完成：{result.stats['segment_count']} 段，"
            f"{result.stats['word_count']} 字，"
            f"audit={audit.verdict}, "
            f"setup points {result.stats['setup_point_landed']}/{result.stats['setup_point_total']}, "
            f"degraded_beats={len(degraded_beats)}"
        )

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
from typing import Any, Callable, Dict, List, Optional, Tuple

from backend.services.observability.run_recorder import RunRecorder
from backend.services.observability.run_trace import trace_event
from backend.services.workflows.adf.story_context_builder import build_story_context
from backend.services.workflows.adf.climax_designer import design_chapter_climax
from backend.services.workflows.adf.tier_decider import decide_tier
from backend.services.workflows.adf.segment_writer import (
    _build_style_contract,
    _build_author_samples,
    _build_characters_text,
    _build_knowledge_constraints,
    _build_compact_canon_hint,
    _build_presence_hint,
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
    enforce_outline_entities,
)
from backend.services.workflows.bsadf.downgrade import render_with_downgrade
from backend.services.workflows.bsadf.dde.decision_card_generator import (
    generate_chapter_decision_set,
)
from backend.services.workflows.bsadf.dde.slot_mutator import mutate_slot_cards
from backend.services.workflows.bsadf.dde.types import (
    ChapterDecisionSet,
    chapter_decision_set_to_dict,
)
from backend.services.workflows.bsadf.types import (
    beat_slot_to_dict,
    BeatSlotCard,
    DegradedBeat,
)

logger = logging.getLogger(__name__)


async def _extract_state_card_or_keep_old(
    state_card: SceneStateCard,
    segment_text: str,
    name_registry: Any,
    recorder: Optional[RunRecorder],
    segment_index: int,
    result: GenerationResult,
) -> SceneStateCard:
    """段定稿后抽新状态卡；失败显式记 result.degraded 并沿用旧卡。

    失败判定：extract_state_card 内部降级返回同一旧卡对象（is 判定），
    或返回一张全空废卡（替换旧卡等于静默丢状态）。
    真实事故：deepseek-v4-pro 忽略 reasoning 关闭参数，token 预算全被
    推理烧光，5 次抽取全部空输出——若无 degraded 记录，Loop 1 状态矛盾
    闸门整章裸奔且无人知晓。
    """
    try:
        new_card = await extract_state_card(
            prev_card=state_card,
            segment_text=segment_text,
            registry=name_registry,
            recorder=recorder,
            segment_index=segment_index,
        )
        if new_card is state_card or new_card.is_empty():
            result.degraded.append({
                "phase": "state_tracker",
                "reason": "extract_empty",
                "segment_index": segment_index,
                "detail": f"第 {segment_index + 1} 段状态卡抽取失败（空输出/废卡），沿用旧卡",
            })
            return state_card
        return new_card
    except Exception as e:
        logger.warning(f"[BSAdfWorkflow] 状态卡抽取异常（沿用旧卡，不阻塞）：{e}")
        result.degraded.append({
            "phase": "state_tracker",
            "reason": "extract_exception",
            "segment_index": segment_index,
            "detail": f"第 {segment_index + 1} 段状态卡抽取异常：{str(e)[:120]}",
        })
        return state_card


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
                TIER_DECIDED / BSADF_STAGE / BEAT_SLOTS_BUILT（载荷内嵌
                decision_set）/ DDE_AUTO_APPLIED（仅 Track A）/
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
        decision_set = ChapterDecisionSet()  # DDE 章节级剧情分叉（默认空=全章无岔路）
        # Track A/B 都生效：Track A 静默应用默认分支，Track B 随暂停一起给作者
        enable_dde = getattr(request, "enable_dde", True)

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

            # ===== NLE-ADF Loop 1：大纲自检 =====
            if getattr(self.request, "enable_outline_self_check", False):
                from backend.services.workflows.bsadf.outline_self_check import (
                    run_outline_self_check,
                )
                beat_slot_dicts_for_check = [beat_slot_to_dict(c) for c in cards]
                loop1_result = await run_outline_self_check(
                    outline_text=getattr(self.chapter, "outline_text", "") or "",
                    chapter_title=getattr(self.chapter, "title", "") or "",
                    beat_slots=beat_slot_dicts_for_check,
                    recorder=self.recorder,
                )
                await _emit("LOOP1_OUTLINE_CHECKED", {
                    "hard_facts": loop1_result.hard_facts,
                    "gaps": loop1_result.gaps,
                    "critique_pass": loop1_result.pass_,
                    "violations": loop1_result.violations,
                    "macro_gaps_for_dde": loop1_result.macro_gaps_for_dde,
                })
                if not hasattr(result, "debug_info") or result.debug_info is None:
                    result.debug_info = {}
                result.debug_info["loop1_result"] = {
                    "pass": loop1_result.pass_,
                    "violations": loop1_result.violations,
                    "macro_gaps_for_dde": loop1_result.macro_gaps_for_dde,
                    "degraded_reason": loop1_result.degraded_reason,
                }
                if loop1_result.macro_gaps_for_dde:
                    if "_loop1_macro_gaps" not in result.debug_info:
                        result.debug_info["_loop1_macro_gaps"] = []
                    result.debug_info["_loop1_macro_gaps"].extend(
                        loop1_result.macro_gaps_for_dde
                    )

            # 4b. 可选 LLM 扩写（enrichment，失败保留种子）
            # guard_context：幻觉闸门的授权上下文（本章大纲全文 + 高潮设计），
            # 扩写词含剧情级关键词且不在此上下文里 → 剥离（防超前变异幻觉）
            enable_slot_enrichment = getattr(request, "enable_slot_enrichment", True)
            guard_context = (
                (getattr(self.chapter, "outline_text", "") or "")
                + "\n"
                + (getattr(anchor.climax, "description", "") or "")
            )
            # 槽位扩写逐卡进度回调：每张卡开始扩写前 emit SLOT_ENRICH_PROGRESS，
            # 让前端实时看到"槽位扩写 3/6"（SLOT_BUILD 60s 沉默的根因修复）
            async def _enrich_progress(idx: int, total: int, beat_id: str) -> None:
                await _emit("SLOT_ENRICH_PROGRESS", {
                    "current": idx + 1,
                    "total": total,
                    "beat_id": beat_id,
                })

            await enrich_slots(
                cards,
                recorder=self.recorder,
                enable=enable_slot_enrichment,
                guard_context=guard_context,
                progress_callback=_enrich_progress,
            )

            # 4b 后置代码闸门：outline_beat 关键实体（书名/引文/角色名）
            # 必须物理映射进被 coverage 校验的槽位，不信任 prompt 软约束
            enforce_outline_entities(
                cards,
                known_names=[
                    getattr(e, "name", "") for e in self.entities
                ],
            )

            # 4b 后 DDE：章节级剧情分叉判断（全章 1×creative LLM，无岔路放行）
            # 时机保持在 Phase 4b 后——此时卡已 enrich，分支判断更准
            if enable_dde and cards:
                await _emit("BSADF_STAGE", {"stage": "BRANCH_CHECK"})
                try:
                    decision_set = await generate_chapter_decision_set(
                        chapter=self.chapter,
                        anchor=anchor,
                        spine=spine,
                        cards=cards,
                        recorder=self.recorder,
                    )
                except Exception as e:
                    logger.warning(f"[BSADF] DDE 章节分叉判断异常（降级无岔路放行）: {e}")
                    decision_set = ChapterDecisionSet()
                    result.degraded.append({
                        "phase": "dde",
                        "reason": "exception",
                        "detail": str(e)[:200],
                    })

            await _emit("BEAT_SLOTS_BUILT", {
                "count": len(cards),
                "beat_ids": [c.beat_id for c in cards],
                # Track A 渲染期卡片可见：带全量卡序列化（Track B 的 route 完整版
                # 会带 run_id 再发一次，前端据 run_id 区分只填卡 vs 进 beat_pending）
                "beat_slots": [beat_slot_to_dict(c) for c in cards],
                "decision_set": chapter_decision_set_to_dict(decision_set),
            })

        except Exception as e:
            logger.exception(f"[BSADF] Phase 4a/4b 槽位构建异常: {e}")
            result.degraded.append({
                "phase": "slot_pipeline",
                "reason": "exception",
                "detail": str(e)[:200],
            })

        # ============================================================
        # Track A 静默 DDE：有分支立即用 default_option 静默突变
        # （写 branch_directive，全程不暂停）；无分支同样上报
        # （has_story_branch=false），供前端展示"本章无岔路"
        # ============================================================
        if not pause_after_slot_build and enable_dde and cards:
            if decision_set.has_story_branch:
                mutate_slot_cards(
                    cards=cards,
                    decision_set=decision_set,
                    skipped=True,  # 静默应用：全部走 default_option（主路径）
                )
                logger.info(
                    f"[BSADF] Track A 静默应用 DDE 默认分支："
                    f"{[(n.beat_id, n.default_option) for n in decision_set.decision_nodes]}"
                )
            await _emit("DDE_AUTO_APPLIED", {
                "has_story_branch": decision_set.has_story_branch,
                "decision_set": chapter_decision_set_to_dict(decision_set),
                "applied": {
                    node.beat_id: node.default_option
                    for node in decision_set.decision_nodes
                },
            })

        # 保留槽位卡（无论是否暂停都写；Track A 静默突变后的快照含 branch_directive）
        result.debug_info["beat_slots"] = [beat_slot_to_dict(c) for c in cards]
        result.debug_info["decision_set"] = chapter_decision_set_to_dict(decision_set)
        # trace：槽位卡全量快照（enrichment 后、渲染前，debug 强制词/大纲分配用）
        trace_event("slots_built", cards=result.debug_info["beat_slots"])

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
        tier_reason: Optional[str] = None,
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
            tier_reason: 前一请求的定档理由（暂停时暂存，恢复后回填 tier_decision，
                供 Track B COMPLETE 载荷与 Track A 字段契约对齐）

        Returns:
            GenerationResult（与 execute 跑完全程等价，segments/final_text/audit/degraded 齐全）
        """
        result = GenerationResult()
        result.distal_anchor = anchor
        result.spine_track = spine
        result.tier_decision = {
            "tier": tier,
            "reason": tier_reason,
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
            # 写作期防线（对齐 ADF segment_writer）：Canon 事实 + 知识边界 + 在场提示
            canon_hint = _build_compact_canon_hint(self.canon_context)
            knowledge_constraints = _build_knowledge_constraints(
                self.canon_context,
                resolve_hidden_constraints(
                    self.relationships, resolve_characters(self.entities),
                ),
            )
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

                # 段渲染开始：点亮前端「渲染中」状态灯（rendered/degraded 由
                # render_with_downgrade 内部 emit，开始态此前无人发，状态灯恒死）
                await _emit("BEAT_RENDER_PROGRESS", {
                    "status": "rendering",
                    "beat_id": card.beat_id,
                    "segment_index": i,
                })

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
                    knowledge_constraints=knowledge_constraints,
                    presence_hint=_build_presence_hint(segments, name_registry),
                    canon_hint=canon_hint,
                    # 结局段豁免字数硬截断（结局完整性 > 字数预算）
                    is_final_segment=(i == len(cards) - 1),
                )
                segments.append(segment)
                if degraded is not None:
                    degraded_beats.append(degraded)

                # 段定稿后抽状态卡（非末段、启用 state_tracker、段非空）；
                # 失败（空输出/废卡/异常）显式记 result.degraded，见 helper
                if (
                    enable_state_tracker
                    and segment.text.strip()
                    and i < len(cards) - 1
                ):
                    state_card = await _extract_state_card_or_keep_old(
                        state_card=state_card,
                        segment_text=segment.text,
                        name_registry=name_registry,
                        recorder=self.recorder,
                        segment_index=i,
                        result=result,
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
        # 渲染后刷新槽位卡快照（status/render_attempts 已在渲染中更新，
        # 覆盖 Phase 4a 的构建时快照，供 /rerender-beat 与 DB 持久化拿到真实状态）
        result.debug_info["beat_slots"] = [beat_slot_to_dict(c) for c in cards]
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
        patched_beat_texts: set = set()  # 补写成功的节拍原文（rescue_needed 计算用）
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
                    # 补写段与正文同一文风/设定标准：禁词注入 + 代码闸门，
                    # canon 注入防发明设定（"二百年记录 vs 三十年前"事故）。
                    # 禁词不再逐卡携带（BeatSlotCard.ban_words 已删除），
                    # 传 None 由 beat_patcher 内部回退 DEFAULT_BAN_LIST 常量
                    ban_words=None,
                    canon_hint=_build_compact_canon_hint(self.canon_context),
                )
                result.final_text = patch_result.new_text
                final_text = patch_result.new_text  # 同步本地变量，Phase 7 读它
                patched_beat_texts = set(patch_result.patched)
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
        # Phase 6.5 收尾：rescue_needed 标记（路线 C 降级救援）
        # ============================================================
        # 审计判 missing 且未被补写救回的节拍 → 映射回槽位卡，随 COMPLETE 输出。
        # 前端分镜工作台据此高亮"核心转折未落地"的内联救援卡（作者微调后 /rerender-beat）。
        rescue_needed: list = []
        if enable_beats and audit.missing_beats:
            for mb in audit.missing_beats:
                beat_text = (mb.get("beat") or "").strip()
                if not beat_text or beat_text in patched_beat_texts:
                    continue
                # 按 outline_beat 子串匹配映射回槽位卡（双向包含容忍 LLM 改写）
                matched_card = None
                for c in cards:
                    ob = (c.outline_beat or "").strip()
                    if ob and (ob in beat_text or beat_text in ob):
                        matched_card = c
                        break
                rescue_needed.append({
                    "beat_id": matched_card.beat_id if matched_card else "",
                    "segment_index": matched_card.segment_index if matched_card else -1,
                    "outline_beat": beat_text,
                    "core_plot_event": matched_card.core_plot_event if matched_card else "",
                    "reason": "core_plot_event_not_landed",
                })
        result.debug_info["rescue_needed"] = rescue_needed
        if rescue_needed:
            await _emit("RESCUE_NEEDED", {"items": rescue_needed})
            logger.info(
                f"[BSADF] Phase 6.5 救援标记：{len(rescue_needed)} 个节拍核心转折未落地 "
                f"→ {[r['beat_id'] or r['outline_beat'][:12] for r in rescue_needed]}"
            )

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
        # Phase 7.5: 终稿残句门禁（SENTENCE_INTEGRITY）
        # 0 LLM 扫描残缺句（"白霆的了一下"类），命中则定点修复
        # （每条 1×creative + 三重安全网，不过网保留原句）。
        # 渲染→wash→PRUNE→审计→一致性守卫都不查句子完整性，这是最后一道。
        # ============================================================
        try:
            from backend.services.workflows.sentence_integrity import (
                repair_sentence_defects,
                scan_sentence_defects,
            )

            sentence_defects = scan_sentence_defects(result.final_text)
            if sentence_defects:
                trace_event(
                    "sentence_defects_found",
                    count=len(sentence_defects),
                    defects=[{
                        "type": d["type"],
                        "position": d["position"],
                        "sentence": d["sentence"][:80],
                    } for d in sentence_defects],
                )
                registry = build_name_registry(
                    self.entities, self.locations, self.assets, self.canon_context,
                )
                fixed_text, fixed_count, fix_failures = await repair_sentence_defects(
                    text=result.final_text,
                    defects=sentence_defects,
                    registered_names=sorted(registry.all_surface_forms),
                    recorder=self.recorder,
                )
                result.final_text = fixed_text
                final_text = fixed_text  # 同步本地变量（统计收尾读它）
                result.stats["sentence_defects_found"] = len(sentence_defects)
                if fixed_count:
                    result.stats["sentence_defects_fixed"] = fixed_count
                if fix_failures:
                    result.degraded.append({
                        "phase": "sentence_integrity",
                        "reason": "fix_failed",
                        "detail": "; ".join(
                            f"{f['sentence'][:20]}({f['reason']})" for f in fix_failures
                        )[:200],
                    })
                    await _emit("SENTENCE_DEFECTS_UNFIXED", {"items": fix_failures})
        except Exception as e:
            logger.warning(f"[BSADF] Phase 7.5 残句门禁异常（不阻塞，保留原文）: {e}")
            result.degraded.append({"phase": "sentence_integrity", "reason": "exception", "detail": str(e)[:200]})

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

    # ============================================================
    # NLE-ADF 步进运行时支持（Phase 4 单段渲染 + 4.5-7.5 后处理可分片调用）
    # ============================================================
    # 设计要点：
    # - render_one 与 _run_render_and_postprocess 的 for 循环体保持同样的渲染语义，
    #   但接受外部传入的 locked_segments / state_card_chain，使其可在 stepping_loop
    #   中被逐段调用、段间挂起。
    # - run_post_step_phases 复用 Phase 4.5-7.5 的全部调用，独立于 execute（不破坏
    #   批量模式）；接受少量代码重复以降低回归风险（推荐方案）。
    # - execute_stepping 是 execute(pause_after_slot_build=True) 的语义别名，供路由层
    #   显式发起步进运行（跑到 Phase 4b 暂停，返回含 beat_slots 的 GenerationResult）。

    def _build_render_context(self, anchor: "ChapterClimax") -> Dict[str, Any]:
        """预构建渲染所需的共享上下文（每段都用，避免循环内重复构建）。

        与 _run_render_and_postprocess 中的预构建块对齐；抽出来供 render_one 复用。
        """
        from backend.services.workflows.adf.setting_resolver import (
            build_scene_setting_text, resolve_characters, resolve_hidden_constraints,
        )
        from backend.services.workflows.adf.name_registry import (
            build_name_registry, registry_to_prompt_block,
        )
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
        canon_hint = _build_compact_canon_hint(self.canon_context)
        knowledge_constraints = _build_knowledge_constraints(
            self.canon_context,
            resolve_hidden_constraints(
                self.relationships, resolve_characters(self.entities),
            ),
        )
        genre = getattr(self.book, "genre", None)
        return {
            "style_contract": style_contract,
            "emotion_curve_text": emotion_curve_text,
            "scene_setting_text": scene_setting_text,
            "name_registry": name_registry,
            "name_registry_block": name_registry_block,
            "canon_hint": canon_hint,
            "knowledge_constraints": knowledge_constraints,
            "genre": genre,
        }

    async def render_one(
        self,
        card: BeatSlotCard,
        segment_index: int,
        locked_segments: List,
        state_card_chain: List,
        run: Any = None,
    ) -> Tuple[Any, Optional[DegradedBeat]]:
        """单段渲染（步进模式可恢复调用）。

        从 locked_segments 构建 rolling_prefix，从 state_card_chain 末尾取滚动状态卡，
        调 render_with_downgrade 渲染单段。若传入 run，则段正文定稿后通过 run 推
        BEAT_TEXT_CHUNK 事件（与批量模式一致的正文可见性），并更新滚动状态卡链。

        与 _run_render_and_postprocess 的 for 循环体语义对齐：
        - rolling_prefix：前段尾 500 字 / 开篇 entry_state
        - state_card_block：当前滚动状态卡
        - render_with_downgrade：相同的全部渲染参数 + presence_hint + is_final_segment
        - 段后状态卡抽取：步进模式无法预知是否末段，总是抽取（调用方决定是否用）；
          抽取失败沿用旧卡（步进模式不写 result.degraded，避免无谓字段）

        Args:
            card: 待渲染的槽位卡（in-place 更新 status/render_attempts）
            segment_index: 段序号（与 card.segment_index 应一致；此处冗余传以明示）
            locked_segments: 已锁死的段列表（用于 rolling_prefix + presence_hint）
            state_card_chain: 滚动状态卡链；末元素为当前激活卡，新卡追加到末尾
            run: SteppingRun（可选；非 None 时推 BEAT_TEXT_CHUNK 并维护 state_card_chain）

        Returns:
            (SegmentResult, degraded_beat) — degraded_beat 为 None 表示渲染成功
        """
        from backend.services.workflows.adf.state_tracker import (
            card_to_prompt_block, extract_state_card,
        )

        # 重建/复用渲染上下文（spine/anchor 由 execute_stepping 暂存到 workflow 上）
        anchor = getattr(self, "_paused_anchor", None) or self._last_anchor_for_stepping()
        if anchor is None:
            # 兜底：无 anchor 时无法渲染（execute_stepping 未调用过）
            raise RuntimeError("render_one 需先经 execute_stepping 暂存 anchor/spine")

        ctx = self._build_render_context(anchor)
        enable_state_tracker = getattr(self.request, "enable_state_tracker", True)

        ROLLING_PREFIX_TAIL = 500
        if locked_segments:
            prev_text = locked_segments[-1].text
            rolling_prefix = (
                prev_text[-ROLLING_PREFIX_TAIL:]
                if len(prev_text) > ROLLING_PREFIX_TAIL
                else prev_text
            )
        else:
            spine = getattr(self, "_paused_spine", None)
            rolling_prefix = (
                getattr(getattr(spine, "entry_state", None), "last_scene_image", "")
                or "（本章开篇）"
            )

        state_card = state_card_chain[-1] if state_card_chain else SceneStateCard()
        state_card_block = card_to_prompt_block(state_card) if enable_state_tracker else ""

        segment, card, degraded = await render_with_downgrade(
            card=card,
            rolling_prefix=rolling_prefix,
            scene_setting_text=ctx["scene_setting_text"],
            name_registry_block=ctx["name_registry_block"],
            state_card_block=state_card_block,
            emotion_curve_text=ctx["emotion_curve_text"],
            style_contract=ctx["style_contract"],
            genre=ctx["genre"],
            recorder=self.recorder,
            prev_card_state=state_card if enable_state_tracker else None,
            knowledge_constraints=ctx["knowledge_constraints"],
            presence_hint=_build_presence_hint(locked_segments, ctx["name_registry"]),
            canon_hint=ctx["canon_hint"],
            # 步进模式无法预知末段；保守地按非末段处理（字数硬截断仍生效）
            is_final_segment=False,
        )

        # 段正文定稿后推 BEAT_TEXT_CHUNK（与批量模式对齐的正文可见性）
        if run is not None and getattr(segment, "text", ""):
            try:
                from backend.services.workflows.bsadf.stepping_runtime import _emit_event
                await _emit_event(run, "BEAT_TEXT_CHUNK", {
                    "beat_id": card.beat_id,
                    "segment_index": segment_index,
                    "text": segment.text,
                })
            except Exception as e:
                logger.warning(f"[BSADF] render_one BEAT_TEXT_CHUNK 推送失败（不阻塞）: {e}")

        # 段后状态卡抽取（步进模式总是抽取，调用方决定是否消费）
        if enable_state_tracker and segment.text.strip():
            try:
                new_card = await extract_state_card(
                    prev_card=state_card,
                    segment_text=segment.text,
                    registry=ctx["name_registry"],
                    recorder=self.recorder,
                    segment_index=segment_index,
                )
                # 与批量模式一致：空输出/废卡沿用旧卡（不静默丢状态）
                if new_card is not state_card and not new_card.is_empty():
                    state_card_chain.append(new_card)
                else:
                    if not state_card_chain:
                        state_card_chain.append(state_card)
            except Exception as e:
                logger.warning(f"[BSADF] render_one 状态卡抽取异常（沿用旧卡，不阻塞）：{e}")
                if not state_card_chain:
                    state_card_chain.append(state_card)

        return segment, degraded

    def _last_anchor_for_stepping(self) -> Optional["ChapterClimax"]:
        """execute_stepping 暂存的 anchor 兜底取值（_paused_anchor 已 set 时不会到这）。"""
        return getattr(self, "_paused_anchor", None)

    async def run_post_step_phases(
        self,
        final_text: str,
        locked_segments: List,
        run: Any = None,
    ) -> Dict[str, Any]:
        """Phase 4.5-7.5 后处理（步进模式末段锁死后调用）。

        复用 _run_render_and_postprocess 的 Phase 4.5-7.5 调用链（PRUNE/AUDIT/
        REFINE/BEAT_PATCH/CONSISTENCY/SENTENCE），独立实现以避免批量模式回归。
        输入是步进循环已锁死的段列表与拼接好的 final_text；返回 dict 供 stepping_loop
        发 COMPLETE。

        Args:
            final_text: 已锁死段拼接的全文（"\n\n".join）
            locked_segments: 已锁死的 SegmentResult 列表
            run: SteppingRun（可选；非 None 时从 run.cards 取槽位卡做 rescue_needed 映射）

        Returns:
            dict: {
                "text": 终稿正文（经 Phase 4.5-7.5 处理）,
                "engine": "bsadf",
                "stats": 统计,
                "degraded_beats": 降级段列表,
                "audit": 审计结论 dict,
                "rescue_needed": 未落地节拍,
                "final_text": 终稿正文（冗余字段，与 stepping_loop COMPLETE 载荷对齐）,
            }
        """
        result = GenerationResult()
        request = self.request
        segments: List = list(locked_segments)
        # 步进模式降级段：从 locked_segments 反查（text 为空即降级）；cards 可用时
        # 以 card.status=='degraded' 为准
        cards = list(getattr(run, "cards", []) or []) if run is not None else []
        degraded_beats: List[DegradedBeat] = [
            DegradedBeat(
                beat_id=getattr(c, "beat_id", ""),
                segment_index=getattr(c, "segment_index", idx),
                reason="render_degraded",
                attempts=getattr(c, "render_attempts", 0),
                card_snapshot=c,
            )
            for idx, c in enumerate(cards)
            if getattr(c, "status", "") == "degraded"
        ]

        # anchor/spine 由 execute_stepping 暂存到 workflow 上
        anchor = getattr(self, "_paused_anchor", None)
        spine = getattr(self, "_paused_spine", None)
        tier_info = getattr(self, "_paused_tier_info", {}) or {}
        tier = tier_info.get("tier", "auto")
        target_word_count = tier_info.get("target_word_count", 0) or 0
        max_segments = tier_info.get("max_segments", len(cards) or len(segments))

        result.segments = segments
        result.final_text = final_text
        result.distal_anchor = anchor or ChapterClimax()
        result.spine_track = spine or StoryContext()
        result.tier_decision = {
            "tier": tier,
            "reason": tier_info.get("reason", ""),
            "climax_score": getattr(getattr(anchor, "climax", None), "intensity", 0) if anchor else 0,
            "target_word_count": target_word_count,
            "max_segments": max_segments,
        }

        async def _emit(event: str, data: dict) -> None:
            # 步进模式后处理事件推给 run（若有），否则静默
            if run is not None:
                try:
                    from backend.services.workflows.bsadf.stepping_runtime import _emit_event
                    await _emit_event(run, event, data)
                except Exception as e:
                    logger.warning(f"[BSADF] run_post_step_phases _emit {event} 失败: {e}")

        if not final_text.strip():
            logger.error("[BSADF] run_post_step_phases 收到空正文，跳过审计与精修")
            result.audit.verdict = "fail"
            result.audit.spine_violations = ["正文为空"]
            result.stats = {
                "segment_count": len(segments),
                "word_count": 0,
                "slot_count": len(cards),
                "degraded_beat_count": len(degraded_beats),
            }
            return {
                "text": final_text,
                "engine": "bsadf",
                "stats": result.stats,
                "degraded_beats": [],
                "audit": {"verdict": "fail"},
                "rescue_needed": [],
                "final_text": final_text,
            }

        # ============================================================
        # Phase 4.5: 去 AI 味剪枝（PRUNE）
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
                progress_callback=None,
            )
            result.segments = pruned_segments
            result.final_text = pruned_text
            final_text = pruned_text
            segments = pruned_segments
            if prune_report.ooc_triggered:
                result.degraded.append({
                    "phase": "prune",
                    "reason": "ooc_fallback",
                    "detail": f"OOC 安全线触发，整章回退未剪枝文本：{prune_report.ooc_issues}",
                })
        except Exception as e:
            logger.warning(f"[BSADF] run_post_step_phases Phase 4.5 剪枝异常（不阻塞）: {e}")
            result.degraded.append({"phase": "prune", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 5: 锚点审计（ANCHOR_AUDIT）
        # ============================================================
        await _emit("ADF_STAGE", {"stage": "ANCHOR_AUDIT"})

        purpose = ""
        if self.chapter_card is not None:
            purpose = (getattr(self.chapter_card, "purpose", "") or "").strip()
        if not purpose:
            purpose = (getattr(self.chapter, "outline_text", "") or "")[:300]

        enable_audit = getattr(request, "enable_anchor_audit", True)
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

        if enable_audit and anchor is not None and spine is not None:
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
                logger.warning(f"[BSADF] run_post_step_phases Phase 5 审计异常，降级 unaudited: {e}")
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
        # Phase 6: 条件补埋（REFINE）
        # ============================================================
        enable_refine = getattr(request, "enable_refinement", True)
        if enable_refine and audit.verdict == "needs_refinement" and audit.refinement_targets and anchor is not None:
            await _emit("ADF_STAGE", {"stage": "REFINE"})
            try:
                segments, refined_ids = await refine_missing_preconditions(
                    audit=audit,
                    anchor=anchor,
                    segments=segments,
                    style_card=self.style_card,
                    recorder=self.recorder,
                )
                result.segments = segments
                result.final_text = "\n\n".join(s.text for s in segments if s.text)
                result.stats["refined_setup_points"] = refined_ids
            except Exception as e:
                logger.warning(f"[BSADF] run_post_step_phases Phase 6 精修异常（不阻塞）: {e}")
                result.degraded.append({"phase": "refine", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 6.5: 缺失节拍补写（BEAT_PATCH）
        # ============================================================
        patched_beat_texts: set = set()
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
                    ban_words=None,
                    canon_hint=_build_compact_canon_hint(self.canon_context),
                )
                result.final_text = patch_result.new_text
                final_text = patch_result.new_text
                patched_beat_texts = set(patch_result.patched)
                if "beat_coverage" in result.stats:
                    result.stats["beat_coverage"]["patched"] = len(patch_result.patched)
            except Exception as e:
                logger.warning(f"[BSADF] run_post_step_phases Phase 6.5 节拍补写异常（不阻塞）: {e}")
                result.degraded.append({"phase": "beat_patch", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 6.5 收尾：rescue_needed 标记
        # ============================================================
        rescue_needed: list = []
        if enable_beats and audit.missing_beats:
            for mb in audit.missing_beats:
                beat_text = (mb.get("beat") or "").strip()
                if not beat_text or beat_text in patched_beat_texts:
                    continue
                matched_card = None
                for c in cards:
                    ob = (getattr(c, "outline_beat", "") or "").strip()
                    if ob and (ob in beat_text or beat_text in ob):
                        matched_card = c
                        break
                rescue_needed.append({
                    "beat_id": getattr(matched_card, "beat_id", "") if matched_card else "",
                    "segment_index": getattr(matched_card, "segment_index", -1) if matched_card else -1,
                    "outline_beat": beat_text,
                    "core_plot_event": getattr(matched_card, "core_plot_event", "") if matched_card else "",
                    "reason": "core_plot_event_not_landed",
                })
        result.debug_info["rescue_needed"] = rescue_needed

        # ============================================================
        # Phase 7: 一致性守卫（CONSISTENCY_GUARD）
        # ============================================================
        enable_guard = getattr(request, "enable_consistency_guard", True)
        if enable_guard and anchor is not None:
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
                    progress_callback=None,
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
            except Exception as e:
                logger.warning(f"[BSADF] run_post_step_phases Phase 7 一致性守卫异常（不阻塞，保留原文）: {e}")
                result.degraded.append({"phase": "consistency_guard", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # Phase 7.5: 终稿残句门禁（SENTENCE_INTEGRITY）
        # ============================================================
        try:
            from backend.services.workflows.sentence_integrity import (
                repair_sentence_defects,
                scan_sentence_defects,
            )
            sentence_defects = scan_sentence_defects(result.final_text)
            if sentence_defects:
                registry = build_name_registry(
                    self.entities, self.locations, self.assets, self.canon_context,
                )
                fixed_text, fixed_count, fix_failures = await repair_sentence_defects(
                    text=result.final_text,
                    defects=sentence_defects,
                    registered_names=sorted(registry.all_surface_forms),
                    recorder=self.recorder,
                )
                result.final_text = fixed_text
                result.stats["sentence_defects_found"] = len(sentence_defects)
                if fixed_count:
                    result.stats["sentence_defects_fixed"] = fixed_count
                if fix_failures:
                    result.degraded.append({
                        "phase": "sentence_integrity",
                        "reason": "fix_failed",
                        "detail": "; ".join(
                            f"{f['sentence'][:20]}({f['reason']})" for f in fix_failures
                        )[:200],
                    })
        except Exception as e:
            logger.warning(f"[BSADF] run_post_step_phases Phase 7.5 残句门禁异常（不阻塞，保留原文）: {e}")
            result.degraded.append({"phase": "sentence_integrity", "reason": "exception", "detail": str(e)[:200]})

        # ============================================================
        # 统计收尾
        # ============================================================
        result.stats.update({
            "segment_count": len(segments),
            "word_count": len(result.final_text),
            "setup_point_total": len(getattr(anchor, "preconditions", []) or []) if anchor else 0,
            "setup_point_landed": sum(
                1 for pc in (getattr(anchor, "preconditions", []) or []) if pc.landed
            ) if anchor else 0,
            "tier": tier,
            "target_word_count": target_word_count,
            "climax_intensity": getattr(getattr(anchor, "climax", None), "intensity", 0) if anchor else 0,
            "audit_climax_score": audit.climax_score,
            "audit_verdict": audit.verdict,
            "slot_count": len(cards),
            "degraded_beat_count": len(degraded_beats),
        })

        logger.info(
            f"[BSADF] run_post_step_phases 完成：{result.stats['segment_count']} 段，"
            f"{result.stats['word_count']} 字，audit={audit.verdict}"
        )

        return {
            "text": result.final_text,
            "engine": "bsadf",
            "stats": result.stats,
            "degraded_beats": [
                {
                    "beat_id": db.beat_id,
                    "segment_index": db.segment_index,
                    "reason": db.reason,
                }
                for db in degraded_beats
            ],
            "audit": {
                "verdict": audit.verdict,
                "missing_setup_points": audit.missing_preconditions,
                "missing_beats": audit.missing_beats,
            },
            "rescue_needed": rescue_needed,
            "final_text": result.final_text,
        }

    async def execute_stepping(
        self,
        progress_callback: Optional[Callable[[str, dict], Any]] = None,
    ) -> GenerationResult:
        """发起步进运行：跑到 Phase 4b 暂停，返回含 beat_slots 的 GenerationResult。

        语义等同 execute(pause_after_slot_build=True)，但语义上明确表达"步进模式"，
        并把后处理所需的 anchor/spine/tier 暂存到 workflow 实例（供 render_one /
        run_post_step_phases 复用）。

        Returns:
            GenerationResult（debug_info 内含 beat_slots / decision_set / emotion_curve_samples；
            distal_anchor / spine_track / tier_decision 已填充）
        """
        result = await self.execute(
            progress_callback=progress_callback,
            pause_after_slot_build=True,
        )
        # 暂存后处理上下文（render_one / run_post_step_phases 复用）
        self._paused_spine = result.spine_track
        self._paused_anchor = result.distal_anchor
        self._paused_tier_info = dict(result.tier_decision)
        # 情绪曲线采样（供前端 beat_pending 面板展示情绪轨迹）
        try:
            self._emotion_curve_samples = [
                {"progress": s.progress, "register": s.register, "energy": s.energy}
                for s in (result.distal_anchor.emotion_curve.samples or [])
            ]
            result.debug_info["emotion_curve_samples"] = self._emotion_curve_samples
        except Exception:
            result.debug_info["emotion_curve_samples"] = []
        return result

    async def ingest_memory(self, segment: Any, card: Any, segment_index: int, **kw) -> Dict[str, Any]:
        """Loop 3 记忆倒灌（NLE-ADF）：从段正文抽取涌现实体/关系/地点/大纲补遗。

        调用点：stepping_runtime 在 BEAT_LOCKED 前（enable_memory_ingestion=True 时）。
        保守回写：仅累计 outline_addenda 到 _accumulated_addenda（不破坏性改写），
        其余字段通过 BEAT_LOCKED.extracted_facts 透传给前端/后处理。
        失败返回空 dict（不阻塞 pass）。
        """
        if not getattr(self.request, "enable_memory_ingestion", False):
            return {}
        try:
            from backend.services.workflows.bsadf.memory_ingestion import (
                extract_emergent_facts,
            )
            prev_summary = getattr(self, "_last_state_card_text", "") or ""
            facts = await extract_emergent_facts(
                segment_text=getattr(segment, "text", ""),
                beat_id=getattr(card, "beat_id", ""),
                prev_state_summary=prev_summary,
                recorder=self.recorder,
            )
            if not facts.is_empty():
                addenda_list = getattr(self, "_accumulated_addenda", [])
                addenda_list.extend(facts.outline_addenda)
                self._accumulated_addenda = addenda_list
            return facts.to_dict()
        except Exception as e:
            logger.warning(f"[BSADF] ingest_memory 异常（不阻塞）: {e}")
            return {}


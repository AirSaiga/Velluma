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
起草模块 - 章节正文生成的核心工作流。

职责：
- 提供统一的起草入口 execute_draft_stage
- 支持三档工作流路径（疾速/均衡/堡垒）
- 协调思考层和正文层的生成流程

工作流架构：
```
输入: Story Beats → 路由选择 → 三档路径之一 → 输出: BeatDraftResult[]

三档路径：
- TIER_1_FAST:     跳过思考层，直接并行生成正文
- TIER_2_STANDARD: 轻量级思考 + 串行正文生成
- TIER_3_FORTRESS: 完整思考层(MCTS) + 串行正文生成 + QC检查
```

依赖关系：
- drafting_thinking.py: Scene Intent 和 Subconscious 生成
- drafting_prose.py:    正文生成（三种并发策略）
- drafting_utils.py:    工具函数

使用方式：
    from backend.services.workflows.drafting import execute_draft_stage, BeatDraftResult
    results = await execute_draft_stage(chapter, book, beats, ...)
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Callable

from pydantic import BaseModel

from backend.schemas import (
    DynamicContext,
    DraftingFeatureFlags,
    WorkflowTier,
)
from backend.services.utils.logging import get_runtime_logger
from backend.services.orchestration.tier_mapper import map_tension_to_workflow_tier
from backend.services.workflows.utils import clean_llm_output
from backend.services.workflows.context_blocks import (
    render_character_cards_block,
    render_open_hooks_block,
    render_world_snapshot_block,
    render_golden_snippets_block,
    render_style_blacklist_block,
    render_author_intent_block,
)

logger = get_runtime_logger(__name__)

# 从子模块导入具体实现
from backend.services.workflows.drafting_thinking import (
    _call_llm_with_stats,
    _generate_scene_intent_batch,
    _generate_subconscious_batch,
    _generate_lightweight_subconscious,
    _generate_intent_and_sketch_batch,
    _build_beat_hooks,
)
# CP1.0 死代码清理：drafting_prose.py 已删除，
# 活路径函数 quick_qc / extract_tail / clamp_tokens 迁入 drafting_utils.py
from backend.services.workflows.drafting_utils import (
    quick_qc as _quick_qc,
    _extract_tail,
    _clamp_tokens,
)

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


class BeatDraftResult(BaseModel):
    """
    Beat 生成结果数据结构。

    Attributes:
        beat_id: Beat 唯一标识
        beat_index: Beat 在章节中的位置索引（从1开始）
        scene_intent: Scene Intent 分析结果
        subconscious_thought: 角色潜意识/内心独白
        draft_chunk: 生成的小说正文
        prompts: 调试用的提示词历史列表
        mcts_rollout: MCTS 三分支推演记录
    """
    beat_id: str
    beat_index: int
    scene_intent: dict
    subconscious_thought: str
    draft_chunk: str
    prompts: List[dict] = []
    mcts_rollout: Optional[list] = None


async def execute_draft_stage(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    assets: Optional[List[Any]] = None,  #
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    workflow_tier: Optional[WorkflowTier] = None,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    recorder: Optional[Any] = None,
    previous_world_snapshot: Optional[Any] = None,
    author_intent: Optional[str] = None,
    sketch_segments: Optional[List[str]] = None,
    use_context_engine: bool = True,
    style_card: Optional[Any] = None,
    chapter_card: Optional[Any] = None,
) -> List[BeatDraftResult]:
    """
    V4.1 智能路由起草阶段主入口。

    V4.1 路由策略（Per-Beat 自动分配）：
    - 不再整章统一走一条路径，而是根据每个 Beat 的 pacing_type 和 weight
      自动推断最适合的 tier（Fast/Standard/Fortress）
    - Fast Beat (pacing=Fast / weight<=2): 极简 prompt，跳过 QC，灵气优先
    - Standard Beat (默认): 轻量思考 + 标准 QC
    - Fortress Beat (pacing=Slow / weight>=4): 更严格的质量控制

    所有 Beat 共享同一个串行 Rolling Prefix 链，确保跨 tier 的连贯性。

    Args:
        chapter: 章节对象
        book: 书籍对象
        entities: 角色实体列表
        relationships: 关系列表
        beats: Story beats 数据
        open_hooks: 开放的伏笔列表
        word_count: 目标字数
        previous_summary: 前情摘要
        relevant_memories: 相关记忆列表
        locations: 地点列表
        enable_qc: 是否启用质量控制
        feature_flags: 功能标志
        physical_state_lock: 物理状态锁
        entity_spatial_ledger: 实体空间台账
        chapter_assets_schema: 章节资产模式
        workflow_tier: 工作流层级（覆盖自动检测）
        stats_callback: LLM 统计回调
        reasoning_config: 推理配置
        progress_callback: 进度回调

    Returns:
        List[BeatDraftResult]: 每个 beat 的生成结果
    """
    if not beats:
        return []

    flags = feature_flags or DraftingFeatureFlags()

    # 确定章节默认工作流层级（作为 per-beat 推断的 fallback）
    effective_tier = workflow_tier

    if not effective_tier and chapter:
        tension_level = getattr(chapter, 'tension_level', None)
        if tension_level and isinstance(tension_level, int) and 1 <= tension_level <= 5:
            effective_tier = map_tension_to_workflow_tier(tension_level)
            logger.info(f"[Draft Stage] 从 chapter.tension_level={tension_level} 映射到默认 tier {effective_tier}")

    if not effective_tier and beats:
        effective_tier = beats[0].get("workflow_tier")

    if not effective_tier:
        effective_tier = flags.workflow_tier

    logger.info(f"[Draft Stage] V4.1 Per-Beat 智能路由启动，默认 tier: {effective_tier}，共 {len(beats)} 个 Beats")

    # V4.1: 统一路径，per-beat 自动分配 tier
    return await _execute_unified_path(
        chapter=chapter, book=book, entities=entities, relationships=relationships,
        beats=beats, open_hooks=open_hooks,
        word_count=word_count, previous_summary=previous_summary,
        relevant_memories=relevant_memories, locations=locations, assets=assets,
        enable_qc=enable_qc, feature_flags=flags,
        physical_state_lock=physical_state_lock,
        entity_spatial_ledger=entity_spatial_ledger,
        chapter_assets_schema=chapter_assets_schema,
        workflow_tier=effective_tier,
        stats_callback=stats_callback, reasoning_config=reasoning_config,
        progress_callback=progress_callback,
        recorder=recorder,
        previous_world_snapshot=previous_world_snapshot,
        author_intent=author_intent,
        sketch_segments=sketch_segments,
        use_context_engine=use_context_engine,
        style_card=style_card,
        chapter_card=chapter_card,
    )


# =============================================================================
# V4.1 Per-Beat Tier 推断
# =============================================================================

def infer_beat_tier(beat: dict, chapter_tier: str) -> str:
    """
    基于 Beat 元数据推断最适合的工作流层级。

    规则（从强到弱）：
    - pacing_type="Slow" 或 weight >= 4 → TIER_3_FORTRESS（需要精细打磨）
    - pacing_type="Fast" 或 weight <= 2 → TIER_1_FAST（轻快处理，灵气优先）
    - 其他 → 使用章节默认 tier

    Args:
        beat: StoryBeat 字典，包含 pacing_type、weight 等字段
        chapter_tier: 章节默认 tier（fallback）

    Returns:
        str: "TIER_1_FAST" | "TIER_2_STANDARD" | "TIER_3_FORTRESS"
    """
    pacing = beat.get("pacing_type", "Medium")
    weight = beat.get("weight", 3)

    if pacing == "Slow" or weight >= 4:
        return "TIER_3_FORTRESS"
    if pacing == "Fast" or weight <= 2:
        return "TIER_1_FAST"
    return chapter_tier


# =============================================================================
# V4.1 统一执行路径（Per-Beat 自动分配）
# =============================================================================

async def _generate_beat_with_failfast(
    engine: Any,
    beat: dict,
    beat_index: int,
    previous_tail: str,
    sketch_segment: Optional[str],
    physical_state_lock: str,
    tier: str,
    target_words: int,
    base_temperature: float,
    stage_name: str,
    enable_fail_fast: bool,
    style_cliche_threshold: int,
    book: Any,
    pov_character: str,
    stats_callback: Optional[Callable] = None,
    recorder: Optional[Any] = None,
    fail_fast_max_attempts: int = 2,
    enable_fortress_dual_candidate: bool = False,
) -> str:
    """CP1.4：用 ContextEngine + fail-fast 包装生成单拍正文。

    业务流程：
    1. 用 engine.build_draft_prompt 组装 prompt（P0/P1/P1'/P2 四级布局）
    2. enable_fail_fast=False → 单次生成（Fast tier 灵气优先）
    3. enable_fail_fast=True → execute_generation_with_retry 包装：
       - 每轮重新组装 prompt（pending_hint 作为 extra_instruction 注入 P2 末尾）
       - 命中阻断级问题（红线/AI 腔超阈值）按类别调温重试
       - 默认 ≤2 轮
    4. CP4.4：tier=TIER_3_FORTRESS 且 enable_fortress_dual_candidate=True →
       走双候选并行生成 + 代码级优选（蓝图 §4.6.2），成本 ×2，默认关闭
    """
    from backend.services.workflows.fail_fast import (
        execute_generation_with_retry, build_draft_validator,
    )

    # 构造 validate 闭包（仅 enable_fail_fast=True 时用）
    validate = None
    if enable_fail_fast:
        try:
            validate = build_draft_validator(
                beat=beat, book=book, pov_character=pov_character,
                style_cliche_threshold=style_cliche_threshold,
            )
        except Exception as e:
            logger.warning(f"[Unified Path] build_draft_validator 失败，跳过 fail-fast: {e}")
            validate = None

    max_attempts = fail_fast_max_attempts if (enable_fail_fast and validate) else 1

    # 构造 generate_once 闭包：每次调用都用 engine 重组 prompt
    async def generate_once(temp: float, hint: str) -> str:
        system_prompt, user_prompt = engine.build_draft_prompt(
            beat=beat,
            beat_index=beat_index,
            previous_tail=previous_tail,
            sketch_segment=sketch_segment,
            physical_state_lock=physical_state_lock,
            extra_instruction=hint,
            tier=tier,
            target_words=target_words,
        )
        return await _call_llm_with_stats(
            stage=stage_name,
            system_prompt=system_prompt, user_prompt=user_prompt,
            temperature=temp, max_tokens=_clamp_tokens(target_words),
            beat_index=beat_index, stats_callback=stats_callback,
            model_type="creative",
            recorder=recorder,
        )

    # CP4.4：Fortress 双候选路径（蓝图 §4.6.2，默认关闭）
    if (
        tier == "TIER_3_FORTRESS"
        and enable_fortress_dual_candidate
        and engine is not None
    ):
        from backend.services.workflows.fortress_candidate import (
            generate_and_pick_dual_candidates,
        )
        try:
            result = await generate_and_pick_dual_candidates(
                generate_once=generate_once,
                validate=validate,
                beat_index=beat_index,
                fail_fast_max_attempts=max_attempts,
                initial_temperature=base_temperature,
                stage_name=stage_name,
                recorder=recorder,
            )
            return result.winner_text
        except Exception as e:
            logger.warning(
                f"[Fortress] Beat {beat_index} 双候选路径异常，降级单候选 fail-fast: {e}"
            )
            if recorder is not None:
                recorder.record_degraded(
                    stage=f"fortress.beat_{beat_index}",
                    reason="dual_path_exception",
                    action="fallback_single_fail_fast",
                    model_slot="creative",
                    detail=f"{type(e).__name__}: {str(e)[:200]}",
                )
            # 异常降级到下方单候选路径

    # 单候选 fail-fast 路径（默认）
    chunk, _ = await execute_generation_with_retry(
        generate_once=generate_once,
        validate=validate,
        max_attempts=max_attempts,
        beat_number=beat_index,
        initial_temperature=base_temperature,
        strategy_name=stage_name,
        recorder=recorder,
    )
    return chunk


async def _execute_unified_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    assets: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    workflow_tier: Optional[str] = None,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    recorder: Optional[Any] = None,
    previous_world_snapshot: Optional[Any] = None,
    author_intent: Optional[str] = None,
    sketch_segments: Optional[List[str]] = None,
    use_context_engine: bool = True,
    style_card: Optional[Any] = None,
    chapter_card: Optional[Any] = None,
) -> List[BeatDraftResult]:
    """
    V4.1 统一起草路径：所有 Beat 串行生成，per-beat 自动选择 prompt 和 QC 策略。

    CP1.4 升级：
    - use_context_engine=True（默认）：用 ContextEngine 组装 P0/P1/P1'/P2 四级布局
      （跨拍前缀字节级稳定，吃 DeepSeek prompt 缓存）
    - use_context_engine=False：回退到 Phase 0 T4 的 _build_fast/standard_path_prompt
    - Standard/Fortress tier 启用 fail-fast 重试（CP1.1 设施）
    - sketch_segments 注入 P2（CP1.2 segments 输出）

    特点：
    - 共享统一的 Rolling Prefix 链，跨 tier 连贯性最佳
    - 统一生成 Scene Intent + Subconscious（所有 beats），Fast beats 在 prose 阶段忽略
    - Fast Beat: 极简 prompt，跳过 QC 与 fail-fast，temp=0.75
    - Standard Beat: 标准 prompt + 轻量 QC + fail-fast（默认 2 轮），temp=0.75
    - Fortress Beat: 标准 prompt + 增强 QC + fail-fast（加严阈值），temp=0.7
    """
    logger.info("[Unified Path] 启动 V4.1 Per-Beat 统一起草路径...")
    flags = feature_flags or DraftingFeatureFlags()

    # CP1.4：ContextEngine 初始化（本章一次，P0+P1 在 __init__ 冻结）
    # CP2.3e：透传 style_card + chapter_card（由 stream_handler 加载后传入）
    engine = None
    if use_context_engine:
        try:
            from backend.services.context.engine import ContextEngine
            engine = ContextEngine(
                book=book, chapter=chapter, entities=entities,
                relationships=relationships, open_hooks=open_hooks,
                previous_world_snapshot=previous_world_snapshot,
                author_intent=author_intent,
                relevant_memories=relevant_memories,
                style_card=style_card,
                chapter_card=chapter_card,
            )
            logger.info(
                f"[Unified Path] ContextEngine 已启用 "
                f"(P0={len(engine._p0_block)}字, P1={len(engine._p1_chapter_block)}字, "
                f"style_card={'有' if style_card else '无'}, chapter_card={'有' if chapter_card else '无'})"
            )
        except Exception as e:
            logger.warning(
                f"[Unified Path] ContextEngine 初始化失败，回退到 Phase 0 prompt builder: {e}"
            )
            engine = None

    # 1. Per-Beat 推断 tier
    beat_tiers = [infer_beat_tier(beat, workflow_tier or "TIER_2_STANDARD") for beat in beats]
    tier_summary = {}
    for t in beat_tiers:
        tier_summary[t] = tier_summary.get(t, 0) + 1
    logger.info(f"[Unified Path] Per-beat tier 分配: {tier_summary}")

    # 2. 统一生成 Scene Intent + Subconscious（所有 beats，使用合并 batch）
    logger.info("[Unified Path] 统一生成 Scene Intent + Emotional Sketch...")
    try:
        scene_intent_results, subconscious_results, intent_sketch_prompts = await _generate_intent_and_sketch_batch(
            beats=beats, chapter=chapter, open_hooks=open_hooks,
            stats_callback=stats_callback, reasoning_config=reasoning_config,
            recorder=recorder,
        )
    except Exception as e:
        logger.error(f"[Unified Path] 合并生成失败: {e}")
        scene_intent_results = [{"intent_label": "默认", "goal": beat.get("summary", "")} for beat in beats]
        subconscious_results = ["" for _ in beats]
        intent_sketch_prompts = [[] for _ in beats]

    # 验证数组长度一致性
    if len(scene_intent_results) != len(beats) or len(subconscious_results) != len(beats):
        logger.error(f"[Unified Path] 结果数组长度不匹配: beats={len(beats)}, scene_intent={len(scene_intent_results)}, subconscious={len(subconscious_results)}")
        scene_intent_results = scene_intent_results[:len(beats)] + [{"intent_label": "默认", "goal": beats[i].get("summary", "")} for i in range(len(scene_intent_results), len(beats))]
        subconscious_results = subconscious_results[:len(beats)] + ["" for _ in range(len(subconscious_results), len(beats))]

    # 3. 串行生成正文（带 Rolling Prefix，per-beat 选择 prompt）
    results: List[BeatDraftResult] = []
    previous_tail = ""
    current_physical_lock = physical_state_lock or ""

    for i, beat in enumerate(beats):
        beat_tier = beat_tiers[i]
        beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
        target_words = beat.get("word_count_target") or beat.get("target_words", max(200, word_count // max(1, len(beats))))

        scene_intent = scene_intent_results[i] if i < len(scene_intent_results) else {"intent_label": "默认", "goal": beat.get("summary", "")}
        subconscious = subconscious_results[i] if i < len(subconscious_results) else ""

        # CP1.2：取本拍对应的 sketch_segment（按 beat_index 对齐）
        sketch_seg = None
        if sketch_segments and i < len(sketch_segments):
            sketch_seg = sketch_segments[i]

        # 根据 tier 选择温度、QC 策略、fail-fast 阈值
        if beat_tier == "TIER_1_FAST":
            temperature = 0.75
            do_qc = False
            enable_fail_fast = False
            style_cliche_threshold = 2
            stage_name = "unified_fast_prose"
        elif beat_tier == "TIER_3_FORTRESS":
            temperature = 0.7
            do_qc = enable_qc
            enable_fail_fast = True
            style_cliche_threshold = 1  # Fortress 加严：AI 腔阈值降到 1
            stage_name = "unified_fortress_prose"
        else:
            temperature = 0.75
            do_qc = enable_qc
            enable_fail_fast = True
            style_cliche_threshold = 2
            stage_name = "unified_standard_prose"

        # ============ CP1.4：生成正文（ContextEngine + fail-fast 包装） ============
        pov_character = beat.get("pov_character", "") or ""

        if engine is not None:
            # 主路径：ContextEngine 组装 prompt + fail-fast 包装
            response = await _generate_beat_with_failfast(
                engine=engine,
                beat=beat,
                beat_index=i + 1,
                previous_tail=previous_tail,
                sketch_segment=sketch_seg,
                physical_state_lock=current_physical_lock,
                tier=beat_tier,
                target_words=target_words,
                base_temperature=temperature,
                stage_name=stage_name,
                enable_fail_fast=enable_fail_fast,
                style_cliche_threshold=style_cliche_threshold,
                book=book,
                pov_character=pov_character,
                stats_callback=stats_callback,
                recorder=recorder,
                fail_fast_max_attempts=getattr(flags, "fail_fast_max_attempts", 2),
                # CP4.4：透传 Fortress 双候选开关（蓝图 §4.6.2，默认关闭）
                enable_fortress_dual_candidate=getattr(flags, "enable_fortress_dual_candidate", False),
            )
            # engine 路径不单独记录 prompt 历史（由 stats_callback/recorder 记）
            system_prompt, user_prompt = "", ""  # 占位，下方 prompts_history 简化
        else:
            # 回退路径：Phase 0 T4 的内联 prompt builder
            if beat_tier == "TIER_1_FAST":
                system_prompt, user_prompt = _build_fast_path_prompt(
                    chapter=chapter, book=book, beat=beat,
                    previous_tail=previous_tail, target_words=target_words,
                    previous_summary=previous_summary if i == 0 else None,
                    physical_state_lock=current_physical_lock,
                    entities=entities, open_hooks=open_hooks,
                    previous_world_snapshot=previous_world_snapshot if i == 0 else None,
                    author_intent=author_intent,
                )
            else:
                system_prompt, user_prompt = _build_standard_path_prompt(
                    chapter=chapter, book=book, beat=beat,
                    scene_intent=scene_intent,
                    subconscious=subconscious,
                    previous_tail=previous_tail,
                    physical_state_lock=current_physical_lock,
                    target_words=target_words,
                    entities=entities, open_hooks=open_hooks,
                    previous_world_snapshot=previous_world_snapshot if i == 0 else None,
                    author_intent=author_intent,
                )
            response = await _call_llm_with_stats(
                stage=stage_name,
                system_prompt=system_prompt, user_prompt=user_prompt,
                temperature=temperature, max_tokens=_clamp_tokens(target_words),
                beat_index=i + 1, stats_callback=stats_callback,
                model_type="creative",
                recorder=recorder,
            )

        chunk_text = clean_llm_output(response).strip()

        # QC 检查（长度/结构异常修复，与 fail-fast 互补）
        if do_qc:
            chunk_text, _ = await _quick_qc(
                prose_text=chunk_text, beat=beat, beat_index=i + 1,
                chapter=chapter, book=book, entities=entities,
                relationships=relationships,
                target_words=target_words,
            )

        # 更新 Rolling Prefix
        previous_tail = _extract_tail(chunk_text, max_chars=300)

        # 更新物理状态锁
        current_exit = beat.get("exit_state", "")
        if current_exit and current_exit != "未指定":
            current_physical_lock = f"{beat.get('pov_character', '主角')}当前态势（Beat {i+1} 结束）：{current_exit}"

        prompts_history = [{
            "stage": stage_name, "beat_index": i + 1,
            "system_prompt": system_prompt, "user_prompt": user_prompt,
        }]
        if i < len(intent_sketch_prompts) and intent_sketch_prompts[i]:
            prompts_history.extend(intent_sketch_prompts[i])

        results.append(BeatDraftResult(
            beat_id=beat_id, beat_index=i + 1,
            scene_intent=scene_intent,
            subconscious_thought=subconscious,
            draft_chunk=chunk_text, prompts=prompts_history, mcts_rollout=None,
        ))

        if progress_callback:
            progress_callback(i + 1, len(beats), f"Beat {i+1} ({beat_tier}) 完成")

    logger.info(f"[Unified Path] 统一路径生成完成，共 {len(results)} 个 Beats")
    return results




# =============================================================================
# Prompt 构建函数
# =============================================================================

def _build_fast_path_prompt(
    chapter: Any,
    book: Any,
    beat: dict,
    previous_tail: str,
    target_words: int,
    previous_summary: Optional[str] = None,
    physical_state_lock: str = "",
    entities: Optional[List[Any]] = None,
    open_hooks: Optional[List[dict]] = None,
    previous_world_snapshot: Optional[Any] = None,
    author_intent: Optional[str] = None,
) -> tuple[str, str]:
    """V4.1 Fast-Path: 自由创作版 Prompt。

    保留极简约束（只防世界观污染和硬红线），给 LLM 最大的创作自由。
    相比旧版，增加了 Rolling Prefix 支持和基本情境信息。

    Phase 0 T4：新增 entities/open_hooks/previous_world_snapshot/author_intent
    修复调研报告病灶 4（角色卡/伏笔/快照/作者意图未注入）。
    """
    pov_character = beat.get("pov_character", "主角")
    location = beat.get("location", "未指定")
    summary = beat.get("summary", "")
    red_lines = beat.get("red_lines", [])
    book_genre = getattr(book, 'genre', None) or "通用小说"

    red_lines_text = "；".join(red_lines) if red_lines else "无"

    # 极简 system prompt：只保留身份 + 3 条 P0 底线
    system_prompt = f"""你是小说家。请根据下文情境续写正文。

底线（不可违反）：
① 本书是【{book_genre}】，严禁题材污染。
② 红线：{red_lines_text}
③ 只写【{pov_character}】能感知到的内容。

直接输出正文，不要解释，不要 Markdown。目标约 {target_words} 字。"""

    # user prompt：提供必要情境 + 前文衔接 + 自由创作引导
    continuity = ""
    if previous_tail:
        continuity = f"【前文衔接】\n{previous_tail}\n"

    previous_context = ""
    if previous_summary:
        prev_tail = previous_summary[-300:] if len(previous_summary) > 300 else previous_summary
        previous_context = f"【前情回顾】\n{prev_tail}\n"

    physical_context = ""
    if physical_state_lock:
        physical_context = f"【角色状态】\n{physical_state_lock}\n"

    # Phase 0 T4：上下文增强段（角色卡/伏笔/快照/作者意图/金句/黑名单）
    context_blocks = []
    context_blocks.append(render_author_intent_block(author_intent))
    context_blocks.append(render_character_cards_block(entities))
    context_blocks.append(render_open_hooks_block(open_hooks))
    context_blocks.append(render_world_snapshot_block(previous_world_snapshot))
    if book is not None:
        context_blocks.append(render_golden_snippets_block(getattr(book, 'golden_snippets', None) or []))
        context_blocks.append(render_style_blacklist_block(getattr(book, 'style_blacklist', None) or []))
    context_section = "".join(b for b in context_blocks if b)

    user_prompt = f"""{continuity}{previous_context}{physical_context}{context_section}
【情境】
角色：{pov_character}
场景：{location}
剧情：{summary}

请续写正文。自由地写，不要拘泥于格式，让故事自己流动。"""

    return system_prompt, user_prompt


def _build_standard_path_prompt(
    chapter: Any,
    book: Any,
    beat: dict,
    scene_intent: dict,
    subconscious: str,
    previous_tail: str,
    physical_state_lock: str,
    target_words: int,
    entities: Optional[List[Any]] = None,
    open_hooks: Optional[List[dict]] = None,
    previous_world_snapshot: Optional[Any] = None,
    author_intent: Optional[str] = None,
) -> tuple[str, str]:
    """V4.0 Standard-Path: 构建均衡流的 Prompt。

    Phase 0 T4：新增 entities/open_hooks/previous_world_snapshot/author_intent。
    """
    pov_character = beat.get("pov_character", "主角")
    location = beat.get("location", "未指定")
    summary = beat.get("summary", "")

    continuity = ""
    if previous_tail:
        continuity = f"\n【前文衔接】必须无缝衔接：{previous_tail}\n"

    physical_context = ""
    if physical_state_lock:
        physical_context = f"\n【物理状态锁】{physical_state_lock}\n"

    # Phase 0 T4：上下文增强段
    context_blocks = []
    context_blocks.append(render_author_intent_block(author_intent))
    context_blocks.append(render_character_cards_block(entities))
    context_blocks.append(render_open_hooks_block(open_hooks))
    context_blocks.append(render_world_snapshot_block(previous_world_snapshot))
    if book is not None:
        context_blocks.append(render_golden_snippets_block(getattr(book, 'golden_snippets', None) or []))
        context_blocks.append(render_style_blacklist_block(getattr(book, 'style_blacklist', None) or []))
    context_section = "".join(b for b in context_blocks if b)

    system_prompt = f"""你是专业小说写手。请根据以下信息生成小说正文。

【章节背景】{getattr(chapter, 'chapter_name', f'第{getattr(chapter, "chapter_number", 1)}章')}
【角色视角】{pov_character}
【场景地点】{location}{continuity}{physical_context}

【场景意图】{scene_intent.get('goal', summary)}
【内心独白】{subconscious}

要求：
1. 将内心独白转化为具象化的动作、对话和环境描写
2. 直接输出小说正文，不要解释
3. 字数约 {target_words} 字
4. 保持叙事连贯性
{context_section}"""

    user_prompt = f"【剧情目标】{summary}\n\n请生成以上内容的小说正文："

    return system_prompt, user_prompt



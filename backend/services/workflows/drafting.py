# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
起草模块 - V2.5 认知流式生成 (Cognitive Streaming) 实现。

职责：提供基于"潜意识-正文"双层架构 + 动态认知组件的章节内容生成功能。

核心架构：
- 双模型路由：逻辑推理模型(Reasoning) vs 创意生成模型(Creative)
- 混合流水线：Scene Intent + Subconscious 并行生成，Prose Draft 串行滑动窗口生成
- Rolling Prefix：Beat n 接收 Beat n-1 的末尾 300 字符作为上下文
- V2.5 新增认知组件：
  - Entity State Lock (物理边界锁定)：防幻觉边界
  - Emotional Scratchpad (情绪暂存器)：性格微演变
  - Fail-Fast Micro-Review (即时断言)：防错重试机制

主要功能：
- execute_draft_stage: 主入口，执行完整的混合流水线
- _generate_subconscious_batch: 并行生成潜意识层
- _generate_scene_intent_batch: 并行生成场景意图
- _generate_prose_serial_v25: V2.5 串行生成正文（Rolling Prefix + 认知组件）
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable
from pydantic import BaseModel

# 配置模块级日志记录器
logger = logging.getLogger(__name__)

from backend.schemas import (
    DynamicContext, 
    DraftingFeatureFlags, 
    MicroReviewResult,
    DynamicStateUpdateResult,  # V2.5+ NEW
    CharacterPhysicalState,  # V2.5+ NEW: 用于 entity_spatial_ledger
    WorkflowTier,  # V3.0 NEW
    map_tension_to_workflow_tier,  # V3.0 NEW
)
from backend.services.prompts import (
    build_scene_intent_prompt,
    parse_scene_intent_result,
    build_subconscious_prompt,
    build_prose_draft_prompt,
    build_prose_draft_prompt_v25,
    build_micro_review_prompt,
    build_emotional_update_prompt,
    build_chunk_review_prompt,
    build_chunk_refine_prompt,
    # V2.5+ NEW
    build_dynamic_state_update_prompt,
)
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output

# =============================================================================
# LLM 调用统计回调类型定义
# =============================================================================
# 设计意图：允许外部（如 agentic_workflow）注入统计回调，统一追踪 LLM 调用次数和耗时
# 使用方式：
#   - 外部传入 callback: Callable[[str, float, bool, Optional[int]], None]
#   - 参数：stage_name(阶段名), elapsed_seconds(耗时), success(是否成功), beat_index(Beat索引,可选)
LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


async def _call_llm_with_stats(
    stage: str,
    *,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    system_prompt: str = "",
    user_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    response_format: Optional[dict] = None,
    top_p: float = 1.0,
    beat_index: Optional[int] = None,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,  # 推理模式配置
) -> str:
    """
    带统计追踪的 LLM 调用包装器。
    
    职责：在调用 call_llm 的同时，通过回调函数记录调用统计信息。
    
    Args:
        stage: 阶段标识符（如 "scene_intent", "subconscious", "prose_draft"）
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        temperature: 温度参数
        max_tokens: 最大 token 数
        response_format: 响应格式（如 JSON 模式）
        top_p: Top-p 采样参数
        beat_index: Beat 索引（用于按 Beat 统计）
        stats_callback: 统计回调函数，若为 None 则跳过统计
        reasoning_config: 推理模式配置（OpenRouter Reasoning Tokens 支持）
    
    Returns:
        str: LLM 生成的文本内容
    """
    start_time = time.perf_counter()
    success = True
    try:
        return await call_llm(
            api_key=api_key,
            base_url=base_url,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            top_p=top_p,
            reasoning_config=reasoning_config,
        )
    except Exception:
        success = False
        raise
    finally:
        if stats_callback:
            elapsed = time.perf_counter() - start_time
            stats_callback(stage, elapsed, success, beat_index)


class BeatDraftResult(BaseModel):
    """
    Beat 生成结果数据结构。
    
    职责：封装单个 Beat 的完整生成结果，包括潜意识层和正文层。
    
    Attributes:
        beat_id: Beat 唯一标识
        beat_index: Beat 在章节中的位置索引（从1开始）
        scene_intent: Scene Intent 分析结果（目标/风险/约束）
        subconscious_thought: 角色的潜意识/内心独白网络（50-100字）
        draft_chunk: 生成的小说正文
        prompts: 调试用的提示词历史列表
        mcts_rollout: 完整的 MCTS 三分支推演记录（Risk 5 可观测性）
    """
    beat_id: str
    beat_index: int
    scene_intent: dict
    subconscious_thought: str
    draft_chunk: str
    prompts: List[dict] = []
    mcts_rollout: Optional[list] = None  # MCTS 可观测性（Risk 5 修复）


async def execute_draft_stage(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    workflow_tier: Optional[WorkflowTier] = None,  # V3.0 NEW
    stats_callback: LLMStatsCallback = None,  # LLM 调用统计回调（可选）
    reasoning_config: Optional[dict] = None,  # 推理模式配置（OpenRouter Reasoning Tokens）
) -> List[BeatDraftResult]:
    """
    V3.0 智能路由起草阶段主入口。
    
    职责：根据 workflow_tier 动态选择执行路径，实现算力资源的智能分配。
    
    V3.0 路由策略：
    - TIER_1_FAST (Level 1-2): 疾速流，跳过复杂思考层，直接生成
    - TIER_2_STANDARD (Level 3): 均衡流，轻量级思考 + 串行生成
    - TIER_3_FORTRESS (Level 4-5): 堡垒流，算力全开，保持 V2.5 完整流程
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        beats: 节拍数据列表（V3.0: 每个 beat 可包含 workflow_tier）
        open_hooks: 开放伏笔列表
        api_key: LLM API Key
        base_url: LLM Base URL
        reasoning_model: 高逻辑模型（用于 Scene Intent / Subconscious / Review）
        creative_model: 高创意模型（用于 Prose Draft）
        word_count: 目标总字数
        previous_summary: 上一章摘要（可选）
        relevant_memories: RAG 检索的相关记忆（可选）
        locations: 地图地点列表（可选）
        enable_qc: 是否启用自动质检（默认 True）
        feature_flags: V3.0 功能开关配置（可选）
        physical_state_lock: 主角物理状态锁定描述（可选）
        workflow_tier: 工作流层级（可选，默认从 beats[0] 或 flags 获取）
        stats_callback: LLM 调用统计回调函数（可选），用于追踪各阶段调用次数和耗时
        reasoning_config: 推理模式配置（可选），用于 OpenRouter 推理模型
    
    Returns:
        List[BeatDraftResult]: 按 Beat 顺序排列的生成结果列表
    """
    if not beats:
        return []
    
    # 初始化功能开关（使用默认值）
    flags = feature_flags or DraftingFeatureFlags()
    
    # V3.0: 确定工作流层级（优先级: 传入参数 > chapter.tension_level 映射 > beat 元数据 > flags 默认值）
    effective_tier = workflow_tier
    
    # 尝试从 chapter.tension_level 计算（最可靠，基于用户输入）
    if not effective_tier and chapter:
        tension_level = getattr(chapter, 'tension_level', None)
        if tension_level and isinstance(tension_level, int) and 1 <= tension_level <= 5:
            effective_tier = map_tension_to_workflow_tier(tension_level)
            logger.info(f"[Draft Stage] 从 chapter.tension_level={tension_level} 映射到 {effective_tier}")
    
    # 尝试从 beat 的 workflow_tier 获取（LLM 输出，备用）
    if not effective_tier and beats:
        effective_tier = beats[0].get("workflow_tier")
    
    # 使用 flags 默认值
    if not effective_tier:
        effective_tier = flags.workflow_tier
    
    logger.info(f"[Draft Stage] V3.0 智能路由启动，工作流层级: {effective_tier}，共 {len(beats)} 个 Beats")
    
    # V3.0: 根据 workflow_tier 路由到不同的执行路径
    if effective_tier == "TIER_1_FAST":
        return await _execute_fast_path(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beats=beats,
            open_hooks=open_hooks,
            api_key=api_key,
            base_url=base_url,
            reasoning_model=reasoning_model,
            creative_model=creative_model,
            word_count=word_count,
            previous_summary=previous_summary,
            stats_callback=stats_callback,
        )
    elif effective_tier == "TIER_2_STANDARD":
        return await _execute_standard_path(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beats=beats,
            open_hooks=open_hooks,
            api_key=api_key,
            base_url=base_url,
            reasoning_model=reasoning_model,
            creative_model=creative_model,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            enable_qc=enable_qc,
            feature_flags=flags,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            stats_callback=stats_callback,
        )
    else:  # TIER_3_FORTRESS
        return await _execute_fortress_path(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beats=beats,
            open_hooks=open_hooks,
            api_key=api_key,
            base_url=base_url,
            reasoning_model=reasoning_model,
            creative_model=creative_model,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            enable_qc=enable_qc,
            feature_flags=flags,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            stats_callback=stats_callback,
        )


async def _generate_scene_intent_batch(
    beats: List[dict],
    chapter: Any,
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    model: str,
    stats_callback: LLMStatsCallback = None,
) -> tuple[List[dict], List[List[dict]]]:
    """
    步骤 A-1: 批量并行生成 Scene Intent。
    
    Scene Intent 是轻量级的逻辑分析，包含场景目标、风险、约束。
    所有 Beat 的 Scene Intent 可以安全并行生成（无文本依赖）。
    
    Args:
        beats: 节拍数据列表
        chapter: 章节实体
        open_hooks: 开放伏笔列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        stats_callback: LLM 调用统计回调（可选）
    
    Returns:
        tuple[List[dict], List[List[dict]]]: (Scene Intent 结果列表, 每个 Beat 的 prompts 列表)
    """
    async def _single_scene_intent(beat: dict, beat_index: int) -> tuple[dict, List[dict]]:
        """生成单个 Beat 的 Scene Intent。
        
        Returns:
            tuple[dict, List[dict]]: (Scene Intent 结果, prompts 列表)
        """
        prompts_history = []
        try:
            # 构建该 Beat 关联的 hooks
            beat_hook_ids = set(beat.get("hook_ids", []))
            beat_hooks = []
            if beat_hook_ids:
                beat_hooks = [
                    item for item in open_hooks
                    if item.get("hook_id") in beat_hook_ids or item.get("ledger_key") in beat_hook_ids
                ]
            if not beat_hooks and beat_index == 1:
                beat_hooks = open_hooks[:2] if len(open_hooks) >= 2 else open_hooks
            
            system_prompt, user_prompt = build_scene_intent_prompt(
                chapter=chapter,
                beat=beat,
                open_hooks=beat_hooks,
            )
            
            # 记录 Scene Intent prompt
            prompts_history.append({
                "stage": "SCENE_INTENT",
                "beat_index": beat_index,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": 0.2,
            })
            
            response = await _call_llm_with_stats(
                stage="scene_intent",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
                max_tokens=600,
                beat_index=beat_index,
                stats_callback=stats_callback,
                reasoning_config=reasoning_config,  # 推理模式配置
            )
            
            scene_intent = parse_scene_intent_result(response, beat.get("summary", ""))
            return scene_intent, prompts_history
            
        except Exception as e:
            logger.error(f"[Scene Intent] Beat {beat_index}: {e}")
            # 返回默认的 Scene Intent
            return {
                "intent_label": "推进剧情",
                "goal": beat.get("summary", "推进剧情"),
                "stakes": None,
                "constraints": [],
                "sensory_translation_rule": None,
            }, prompts_history
    
    # 并行生成所有 Scene Intent
    tasks = [
        _single_scene_intent(beat, i + 1)
        for i, beat in enumerate(beats)
    ]
    
    results = await asyncio.gather(*tasks)
    # 解构结果为两个列表
    scene_intents = [r[0] for r in results]
    prompts_list = [r[1] for r in results]
    return scene_intents, prompts_list


async def _generate_subconscious_batch(
    beats: List[dict],
    scene_intent_results: List[dict],
    chapter: Any,
    entities: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    stats_callback: LLMStatsCallback = None,
) -> tuple[List[str], List[Optional[list]], List[List[dict]]]:
    """
    步骤 A-2: 批量并行生成 Subconscious（潜意识层）。
    
    Subconscious 是 50-100 字的第一人称内心独白，为后续 Prose 生成提供情感锚点。
    所有 Beat 的 Subconscious 可以安全并行生成（依赖 Scene Intent，但不依赖其他 Beat 的文本）。
    
    Args:
        beats: 节拍数据列表
        scene_intent_results: 对应的 Scene Intent 结果列表
        chapter: 章节实体
        entities: 角色实体列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        stats_callback: LLM 调用统计回调（可选）
    
    Returns:
        tuple[List[str], List[Optional[list]], List[List[dict]]]: (潜意识独白列表, MCTS rollout 列表, 每个 Beat 的 prompts 列表)
    """
    async def _single_subconscious(beat: dict, scene_intent: dict, beat_index: int) -> tuple[str, Optional[list], List[dict]]:
        """生成单个 Beat 的 Subconscious（MCTS 潜意识树搜索）。
        
        Returns:
            tuple[str, Optional[list], List[dict]]: (潜意识思考文本, MCTS rollout 数据, prompts 列表)
        """
        prompts_history = []
        try:
            # ========================================================================
            # 构建伪前文（Risk 2 修复）- 基于前一个 beat 的状态
            # ========================================================================
            pseudo_tail = ""
            if beat_index > 1:  # beat_index 是 1-based
                prev_beat = beats[beat_index - 2]  # 转换为 0-based 索引
                prev_exit = prev_beat.get("exit_state", "")
                current_entry = beat.get("entry_state", "")
                if prev_exit or current_entry:
                    pseudo_tail = f"前一节拍结束状态：{prev_exit}。当前切入：{current_entry}"
            
            # ========================================================================
            # pov_perception_state 优先级取值链（Risk 4 配套）
            # ========================================================================
            pov_perception_state = beat.get("pov_perception_state") or beat.get("entry_state") or "正常"
            
            system_prompt, user_prompt = build_subconscious_prompt(
                chapter=chapter,
                beat=beat,
                scene_intent=scene_intent,
                entities=entities,
                pov_perception_state=pov_perception_state,
                red_lines=beat.get("red_lines", []),
                previous_tail=pseudo_tail,  # 使用伪前文替代空字符串
            )
            
            # 记录 Subconscious prompt（包含 MCTS 动机连贯性检查规则）
            prompts_history.append({
                "stage": "SUBCONSCIOUS",
                "beat_index": beat_index,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": 0.4,
            })
            
            response = await _call_llm_with_stats(
                stage="subconscious",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.4,  # 推理任务需更确定
                max_tokens=1000,  # JSON 结构需更多 token
                response_format={"type": "json_object"},
                beat_index=beat_index,
                stats_callback=stats_callback,
                reasoning_config=reasoning_config,  # 推理模式配置
            )
            
            # 清理并尝试解析 MCTS JSON
            cleaned = clean_llm_output(response).strip()
            
            # 尝试解析 MCTS JSON
            mcts_rollout_data = None  # MCTS 可观测性（Risk 5 修复）
            try:
                mcts_result = json.loads(cleaned)
                thought = mcts_result.get("best_subconscious", "").strip()
                # 保存完整的 MCTS rollout 数据
                mcts_rollout_data = mcts_result.get("mcts_rollout", None)
                if not thought:
                    # 回退：从 rollout 中选最高分
                    rollout = mcts_result.get("mcts_rollout", [])
                    if rollout:
                        best = max(rollout, key=lambda x: x.get("score", 0))
                        thought = best.get("thought", "")
            except (json.JSONDecodeError, TypeError, KeyError):
                # JSON 解析失败，回退到纯文本模式
                thought = cleaned
            
            # 长度约束
            if len(thought) > 150:
                thought = thought[:147] + "..."
            if len(thought) < 20:
                thought = f"{thought}... 内心的紧张感在蔓延。"
            
            return thought, mcts_rollout_data, prompts_history  # 返回元组：(思考文本, MCTS rollout, prompts)
            
        except Exception as e:
            logger.error(f"[Subconscious] Beat {beat_index}: {e}")
            # 返回默认的内心独白
            pov_character = beat.get("pov_character", "我")
            return f"{pov_character}深吸一口气，试图平复内心的波动。接下来该怎么办？", None, prompts_history
    
    # 并行生成所有 Subconscious
    tasks = [
        _single_subconscious(beat, scene_intent_results[i], i + 1)
        for i, beat in enumerate(beats)
    ]
    
    results = await asyncio.gather(*tasks)
    
    # 解构 tuple 结果为三个列表：(thoughts, mcts_rollouts, prompts)
    thoughts = [r[0] for r in results]
    mcts_rollouts = [r[1] for r in results]
    prompts_list = [r[2] for r in results]
    return thoughts, mcts_rollouts, prompts_list


async def _generate_prose_serial_v25(
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    creative_model: str,
    reasoning_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: DraftingFeatureFlags = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[dict]:
    """
    步骤 B-V25: 串行滑动窗口生成正文（Rolling Prefix + 认知组件）。
    
    V3.0 新增：支持强制并行模式（force_parallel_prose）
    - 串行模式：严格 Rolling Prefix，保证连贯性
    - 并行模式：无视前文衔接，极速生成
    
    V2.5 增强特性：
    - DynamicContext: 跨 Beat 流转的动态上下文容器
    - Fail-Fast: 即时断言检查与回溯重试机制
    - Emotional Scratchpad: 动态情绪状态更新
    
    核心机制（串行模式）：
    - Beat 1: 基于 Subconscious_1 + DynamicContext_0 生成 Prose_1
    - 断言检查: Fail-Fast 验证 Prose_1 物理/逻辑合法性
    - 状态更新: Emotional Scratchpad 更新 DynamicContext_1
    - Beat 2: 基于 Subconscious_2 + DynamicContext_1 生成 Prose_2
    - ...
    
    公式: Context_n = Subconscious_n + DynamicContext_(n-1)
    
    Args:
        beats: 节拍数据列表
        scene_intent_results: Scene Intent 结果列表
        subconscious_results: Subconscious 结果列表
        chapter: 章节实体
        book: 书籍实体
        entities: 角色实体列表
        relationships: 角色关系列表
        api_key: LLM API Key
        base_url: LLM Base URL
        creative_model: 高创意模型（用于正文生成）
        reasoning_model: 高逻辑模型（用于断言检查）
        word_count: 目标总字数
        previous_summary: 上一章摘要
        relevant_memories: RAG 相关记忆
        locations: 地图地点列表
        enable_qc: 是否启用质检
        feature_flags: V2.5 功能开关配置
        physical_state_lock: 主角物理状态锁定描述
        stats_callback: LLM 调用统计回调（可选）
    
    Returns:
        List[dict]: 按 Beat 顺序排列的结果列表，每项包含 {"text": str, "prompts": list}
    """
    # 初始化功能开关（如果未提供）
    flags = feature_flags or DraftingFeatureFlags()
    
    # ========================================================================
    # V3.0 并发模式判断
    # ========================================================================
    force_parallel = getattr(flags, 'force_parallel_prose', False)
    
    if force_parallel:
        logger.info("[Prose V25] 强制并行模式启用：将无视前文衔接，并发生成所有 Beats")
        return await _generate_prose_parallel_v25(
            beats=beats,
            scene_intent_results=scene_intent_results,
            subconscious_results=subconscious_results,
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            api_key=api_key,
            base_url=base_url,
            creative_model=creative_model,
            reasoning_model=reasoning_model,
            word_count=word_count,
            previous_summary=previous_summary,
            relevant_memories=relevant_memories,
            locations=locations,
            enable_qc=enable_qc,
            feature_flags=flags,
            physical_state_lock=physical_state_lock,
            entity_spatial_ledger=entity_spatial_ledger,
            chapter_assets_schema=chapter_assets_schema,
            stats_callback=stats_callback,
        )
    
    results: List[dict] = []
    
    # ========================================================================
    # 初始化跨 Beat 动态上下文 (DynamicContext) - V2.5+ 增强版
    # ========================================================================
    # 从第一章节提取初始情绪状态（使用 entry_state）
    initial_emotional_state = "初始状态：未知"
    if beats and beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"
    
    # V2.5+ NEW: 构建初始关系状态锁
    initial_relational_state = _build_initial_relational_state(relationships, entities)
    
    # V3.0 NEW: 初始化 pov_perception_state（三级优先级链：pov_perception_state > entry_state > "正常"）
    def _get_pov_perception_state(beat: dict) -> str:
        """取值优先级：beat.pov_perception_state > beat.entry_state > "正常" """
        return beat.get("pov_perception_state") or beat.get("entry_state") or "正常"
    
    initial_pov_perception_state = _get_pov_perception_state(beats[0]) if beats else "正常"
    
    dynamic_context = DynamicContext(
        previous_tail="",
        current_emotional_state=initial_emotional_state,
        physical_state_lock=physical_state_lock or "",
        accumulated_summary="",           # V2.5+ NEW: 宏观剧情累加器
        relational_state_lock=initial_relational_state,  # V2.5+ NEW: 关系状态锁
        entity_spatial_ledger=entity_spatial_ledger or {},  # V2.5+ NEW: 空间账本
    )
    
    # V3.0 NEW: 存储 pov_perception_state（因为 DynamicContext 可能没有此属性，使用独立变量）
    current_pov_perception_state = initial_pov_perception_state
    
    logger.info(f"[Prose V25+] 初始化 DynamicContext (串行模式): "
                f"emotional='{initial_emotional_state[:30]}...', "
                f"physical='{physical_state_lock[:30] if physical_state_lock else '无'}...', "
                f"relational='{initial_relational_state[:30] if initial_relational_state else '无'}...'")
    
    for i, beat in enumerate(beats):
        beat_index = i + 1
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        pov_character = beat.get("pov_character", "主角")
        
        # 提取 POV 角色的静态设定（用于正文生成中的角色行为约束）
        pov_profile = ""
        if pov_character and entities:
            for entity in entities:
                char = getattr(entity, 'character', None) or entity
                char_name = getattr(char, 'name', '') or ''
                if char_name and pov_character in char_name:
                    raw_profile = getattr(char, 'static_prompt', '') or ''
                    pov_profile = raw_profile[:150] if raw_profile else ''
                    break
        
        try:
            # 计算目标字数
            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))
            
            # ========================================================================
            # Fail-Fast 重试循环
            # ========================================================================
            max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
            chunk_text = ""
            is_valid = False
            attempt = 0
            current_temp = 0.75  # 基础温度
            
            prompts_history = []
            
            while attempt < max_attempts and not is_valid:
                attempt += 1
                
                # 构建 V2.5+ 增强版 Prose Draft Prompt
                system_prompt, user_prompt = build_prose_draft_prompt_v25(
                    chapter=chapter,
                    book=book,
                    beat=beat,
                    scene_intent=scene_intent_results[i],
                    subconscious_thought=subconscious_results[i],
                    previous_tail=dynamic_context.previous_tail,
                    target_words=target_words,
                    physical_state_lock=dynamic_context.physical_state_lock,
                    current_emotional_state=dynamic_context.current_emotional_state,
                    # V2.5+ NEW PARAMETERS:
                    accumulated_summary=dynamic_context.accumulated_summary,
                    relational_state_lock=dynamic_context.relational_state_lock,
                    red_lines=beat.get("red_lines"),
                    entity_spatial_ledger=dynamic_context.entity_spatial_ledger if dynamic_context.entity_spatial_ledger else None,
                    # V3.0 NEW PARAMETERS (四重锁):
                    chapter_assets_schema=chapter_assets_schema or getattr(chapter, 'chapter_assets_schema', '') or '',
                    pov_perception_state=current_pov_perception_state,
                    pov_character_profile=pov_profile,
                )
                
                prompts_history.append({
                    "stage": f"PROSE_DRAFT_ATTEMPT_{attempt}",
                    "beat_index": beat_index,
                    "temperature": current_temp,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                })
                
                logger.info(f"[Prose V25] Beat {beat_index}/{len(beats)} 尝试 {attempt}/{max_attempts} (temp={current_temp:.2f})...")
                prose_start = time.perf_counter()
                
                # 生成正文（带统计追踪）
                response = await _call_llm_with_stats(
                    stage="prose_draft",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    temperature=current_temp,
                    max_tokens=_clamp_tokens(target_words),
                    beat_index=beat_index,
                    stats_callback=stats_callback,
                )
                
                chunk_text = clean_llm_output(response).strip()
                logger.info(f"[Prose V25] Beat {beat_index} 生成完成，耗时 {time.perf_counter() - prose_start:.2f}s，字数 {len(chunk_text)}")
                
                # ========================================================================
                # Fail-Fast 断言检查 (V3.0 增强版 - 智能回溯策略)
                # ========================================================================
                if flags.enable_fail_fast and attempt < max_attempts:
                    is_valid, fail_reason, fail_categories = await _micro_review_assertion(
                        chunk_text=chunk_text,
                        dynamic_context=dynamic_context,
                        pov_character=pov_character,
                        beat=beat,
                        api_key=api_key,
                        base_url=base_url,
                        model=reasoning_model,
                        entity_spatial_ledger=dynamic_context.entity_spatial_ledger if dynamic_context.entity_spatial_ledger else None,
                        beat_index=beat_index,
                        stats_callback=stats_callback,
                    )
                    
                    if not is_valid:
                        logger.warning(f"[Fail-Fast] Beat {beat_index} 断言失败: {fail_reason} [类别: {', '.join(fail_categories)}]")
                        
                        # V3.0: 智能温度调整策略
                        if "文风" in fail_categories:
                            # 文风问题：提高温度重新采样
                            current_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
                            logger.info(f"[Fail-Fast] 文风问题，提高温度至 {current_temp:.2f}")
                        else:
                            # 逻辑越界/红线/物理幻觉：保持或降低温度，注入错误提示
                            current_temp = max(0.3, current_temp - 0.1)
                            logger.info(f"[Fail-Fast] 逻辑错误，降低温度至 {current_temp:.2f}")
                            
                            # V3.0: 在 prompt 中叠加错误信息（仅用于下一次重试）
                            error_hint = f"\n\n【修正要求】上一版本存在以下问题：{fail_reason}。请保持原语境，仅修复该冲突，不要改变整体文风。"
                            # 注意：这里的 user_prompt 需要在下次循环时包含此提示
                            # 通过修改外部作用域的变量来实现
                            user_prompt = user_prompt + error_hint
                    else:
                        logger.info(f"[Fail-Fast] Beat {beat_index} 断言通过")
                else:
                    is_valid = True
            
            # ========================================================================
            # 可选：自动质检与修复（原有 QC 逻辑）
            # ========================================================================
            if enable_qc:
                chunk_text, qc_prompts = await _quick_qc(
                    prose_text=chunk_text,
                    beat=beat,
                    beat_index=beat_index,
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    target_words=target_words,
                )
                prompts_history.extend(qc_prompts)
            
            # ========================================================================
            # 更新动态上下文 (V2.5+ 增强版状态更新)
            # ========================================================================
            # 1. 更新 Rolling Prefix (previous_tail) - 追加视角锚定标签防止 POV 漂移
            tail_text = _extract_tail(chunk_text, max_chars=300)
            next_entry_state = beats[i+1].get('entry_state', '未指定') if i+1 < len(beats) else '章节结束'
            pov_anchor = f"\n[System Tracker: 当前主语视角强锁定为 {pov_character} | 当前退出状态: {beat.get('exit_state', '未指定')} | 下一拍进入状态: {next_entry_state}]"
            dynamic_context.previous_tail = tail_text + pov_anchor
            
            # 2. 升级状态更新（情绪 + 关系 + 摘要）
            if flags.enable_emotional_scratchpad:
                state_update = await _update_dynamic_state(
                    chunk_text=chunk_text,
                    current_emotional_state=dynamic_context.current_emotional_state,
                    pov_character=pov_character,
                    api_key=api_key,
                    base_url=base_url,
                    model=reasoning_model,
                    relational_state_lock=dynamic_context.relational_state_lock,  # NEW
                    beat_context=beat,  # NEW: 传递 beat 上下文
                    book_genre=getattr(book, 'genre', '通用小说'),  # NEW: 传递书籍类型
                )
                
                # 更新情绪状态
                dynamic_context.current_emotional_state = state_update.new_emotional_state
                
                # NEW: 更新关系状态锁
                if state_update.relational_delta:
                    dynamic_context.relational_state_lock = _merge_relational_delta(
                        dynamic_context.relational_state_lock,
                        state_update.relational_delta
                    )
                
                # NEW: 更新宏观剧情累加器
                if state_update.beat_summary:
                    dynamic_context.update_summary(state_update.beat_summary)
                
                logger.info(f"[Dynamic State] Beat {beat_index} 更新: "
                            f"E='{state_update.new_emotional_state[:30]}...', "
                            f"R_delta='{state_update.relational_delta[:30] if state_update.relational_delta else '无'}...', "
                            f"S='{state_update.beat_summary[:30]}...'")
            
            # V3.0 NEW: 更新 pov_perception_state（使用三级优先级链从下一个 beat 获取）
            if i + 1 < len(beats):
                next_beat = beats[i + 1]
                current_pov_perception_state = _get_pov_perception_state(next_beat)
            
            results.append({
                "text": chunk_text,
                "prompts": prompts_history,
            })
            
        except Exception as e:
            logger.error(f"[Prose V25] Beat {beat_index}: {e}")
            # 返回空文本，但保持 Rolling Prefix 不变（尝试用上一个 tail 继续）
            results.append({
                "text": "",
                "prompts": [],
            })
    
    return results


async def _generate_prose_parallel_v25(
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    creative_model: str,
    reasoning_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: DraftingFeatureFlags = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[dict]:
    """
    V3.0 并行模式正文生成 - 极速但可能损失连贯性。
    
    特点：
    - 无视 Rolling Prefix，所有 Beat 同时生成
    - previous_tail 始终为空字符串
    - current_emotional_state 始终使用初始值，不跨 Beat 累加
    - Fail-Fast 检查仍然执行，但不影响其他 Beat
    
    适用场景：用户明确选择速度优先于质量时。
    """
    flags = feature_flags or DraftingFeatureFlags()
    
    # 初始化固定的上下文状态（所有 Beat 使用相同的初始状态）
    initial_emotional_state = "初始状态：未知"
    if beats and beats[0].get("entry_state"):
        initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"
    
    initial_relational_state = _build_initial_relational_state(relationships, entities)
    
    logger.info(f"[Prose V25-Parallel] 启动并行生成，共 {len(beats)} 个 Beats")
    
    async def _single_prose_task(
        beat_index: int,
        beat: dict,
        scene_intent: dict,
        subconscious: str,
    ) -> dict:
        """单个 Beat 的生成任务（用于并行执行）。"""
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        pov_character = beat.get("pov_character", "主角")
        
        # 提取 POV 角色的静态设定
        pov_profile = ""
        if pov_character and entities:
            for entity in entities:
                char = getattr(entity, 'character', None) or entity
                char_name = getattr(char, 'name', '') or ''
                if char_name and pov_character in char_name:
                    raw_profile = getattr(char, 'static_prompt', '') or ''
                    pov_profile = raw_profile[:150] if raw_profile else ''
                    break
        
        try:
            # 计算目标字数
            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))
            
            # Fail-Fast 重试循环（每个 Beat 独立）
            max_attempts = flags.fail_fast_max_attempts if flags.enable_fail_fast else 1
            chunk_text = ""
            is_valid = False
            attempt = 0
            current_temp = 0.75
            
            prompts_history = []
            
            # 并行模式下使用固定的初始状态，不跨 Beat 更新
            pov_perception_state = beat.get("pov_perception_state") or beat.get("entry_state") or "正常"
            
            while attempt < max_attempts and not is_valid:
                attempt += 1
                
                # 构建 Prose Draft Prompt（previous_tail 始终为空）
                system_prompt, user_prompt = build_prose_draft_prompt_v25(
                    chapter=chapter,
                    book=book,
                    beat=beat,
                    scene_intent=scene_intent,
                    subconscious_thought=subconscious,
                    previous_tail="",  # 并行模式：无视前文
                    target_words=target_words,
                    physical_state_lock=physical_state_lock or "",
                    current_emotional_state=initial_emotional_state,  # 并行模式：使用初始状态
                    accumulated_summary="",  # 并行模式：无累加摘要
                    relational_state_lock=initial_relational_state,
                    red_lines=beat.get("red_lines"),
                    entity_spatial_ledger=entity_spatial_ledger or None,
                    chapter_assets_schema=chapter_assets_schema or '',
                    pov_perception_state=pov_perception_state,
                    pov_character_profile=pov_profile,
                )
                
                prompts_history.append({
                    "stage": f"PROSE_PARALLEL_ATTEMPT_{attempt}",
                    "beat_index": beat_index,
                    "temperature": current_temp,
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                })
                
                logger.info(f"[Prose V25-Parallel] Beat {beat_index}/{len(beats)} 尝试 {attempt}/{max_attempts}...")
                
                # 生成正文
                response = await _call_llm_with_stats(
                    stage="prose_draft_parallel",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    temperature=current_temp,
                    max_tokens=_clamp_tokens(target_words),
                    beat_index=beat_index,
                    stats_callback=stats_callback,
                )
                
                chunk_text = clean_llm_output(response).strip()
                
                # Fail-Fast 断言检查（并行模式下仍执行，但不阻塞其他 Beat）
                if flags.enable_fail_fast and attempt < max_attempts:
                    # 并行模式下使用临时 DynamicContext
                    temp_context = DynamicContext(
                        previous_tail="",
                        current_emotional_state=initial_emotional_state,
                        physical_state_lock=physical_state_lock or "",
                        accumulated_summary="",
                        relational_state_lock=initial_relational_state,
                        entity_spatial_ledger=entity_spatial_ledger or {},
                    )
                    
                    is_valid, fail_reason, fail_categories = await _micro_review_assertion(
                        chunk_text=chunk_text,
                        dynamic_context=temp_context,
                        pov_character=pov_character,
                        beat=beat,
                        api_key=api_key,
                        base_url=base_url,
                        model=reasoning_model,
                        entity_spatial_ledger=entity_spatial_ledger,
                        beat_index=beat_index,
                        stats_callback=stats_callback,
                    )
                    
                    if not is_valid:
                        logger.warning(f"[Fail-Fast Parallel] Beat {beat_index} 断言失败: {fail_reason}")
                        # 温度调整
                        if "文风" in fail_categories:
                            current_temp = min(1.0, current_temp + flags.fail_fast_temperature_step)
                        else:
                            current_temp = max(0.3, current_temp - 0.1)
                    else:
                        logger.info(f"[Fail-Fast Parallel] Beat {beat_index} 断言通过")
                else:
                    is_valid = True
            
            # 可选：自动质检
            if enable_qc:
                chunk_text, qc_prompts = await _quick_qc(
                    prose_text=chunk_text,
                    beat=beat,
                    beat_index=beat_index,
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    api_key=api_key,
                    base_url=base_url,
                    model=creative_model,
                    target_words=target_words,
                )
                prompts_history.extend(qc_prompts)
            
            return {
                "text": chunk_text,
                "prompts": prompts_history,
            }
            
        except Exception as e:
            logger.error(f"[Prose V25-Parallel] Beat {beat_index}: {e}")
            return {
                "text": "",
                "prompts": [],
            }
    
    # 创建所有 Beat 的并发任务
    tasks = [
        _single_prose_task(
            beat_index=i + 1,
            beat=beat,
            scene_intent=scene_intent_results[i],
            subconscious=subconscious_results[i],
        )
        for i, beat in enumerate(beats)
    ]
    
    # 并发执行所有任务
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果（将异常转换为空结果）
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"[Prose V25-Parallel] Beat {i+1} 发生异常: {result}")
            processed_results.append({"text": "", "prompts": []})
        else:
            processed_results.append(result)
    
    logger.info(f"[Prose V25-Parallel] 并行生成完成，共 {len(processed_results)} 个 Beats")
    return processed_results


async def _micro_review_assertion(
    chunk_text: str,
    dynamic_context: DynamicContext,
    pov_character: str,
    # ========================================
    # NEW: Beat parameter for red_lines access
    # ========================================
    beat: Optional[dict] = None,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
    entity_spatial_ledger: Optional[dict] = None,
    beat_index: Optional[int] = None,
    stats_callback: LLMStatsCallback = None,
) -> tuple[bool, str, List[str]]:
    """
    V3.0 Fail-Fast 微审查断言（增强版）。
    
    职责：极速检查生成的文本是否存在物理/逻辑/关系/OOC 硬伤。
    
    V3.0 更新：返回失败类别，用于智能温度调整策略。
    
    断言决策树:
    ```
    IF Violate(red_lines):
        RETURN (False, "触碰红线约束", ["红线"])
    IF Physical_Hallucination:
        RETURN (False, "物理状态冲突", ["物理幻觉"])
    IF OOC_Behavior:
        RETURN (False, "角色行为偏离设定", ["OOC"])
    IF Relationship_Jump:
        RETURN (False, "人物关系无逻辑突变", ["关系"])
    IF Style_Issue:
        RETURN (False, "文风问题", ["文风"])
    RETURN (True, "", [])
    ```
    
    Args:
        chunk_text: 待检查的文本片段
        dynamic_context: 动态上下文（包含物理状态锁、关系状态锁）
        pov_character: 视角角色名
        beat: Beat 数据字典（用于获取 red_lines）
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称（建议使用轻量级模型）
        entity_spatial_ledger: 角色空间账本（可选）
        beat_index: Beat 索引（用于统计）
        stats_callback: LLM 调用统计回调（可选）
    
    Returns:
        tuple[bool, str, List[str]]: (是否通过, 失败原因, 失败类别列表)
        失败类别: ["红线", "物理幻觉", "OOC", "关系", "文风", "其他"]
    """
    try:
        # V2.5+ NEW: 提取角色设定用于 OOC 检查
        char_prompts = _extract_character_prompts_for_beat(beat, dynamic_context) if beat else None
        
        # V2.5+ NEW: 增强物理状态锁，加入空间账本信息
        effective_physical_lock = dynamic_context.physical_state_lock
        if entity_spatial_ledger:
            from backend.services.prompts.draft_prompts import _format_entity_spatial_ledger
            spatial_info = _format_entity_spatial_ledger(entity_spatial_ledger)
            if spatial_info:
                effective_physical_lock = f"{effective_physical_lock}\n\n【角色空间绑定】:\n{spatial_info}"
        
        system_prompt, user_prompt = build_micro_review_prompt(
            chunk_text=chunk_text,
            physical_state_lock=effective_physical_lock,
            pov_character=pov_character,
            # V2.5+ NEW: 传递增强参数
            red_lines=beat.get("red_lines") if beat else None,
            relational_state_lock=dynamic_context.relational_state_lock,
            character_static_prompts=char_prompts,
        )
        
        response = await _call_llm_with_stats(
            stage="micro_review",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.0,  # 确定性输出
            response_format={"type": "json_object"},
            max_tokens=200,  # 极短输出
            beat_index=beat_index,
            stats_callback=stats_callback,
        )
        
        # 解析 JSON 结果
        result_text = clean_llm_output(response).strip()
        result = json.loads(result_text)
        
        review_result = MicroReviewResult(**result)
        
        # V2.5+ NEW: 构建包含失败检查项的原因
        failed_reason = review_result.reason or "未知逻辑错误"
        if review_result.failed_checks:
            failed_reason = f"[检查项 {', '.join(review_result.failed_checks)}] {failed_reason}"
        
        # V3.0: 推断失败类别
        fail_categories = _infer_fail_categories(failed_reason, review_result.failed_checks or [])
        
        if review_result.pass_check:
            return True, "", []
        else:
            return False, failed_reason, fail_categories
            
    except json.JSONDecodeError as e:
        logger.warning(f"[Fail-Fast] JSON 解析失败: {e}")
        # JSON 解析失败时，保守起见允许通过（避免阻塞）
        return True, "", []
    except Exception as e:
        logger.warning(f"[Fail-Fast] 断言检查异常: {e}")
        # 异常时允许通过，避免阻塞主流程
        return True, "", []


def _infer_fail_categories(fail_reason: str, failed_checks: List[str]) -> List[str]:
    """
    V3.0: 从失败原因和检查项中推断失败类别。
    
    Args:
        fail_reason: 失败原因描述
        failed_checks: 失败的检查项列表
    
    Returns:
        List[str]: 失败类别列表
    """
    categories = []
    reason_lower = fail_reason.lower()
    checks_lower = [c.lower() for c in failed_checks]
    
    # 基于检查项推断
    for check in checks_lower:
        if any(kw in check for kw in ["red_line", "红线", "禁忌"]):
            categories.append("红线")
        elif any(kw in check for kw in ["physical", "物理", "状态", "空间", "位置"]):
            categories.append("物理幻觉")
        elif any(kw in check for kw in ["ooc", "角色", "设定", "性格"]):
            categories.append("OOC")
        elif any(kw in check for kw in ["relation", "关系", "态度", "信任"]):
            categories.append("关系")
        elif any(kw in check for kw in ["style", "文风", "文笔", "语言"]):
            categories.append("文风")
    
    # 基于失败原因推断
    if any(kw in reason_lower for kw in ["红线", "禁忌", "禁止"]):
        categories.append("红线")
    if any(kw in reason_lower for kw in ["物理", "空间", "位置", "幻觉", "瞬移"]):
        categories.append("物理幻觉")
    if any(kw in reason_lower for kw in ["ooc", "角色", "设定", "性格", "行为偏离"]):
        categories.append("OOC")
    if any(kw in reason_lower for kw in ["关系", "态度", "信任", "敌对", "友好"]):
        categories.append("关系")
    if any(kw in reason_lower for kw in ["文风", "白开水", "ai味", "平淡", "机械", "套路", "模板"]):
        categories.append("文风")
    
    # 去重
    unique_categories = list(set(categories))
    
    # 如果没有识别出类别，归为"其他"
    if not unique_categories:
        unique_categories.append("其他")
    
    return unique_categories


async def _update_emotional_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    更新情绪暂存器。
    
    职责：基于刚生成的剧情，总结主角心理状态的微小演变。
    
    设计原则：
    - 极简输出：20字以内的一句话总结
    - 微演变：强调心理状态的变化，而非静态描述
    
    Args:
        chunk_text: 刚生成的剧情文本
        current_emotional_state: 之前的心理状态
        pov_character: 视角角色名
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称（轻量级即可）
    
    Returns:
        str: 新的心理状态描述（20字以内）
    """
    try:
        system_prompt, user_prompt = build_emotional_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
        )
        
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,  # 低温度，保持确定性
            max_tokens=100,  # 极短输出
        )
        
        new_emotion = clean_llm_output(response).strip()
        
        # 长度限制：如果超过 30 字，尝试截断
        if len(new_emotion) > 30:
            # 找到最后一个句号或逗号
            for punct in [".", "。", ",", "，"]:
                last_punct = new_emotion.rfind(punct, 0, 30)
                if last_punct > 10:  # 至少保留 10 个字符
                    new_emotion = new_emotion[:last_punct + 1]
                    break
            else:
                # 没找到合适的标点，强制截断
                new_emotion = new_emotion[:30] + "..."
        
        return new_emotion
        
    except Exception as e:
        logger.warning(f"[Emotional Update] 情绪更新失败: {e}")
        # 失败时返回原状态，避免破坏上下文
        return current_emotional_state


async def _quick_qc(
    prose_text: str,
    beat: dict,
    beat_index: int,
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    target_words: int,
) -> tuple[str, List[dict]]:
    """
    快速质检与修复。
    
    触发条件：
    - 字数异常：生成内容 < 目标字数的 50%
    - 结构异常：长文本但无段落分隔（\n\n）
    
    Args:
        prose_text: 待质检的文本
        beat: Beat 数据
        beat_index: Beat 索引
        chapter: 章节实体
        book: 书籍实体
        entities: 角色实体列表
        relationships: 角色关系列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        target_words: 目标字数
    
    Returns:
        tuple[str, List[dict]]: (修复后的文本, QC 阶段提示词历史)
    """
    prompts = []
    
    # 异常检测
    compact_text = prose_text.replace("\n", "").replace(" ", "")
    has_abnormal_length = len(compact_text) < max(120, int(target_words * 0.5))
    has_abnormal_structure = ("\n\n" not in prose_text) and len(prose_text) > 500
    
    if not has_abnormal_length and not has_abnormal_structure:
        return prose_text, prompts
    
    logger.info(f"[QC] Beat {beat_index} 检测到异常，开始修复...")
    
    try:
        # 构建 Review Prompt
        review_system, review_user = build_chunk_review_prompt(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beat_summary=beat.get("summary", ""),
            chunk_text=prose_text,
        )
        
        prompts.append({
            "stage": "CHUNK_REVIEW",
            "beat_index": beat_index,
            "system_prompt": review_system,
            "user_prompt": review_user,
        })
        
        review_response = await call_llm(
            system_prompt=review_system,
            user_prompt=review_user,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=800,
        )
        
        import json
        try:
            review_result = json.loads(clean_llm_output(review_response))
        except json.JSONDecodeError:
            return prose_text, prompts
        
        if review_result.get("pass", True):
            return prose_text, prompts
        
        # 需要修复
        instruction = review_result.get("revision_instruction", "")
        if not instruction:
            issues = review_result.get("issues", [])
            instruction = "; ".join(issues) if issues else "修正文本质量问题"
        
        logger.info(f"[QC] Beat {beat_index} 修复指令: {instruction[:50]}...")
        
        # 构建 Refine Prompt
        refine_system, refine_user = build_chunk_refine_prompt(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beat_summary=beat.get("summary", ""),
            chunk_text=prose_text,
            revision_instruction=instruction,
        )
        
        prompts.append({
            "stage": "CHUNK_REFINE",
            "beat_index": beat_index,
            "system_prompt": refine_system,
            "user_prompt": refine_user,
        })
        
        refine_response = await call_llm(
            system_prompt=refine_system,
            user_prompt=refine_user,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=_clamp_tokens(target_words),
        )
        
        refined_text = clean_llm_output(refine_response).strip()
        logger.info(f"[QC] Beat {beat_index} 修复完成，新字数 {len(refined_text)}")
        
        return refined_text, prompts
        
    except Exception as e:
        logger.error(f"[QC] Beat {beat_index}: {e}")
        return prose_text, prompts


def _extract_tail(text: str, max_chars: int = 300) -> str:
    """
    提取文本末尾指定长度的内容，作为 Rolling Prefix。
    
    策略：
    - 如果文本长度 <= max_chars，返回全文
    - 如果文本长度 > max_chars，从最后一个段落边界截取
    - 确保截取的内容语义完整（不从句子中间切断）
    
    Args:
        text: 原始文本
        max_chars: 最大字符数（默认 300）
    
    Returns:
        str: 末尾文本片段
    """
    if not text:
        return ""
    
    if len(text) <= max_chars:
        return text
    
    # 尝试从段落边界截取
    paragraphs = text.split("\n\n")
    tail_parts = []
    current_length = 0
    
    # 从后向前收集段落
    for para in reversed(paragraphs):
        if current_length + len(para) + 2 > max_chars:
            # 如果加上这个段落会超长度，尝试只加一部分
            remaining = max_chars - current_length
            if remaining > 50:  # 至少还有 50 字符空间
                # 尝试在句子边界切断
                sentences = para.split("。")
                partial = ""
                for sent in reversed(sentences):
                    if len(partial) + len(sent) + 1 <= remaining:
                        partial = sent + "。" + partial if partial else sent + "。"
                    else:
                        break
                if partial:
                    tail_parts.insert(0, partial)
            break
        tail_parts.insert(0, para)
        current_length += len(para) + 2
    
    result = "\n\n".join(tail_parts)
    
    # 如果还是太长，强制截断
    if len(result) > max_chars:
        result = result[-max_chars:]
        # 确保不从句子中间切断（简单策略：找到最近的句号）
        first_period = result.find("。")
        if first_period > 0 and first_period < 50:  # 如果句号在前50字符内
            result = result[first_period + 1:]
    
    return result.strip()


def _clamp_tokens(target_words: int) -> int:
    """
    根据目标字数计算合理的 max_tokens。
    
    中文字符与 token 的大致比例约为 1:1.5，这里使用安全系数。
    
    Args:
        target_words: 目标字数
    
    Returns:
        int: 建议的 max_tokens 值
    """
    # 中文字数 -> tokens 估算：乘以 2 作为安全系数
    estimated_tokens = int(target_words * 2)
    # 限制在合理范围内
    return max(1200, min(estimated_tokens, 5200))


# ========================================================================
# 兼容性保留：原有的并行生成函数
# ========================================================================

async def generate_chunks_parallel(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    story_beats: List[Any],
    open_hooks: List[dict],
    previous_summary: Optional[str],
    relevant_memories: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    word_count: int,
) -> List[str]:
    """
    【兼容性保留】并行生成多个故事节拍的正文片段。
    
    警告：此函数为旧版实现，使用完全并行的方式生成，可能导致 Beat 间语气不连贯。
    新项目请使用 execute_draft_stage。
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        beats: 节拍数据列表
        story_beats: 数据库中的 StoryBeat 实体列表
        open_hooks: 开放伏笔列表
        previous_summary: 上一章摘要
        relevant_memories: RAG 检索的相关记忆
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        word_count: 目标总字数
    
    Returns:
        List[str]: 生成的 chunks 列表，按节拍顺序排列
    """
    from backend.services.prompts import build_chunk_draft_prompt
    
    async def process_single_beat(beat_index: int, beat: dict, story_beat: Any) -> tuple[int, str]:
        """处理单个节拍的生成流程。"""
        try:
            beat_hooks = _build_beat_hooks(beat, open_hooks, beat_index)
            
            scene_system_prompt, scene_user_prompt = build_scene_intent_prompt(
                chapter=chapter,
                beat=beat,
                open_hooks=beat_hooks,
            )
            scene_intent_raw = await call_llm(
                system_prompt=scene_system_prompt,
                user_prompt=scene_user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            scene_intent_data = parse_scene_intent_result(scene_intent_raw, beat.get("summary", ""))
            
            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))
            
            context_summaries = _build_context_summaries(beat_index, beats, len(beats))
            
            chunk_system_prompt, chunk_user_prompt = build_chunk_draft_prompt(
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                beat=beat,
                scene_intent=scene_intent_data,
                target_words=target_words,
                previous_chunks=[],
                previous_summary=previous_summary,
                relevant_memories=relevant_memories,
                hook_contexts=beat_hooks,
                context_beat_summaries=context_summaries,
            )
            
            chunk_text = await call_llm(
                system_prompt=chunk_system_prompt,
                user_prompt=chunk_user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.7,
            )
            return beat_index - 1, clean_llm_output(chunk_text)
        except Exception as e:
            logger.error(f"[Beat] Beat {beat_index} failed: {e}")
            return beat_index - 1, ""
    
    def _build_beat_hooks(beat: dict, all_hooks: List[dict], beat_index: int) -> List[dict]:
        """构建节拍关联的伏笔上下文。"""
        beat_hook_ids = set(beat.get("hook_ids", []))
        if beat_hook_ids:
            return [
                item for item in all_hooks
                if item.get("hook_id") in beat_hook_ids or item.get("ledger_key") in beat_hook_ids
            ]
        if beat_index == 1:
            return all_hooks[:2] if len(all_hooks) >= 2 else all_hooks
        return []
    
    def _build_context_summaries(beat_index: int, beats: List[dict], total_beats: int) -> dict:
        """构建前后节拍的摘要上下文。"""
        summaries = {}
        if beat_index > 1:
            summaries["prev"] = beats[beat_index - 2].get("summary", "")
        if beat_index < total_beats:
            summaries["next"] = beats[beat_index].get("summary", "")
        return summaries
    
    sem = asyncio.Semaphore(5)
    
    async def sem_task(task):
        async with sem:
            return await task
    
    tasks = [
        sem_task(process_single_beat(i, b, sb))
        for i, b, sb in zip(range(1, len(beats) + 1), beats, story_beats)
    ]
    
    results = await asyncio.gather(*tasks)
    
    generated_chunks = [""] * len(beats)
    for idx, text in results:
        generated_chunks[idx] = text
    
    return generated_chunks



# ========================================================================
# V2.5+ Cognitive Streaming - 增强版状态更新与辅助函数
# ========================================================================

async def _update_dynamic_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
    relational_state_lock: str = "",
    beat_context: Optional[Any] = None,
    book_genre: str = "通用小说",
) -> DynamicStateUpdateResult:
    """
    更新动态状态（V2.5+ 升级版）。
    
    职责：基于刚生成的剧情，总结：
    - 新的角色内心状态 $E_{new}$
    - 角色关系变化 $R_{delta}$
    - 本段剧情摘要 $S_{new}$
    
    状态演化公式:
    $$\\Delta_{state} = f_{llm}(Text_{chunk}, State_{prev}, Rel_{current})$$
    $$State_{new} = State_{prev} \\oplus \\Delta_{state}$$
    
    Args:
        chunk_text: 刚生成的剧情文本
        current_emotional_state: 之前的心理状态
        pov_character: 视角角色名
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        relational_state_lock: 当前关系状态锁
        beat_context: Beat 上下文信息
        book_genre: 书籍类型（默认"通用小说"）
    
    Returns:
        DynamicStateUpdateResult: 结构化状态更新结果
    """
    try:
        system_prompt, user_prompt = build_dynamic_state_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
            relational_state_lock=relational_state_lock,
            beat_context=beat_context,
            book_genre=book_genre,
        )
        
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,  # 低温度，保持确定性
            response_format={"type": "json_object"},
            max_tokens=300,  # 足够容纳 JSON 结构
        )
        
        result_text = clean_llm_output(response).strip()
        result_json = json.loads(result_text)
        
        # 使用 Pydantic 验证和解析
        result = DynamicStateUpdateResult(**result_json)
        return result
        
    except json.JSONDecodeError as e:
        logger.warning(f"[Dynamic State Update] JSON 解析失败: {e}")
        # 降级处理：返回默认结果
        return DynamicStateUpdateResult(
            new_emotional_state=current_emotional_state,
            relational_delta="",
            beat_summary=_extract_fallback_summary(chunk_text)
        )
    except Exception as e:
        logger.warning(f"[Dynamic State Update] 状态更新失败: {e}")
        # 降级处理
        return DynamicStateUpdateResult(
            new_emotional_state=current_emotional_state,
            relational_delta="",
            beat_summary=_extract_fallback_summary(chunk_text)
        )


def _extract_fallback_summary(text: str, max_len: int = 40) -> str:
    """
    提取剧情摘要的降级方案（当 LLM 调用失败时使用）。
    
    策略：取前 max_len 个字符，尝试在句子边界截断
    """
    if len(text) <= max_len:
        return text
    
    # 尝试在句子边界截断
    truncated = text[:max_len]
    for punct in ["，", "。", "！", "？", ",", ".", "!"]:
        idx = truncated.rfind(punct)
        if idx > 10:
            return truncated[:idx + 1]
    
    return truncated + "..."


def _build_initial_relational_state(relationships: List[Any], entities: List[Any]) -> str:
    """
    构建初始关系状态锁。
    
    基于 relationships 列表生成关系状态描述
    """
    if not relationships:
        return ""
    
    rel_descriptions = []
    for rel in relationships:
        source = rel.source_character.name if hasattr(rel, 'source_character') and rel.source_character else "?"
        target = rel.target_character.name if hasattr(rel, 'target_character') and rel.target_character else "?"
        rel_type = rel.relation_type if hasattr(rel, 'relation_type') else "未知关系"
        affinity = rel.affinity_score if hasattr(rel, 'affinity_score') else 0
        
        # 将数值亲和度转化为描述
        if affinity <= -50:
            affinity_desc = "敌对"
        elif affinity <= -20:
            affinity_desc = "不信任"
        elif affinity < 20:
            affinity_desc = "中立"
        elif affinity < 50:
            affinity_desc = "友好"
        else:
            affinity_desc = "亲密"
        
        desc = f"{source} ↔ {target}: {rel_type}（{affinity_desc}）"
        
        if hasattr(rel, 'interaction_prompt') and rel.interaction_prompt:
            desc += f" - {rel.interaction_prompt}"
        
        rel_descriptions.append(desc)
    
    return "\n".join(rel_descriptions)


def _merge_relational_delta(current_state: str, delta: str) -> str:
    """
    合并关系变化到当前关系状态锁。
    
    策略：
    - 保留当前状态的主要信息
    - 追加新的变化描述
    - 控制总长度（$$L_{relational} \\le 300$$）
    """
    MAX_LEN = 300
    
    if not delta:
        return current_state
    
    # 简单追加策略
    new_state = f"{current_state}\n[更新]: {delta}" if current_state else delta
    
    if len(new_state) > MAX_LEN:
        # 保留最近的更新
        return new_state[-MAX_LEN:]
    
    return new_state


def _extract_character_prompts_for_beat(
    beat: Optional[dict], 
    dynamic_context: DynamicContext
) -> Optional[dict[str, str]]:
    """
    从 beat 中提取在场角色的静态设定。
    
    用于 OOC 检测时的角色设定参考
    
    Args:
        beat: Beat 数据字典
        dynamic_context: 动态上下文
    
    Returns:
        dict[str, str]: {角色名: 静态设定} 的字典，或 None
    """
    if not beat:
        return None
    
    # 从 beat 提取角色名列表
    pov_character = beat.get("pov_character", "")
    present_characters = beat.get("present_characters", []) or [pov_character] if pov_character else []
    
    # 如果没有角色信息，返回 None
    if not present_characters:
        return None
    
    # 简化实现：返回空字典占位
    # 实际实现中应该：
    # 1. 从 entities 或数据库查询 Character 记录
    # 2. 提取 static_prompt 字段
    # 3. 构建 {角色名: 静态设定} 的字典
    
    return {}  # Placeholder - 实际实现需要接入 Character 查询


# ========================================================================
# 兼容性保留：旧版情绪更新函数
# ========================================================================

async def _update_emotional_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    【兼容性保留】更新情绪暂存器。
    
    职责：基于刚生成的剧情，总结主角心理状态的微小演变。
    
    注意：此函数为旧版实现，新项目请使用 _update_dynamic_state。
    """
    try:
        system_prompt, user_prompt = build_emotional_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
        )
        
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,
            max_tokens=100,
        )
        
        new_emotion = clean_llm_output(response).strip()
        
        # 长度限制
        if len(new_emotion) > 30:
            for punct in [".", "。", ",", "，"]:
                last_punct = new_emotion.rfind(punct, 0, 30)
                if last_punct > 10:
                    new_emotion = new_emotion[:last_punct + 1]
                    break
            else:
                new_emotion = new_emotion[:30] + "..."
        
        return new_emotion
        
    except Exception as e:
        logger.warning(f"[Emotional Update] 情绪更新失败: {e}")
        return current_emotional_state


# ========================================================================
# V3.0: 智能路由三档执行路径
# ========================================================================

async def _execute_fast_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    stats_callback: LLMStatsCallback = None,
) -> List[BeatDraftResult]:
    """
    V3.0 Tier 1: 疾速流 (Fast-Path) - 完全并发版本
    
    特点:
    - 跳过 Scene Intent 和 Subconscious 独立调用
    - 完全并发生成所有 Beat，无视 previous_tail 依赖
    - 单次调用 creative_model 生成正文
    - 跳过 Stitching（直接拼接）
    
    适用场景: 低张力日常剧情 (tension_level 1-2)，追求极致速度
    """
    logger.info("[Fast Path] 启动疾速流生成（完全并发）...")
    
    async def _single_fast_beat(
        beat_index: int,
        beat: dict,
    ) -> BeatDraftResult:
        """单个 Beat 的疾速生成任务。"""
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        target_words = beat.get("word_count_target") or beat.get("target_words", max(200, word_count // max(1, len(beats))))
        
        try:
            # 构建简化版 Prompt（previous_tail 为空，完全无视前文）
            system_prompt, user_prompt = build_fast_path_prompt(
                chapter=chapter,
                book=book,
                beat=beat,
                previous_tail="",  # 疾速流：无视前文
                target_words=target_words,
                previous_summary=previous_summary,
            )
            
            # 单次调用 creative_model
            response = await _call_llm_with_stats(
                stage="fast_path_prose",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=creative_model,
                temperature=0.75,
                max_tokens=_clamp_tokens(target_words),
                beat_index=beat_index,
                stats_callback=stats_callback,
            )
            
            chunk_text = clean_llm_output(response).strip()
            
            return BeatDraftResult(
                beat_id=beat_id,
                beat_index=beat_index,
                scene_intent={"intent_label": "疾速流", "goal": beat.get("summary", "")},
                subconscious_thought="",
                draft_chunk=chunk_text,
                prompts=[{"stage": "FAST_PATH", "system_prompt": system_prompt, "user_prompt": user_prompt}],
                mcts_rollout=None,
            )
        except Exception as e:
            logger.error(f"[Fast Path] Beat {beat_index} 生成失败: {e}")
            return BeatDraftResult(
                beat_id=beat_id,
                beat_index=beat_index,
                scene_intent={"intent_label": "疾速流", "goal": beat.get("summary", "")},
                subconscious_thought="",
                draft_chunk="",
                prompts=[],
                mcts_rollout=None,
            )
    
    # 创建所有 Beat 的并发任务
    tasks = [
        _single_fast_beat(beat_index=i + 1, beat=beat)
        for i, beat in enumerate(beats)
    ]
    
    # 并发执行所有任务
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 处理结果
    processed_results: List[BeatDraftResult] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"[Fast Path] Beat {i+1} 发生异常: {result}")
            beat = beats[i]
            beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
            processed_results.append(BeatDraftResult(
                beat_id=beat_id,
                beat_index=i + 1,
                scene_intent={"intent_label": "疾速流", "goal": beat.get("summary", "")},
                subconscious_thought="",
                draft_chunk="",
                prompts=[],
                mcts_rollout=None,
            ))
        else:
            processed_results.append(result)
    
    logger.info(f"[Fast Path] 疾速流生成完成，共 {len(processed_results)} 个 Beats")
    return processed_results


async def _execute_standard_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[BeatDraftResult]:
    """
    V3.0 Tier 2: 均衡流 (Standard-Path)
    
    特点:
    - 轻量级 Subconscious（关闭 MCTS，单次生成 50 字内心定调）
    - CoreDynamicContext（previous_tail + physical_state_lock）
    - 串行调用 creative_model 生成正文
    - 标准 Reviewing（失败后局部 Refine）
    
    适用场景: 中等张力剧情 (tension_level 3)
    """
    logger.info("[Standard Path] 启动均衡流生成...")
    flags = feature_flags or DraftingFeatureFlags()
    
    # 步骤 A: 轻量级 Scene Intent
    scene_intent_results, scene_intent_prompts_list = await _generate_scene_intent_batch(
        beats=beats,
        chapter=chapter,
        open_hooks=open_hooks,
        api_key=api_key,
        base_url=base_url,
        model=reasoning_model,
        stats_callback=stats_callback,
    )
    
    # 步骤 B: 轻量级 Subconscious（无 MCTS）
    subconscious_results = await _generate_lightweight_subconscious(
        beats=beats,
        scene_intent_results=scene_intent_results,
        chapter=chapter,
        api_key=api_key,
        base_url=base_url,
        model=reasoning_model,
        stats_callback=stats_callback,
    )
    
    # 步骤 C: 串行生成正文（使用简化版 DynamicContext）
    results: List[BeatDraftResult] = []
    previous_tail = ""
    current_physical_lock = physical_state_lock or ""
    
    for i, beat in enumerate(beats):
        beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
        target_words = beat.get("word_count_target") or beat.get("target_words", max(200, word_count // max(1, len(beats))))
        
        # 构建简化版 Prompt（仅使用 previous_tail 和 physical_state_lock）
        system_prompt, user_prompt = build_standard_path_prompt(
            chapter=chapter,
            book=book,
            beat=beat,
            scene_intent=scene_intent_results[i],
            subconscious=subconscious_results[i],
            previous_tail=previous_tail,
            physical_state_lock=current_physical_lock,
            target_words=target_words,
        )
        
        # 调用 creative_model（带统计追踪）
        response = await _call_llm_with_stats(
            stage="standard_path_prose",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=creative_model,
            temperature=0.75,
            max_tokens=_clamp_tokens(target_words),
            beat_index=i + 1,
            stats_callback=stats_callback,
        )
        
        chunk_text = clean_llm_output(response).strip()
        
        # 可选：标准 QC
        if enable_qc:
            chunk_text, _ = await _quick_qc(
                prose_text=chunk_text,
                beat=beat,
                beat_index=i + 1,
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                api_key=api_key,
                base_url=base_url,
                model=creative_model,
                target_words=target_words,
            )
        
        # 更新上下文
        previous_tail = _extract_tail(chunk_text, max_chars=300)
        
        prompts_history = [{
            "stage": "STANDARD_PATH",
            "beat_index": i + 1,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }]
        
        results.append(BeatDraftResult(
            beat_id=beat_id,
            beat_index=i + 1,
            scene_intent=scene_intent_results[i],
            subconscious_thought=subconscious_results[i],
            draft_chunk=chunk_text,
            prompts=prompts_history,
            mcts_rollout=None,
        ))
    
    logger.info(f"[Standard Path] 均衡流生成完成，共 {len(results)} 个 Beats")
    return results


async def _execute_fortress_path(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
    feature_flags: Optional[DraftingFeatureFlags] = None,
    physical_state_lock: Optional[str] = None,
    entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    chapter_assets_schema: str = "",
    stats_callback: LLMStatsCallback = None,
) -> List[BeatDraftResult]:
    """
    V3.0 Tier 3: 堡垒流 (Fortress-Path)
    
    特点:
    - MCTS 三分支 Subconscious 搜索
    - 全部 5 维 DynamicContext
    - Fail-Fast 断言检查
    - 完整 STITCHING -> REVIEWING -> REFINING 闭环
    
    适用场景: 高张力关键剧情 (tension_level 4-5)
    
    注意：此函数保持 V2.5 完整实现，算力全开。
    """
    logger.info("[Fortress Path] 启动堡垒流生成（V2.5 完整管线）...")
    flags = feature_flags or DraftingFeatureFlags()
    stage_start = time.perf_counter()
    
    # ========================================================================
    # 步骤 A: 并行生成轻量级思考层（无文本依赖）
    # ========================================================================
    logger.info("[Draft Stage] 步骤 A: 并行生成 Scene Intent + Subconscious...")
    step_a_start = time.perf_counter()
    
    # A-1: 并行生成 Scene Intent
    scene_intent_results, scene_intent_prompts_list = await _generate_scene_intent_batch(
        beats=beats,
        chapter=chapter,
        open_hooks=open_hooks,
        api_key=api_key,
        base_url=base_url,
        model=reasoning_model,
        stats_callback=stats_callback,
    )
    
    # A-2: 并行生成 Subconscious（依赖 Scene Intent，带 MCTS）
    subconscious_results, mcts_rollout_results, subconscious_prompts_list = await _generate_subconscious_batch(
        beats=beats,
        scene_intent_results=scene_intent_results,
        chapter=chapter,
        entities=entities,
        api_key=api_key,
        base_url=base_url,
        model=reasoning_model,
        stats_callback=stats_callback,
    )
    
    logger.info(f"[Draft Stage] 步骤 A 完成，耗时 {time.perf_counter() - step_a_start:.2f}s")
    
    # ========================================================================
    # 步骤 B-V25: 串行滑动窗口生成正文（Rolling Prefix + DynamicContext）
    # ========================================================================
    logger.info("[Draft Stage] 步骤 B-V25: 串行生成正文（Rolling Prefix + 认知组件）...")
    step_b_start = time.perf_counter()
    
    prose_results = await _generate_prose_serial_v25(
        beats=beats,
        scene_intent_results=scene_intent_results,
        subconscious_results=subconscious_results,
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        api_key=api_key,
        base_url=base_url,
        creative_model=creative_model,
        reasoning_model=reasoning_model,
        word_count=word_count,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        locations=locations,
        enable_qc=enable_qc,
        feature_flags=flags,
        physical_state_lock=physical_state_lock,
        entity_spatial_ledger=entity_spatial_ledger,
        chapter_assets_schema=chapter_assets_schema,
        stats_callback=stats_callback,
    )
    
    logger.info(f"[Draft Stage] 步骤 B-V25 完成，耗时 {time.perf_counter() - step_b_start:.2f}s")
    
    # ========================================================================
    # 组装结果
    # ========================================================================
    results: List[BeatDraftResult] = []
    for i, beat in enumerate(beats):
        beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
        
        all_prompts = []
        all_prompts.extend(scene_intent_prompts_list[i])
        all_prompts.extend(subconscious_prompts_list[i])
        all_prompts.extend(prose_results[i]["prompts"])
        
        result = BeatDraftResult(
            beat_id=beat_id,
            beat_index=i + 1,
            scene_intent=scene_intent_results[i],
            subconscious_thought=subconscious_results[i],
            draft_chunk=prose_results[i]["text"],
            prompts=all_prompts,
            mcts_rollout=mcts_rollout_results[i],
        )
        results.append(result)
    
    logger.info(f"[Fortress Path] 堡垒流完成，总耗时 {time.perf_counter() - stage_start:.2f}s")
    return results


def build_fast_path_prompt(
    chapter: Any,
    book: Any,
    beat: dict,
    previous_tail: str,
    target_words: int,
    previous_summary: Optional[str] = None,
) -> tuple[str, str]:
    """V3.0 Fast-Path: 构建疾速流的简化 Prompt"""
    
    pov_character = beat.get("pov_character", "主角")
    location = beat.get("location", "未指定")
    summary = beat.get("summary", "")
    red_lines = beat.get("red_lines", [])
    
    continuity = ""
    if previous_tail:
        continuity = f"\n【前文衔接】必须无缝衔接：{previous_tail}\n"
    
    previous_context = ""
    if previous_summary:
        previous_context = f"\n【前情回顾】{previous_summary}\n"
    
    red_lines_text = ""
    if red_lines:
        red_lines_text = f"\n【红线约束】{', '.join(red_lines)}"
    
    system_prompt = f"""你是专业小说写手。请根据以下信息直接生成小说正文。

【章节背景】{getattr(chapter, 'chapter_name', f'第{getattr(chapter, "chapter_number", 1)}章')}
【角色视角】{pov_character}
【场景地点】{location}{previous_context}{continuity}{red_lines_text}

要求：
1. 直接输出小说正文，不要解释、不要总结
2. 紧扣剧情目标，不偏离红线约束
3. 字数约 {target_words} 字，允许适度超出
4. 保持叙事连贯性，与前文无缝衔接
5. 使用自然流畅的文学语言，避免AI腔
"""
    
    user_prompt = f"【剧情目标】{summary}\n\n请生成以上内容的小说正文："
    
    return system_prompt, user_prompt


def build_standard_path_prompt(
    chapter: Any,
    book: Any,
    beat: dict,
    scene_intent: dict,
    subconscious: str,
    previous_tail: str,
    physical_state_lock: str,
    target_words: int,
) -> tuple[str, str]:
    """V3.0 Standard-Path: 构建均衡流的 Prompt"""
    
    pov_character = beat.get("pov_character", "主角")
    location = beat.get("location", "未指定")
    summary = beat.get("summary", "")
    
    continuity = ""
    if previous_tail:
        continuity = f"\n【前文衔接】必须无缝衔接：{previous_tail}\n"
    
    physical_context = ""
    if physical_state_lock:
        physical_context = f"\n【物理状态锁】{physical_state_lock}\n"
    
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
"""
    
    user_prompt = f"【剧情目标】{summary}\n\n请生成以上内容的小说正文："
    
    return system_prompt, user_prompt


async def _generate_lightweight_subconscious(
    beats: List[dict],
    scene_intent_results: List[dict],
    chapter: Any,
    api_key: str,
    base_url: str,
    model: str,
    stats_callback: LLMStatsCallback = None,
) -> List[str]:
    """
    V3.0 Standard-Path: 轻量级 Subconscious（无 MCTS，单次生成 50 字内心定调）
    """
    async def _single_lightweight(beat: dict, scene_intent: dict, beat_index: int) -> str:
        system_prompt = "你是一位擅长内心独白描写的作家。请用一句话（50字以内）概括角色此刻的内心状态。"
        
        pov_character = beat.get("pov_character", "主角")
        goal = scene_intent.get("goal", beat.get("summary", ""))
        
        user_prompt = f"""角色：{pov_character}
场景目标：{goal}

请输出角色此刻的内心独白（一句话，50字以内）："""
        
        try:
            response = await _call_llm_with_stats(
                stage="lightweight_subconscious",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.4,
                max_tokens=100,
                beat_index=beat_index,
                stats_callback=stats_callback,
            )
            thought = clean_llm_output(response).strip()
            # 限制长度
            if len(thought) > 60:
                thought = thought[:57] + "..."
            return thought
        except Exception as e:
            logger.warning(f"[Lightweight Subconscious] 生成失败: {e}")
            return f"{pov_character}深吸一口气，准备面对接下来的挑战。"
    
    tasks = [
        _single_lightweight(beat, scene_intent_results[i], i + 1)
        for i, beat in enumerate(beats)
    ]
    return await asyncio.gather(*tasks)

"""
思考层生成模块 - Scene Intent + Subconscious 批量并行生成。

职责：提供起草阶段的思考层（Scene Intent / Subconscious）批量生成功能。

主要功能：
- _generate_scene_intent_batch: 批量并行生成 Scene Intent
- _generate_subconscious_batch: 批量并行生成 Subconscious（含 MCTS）
- _generate_lightweight_subconscious: 轻量级 Subconscious（无 MCTS）
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

from backend.services.prompts import (
    build_scene_intent_prompt,
    parse_scene_intent_result,
    build_subconscious_prompt,
)
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output

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
    reasoning_config: Optional[dict] = None,
) -> str:
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


async def _generate_scene_intent_batch(
    beats: List[dict],
    chapter: Any,
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    model: str,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
) -> tuple[List[dict], List[List[dict]]]:
    """
    批量并行生成 Scene Intent。

    为每个 Beat 生成场景意图分析（目标/风险/约束），用于后续 Subconscious 和 Prose 生成。

    Args:
        beats: 节拍数据列表
        chapter: 章节实体
        open_hooks: 开放伏笔列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        stats_callback: 统计回调
        reasoning_config: 推理配置

    Returns:
        tuple[List[dict], List[List[dict]]]: (Scene Intent 结果列表, Prompt 历史列表)
    """
    logger.info(f"[Scene Intent] 启动批量生成，共 {len(beats)} 个 Beats")

    async def _single_scene_intent(beat_index: int, beat: dict) -> tuple[int, dict, list]:
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        try:
            beat_hooks = _build_beat_hooks(beat, open_hooks, beat_index)

            system_prompt, user_prompt = build_scene_intent_prompt(
                chapter=chapter,
                beat=beat,
                open_hooks=beat_hooks,
            )

            prompts_history = [{
                "stage": "SCENE_INTENT",
                "beat_index": beat_index,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }]

            response = await _call_llm_with_stats(
                stage="scene_intent",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
                beat_index=beat_index,
                stats_callback=stats_callback,
                reasoning_config=reasoning_config,
            )

            scene_intent_data = parse_scene_intent_result(response, beat.get("summary", ""))
            return beat_index - 1, scene_intent_data, prompts_history

        except Exception as e:
            logger.error(f"[Scene Intent] Beat {beat_index} 生成失败: {e}")
            return beat_index - 1, {"intent_label": "fallback", "goal": beat.get("summary", "")}, []

    tasks = [_single_scene_intent(i + 1, beat) for i, beat in enumerate(beats)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scene_intents = [None] * len(beats)
    all_prompts = [[] for _ in range(len(beats))]

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[Scene Intent] 任务异常: {result}")
            continue
        idx, intent, prompts = result
        scene_intents[idx] = intent
        all_prompts[idx] = prompts

    for i, intent in enumerate(scene_intents):
        if intent is None:
            scene_intents[i] = {"intent_label": "fallback", "goal": beats[i].get("summary", "")}

    logger.info(f"[Scene Intent] 批量生成完成")
    return scene_intents, all_prompts


async def _generate_subconscious_batch(
    beats: List[dict],
    scene_intent_results: List[dict],
    chapter: Any,
    entities: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
) -> tuple[List[str], List[Optional[list]], List[List[dict]]]:
    """
    批量并行生成 Subconscious（含 MCTS 三分支搜索）。

    Args:
        beats: 节拍数据列表
        scene_intent_results: Scene Intent 结果列表
        chapter: 章节实体
        entities: 角色实体列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        stats_callback: 统计回调
        reasoning_config: 推理配置

    Returns:
        tuple: (Subconscious 结果列表, MCTS Rollout 列表, Prompt 历史列表)
    """
    logger.info(f"[Subconscious] 启动批量生成（含 MCTS），共 {len(beats)} 个 Beats")

    async def _single_subconscious(beat_index: int, beat: dict, scene_intent: dict) -> tuple[int, str, Optional[list], list]:
        try:
            system_prompt, user_prompt = build_subconscious_prompt(
                chapter=chapter,
                beat=beat,
                scene_intent=scene_intent,
                pov_character=beat.get("pov_character", "主角"),
            )

            prompts_history = [{
                "stage": "SUBCONSCIOUS",
                "beat_index": beat_index,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }]

            response = await _call_llm_with_stats(
                stage="subconscious",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.4,
                max_tokens=500,
                beat_index=beat_index,
                stats_callback=stats_callback,
                reasoning_config=reasoning_config,
            )

            thought = clean_llm_output(response).strip()

            mcts_rollout = None
            if len(thought) > 100:
                try:
                    parsed = json.loads(thought)
                    if isinstance(parsed, dict) and "branches" in parsed:
                        mcts_rollout = parsed.get("branches", [])
                        thought = parsed.get("selected", thought[:100])
                except json.JSONDecodeError:
                    pass

            return beat_index - 1, thought, mcts_rollout, prompts_history

        except Exception as e:
            logger.error(f"[Subconscious] Beat {beat_index} 生成失败: {e}")
            pov = beat.get("pov_character", "主角")
            return beat_index - 1, f"{pov}深吸一口气，内心涌动着复杂的情感。", None, []

    tasks = [
        _single_subconscious(i + 1, beat, scene_intent_results[i])
        for i, beat in enumerate(beats)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    thoughts = [""] * len(beats)
    rollouts = [None] * len(beats)
    all_prompts = [[] for _ in range(len(beats))]

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[Subconscious] 任务异常: {result}")
            continue
        idx, thought, rollout, prompts = result
        thoughts[idx] = thought
        rollouts[idx] = rollout
        all_prompts[idx] = prompts

    logger.info(f"[Subconscious] 批量生成完成")
    return thoughts, rollouts, all_prompts


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
    轻量级 Subconscious（无 MCTS，单次生成 50 字内心定调）。

    用于 V3.0 均衡流（Standard-Path），跳过 MCTS 三分支搜索。
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

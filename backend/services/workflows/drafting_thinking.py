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
from backend.services.llm import call_llm, call_llm_with_usage
from backend.services.workflows.utils import clean_llm_output

LLMStatsCallback = Optional[Callable[[str, float, bool, Optional[int]], None]]


async def _call_llm_with_stats(
    stage: str,
    *,
    model: Optional[str] = None,
    model_type: Optional[str] = None,
    system_prompt: str = "",
    user_prompt: str = "",
    temperature: float = 0.7,
    max_tokens: int = 2000,
    response_format: Optional[dict] = None,
    top_p: float = 1.0,
    beat_index: Optional[int] = None,
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
    recorder: Optional[Any] = None,
) -> str:
    """带 stats 回调与观测层记录的 LLM 调用封装。

    职责：在原 call_llm 基础上采集耗时/成功状态（stats_callback），
         若传入 recorder（RunRecorder），额外记录 usage/degraded 到观测层。

    Args:
        recorder: 可选的 RunRecorder 实例。传入时自动包装 record_call。
                  None 时仅采集 stats，不落库 generation_runs。
    """
    start_time = time.perf_counter()
    success = True
    try:
        if recorder is not None:
            # 观测层路径：包装 record_call 采集 usage（含 thinking 拆分）
            slot = model_type or "default"
            async with recorder.record_call(stage=stage, model_slot=slot) as ctx:
                result = await call_llm_with_usage(
                    model=model,
                    model_type=model_type or "default",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    top_p=top_p,
                    reasoning_config=reasoning_config,
                )
                ctx.set_result(result)
            return result.content
        else:
            # 无 recorder：走旧路径（内部仍走 call_llm_with_usage，但不落库）
            return await call_llm(
                model=model,
                model_type=model_type or "default",
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
                model_type="reasoning",
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
                entities=entities,
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
                model_type="reasoning",
                temperature=0.55,
                max_tokens=500,
                beat_index=beat_index,
                stats_callback=stats_callback,
                reasoning_config=reasoning_config,
            )

            thought = clean_llm_output(response).strip()

            # 新 subconscious 输出纯文本，不再解析 JSON
            # 若模型仍输出 JSON（兼容旧行为），尝试提取文本内容
            mcts_rollout = None
            if thought.startswith("{"):
                try:
                    parsed = json.loads(thought)
                    if isinstance(parsed, dict):
                        mcts_rollout = parsed.get("mcts_rollout") or parsed.get("branches")
                        thought = parsed.get("best_subconscious") or parsed.get("selected") or thought
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


async def _generate_intent_and_sketch_batch(
    beats: List[dict],
    chapter: Any,
    open_hooks: List[dict],
    stats_callback: LLMStatsCallback = None,
    reasoning_config: Optional[dict] = None,
    recorder: Optional[Any] = None,
) -> tuple[List[dict], List[str], List[List[dict]]]:
    """
    合并批量生成 Scene Intent + Emotional Sketch。

    将原先两次独立的 LLM 调用（Scene Intent + Subconscious）合并为一次调用，
    输出 JSON 包含 scene_intent 和 subconscious 两个字段。

    Returns:
        tuple: (Scene Intent 列表, Subconscious 列表, Prompt 历史列表)
    """
    logger.info(f"[Intent+Sketch] 启动合并批量生成，共 {len(beats)} 个 Beats")

    async def _single(beat_index: int, beat: dict) -> tuple[int, dict, str, list]:
        try:
            beat_hooks = _build_beat_hooks(beat, open_hooks, beat_index)

            pov_character = beat.get("pov_character", "主角")
            summary = beat.get("summary", "")
            goal = beat.get("action_summary", summary)
            entry_state = beat.get("entry_state", "")
            red_lines = beat.get("red_lines", [])
            red_lines_text = "；".join(red_lines) if red_lines else "无"

            # 合并的 system prompt：同时承担场景分析和内心描写指导
            system_prompt = """你是场景分析师兼内心描写作家。

请分析给定的剧情节拍，输出 JSON 包含两部分：
1. scene_intent：场景意图分析（goal/stakes/constraints）
2. subconscious：角色此刻的内心状态速写（100-150字自由文本）

输出格式：
{
  "scene_intent": {
    "intent_label": "场景标签",
    "goal": "本场景目标",
    "stakes": "失败代价",
    "constraints": ["约束1", "约束2"]
  },
  "subconscious": "角色内心流动的纯文本..."
}"""

            # 合并的 user prompt：同时包含场景信息和角色状态
            hooks_text = ""
            if beat_hooks:
                hooks_text = "【相关伏笔】\n" + "\n".join([h.get("content", "") for h in beat_hooks[:3]])

            user_prompt = f"""【剧情节拍】
角色：{pov_character}
剧情：{summary}
场景目标：{goal}
切入状态：{entry_state}
红线：{red_lines_text}
{hooks_text}

请输出 JSON。"""

            prompts_history = [{
                "stage": "INTENT_AND_SKETCH",
                "beat_index": beat_index,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }]

            response = await _call_llm_with_stats(
                stage=f"intent_and_sketch.beat_{beat_index}",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.35,
                response_format={"type": "json_object"},
                max_tokens=800,
                beat_index=beat_index,
                stats_callback=stats_callback,
                reasoning_config=reasoning_config,
                recorder=recorder,
            )

            raw = clean_llm_output(response).strip()
            parsed = json.loads(raw)

            scene_intent = parsed.get("scene_intent", {})
            if not isinstance(scene_intent, dict):
                scene_intent = {}
            scene_intent.setdefault("intent_label", "合并生成")
            scene_intent.setdefault("goal", summary)

            subconscious = str(parsed.get("subconscious", "")).strip()
            if not subconscious:
                subconscious = f"{pov_character}深吸一口气，准备面对接下来的挑战。"

            return beat_index - 1, scene_intent, subconscious, prompts_history

        except Exception as e:
            logger.error(f"[Intent+Sketch] Beat {beat_index} 生成失败: {e}")
            pov = beat.get("pov_character", "主角")
            fallback_intent = {"intent_label": "fallback", "goal": beat.get("summary", "")}
            fallback_sub = f"{pov}深吸一口气，准备面对接下来的挑战。"
            return beat_index - 1, fallback_intent, fallback_sub, []

    tasks = [_single(i + 1, beat) for i, beat in enumerate(beats)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    scene_intents = [None] * len(beats)
    subconsciouses = [""] * len(beats)
    all_prompts = [[] for _ in range(len(beats))]

    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[Intent+Sketch] 任务异常: {result}")
            continue
        idx, intent, sub, prompts = result
        scene_intents[idx] = intent
        subconsciouses[idx] = sub
        all_prompts[idx] = prompts

    for i, intent in enumerate(scene_intents):
        if intent is None:
            scene_intents[i] = {"intent_label": "fallback", "goal": beats[i].get("summary", "")}

    logger.info(f"[Intent+Sketch] 合并批量生成完成")
    return scene_intents, subconsciouses, all_prompts


async def _generate_lightweight_subconscious(
    beats: List[dict],
    scene_intent_results: List[dict],
    chapter: Any,
    stats_callback: LLMStatsCallback = None,
) -> List[str]:
    """
    情绪锚点速写（无 MCTS，自由流动的内心描写）。

    用于 V4.0 均衡流（Standard-Path），用 100-150 字的自由内心流动替代机械化的 MCTS 决策树。
    目的是给正文生成提供"情感温度"和"心理质感"，而非理性推演。
    """
    async def _single_emotional_sketch(beat: dict, scene_intent: dict, beat_index: int) -> str:
        pov_character = beat.get("pov_character", "主角")
        goal = scene_intent.get("goal", beat.get("summary", ""))
        entry_state = beat.get("entry_state", "")
        red_lines = beat.get("red_lines", [])
        physical_state = beat.get("pov_perception_state", "")

        red_lines_text = "；".join(red_lines) if red_lines else "无"

        system_prompt = "你是擅长捕捉人物内心状态的作家。请描写角色此刻的心理流动，不要分析、不要打分、不要结构化。"

        user_prompt = f"""角色：{pov_character}
切入状态：{entry_state}
场景目标：{goal}
物理知觉：{physical_state if physical_state else "未指定"}
不可触碰的底线：{red_lines_text}

请写一段角色此刻的内心状态（100-150字）：
• 可以是混乱的、矛盾的、不连贯的
• 允许有身体的细微反应（口干、心跳、耳鸣）
• 允许有与当前主线无关的记忆闪回
• 不要解释"为什么"，只呈现"是什么"
• 不要输出 JSON、不要分点、不要编号

直接输出内心描写的纯文本。"""

        try:
            response = await _call_llm_with_stats(
                stage="emotional_sketch",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.6,
                max_tokens=300,
                beat_index=beat_index,
                stats_callback=stats_callback,
            )
            thought = clean_llm_output(response).strip()
            # 兜底：如果过长截断，过短保留
            if len(thought) > 200:
                thought = thought[:197] + "..."
            return thought
        except Exception as e:
            logger.warning(f"[Emotional Sketch] 生成失败: {e}")
            return f"{pov_character}的呼吸有些不稳，指尖微微发凉。"

    tasks = [
        _single_emotional_sketch(beat, scene_intent_results[i], i + 1)
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

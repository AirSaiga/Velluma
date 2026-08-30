# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
Phase 2: 远端锚设计器（Anchor Designer，V3.2 §4.2，核心创新 #1）。

职责：
- 1 次 reasoning LLM 调用，设计高潮点 + 前置条件 + 情绪曲线
- 强制关联：spine_track.must_plant_hooks 的每个钩子必须转化为对应 Precondition

设计意图：
- 这是 ADF 的"设计阶段"——只设计目标和条件，不设计铺垫路径
- preconditions 是无序的状态集合（不是节点序列），让正向写作时涌现决定埋设位置

业务场景：
- workflows/adf/adf_workflow.py Phase 2 调用

使用方式：
    anchor = await design_chapter_climax(
        chapter=chapter, chapter_card=cc, spine=spine,
        previous_summary=..., open_hooks=..., entities=...,
        recorder=recorder,
    )
"""

import json
import logging
import re
from typing import Any, Dict, Optional

from backend.services.llm import call_llm_with_usage
from backend.services.observability.run_recorder import RunRecorder
from backend.services.prompts.adf_prompts import build_anchor_design_prompt
from backend.services.workflows.adf.story_context_builder import (
    format_entry_state_for_prompt,
    format_exit_expectation_for_prompt,
    format_chapter_position_for_prompt,
)
from backend.services.workflows.adf.types import (
    ChapterClimax,
    ClimaxSpec,
    Precondition,
    EmotionCurve,
    EmotionCurveSample,
)

logger = logging.getLogger(__name__)


def _extract_json(content: str) -> Optional[dict]:
    """从 LLM 返回（可能含围栏或自由文本）中抽取 JSON 对象。"""
    if not content:
        return None
    # 先尝试 ```json ... ``` 围栏
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass
    # 再尝试找最大的 {...}
    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass
    return None


def _parse_climax(data: dict) -> ClimaxSpec:
    c = data.get("climax") or {}
    return ClimaxSpec(
        description=str(c.get("description", "")).strip(),
        emotional_target=str(c.get("emotional_target", "")).strip(),
        payoff_question=str(c.get("payoff_question", "")).strip(),
        open_question=str(c.get("open_question", "")).strip(),
        intensity=max(1, min(10, int(c.get("intensity", 5) or 5))),
    )


def _parse_preconditions(data: dict) -> list:
    pcs = data.get("preconditions") or []
    result = []
    for i, pc in enumerate(pcs):
        if not isinstance(pc, dict):
            continue
        pc_id = str(pc.get("id") or f"PC_{i:02d}").strip()
        category = str(pc.get("category", "role")).strip()
        description = str(pc.get("description", "")).strip()
        terms = pc.get("must_use_terms") or []
        if isinstance(terms, str):
            terms = [t.strip() for t in terms.split("、") if t.strip()]
        terms = [str(t).strip() for t in terms if str(t).strip()]
        offset = int(pc.get("min_landing_offset", 0) or 0)
        result.append(Precondition(
            id=pc_id,
            category=category,
            description=description,
            must_use_terms=terms,
            min_landing_offset=max(0, offset),
        ))
    return result


def _parse_emotion_curve(data: dict) -> EmotionCurve:
    ec = data.get("emotion_curve") or {}
    samples_raw = ec.get("samples") or []
    samples = []
    for s in samples_raw:
        if not isinstance(s, dict):
            continue
        try:
            samples.append(EmotionCurveSample(
                progress=max(0.0, min(1.0, float(s.get("progress", 0)))),
                register=str(s.get("register", "?")).strip(),
                energy=max(1, min(10, int(s.get("energy", 5)))),
            ))
        except (TypeError, ValueError):
            continue
    # 至少保证入口和 climax 两个点
    if len(samples) < 2:
        samples = [
            EmotionCurveSample(progress=0.0, register="入口", energy=2),
            EmotionCurveSample(progress=1.0, register="收束", energy=5),
        ]
    # 按 progress 排序
    samples.sort(key=lambda s: s.progress)
    return EmotionCurve(samples=samples)


def _ensure_hooks_have_preconditions(
    anchor: ChapterClimax,
    must_plant_hooks: list,
) -> ChapterClimax:
    """强制关联：must_plant_hooks 中的每个钩子必须有对应 Precondition。

    如果某个钩子没有对应 Precondition（关键词或描述对不上），
    生成一个补丁 Precondition。
    """
    if not must_plant_hooks:
        return anchor
    for hook in must_plant_hooks:
        # 检查现有 preconditions 是否已覆盖此 hook
        covered = False
        for pc in anchor.preconditions:
            if hook in pc.description or any(hook in t for t in pc.must_use_terms):
                covered = True
                break
        if not covered:
            # 补一个 Precondition
            pc_id = f"PC_HOOK_{abs(hash(hook)) % 1000:03d}"
            anchor.preconditions.append(Precondition(
                id=pc_id,
                category="foreshadow",
                description=f"必须埋设钩子（来自脉络轨）：{hook}",
                must_use_terms=[],  # 钩子无强制关键词，靠语义
                min_landing_offset=300,
            ))
            logger.info(f"[ADF] 为钩子 '{hook[:50]}' 补丁生成 Precondition {pc_id}")
    return anchor


async def design_chapter_climax(
    chapter: Any,
    chapter_card: Any,
    spine: Any,
    previous_summary: Any,
    rolling_summary: Any,
    open_hooks: Any,
    entities: Any,
    recorder: Optional[RunRecorder] = None,
    canon_context: str = "",
    author_intent: str = "",
    expectation_actions: Optional[Dict[str, str]] = None,
) -> ChapterClimax:
    """Phase 2: 设计远端锚（1 次 reasoning LLM）。

    Args:
        chapter: Chapter ORM
        chapter_card: ChapterCard ORM
        spine: StoryContext dataclass（Phase 1 产出）
        previous_summary: 前章摘要
        rolling_summary: 全书滚动摘要
        open_hooks: 开放伏笔
        entities: 本章角色列表
        recorder: RunRecorder（可选）
        canon_context: V4.0 作者脑中世界图谱文本（private 节点绝不许泄露到正文）
        author_intent: V4.2 介入点 1 作者意图汇总（强约束）
        expectation_actions: V4.2 作者对每个期待的处理决策（覆盖自动推断）

    Returns:
        ChapterClimax
    """
    # 抽取 prompt 输入
    purpose = ""
    must_hit_events_text = "（未指定）"
    if chapter_card is not None:
        purpose = (getattr(chapter_card, "purpose", "") or "").strip()
        events = getattr(chapter_card, "must_hit_events", []) or []
        if isinstance(events, list) and events:
            lines = []
            for ev in events[:5]:
                if isinstance(ev, dict):
                    event_text = ev.get("event", "") or ""
                    emotion = ev.get("emotion", "") or ""
                    line = f"- {event_text}"
                    if emotion:
                        line += f"（情绪：{emotion}）"
                    lines.append(line)
            must_hit_events_text = "\n".join(lines) if lines else "（未指定）"
    if not purpose:
        goals = getattr(chapter, "chapter_goals", []) or []
        if isinstance(goals, list) and goals:
            purpose = "；".join(str(g) for g in goals[:3])
        else:
            outline = getattr(chapter, "outline_text", "") or ""
            purpose = outline[:300] if outline else "（未提供）"

    # 前文张力
    tension_parts = []
    if previous_summary:
        tension_parts.append(f"前一章结尾：{str(previous_summary)[:500]}")
    if rolling_summary:
        tension_parts.append(f"全书进展：{str(rolling_summary)[:800]}")
    previous_tension = "\n\n".join(tension_parts) if tension_parts else "（本章是第一章或无前文）"

    # 开放伏笔
    hook_lines = []
    for h in (open_hooks or [])[:5]:
        if isinstance(h, dict):
            content = h.get("content", "") or ""
        else:
            content = str(getattr(h, "content", "") or "")
        if content:
            hook_lines.append(f"- {content[:100]}")
    open_hooks_text = "\n".join(hook_lines) if hook_lines else "（无）"

    # 角色
    char_lines = []
    for ent in (entities or [])[:8]:
        char = getattr(ent, "character", None)
        if char is None:
            continue
        name = getattr(char, "name", "") or "未命名"
        static = (getattr(char, "static_prompt", "") or "").strip()
        if static:
            static = static[:120] + ("…" if len(static) > 120 else "")
            char_lines.append(f"- {name}：{static}")
        else:
            char_lines.append(f"- {name}")
    characters_text = "\n".join(char_lines) if char_lines else "（未指定）"

    # 构造 prompt
    system_prompt, user_prompt = build_anchor_design_prompt(
        purpose=purpose,
        must_hit_events=must_hit_events_text,
        entry_state=format_entry_state_for_prompt(spine),
        exit_expectation=format_exit_expectation_for_prompt(spine),
        chapter_position=format_chapter_position_for_prompt(spine),
        must_plant_hooks=spine.must_plant_hooks,
        must_resolve_hooks=spine.must_resolve_hooks,
        character_arc_advances=spine.character_arc_advances,
        previous_tension=previous_tension,
        open_hooks=open_hooks_text,
        characters=characters_text,
    )

    # V4.0：把 Canon 上下文（作者脑中世界）作为强约束 prepend 到 system_prompt
    # ★ 核心约束：private 节点的 canon_text 绝不能在生成结果里出现
    if canon_context and canon_context.strip() and canon_context != "（Canon 为空，无强约束）":
        system_prompt = (
            f"# ★★★ 作者脑中世界（Canon，最高优先级约束）★★★\n\n"
            f"{canon_context}\n\n"
            f"--- 以上 Canon 信息在设计远端锚时必须严格遵守：\n"
            f"- private 字段可作为隐藏动机影响高潮设计，但绝不能在描述里直接说出\n"
            f"- public 已建立事实必须作为 Precondition 纳入（确保连贯）\n"
            f"- 活跃伏笔必须转化为 Precondition\n"
            f"---\n\n"
            f"{system_prompt}"
        )

    # V4.2：把作者意图（介入点 1 的决策汇总）作为强约束 prepend 到 system_prompt
    # ★ 这是作者主权的直接体现——覆盖任何自动推断
    if author_intent and author_intent.strip():
        expectation_hint = ""
        if expectation_actions:
            exp_lines = []
            for eid, action in expectation_actions.items():
                action_label = {
                    "accumulate": "继续累积（卡爽点）",
                    "payoff": "释放（爽点）",
                    "ignore": "本章不涉及",
                }.get(action, action)
                exp_lines.append(f"- 期待 {eid}: {action_label}")
            expectation_hint = "\n\n## 作者对本章期待的明确决策（覆盖任何自动推断）\n" + "\n".join(exp_lines)

        system_prompt = (
            f"# ★★★ 作者意图（介入点 1 确认，最高优先级）★★★\n\n"
            f"作者对本章的明确意图：{author_intent}{expectation_hint}\n\n"
            f"--- 设计远端锚时必须严格遵守：\n"
            f"- 作者说'释放'的期待，本章 climax 必须释放\n"
            f"- 作者说'累积/卡爽点'的期待，本章不许释放\n"
            f"- 作者补充的意图作为情绪曲线/climax 设计的硬约束\n"
            f"---\n\n"
            f"{system_prompt}"
        )

    # 调用 LLM
    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="adf.anchor_design",
                model_slot="reasoning",
            ) as call_ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="reasoning",
                    temperature=0.4,
                    max_tokens=4096,
                )
                call_ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="reasoning",
                temperature=0.4,
                max_tokens=4096,
            )
    except Exception as e:
        logger.warning(f"[ADF] 远端锚设计 LLM 调用失败，降级默认锚: {e}")
        # 降级：用大纲第一句作为 climax description，无 preconditions
        return ChapterClimax(
            climax=ClimaxSpec(
                description=(purpose or "本章核心场景")[:200],
                emotional_target="（未指定）",
                intensity=5,
            ),
            preconditions=[],
            emotion_curve=EmotionCurve(samples=[
                EmotionCurveSample(progress=0.0, register="入口", energy=2),
                EmotionCurveSample(progress=1.0, register="收束", energy=5),
            ]),
        )

    # 解析
    data = _extract_json(result.content)
    if not data:
        logger.warning(f"[ADF] 远端锚设计 JSON 解析失败，降级默认锚")
        return ChapterClimax(
            climax=ClimaxSpec(description=(purpose or "本章核心场景")[:200], intensity=5),
            preconditions=[],
            emotion_curve=EmotionCurve(samples=[
                EmotionCurveSample(progress=0.0, register="入口", energy=2),
                EmotionCurveSample(progress=1.0, register="收束", energy=5),
            ]),
        )

    anchor = ChapterClimax(
        climax=_parse_climax(data),
        preconditions=_parse_preconditions(data),
        emotion_curve=_parse_emotion_curve(data),
    )

    # 强制关联：钩子必须有对应 Precondition
    anchor = _ensure_hooks_have_preconditions(anchor, spine.must_plant_hooks)

    logger.info(
        f"[ADF] 远端锚设计完成：climax intensity={anchor.climax.intensity}, "
        f"{len(anchor.preconditions)} 个 preconditions, "
        f"{len(anchor.emotion_curve.samples)} 个曲线采样点"
    )
    return anchor

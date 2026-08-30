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
场景意图提示词模块 - Scene Intent 生成提示词。

职责：
- 提供场景意图（Scene Intent）分析的提示词构建
- 定义不同节奏类型的微指令
- 构建场景意图分析的用户提示

业务场景：
- 起草阶段的场景意图分析
- 为每个 Beat 生成场景意图指导

主要功能：
- 节奏类型微指令定义
- 场景意图提示构建
- 上下文渲染

依赖项：
- backend.models: 数据模型

使用方式：
    prompt = build_scene_intent_prompt(chapter, beat, ...)
"""

import re
import json

from backend.models import Chapter


PACING_MICRO_INSTRUCTIONS = {
    "slow_burn": [
        "单段只推进一个小动作，不触发关系爆点",
        "增加环境或心理层面的细节垫层，避免结论跳跃",
        "冲突表达以试探、停顿、回避为主，不直接摊牌",
    ],
    "fast_paced": [
        "每段至少出现一个可见动作变化，减少铺垫冗余",
        "优先保留关键决策与结果反馈，压缩背景解释",
        "句式更短、更直接，推动信息快速抵达",
    ],
    "balanced": [
        "动作推进与情绪描写保持均衡，避免单侧堆叠",
        "每段包含一次可感知变化并补充必要动机",
        "冲突与缓冲交替出现，保持阅读节奏稳定",
    ],
}


def build_scene_intent_prompt(
    chapter: Chapter,
    beat: dict,
    open_hooks: list = None,
    anchor_pov: str = None,
    original_actor: str = None,
):
    """
    构建场景意图分析 prompt。

    Args:
        chapter: 章节对象
        beat: 节拍数据字典，需包含 summary、position、exit_state、original_actor 等字段
        open_hooks: 开放伏笔列表
        anchor_pov: 锁定的绝对主视角角色名，若与 beat 的 original_actor 不同则触发感官转化约束
        original_actor: 显式传入的执行者角色名，优先级高于 beat.original_actor

    Returns:
        (system_prompt, user_prompt) 元组
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_summary = beat.get("summary", "")
    beat_original_actor = original_actor or beat.get("original_actor") or ""
    pacing_style = str(getattr(chapter, "pacing_style", "balanced") or "balanced").strip() or "balanced"
    if pacing_style not in PACING_MICRO_INSTRUCTIONS:
        pacing_style = "balanced"
    pacing_micro_lines = PACING_MICRO_INSTRUCTIONS[pacing_style]
    exit_state = str(beat.get("exit_state") or "").strip() or "停在当前 beat 的收束状态，不越界推进"

    # V4.0: 检测 ensemble 模式并构建多角色目标区块
    pov_mode = beat.get("pov_mode", "single") or "single"
    pov_characters_list = beat.get("pov_characters", []) or []
    is_ensemble = pov_mode in ("ensemble", "omniscient") and len(pov_characters_list) >= 2

    ensemble_section = ""
    if is_ensemble:
        chars_str = "\n".join([f"  - 【{c}】" for c in pov_characters_list])
        mode_label = "多角色共存" if pov_mode == "ensemble" else "全知"
        ensemble_section = f"""
[视角策略：{mode_label}模式]
本 Beat 采用【{mode_label}】视角，以下角色均需内心展现：
{chars_str}
- constraints 中必须为每个角色指定其动机目标（格式：“[角色名]目标：...”）
- 确保每个角色在生成文本中至少获得一次内心切入
"""

    sensory_transform_constraint = ""
    if anchor_pov and beat_original_actor and anchor_pov != beat_original_actor:
        sensory_transform_constraint = f"""
[特级约束：非主视角事件转化]
当前 Beat 的主要动作是由【{beat_original_actor}】执行的，但本章的绝对锁定视角是【{anchor_pov}】。
你生成的 intent_label 和 constraints 必须包含"感官转化法则"。
**绝对禁止**建议大模型切换镜头去写【{beat_original_actor}】。必须将该事件转化为【{anchor_pov}】在此刻环境中所能感知到的物理异象（如：远处的爆炸闷响、地面的剧震、战术雷达的红光跳动、通讯频道的盲音等）。
"""

    system_prompt = f"""你是场景意图分析师。请根据输入剧情节拍输出 JSON。

输出结构：{sensory_transform_constraint}{ensemble_section}
{{
  "intent_label": "场景标签",
  "goal": "本场景目标",
  "stakes": "失败代价或风险",
  "constraints": ["约束1", "约束2"]
}}

要求：
1. goal 必须具体
2. constraints 必须是字符串数组
3. constraints 中必须包含节奏微观指令，并显式声明"停在 exit_state"
4. 不得让场景推进越过 exit_state
5. 只输出 JSON"""
    open_hooks_text = "暂无开放伏笔"
    if isinstance(open_hooks, list) and open_hooks:
        hook_lines = []
        for item in open_hooks[:6]:
            if not isinstance(item, dict):
                continue
            hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            hook_lines.append(f"- {hook_id}: {content}" if hook_id else f"- {content}")
        if hook_lines:
            open_hooks_text = chr(10).join(hook_lines)
    user_prompt = f"""请为以下章节节拍生成 SceneIntent：

【章节名】{chapter_name}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【节拍位置】{beat.get("position", 1)}
【节拍内容】
{beat_summary}
【节拍收束状态 exit_state】
{exit_state}
【叙事节奏偏好】{pacing_style}
【节奏微观指令（必须写入 constraints）】
- {pacing_micro_lines[0]}
- {pacing_micro_lines[1]}
- {pacing_micro_lines[2]}
【开放伏笔】
{open_hooks_text}"""
    return system_prompt, user_prompt


def parse_scene_intent_result(scene_intent_raw: str, beat_summary: str):
    text = (scene_intent_raw or "").strip()
    candidates = [text] if text else []
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if isinstance(parsed_obj, dict):
        intent_label = str(parsed_obj.get("intent_label") or "").strip() or "推进剧情"
        goal = str(parsed_obj.get("goal") or "").strip() or beat_summary or "推进剧情"
        stakes_raw = parsed_obj.get("stakes")
        stakes = str(stakes_raw).strip() if stakes_raw is not None else ""
        constraints_raw = parsed_obj.get("constraints")
        constraints = [str(item).strip() for item in constraints_raw if str(item).strip()] if isinstance(constraints_raw, list) else []
        sensory_translation_rule = parsed_obj.get("sensory_translation_rule")
        return {
            "intent_label": intent_label,
            "goal": goal,
            "stakes": stakes or None,
            "constraints": constraints,
            "sensory_translation_rule": str(sensory_translation_rule).strip() if sensory_translation_rule is not None else None,
        }
    return {
        "intent_label": "推进剧情",
        "goal": beat_summary or "推进剧情",
        "stakes": None,
        "constraints": [],
        "sensory_translation_rule": None,
    }

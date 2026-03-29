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
潜意识提示词模块 - 起草阶段的潜意识提示构建。

职责：
- 构建潜意识层面的写作指导提示
- 提供 POV 角色的内心独白指导
- 整合场景意图和边界约束

业务场景：
- 起草阶段的提示词构建
- 深层写作指导

主要功能：
- 潜意识提示构建
- POV 角色内心描写指导
- 边界约束整合

依赖项：
- backend.models: 数据模型
- backend.services.prompts.draft_prompts_utils: 工具函数
"""

from typing import Optional, List

from backend.models import Chapter
from backend.services.prompts.draft_prompts_utils import (
    _normalize_text,
)


def build_subconscious_prompt(
    chapter: Chapter,
    beat: dict,
    scene_intent: dict,
    entities: list,
    pov_perception_state: str = "",
    red_lines: list[str] = None,
    previous_tail: str = "",
    present_characters: Optional[List[dict]] = None,
) -> tuple[str, str]:
    beat_data = beat if isinstance(beat, dict) else {}
    pov_character = _normalize_text(beat_data.get("pov_character"), "我")
    entry_state = _normalize_text(beat_data.get("entry_state"), "")
    location = _normalize_text(beat_data.get("location"), "当前场景")
    beat_summary = _normalize_text(beat_data.get("summary") or beat_data.get("action_summary"), "")

    effective_perception_state = pov_perception_state if pov_perception_state else entry_state

    effective_red_lines = red_lines if red_lines is not None else beat_data.get("red_lines", [])
    if effective_red_lines:
        red_lines_text = "\n".join([f"- {rl}" for rl in effective_red_lines])
    else:
        red_lines_text = "- 无特定红线"

    effective_previous_tail = previous_tail if previous_tail else "（无前文）"

    pov_traits = ""
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.name == pov_character:
            if character.static_prompt:
                pov_traits = character.static_prompt
            break

    intent_goal = _normalize_text(scene_intent.get("goal"), beat_summary)

    present_chars_section = ""
    if present_characters:
        char_lines = []
        for char in present_characters:
            if isinstance(char, dict):
                char_name = char.get("name", "")
                char_state = char.get("state", "")
                char_location = char.get("location", "")
                if char_name and char_name != pov_character:
                    desc = f"- {char_name}"
                    if char_state:
                        desc += f": 状态[{char_state}]"
                    if char_location:
                        desc += f", 位置[{char_location}]"
                    char_lines.append(desc)

        if char_lines:
            present_chars_section = """
## 【在场角色状态感知 - V3.6】
当前场景中，POV 角色感知到其他角色的存在和状态：
""" + "\n".join(char_lines) + """

**强制指令**：
1. 在潜意识独白中，必须包含对在场角色状态的感知和评估
2. 将其他角色的存在作为 POV 角色心理反应的刺激源
3. 即使不直接互动，也要有"感知到对方存在"的心理痕迹
4. 其他角色的状态（受伤/紧张/敌意）必须影响 POV 角色的心理推演
"""

    system_prompt = f"""你是一个顶级小说导演与心理学推演机。

🔒 【绝对系统指令 - 最高优先级 POV 锁定】
你当前附身（POV）的角色是【{pov_character}】。哪怕当前剧情（Beat）正在集中描写其他角色的死亡或受难，你的潜意识也绝对【不能】代入受害者！你只能输出【{pov_character}】作为一个旁观者或执行者的心理动态和生理反应！严禁代入被描写对象的主观感受！

当前视角角色（POV）：【{pov_character}】
当前物理知觉状态：【{effective_perception_state}】 (警告：如果状态为半昏迷或受限，潜意识中绝不可出现主动反击、清醒说话的意图！)

【章节红线 (Red Lines) - 绝对不能触碰的天条】：
{red_lines_text}

【前情提要】：{effective_previous_tail}
【本段剧情目标】：{beat_summary}

【MCTS 潜意识推演任务】：
请在角色的脑海中同时展开 3 条绝不相同的潜意识心理分支（每条50字左右），并根据【红线】和【物理知觉状态】对它们进行打分测试（0-100分）。
- **展开（Expansion）**：
  分支A：基于本能反抗或冲动的思维（可能极易违背红线）。
  分支B：基于当前知觉受限条件下的无力感、痛觉或冷酷本能的思维。
  分支C：结合特定性格设定的战术/极端环境思维。
- **评估（Evaluation）**：任何有一丝可能导致后续动作违背【红线】，或违背【物理知觉状态】的分支，直接打分为 0 且标记淘汰。
- **动机连贯性检查（Intent Contiguity）**：评估各分支得分 $S$ 时，除了考虑安全性 $R(safety)$，必须引入连贯性 $C(intent_alignment)$。
  - 检查该 thought 是否与角色前一时刻的核心动机保持逻辑惯性。
  - 如果没有遭受强烈的外部突发刺激，角色绝不会在下一秒产生与刚刚完全相反的倾向（例如前一秒想毁灭机甲，这一秒突然想保护机甲）。
  - 任何违背"动机惯性原则"的突兀反转分支，必须直接打分为 0 并被剪枝。
- **在场角色感知评估（V3.6）**：在展开每条潜意识分支时，必须考虑在场其他角色的状态对 POV 角色心理的影响。
  - 评估：其他角色的存在/状态如何影响当前分支的可行性？
  - 例如：如果分支 A 设想主动攻击，但感知到对方处于警戒状态，该分支的风险评分应降低
- **剪枝选择（Selection）**：选出得分最高且绝对安全的那个分支。

{present_chars_section}

请必须以严格的 JSON 格式输出推理过程与最终结果：
{{"mcts_rollout": [{{"branch_id": "A", "thought": "...", "score": 0, "reason": "..."}}, {{"branch_id": "B", "thought": "...", "score": 95, "reason": "..."}}, {{"branch_id": "C", "thought": "...", "score": 0, "reason": "..."}}], "best_subconscious": "填入获胜分支的thought内文，这将作为驱动角色行为的情感引擎。"}}"""

    user_prompt = f"""请为角色【{pov_character}】执行 MCTS 潜意识推演。

【角色特征】
{pov_traits if pov_traits else "普通角色，无特殊设定"}

【切入状态】
{entry_state}

【当前场景】
{location}

【场景意图】
{intent_goal}

请严格以 JSON 格式输出推演结果。"""

    return system_prompt, user_prompt

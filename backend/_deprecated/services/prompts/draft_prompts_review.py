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
起草微审阅提示词模块 - 起草阶段的微审阅提示。

职责：
- 构建起草阶段的微审阅提示
- 提供物理状态锁验证
- 提供 OOC 检测指导

业务场景：
- 起草完成后的微审阅
- 状态一致性检查

主要功能：
- 微审阅提示构建
- 物理状态验证
- OOC 检测

依赖项：
- backend.services.prompts.draft_prompts_utils: 工具函数
"""

from typing import Optional

from backend.services.prompts.draft_prompts_utils import _normalize_text


def build_micro_review_prompt(
    chunk_text: str,
    physical_state_lock: str,
    pov_character: str = "主角",
    red_lines: Optional[list[str]] = None,
    relational_state_lock: str = "",
    character_static_prompts: Optional[dict[str, str]] = None,
    pov_mode: str = "single",
    pov_characters: Optional[list[str]] = None,
) -> tuple[str, str]:

    relationship_check = ""
    if relational_state_lock:
        relationship_check = """
5. **人物关系硬伤检查**：
   - 死敌之间是否突然无逻辑地友好互动？
   - 信任度极低的角色是否突然共享敏感信息？
   - 角色互动是否符合当前关系状态描述？
   - 关系变化是否有明确的事件驱动？（禁止无逻辑突变）"""

    ooc_check = ""
    if character_static_prompts:
        char_traits = "\n".join([f"     - {name}: {traits[:50]}..."
                                for name, traits in character_static_prompts.items()])
        ooc_check = f"""
6. **OOC（偏离角色设定）检查**：
   角色静态设定参考：
{char_traits}

   检查项：
   - 角色的言行是否符合其性格设定？
   - 角色是否做出了违背其价值观的决定？
   - 角色的反应是否与其过往行为模式一致？
   - 是否出现了"性格突变"而无合理铺垫？"""

    red_lines_check = ""
    if red_lines:
        red_lines_text = "\n     - ".join([""] + list(red_lines))
        red_lines_check = f"""
7. **红线绝对约束检查**：
   以下红线绝对禁止触碰：{red_lines_text}

   判定标准：
   - 任何触碰红线的内容，无论其他检查是否通过，均判定为失败
   - 红线具有最高优先级"""

    ensemble_pov_check = ""
    is_ensemble_review = pov_mode in ("ensemble", "omniscient") and pov_characters and len(pov_characters) >= 2
    if is_ensemble_review:
        chars_str = "、".join(pov_characters)
        ensemble_pov_check = f"""
8. **多视角覆盖检查（ensemble 专属）**：
   本 Beat 视角角色列表：{chars_str}
   检查项：
   - 以上每个角色是否至少获得一次内心独白或主观感知描写？
   - 是否存在某角色全程仅作为背景/道具而无主观视角？
   - 不同角色的声音（语气/词汇/关注点）是否有区分？
   判定：若有角色完全缺席内心展现，判定为失败。"""

    system_prompt = f"""你是一个无情的物理、逻辑与角色一致性断言机（Assertion Checker）。

你的任务：快速检查小说片段是否发生了极其荒谬的物理、逻辑、关系或角色设定崩塌。

【检查项列表】
仔细寻找以下毁灭级幻觉：

1. **物理状态冲突**：肉身喷火、血肉之躯发射激光、徒手举起重物等
2. **装备/能力幻觉**：当前不存在的装备突然使用、未提及的能力突然出现
3. **实体混淆**：已被摧毁的物体重新出现、当前场景不存在的角色突然说话
4. **时空错乱**：时间线跳跃无逻辑、场景切换无过渡{relationship_check}{ooc_check}{red_lines_check}{ensemble_pov_check}

【重要原则】
- 只查硬伤：文字不优美、修辞平淡、节奏拖沓 —— 这些都不属于错误
- 聚焦物理与逻辑：重点关注物理状态、逻辑连贯性、角色一致性
- 关系红线：人物关系的突变必须有明确的事件驱动
- OOC 红线：角色行为必须与其设定一致
- 不评文笔：不要评价写得是否生动、是否有文学性

【输出格式】
必须返回严格的 JSON 格式，不要有任何其他内容：
{{
  "pass_check": true/false,
  "reason": "如果为false，用一句话指出荒谬之处。如果为true则留空。",
  "failed_checks": ["列出失败的检查项编号，如['5', '7']"]
}}"""

    rel_state_section = ""
    if relational_state_lock:
        rel_state_section = f"""
【在场角色关系状态】
{relational_state_lock}"""

    red_lines_section = ""
    if red_lines:
        red_lines_section = f"""
【红线约束（最高优先级）】
{chr(10).join(['- ' + rl for rl in red_lines])}"""

    ensemble_pov_section = ""
    if is_ensemble_review and pov_characters:
        ensemble_pov_section = f"\n【多视角角色列表】\n" + "\n".join([f"- {c}" for c in pov_characters])

    user_prompt = f"""【已知合法状态】
视角角色：{pov_character}{ensemble_pov_section}
物理状态约束：{physical_state_lock if physical_state_lock else "无特殊约束"}{rel_state_section}{red_lines_section}

【待检片段】
{chunk_text}

请执行断言检查，返回 JSON 结果。"""

    return system_prompt, user_prompt


def build_emotional_update_prompt(
    chunk_text: str,
    previous_emotional_state: str,
    pov_character: str = "主角",
    character_static_prompt: str = "",
) -> tuple[str, str]:
    system_prompt = f"""你是一个精通心理学的观察员。你的任务是推演角色在经历刚才的事件后，当下的微观心理状态。

【角色底层性格（绝对引力锚）】：{character_static_prompt}
(注意：无论遇到多大刺激，角色的本能最终都会将其拉回或试图掩盖成这种底层性格)

【前情心理状态】：{previous_emotional_state}
【刚刚发生的剧情】：{chunk_text}

请用极为简短的一句话（20字以内），总结角色此刻的最新心理状态。
公式要求：新情绪 = (外部刺激带来的短暂生理/心理反应) + (被底层性格强压或扭转后的最终表现)
【警告】：严禁让角色发展成与底层性格完全相反的精神病态！

示例输出格式："虽然内心因失控而战栗，但极强的自控力让他表面恢复了冷酷与肃杀。"
"""

    user_prompt = f"""【角色】{pov_character}

【前情中心理状态】
{previous_emotional_state}

【刚刚发生的剧情】
{chunk_text[:500] if len(chunk_text) > 500 else chunk_text}

请总结心理状态演变（20字以内）："""

    return system_prompt, user_prompt


def build_dynamic_state_update_prompt(
    chunk_text: str,
    previous_emotional_state: str,
    pov_character: str = "主角",
    relational_state_lock: str = "",
    beat_context: Optional[dict] = None,
    book_genre: str = "通用小说",
) -> tuple[str, str]:
    beat_info = ""
    if beat_context:
        beat_summary = beat_context.get("summary", "")
        beat_location = beat_context.get("location", "")
        beat_pov = beat_context.get("pov_character", pov_character)
        beat_info = f"""
【当前 Beat 信息】
- 摘要：{beat_summary}
- 地点：{beat_location}
- 视角：{beat_pov}"""

    system_prompt = f"""你是一个无情的战场行为逻辑分析师。
请根据刚才发生的剧情，更新角色的心理状态与实体关系矩阵。

【状态机更新规则】：
新状态 = (受到刺激后的即时反应) - (被该角色底层人设强行修正后的结果)

【词汇清洗协议 - 强制执行】：
1. 必须根据作品基调（{book_genre}）使用严谨的分析判断词汇。
2. 严禁使用任何带有浪漫主义、主观同情或拟人泛滥的词汇。
   禁用词汇黑名单：羁绊、凄美、共生、牺牲、宿命、救赎、灵魂共鸣、命运交织。
3. 角色间的合作或救助行为，必须被翻译为冷硬的分析表述：
   - ✅ "出于战术利益的考量" / "顺位优先级的变更" / "防备下的妥协"
   - ❌ "内心深处的牵绊驱使他伸出了手"

【输出格式要求】：
请严格按以下 JSON 格式输出，不要有任何额外文字：
{{{{
  "new_emotional_state": "角色当前的心理状态（20字以内，强调从前一状态到新状态的演变）",
  "relational_delta": "角色关系的变化（如'与盟友的战术信任度因联合作战小幅上升'，无变化则留空）",
  "beat_summary": "本段剧情的极简一句话摘要（用于宏观剧情累加，40字以内）"
}}}}"""

    user_prompt = f"""【POV角色】{pov_character}

【前情中心理状态】
{previous_emotional_state}

{beat_info}

【当前在场角色关系状态】
{relational_state_lock if relational_state_lock else "未指定"}

【刚刚生成的剧情片段】
{chunk_text[:800] if len(chunk_text) > 800 else chunk_text}

请分析上述剧情，返回 JSON 格式的状态更新结果。"""

    return system_prompt, user_prompt

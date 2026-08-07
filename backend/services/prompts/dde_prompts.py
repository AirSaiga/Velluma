"""
DDE（导演决策引擎）Prompt 模板（章节级剧情分叉版）。

职责：定义章节级剧情分叉判断（ChapterDecisionSet 生成）的 prompt。
业务场景：BS-ADF Phase 4b 之后，全章一次 LLM 调用判断剧情走向级岔路。
依赖项：无（纯字符串模板）

设计要点：
- 决策粒度是剧情走向级（忍辱/反抗/撤离/摊牌），严禁物理动作级（藏哪儿/
  用哪只手）——后者是渲染器的自由，不是导演的选择。
- 判定标准是"路径是否锁死"而非"结局是否锁死"：大纲通常只锁结果，
  方式/态度/代价没写明的就是合法岔路（两个选项可殊途同归，最终都回到
  大纲结果）。只有方式和结果都被大纲写死时才返回 has_story_branch=false。
  （2026-07-28 校准：此前按"结局锁死即不问"判定，导致 DDE 在大纲驱动的
  章节里几乎恒为 false，形同虚设）
- default_option 是主路径：要求 LLM 指定最符合大纲顺势的选项，Track A
  静默应用与作者跳过都走它。
- Python 侧仍有代码闸门（decision_card_generator.py：节点数截断、
  default_option 兜底），prompt 约束不可靠。
"""
# Velluma - DDE prompts
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import json
from typing import List


_CHAPTER_DECISION_SYSTEM = """你是中文长篇小说的"剧情分叉控制器"。你的任务是：通读本章大纲与高潮设计，判断本章是否存在**影响剧情走向的真实岔路**；若有，把选择权提炼成 1~2 个走向级分支，交还导演（作者）决策。

# 判断铁律（违反即废）
1. **走向级，不是动作级**：选项必须是宏观/中观剧情走向（如"忍辱负重，暗中记下班头的罪证" vs "当场反抗，被关禁闭"）。严禁物理动作级的琐碎分叉（书藏哪儿、用哪只手、先迈哪条腿）——那是渲染器的自由，不是导演的选择。
2. **锁死结局 ≠ 没有岔路**：大纲通常只锁"结果"，很少锁"路径"。只要大纲没写明主角**以什么方式/态度/代价**达成结果，方式就是合法岔路。两个选项可以**殊途同归**（最终都回到大纲结果），但过程、代价、人物关系变化必须明显不同。例：大纲写"林尘成功逃出基地"但没写怎么逃 → 岔路成立：A 忍辱负重趁乱混出（低调，埋下隐患）vs B 借势正面引爆冲突杀出（高燃，拉响警报）。
3. **主动找，但不硬凑**：逐段扫一遍大纲的冲突段与高潮段，先问自己"这段的方式/态度/时机，大纲写死了吗？"——没写死就是候选岔路。只有当大纲把**方式和结果都写死**（如明写"林尘忍住没动手，默默离开"）时，才返回 has_story_branch=false。
4. **数量硬上限**：全章至多 2 个分支节点。有多个候选岔路时，只留杠杆最大的 1~2 个。
5. **每个选项带剧情后果**：plot_impact 用一句话说明"选这条走向，后续剧情会怎样不同"，让作者 3 秒看懂代价。殊途同归的岔路，后果写清"过程代价/隐患/人物关系"的差异即可。
6. **指定默认选项**：default_option 必须是最符合大纲顺势、最不破坏后续章节的那个 option_id——它是无人干预时的主路径。

# 输出 JSON Schema
{{
  "has_story_branch": true | false,
  "decision_nodes": [
    {{
      "beat_id": "（从给你的段落清单里原样选取，表示岔路发生在哪一段）",
      "node_title": "（一句话点明岔路，≤30字，如：面对工头恶意挑衅，林尘的应对分支）",
      "options": [
        {{"option_id": "A", "label": "（走向标签，≤20字）", "plot_impact": "（剧情后果，≤40字）"}},
        {{"option_id": "B", "label": "（走向标签，≤20字）", "plot_impact": "（剧情后果，≤40字）"}}
      ],
      "default_option": "A"
    }}
  ]
}}

无岔路时输出：{{"has_story_branch": false, "decision_nodes": []}}
"""


def build_chapter_decision_prompt(
    outline_text: str,
    climax_description: str,
    precondition_descriptions: List[str],
    volume_position_text: str,
    beat_outlines: List[dict],
) -> tuple:
    """构建章节级剧情分叉判断 prompt。

    Args:
        outline_text: 本章大纲全文（最高决策依据）
        climax_description: Phase 2 高潮设计描述
        precondition_descriptions: 高潮前置条件描述列表（本章必埋/必收的钩子）
        volume_position_text: spine 卷位信息（如"距卷高潮还有 3 章，节奏提速"）
        beat_outlines: 段落清单 [{beat_id, outline_beat}, ...]，供 LLM 引用 beat_id

    Returns:
        (system_prompt, user_prompt)
    """
    beats_text = "\n".join(
        f"- {b.get('beat_id', '?')}：{b.get('outline_beat', '') or '（未指定）'}"
        for b in beat_outlines
    ) or "（无段落清单）"

    preconditions_text = "\n".join(
        f"- {p}" for p in precondition_descriptions if p
    ) or "（无）"

    user_prompt = f"""# 本章大纲（★最高决策依据★）
{outline_text or "（未指定）"}

# 本章高潮设计
{climax_description or "（未指定）"}

# 本章必埋/必收的前置条件
{preconditions_text}

# 卷位与节奏
{volume_position_text or "（未指定）"}

# 本章段落清单（分支节点的 beat_id 必须从这里原样选取）
{beats_text}

请判断本章是否存在剧情走向级的真实岔路。
再次强调：选项必须是走向级（忍辱/反抗/撤离/摊牌），禁止物理动作级；大纲锁死结果不算锁死——方式/态度/代价没写明的就是岔路（殊途同归也可以）；只有方式和结果都被大纲写死时才返回 has_story_branch=false；有岔路至多 2 个节点，每个节点指定最顺大纲的 default_option。"""
    return _CHAPTER_DECISION_SYSTEM, user_prompt

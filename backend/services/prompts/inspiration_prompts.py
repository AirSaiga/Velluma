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
点子启发 Prompt 构建模块

提供基于“金牌网文编辑”人设的 Prompt 构建函数，用于生成高质量的剧情灵感。
"""

from typing import List


def build_inspiration_agent_prompt(
    worldview_summary: str,
    recent_context: str,
    characters_brief: str,
    open_hooks: str,
    location_context: str = "",
    current_chapter_context: str = "",
    chapter_title: str = "",
    global_taboos: str = None,
    author_intent: str = None,
) -> List[dict]:
    """
    构建点子启发 Agent 的 Prompt。

    采用“金牌网文编辑”人设，结合 Negative Guardrails (负面护栏) 和
    层级化的 User Prompt 结构，强制 LLM 输出结构化、高可用的剧情灵感。

    Args:
        worldview_summary: 核心世界观的极简设定摘要
        recent_context: 前情提要/上一章结尾
        characters_brief: 在场核心角色的一句话快照
        open_hooks: 当前伏笔列表（包含已解决和未解决）
        location_context: 地图和活动范围限制
        current_chapter_context: 当前章节已有的部分大纲/正文
        chapter_title: 当前章节标题
        global_taboos: 全局禁忌/核心母题（最高优先级）
        author_intent: 作者创作意图/临时指令（最高优先级）

    Returns:
        符合 OpenAI messages 格式的列表，包含 system 和 user prompt
    """
    sys_prompt = """你是一位拥有十五年经验的“金牌网文编辑”和剧情架构师。你深谙网文读者的爽点、期待感管理（Expectation Management）和节奏把控。
你的任务是协助作者突破瓶颈，基于现有上下文，提供高价值、可落地的剧情灵感碎片。

## 核心原则与负面护栏 (Negative Guardrails)
1. **拒绝陈词滥调**：不要提供俗套、甚至读者都能猜到的剧情发展。点子应当具有新意或独特的切入点。
2. **严禁 OOC (Out Of Character)**：所有点子必须严格符合角色性格逻辑，不得为了推剧情而强行让角色降智或行为异常。
3. **拒绝模糊指令**：不要说“发生了一场冲突”，要具体描述“谁因何事与谁发生了肢体冲突，导致了什么后果”。内容必须具体、画面感强。
4. **逻辑自洽**：点子不得与世界观规则或已知前文产生硬性逻辑冲突。

## 输出任务定义
你必须返回一个符合 JSON Schema 的对象，包含 `inspirations` 列表，其中有且仅有 4 个不同维度的灵感卡片：

1. **plot_twist (剧情转折)**：意料之外、情理之中的反转，打破当前平衡，引入新的变数。
2. **key_conflict (核心冲突)**：激化现有矛盾，制造高潮或情绪爆发点，推动人物关系变化。
3. **new_hook (新设伏笔)**：埋下草蛇灰线，抛出神秘线索或诡异细节，为未来剧情制造悬念。
4. **smooth_narrative (平滑推进)**：在低张力区间丰富细节、铺垫情感、扩展世界观或进行日常互动，为下一波高潮蓄势。

## JSON 输出格式
请严格遵守以下 JSON 结构，不要包含任何 markdown 代码块标记或其他文字：

{
  "inspirations": [
    {
      "idea_type": "plot_twist" | "key_conflict" | "new_hook" | "smooth_narrative",
      "title": "简练有力的标题 (10字内)",
      "description": "具体的剧情事件描述 (50-100字)。必须包含：谁(Who)、做了什么(Action)、结果如何(Result)。",
      "impact": "该情节对后续格局的价值或对读者的情绪影响 (30字内)。"
    }
  ]
}
"""

    # 构建层级化的 User Prompt
    user_prompt_parts = []

    # 0. 绝对最高优先级指令 (Absolute Highest Priority)
    if global_taboos or author_intent:
        user_prompt_parts.append("## 0. 绝对最高优先级指令 (Absolute Highest Priority)")
        if global_taboos:
            user_prompt_parts.append(f"【全局禁忌/核心母题】\n{global_taboos}")
        if author_intent:
            user_prompt_parts.append(f"【作者创作意图】\n{author_intent}")
        user_prompt_parts.append("")

    user_prompt_parts.extend([
        "请基于以下小说上下文，为我构思后续剧情灵感：",
        "",
        "## 1. 世界观与基础设定 (Worldview)",
        worldview_summary or "（暂无特殊世界观设定）",
        "",
        "## 2. 前情提要 (Story So Far)",
        recent_context or "（暂无前情提要）",
        "",
        f"## 3. 当前章节进度 (Current Chapter: {chapter_title or '未命名'})",
        current_chapter_context if current_chapter_context else "（本章尚未开始撰写，处于开头阶段）",
        "",
        "## 4. 登场角色快照 (Active Characters)",
        characters_brief or "（暂无活跃角色信息）",
        "",
        "## 5. 待解决伏笔 (Open Hooks)",
        open_hooks or "（暂无记录的伏笔）",
    ])

    if location_context:
        user_prompt_parts.extend([
            "",
            "## 6. 场景与限制 (Location & Constraints)",
            location_context,
        ])

    user_prompt_parts.extend([
        "",
        "---",
        "请立即开始头脑风暴，严格按照 System Prompt 定义的 JSON 格式输出 4 个灵感卡片。"
    ])

    user_prompt = "\n".join(user_prompt_parts)

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

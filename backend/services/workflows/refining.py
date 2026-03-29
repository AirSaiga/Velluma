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

from typing import Any, Optional

from backend.services.prompts import build_refine_agent_prompt
from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter, Book, Character, CharacterRelationship
from backend.services.utils.prompt_logger import PromptLogger


async def refine_draft(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    current_draft: str,
    revision_plan: str,
    word_count: int,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """根据审阅意见精修章节初稿。

    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        current_draft: 当前草稿文本
        revision_plan: 审阅意见/修改计划
        word_count: 目标字数
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name

    Returns:
        str: 精修后的正文
    """
    system_prompt, user_prompt = build_refine_agent_prompt(
        chapter, book, entities, relationships, current_draft, revision_plan, word_count
    )
    
    refined_text = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.7,
        max_tokens=10000,
    )
    
    return clean_llm_output(refined_text)


async def refine_single_beat(
    beat: dict,
    original_chunk: str,
    revision_guide: str,
    issue_descriptions: list[str],
    chapter: Chapter,
    book: Book,
    api_key: str,
    base_url: str,
    model: str,
    previous_tail: str = "",
    beat_id: str = None,
    all_issues: list[dict] = None,
    prompt_logger: Optional[PromptLogger] = None,
) -> str:
    """对单个 Beat 进行精准局部重写。

    基于 Review Agent 给出的审查驳回原因和修改计划，对指定 Beat 的草稿
    进行针对性精修。通过强调驳回原因和具体问题，确保 LLM 严格遵循修改指令。

    【Bug 1 修复 - 精准制导打点精修】
    实现算法：I_k = { i ∈ I | k ∈ i.target_beat_ids }
    只将 target_beat_ids 包含当前 beat_id 的 issues 传入该 beat 的精修。

    Args:
        beat: Beat 信息字典，应包含 summary、pov_character、entry_state、
              exit_state、red_lines 等字段
        original_chunk: 待修改的原始草稿文本
        revision_guide: Review Agent 给出的全局修改计划
        issue_descriptions: 针对该 beat 的具体问题描述列表（兼容性保留）
        chapter: 章节实体
        book: 书籍实体
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        previous_tail: 前一 Beat 的尾巴文本，用于保持语气衔接
        beat_id: 当前 Beat 的唯一标识（用于精准匹配 issues）
        all_issues: Review Agent 返回的所有 issues 列表，包含 target_beat_ids

    Returns:
        str: 精修后的正文
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"

    # =======================================================================
    # Bug 1 修复：精准制导打点精修 - 只传入与当前 beat 相关的 issues
    # 算法：I_k = { i ∈ I | k ∈ i.target_beat_ids }
    # =======================================================================
    targeted_issues = []
    
    if all_issues and isinstance(all_issues, list):
        # 从 beat 中提取 beat_id
        current_beat_id = beat_id or beat.get("beat_id") or beat.get("id")
        if current_beat_id:
            for issue in all_issues:
                if isinstance(issue, dict):
                    target_beat_ids = issue.get("target_beat_ids", [])
                    # 如果 issue 没有指定 target_beat_ids，或包含当前 beat_id，则适用
                    if not target_beat_ids or current_beat_id in target_beat_ids:
                        targeted_issues.append(issue.get("description", ""))
    
    # 合并传入的 issue_descriptions（兼容性处理）
    if issue_descriptions:
        targeted_issues.extend([desc for desc in issue_descriptions if desc])
    
    # 去重
    targeted_issues = list(dict.fromkeys(targeted_issues))

    # 构建问题描述列表
    issues_text = ""
    if targeted_issues:
        issues_list = "\n".join(f"- {desc}" for desc in targeted_issues if desc)
        issues_text = f"""
针对本段的具体问题：
{issues_list}
"""

    # 构建 system_prompt - 强调审查驳回原因与修改指令
    system_prompt = f"""{global_sys_prompt}

你是一个精修编辑。你之前的草稿被编辑驳回，请根据以下修改指令重新生成本段内容。

【审查驳回原因与修改指令】
你之前的草稿被编辑驳回。原因及修改计划如下：
{revision_guide}
{issues_text}
请严格遵守上述修改计划，重新生成本段的内容。保持原有的优秀动作描写，但必须彻底根除上面指出的问题！

## 你的任务
根据修改指令重写片段，保持原有风格和情节连贯性，同时彻底修复指出的所有问题。
直接输出修改后的正文，不要包含任何解释、标题或元信息。"""

    # 提取 beat 信息
    beat_summary = beat.get("summary", "")
    pov_character = beat.get("pov_character", "")
    entry_state = beat.get("entry_state", "")
    exit_state = beat.get("exit_state", "")
    red_lines = beat.get("red_lines", [])

    # 构建红线说明
    red_lines_text = ""
    if red_lines:
        if isinstance(red_lines, list):
            red_lines_text = f"\n【红线（禁止触碰）】\n" + "\n".join(f"- {rl}" for rl in red_lines)
        elif isinstance(red_lines, str):
            red_lines_text = f"\n【红线（禁止触碰）】\n{red_lines}"

    # 构建前文衔接说明
    tail_text = ""
    if previous_tail:
        tail_text = f"""
【前文衔接参考】
以下是前一段的末尾文本，请确保语气和节奏自然衔接：
---
{previous_tail[-500:]}
---
"""

    # 构建 user_prompt
    user_prompt = f"""请重写以下片段：

【剧情摘要】
{beat_summary}

【视角人物】
{pov_character if pov_character else "未指定"}

【入场状态】
{entry_state if entry_state else "未指定"}

【退场状态】
{exit_state if exit_state else "未指定"}
{red_lines_text}
{tail_text}
【待修改的原始草稿】
---
{original_chunk}
---

请直接输出修改后的正文，不要包含任何解释或标记。"""

    if prompt_logger:
        beat_label = f"FUSION_REFINE_BEAT_{beat_id or beat.get('beat_id', 'unknown')}"
        prompt_logger.log_prompts(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=0.7,
            max_tokens=6000,
            prompt_label=beat_label,
        )

    refined_text = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.7,
        max_tokens=6000,
    )

    return clean_llm_output(refined_text)
from typing import Any, Optional

from backend.services.prompts import build_refine_agent_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter, Book, Character, CharacterRelationship


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
) -> str:
    """对单个 Beat 进行精准局部重写。

    基于 Review Agent 给出的审查驳回原因和修改计划，对指定 Beat 的草稿
    进行针对性精修。通过强调驳回原因和具体问题，确保 LLM 严格遵循修改指令。

    Args:
        beat: Beat 信息字典，应包含 summary、pov_character、entry_state、
              exit_state、red_lines 等字段
        original_chunk: 待修改的原始草稿文本
        revision_guide: Review Agent 给出的全局修改计划
        issue_descriptions: 针对该 beat 的具体问题描述列表
        chapter: 章节实体
        book: 书籍实体
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        previous_tail: 前一 Beat 的尾巴文本，用于保持语气衔接

    Returns:
        str: 精修后的正文
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"

    # 构建问题描述列表
    issues_text = ""
    if issue_descriptions:
        issues_list = "\n".join(f"- {desc}" for desc in issue_descriptions if desc)
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

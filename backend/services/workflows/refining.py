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
    )
    
    return clean_llm_output(refined_text)

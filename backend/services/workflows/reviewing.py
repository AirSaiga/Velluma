from typing import Any, Tuple

from backend.services.prompts import build_review_agent_prompt, parse_review_result
from backend.services.llm_client import call_llm
from backend.models import Chapter, Book, Character, CharacterRelationship


async def review_draft(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    chapter_outline: str,
    draft_text: str,
    api_key: str,
    base_url: str,
    model: str,
) -> Tuple[dict, bool]:
    """审阅章节初稿，检查 OOC、剧情合规性和逻辑完整性。

    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        chapter_outline: 章节大纲
        draft_text: 待审阅的草稿文本
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name

    Returns:
        Tuple[dict, bool]: (review_result_dict, passed_bool)
        - review_result_dict: 审阅结果字典，包含 pass、issues、revision_plan 等字段
        - passed_bool: 审阅是否通过
    """
    system_prompt, user_prompt = build_review_agent_prompt(
        chapter, book, entities, relationships, chapter_outline or "", draft_text
    )
    
    review_result_json = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    
    review_result, _ = parse_review_result(review_result_json)
    
    return review_result, review_result.get("pass", False)

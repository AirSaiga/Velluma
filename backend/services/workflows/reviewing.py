from backend.services.prompts import build_review_agent_prompt, parse_review_result
from backend.services.llm_client import call_llm


async def review_draft(chapter, book, entities, relationships, chapter_outline, draft_text, api_key, base_url, model):
    """
    审阅章节初稿，检查OOC、剧情合规性和逻辑完整性。
    
    返回:
        tuple: (review_result_dict, passed_bool)
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

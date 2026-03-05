from backend.services.prompts import build_refine_agent_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output


async def refine_draft(chapter, book, entities, relationships, current_draft, revision_plan, word_count, api_key, base_url, model):
    """
    根据审阅意见精修章节初稿。
    
    返回:
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

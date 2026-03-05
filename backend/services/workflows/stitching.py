from backend.services.prompts import build_stitch_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output


async def stitch_chunks(chapter, beats, chunks, word_count, api_key, base_url, model):
    """
    将多个并行生成的chunks统稿成连贯的章节正文。
    
    返回:
        str: 统稿后的正文
    """
    stitch_system_prompt, stitch_user_prompt = build_stitch_prompt(
        chapter=chapter,
        beats=beats,
        chunks=chunks,
        word_count=word_count,
    )
    
    stitched_text = await call_llm(
        system_prompt=stitch_system_prompt,
        user_prompt=stitch_user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.4,
    )
    
    stitched_text = clean_llm_output(stitched_text)
    
    if not stitched_text.strip():
        stitched_text = "\n\n".join(chunks).strip()
    
    return stitched_text

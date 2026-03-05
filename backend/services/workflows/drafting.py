import asyncio

from backend.services.prompts import build_scene_intent_prompt, parse_scene_intent_result, build_chunk_draft_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output


async def generate_chunks_parallel(chapter, book, entities, relationships, beats, story_beats, open_hooks, previous_summary, relevant_memories, api_key, base_url, model, word_count):
    """
    并行生成多个故事节拍的正文片段。
    
    返回:
        list: 生成的chunks列表
    """
    async def process_beat(beat_index, beat, story_beat):
        try:
            beat_hook_ids = set(beat.get("hook_ids", []))
            beat_open_hooks = []
            if beat_hook_ids:
                beat_open_hooks = [
                    item
                    for item in open_hooks
                    if item["hook_id"] in beat_hook_ids or item["ledger_key"] in beat_hook_ids
                ]
            if not beat_open_hooks and beat_index == 1:
                beat_open_hooks = open_hooks[:2]

            scene_system_prompt, scene_user_prompt = build_scene_intent_prompt(
                chapter=chapter,
                beat=beat,
                open_hooks=beat_open_hooks,
            )
            scene_intent_raw = await call_llm(
                system_prompt=scene_system_prompt,
                user_prompt=scene_user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            scene_intent_data = parse_scene_intent_result(scene_intent_raw, beat.get("summary", ""))
            
            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))

            context_summaries = {}
            if beat_index > 1:
                context_summaries['prev'] = beats[beat_index - 2].get('summary', '')
            if beat_index < len(beats):
                context_summaries['next'] = beats[beat_index].get('summary', '')

            chunk_system_prompt, chunk_user_prompt = build_chunk_draft_prompt(
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                beat=beat,
                scene_intent=scene_intent_data,
                target_words=target_words,
                previous_chunks=[],
                previous_summary=previous_summary,
                relevant_memories=relevant_memories,
                hook_contexts=beat_open_hooks,
                context_beat_summaries=context_summaries,
            )
            
            chunk_text = await call_llm(
                system_prompt=chunk_system_prompt,
                user_prompt=chunk_user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.7,
            )
            return beat_index - 1, clean_llm_output(chunk_text)
        except Exception as e:
            print(f"[Beat Error] Beat {beat_index} failed: {e}")
            return beat_index - 1, ""

    sem = asyncio.Semaphore(5)
    async def sem_task(task):
        async with sem:
            return await task

    tasks = [
        sem_task(process_beat(i, b, sb)) 
        for i, b, sb in zip(range(1, len(beats)+1), beats, story_beats)
    ]
    
    results = await asyncio.gather(*tasks)
    
    generated_chunks = [""] * len(beats)
    for idx, text in results:
        generated_chunks[idx] = text
    
    return generated_chunks

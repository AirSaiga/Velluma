from backend.services.prompts import build_planner_agent_prompt, parse_planner_result
from backend.services.llm_client import call_llm
from backend.models import StoryBeat


async def generate_beats(chapter, book, entities, relationships, word_count, open_hooks, api_key, base_url, model, previous_chapter_summary=None):
    """
    生成章节故事节拍 (Story Beats)。
    
    返回:
        list: beats列表
    """
    planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=word_count,
        open_hooks=open_hooks,
        previous_chapter_summary=previous_chapter_summary,
    )
    
    planner_result_raw = await call_llm(
        system_prompt=planner_system_prompt,
        user_prompt=planner_user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    
    beats = parse_planner_result(planner_result_raw, chapter.outline_text or "", word_count)
    
    story_beats = []
    for beat_index, beat in enumerate(beats, start=1):
        story_beat = StoryBeat(
            book_id=chapter.book_id,
            chapter_id=chapter.id,
            beat_id=beat.get("beat_id"),
            beat_type="progression",
            position=beat.get("position", beat_index),
            location=beat.get("location"),
            pov_character=beat.get("pov_character"),
            action_summary=beat.get("action_summary"),
            worldbuilding_instruction=beat.get("worldbuilding_instruction"),
            word_count_target=beat.get("word_count_target", beat.get("target_words", 0)),
            summary=beat.get("summary", ""),
            meta={"target_words": beat.get("target_words", 0)},
            status="planned",
        )
        story_beats.append(story_beat)
    
    return beats, story_beats

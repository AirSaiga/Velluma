from backend.services.prompts import (
    build_planner_agent_prompt,
    parse_planner_result,
    build_pov_assignment_prompt,
    parse_pov_assignment_result,
)
import json
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
            entry_state=beat.get("entry_state"),
            exit_state=beat.get("exit_state"),
            red_lines=beat.get("red_lines", []),
            word_count_target=beat.get("word_count_target", beat.get("target_words", 0)),
            summary=beat.get("summary", ""),
            meta={"target_words": beat.get("target_words", 0)},
            status="planned",
        )
        story_beats.append(story_beat)
    
    return beats, story_beats


async def assign_pov_to_beats(
    beats,
    characters,
    story_premise,
    api_key,
    base_url,
    model,
):
    """
    为节拍分配 POV 角色。
    
    Args:
        beats: 节拍列表 (可以是 list[dict] 或 list[StoryBeat])
        characters: 角色列表 (list[dict], 每个包含 name, role, description)
        story_premise: 故事概要
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        
    Returns:
        tuple: (更新后的节拍列表, prompt_debug_info)
    """
    # 转换 beats 为 dict 列表供 prompt 使用
    beats_for_prompt = []
    for beat in beats:
        if isinstance(beat, dict):
            beats_for_prompt.append(beat)
        elif hasattr(beat, "beat_id") and hasattr(beat, "summary"): # StoryBeat object
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None) or getattr(beat, "id", None),
                "position": getattr(beat, "position", None),
                "summary": getattr(beat, "summary", ""),
            }
            beats_for_prompt.append(beat_dict)
        else:
             # Fallback
            beat_dict = {
                "beat_id": getattr(beat, "beat_id", None),
                "position": getattr(beat, "position", None),
                "summary": getattr(beat, "summary", ""),
            }
            beats_for_prompt.append(beat_dict)
            
    system_prompt, user_prompt = build_pov_assignment_prompt(
        story_premise=story_premise,
        characters=characters,
        beats=beats_for_prompt,
    )
    
    llm_result_raw = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        response_format={"type": "json_object"},
    )
    
    try:
        llm_result = json.loads(llm_result_raw)
        assignments = parse_pov_assignment_result(llm_result)
        
        # 应用结果到原始 beats 对象
        for beat in beats:
            # 确定 beat 的标识符
            beat_id = None
            if isinstance(beat, dict):
                beat_id = str(beat.get("beat_id", beat.get("position")))
            else:
                beat_id = str(getattr(beat, "beat_id", getattr(beat, "position", None)))
                
            if beat_id and beat_id in assignments:
                pov_char = assignments[beat_id]
                if isinstance(beat, dict):
                    beat["pov_character"] = pov_char
                else:
                    setattr(beat, "pov_character", pov_char)
                    
    except json.JSONDecodeError:
        pass
        
    return beats, {"system_prompt": system_prompt, "user_prompt": user_prompt}

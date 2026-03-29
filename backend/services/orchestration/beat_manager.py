from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sa_delete

from backend.models import Chapter, StoryBeat


async def save_story_beats(
    db: AsyncSession,
    chapter: Chapter,
    beats: List[dict]
) -> List[StoryBeat]:
    await db.execute(sa_delete(StoryBeat).where(StoryBeat.chapter_id == chapter.id))
    await db.flush()

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
            pov_perception_state=beat.get("pov_perception_state", "正常"),
            anchor_pov=beat.get("anchor_pov"),
            original_actor=beat.get("original_actor"),
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
        db.add(story_beat)
        story_beats.append(story_beat)

    await db.flush()
    return story_beats


def build_physical_state_lock(beats: List[dict]) -> Optional[str]:
    if beats and beats[0].get("entry_state"):
        return beats[0].get("entry_state")
    return None

"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
节拍管理器 - StoryBeat 实体持久化和状态管理。

职责：
- 管理 StoryBeat 的创建、更新、删除操作
- 提供节拍数据的序列化和反序列化
- 封装节拍与章节的关联逻辑

业务场景：
- 章节生成时保存 Planner 输出的节拍计划
- 章节详情页加载节拍列表
- 物理状态锁的构建和验证

主要功能：
- 节拍批量保存（先删后插保证幂等性）
- 节拍到物理状态锁的转换
- 节拍数据验证

依赖项：
- backend.models: StoryBeat ORM 模型
- SQLAlchemy: 数据库会话管理

使用方式：
    beats = await save_story_beats(db, chapter, beat_list)
"""

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
            # CP2.3d 补齐字段（与 planning.generate_beats 输出对齐，confirm 端点复用）
            pov_aperture=beat.get("pov_aperture", "subjective_observation"),
            persistent_state_anchors=beat.get("persistent_state_anchors", []),
            pacing_type=beat.get("pacing_type"),
            weight=beat.get("weight", 1),
            participants=beat.get("participants", []),
        )
        db.add(story_beat)
        story_beats.append(story_beat)

    await db.flush()
    return story_beats


def build_physical_state_lock(beats: List[dict]) -> Optional[str]:
    if beats and beats[0].get("entry_state"):
        return beats[0].get("entry_state")
    return None

import json

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, ChapterMapLocation


async def build_chapter_prompt(chapter_id, db: AsyncSession, word_count: int = 2000) -> dict:
    """
    构建简单章节生成的提示词 (单轮 LLM 调用)。

    提示词结构设计 (按优先级排列)：
    1. 全局角色定义 (global_sys_prompt) - LLM 行为基线
    2. 世界观设定 - 场景上下文
    3. 角色静态设定 - 不变的人设
    4. 角色动态状态 - 当前心理/情感 (随章节变化)
    5. 角色互动约束 - 关系规则
    6. 字数要求 - 最高优先级约束 (LLM 容易忽略，需强调)

    数据流：
    - chapter_id → 查询 Chapter → 获取章节大纲
    - chapter_id → 查询 ChapterEntity → 获取涉及的角色
    - 角色ID集合 → 查询 CharacterRelationship → 获取角色关系

    权衡：使用 selectinload 避免 N+1 查询，但一次性加载所有关系可能影响大规模章节性能。
    """
    chapter_result = await db.execute(select(Chapter).options(selectinload(Chapter.book)).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    book = chapter.book
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings
    worldview_prompt = f"【世界观设定】\n{worldview_settings}" if worldview_settings else None

    map_activity_range = getattr(chapter, "map_activity_range", None)
    map_prompt = f"【地图活动范围】\n{map_activity_range}" if map_activity_range else None

    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()

    locations_result = await db.execute(
        select(ChapterMapLocation).options(selectinload(ChapterMapLocation.location)).where(ChapterMapLocation.chapter_id == chapter_id)
    )
    locations = locations_result.scalars().all()
    location_prompts = []
    for loc_rel in locations:
        if loc_rel.location:
            desc = f"【{loc_rel.location.name}】{loc_rel.location.description or ''}"
            location_prompts.append(desc)
    
    if map_prompt:
        location_prompts.append(map_prompt)
    
    final_map_prompt = "\n".join(location_prompts) if location_prompts else None

    static_states = []
    dynamic_states = []
    character_ids = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            character_ids.append(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")

    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    relationships = relationships_result.scalars().all()

    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")

    system_prompt_parts = [
        global_sys_prompt,
        worldview_prompt if worldview_prompt else "",
        f"【场景与地图】\n{final_map_prompt}" if final_map_prompt else "",
        "\n\n## 角色静态设定",
        "\n".join(static_states) if static_states else "暂无角色设定",
        "\n\n## 角色动态状态",
        "\n".join(dynamic_states) if dynamic_states else "暂无动态状态",
        "\n\n## 角色互动约束",
        "\n".join(relationship_prompts) if relationship_prompts else "暂无互动约束",
        "\n\n## 【强制字数要求 - 最高优先级】",
        f"★ 生成内容必须精确控制在 {word_count} 字 (±100字误差可接受)",
        "★ 这是最强约束，必须严格遵守，不得少于或超过此字数限制",
        "★ 规划好内容结构，确保最终字数符合要求",
        "\n\n## 核心规则",
        "1. 严格遵循章节大纲进行创作",
        "2. 保持角色性格和互动方式的连贯性",
        "3. 根据角色关系约束调整互动氛围",
        "4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等",
        "5. 生成内容必须满足上述字数要求",
        "6. 段落之间请使用双换行符（\\n\\n）分隔，以确保排版清晰。",
        "7. 严禁使用 Markdown 格式（如加粗、斜体、列表等），仅输出纯文本。",
    ]
    system_prompt = "\n".join(system_prompt_parts)

    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

请直接输出小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""
    return {"system_prompt": system_prompt, "user_prompt": user_prompt, "chapter": chapter}

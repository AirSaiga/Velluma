import json

from backend.models import Chapter, Book


def build_draft_agent_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    word_count: int,
    previous_summary: str = None,
    relevant_memories: list = None,
    beat: dict = None,
    scene_intent: dict = None,
    hook_contexts: list = None,
    locations: list = None,
):
    """
    构建主笔 Agent (Draft Agent) 的提示词，负责初稿创作。

    与 build_chapter_prompt 的区别：
    - 该函数用于单轮生成，该函数用于代理工作流 (多轮迭代)
    - 输入是已加载的 ORM 对象，而非从 DB 查询
    - 新增 context 注入：previous_summary (前情提要) 和 relevant_memories (RAG 检索)

    核心任务：根据章节大纲生成符合角色设定和关系约束的初稿。
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    
    map_activity_range = getattr(chapter, "map_activity_range", None)
    map_prompt = f"【地图活动范围】\n{map_activity_range}" if map_activity_range else None
    
    location_prompts = []
    if locations:
        for loc_rel in locations:
            location = getattr(loc_rel, "location", None)
            if location:
                desc = f"【{location.name}】{location.description or ''}"
                location_prompts.append(desc)
    
    if map_prompt:
        location_prompts.append(map_prompt)
    
    final_map_prompt = "\n".join(location_prompts) if location_prompts else None

    tone_instruction = (
        getattr(chapter, "tone", None)
        or getattr(book, "tone", None)
        or "整体基调保持与章节冲突和人物状态一致。"
    )
    beat_data = beat if isinstance(beat, dict) else {}
    worldbuilding_instruction = (
        beat_data.get("worldbuilding_instruction")
        or getattr(chapter, "worldbuilding_instruction", None)
        or getattr(book, "worldbuilding_instruction", None)
    )
    worldbuilding_prompt = f"## 世界构建指令\n{worldbuilding_instruction}" if worldbuilding_instruction else None

    prev_summary_prompt = f"## 前情提要\n{previous_summary}" if previous_summary else None

    memories_prompt = None
    if relevant_memories:
        memories_text = "\n".join([f"- {m.chunk_text}" for m in relevant_memories])
        memories_prompt = f"## 相关记忆/伏笔（RAG）\n{memories_text}"

    scene_intent_data = scene_intent if isinstance(scene_intent, dict) else (
        getattr(chapter, "scene_intent", None)
        or getattr(chapter, "scene_intent_data", None)
        or getattr(chapter, "scene_intents", None)
    )
    scene_intent_prompt = None
    if isinstance(scene_intent_data, dict):
        scene_intent_prompt = (
            "## SceneIntent\n"
            f"标签：{scene_intent_data.get('intent_label', '推进剧情')}\n"
            f"目标：{scene_intent_data.get('goal', '推进剧情')}\n"
            f"风险：{scene_intent_data.get('stakes') or '无'}\n"
            f"约束：{', '.join(scene_intent_data.get('constraints', [])) if scene_intent_data.get('constraints') else '无'}"
        )
    elif isinstance(scene_intent_data, list) and scene_intent_data:
        latest_intent = scene_intent_data[-1]
        if isinstance(latest_intent, dict):
            scene_intent_prompt = (
                "## SceneIntent\n"
                f"标签：{latest_intent.get('intent_label', '推进剧情')}\n"
                f"目标：{latest_intent.get('goal', '推进剧情')}\n"
                f"风险：{latest_intent.get('stakes') or '无'}\n"
                f"约束：{', '.join(latest_intent.get('constraints', [])) if latest_intent.get('constraints') else '无'}"
            )
        else:
            scene_intent_prompt = f"## SceneIntent\n{latest_intent}"
    elif scene_intent_data:
        scene_intent_prompt = f"## SceneIntent\n{scene_intent_data}"

    static_states = []
    dynamic_states = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")

    system_prompt = f"""{global_sys_prompt}

{worldview_prompt if worldview_prompt else ''}

{final_map_prompt if final_map_prompt else ''}

{prev_summary_prompt if prev_summary_prompt else ''}

{memories_prompt if memories_prompt else ''}

## 基调
{tone_instruction}

{worldbuilding_prompt if worldbuilding_prompt else ''}

{scene_intent_prompt if scene_intent_prompt else ''}

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## 【强制字数要求 - 最高优先级】
★ 生成内容必须精确控制在 {word_count} 字 (±100字误差可接受)
★ 这是最强约束，必须严格遵守，不得少于或超过此字数限制

## 核心规则
1. 严格遵循章节大纲进行创作
2. 保持角色性格和互动方式的连贯性
3. 根据角色关系约束调整互动氛围
4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等
5. 生成内容必须满足上述字数要求
6. 段落之间请使用双换行符（\\n\\n）分隔，以确保排版清晰。
7. 严禁使用 Markdown 格式（如加粗、斜体、列表等），仅输出纯文本。"""
    action_summary = (
        beat_data.get("action_summary")
        or getattr(chapter, "action_summary", None)
        or beat_data.get("summary")
        or chapter.outline_text
        or "围绕本段冲突推进关键动作。"
    )
    hook_text = beat_data.get("hook") or getattr(chapter, "hook", None) or getattr(chapter, "opening_hook", None)
    normalized_hooks = []
    if isinstance(hook_contexts, list):
        for item in hook_contexts:
            if isinstance(item, dict):
                hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
                content = str(item.get("content") or "").strip()
                if content:
                    normalized_hooks.append({"hook_id": hook_id, "content": content})
            elif item:
                normalized_hooks.append({"hook_id": "", "content": str(item).strip()})
    action_summary_prompt = f"【动作摘要】\n{action_summary}"
    hook_prompt = f"【开篇钩子】\n{hook_text}" if hook_text else None
    ledger_hooks_prompt = None
    if normalized_hooks:
        hook_lines = []
        for hook in normalized_hooks[:3]:
            if hook["hook_id"]:
                hook_lines.append(f"- {hook['hook_id']}: {hook['content']}")
            else:
                hook_lines.append(f"- {hook['content']}")
        ledger_hooks_prompt = f"【开放伏笔】\n{chr(10).join(hook_lines)}"
    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
{action_summary_prompt}
{hook_prompt if hook_prompt else ''}
{ledger_hooks_prompt if ledger_hooks_prompt else ''}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

写作方法：
- Show, don't tell：优先通过动作、感官、对话与细节呈现情绪和信息，避免直接讲解。
- hook 自然注入：将钩子信息融入情境、冲突或悬念，不要生硬贴标签。
- 若存在开放伏笔，必须通过环境细节或角色动作自然植入，不要显式解释"这是伏笔"。

请直接输出小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""
    return system_prompt, user_prompt


def build_chunk_draft_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    beat: dict,
    scene_intent: dict,
    target_words: int,
    previous_chunks: list[str],
    previous_summary: str = None,
    relevant_memories: list = None,
    hook_contexts: list = None,
    context_beat_summaries: dict = None,
    locations: list = None,
):
    system_prompt, user_prompt = build_draft_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=target_words,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        beat=beat,
        scene_intent=scene_intent,
        hook_contexts=hook_contexts,
        locations=locations,
    )
    
    continuity_section = ""
    if previous_chunks:
        continuity_text = "\n\n".join(previous_chunks[-2:])
        continuity_section = f"【连贯性参考（最近已生成内容）】\n{continuity_text}"
    else:
        context_parts = []
        if context_beat_summaries:
            if context_beat_summaries.get('prev'):
                context_parts.append(f"前一节拍梗概：{context_beat_summaries['prev']}")
            if context_beat_summaries.get('next'):
                context_parts.append(f"后一节拍梗概：{context_beat_summaries['next']}")
        
        if context_parts:
            continuity_section = "【上下文情节参考】\n" + "\n".join(context_parts) + "\n请根据上下文梗概，确保本段落的开头和结尾能与前后情节自然衔接。"
        else:
            continuity_section = "【连贯性参考】\n暂无已生成内容"

    chunk_user_prompt = f"""{user_prompt}

【当前 Story Beat】
位置：{beat.get("position", 1)}
BeatID：{beat.get("beat_id", "")}
摘要：{beat.get("summary", "")}
动作摘要：{beat.get("action_summary", beat.get("summary", ""))}
场景：{beat.get("location") or "未指定"}
视角角色：{beat.get("pov_character") or "未指定"}
建议字数：{target_words}

【Scene Intent】
标签：{scene_intent.get("intent_label", "推进剧情")}
目标：{scene_intent.get("goal", "推进剧情")}
风险：{scene_intent.get("stakes") or "无"}
约束：{", ".join(scene_intent.get("constraints", [])) if scene_intent.get("constraints") else "无"}

{continuity_section}

请只输出当前 beat 对应的正文 chunk，不要重复前文，不要输出解释。"""
    return system_prompt, chunk_user_prompt

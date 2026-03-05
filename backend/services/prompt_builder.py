import json
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity


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
    # 步骤1：加载章节基础信息 (含关联的 Book)
    chapter_result = await db.execute(select(Chapter).options(selectinload(Chapter.book)).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    book = chapter.book
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings
    worldview_prompt = f"【世界观设定】\n{worldview_settings}" if worldview_settings else None

    # 步骤2：加载本章涉及的角色及其动态状态
    # 关键：去重逻辑防止同一角色出现多次 (一个角色可能多处出场)
    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()

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

    # 步骤3：加载角色间关系约束
    # 关键：只查询本章出场的角色间关系，避免无关关系干扰
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

    # 步骤4：组装 system prompt (分层级结构确保 LLM 理解优先级)
    system_prompt_parts = [
        global_sys_prompt,
        worldview_prompt if worldview_prompt else "",
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

    # 步骤5：构建 user prompt (包含章节创作任务)
    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

请直接输出小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""
    return {"system_prompt": system_prompt, "user_prompt": user_prompt, "chapter": chapter}


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
- 若存在开放伏笔，必须通过环境细节或角色动作自然植入，不要显式解释“这是伏笔”。

请直接输出小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""
    return system_prompt, user_prompt


def build_planner_agent_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    word_count: int,
    open_hooks: list = None,
):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    character_names = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            character_names.append(character.name)
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"{source_name}↔{target_name}: {rel.interaction_prompt}")
    normalized_hooks = []
    if isinstance(open_hooks, list):
        for item in open_hooks:
            if not isinstance(item, dict):
                continue
            hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
            content = str(item.get("content") or "").strip()
            if content:
                normalized_hooks.append({"hook_id": hook_id, "content": content})
    open_hooks_text = (
        chr(10).join(
            [
                f"- {hook['hook_id']}: {hook['content']}" if hook["hook_id"] else f"- {hook['content']}"
                for hook in normalized_hooks[:6]
            ]
        )
        if normalized_hooks
        else "暂无开放伏笔"
    )
    system_prompt = f"""{global_sys_prompt}

你是章节规划师。请把章节拆分成可执行的 story beats，并仅输出 JSON。

{worldview_prompt if worldview_prompt else ''}

## 输出 JSON 结构
{{
  "beats": [
    {{
      "position": 1,
      "beat_id": "beat-1",
      "summary": "本段剧情概述",
      "location": "场景地点",
      "pov_character": "视角角色",
      "action_summary": "动作化执行摘要",
      "worldbuilding_instruction": "本段生效的世界构建约束",
      "word_count_target": 600,
      "hook_ids": ["hk-1"]
    }}
  ]
}}

约束：
1. beats 至少 1 个，最多 6 个
2. position 从 1 开始递增
3. summary 具体、可执行，不要空泛
4. action_summary 必须可执行、动作化
5. word_count_target 为正整数，总和接近章节目标字数
6. 若存在开放伏笔，至少在一个 beat 的 hook_ids 中绑定
7. 只输出 JSON，不要额外解释"""
    user_prompt = f"""请规划以下章节：

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【目标字数】{word_count}
【角色】{", ".join(character_names) if character_names else "暂无"}
【关系约束】
{chr(10).join(relationship_prompts) if relationship_prompts else "暂无互动约束"}
【开放伏笔】
{open_hooks_text}"""
    return system_prompt, user_prompt


def parse_planner_result(planner_result_raw: str, chapter_outline: str, word_count: int):
    text = (planner_result_raw or "").strip()
    candidates = [text] if text else []
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    beats = []
    if isinstance(parsed_obj, dict) and isinstance(parsed_obj.get("beats"), list):
        for idx, beat in enumerate(parsed_obj["beats"], start=1):
            if not isinstance(beat, dict):
                continue
            summary = str(beat.get("summary") or "").strip()
            if not summary:
                continue
            position = beat.get("position")
            if not isinstance(position, int) or position <= 0:
                position = idx
            target_words = beat.get("target_words")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = max(200, word_count // max(1, len(parsed_obj["beats"])))
            word_count_target = beat.get("word_count_target")
            if not isinstance(word_count_target, int) or word_count_target <= 0:
                word_count_target = target_words
            beat_id = str(beat.get("beat_id") or f"beat-{position}").strip() or f"beat-{position}"
            location = str(beat.get("location") or "").strip() or None
            pov_character = str(beat.get("pov_character") or "").strip() or None
            action_summary = str(beat.get("action_summary") or "").strip() or summary
            worldbuilding_instruction = str(beat.get("worldbuilding_instruction") or "").strip() or None
            raw_hook_ids = beat.get("hook_ids")
            hook_ids = [str(item).strip() for item in raw_hook_ids if str(item).strip()] if isinstance(raw_hook_ids, list) else []
            beats.append(
                {
                    "position": position,
                    "beat_id": beat_id,
                    "summary": summary,
                    "location": location,
                    "pov_character": pov_character,
                    "action_summary": action_summary,
                    "worldbuilding_instruction": worldbuilding_instruction,
                    "word_count_target": word_count_target,
                    "target_words": word_count_target,
                    "hook_ids": hook_ids,
                }
            )
    if not beats:
        fallback_summary = (chapter_outline or "").strip() or "按章节大纲推进剧情并完成关键冲突。"
        beats = [
            {
                "position": 1,
                "beat_id": "beat-1",
                "summary": fallback_summary,
                "location": None,
                "pov_character": None,
                "action_summary": fallback_summary,
                "worldbuilding_instruction": None,
                "word_count_target": word_count,
                "target_words": word_count,
                "hook_ids": [],
            }
        ]
    beats.sort(key=lambda item: item["position"])
    return beats


def build_scene_intent_prompt(chapter: Chapter, beat: dict, open_hooks: list = None):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_summary = beat.get("summary", "")
    system_prompt = """你是场景意图分析师。请根据输入剧情节拍输出 JSON。

输出结构：
{
  "intent_label": "场景标签",
  "goal": "本场景目标",
  "stakes": "失败代价或风险",
  "constraints": ["约束1", "约束2"]
}

要求：
1. goal 必须具体
2. constraints 必须是字符串数组
3. 只输出 JSON"""
    open_hooks_text = "暂无开放伏笔"
    if isinstance(open_hooks, list) and open_hooks:
        hook_lines = []
        for item in open_hooks[:6]:
            if not isinstance(item, dict):
                continue
            hook_id = str(item.get("hook_id") or item.get("ledger_key") or "").strip()
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            hook_lines.append(f"- {hook_id}: {content}" if hook_id else f"- {content}")
        if hook_lines:
            open_hooks_text = chr(10).join(hook_lines)
    user_prompt = f"""请为以下章节节拍生成 SceneIntent：

【章节名】{chapter_name}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【节拍位置】{beat.get("position", 1)}
【节拍内容】
{beat_summary}
【开放伏笔】
{open_hooks_text}"""
    return system_prompt, user_prompt


def parse_scene_intent_result(scene_intent_raw: str, beat_summary: str):
    text = (scene_intent_raw or "").strip()
    candidates = [text] if text else []
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    parsed_obj = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    if isinstance(parsed_obj, dict):
        intent_label = str(parsed_obj.get("intent_label") or "").strip() or "推进剧情"
        goal = str(parsed_obj.get("goal") or "").strip() or beat_summary or "推进剧情"
        stakes_raw = parsed_obj.get("stakes")
        stakes = str(stakes_raw).strip() if stakes_raw is not None else ""
        constraints_raw = parsed_obj.get("constraints")
        constraints = [str(item).strip() for item in constraints_raw if str(item).strip()] if isinstance(constraints_raw, list) else []
        return {
            "intent_label": intent_label,
            "goal": goal,
            "stakes": stakes or None,
            "constraints": constraints,
        }
    return {
        "intent_label": "推进剧情",
        "goal": beat_summary or "推进剧情",
        "stakes": None,
        "constraints": [],
    }


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
    )
    continuity_text = "\n\n".join(previous_chunks[-2:]) if previous_chunks else "暂无已生成内容"
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

【连贯性参考（最近已生成内容）】
{continuity_text}

请只输出当前 beat 对应的正文 chunk，不要重复前文，不要输出解释。"""
    return system_prompt, chunk_user_prompt


def build_stitch_prompt(chapter: Chapter, beats: list[dict], chunks: list[str], word_count: int):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_lines = [f"{idx + 1}. {beat.get('summary', '')}" for idx, beat in enumerate(beats)]
    chunk_lines = [f"### Chunk {idx + 1}\n{chunk}" for idx, chunk in enumerate(chunks)]
    system_prompt = f"""你是小说统稿编辑。请将多个 chunk 融合成连贯的章节正文，并保持约 {word_count} 字（±100）。

要求：
1. 保持剧情顺序与逻辑连贯
2. 消除重复信息与风格断裂
3. 统一人称、时态与语气
4. 输出纯文本，不要标题或解释"""
    user_prompt = f"""请统稿以下内容：

【章节名】{chapter_name}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【Story Beats】
{chr(10).join(beat_lines) if beat_lines else "暂无"}

【Chunks】
{chr(10).join(chunk_lines) if chunk_lines else "暂无"}
"""
    return system_prompt, user_prompt


def build_review_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, chapter_outline: str, draft_text: str):
    """
    构建审阅 Agent (Review Agent) 的提示词，负责质量检查。

    核心任务：
    1. OOC 检测 (Out Of Character) - 角色行为是否符合性格设定
    2. 剧情合规性 - 是否遵循章节大纲
    3. 逻辑完整性 - 是否有情节漏洞

    特殊设计：
    - 只传入静态设定，不传动态状态 (避免审阅时受到当前状态的过度影响)
    - 强制 JSON 输出格式 (便于程序化解析)
    - temperature=0.1 (低温度保证判断一致性)

    数据流：draft_text (待审内容) → LLM 审查 → JSON 格式审查结果
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    static_states = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")
    system_prompt = f"""{global_sys_prompt}

你是一个严格的小说质量审查员。你不负责写小说，只负责检查初稿是否符合要求。

{worldview_prompt if worldview_prompt else ''}

## 角色设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## 你的任务
1. 检查初稿是否遵循了章节大纲要求
2. 检查角色是否出现 OOC (Out Of Character，人设崩塌)
3. 检查是否有逻辑硬伤或情节漏洞
4. 检查是否遗漏了应该有的剧情点

## 输出格式要求
你必须以 JSON 格式输出，结构如下：
{{
    "pass": true/false,
    "issues": [
        {{
            "type": "OOC/剧情遗漏/逻辑硬伤",
            "severity": "high/medium/low",
            "description": "详细描述问题"
        }}
    ],
    "revision_plan": "给出具体的重写建议"
}}

- pass: true 表示所有检查通过，可以直接输出
- pass: false 表示存在问题，需要重写
- issues: 列出发现的问题
- revision_plan: 给出具体的重写指导

注意：你必须输出合法的 JSON 格式，不要输出任何其他内容！"""
    user_prompt = f"""请审查以下初稿:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter_outline}

【初稿内容】
{draft_text}

请输出 JSON 格式的审查结果。"""
    return system_prompt, user_prompt


def build_refine_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, draft_text: str, revision_plan: str, word_count: int):
    """
    构建精修 Agent (Refine Agent) 的提示词，根据审查意见重写初稿。

    核心任务：
    - 基于 revision_plan 针对性修改
    - 保持原有优秀部分不被破坏
    - 确保修改后仍符合字数要求

    数据流：
    - revision_plan (来自 Review Agent) + draft_text → LLM 重写 → 修改后的正文

    关键设计：将审查意见作为显式约束注入 prompt，而非让 LLM 自行理解上下文。
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
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

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## 【强制字数要求 - 最高优先级】
★ 生成内容必须精确控制在 {word_count} 字 (±100字误差可接受)
★ 这是最强约束，必须严格遵守，不得少于或超过此字数限制

## 你的任务
你是一个精修编辑，需要根据审查意见对初稿进行针对性重写。
请仔细阅读以下审查意见和初稿，然后生成修改后的版本。

## 核心规则
1. 严格遵循审查意见进行修改
2. 保持原有优秀的部分
3. 修正被指出的问题
4. 确保修改后的内容符合章节大纲
5. 保持角色性格一致性
6. 生成内容必须满足上述字数要求"""
    user_prompt = f"""请根据以下审查意见重写初稿:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

【审查意见】
{revision_plan}

【当前初稿】
{draft_text}

请直接输出修改后的完整小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""
    return system_prompt, user_prompt


def parse_review_result(review_result_raw: str):
    """
    解析审阅 Agent 返回的 JSON 结果。

    容错设计：LLM 可能输出各种格式的"伪 JSON" (如带 markdown 包裹、前后有文本等)，
    因此需要多策略尝试解析：
    1. 原始文本
    2. markdown 代码块中的 JSON
    3. 首尾大括号包围的内容

    副作用：正则匹配可能误捕获嵌套代码块，但嵌套情况罕见可忽略。

    错误处理：
    - 空响应 → 返回默认失败结果 (pass=false)
    - JSON 解析失败 → 返回默认失败结果 + 解析错误信息
    - 字段缺失 → 使用默认值填充 (如 issues=[])
    """
    text = (review_result_raw or "").strip()
    if not text:
        return {
            "pass": False,
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回为空，无法完成质检。"}],
            "revision_plan": "请基于章节大纲重新审查，并仅输出合法 JSON。",
        }, "Empty response from Review Agent"
    candidates = [text]
    # 策略1：提取 markdown 代码块中的 JSON
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    # 策略2：提取首尾大括号包围的内容
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    # 尝试多策略解析，直到成功
    parsed_obj = None
    parse_error = None
    for candidate in candidates:
        try:
            parsed_obj = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            parse_error = str(e)
    if not isinstance(parsed_obj, dict):
        return {
            "pass": False,
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回内容无法解析为合法 JSON。"}],
            "revision_plan": "请严格按约定 JSON 结构输出审查结论，不要附加解释文本。",
        }, parse_error or "Review JSON parse failed"
    # 字段提取，缺失时使用默认值
    issues = parsed_obj.get("issues")
    if not isinstance(issues, list):
        issues = []
    revision_plan = parsed_obj.get("revision_plan")
    if not isinstance(revision_plan, str) or not revision_plan.strip():
        revision_plan = "请按章节大纲与角色设定修复逻辑问题，并返回完整正文。"
    result = {"pass": bool(parsed_obj.get("pass", False)), "issues": issues, "revision_plan": revision_plan}
    return result, None

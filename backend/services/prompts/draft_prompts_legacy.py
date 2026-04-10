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
遗留起草提示词模块 - 早期版本的起草提示。

职责：
- 提供早期版本的起草提示构建
- 保持向后兼容性
- 支持遗留系统

业务场景：
- 遗留起草流程
- 向后兼容

主要功能：
- 遗留版本起草提示构建

依赖项：
- backend.models: 数据模型
"""

import json

from backend.models import Chapter, Book
from backend.services.prompts.draft_prompts_utils import (
    _normalize_text,
    _normalize_text_list,
    _render_boundary_constraints,
    _render_scene_intent_prompt,
    _render_style_control_prompt,
)


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
    anchor_pov: str = None,
):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None

    style_control_prompt = _render_style_control_prompt(book)

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
    beat_summary = _normalize_text(beat_data.get("summary"))
    beat_action_summary = _normalize_text(beat_data.get("action_summary"), beat_summary)
    entry_state = _normalize_text(beat_data.get("entry_state"), f"承接上文并切入：{beat_summary[:40]}" if beat_summary else "承接上文并切入当前节拍。")
    exit_state = _normalize_text(beat_data.get("exit_state"), f"停在本节拍收束点：{beat_action_summary[:40]}" if beat_action_summary else "停在当前节拍收束状态，不越界推进。")
    red_lines = _normalize_text_list(beat_data.get("red_lines"))
    if not red_lines:
        red_lines = ["不得越过本节拍 exit_state 指向的剧情停点"]
    boundary_constraints_prompt = _render_boundary_constraints(entry_state, exit_state, red_lines)

    anchor_pov_protocol = None
    if anchor_pov:
        anchor_pov_protocol = f"""## 绝对锚点视界与动作接续协议
1. **单一摄影机法则**：你的文字必须像VR游戏一样，绝对锁定在【{anchor_pov}】的大脑中。只能描写他可见、可听、可触之事。严禁开启上帝视角跨越空间。
2. **直接动作起手**：第一句话必须严格基于 `entry_state` 的物理姿态或环境状态开始。禁止凭空回顾上文。
3. **毒性词库硬拦截**：禁止使用任何破坏连续性的时间/空间转场副词作为段落起手。
   - ❌ 绝对禁用："与此同时"、"此时"、"画面一转"、"殊不知"、"在另一边"、"而在这时"。
   - ✅ 正确做法：利用环境音，光线变化或角色的动作反应自然过渡。"""

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
    scene_intent_prompt = _render_scene_intent_prompt(scene_intent_data)

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

{style_control_prompt if style_control_prompt else ''}

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

{boundary_constraints_prompt}

## 【字数与内容完整性建议】
★ 目标字数：约 {word_count} 字 (允许根据剧情需要适度超出)
★ 优先级说明：请优先保证本节拍的剧情完整性、情感铺垫和动作细节。如果为了把故事讲好、讲透，导致字数超出预期，是完全可以接受的。切勿为了压缩字数而牺牲关键细节！

{anchor_pov_protocol if anchor_pov_protocol else ''}

## 🛑 危机递进与物理预警法则 (Escalation & Sensory Bridge Protocol)

在处理"日常平静状态"向"突发危机/激烈动作"转换的剧情点时，**绝对禁止从 0 直接跳到 100**。必须通过局部的微观物理变化来建立情绪的压迫感。

### ❌ 绝对禁止的转场方式：
1. **禁用偷懒的声明式过渡句**：严禁使用"这种宁静在下一秒被打破"、"突然"、"就在这时"、"毫无征兆地"作为段落的开头。
2. **禁止瞬间爆发**：禁止上一句话还在写微风和月光，下一句话立刻变成导弹爆炸。

### ✅ 必须执行的三段式危机爬升（Rule of Three）：
当剧变即将发生时，你的文字必须放慢速度，拆解为以下三个层次：
1. **微弱的异常（Anomaly）**：危机到来前的一两秒，先写极其细微的物理异样。（如：水杯里不自然的波纹、空气中突然刺耳的高频静电音、飞虫的惊落，气压气味的变化）。
2. **角色的错愕（Disconnect）**：主角的第一反应不应该是立刻明白发生了战争，而是短暂的疑惑或误判（如：以为是机器故障、以为是错觉），目光顺着异常看过去。
3. **彻底的爆发（Impact）**：在极度的安静或错愕中，真正的灾难或动作才以最猛烈的具象化形态砸在主角脸上。

## 🛑 海明威极致叙事与反AI味协议（最高优先级约束）

在扩写时，你的文字必须像手术刀一样干净利落，充满高密度的画面感。一旦触发以下"AI味"特征，将被系统判定为不及格：

### ❌ 绝对禁止（触发即失败）：
1. **禁止设定倾倒（Info-dumping）**：绝不准在动作或紧张情节发生时，打断节奏去大段解释世界观名词（如解释某个阶级、某种武器的背景）。让世界观自然消融在物理环境和对话中。
2. **禁止预告片式说教旁白**：严禁出现"命运的齿轮开始转动"、"时代的洪流"、"他此时还不知道自己将卷入怎样的旋涡"、"一场改变世界格局的战争开始了"这类上帝视角的虚词和评价词。主角只关注眼前的生死！
3. **禁止"紫壶文风（Purple Prose）"与形容词堆砌**：一个名词前最多只能有一个修饰语。绝对禁止诸如"廉价的、生锈的、过滤不彻底的空气"这类连环定语。做减法！

### ✅ 必须执行的句式编排：
1. **极致短句与碎镜式排版**：在面对危机爆发（如防空警报骤响、爆炸、遇袭）时，必须大量使用短句（字数少于10个字），甚至使用只有主谓结构的词组片段，并频繁使用回车键单独换行，以制造呼吸急促的压迫感。
   - *反面示例*：突然，一种毫无征兆的悸动从脚下的金属地板深处传了过来，那是一种低频的、足以引起内脏共鸣的颤栗。
   - *正面示例*：地板深处传来悸动。一种低频的颤栗。足以引起内脏共鸣。
2. **行为视角的局限性**：主角拥有强烈的认知局限。如果主角是底层劳工，他不会去思考"防线被饱和式轰炸瓦解"，他只会感受到"头顶的混凝土砸了下来，灰尘堵住了喉咙"。
3. **冰山理论（Show, Don't Tell）**：不要总结情绪（如"他感到无比绝望"），直接描写物理反应（如"汗水流进眼睛带来火辣辣的刺痛，他死死咬住发抖的牙关"）。

## 🛑 原住民视角与设定名词脱敏协议（In-Universe Protocol）

在使用设定集中的专有名词（如特定的机甲名、势力、术语）时，必须绝对摒弃"百科全书式的科普"，采取"原住民盲视原则"。

### ❌ 绝对禁止的名词出场方式：
1. **禁止"定语贴标签"**：严禁出现 `[等级/定语] + [名词]` 直接贴脸的句式。
   - *反面典型*："那是苏璃驾驶的A级机甲苍穹。" / "作为基因劣质者的底层劳工…"
2. **禁止突兀的说明**：不要在动作进行中突然停下来解释这个名词的来历、参数或社会地位。如果你必须要让读者知道它的特殊性，请通过**角色的反应、对话或系统UI的反馈**来侧面展现。

### ✅ 必须执行的名词出场方式：
1. **冰山式抛出（脱敏态）**：直接以代称或裸词出现，假装读者已经认识它。
   - *正面典型*："启动第二阶段防御方案。"白霆的声音低沉而冷静，"让'红月'待命。"（利用对话极其自然地抛出名字，绝不加多余解释）。
2. **先有形，后有名**：如果一台机甲首次登场，先写它造成的物理压迫感或视觉特征（如：巨大的阴影遮蔽了穹顶、液态核心在搏动），最后再通过角色的意识流或战术面板的锁定信息自然带出它的名字。
3. **常识词免检（豁免名录）**：对于具有现实认知基础的"软科幻复合词"（如：相位干扰弹、高周波震动刃、全息隐匿涂层），请直接当作日常用品写出，作者和读者都有常识，**绝对不要停下来解释它们是什么。**

## 核心规则
1. 严格遵循章节大纲进行创作
2. 保持角色性格和互动方式的连贯性
3. 根据角色关系约束调整互动氛围
4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等
5. 生成内容应尽可能符合上述字数建议
6. 段落之间请使用双换行符（\\n\\n）分隔，以确保排版清晰。
7. 严禁使用 Markdown 格式（如加粗、斜体、列表等），仅输出纯文本。"""
    action_summary = (
        beat_action_summary
        or getattr(chapter, "action_summary", None)
        or beat_summary
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
【字数建议】约 {word_count} 字（内容完整性优先）

写作方法：
- Show, don't tell：优先通过动作、感官、对话与细节呈现情绪和信息，避免直接讲解。
- hook 自然注入：将钩子信息融入情境、冲突或悬念，不要生硬贴标签。
- 若存在开放伏笔，必须通过环境细节或角色动作自然植入，不要显式解释"这是伏笔"。

请直接输出小说正文，不需要任何额外说明或标记。请确保剧情完整连贯。"""
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
    anchor_pov: str = None,
    sensory_translation_rule: str = None,
):
    beat_data = beat if isinstance(beat, dict) else {}
    scene_intent_data = scene_intent if isinstance(scene_intent, dict) else {}
    beat_summary = _normalize_text(beat_data.get("summary"))
    beat_action_summary = _normalize_text(beat_data.get("action_summary"), beat_summary)
    entry_state = _normalize_text(beat_data.get("entry_state"), f"承接上文并切入：{beat_summary[:40]}" if beat_summary else "承接上文并切入当前节拍。")
    exit_state = _normalize_text(beat_data.get("exit_state"), f"停在本节拍收束点：{beat_action_summary[:40]}" if beat_action_summary else "停在当前节拍收束状态，不越界推进。")
    red_lines = _normalize_text_list(beat_data.get("red_lines"))
    if not red_lines:
        red_lines = ["不得越过本节拍 exit_state 指向的剧情停点"]
    chunk_boundary_section = (
        "【Chunk 边界约束（剧情完整性优先）】\n"
        f"- 切入状态 entry_state：{entry_state}\n"
        f"- 目标收束状态 exit_state：{exit_state}\n"
        f"- 绝对禁忌 red_lines：{'；'.join(red_lines)}\n"
        "- 请平滑过渡至 exit_state，确保本节拍内的事件和冲突已完整闭环。\n"
        f"- 此段落必须严格锁定在【{beat_data.get('pov_character', '未指定')}】的第一/第三人称有限视角！"
    )
    intent_constraints = _normalize_text_list(scene_intent_data.get("constraints"))

    pacing_type = beat_data.get("pacing_type", "Medium")
    pacing_instructions = {
        "Fast": "多用短句、动词，减少修饰语。强调动作的紧凑衔接，营造紧张感或速度感。避免过长的心理描写或静态环境描写。",
        "Medium": "平衡长短句，叙事节奏平稳。交替使用动作描写与心理/环境描写，推动情节稳步发展。",
        "Slow": "多用长句、感官细节描写（视觉、听觉、嗅觉等）。强调氛围渲染与内心独白，放慢叙事速度，通过细节堆叠增强沉浸感。",
    }
    pacing_instruction = pacing_instructions.get(pacing_type, pacing_instructions["Medium"])
    pacing_section = f"【节奏与句式控制 (Pacing: {pacing_type})】\n{pacing_instruction}"

    system_prompt, user_prompt = build_draft_agent_prompt(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        word_count=target_words,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        beat=beat_data,
        scene_intent=scene_intent_data,
        hook_contexts=hook_contexts,
        locations=locations,
        anchor_pov=anchor_pov,
    )

    if sensory_translation_rule:
        sensory_constraint = f"## 【最高优先级约束：感官转化法则】\n{sensory_translation_rule}"
        system_prompt = f"{sensory_constraint}\n\n{system_prompt}"

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
位置：{beat_data.get("position", 1)}
BeatID：{_normalize_text(beat_data.get("beat_id"))}
摘要：{beat_summary}
动作摘要：{beat_action_summary}
场景：{_normalize_text(beat_data.get("location"), "未指定")}
视角角色：{_normalize_text(beat_data.get("pov_character"), "未指定")}
建议字数：{target_words}

{chunk_boundary_section}

【Scene Intent】
标签：{_normalize_text(scene_intent_data.get("intent_label"), "推进剧情")}
目标：{_normalize_text(scene_intent_data.get("goal"), "推进剧情")}
风险：{_normalize_text(scene_intent_data.get("stakes"), "无")}
约束：{", ".join(intent_constraints) if intent_constraints else "无"}

{continuity_section}

{pacing_section}

请只输出当前 beat 对应的正文 chunk，不要重复前文，不要输出解释。"""
    return system_prompt, chunk_user_prompt

"""
审阅提示词模块。

职责：提供章节审阅（Review）和精修（Refine）阶段的提示词构建和结果解析功能。

子模块：
- review_prompts_utils: 边界渲染、问题类型标准化、结果解析
"""

import json

from backend.models import Chapter, Book
from backend.services.prompts.review_prompts_utils import (
    render_boundary_brief as _render_boundary_brief,
    parse_review_result,
)


def build_review_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, chapter_outline: str, draft_text: str, beats: list = None):
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
    boundary_brief = _render_boundary_brief(chapter)

    reference_beats_text = ""
    if beats and isinstance(beats, list):
        beats_info = []
        for idx, beat in enumerate(beats, start=1):
            beat_id = beat.get("beat_id", f"beat_{idx:02d}")
            summary = beat.get("summary", "") or f"Beat {idx}"
            beats_info.append(f'{{"beat_id": "{beat_id}", "summary": "{summary}"}}')
        reference_beats_text = f"\n## 剧情节拍规划 (Reference Beats)\n你正在审阅合并后的完整章节文本。为了方便后续精修定位，我为你提供了本章原本的剧情节拍规划。\n当你在正文中发现 OOC、逻辑硬伤或越界问题时，请对照这个规划表，**推理出该问题情节属于哪个或哪几个 Beat**，并将对应的 `beat_id` 填入 `target_beat_ids` 字段。\n\n[{', '.join(beats_info)}]"

    system_prompt = f"""{global_sys_prompt}

你是一个严格的小说质量审查员。你不负责写小说，只负责检查初稿是否符合要求。

{worldview_prompt if worldview_prompt else ''}

## 角色设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## Boundary & Pacing 边界基线
{boundary_brief}
{reference_beats_text}

## 你的任务
1. 检查初稿是否遵循了章节大纲要求
2. 检查角色是否出现 OOC (Out Of Character，人设崩塌)
3. 检查是否有逻辑硬伤或情节漏洞
4. 检查是否遗漏了应该有的剧情点
5. 检查是否出现 Boundary & Pacing 越界（越过 exit_state 或触发 red_lines）
6. 检查是否存在大幅删段、关键段落缺失或过度压缩导致的完整性损伤

注意：初稿已经过分段质检，请重点关注**段落间的连贯性**和**全局逻辑**，对于细枝末节的措辞问题可适当放宽。

## 输出格式要求
你必须以 JSON 格式输出，结构如下：
{{
    "pass": true/false,
    "issues": [
        {{
            "type": "OOC/剧情遗漏/逻辑硬伤/PACING_OVERFLOW/完整性缺失",
            "severity": "high/medium/low",
            "description": "详细描述问题",
            "target_beat_ids": ["beat_01", "beat_02"]
        }}
    ],
    "revision_plan": "给出具体的重写建议"
}}

- pass: true 表示所有检查通过，可以直接输出
- pass: false 表示存在问题，需要重写
- issues: 列出发现的问题
- **重要**：每个 issue 必须包含 `target_beat_ids` 字段，值为问题所属的 Beat ID 列表（如 ["beat_03", "beat_04"]）。请根据正文内容与 Reference Beats 地图进行推理定位。
- 当存在以下任一情况时，必须新增一条 issue.type = "PACING_OVERFLOW"：
  1) 文本越过任一 beat 的 exit_state
  2) 文本触发任一 beat 的 red_lines 禁忌事件
- 当发现重写版本相对原有叙事出现大幅删段、关键段落被删除且未等价重建时，必须新增一条 issue.type = "完整性缺失"
- revision_plan: 给出具体的重写指导
- 若存在 PACING_OVERFLOW，revision_plan 必须明确"回退到越界前状态、放慢节奏、悬停在对应 exit_state"
- 若存在完整性缺失，revision_plan 必须明确"补回被删减的关键段落信息，禁止继续大幅删段"

## 【精修策略指导 - 精准裁剪原则】
由于 Draft 阶段采用了"冰山模型"，文本生成时放宽了部分红线限制以保持创意流动性。如果发现某段越过 exit_state：

**推荐策略（精准裁剪）**：
1. 不要要求全部重写
2. 精准定位越过边界的具体句子或段落
3. 通过微调动作或添加收束句，使文本停在规定的 exit_state 上
4. 保持原有的文本灵气和叙事节奏，只调整结尾边界

**示例**：
- 原文结尾："他冲向门口，推开门，发现敌人已经在走廊尽头。"
- 如果 exit_state 要求停在"准备开门"：修改为"他冲向门口，手搭在门把上，心跳如鼓。"
- 这样保留了动作张力，同时遵守了边界约束

**禁止策略**：
- 不要为了合规而大幅删减关键情节
- 不要改变原文的整体语气和风格
- 不要添加突兀的转折或解释

注意：你必须输出合法的 JSON 格式，不要输出任何其他内容！"""
    user_prompt = f"""请审查以下初稿:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter_outline}

【Boundary & Pacing 边界基线】
{boundary_brief}

【初稿内容】
{draft_text}

请输出 JSON 格式的审查结果。"""
    return system_prompt, user_prompt


def build_refine_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, draft_text: str, revision_plan: str, word_count: int):
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
    boundary_brief = _render_boundary_brief(chapter)
    system_prompt = f"""{global_sys_prompt}

{worldview_prompt if worldview_prompt else ''}

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## Boundary & Pacing 边界基线
{boundary_brief}

## 你的任务
你是一个精修编辑，需要根据审查意见对初稿进行针对性重写。
请仔细阅读以下审查意见和初稿，然后生成修改后的版本。

## 字数硬性约束（最高优先级，不可违反）
- 原稿字数约 **{word_count} 字**
- 精修后字数**不得低于原稿的 90%**（即不得低于 {int(word_count * 0.9)} 字）
- 严禁通过删段、合并段落或省略细节来缩减字数
- 若审查意见要求修改某处，必须用等量或更多新文字替换，而非直接删除

## 核心规则
1. 严格遵循审查意见进行修改
2. 保持原有优秀的部分
3. 修正被指出的问题
4. 确保修改后的内容符合章节大纲
5. 保持角色性格一致性
6. 如审查意见包含 PACING_OVERFLOW，必须执行"回退-降速-悬停"策略：先回退越界剧情，再放慢推进，最后停在对应 exit_state
7. 重写时必须保留原稿的关键段落信息与叙事骨架，不得大幅删除段落
8. 若必须删除局部段落，必须以等价的新段落补回信息、动机与情绪链路，保证前后完整

## 🛑 精修文笔禁令（Negative Constraint - 最高优先级）
你只能通过修改具体的【动作动词】和【环境破坏力】来体现审查意见，严格遵循 'Show, don't tell' 原则。
在正文生成中，【严禁】使用任何判定式、解释式的说教词汇：
- ❌ 严禁出现：「不是...而是...」、「这并非...只是一种...」、「这说明了...」、「这意味着...」、「这代表了...」
- ❌ 严禁出现：「其实...」、「事实上...」、「实际上...」、「本质上...」
- ❌ 严禁出现：「从此...」、「于是...」、「因此...」（作为解释因果的副词）
- ❌ 严禁打破第四面墙对读者进行解释说明
- ✅ 正确做法：用具体的动作、感官细节和环境反应来表达审查要求的内容，让情节自己说话

**修正示例**：
- 错误：「这不是恐惧，只是一种本能的警觉。」
- 正确：「后颈的汗毛一根根竖了起来。」
- 错误：「这并非背叛，而是一种无奈的选择。」
- 正确：「他别过脸去，握剑的手指关节泛白。」"""
    user_prompt = f"""请根据以下审查意见重写初稿:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}

【Boundary & Pacing 边界基线】
{boundary_brief}

【审查意见】
{revision_plan}

【当前初稿】
{draft_text}

若审查意见涉及 PACING_OVERFLOW，请执行以下策略：

**推荐策略（精准裁剪）**：
1. 定位越过 exit_state 的具体句子（通常是最后 1-3 句）
2. 不要删除整段，而是微调结尾动作
3. 通过添加收束句或微调动作，使文本停在规定的 exit_state 上
4. 保持原有文本的灵气和叙事节奏

**示例**：
- 原文结尾："他冲向门口，推开门，发现敌人已经在走廊尽头。"
- 目标 exit_state："准备开门，但未看到门外"
- 精准裁剪："他冲向门口，手搭在门把上，心跳如鼓。门后的未知让他迟疑了一瞬。"
- 这样既保留了动作张力，又遵守了边界约束

**回退策略（仅在严重越界时使用）**：
1) 删除越过 exit_state 之后的推进内容
2) 撤销触发 red_lines 的事件与行为  
3) 放慢叙事推进并停在对应 exit_state，保留必要悬念

**完整性保护原则**：
1) 优先使用精准裁剪，避免大幅删段
2) 必须保留原稿中的关键情节节点、动机链与情绪递进
3) 如需调整结构，只能重写优化，不可直接删去关键段落
4) 修改后的文本长度应与原文接近（±20%），严禁过度压缩

请直接输出修改后的完整小说正文，不需要任何额外说明或标记。请确保剧情完整连贯。"""
    return system_prompt, user_prompt


def build_chunk_review_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, beat_summary: str, chunk_text: str):
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"

    static_states = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")

    system_prompt = f"""{global_sys_prompt}

你是一个严格的小说片段质检员。
请检查生成的片段是否符合剧情要求，且角色行为符合设定。

## 角色设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 检查标准
1. **剧情符合度**: 是否完成了剧情摘要(Summary)中的关键动作？
2. **角色一致性**: 是否存在严重 OOC (Out Of Character)？
3. **文本质量**: 是否有严重的重复、乱码或未完成的句子？

## 输出格式 (JSON)
{{
    "pass": true/false,
    "issues": ["简短描述问题1", "简短描述问题2"],
    "revision_instruction": "一句话修改指令"
}}
注意：若问题不严重（如轻微措辞不当），请优先判定为 pass: true。仅在严重逻辑错误或 OOC 时返回 false。"""

    user_prompt = f"""请质检以下小说片段:

【剧情摘要】
{beat_summary}

【生成片段】
{chunk_text}

请输出 JSON 格式质检结果。"""

    return system_prompt, user_prompt


def build_chunk_refine_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, beat_summary: str, chunk_text: str, revision_instruction: str):
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"

    static_states = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")

    system_prompt = f"""{global_sys_prompt}

你是一个精修编辑。请根据修改指令，对小说片段进行快速修正。

## 角色设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 你的任务
根据指令重写片段，保持原有风格，修复指出的问题。
直接输出修改后的正文，不要包含任何解释。"""

    user_prompt = f"""请重写以下片段:

【剧情摘要】
{beat_summary}

【修改指令】
{revision_instruction}

【原片段】
{chunk_text}

请直接输出修改后的正文。"""

    return system_prompt, user_prompt

"""
审阅提示词模块。

职责：提供章节审阅（Review）和精修（Refine）阶段的提示词构建和结果解析功能。

业务场景：
- Review Agent: 对章节初稿进行质量检查，包括 OOC、剧情合规性、逻辑完整性
- Refine Agent: 根据审阅意见重写初稿
- Chunk Review/Refine: 对单个片段进行快速质检和修正

工作流位置：
- 位于 Agentic 工作流的 DRAFTING 阶段之后
- 输入：章节信息、初稿文本、审查意见
- 输出：审阅结果或修改后的正文

主要函数：
- build_review_agent_prompt: 构建审阅提示词
- build_refine_agent_prompt: 构建精修提示词
- parse_review_result: 解析审阅结果
- build_chunk_review_prompt: 构建分段审阅提示词
- build_chunk_refine_prompt: 构建分段精修提示词
"""

import json
import re

from backend.models import Chapter, Book


def _render_boundary_brief(chapter: Chapter) -> str:
    beats = getattr(chapter, "story_beats", None)
    if not isinstance(beats, list) or not beats:
        return "暂无节拍边界数据，请结合章节大纲谨慎判定越界与配速风险。"
    ordered_beats = sorted(beats, key=lambda beat: getattr(beat, "position", 0) or 0)
    lines = []
    for idx, beat in enumerate(ordered_beats, start=1):
        summary = str(getattr(beat, "summary", "") or "").strip() or f"Beat {idx}"
        entry_state = str(getattr(beat, "entry_state", "") or "").strip() or "未提供"
        exit_state = str(getattr(beat, "exit_state", "") or "").strip() or "未提供"
        red_lines = getattr(beat, "red_lines", None)
        if isinstance(red_lines, list):
            red_line_items = [str(item).strip() for item in red_lines if str(item).strip()]
        else:
            red_line_items = []
        red_line_text = "；".join(red_line_items) if red_line_items else "无"
        lines.append(
            f"{idx}. {summary}\n"
            f"   - entry_state: {entry_state}\n"
            f"   - exit_state: {exit_state}\n"
            f"   - red_lines: {red_line_text}"
        )
    return "\n".join(lines)


def _normalize_issue_type(raw_type, description: str) -> str:
    issue_type = str(raw_type or "").strip()
    normalized = issue_type.upper()
    description_text = str(description or "")
    lowered_issue_type = issue_type.lower()
    lowered_description = description_text.lower()
    if (
        normalized == "PACING_OVERFLOW"
        or "PACING_OVERFLOW" in normalized
        or "越界" in issue_type
        or "越过" in issue_type
        or "超速" in issue_type
        or "收束" in issue_type
        or "exit_state" in issue_type.lower()
        or "red_line" in issue_type.lower()
        or "越界" in description_text
        or "越过" in description_text
        or "超速" in description_text
        or "收束" in description_text
        or "exit_state" in description_text.lower()
        or "red_line" in description_text.lower()
    ):
        return "PACING_OVERFLOW"
    if (
        "完整性" in issue_type
        or "段落" in issue_type
        or "删段" in issue_type
        or "删减" in issue_type
        or "压缩" in issue_type
        or "integrity" in lowered_issue_type
        or "paragraph" in lowered_issue_type
        or "完整性" in description_text
        or "段落" in description_text
        or "删段" in description_text
        or "删减" in description_text
        or "压缩" in description_text
        or "integrity" in lowered_description
        or "paragraph" in lowered_description
    ):
        return "完整性缺失"
    if "OOC" in normalized:
        return "OOC"
    if "剧情遗漏" in issue_type or "PLOT MISSING" in normalized or "MISSING" in normalized:
        return "剧情遗漏"
    if "逻辑" in issue_type or "LOGIC" in normalized or "FLAW" in normalized:
        return "逻辑硬伤"
    return "逻辑硬伤"


def _build_default_revision_plan(has_pacing_overflow: bool) -> str:
    if has_pacing_overflow:
        return "请先回退到越界前的收束节点，删除触发 red_lines 的情节，放慢叙事节奏并悬停在对应 exit_state，再补齐必要动机后输出完整正文。"
    return "请按章节大纲与角色设定修复逻辑问题，保留原文关键段落结构，避免大幅删段，并返回完整正文。"


def build_review_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, chapter_outline: str, draft_text: str, beats: list = None):
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

    新增参数：
    - beats: 剧情节拍列表，用于构建 Reference_Beats 地图，帮助定位问题所属的 Beat
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
    """
    构建精修 Agent (Refine Agent) 的提示词，根据审查意见重写初稿。

    核心任务：
    - 基于 revision_plan 针对性修改
    - 保持原有优秀部分不被破坏
    - 强约束正文完整性，禁止通过大幅删段完成修改

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
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回为空，无法完成质检。", "target_beat_ids": []}],
            "revision_plan": "请基于章节大纲重新审查，并仅输出合法 JSON。",
            "target_beat_ids": [],
        }, "Empty response from Review Agent"
    candidates = [text]
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
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
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回内容无法解析为合法 JSON。", "target_beat_ids": []}],
            "revision_plan": "请严格按约定 JSON 结构输出审查结论，不要附加解释文本。",
            "target_beat_ids": [],
        }, parse_error or "Review JSON parse failed"
    raw_issues = parsed_obj.get("issues")
    normalized_issues = []
    all_target_beat_ids = set()
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if isinstance(issue, dict):
                description = str(issue.get("description") or "").strip()
                issue_type = _normalize_issue_type(issue.get("type"), description)
                severity = str(issue.get("severity") or "").strip().lower()
                if severity not in {"high", "medium", "low"}:
                    severity = "medium"
                target_beat_ids = issue.get("target_beat_ids")
                if isinstance(target_beat_ids, list):
                    for bid in target_beat_ids:
                        if isinstance(bid, str) and bid.strip():
                            all_target_beat_ids.add(bid.strip())
                normalized_issues.append(
                    {
                        "type": issue_type,
                        "severity": severity,
                        "description": description or "未提供问题描述",
                        "target_beat_ids": target_beat_ids if isinstance(target_beat_ids, list) else [],
                    }
                )
            elif isinstance(issue, str) and issue.strip():
                description = issue.strip()
                normalized_issues.append(
                    {
                        "type": _normalize_issue_type("", description),
                        "severity": "medium",
                        "description": description,
                        "target_beat_ids": [],
                    }
                )
    revision_plan = parsed_obj.get("revision_plan")
    has_pacing_overflow = any(issue.get("type") == "PACING_OVERFLOW" for issue in normalized_issues)
    if not isinstance(revision_plan, str) or not revision_plan.strip():
        revision_plan = _build_default_revision_plan(has_pacing_overflow)
    elif has_pacing_overflow:
        lowered_revision_plan = revision_plan.lower()
        if (
            "回退" not in revision_plan
            and "exit_state" not in lowered_revision_plan
            and "悬停" not in revision_plan
            and "收束" not in revision_plan
        ):
            revision_plan = (
                f"{revision_plan.rstrip()}\n"
                "补充要求：请先回退越界剧情，放慢推进并悬停在对应 exit_state，确保不触发 red_lines。"
            )
    result = {
        "pass": bool(parsed_obj.get("pass", False)),
        "issues": normalized_issues,
        "revision_plan": revision_plan,
        "target_beat_ids": list(all_target_beat_ids)
    }
    return result, None


def build_chunk_review_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, beat_summary: str, chunk_text: str):
    """
    构建分段审阅 Agent (Chunk Review Agent) 的提示词。
    
    相比全章审阅，分段审阅更关注：
    1. 局部 OOC (Out Of Character)
    2. 是否完成了 Beat 的指令 (summary)
    3. 基础文笔流畅度
    
    忽略：
    1. 前后文连贯性 (因为是分段并行生成，缺乏上下文)
    2. 全局伏笔
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    
    # 简化版角色设定 (只取名字和静态设定，减少 Token)
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
    """
    构建分段精修 Agent (Chunk Refine Agent) 的提示词。
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    
    # 简化版角色设定
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

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
    return "请按章节大纲与角色设定修复逻辑问题，并返回完整正文。"


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
    boundary_brief = _render_boundary_brief(chapter)
    system_prompt = f"""{global_sys_prompt}

你是一个严格的小说质量审查员。你不负责写小说，只负责检查初稿是否符合要求。

{worldview_prompt if worldview_prompt else ''}

## 角色设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## Boundary & Pacing 边界基线
{boundary_brief}

## 你的任务
1. 检查初稿是否遵循了章节大纲要求
2. 检查角色是否出现 OOC (Out Of Character，人设崩塌)
3. 检查是否有逻辑硬伤或情节漏洞
4. 检查是否遗漏了应该有的剧情点
5. 检查是否出现 Boundary & Pacing 越界（越过 exit_state 或触发 red_lines）

注意：初稿已经过分段质检，请重点关注**段落间的连贯性**和**全局逻辑**，对于细枝末节的措辞问题可适当放宽。

## 输出格式要求
你必须以 JSON 格式输出，结构如下：
{{
    "pass": true/false,
    "issues": [
        {{
            "type": "OOC/剧情遗漏/逻辑硬伤/PACING_OVERFLOW",
            "severity": "high/medium/low",
            "description": "详细描述问题"
        }}
    ],
    "revision_plan": "给出具体的重写建议"
}}

- pass: true 表示所有检查通过，可以直接输出
- pass: false 表示存在问题，需要重写
- issues: 列出发现的问题
- 当存在以下任一情况时，必须新增一条 issue.type = "PACING_OVERFLOW"：
  1) 文本越过任一 beat 的 exit_state
  2) 文本触发任一 beat 的 red_lines 禁忌事件
- revision_plan: 给出具体的重写指导
- 若存在 PACING_OVERFLOW，revision_plan 必须明确“回退到越界前状态、放慢节奏、悬停在对应 exit_state”

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
6. 如审查意见包含 PACING_OVERFLOW，必须执行“回退-降速-悬停”策略：先回退越界剧情，再放慢推进，最后停在对应 exit_state
7. 生成内容必须满足上述字数要求"""
    user_prompt = f"""请根据以下审查意见重写初稿:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

【Boundary & Pacing 边界基线】
{boundary_brief}

【审查意见】
{revision_plan}

【当前初稿】
{draft_text}

若审查意见涉及 PACING_OVERFLOW，请执行以下回退策略：
1) 删除越过 exit_state 之后的推进内容
2) 撤销触发 red_lines 的事件与行为
3) 放慢叙事推进并停在对应 exit_state，保留必要悬念

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
            "issues": [{"type": "审查异常", "severity": "high", "description": "Review Agent 返回内容无法解析为合法 JSON。"}],
            "revision_plan": "请严格按约定 JSON 结构输出审查结论，不要附加解释文本。",
        }, parse_error or "Review JSON parse failed"
    raw_issues = parsed_obj.get("issues")
    normalized_issues = []
    if isinstance(raw_issues, list):
        for issue in raw_issues:
            if isinstance(issue, dict):
                description = str(issue.get("description") or "").strip()
                issue_type = _normalize_issue_type(issue.get("type"), description)
                severity = str(issue.get("severity") or "").strip().lower()
                if severity not in {"high", "medium", "low"}:
                    severity = "medium"
                normalized_issues.append(
                    {
                        "type": issue_type,
                        "severity": severity,
                        "description": description or "未提供问题描述",
                    }
                )
            elif isinstance(issue, str) and issue.strip():
                description = issue.strip()
                normalized_issues.append(
                    {
                        "type": _normalize_issue_type("", description),
                        "severity": "medium",
                        "description": description,
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
    result = {"pass": bool(parsed_obj.get("pass", False)), "issues": normalized_issues, "revision_plan": revision_plan}
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

import json
import re

from backend.models import Chapter, Book


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
    issues = parsed_obj.get("issues")
    if not isinstance(issues, list):
        issues = []
    revision_plan = parsed_obj.get("revision_plan")
    if not isinstance(revision_plan, str) or not revision_plan.strip():
        revision_plan = "请按章节大纲与角色设定修复逻辑问题，并返回完整正文。"
    result = {"pass": bool(parsed_obj.get("pass", False)), "issues": issues, "revision_plan": revision_plan}
    return result, None

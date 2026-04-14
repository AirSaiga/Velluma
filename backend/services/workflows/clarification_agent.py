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
澄清阶段工作流 - 用户意图分析与需求澄清。

职责：
- 调用 Clarification Agent 分析用户的简略大纲
- 找出剧情中缺乏表现力、感官细节或情感动机的【信息空白】
- 生成结构化的澄清问题，供前端展示给用户

业务场景：
- 用户发起大纲生成、节拍调整或章节重写等开放式请求时
- 在 Planning 阶段之前作为前置信息收集步骤

主要功能：
- 意图完整性评估
- 动态澄清问题生成

依赖项：
- backend.services.prompts.clarification_prompts: Clarification Prompt 模板
- backend.services.llm: LLM 调用接口
- backend.models: 数据模型

使用方式：
    result = await execute_clarification_stage(ambiguous_text, book, ...)
"""

from typing import Any, Optional, Dict, List
import json

from backend.models import Chapter, Book
from backend.world_state_schemas import WorldTerminalState
from backend.services.llm import call_llm
from backend.services.utils.logging import get_runtime_logger
from backend.services.prompts.clarification_prompts import build_clarification_agent_prompt

logger = get_runtime_logger(__name__)


async def execute_clarification_stage(
    ambiguous_text: str,
    book: Book,
    chapter: Optional[Chapter] = None,
    entities: Optional[list] = None,
    relationships: Optional[list] = None,
    open_hooks: Optional[list] = None,
    previous_chapter_summary: Optional[str] = None,
    locations: Optional[list] = None,
    global_taboos: Optional[str] = None,
    author_intent: Optional[str] = None,
    user_instruction: Optional[str] = None,
    previous_issues: Optional[List[str]] = None,
    previous_chapter_snapshot: Optional[dict] = None,
    previous_world_terminal_state: Optional[WorldTerminalState] = None,
    api_key: str = "",
    base_url: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """执行意图澄清分析，生成澄清问题或修正后的大纲。

    Args:
        ambiguous_text: 用户的简略大纲或自然语言指令
        book: 当前书籍实体
        chapter: 当前章节实体（可选，用于提供上下文）
        entities: 相关的角色实体列表（可选）
        relationships: 角色关系列表（可选）
        open_hooks: 开放伏笔列表（可选）
        previous_chapter_summary: 上一章摘要（可选）
        locations: 章节关联的地点列表（可选）
        global_taboos: 全局禁忌（可选）
        author_intent: 作者意图（可选）
        user_instruction: 用户的补充回答（交互式流程用）
        previous_issues: 之前识别出的问题（交互式流程用）
        previous_chapter_snapshot: 上一章的世界状态快照（可选）
        previous_world_terminal_state: V4.0 结构化世界终端状态（可选）
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name

    Returns:
        Dict[str, Any]: 包含 is_ambiguous, identified_issues, clarifying_questions, refined_text
    """
    logger.info(f"[Clarification] 开始分析大纲意图，输入长度: {len(ambiguous_text)}, 是否带有补充回答: {bool(user_instruction)}")
    
    # 如果ambiguous_text为空，但用户有补充回答，使用用户的回答作为ambiguous_text
    if not ambiguous_text and user_instruction:
        logger.info("[Clarification] ambiguous_text为空，使用用户回答作为输入")
        ambiguous_text = user_instruction
    
    system_prompt, user_prompt = build_clarification_agent_prompt(
        book=book,
        ambiguous_text=ambiguous_text,
        chapter=chapter,
        entities=entities,
        relationships=relationships,
        open_hooks=open_hooks,
        previous_chapter_summary=previous_chapter_summary,
        locations=locations,
        global_taboos=global_taboos,
        author_intent=author_intent,
        user_instruction=user_instruction,
        previous_issues=previous_issues,
        previous_chapter_snapshot=previous_chapter_snapshot,
        previous_world_terminal_state=previous_world_terminal_state,
    )
    
    try:
        response_raw = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,  # 稍微给一点创造性，用于生成建议
            response_format={"type": "json_object"},
        )
        
        # 移除可能存在的 Markdown 代码块标记
        cleaned_response = response_raw.strip()
        if cleaned_response.startswith("```json"):
            cleaned_response = cleaned_response[7:]
        elif cleaned_response.startswith("```"):
            cleaned_response = cleaned_response[3:]
        if cleaned_response.endswith("```"):
            cleaned_response = cleaned_response[:-3]
        cleaned_response = cleaned_response.strip()
        
        response_json = json.loads(cleaned_response)
        
        is_ambiguous = response_json.get("is_ambiguous", False)
        
        if is_ambiguous:
            logger.info("[Clarification] 大纲存在信息空白，已生成澄清建议")
        else:
            logger.info("[Clarification] 大纲意图清晰")
            
        # 确保返回的JSON包含refined_text字段
        if "refined_text" not in response_json:
            # 如果是第二轮（用户已回答），但没有返回refined_text，使用原始文本作为默认值
            if user_instruction:
                response_json["refined_text"] = ambiguous_text
            else:
                response_json["refined_text"] = ""
        
        # 添加原始大纲字段，用于前端显示
        response_json["original_outline"] = ambiguous_text
        
        return response_json
        
    except json.JSONDecodeError as e:
        logger.error(f"[Clarification] JSON解析失败: {str(e)}")
        return {
            "is_ambiguous": False,
            "identified_issues": [],
            "clarification_suggestions": [],
            "refined_text": ambiguous_text,
            "original_outline": ambiguous_text,
            "error": "JSON parse error"
        }
    except Exception as e:
        logger.error(f"[Clarification] 意图分析阶段发生错误: {str(e)}")
        return {
            "is_ambiguous": False,
            "identified_issues": [],
            "clarification_suggestions": [],
            "refined_text": ambiguous_text,
            "original_outline": ambiguous_text,
            "error": str(e)
        }

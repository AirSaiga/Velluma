from typing import Any, Tuple, Optional

from backend.services.prompts import build_review_agent_prompt, parse_review_result, build_chunk_refine_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter, Book, Character, CharacterRelationship


async def review_draft(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    chapter_outline: str,
    draft_text: str,
    api_key: str,
    base_url: str,
    model: str,
) -> Tuple[dict, bool]:
    """
    【基础版】审阅章节初稿，检查 OOC、剧情合规性和逻辑完整性。
    
    职责：调用 Review Agent 进行基础质量检查。
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        chapter_outline: 章节大纲
        draft_text: 待审阅的草稿文本
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
    
    Returns:
        Tuple[dict, bool]: (review_result_dict, passed_bool)
        - review_result_dict: 审阅结果字典，包含 pass、issues、revision_plan 等字段
        - passed_bool: 审阅是否通过
    """
    system_prompt, user_prompt = build_review_agent_prompt(
        chapter, book, entities, relationships, chapter_outline or "", draft_text
    )
    
    review_result_json = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    
    review_result, _ = parse_review_result(review_result_json)
    
    return review_result, review_result.get("pass", False)


async def review_draft_with_beats(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    chapter_outline: str,
    draft_text: str,
    beats: list[dict],
    api_key: str,
    base_url: str,
    model: str,
) -> Tuple[dict, bool]:
    """
    【增强版】审阅章节初稿，支持 Beat 级别的精准问题定位。
    
    职责：调用 Review Agent 进行质量检查，并提供 Beat 级别的问题定位信息，
    用于后续的局部精修。
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        chapter_outline: 章节大纲
        draft_text: 待审阅的草稿文本
        beats: 剧情节拍列表，用于构建 Reference Beats 地图
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
    
    Returns:
        Tuple[dict, bool]: (review_result_dict, passed_bool)
        - review_result_dict: 包含 target_beat_ids 用于定位问题 Beat
        - passed_bool: 审阅是否通过
    """
    system_prompt, user_prompt = build_review_agent_prompt(
        chapter, book, entities, relationships, chapter_outline or "", draft_text, beats=beats
    )
    
    review_result_json = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    
    review_result, _ = parse_review_result(review_result_json)
    
    return review_result, review_result.get("pass", False)


async def surgical_refinement(
    chapter: Chapter,
    book: Book,
    entities: list[Any],
    relationships: list[CharacterRelationship],
    draft_text: str,
    target_exit_state: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    【精准裁剪】对越过 exit_state 的文本进行精准裁剪修复。
    
    职责：不是重写整段，而是精准裁剪最后几句话，通过微调动作使其
    停在规定的 exit_state 上，保持原有文本灵气。
    
    策略：
    1. 分析文本与 target_exit_state 的差距
    2. 只修改最后 1-3 句话
    3. 添加收束句或微调动作
    4. 保持原有语气和风格
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 角色实体列表
        relationships: 角色关系列表
        draft_text: 需要裁剪的原文
        target_exit_state: 目标收束状态
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
    
    Returns:
        str: 裁剪后的文本
    """
    system_prompt = f"""你是一个精准裁剪编辑。

你的任务是对文本进行**最小化修改**，使其停在指定的 exit_state 上。

## 核心原则
1. **最小干预**：只修改最后 1-3 句话，不要动前面的内容
2. **保持灵气**：保留原文的语气、节奏和情感张力
3. **精准收束**：通过微调动作或添加收束句，使文本停在 exit_state

## 修改示例
原文结尾：
"他冲向门口，推开门，发现敌人已经在走廊尽头。他大喊一声，冲了上去。"

target_exit_state: "停在准备开门，但未看到门外"

错误修改（过度删改）：
"他来到门口，犹豫了一下。"

正确修改（精准裁剪）：
"他冲向门口，手搭在门把上，心跳如鼓。门后的未知让他迟疑了一瞬。"

## 禁止事项
- 不要大幅删减前面的内容
- 不要改变整体语气和风格  
- 不要添加突兀的解释"""

    user_prompt = f"""请对以下文本进行精准裁剪：

【目标收束状态】
{target_exit_state}

【原文】
{draft_text}

请只修改最后几句话，使其停在目标收束状态。输出完整的修改后文本。"""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.4,  # 比正常写作低，保持稳定性
            max_tokens=len(draft_text) * 2,  # 确保足够长度
        )
        
        refined_text = clean_llm_output(response).strip()
        
        # 如果裁剪后的文本过短，回退到原文
        if len(refined_text) < len(draft_text) * 0.5:
            print(f"[Surgical Refinement] 裁剪后文本过短，回退到原文")
            return draft_text
        
        return refined_text
        
    except Exception as e:
        print(f"[Surgical Refinement Error] {e}")
        return draft_text


async def quick_boundary_fix(
    chunk_text: str,
    beat_summary: str,
    target_exit_state: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    【快速边界修复】对单个 Beat 的越界问题进行快速修复。
    
    用于 Chunk QC 阶段的快速边界调整，比 surgical_refinement 更轻量。
    
    Args:
        chunk_text: Beat 生成的文本
        beat_summary: Beat 摘要
        target_exit_state: 目标收束状态
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
    
    Returns:
        str: 修复后的文本
    """
    system_prompt = """你是一个快速边界修复助手。

任务：调整文本结尾，使其停在指定的 exit_state。

规则：
1. 只修改最后 1-2 句话
2. 保持前文不变
3. 添加收束句或微调动作
4. 输出完整文本"""

    user_prompt = f"""【Beat 摘要】
{beat_summary}

【目标收束状态】
{target_exit_state}

【当前文本】
{chunk_text}

请调整结尾使其停在目标状态。输出完整文本："""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.5,
            max_tokens=len(chunk_text) * 2,
        )
        
        return clean_llm_output(response).strip()
        
    except Exception as e:
        print(f"[Quick Boundary Fix Error] {e}")
        return chunk_text

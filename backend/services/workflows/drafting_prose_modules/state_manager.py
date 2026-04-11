"""
状态管理器模块 - 动态状态更新和关系状态管理。

职责：
- 管理情绪状态更新
- 管理关系状态变更
- 提供初始状态构建

原子组件：
- update_dynamic_state: 更新动态状态
- update_emotional_state: 更新情绪状态
- build_initial_relational_state: 构建初始关系状态
- merge_relational_delta: 合并关系状态变更

依赖项：
- backend.services.prompts: Prompt 构建
- backend.schemas: 状态更新结果类型

使用方式：
    from backend.services.workflows.drafting_prose_modules.state_manager import (
        update_dynamic_state,
        update_emotional_state,
        build_initial_relational_state,
    )
"""

import json
import logging
from typing import Any, List, Optional
from backend.services.workflows.beat_utils import get_target_words

from backend.schemas import DynamicStateUpdateResult
from backend.services.llm import call_llm
from backend.services.prompts import (
    build_dynamic_state_update_prompt,
    build_emotional_update_prompt,
)
from backend.services.workflows.utils import clean_llm_output

logger = logging.getLogger(__name__)


def build_initial_relational_state(
    relationships: List[Any],
    entities: List[Any]
) -> str:
    """
    构建初始关系状态描述。

    将角色关系列表转换为可读的文本描述。

    Args:
        relationships: 角色关系列表
        entities: 角色实体列表

    Returns:
        关系状态描述文本，格式如：
        "角色A ↔ 角色B: 关系类型（亲密度）"
    """
    if not relationships:
        return ""

    rel_descriptions = []
    for rel in relationships:
        source = rel.source_character.name if hasattr(rel, 'source_character') and rel.source_character else "?"
        target = rel.target_character.name if hasattr(rel, 'target_character') and rel.target_character else "?"
        rel_type = rel.relation_type if hasattr(rel, 'relation_type') else "未知关系"
        affinity = rel.affinity_score if hasattr(rel, 'affinity_score') else 0

        if affinity <= -50:
            affinity_desc = "敌对"
        elif affinity <= -20:
            affinity_desc = "不信任"
        elif affinity < 20:
            affinity_desc = "中立"
        elif affinity < 50:
            affinity_desc = "友好"
        else:
            affinity_desc = "亲密"

        desc = f"{source} ↔ {target}: {rel_type}（{affinity_desc}）"

        if hasattr(rel, 'interaction_prompt') and rel.interaction_prompt:
            desc += f" - {rel.interaction_prompt}"

        rel_descriptions.append(desc)

    return "\n".join(rel_descriptions)


def merge_relational_delta(current_state: str, delta: str) -> str:
    """
    合并关系状态变更。

    将新的关系变更追加到当前状态，并限制总长度。

    Args:
        current_state: 当前关系状态
        delta: 新发生的关系变更

    Returns:
        合并后的关系状态
    """
    MAX_LEN = 300

    if not delta:
        return current_state

    new_state = f"{current_state}\n[更新]: {delta}" if current_state else delta

    if len(new_state) > MAX_LEN:
        return new_state[-MAX_LEN:]

    return new_state


def extract_fallback_summary(text: str, max_len: int = 40) -> str:
    """
    提取后备摘要。

    当 LLM 调用失败时，使用简单的文本截取作为摘要。

    Args:
        text: 原始文本
        max_len: 最大长度

    Returns:
        截取后的摘要文本
    """
    if len(text) <= max_len:
        return text

    truncated = text[:max_len]
    for punct in ["，", "。", "！", "？", ",", ".", "!"]:
        idx = truncated.rfind(punct)
        if idx > 10:
            return truncated[:idx + 1]

    return truncated + "..."


async def update_dynamic_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
    relational_state_lock: str = "",
    beat_context: Optional[Any] = None,
    book_genre: str = "通用小说",
) -> DynamicStateUpdateResult:
    """
    更新动态状态。

    分析生成的文本片段，更新角色情绪状态和关系状态。

    Args:
        chunk_text: 生成的文本片段
        current_emotional_state: 当前情绪状态
        pov_character: 视角角色
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称
        relational_state_lock: 关系状态锁定
        beat_context: 节拍上下文
        book_genre: 书籍类型

    Returns:
        DynamicStateUpdateResult: 包含新情绪状态、关系变更和摘要
    """
    try:
        system_prompt, user_prompt = build_dynamic_state_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
            relational_state_lock=relational_state_lock,
            beat_context=beat_context,
            book_genre=book_genre,
        )

        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=300,
        )

        result_text = clean_llm_output(response).strip()
        result_json = json.loads(result_text)

        result = DynamicStateUpdateResult(**result_json)
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"[Dynamic State Update] JSON 解析失败: {e}")
        return DynamicStateUpdateResult(
            new_emotional_state=current_emotional_state,
            relational_delta="",
            beat_summary=extract_fallback_summary(chunk_text)
        )
    except Exception as e:
        logger.warning(f"[Dynamic State Update] 状态更新失败: {e}")
        return DynamicStateUpdateResult(
            new_emotional_state=current_emotional_state,
            relational_delta="",
            beat_summary=extract_fallback_summary(chunk_text)
        )


async def update_emotional_state(
    chunk_text: str,
    current_emotional_state: str,
    pov_character: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    """
    更新情绪状态。

    专门用于分析文本片段并更新角色情绪状态。

    Args:
        chunk_text: 生成的文本片段
        current_emotional_state: 当前情绪状态
        pov_character: 视角角色
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称

    Returns:
        更新后的情绪状态文本
    """
    try:
        system_prompt, user_prompt = build_emotional_update_prompt(
            chunk_text=chunk_text,
            previous_emotional_state=current_emotional_state,
            pov_character=pov_character,
        )

        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=200,
        )

        result_text = clean_llm_output(response).strip()
        result_json = json.loads(result_text)

        return result_json.get("emotional_state", current_emotional_state)

    except json.JSONDecodeError as e:
        logger.warning(f"[Emotional Update] JSON 解析失败: {e}")
        return current_emotional_state
    except Exception as e:
        logger.warning(f"[Emotional Update] 情绪更新失败: {e}")
        return current_emotional_state


# 向后兼容别名
_update_dynamic_state = update_dynamic_state
_update_emotional_state = update_emotional_state
_build_initial_relational_state = build_initial_relational_state
_merge_relational_delta = merge_relational_delta
_extract_fallback_summary = extract_fallback_summary

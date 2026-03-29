"""
起草模块辅助工具函数。

职责：提供起草阶段常用的辅助函数，与核心逻辑解耦。

主要功能：
- 文本截取和尾部提取
- Token 数量限制
- 关系状态管理
- Prompt 构建辅助

使用场景：
- workflows/drafting.py: 主起草逻辑调用
"""

from typing import Any, List


def _extract_tail(text: str, max_chars: int = 300) -> str:
    """
    提取文本尾部。

    用于生成 Rolling Prefix（滚动前缀），
    将前一个 Beat 的末尾部分作为下一个 Beat 的上下文。

    Args:
        text: 原始文本
        max_chars: 最大字符数

    Returns:
        尾部文本（不超过 max_chars）
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _clamp_tokens(target_words: int) -> int:
    """
    将目标字数转换为 Token 上限。

    经验公式：1 Token ≈ 1.5-2 中文字符 ≈ 0.75 英文单词
    为安全起见，使用 2.0 比率保守估算。

    Args:
        target_words: 目标字数

    Returns:
        Token 上限
    """
    return int(target_words * 2.0)


def _extract_fallback_summary(text: str, max_len: int = 40) -> str:
    """
    从文本中提取降级摘要。

    当 LLM 未能提供有效摘要时使用，
    通过简单的首尾截取生成近似摘要。

    Args:
        text: 原始文本
        max_len: 最大长度

    Returns:
        摘要文本
    """
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def _build_initial_relational_state(
    relationships: List[Any],
    entities: List[Any]
) -> str:
    """
    构建初始关系状态描述。

    用于为第一个 Beat 提供角色关系上下文，
    包含关系类型和亲密度信息。

    Args:
        relationships: 角色关系列表
        entities: 角色实体列表

    Returns:
        关系状态描述文本
    """
    if not relationships:
        return ""

    entity_map = {e.id: e for e in entities} if entities else {}

    lines = []
    for rel in relationships:
        if not rel.is_public:
            continue

        source = entity_map.get(rel.source_char_id, None)
        target = entity_map.get(rel.target_char_id, None)
        source_name = getattr(source, 'name', 'Unknown') if source else 'Unknown'
        target_name = getattr(target, 'name', 'Unknown') if target else 'Unknown'

        lines.append(
            f"{source_name} 与 {target_name}: {rel.relation_type}"
            + (f" (亲密度: {rel.affinity_score})" if rel.affinity_score else "")
        )

    return "\n".join(lines) if lines else ""


def _merge_relational_delta(current_state: str, delta: str) -> str:
    """
    合并关系状态增量。

    将新生成的关系变化合并到现有状态中，
    用于跨 Beat 的关系演变追踪。

    Args:
        current_state: 当前状态文本
        delta: 增量文本（新变化）

    Returns:
        合并后的状态文本
    """
    if not delta:
        return current_state
    if not current_state:
        return delta
    return f"{current_state}\n{delta}"


def _extract_character_prompts_for_beat(
    beat: dict,
    entities: List[Any],
) -> dict:
    """
    提取 Beat 对应的角色 Prompt 列表。

    Args:
        beat: 节拍数据
        entities: 角色实体列表

    Returns:
        角色名到 Prompt 的映射
    """
    entity_prompts = {}
    entity_map = {e.id: e for e in entities} if entities else {}

    pov_id = beat.get("pov_character_id")
    if pov_id and pov_id in entity_map:
        entity = entity_map[pov_id]
        prompt = getattr(entity, 'dynamic_state', '') or getattr(entity, 'description', '')
        if prompt:
            entity_prompts[pov_id] = prompt

    return entity_prompts

"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

"""
Beat 工具函数模块

职责：提供 Beat 生成过程中常用的工具函数，消除重复代码。

包含：
- 目标字数计算
- Beat ID 生成
- 列表安全访问
- 参数验证
"""

from typing import Any, List, TypeVar, Optional, Dict

T = TypeVar("T")


class BeatDefaults:
    """Beat 生成默认值常量"""
    MIN_WORDS_PER_BEAT = 200
    MAX_LLM_TOKENS = 5200
    MIN_LLM_TOKENS = 1200
    DEFAULT_TEMPERATURE = 0.75
    MAX_RETRY_ATTEMPTS = 3
    ROLLING_PREFIX_MAX_CHARS = 300
    FALLBACK_SUMMARY_MAX_LEN = 40


def get_target_words(beat: Dict[str, Any], word_count: int, total_beats: int) -> int:
    """
    安全获取 Beat 的目标字数。
    
    优先级：
    1. beat["word_count_target"]
    2. beat["target_words"]
    3. 自动计算：max(200, word_count // total_beats)
    
    Args:
        beat: Beat 数据字典
        word_count: 章节总字数
        total_beats: Beat 总数
        
    Returns:
        int: 目标字数，确保 >= 200
    """
    target = beat.get("word_count_target") or beat.get("target_words")
    if isinstance(target, int) and target > 0:
        return target
    return max(BeatDefaults.MIN_WORDS_PER_BEAT, word_count // max(1, total_beats))


def safe_get_beat_id(beat: Dict[str, Any], index: int) -> str:
    """
    安全获取 Beat ID，不存在则生成默认 ID。
    
    Args:
        beat: Beat 数据字典
        index: Beat 索引（从0开始）
        
    Returns:
        str: Beat ID，格式为 beat["beat_id"] 或 "beat-{index+1}"
    """
    return str(beat.get("beat_id", f"beat-{index + 1}"))


def safe_get_from_list(items: List[T], index: int, default: T) -> T:
    """
    安全从列表获取元素，越界返回默认值。
    
    Args:
        items: 列表
        index: 索引
        default: 默认值
        
    Returns:
        T: 列表元素或默认值
    """
    return items[index] if 0 <= index < len(items) else default


def clamp_tokens(target_words: int) -> int:
    """
    根据目标字数计算安全的 LLM token 数量。
    
    计算方式：目标字数 * 2，限制在 [1200, 5200] 范围内
    
    Args:
        target_words: 目标字数
        
    Returns:
        int: 安全的 token 数量
    """
    estimated = int(target_words * 2)
    return max(BeatDefaults.MIN_LLM_TOKENS, min(estimated, BeatDefaults.MAX_LLM_TOKENS))


def extract_tail(text: str, max_chars: int = 300) -> str:
    """
    提取文本尾部用于 Rolling Prefix。
    
    策略：
    1. 优先按段落分割，保留最后几个完整段落
    2. 段落过长则按句子分割
    3. 确保返回的文本不超过 max_chars
    
    Args:
        text: 原文本
        max_chars: 最大字符数，默认 300
        
    Returns:
        str: 文本尾部
    """
    if not text:
        return ""

    if len(text) <= max_chars:
        return text

    # 按段落分割
    paragraphs = text.split("\n\n")
    tail_parts = []
    current_length = 0

    for para in reversed(paragraphs):
        if current_length + len(para) + 2 > max_chars:
            remaining = max_chars - current_length
            if remaining > 50:
                # 按句子分割
                sentences = para.split("。")
                partial = ""
                for sent in reversed(sentences):
                    if len(partial) + len(sent) + 1 <= remaining:
                        partial = sent + "。" + partial if partial else sent + "。"
                    else:
                        break
                if partial:
                    tail_parts.insert(0, partial)
            break
        tail_parts.insert(0, para)
        current_length += len(para) + 2

    result = "\n\n".join(tail_parts)

    # 最终截断保护
    if len(result) > max_chars:
        result = result[-max_chars:]
        first_period = result.find("。")
        if first_period > 0 and first_period < 50:
            result = result[first_period + 1:]

    return result.strip()


def get_pov_profile(pov_character: str, entities: List[Any]) -> str:
    """
    获取 POV 角色的 profile 信息。
    
    Args:
        pov_character: POV 角色名称
        entities: 实体列表
        
    Returns:
        str: 角色 profile，限制 150 字符
    """
    if not pov_character or not entities:
        return ""
        
    for entity in entities:
        char = getattr(entity, 'character', None) or entity
        char_name = getattr(char, 'name', '') or ''
        if char_name and pov_character in char_name:
            raw_profile = getattr(char, 'static_prompt', '') or ''
            return raw_profile[:150] if raw_profile else ''
    return ""


def build_context_summaries(beat_index: int, beats: List[Dict[str, Any]], total_beats: int) -> Dict[str, str]:
    """
    构建 Beat 上下文摘要（前情/后续）。
    
    Args:
        beat_index: 当前 Beat 索引（从1开始）
        beats: 所有 Beats
        total_beats: Beat 总数
        
    Returns:
        Dict[str, str]: {"prev": ..., "next": ...}
    """
    summaries = {}
    if beat_index > 1:
        summaries["prev"] = beats[beat_index - 2].get("summary", "")
    if beat_index < total_beats:
        summaries["next"] = beats[beat_index].get("summary", "")
    return summaries

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
文本洗涤器 —— 确定性正则裁剪层。

职责：
- sanitize_segment：对单段正文做安全正则裁剪（删黑名单词/微操短语），无损语义
- sanitize_rolling_prefix：对下段 prompt 的 rolling_prefix 做风格去毒，防腔调滚动放大

设计原则（对应"正则安全裁剪"策略）：
- 只删"确定性无信息量"的内容：黑名单词、微操短语
- 绝不用正则改句式结构（匀速句式/后置修饰语泛滥这类交给 LLM 洗涤）
- 删除后清理可能产生的多余标点/空格，保证输出仍是通顺中文
- 可逆性：sanitize 是"裁剪"不是"改写"，删掉的都是冗余

警示：中文正则裁剪有误伤风险。本模块只处理两类高确定性目标：
1. 整词替换（冷冽→删除，因为是孤立填充词）
2. 微操短语删除（指尖颤了颤→删除，无情节信息）
绝不触碰比喻主干、句子结构。

业务场景：
- segment_writer 段后处理：未触发洗涤阈值时调用 sanitize_segment 轻裁
- segment_writer 下段 prompt 前：sanitize_rolling_prefix 去毒前段末500字
"""

import re
from typing import List

from backend.services.nlg.anti_ai_rules import (
    AntiAIBanList,
    DEFAULT_BAN_LIST,
)


# 预编译正则
def _compile_all(patterns) -> List[re.Pattern]:
    return [re.compile(p) for p in patterns]


_BANNED_WORD_PATTERNS = None  # 惰性构建（词表可能很长，构建一次复用）
_MICRO_ACTION_REGEX = _compile_all(DEFAULT_BAN_LIST.banned_regexes)


def _get_banned_word_patterns(ban_list: AntiAIBanList) -> List[re.Pattern]:
    """惰性构建"整词匹配"正则。中文无词边界，用非贪婪上下文避免误删子串。"""
    global _BANNED_WORD_PATTERNS
    if _BANNED_WORD_PATTERNS is None or ban_list is not DEFAULT_BAN_LIST:
        # 整词直接 re.escape；中文里这些词本身不会是更长词的子串（已人工筛选）
        return [re.compile(re.escape(w)) for w in ban_list.banned_words if w]
    return _BANNED_WORD_PATTERNS


# 清理裁剪后产生的多余标点
# 1. 连续逗号/顿号 → 单个
_MULTI_COMMA = re.compile(r"[，、]{2,}")
# 2. 句号/逗号前紧跟空格
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([，。！？、；])")
# 3. 连续空格
_MULTI_SPACE = re.compile(r"[^\S\n]{2,}")
# 4. 连续两个以上句末标点（删微操短语后可能留下"。。"）
_MULTI_END_PUNCT = re.compile(r"([。！？]){2,}")


def _cleanup_punctuation(text: str) -> str:
    """清理裁剪后产生的标点/空格冗余，保证中文通顺。"""
    text = _MULTI_COMMA.sub(lambda m: m.group(0)[0], text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = _MULTI_END_PUNCT.sub(lambda m: m.group(1), text)
    return text


def sanitize_segment(
    text: str,
    ban_list: AntiAIBanList = DEFAULT_BAN_LIST,
) -> str:
    """对单段正文做安全正则裁剪。

    只删除确定性无信息量的内容（黑名单词、微操短语），不改句子结构。
    裁剪后清理标点冗余。

    Args:
        text: 单段正文
        ban_list: 禁令清单

    Returns:
        裁剪后的正文（语义无损）

    警示：本函数只做"减法"。若段落全由黑名单词组成（极少见），
    返回空串，由调用方决定是否触发洗涤 Pass。
    """
    if not text or not text.strip():
        return text

    result = text

    # 1. 删微操句式正则（嘴角上扬/瞳孔收缩等整处删除）
    for pat in _MICRO_ACTION_REGEX:
        result = pat.sub("", result)

    # 2. 删微操短语（词表子串）
    for w in ban_list.banned_micro_actions:
        if w:
            result = result.replace(w, "")

    # 3. 删黑名单填充词
    for pat in _get_banned_word_patterns(ban_list):
        result = pat.sub("", result)

    # 4. 清理标点冗余
    result = _cleanup_punctuation(result)

    return result


def sanitize_rolling_prefix(
    rolling_prefix: str,
    ban_list: AntiAIBanList = DEFAULT_BAN_LIST,
    max_chars: int = 500,
) -> str:
    """对下段 prompt 的 rolling_prefix 做风格去毒。

    核心目的：防止上一段的 AI 腔调通过 rolling context 被后续段落无限放大
    （反模式 #4：上下文风格毒化）。

    比 sanitize_segment 更激进一点：除了删黑名单/微操，还压缩连续的比喻意象
    和后置修饰语（保留首次出现，删重复），因为 rolling_prefix 只是"衔接线索"
    不是"正文本身"，去毒后不影响成品质量。

    Args:
        rolling_prefix: 前段末尾文本（通常已截到 500 字）
        ban_list: 禁令清单
        max_chars: 最大保留字符数（超出截断，保证 prompt 体积）

    Returns:
        去毒后的 rolling_prefix

    使用方式（segment_writer 下段 prompt 前）：
        clean_prefix = sanitize_rolling_prefix(rolling_prefix[-500:])
    """
    if not rolling_prefix or not rolling_prefix.strip():
        return rolling_prefix

    # 1. 基础裁剪（复用段级裁剪逻辑）
    result = sanitize_segment(rolling_prefix, ban_list)

    # 2. 比喻意象去重：同一套路比喻在 prefix 里只保留首次
    seen_metaphors: set = set()
    for pat in _compile_all(ban_list.metaphor_regexes):
        matches = list(pat.finditer(result))
        for m in matches:
            hit = m.group(0)
            if hit in seen_metaphors:
                result = result.replace(hit, "", 1)
            else:
                seen_metaphors.add(hit)

    # 3. 后置修饰语去重（"眼中带着一抹..."同类只留首次）
    seen_trailing: set = set()
    for pat in _compile_all(ban_list.trailing_modifier_regexes):
        matches = list(pat.finditer(result))
        for m in matches:
            hit = m.group(0)
            if hit in seen_trailing:
                result = result.replace(hit, "", 1)
            else:
                seen_trailing.add(hit)

    # 4. 清理 + 截断
    result = _cleanup_punctuation(result)
    if len(result) > max_chars:
        result = result[-max_chars:]

    return result

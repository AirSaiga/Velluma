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
内容安全净化模块。

职责：防止用户可控内容注入 Prompt，保护 LLM 输出格式和系统安全。

主要功能：
- sanitize_user_content: 通用内容净化
- sanitize_json_field: JSON 字段净化
- sanitize_markdown: Markdown 内容净化

安全考虑：
- 移除可能干扰 JSON 解析的标记
- 移除可能绕过系统提示的逃逸序列
- 长度限制防止 Token 溢出
"""

import re
from typing import Optional


def sanitize_user_content(text: Optional[str], max_length: int = 2000) -> str:
    """
    净化用户可控内容，防止 Prompt 注入。

    处理策略：
    1. 移除 JSON/Markdown 代码块标记
    2. 移除反引号和多余空白
    3. 长度限制防止 Token 溢出
    4. 移除可疑的 Prompt 逃逸序列

    Args:
        text: 原始文本
        max_length: 最大长度限制

    Returns:
        净化后的文本
    """
    if not text:
        return ""

    text = str(text)

    # 移除代码块标记 - 防止 Prompt 逃逸
    text = re.sub(r'```[a-z]*\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'`', '', text)

    # 移除可能的 Prompt 注入序列
    injection_patterns = [
        r'system\s*:\s*',  # 角色扮演逃逸
        r'you\s+are\s+',   # 身份覆盖
        r'ignore\s+(?:all\s+)?previous',  # 忽略指令
        r'forget\s+(?:everything\s+)?',   # 忘记指令
        r'<\|(?:system|user|assistant)\|>',  # 特殊分隔符
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # 移除多余空白但保留换行结构
    lines = [line.strip() for line in text.split('\n')]
    text = '\n'.join(line for line in lines if line)

    # 长度限制
    if len(text) > max_length:
        text = text[:max_length] + "..."

    return text


def sanitize_json_field(value: str, field_name: str = "field", max_length: int = 1500) -> str:
    """
    净化将插入 JSON 的字段。

    处理策略：
    1. 转义特殊字符（JSON 安全）
    2. 移除换行符（保持 JSON 结构）
    3. 长度限制

    Args:
        value: 原始值
        field_name: 字段名（用于日志）
        max_length: 最大长度

    Returns:
        JSON 安全的字符串
    """
    if not value:
        return ""

    # JSON 标准转义
    value = value.replace('\\', '\\\\')
    value = value.replace('"', '\\"')
    value = value.replace('\n', ' ')
    value = value.replace('\r', ' ')
    value = value.replace('\t', ' ')
    value = value.replace('\x00', '')

    # 移除可能干扰 JSON 的字符
    value = re.sub(r'[\x01-\x1F\x7F]', '', value)

    # 长度限制
    if len(value) > max_length:
        value = value[:max_length] + "..."

    return value


def sanitize_markdown(text: Optional[str], max_length: int = 3000) -> str:
    """
    净化 Markdown 内容，保留基本格式但防止注入。

    处理策略：
    1. 移除可疑的 HTML 标签
    2. 限制标题层级
    3. 长度限制

    Args:
        text: 原始 Markdown 文本
        max_length: 最大长度

    Returns:
        净化后的 Markdown
    """
    if not text:
        return ""

    text = str(text)

    # 移除可疑的 HTML 标签
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)

    # 限制标题层级 (最多 H3)
    text = re.sub(r'^#{4,}\s+', '### ', text, flags=re.MULTILINE)

    # 移除可疑的链接格式
    text = re.sub(r'\[([^\]]*)\]\([^\)]*javascript:[^\)]*\)', r'\1', text, flags=re.IGNORECASE)

    # 移除多余空白
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 长度限制
    if len(text) > max_length:
        text = text[:max_length] + "\n\n[内容已截断]"

    return text


def sanitize_prompt_variable(name: str, value: Optional[str], max_length: int = 2000) -> str:
    """
    净化 Prompt 变量值，根据变量类型选择合适的净化方法。

    Args:
        name: 变量名（用于判断类型）
        value: 变量值
        max_length: 最大长度

    Returns:
        净化后的值
    """
    if value is None:
        return ""

    # 根据变量名选择净化策略
    sensitive_fields = {'password', 'secret', 'key', 'token', 'credential'}
    json_fields = {'worldview_settings', 'metadata', 'config', 'settings', 'schema'}
    markdown_fields = {'outline', 'description', 'summary', 'content', 'text'}

    name_lower = name.lower()

    if any(s in name_lower for s in sensitive_fields):
        # 敏感字段：完全净化
        return "[已设置]"

    if any(j in name_lower for j in json_fields):
        # JSON 字段
        return sanitize_json_field(value, name, max_length)

    if any(m in name_lower for m in markdown_fields):
        # Markdown 字段
        return sanitize_markdown(value, max_length)

    # 默认通用净化
    return sanitize_user_content(value, max_length)

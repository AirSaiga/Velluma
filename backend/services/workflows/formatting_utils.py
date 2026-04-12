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
文本格式化工具模块 - V3.0

职责：基于正则表达式实现规则化的文本格式化，替代 LLM 格式化。

V3.0 变更：废弃 LLM 格式化，改用纯代码规则处理，降低成本和延迟。

规则:
1. 统一中英文标点（冒号、引号替换为中文全角）
2. 合并 3 个以上连续换行为 2 个
3. 清除段首多余空格/缩进

使用示例:
    from backend.services.workflows.formatting_utils import rule_based_formatting
    formatted_text = rule_based_formatting(raw_text)
"""

import re


def rule_based_formatting(text: str) -> str:
    """
    基于规则的文本格式化函数。
    
    V3.0 主入口函数，替代 LLM 格式化。
    
    Args:
        text: 原始文本
    
    Returns:
        str: 格式化后的文本
    """
    if not text or not text.strip():
        return ""
    
    # 步骤 1: 统一中英文标点
    text = _normalize_punctuation(text)
    
    # 步骤 2: 合并 3 个以上连续换行为 2 个
    text = _merge_newlines(text)
    
    # 步骤 3: 清除段首多余空格/缩进
    text = _remove_leading_spaces(text)

    # 步骤 4: 智能分段
    text = format_paragraphs(text)
    
    return text.strip()


def _normalize_punctuation(text: str) -> str:
    """
    统一中英文标点符号为中文全角。
    
    转换规则:
    - 英文冒号 : -> 中文冒号 ：
    - 英文双引号 "xxx" -> 中文双引号 "xxx"
    - 英文单引号 'xxx' -> 中文单引号 'xxx'
    - 英文逗号 , -> 中文逗号 ，
    - 英文句号 . -> 中文句号 。
    - 英文感叹号 ! -> 中文感叹号 ！
    - 英文问号 ? -> 中文问号 ？
    - 英文括号 () -> 中文括号 （）
    - 英文方括号 [] -> 中文方括号 【】
    """
    # 保留 URL 中的冒号，只转换文本中的冒号
    # 使用负向回顾后发 (?<!...) 排除 http/https 后的冒号
    text = re.sub(r'(?<!http)(?<!https)(?<!\w):\s*', '：', text)
    
    # 引号替换：英文引号 -> 中文引号
    # 处理成对的英文双引号
    text = re.sub(r'"([^"]*)"', r'"\1"', text)
    # 处理成对的英文单引号
    text = re.sub(r"'([^']*)'", r'\'\1\'', text)
    
    # 处理省略号标准化 (需要在替换点之前进行)
    text = re.sub(r'\.{3,}', '……', text)
    text = re.sub(r'…+', '……', text)
    
    # 其他常用标点替换
    # 保护数字中的小数点和逗号（例如 3.14, 1,000）
    text = re.sub(r'(?<=\d),(?=\d)', '\x00', text)
    text = re.sub(r'(?<=\d)\.(?=\d)', '\x01', text)
    
    text = text.replace(',', '，')
    text = text.replace('.', '。')
    text = text.replace('!', '！')
    text = text.replace('?', '？')
    text = text.replace('(', '（')
    text = text.replace(')', '）')
    text = text.replace('[', '【')
    text = text.replace(']', '】')
    
    text = text.replace('\x00', ',')
    text = text.replace('\x01', '.')
    
    # 处理连续标点：多个相同标点合并为一个
    text = re.sub(r'，+', '，', text)
    text = re.sub(r'。+', '。', text)
    text = re.sub(r'！+', '！', text)
    text = re.sub(r'？+', '？', text)
    
    return text


def _merge_newlines(text: str) -> str:
    """
    合并 3 个以上连续换行为 2 个。
    
    保持段落间适当的空行，同时清理过多的空行。
    """
    # 3个或更多换行 -> 2个换行（即一个空行）
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def _remove_leading_spaces(text: str) -> str:
    """
    清除段首的多余空格/缩进。
    
    移除每行开头的空格和制表符，保持段落格式整洁。
    """
    lines = text.split('\n')
    cleaned_lines = [line.lstrip() for line in lines]
    return '\n'.join(cleaned_lines)


def normalize_quotes_smart(text: str) -> str:
    """
    智能处理引号嵌套。
    
    将外层双引号、内层单引号的结构规范化。
    例如: "他说: '你好'" -> "他说：'你好'"
    
    Args:
        text: 包含引号的文本
    
    Returns:
        str: 规范化后的文本
    """
    # 首先标准化外层双引号
    text = re.sub(r'"([^"]*)"', r'"\1"', text)
    
    # 然后处理内部的单引号
    # 使用递归或循环处理嵌套
    for _ in range(3):  # 最多处理3层嵌套
        new_text = re.sub(r'"([^"]*)\'([^\']*)\'([^"]*)"', r'"\1\'\2\'\3"', text)
        if new_text == text:
            break
        text = new_text
    
    return text


def format_paragraphs(text: str, max_length: int = 500) -> str:
    """
    智能分段：将超长段落拆分为适当长度的段落。
    
    V3.0 扩展功能（可选使用）。
    
    Args:
        text: 原始文本
        max_length: 段落最大长度（字符数）
    
    Returns:
        str: 分段后的文本
    """
    if not text:
        return ""
    
    paragraphs = text.split('\n\n')
    formatted_paragraphs = []
    
    for para in paragraphs:
        if len(para) > max_length:
            # 超长段落需要拆分
            sentences = re.split(r'([。！？])', para)
            current_chunk = ""
            chunks = []
            
            for i in range(0, len(sentences), 2):
                if i == len(sentences) - 1:
                    # 最后一个片段，没有标点符号
                    sentence = sentences[i]
                else:
                    sentence = sentences[i] + sentences[i + 1]
                
                if not sentence:
                    continue
                    
                if len(current_chunk) + len(sentence) > max_length and current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = sentence
                else:
                    current_chunk += sentence
            
            if current_chunk:
                chunks.append(current_chunk)
            
            formatted_paragraphs.extend(chunks)
        else:
            formatted_paragraphs.append(para)
    
    return '\n\n'.join(formatted_paragraphs)

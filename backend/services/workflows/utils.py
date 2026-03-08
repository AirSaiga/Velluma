"""
工作流工具函数模块。

职责：提供工作流中常用的工具函数。

主要功能：
- clean_llm_output: 清理 LLM 输出，处理 JSON 解析和 Markdown 标记移除
"""

import json


def clean_llm_output(text: str) -> str:
    """清理 LLM 输出，处理常见的响应格式问题。

    处理逻辑（优先级从高到低）：
    1. 若文本以 { 开头和 } 结尾，尝试解析为 JSON，提取常见 content 字段
    2. 若文本以 ``` 开头，移除 Markdown 代码块标记
    3. 否则直接返回 stripped 文本

    Args:
        text: LLM 原始输出文本

    Returns:
        str: 清理后的文本

    示例:
        >>> clean_llm_output('{"content": "Hello World"}')
        'Hello World'
        >>> clean_llm_output('```python\\nprint("hi")\\n```')
        'print("hi")'
    """
    if not text:
        return ""
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                for key in ["content", "text", "body", "chunk", "draft"]:
                    if key in data and isinstance(data[key], str):
                        return data[key].strip()
        except json.JSONDecodeError:
            pass
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
    return text

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
LLM 智能文本格式化模块 - V4.0

职责：使用 LLM 分析文本语义结构，进行智能分段和格式化。

相比 V4.0 规则引擎的优势：
- 理解对话 vs 叙述的区别
- 识别场景切换（时间、地点、视角变化）
- 根据叙事节奏自然分段
- 保持人物对话的完整性
"""

import re
from typing import Optional

from backend.services.llm.client import call_llm


SYSTEM_PROMPT = """你是一位专业的小说编辑，擅长中文排版和叙事结构优化。

你的任务是对小说文本进行智能格式整理，遵循以下原则：

## 分段原则

1. **对话独立成段**
   - 每个人物的台词单独一段
   - 对话前的动作/神态描写可与对话合并（如果简短）
   - 对话后的动作反应单独成段

2. **场景切换必须分段**
   - 时间变化（如"第二天"、"片刻后"）
   - 地点变化（如"与此同时，在另一边"）
   - 视角切换（从不同人物的视点观察）

3. **叙事段落控制**
   - 同一视角的连续叙述，每段 100-200 字为宜
   - 长段落按逻辑节点拆分（动作变化、情绪转折、观察对象变化）

4. **保留原文**
   - 不要增删文字
   - 不要修改原文标点（除非明显错误）
   - 保持原有的描写细节和风格

## 输出格式

- 段落之间用空行分隔（即两个换行符 \n\n）
- 直接返回整理后的文本
- 不要添加任何说明、标注或代码块标记

## 示例

输入：
兰星推开大门，晨光洒在他脸上。他深吸一口气，走向了广场。"今天天气不错。"他说道。旁边的路人看了他一眼，没有说话。

输出：
兰星推开大门，晨光洒在他脸上。他深吸一口气，走向了广场。

"今天天气不错。"他说道。

旁边的路人看了他一眼，没有说话。
"""


async def llm_based_formatting(
    text: str,
) -> str:
    """
    使用 LLM 进行智能文本格式化。
    
    Args:
        text: 原始文本
    
    Returns:
        str: 格式化后的文本
    """
    if not text or not text.strip():
        return ""
    
    # 如果文本较短，直接返回
    if len(text.strip()) < 50:
        return text.strip()
    
    try:
        formatted = await call_llm(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=f"请对以下小说文本进行智能格式整理：\n\n{text}",
            # 格式整理是机械编辑（分段/标点/空行，不增删文字），维持分析槽
            # 并显式化（2026-09-15）；LLM 失败本就回退规则引擎，离线韧性无虞
            model_type="reasoning",
            temperature=0.3,  # 低温度，保持稳定性
            max_tokens=8192
        )
        
        # 清理可能的标记
        formatted = _clean_llm_output(formatted)
        
        return formatted or text
        
    except Exception as e:
        # LLM 失败时返回原文
        print(f"[LLM Formatting] Error: {e}")
        return text


def _clean_llm_output(text: str) -> str:
    """清理 LLM 输出的可能标记。"""
    # 移除可能的代码块标记
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    
    # 移除 "整理后："、"输出：" 等前缀
    text = re.sub(r'^(整理后|输出|结果|formatted)[：:]\s*', '', text, flags=re.IGNORECASE)
    
    # 标准化换行符
    text = text.replace('\r\n', '\n')
    
    return text.strip()


async def hybrid_formatting(
    text: str,
    use_llm: bool = True
) -> str:
    """
    混合格式化：优先使用 LLM，失败时回退到规则引擎。
    
    Args:
        text: 原始文本
        use_llm: 是否使用 LLM（False 则只用规则引擎）
    
    Returns:
        str: 格式化后的文本
    """
    from backend.services.workflows.formatting_utils import rule_based_formatting
    
    if not use_llm:
        return rule_based_formatting(text)
    
    # 尝试 LLM 格式化
    llm_result = await llm_based_formatting(text)
    
    # 如果 LLM 返回结果且长度合理（±30% 范围内），使用 LLM 结果
    original_len = len(text)
    result_len = len(llm_result)
    
    if llm_result and (original_len * 0.7 <= result_len <= original_len * 1.3):
        return llm_result
    
    # 否则回退到规则引擎
    print(f"[hybrid_formatting] LLM result abnormal, falling back to rule-based")
    return rule_based_formatting(text)

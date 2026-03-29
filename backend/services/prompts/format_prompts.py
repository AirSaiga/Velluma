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

def build_formatting_prompt(text: str) -> tuple[str, str]:
    """
    构建格式化 Agent 的提示词，负责对生成的文本进行段落划分。
    
    任务：
    - 根据上下文逻辑，将输入的文本重新进行段落划分，使其阅读体验更加流畅。
    - 严格保持原文内容不变，仅增加换行符。
    - 直接输出处理后的文本。
    """
    system_prompt = (
        "你是一个专业的小说排版编辑。你的任务是根据上下文逻辑，将输入的文本重新进行段落划分，"
        "使其阅读体验更加流畅。\n"
        "规则：\n"
        "1. 严格保持原文内容不变，不得修改、增加或删除任何文字和标点。\n"
        "2. 仅通过插入换行符来调整段落结构。\n"
        "3. 遇到对话、场景转换、动作描写与心理活动切换时，应当换行。\n"
        "4. 请直接输出处理后的文本，不要包含任何解释或Markdown标记。"
    )
    user_prompt = f"请对以下文本进行段落划分：\n\n{text}"
    return system_prompt, user_prompt

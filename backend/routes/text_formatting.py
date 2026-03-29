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
文本格式整理路由模块 - V3.0

职责：提供文本格式整理 API，用于优化 AI 生成内容的段落结构、标点符号、空行等。

V3.0 变更：废弃 LLM 格式化，改用规则引擎，显著降低成本和延迟。

业务场景：
- AI 生成内容格式混乱时的自动整理
- 用户手动输入后的格式规范化
- 导出前的最终排版
"""

from fastapi import APIRouter, HTTPException
from backend.schemas import FormatTextRequest
from backend.services.workflows.formatting_utils import rule_based_formatting

router = APIRouter(prefix="/api", tags=["text_formatting"])


@router.post("/format_text")
async def format_text(request: FormatTextRequest):
    """整理文本格式（分段、标点、空格等）- V3.0 规则引擎版。

    V3.0 更新：改用基于正则的规则引擎替代 LLM，降低成本。

    业务目的：将原始文本整理为符合阅读习惯的格式，包括：
    - 标点规范化（中英文标点统一为中文全角）
    - 空行合并（3个以上连续换行合并为2个）
    - 清除段首多余空格

    处理规则：
    1. 冒号: -> 中文冒号：
    2. 引号 "xxx" -> "xxx"（中文双引号）
    3. 逗号 , -> 中文逗号 ，
    4. 句号 . -> 中文句号 。
    5. 括号 () -> （）
    6. 方括号 [] -> 【】
    7. 3个及以上换行 -> 2个换行
    8. 清除每行开头的空格

    参数来源：
    - request.text: 待整理的原始文本

    数据流：
    1. 接收原始文本
    2. 应用规则引擎进行格式整理
    3. 返回整理后的文本

    副作用：
    - 不修改数据库，仅返回处理结果
    - 无需 LLM 调用，无额外费用

    边界处理：
    - 空文本直接返回空字符串
    """
    if not request.text.strip():
        return {"formatted_text": ""}
    
    # V3.0: 使用规则化格式化替代 LLM
    formatted_text = rule_based_formatting(request.text)
    
    return {"formatted_text": formatted_text}

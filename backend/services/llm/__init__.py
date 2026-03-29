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
LLM 调用模块 - 统一导出入口。

职责：
- 统一导出 LLM 调用相关函数
- 提供文本生成、嵌入、代理配置等功能

子模块：
- client.py: LLM 调用封装
- embedding.py: 文本嵌入
- proxy.py: 代理配置

主要功能：
- LLM 聊天补全
- 流式响应生成
- 摘要生成
- 文本嵌入
- 代理配置

依赖项：
- OpenAI SDK / DashScope SDK
- httpx: HTTP 客户端
"""

from .client import (
    call_llm,
    generate_stream_response,
    generate_summary,
    format_text_with_llm,
    optimize_selection_with_llm,
)
from .embedding import get_embedding
from .proxy import (
    get_proxy_config,
    set_proxy_config,
    get_active_proxy,
)

__all__ = [
    "call_llm",
    "generate_stream_response",
    "generate_summary",
    "format_text_with_llm",
    "optimize_selection_with_llm",
    "get_embedding",
    "get_proxy_config",
    "set_proxy_config",
    "get_active_proxy",
]

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
文本向量化模块 - 文本嵌入生成服务。

职责：
- 提供文本到向量 embedding 的转换能力
- 支持 DashScope Embedding API
- 为 RAG 检索系统提供向量表示

业务场景：
- RAG 记忆存储前的向量化
- 相似度检索时的查询向量生成
- 语义搜索的向量编码

主要功能：
- 单文本/批量文本向量化
- 1536 维向量输出（适配 pgvector）
- 异常处理和降级策略

依赖项：
- dashscope: 阿里云 DashScope SDK
- 需设置 DASHSCOPE_API_KEY 环境变量

使用方式：
    embedding = await get_embedding("需要向量化的文本")
"""

import logging
import os
from typing import Optional


logger = logging.getLogger(__name__)


async def get_embedding(
    text: str,
    api_key: str = None,
    base_url: Optional[str] = None,
    model: str = "text-embedding-v2",
    timeout: int = 60,
) -> list:
    import dashscope
    from dashscope import TextEmbedding
    from dotenv import load_dotenv

    load_dotenv()

    dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY")
    if not dashscope_api_key:
        logger.warning("[Embedding] DASHSCOPE_API_KEY 未设置")
        return []

    dashscope.api_key = dashscope_api_key

    try:
        # text-embedding-v2 默认输出 1536 维，适配数据库的 Vector(1536)
        resp = TextEmbedding.call(
            model=model,
            input=text,
        )

        if resp.status_code == 200:
            embedding = resp.output["embeddings"][0]["embedding"]
            logger.info(f"[Embedding] 向量维度: {len(embedding)}")
            return embedding
        else:
            logger.error(
                f"[Embedding] 调用失败: "
                f"code={resp.status_code}, "
                f"msg={resp.message if hasattr(resp, 'message') else resp}"
            )
            return []

    except Exception as e:
        logger.error(f"[Embedding] 异常: {e}")
        return []

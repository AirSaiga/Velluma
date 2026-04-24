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
- 可配置维度向量输出（通过 model_config.json 配置）
- 维度验证，确保与数据库 schema 一致
- 异常处理和降级策略

依赖项：
- dashscope: 阿里云 DashScope SDK
- 需设置 DASHSCOPE_API_KEY 环境变量（或由 model_config.json 提供）

使用方式：
    embedding = await get_embedding("需要向量化的文本")
"""

import logging
from typing import Optional

from backend.core.model_config import get_embedding_config, get_embedding_dimensions

logger = logging.getLogger(__name__)


async def get_embedding(
    text: str,
    model: Optional[str] = None,
    timeout: int = 60,
) -> list:
    import dashscope
    from dashscope import TextEmbedding

    emb_config = get_embedding_config()
    dashscope_api_key = emb_config.get("api_key", "")
    emb_model = model or emb_config.get("model", "text-embedding-v2")
    expected_dimensions = get_embedding_dimensions()

    if not dashscope_api_key:
        logger.warning("[Embedding] API Key 未设置，请在 model_config.json 中配置 embedding.api_key")
        return []

    dashscope.api_key = dashscope_api_key

    try:
        # 构建调用参数
        call_params = {
            "model": emb_model,
            "input": text,
        }
        
        # text-embedding-v3/v4 支持 dimensions 参数，v2 不支持
        if emb_model in ("text-embedding-v3", "text-embedding-v4"):
            call_params["dimensions"] = expected_dimensions

        resp = TextEmbedding.call(**call_params)

        if resp.status_code == 200:
            embedding = resp.output["embeddings"][0]["embedding"]
            actual_dimensions = len(embedding)
            
            # 验证维度是否匹配数据库配置
            if actual_dimensions != expected_dimensions:
                logger.error(
                    f"[Embedding] 维度不匹配: 模型输出 {actual_dimensions} 维, "
                    f"数据库配置 {expected_dimensions} 维。"
                    f"请检查 model_config.json 中的 embedding.dimensions 配置"
                )
                return []
            
            logger.info(f"[Embedding] 向量维度: {actual_dimensions}, 模型: {emb_model}")
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

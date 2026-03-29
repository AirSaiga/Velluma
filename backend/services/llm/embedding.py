import logging
import os
from typing import Optional


logger = logging.getLogger(__name__)


async def get_embedding(
    text: str,
    api_key: str = None,
    base_url: Optional[str] = None,
    model: str = "text-embedding-v3",
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
        resp = TextEmbedding.call(
            model=model,
            input=text,
            dimension=1536,
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

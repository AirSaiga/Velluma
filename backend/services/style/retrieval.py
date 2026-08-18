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
作者样本检索（文风模块重构 S2 执行层 E1，docs/style-module-redesign.md §4）。

职责：生成时按当前写作上下文取 1-2 条作者样本做 few-shot 范例注入——
「一段范例胜过十句形容」，这是文风执行层里质量杠杆最大的注入方式。

两级检索（与 RAG「默认流打底 + 向量增强」同模式）：
1. 向量流（embedding 已配置时）：查询文本向量化 → AuthorSampleRepository
   .search_by_style 余弦检索 top-k（`samples/search` 端点同款，休眠设施接活）
2. 兜底流（未配置/向量化失败/无命中）：按 created_at 新近优先取 k 条
   （list_by_book 即新→旧序）——文风会进化，近期的字更能代表现在的作者

红线：任何失败降级为空列表，调用方 prompt 零变化（不阻塞生成）。
预算：k≤2 × max_chars（默认 1200）≈ 单次注入 ≤2400 字（设计稿 §4 E1）。
"""

import logging
from typing import Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories import AuthorSampleRepository
from backend.services.llm.embedding import get_embedding, is_embedding_configured

logger = logging.getLogger(__name__)


def truncate_sample(text: str, max_chars: int) -> str:
    """样本截断至句界（找不到句末标点则原样返回窗口）。"""
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    cut = window.rfind("。")
    if cut < max_chars * 0.5:
        cut = max(window.rfind("！"), window.rfind("？"), window.rfind("…"))
    return window[: cut + 1] if cut >= max_chars * 0.5 else window


def order_samples_for_fallback(samples: List[Any]) -> List[Any]:
    """兜底流排序（完整落地批）：收藏优先 → 近期（era != early）按新近 → 早期。

    文风会进化（近期的字更代表现在的作者），收藏是作者认证的最佳示范；
    早期样本垫底只作补位。向量流不重排（相似度即目的）。
    """
    def rank(s: Any) -> tuple:
        favorite = 0 if getattr(s, "favorite", False) else 1
        era = 0 if (getattr(s, "era", "recent") or "recent") != "early" else 1
        return (favorite, era)

    return sorted(samples, key=rank)


async def retrieve_author_samples(
    db: AsyncSession,
    book_id: str,
    query_text: str = "",
    k: int = 2,
    max_chars: int = 1200,
    scene_type: Optional[str] = None,
) -> List[str]:
    """检索 few-shot 作者样本（返回截断后的样本原文列表）。

    Args:
        db: 异步 DB session
        book_id: 书籍 ID
        query_text: 检索锚文本（当前写作上下文；空则直接走兜底流）
        k: 返回条数上限（默认 2，设计稿预算）
        max_chars: 每条截断上限
        scene_type: 可选场景过滤（对话/动作/抒情/悬念；None 不过滤）

    Returns:
        List[str]：样本原文（已截断）。无样本/全失败 → []
    """
    if not book_id:
        return []
    repo = AuthorSampleRepository(db)

    samples = None
    # ---- 向量流（专业级，embedding 已配置时优先）----
    if query_text and query_text.strip() and is_embedding_configured():
        try:
            query_embedding = await get_embedding(query_text)
            if query_embedding:
                hits = await repo.search_by_style(
                    embedding=query_embedding,
                    book_id=book_id,
                    scene_type=scene_type,
                    limit=k,
                )
                samples = [s for s, _distance in hits]
        except Exception as e:
            logger.info(f"[StyleRetrieval] 向量检索降级（走新近兜底）: {e}")
            samples = None

    # ---- 兜底流：收藏优先 → 近期优先 ----
    if samples is None:
        try:
            samples = order_samples_for_fallback(
                (await repo.list_by_book(book_id, scene_type=scene_type))[: max(k * 3, k)]
            )[:k]
        except Exception as e:
            logger.warning(f"[StyleRetrieval] 样本加载失败（返回空）: {e}")
            return []

    return [truncate_sample(s.content or "", max_chars) for s in samples if (s.content or "").strip()]

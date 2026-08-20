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

C2 场景匹配（docs/foundation-hardening.md §5.2）：scene_hint（v1 仅
"dialogue"）生效时同型样本获软加成——向量流得分 +0.1（距离 -0.1 重排）、
兜底流同型在同档内排前。**软加成不等于 scene_type 硬过滤**：异型样本仍在
候选池内（宁缺排序变化，不做排他筛选）。hint 为 None/"general" 时行为与
现状逐一致（零变化契约）。

红线：任何失败降级为空列表，调用方 prompt 零变化（不阻塞生成）。
预算：k≤2 × max_chars（默认 1200）≈ 单次注入 ≤2400 字（设计稿 §4 E1）。
"""

import logging
from typing import Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories import AuthorSampleRepository
from backend.services.llm.embedding import get_embedding, is_embedding_configured

# A3a 截断常量收敛（docs/foundation-hardening.md §4.1）：样本剂量改引 budget 表
from backend.services.context.budget import AUTHOR_SAMPLE_MAX_CHARS, AUTHOR_SAMPLES_MAX_K
# C2 场景匹配（docs/foundation-hardening.md §5.2）：dialogue hint 下同型样本加成
from backend.services.style.scene_hint import SCENE_GENERAL

logger = logging.getLogger(__name__)

# ============================================================
# C2 场景加成口径
# ============================================================
# 加成量级：向量流对 scene_type 匹配 hint 的样本「得分 +0.1」——检索返回的是
# cosine_distance（升序，越小越相似），得分 +0.1 等价于距离 -0.1 后重排。
SCENE_HINT_BONUS = 0.1
# hint 生效时向量流超额取候选（加成要在更大候选池上重排才有意义——只对 SQL
# top-k 重排，k 名外的同型样本永远吃不到加成）。k=2 → 取 10 条，量级无害。
_SCENE_HINT_OVERFETCH_FACTOR = 5


def scene_hint_active(scene_hint: Optional[str]) -> bool:
    """hint 是否触发加成——非空且非 "general" 即生效（v1 判定器只产
    dialogue，他档语义天然正确，v2 扩细分时直接可用）。

    None / "" / "general" 一律不激活：对检索行为而言 general 档 =
    「无 hint」，与现状逐一致（零变化契约的干净口径）。
    """
    return bool(scene_hint) and scene_hint != SCENE_GENERAL


def _scene_match(sample: Any, scene_hint: Optional[str]) -> bool:
    """样本 scene_type 是否命中生效中的 hint（缺属性/异型 → 不命中，不炸）。"""
    return scene_hint_active(scene_hint) and getattr(sample, "scene_type", None) == scene_hint


def truncate_sample(text: str, max_chars: int) -> str:
    """样本截断至句界（找不到句末标点则原样返回窗口）。"""
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    cut = window.rfind("。")
    if cut < max_chars * 0.5:
        cut = max(window.rfind("！"), window.rfind("？"), window.rfind("…"))
    return window[: cut + 1] if cut >= max_chars * 0.5 else window


def order_samples_for_fallback(samples: List[Any], scene_hint: Optional[str] = None) -> List[Any]:
    """兜底流排序（完整落地批）：收藏优先 → 近期（era != early）按新近 → 早期。

    文风会进化（近期的字更代表现在的作者），收藏是作者认证的最佳示范；
    早期样本垫底只作补位。向量流不重排（相似度即目的）。

    C2 场景加成：hint 生效（v1=dialogue）时，同 scene_type 样本在**同档**
    （收藏/新近/早期）内排前——加成键放元组末位，档位键（favorite/era）
    优先级不变；sorted 稳定排序保证同档同型内仍保持既有次序
    （list_by_book 的 created_at 新→旧）。hint 未生效时加成键恒 1，
    排序与旧逻辑逐一致（零变化契约）。
    """
    def rank(s: Any) -> tuple:
        favorite = 0 if getattr(s, "favorite", False) else 1
        era = 0 if (getattr(s, "era", "recent") or "recent") != "early" else 1
        scene = 0 if _scene_match(s, scene_hint) else 1
        return (favorite, era, scene)

    return sorted(samples, key=rank)


async def retrieve_author_samples(
    db: AsyncSession,
    book_id: str,
    query_text: str = "",
    k: int = AUTHOR_SAMPLES_MAX_K,
    max_chars: int = AUTHOR_SAMPLE_MAX_CHARS,
    scene_type: Optional[str] = None,
    scene_hint: Optional[str] = None,
) -> List[str]:
    """检索 few-shot 作者样本（返回截断后的样本原文列表）。

    Args:
        db: 异步 DB session
        book_id: 书籍 ID
        query_text: 检索锚文本（当前写作上下文；空则直接走兜底流）
        k: 返回条数上限（默认 2，设计稿预算）
        max_chars: 每条截断上限
        scene_type: 可选场景**硬过滤**（对话/动作/抒情/悬念；None 不过滤；
            现无调用方传入，保留字段——C2 起软加成走 scene_hint，勿混用）
        scene_hint: C2 场景匹配软加成（None/"general" 零行为）：
            "dialogue" 时向量流同型样本得分 +0.1（距离 -0.1 重排）、
            兜底流同型同档内排前；异型样本不淘汰（非过滤）

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
                # C2：hint 生效时超额取候选再加成重排（top-k 外的同型样本
                # 才有机会进前 k）；无 hint 保持 limit=k 原口径（零变化）
                fetch_limit = (
                    max(k * _SCENE_HINT_OVERFETCH_FACTOR, k)
                    if scene_hint_active(scene_hint) else k
                )
                hits = await repo.search_by_style(
                    embedding=query_embedding,
                    book_id=book_id,
                    scene_type=scene_type,
                    limit=fetch_limit,
                )
                if scene_hint_active(scene_hint):
                    hits = sorted(
                        ((s, d - SCENE_HINT_BONUS) if _scene_match(s, scene_hint) else (s, d)
                         for s, d in hits),
                        key=lambda t: t[1],
                    )
                samples = [s for s, _distance in hits][:k]
        except Exception as e:
            logger.info(f"[StyleRetrieval] 向量检索降级（走新近兜底）: {e}")
            samples = None

    # ---- 兜底流：收藏优先 → 近期优先（hint 生效时同型同档内提前）----
    if samples is None:
        try:
            samples = order_samples_for_fallback(
                (await repo.list_by_book(book_id, scene_type=scene_type))[: max(k * 3, k)],
                scene_hint=scene_hint,
            )[:k]
        except Exception as e:
            logger.warning(f"[StyleRetrieval] 样本加载失败（返回空）: {e}")
            return []

    return [truncate_sample(s.content or "", max_chars) for s in samples if (s.content or "").strip()]

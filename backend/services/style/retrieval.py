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
作者样本检索（文风模块重构 S2 执行层 E1，docs/style-module-redesign.md §4）。

职责：生成时按当前写作上下文取 1-2 条作者样本做 few-shot 范例注入——
「一段范例胜过十句形容」，这是文风执行层里质量杠杆最大的注入方式。

两级检索（与 RAG「默认流打底 + 向量增强」同模式）：
1. 向量流（embedding 已配置时）：查询文本向量化 → AuthorSampleRepository
   .search_by_style 余弦检索 top-k（`samples/search` 端点同款，休眠设施接活）
2. 兜底流（未配置/向量化失败/无命中）：按 created_at 新近优先取 k 条
   （list_by_book 即新→旧序）——文风会进化，近期的字更能代表现在的作者

C2 场景匹配（docs/reports/foundation-hardening.md §5.2）：scene_hint（v1 仅
"dialogue"）生效时同型样本获软加成——向量流得分 +0.1（距离 -0.1 重排）、
兜底流同型在同档内排前。**软加成不等于 scene_type 硬过滤**：异型样本仍在
候选池内（宁缺排序变化，不做排他筛选）。hint 为 None/"general" 时行为与
现状逐一致（零变化契约）。

三平面分权·选择平面扩展（2026-08-29，docs/style-paradigm.md §3）：
- P5 采纳率先验：每样本「注入后被采纳」贝叶斯先验（ghost_token 埋点派生），
  向量流距离 ÷ 因子（0.8~1.2）、兜底流作排序末位键——只调序不筛选；
- P5 漂移锚样：drift_anchor=True 时收藏样本 +0.1（漂移检出 → 作者认证的
  最佳示范优先，v1 锚样启发式）；
- P6 旋钮选择器：已退役（2026-09-14 去参数化——数学空转实证，见
  docs/reports/style-parameter-effectiveness-audit.md §1.3）；
- P5 AI 来源配比：source=adopted_ghost 的样本每批 ≤1 条（防采纳幽灵自蒸馏
  污染样本库——长期回流会让文风向 AI 味收敛）。

红线：任何失败降级为空列表，调用方 prompt 零变化（不阻塞生成）。
预算：k≤2 × max_chars（默认 1200）≈ 单次注入 ≤2400 字（设计稿 §4 E1）。

全局笔迹库批（scope 维度，取代旧跨书黄金池冷启动暗道）：
- 候选池扩为 本书样本 ∪ 全局样本（scope='global'）；
- 「补位不抢位」：本书样本绝对优先（档位键置于一切排序键之前），
  本书样本不足 k 条时 global 池按同样规则补位；global 池为空时
  所有行为与旧版逐一致（零变化契约）；
- global 样本不参与 era（创作时期）维度的匹配/加分——era 是书级坐标，
  跨书样本谈「早期/近期」无意义；scene 匹配照常参与；
- era 为书级坐标的推论：fallback_rank 对 global（外来）样本 era 键恒 0。
"""

import logging
from typing import Any, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories import AuthorSampleRepository
from backend.services.llm.embedding import get_embedding, is_embedding_configured

# A3a 截断常量收敛（docs/reports/foundation-hardening.md §4.1）：样本剂量改引 budget 表
from backend.services.context.budget import AUTHOR_SAMPLE_MAX_CHARS, AUTHOR_SAMPLES_MAX_K
# C2 场景匹配（docs/reports/foundation-hardening.md §5.2）：dialogue hint 下同型样本加成
from backend.services.style.scene_hint import SCENE_GENERAL
from backend.services.style.sample_prior import PRIOR_FACTOR_MAX, sample_prior_factor

logger = logging.getLogger(__name__)

# AI 来源样本配比上限（P5）：每批 few-shot 至多 1 条采纳幽灵收编的样本
_AI_SOURCE_CAP = 1

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


def _is_foreign_sample(sample: Any, book_id: str) -> bool:
    """样本是否来自其它书（global 补位候选）。缺 book_id 属性的测试桩/
    异常形态一律视为本书（零变化兜底，不炸不误伤）。"""
    sid = getattr(sample, "book_id", None)
    return sid is not None and str(sid) != str(book_id)


def _tier_key(sample: Any, book_id: str) -> int:
    """补位不抢位的档位键：本书=0 / 外书 global=1，置于一切排序键之前。"""
    return 1 if _is_foreign_sample(sample, book_id) else 0


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


# ============================================================
# P6 样本轻指纹（选择器用，纯算法——候选池小，逐条现算可接受）
# —— 2026-09-14 去参数化（第三期审计）：_selector_adjust 与其轻指纹设施整体
#    退役。旋钮/对话目标在向量流无 hint 路径 fetch_limit=k 下连换序空间都不
#    存在（数学空转），兜底流是第 5 排序键几乎恒被前四键屏蔽；两字段已在
#    API 层冻结只读。检索排序回归真实信号：相似度/场景/收藏/新旧/采纳先验。
# ============================================================


def _cap_ai_source(ordered: List[Any], k: int) -> List[Any]:
    """P5 AI 来源配比：source=adopted_ghost 的样本每批至多 _AI_SOURCE_CAP 条，
    超出的让位给后面的非 AI 样本（不足 k 时保留原序补位）。"""
    out: List[Any] = []
    ai_used = 0
    for s in ordered:
        if str(getattr(s, "source", "") or "") == "adopted_ghost":
            if ai_used >= _AI_SOURCE_CAP:
                continue
            ai_used += 1
        out.append(s)
        if len(out) >= k:
            break
    return out


async def retrieve_author_samples_with_meta(
    db: AsyncSession,
    book_id: str,
    query_text: str = "",
    k: int = AUTHOR_SAMPLES_MAX_K,
    max_chars: int = AUTHOR_SAMPLE_MAX_CHARS,
    scene_type: Optional[str] = None,
    scene_hint: Optional[str] = None,
    style_card: Any = None,  # 2026-09-14 冻结：旋钮/对话目标退役后无消费，保留形参防调用方断裂
    drift_anchor: bool = False,
) -> List[Tuple[str, str]]:
    """检索 few-shot 样本（带样本 id——P5 回流埋点用）。

    与 retrieve_author_samples 同为两级检索，另叠加选择平面扩展（先验/
    漂移锚/旋钮选择器/AI 配比，见模块 docstring）。返回 [(sample_id, 截断文本)]。
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

                def vec_adjust(s: Any, d: float) -> float:
                    """距离微调：场景加成（既有）+ 先验因子 + 漂移锚。"""
                    adj = d - SCENE_HINT_BONUS if _scene_match(s, scene_hint) else d
                    adj /= sample_prior_factor(book_id, str(getattr(s, "id", "") or ""))
                    if drift_anchor and getattr(s, "favorite", False):
                        adj -= 0.1
                    return adj

                # 补位不抢位：重排不越档——本书样本（tier 0）内部按微调距离
                # 竞争，global 候选（tier 1）整体垫后只做补位；search_by_style
                # 的 SQL 已按 (tier, distance) 预排，此处键补齐防越档。
                # global 池为空时 tier 恒 0，与旧排序逐一致（零变化契约）。
                hits = sorted(
                    ((s, vec_adjust(s, d)) for s, d in hits),
                    key=lambda t: (_tier_key(t[0], book_id), t[1]),
                )
                # 零命中回落兜底流（B4 顺修）：本书零样本/样本全无向量时
                # search_by_style 返 []——旧代码把 [] 当「有结果」直接短路，
                # 兜底流永不激活（模块 docstring 声称的「无命中走兜底」名不副实）
                samples = _cap_ai_source([s for s, _ in hits], k) or None
        except Exception as e:
            logger.info(f"[StyleRetrieval] 向量检索降级（走新近兜底）: {e}")
            samples = None

    # ---- 兜底流：本书档 → 收藏 → 近期 → 场景 → 先验（全为软排序键）----
    if samples is None:
        try:
            pool = (await repo.list_by_book(book_id, scene_type=scene_type))[: max(k * 3, k)]
            # 全局笔迹库补位池（scope='global'，取代旧跨书黄金池冷启动暗道）：
            # 不论本书池是否为空都取——排序层本书样本绝对优先，global 只在
            # 本书候选不足 k 条时自然补位。挂点纪律不变：只在检索层兜**样本**，
            # 文风卡（画像/负面清单/写作规矩）永远书级隔离。
            try:
                pool = pool + await repo.list_global(
                    exclude_book_id=book_id, limit=max(k * 3, k),
                )
            except Exception as cross_e:
                logger.info(f"[StyleRetrieval] 全局池查询失败（忽略）: {cross_e}")

            def fallback_rank(s: Any) -> tuple:
                tier = _tier_key(s, book_id)
                foreign = tier == 1
                favorite = 0 if getattr(s, "favorite", False) else 1
                # era 是书级坐标：global（外来）样本不参与时期维度——键恒 0
                era = 0 if foreign or (getattr(s, "era", "recent") or "recent") != "early" else 1
                scene = 0 if _scene_match(s, scene_hint) else 1
                # 先验因子升序键（factor∈[0.8,1.2] → 键∈[0,0.4]，越大越靠后）
                prior_key = PRIOR_FACTOR_MAX - sample_prior_factor(
                    book_id, str(getattr(s, "id", "") or ""))
                return (tier, favorite, era, scene, round(prior_key, 3))

            ordered = sorted(pool, key=fallback_rank)
            samples = _cap_ai_source(ordered, k)
        except Exception as e:
            logger.warning(f"[StyleRetrieval] 样本加载失败（返回空）: {e}")
            return []

    return [
        # id 防御式取用：测试桩/异常形态的样本对象可能无 id（P5 埋点容忍缺席）
        (str(getattr(s, "id", "") or ""), truncate_sample(s.content or "", max_chars))
        for s in samples if (s.content or "").strip()
    ]


async def retrieve_author_samples(
    db: AsyncSession,
    book_id: str,
    query_text: str = "",
    k: int = AUTHOR_SAMPLES_MAX_K,
    max_chars: int = AUTHOR_SAMPLE_MAX_CHARS,
    scene_type: Optional[str] = None,
    scene_hint: Optional[str] = None,
) -> List[str]:
    """检索 few-shot 作者样本（返回截断后的样本原文列表）——兼容包装。

    存量消费方（ADF/refinery/audition）不需要样本 id，经此包装保持签名不变；
    stitch 链（需 P5 埋点 sample_ids）走 retrieve_author_samples_with_meta。
    """
    pairs = await retrieve_author_samples_with_meta(
        db, book_id, query_text=query_text, k=k, max_chars=max_chars,
        scene_type=scene_type, scene_hint=scene_hint,
    )
    return [text for _sid, text in pairs]

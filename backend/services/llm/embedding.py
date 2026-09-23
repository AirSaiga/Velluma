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
文本向量化模块 - 文本嵌入生成服务。

职责：
- 提供文本到向量 embedding 的转换能力
- 走 OpenAI 兼容 Embedding 协议（POST /embeddings），厂商无关
- 为 RAG 检索系统提供向量表示

业务场景：
- RAG 记忆存储前的向量化
- 相似度检索时的查询向量生成
- 语义搜索的向量编码

主要功能：
- 单文本向量化（get_embedding：失败静默降级返回 []）
- 批量向量化（get_embeddings / get_embeddings_api_only：按
  EMBEDDING_BATCH_SIZE 透明分批，防模型单请求条数上限整体 400）
- 连通性探测（probe_embedding：设置面板「连接测试」用，结构化报错不静默）
- 连接可跟随文本模型（follow_llm：复用写作/分析模型槽的 api_key+base_url）
  或自管 api_key/base_url（见 model_config.get_embedding_connection）
- 可配置维度向量输出（通过 model_config.json 配置）
- 维度验证，确保与数据库 schema 一致

依赖项：
- openai SDK（AsyncOpenAI，与 LLM 客户端同协议栈）
- 代理与 LLM 客户端同策略（proxy.get_active_proxy）
- DashScope 历史用户零迁移：base_url 缺省回退 DashScope 兼容端点，
  原 Key 直接可用（text-embedding-v2/v3/v4 均在兼容模式提供）

使用方式：
    embedding = await get_embedding("需要向量化的文本")
"""

import logging
import math
from typing import List, Optional, Union

import httpx
from openai import AsyncOpenAI

from backend.core.model_config import (
    DASHSCOPE_COMPAT_BASE_URL,
    get_embedding_config,
    get_embedding_connection,
    get_embedding_follow_source,
)
from backend.services.llm.proxy import get_active_proxy as _get_active_proxy

logger = logging.getLogger(__name__)

# SQLite 方言一次性警告标志：首次因方言短路返回 False 时提示一次（防高频调用刷屏）
_SQLITE_VECTOR_WARNED = False


def is_embedding_configured() -> bool:
    """embedding 是否已配置（有效连接含 api_key）。

    记忆流路由开关：配置 → 向量召回增强（专业级）；未配置 → 结构化+词法默认流
    （recall.py）。纯读 model_config.json，无副作用。

    方言门控：向量流（检索 cosine_distance + 写入 embedding 列）依赖 pgvector，
    为 PG 专有——SQLite 默认后端下即使配置了 embedding，检索层也会报
    `near ">": syntax error`（recall/style 检索静默降级、/samples/search 500）。
    故 SQLite 下一律视为未配置：词法默认流不受影响，写入侧也不再产出
    永远查不到的向量。
    """
    global _SQLITE_VECTOR_WARNED
    # 函数内延迟 import：backend.database 只依赖 sqlalchemy/dotenv，不反向
    # import services.llm（无循环），延迟仅为隔离模块加载时序、稳妥起见
    from backend.database import USE_SQLITE

    if USE_SQLITE:
        if not _SQLITE_VECTOR_WARNED:
            logger.warning(
                "SQLite 后端不支持向量记忆（pgvector 为 PG 专有），embedding 配置暂不生效；"
                "词法默认流不受影响，切 PG（显式设 DATABASE_URL）可启用向量流"
            )
            _SQLITE_VECTOR_WARNED = True
        return False
    return bool(get_embedding_connection().get("api_key"))


def is_embedding_api_configured() -> bool:
    """存储无关的窄判定（2026-09-02 约束治理二期）：只看 embedding 连接是否
    配了 Key——纯 API 余弦比对（semantic_overlap 抢拍语义闸等**不写向量列、
    不走 pgvector 检索**的消费面）在 SQLite 默认部署下同样可用。

    与 is_embedding_configured()（含 SQLite 方言门控，管向量存储/检索流）
    并列，各管各的消费面——不要把本判定塞进旧函数（会放行 SQLite 下的
    pgvector 检索路径报语法错）。纯读 model_config.json，无副作用。
    """
    try:
        return bool(get_embedding_connection().get("api_key"))
    except Exception:
        return False


# 已知接受 OpenAI 风格 dimensions 参数的模型名前缀（小写比对）。
# 未命中的模型一律不传 dimensions——部分服务对未知参数直接 400
# （DashScope text-embedding-v2 传 dimensions 必报错），按原生维度返回后
# 由维度比对兜底（不匹配记 error 并丢弃，probe 探测会把不匹配暴露给用户）。
_DIMENSIONS_PARAM_PREFIXES = (
    "text-embedding-v3",   # DashScope
    "text-embedding-v4",   # DashScope（Qwen3-Embedding 托管版）
    "qwen3.7-text-embedding",  # DashScope 2026 新一代
    "qwen3-embedding",     # 硅基流动等托管的 Qwen3-Embedding 0.6B/4B/8B
    "text-embedding-3",    # OpenAI text-embedding-3-small/large
    "embedding-3",         # 智谱 embedding-3
)


def _supports_dimensions_param(model: str) -> bool:
    return model.lower().startswith(_DIMENSIONS_PARAM_PREFIXES)


# 单次 embedding 请求的 input 条数上限（批量透明分批粒度）。
# 来源：当前配置的 qwen3.7-text-embedding（DashScope 兼容端点）实测单批
# >20 条直接 400「batch size is invalid, it should not be larger than 20」
# ——docs/reports/semantic-threshold-calibration.md §6.1；其他已知模型上限
# 不低于此（text-embedding-v3/v4 为 25，待证），20 对全部已知模型安全。
EMBEDDING_BATCH_SIZE = 20


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """余弦相似度（纯函数）：空向量/零模返回 0.0。

    语义与 services/workflows/validators.py 的同名实现一致（那边不动，
    避免触碰在役引擎）；本处提供新消费方（style/semantic_match.py 语义
    匹配器、校准脚本）共用的规范实现，勿再散第三份。
    """
    if not v1 or not v2:
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    mag1 = math.sqrt(sum(a * a for a in v1))
    mag2 = math.sqrt(sum(b * b for b in v2))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot_product / (mag1 * mag2)


async def _request_embedding(
    text: Union[str, List[str]],
    *,
    api_key: str,
    base_url: str,
    model: str,
    dimensions: int,
    timeout: float,
) -> Union[list, List[list]]:
    """底层调用：成功返回向量；网络/鉴权/参数错误直接抛异常（调用方决定降级或上报）。

    input 兼容单文本（str → 单向量）与批量（List[str] → 按输入序对齐的
    向量列表，OpenAI 兼容协议单请求带一批 input）。

    批量透明分批（2026-09-24 生产修复，校准报告 §6.1）：List 输入按
    EMBEDDING_BATCH_SIZE 切分、逐批串行请求（批间不并发，避免触发限流）、
    按输入序拼接，签名与返回形状不变，对调用方完全透明。存储门控路径
    （get_embeddings）与纯 API 路径（get_embeddings_api_only）均经本函数
    发送，分批天然同时覆盖两者（单文本 get_embedding/probe_embedding 传
    str 不进分批支路，行为零变化）。单批失败直接抛异常中止后续批次——
    与分批前「单次请求失败=整体失败」的错误语义一致，由调用方统一降级
    为全空（不产出半截结果，避免部分段落静默漏检）。
    """
    if isinstance(text, list) and len(text) > EMBEDDING_BATCH_SIZE:
        vectors: List[list] = []
        for start in range(0, len(text), EMBEDDING_BATCH_SIZE):
            vectors.extend(await _request_embedding(
                list(text[start:start + EMBEDDING_BATCH_SIZE]),
                api_key=api_key,
                base_url=base_url,
                model=model,
                dimensions=dimensions,
                timeout=timeout,
            ))
        return vectors

    call_kwargs: dict = {"model": model, "input": text}
    if _supports_dimensions_param(model):
        call_kwargs["dimensions"] = dimensions

    http_client = httpx.AsyncClient(trust_env=False, proxy=_get_active_proxy(), timeout=float(timeout))
    try:
        client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            http_client=http_client,
        )
        resp = await client.embeddings.create(**call_kwargs)
        if isinstance(text, list):
            return [item.embedding for item in resp.data]
        return resp.data[0].embedding
    finally:
        await http_client.aclose()


async def get_embedding(
    text: str,
    model: Optional[str] = None,
    timeout: int = 60,
) -> list:
    """生产路径：任何失败都静默降级为 []（检索层回退词法流，绝不阻塞写作）。"""
    connection = get_embedding_connection()
    api_key = connection["api_key"]
    emb_model = model or connection["model"]
    expected_dimensions = connection["dimensions"]

    if not api_key:
        logger.warning(
            "[Embedding] API Key 未设置（embedding.api_key 为空且未开启 follow_llm "
            "或文本模型槽也无 Key），请在 model_config.json 或设置面板中配置"
        )
        return []

    try:
        embedding = await _request_embedding(
            text,
            api_key=api_key,
            base_url=connection["base_url"],
            model=emb_model,
            dimensions=expected_dimensions,
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"[Embedding] 异常: {e}")
        return []

    # 验证维度是否匹配数据库配置
    actual_dimensions = len(embedding)
    if actual_dimensions != expected_dimensions:
        logger.error(
            f"[Embedding] 维度不匹配: 模型 {emb_model} 输出 {actual_dimensions} 维, "
            f"数据库配置 {expected_dimensions} 维。"
            f"请检查 model_config.json 中的 embedding.dimensions 配置"
        )
        return []

    logger.info(
        f"[Embedding] 向量维度: {actual_dimensions}, 模型: {emb_model}, "
        f"连接: {connection['source']} ({connection['base_url']})"
    )
    return embedding


async def get_embeddings(
    texts: List[str],
    model: Optional[str] = None,
    timeout: int = 120,
) -> List[list]:
    """批量版 get_embedding：批量请求经 _request_embedding 按
    EMBEDDING_BATCH_SIZE 透明分批（≤20 条仍为单次调用，超限切批串行
    拼接），签名与返回形状不变。

    静默降级风格与 get_embedding 一致：
    - 空列表 → []；未配置（is_embedding_configured() False，含 SQLite
      方言门控）→ 与输入等长的全 [] 列表（零网络调用）
    - 整体异常 / 响应条数与输入不齐 → 与输入等长的全 [] 列表
    - 逐条维度校验（不符该条置 []，其余条不受牵连）
    - 不缓存（缓存策略是调用方的职责，如 semantic_match 的模式向量缓存）
    """
    if not texts:
        return []
    if not is_embedding_configured():
        return [[] for _ in texts]

    connection = get_embedding_connection()
    api_key = connection["api_key"]
    emb_model = model or connection["model"]
    expected_dimensions = connection["dimensions"]

    try:
        embeddings = await _request_embedding(
            list(texts),
            api_key=api_key,
            base_url=connection["base_url"],
            model=emb_model,
            dimensions=expected_dimensions,
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"[Embeddings] 批量异常: {e}")
        return [[] for _ in texts]

    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        logger.error(
            f"[Embeddings] 响应条数不齐: 期望 {len(texts)} 实得 "
            f"{len(embeddings) if isinstance(embeddings, list) else '非列表'}"
        )
        return [[] for _ in texts]

    results: List[list] = []
    for emb in embeddings:
        if len(emb) != expected_dimensions:
            logger.error(
                f"[Embeddings] 维度不匹配: 模型 {emb_model} 输出 {len(emb)} 维, "
                f"配置 {expected_dimensions} 维，该条置空"
            )
            results.append([])
        else:
            results.append(emb)
    return results


async def get_embeddings_api_only(
    texts: List[str],
    model: Optional[str] = None,
    timeout: int = 120,
) -> List[list]:
    """纯 API 语义的批量向量（2026-09-02 约束治理二期，语义比对专用入口）。

    与 get_embeddings 的唯一区别：门控是 is_embedding_api_configured()
    （只看 Key）而非 is_embedding_configured()（含 SQLite 存储门控）——
    语义余弦比对（semantic_overlap 抢拍语义闸）不落库、不走 pgvector
    检索，SQLite 默认部署同样可用。

    纪律：调用方不得把产物写向量列（写侧永远走 get_embeddings——SQLite
    下它正确地空转省钱，本入口放行是因为比对面根本不碰存储）。降级行为
    与 get_embeddings 完全一致（未配置/异常/条数不齐/维度不符 → 对应位
    置 []）；分批同经 _request_embedding 透明覆盖（EMBEDDING_BATCH_SIZE）。
    """
    if not texts:
        return []
    if not is_embedding_api_configured():
        return [[] for _ in texts]

    connection = get_embedding_connection()
    emb_model = model or connection["model"]
    expected_dimensions = connection["dimensions"]

    try:
        embeddings = await _request_embedding(
            list(texts),
            api_key=connection["api_key"],
            base_url=connection["base_url"],
            model=emb_model,
            dimensions=expected_dimensions,
            timeout=timeout,
        )
    except Exception as e:
        logger.error(f"[Embeddings] api_only 批量异常: {e}")
        return [[] for _ in texts]

    if not isinstance(embeddings, list) or len(embeddings) != len(texts):
        logger.error(
            f"[Embeddings] api_only 响应条数不齐: 期望 {len(texts)} 实得 "
            f"{len(embeddings) if isinstance(embeddings, list) else '非列表'}"
        )
        return [[] for _ in texts]

    results: List[list] = []
    for emb in embeddings:
        if len(emb) != expected_dimensions:
            logger.error(
                f"[Embeddings] api_only 维度不匹配: 模型 {emb_model} 输出 "
                f"{len(emb)} 维, 配置 {expected_dimensions} 维，该条置空"
            )
            results.append([])
        else:
            results.append(emb)
    return results


async def probe_embedding(overrides: Optional[dict] = None, timeout: int = 15) -> dict:
    """连通性探测（设置面板「连接测试」用）。绝不抛异常，结果全在返回字典里。

    Args:
        overrides: 未保存的表单值 {model, base_url, dimensions, follow_llm, api_key}；
                   None 表示探测已保存的配置。api_key 留空沿用已保存 Key。

    Returns:
        {
          configured: bool,        # 有效连接是否含 Key（False=跳过，不算失败）
          success: bool,
          message: str,            # 人话结论（含修复建议）
          model: str,
          source: str | None,      # self / creative / reasoning
          dimensions_expected: int | None,
          dimensions_returned: int | None,
        }
    """
    if overrides is not None:
        saved = get_embedding_config()
        follow = bool(overrides.get("follow_llm", saved.get("follow_llm", False)))
        model = (overrides.get("model") or "").strip() or saved.get("model", "text-embedding-v2")
        dimensions = overrides.get("dimensions") or saved.get("dimensions", 1536)
        if follow:
            followed = get_embedding_follow_source()
            api_key, base_url, source = followed["api_key"], followed["base_url"], followed["source"]
        else:
            api_key = (overrides.get("api_key") or "").strip() or saved.get("api_key", "")
            base_url = (overrides.get("base_url") or "").strip() or DASHSCOPE_COMPAT_BASE_URL
            source = "self"
    else:
        connection = get_embedding_connection()
        api_key = connection["api_key"]
        base_url = connection["base_url"]
        model = connection["model"]
        dimensions = connection["dimensions"]
        source = connection["source"]

    result = {
        "configured": bool(api_key),
        "success": False,
        "message": "",
        "model": model,
        "source": source,
        "dimensions_expected": dimensions,
        "dimensions_returned": None,
    }
    if not api_key:
        result["message"] = "未配置 API Key"
        return result

    try:
        embedding = await _request_embedding(
            "连接测试",
            api_key=api_key,
            base_url=base_url,
            model=model,
            dimensions=dimensions,
            timeout=timeout,
        )
    except Exception as e:
        result["message"] = f"连接失败 - {str(e)[:200]}"
        return result

    returned = len(embedding)
    result["dimensions_returned"] = returned
    if returned != dimensions:
        # 连接本身是通的，但维度对不上运行时一律丢弃（get_embedding 的硬校验），
        # 对用户而言等于不可用——按失败报，给出明确修法
        result["message"] = (
            f"连接成功，但模型返回 {returned} 维，与配置的 {dimensions} 维不符；"
            f"请把向量维度改为 {returned}（保存并重启会重建向量列，清空全部向量记忆数据）"
        )
        return result

    result["success"] = True
    result["message"] = f"连接成功，返回 {returned} 维，与配置一致"
    return result

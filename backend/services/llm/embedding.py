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
from typing import Optional

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


def is_embedding_configured() -> bool:
    """embedding 是否已配置（有效连接含 api_key）。

    记忆流路由开关：配置 → 向量召回增强（专业级）；未配置 → 结构化+词法默认流
    （recall.py）。纯读 model_config.json，无副作用。
    """
    return bool(get_embedding_connection().get("api_key"))


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


async def _request_embedding(
    text: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    dimensions: int,
    timeout: float,
) -> list:
    """底层调用：成功返回向量；网络/鉴权/参数错误直接抛异常（调用方决定降级或上报）。"""
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

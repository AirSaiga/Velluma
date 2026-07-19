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
LLM 调用客户端 - 统一封装 OpenAI 兼容 API 调用。

职责：
- 提供流式和非流式聊天补全接口
- 封装重试逻辑、超时处理、代理配置
- 支持多种 LLM 提供商（OpenAI/DashScope/本地模型）

业务场景：
- Agentic 工作流各阶段的文本生成
- 章节起草、审阅、精修等核心生成任务
- RAG 摘要生成、上下文组装

主要功能：
- 流式响应（SSE）用于实时输出
- 重试机制（指数退避）保证可靠性
- 代理配置支持（解决网络访问问题）

依赖项：
- OpenAI Python SDK: API 调用封装
- Tenacity: 重试策略
- httpx: HTTP 客户端

使用方式：
    response = await generate_stream_response(
        system_prompt="...",
        user_prompt="...",
        model_type="reasoning"  # 或 model="gpt-4"
    )
    async for chunk in response:
        print(chunk)
"""

import json
import os
import time
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    retry_if_exception,
)

from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_RAG, LOG_PREFIX_SUMMARY
from backend.services.llm.proxy import (
    get_proxy_config,
    set_proxy_config,
    get_active_proxy as _get_active_proxy,
)
from backend.services.llm.embedding import get_embedding
from backend.core.model_config import get_model_profile, resolve_model_name, get_default_reasoning_config, DEFAULT_PROVIDER_URLS


logger = logging.getLogger(__name__)
svc_logger_rag = ServiceLogger(logger, LOG_PREFIX_RAG)
svc_logger_summary = ServiceLogger(logger, LOG_PREFIX_SUMMARY)

PROXY_URL = os.getenv("PROXY_URL", "http://127.0.0.1:4780")
if os.getenv("DISABLE_PROXY") == "1":
    PROXY_URL = None
if not PROXY_URL:
    PROXY_URL = None


def _should_retry_exception(exception: Exception) -> bool:
    from openai import APIConnectionError, RateLimitError, InternalServerError, APIStatusError

    if isinstance(exception, (APIConnectionError, RateLimitError, InternalServerError)):
        return True
    if isinstance(exception, APIStatusError):
        return exception.status_code >= 500
    return False


@retry(
    retry=retry_if_exception_type(Exception) & retry_if_exception(_should_retry_exception),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=2, max=60),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
async def _create_chat_completion(client: AsyncOpenAI, **kwargs):
    return await client.chat.completions.create(**kwargs)


async def generate_stream_response(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    model_type: str = "default",
    max_tokens: int = 8192,
    reasoning_config: Optional[dict] = None,
):
    import httpx

    profile = get_model_profile(model_type)
    api_key = profile["api_key"]
    provider = profile["provider"]
    base_url = profile["base_url"] or DEFAULT_PROVIDER_URLS.get(provider, "https://openrouter.ai/api/v1")
    resolved_model = resolve_model_name(model, model_type)

    if reasoning_config is None:
        reasoning_config = get_default_reasoning_config(model_type)

    yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
    http_client = None
    try:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url.rstrip("/")
        http_client = httpx.AsyncClient(trust_env=False, proxy=_get_active_proxy(), timeout=600.0)
        client_kwargs["http_client"] = http_client
        client = AsyncOpenAI(**client_kwargs)

        create_kwargs = {
            "model": resolved_model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "stream": True,
            "temperature": 0.7,
            "max_tokens": max_tokens,
        }

        if reasoning_config:
            create_kwargs["extra_body"] = reasoning_config

        stream = await _create_chat_completion(client=client, **create_kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    except Exception as e:
        raw_error_msg = str(e).strip()
        error_type = type(e).__name__
        response = getattr(e, "response", None)
        status_code = getattr(response, "status_code", None) if response is not None else None
        response_text = None
        if response is not None:
            try:
                response_text = response.text
            except Exception:
                response_text = None
        if isinstance(response_text, str):
            response_text = response_text.strip()
            if len(response_text) > 500:
                response_text = response_text[:500] + "..."
        parts = [error_type]
        if raw_error_msg:
            parts.append(raw_error_msg)
        if status_code:
            parts.append(f"status={status_code}")
        if response_text:
            parts.append(response_text)
        error_msg = " | ".join(parts)
        
        # 统一错误格式：使用 event 格式与其他模块保持一致
        error_payload = {
            "event": "ERROR",
            "message": f"LLM调用失败: {error_msg}",
            "error_type": error_type,
            "status_code": status_code,
        }
        yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"
        
        # 发送 DONE 事件标记结束
        done_payload = {
            "event": "DONE",
            "error": error_msg,
            "success": False,
        }
        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
    finally:
        if http_client is not None:
            await http_client.aclose()


async def generate_summary(
    text: str,
    model: Optional[str] = None,
    model_type: str = "default",
) -> str:
    system_prompt = "你是一个专业的小说编辑。请为以下章节生成 200 字以内的摘要，概括主要情节和关键伏笔。"

    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await call_llm(
                system_prompt=system_prompt,
                user_prompt=text,
                model=model,
                model_type=model_type,
            )
        except Exception as e:
            if attempt == max_retries - 1:
                svc_logger_summary.error("Final attempt failed", error=str(e))
                raise
            wait_time = (2 ** attempt) * 1
            svc_logger_summary.warning("Attempt failed, retrying", attempt=attempt + 1, wait_time=wait_time, error=str(e))
            await asyncio.sleep(wait_time)
    return ""


async def format_text_with_llm(
    text: str,
    model: Optional[str] = None,
    model_type: str = "default",
) -> str:
    system_prompt = """你是一个专业的文本编辑助手。你的任务是整理用户提供的文本格式。
具体要求：
1. 智能分段：根据语义和上下文，将过长的段落拆分为合理的短段落，增强阅读体验。
2. 标点修正：修正文中错误或缺失的标点符号。
3. 格式规范：确保段落之间有适当的空行（如果需要），去除多余的空格。
4. 内容保持：绝对不要修改文本的原意、语气或用词，只调整格式和标点。
请直接返回整理后的纯文本，不要使用 Markdown 代码块标记（如 ```），也不要包含任何解释或额外的对话。"""

    return await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        model_type=model_type,
        temperature=0.3,
    )


# ============================================================
# Phase 0 观测层：带 usage 采集的 LLM 调用接口
# ============================================================
# 设计依据：调研报告 §2.2-13（全链路零 token 计量）。
# 职责：在原有调用逻辑基础上，采集 response.usage（含 thinking token 拆分）
#       和延迟，包装为 LLMResult 供 RunRecorder 落库 generation_runs。
# 注意：旧 call_llm 仍保留（兼容 9 处调用方），内部转调本函数剥离 usage。


@dataclass
class LLMResult:
    """LLM 调用结果（含 usage 计量）。

    Attributes:
        content: 模型输出文本
        usage: token 计量 {prompt_tokens, completion_tokens, reasoning_tokens}；无 usage 时为 None
        model_name: 实际调用的模型名
        latency_ms: 本次调用耗时（毫秒）
    """
    content: str
    usage: Optional[dict]
    model_name: str
    latency_ms: int


def _parse_usage(response) -> Optional[dict]:
    """从 OpenAI SDK response 中提取 usage（含 thinking token 拆分）。

    OpenAI 兼容协议下，DeepSeek/Qwen 的思考 token 通常落在
    response.usage.completion_tokens_details.reasoning_tokens。
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    # completion_tokens_details 是 SDK 1.10+ 的可选字段（含 reasoning_tokens）
    details = getattr(usage, "completion_tokens_details", None)
    reasoning_tokens = None
    if details is not None:
        reasoning_tokens = getattr(details, "reasoning_tokens", None)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
    }


async def call_llm_with_usage(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    model_type: str = "default",
    temperature: float = 0.7,
    response_format: Optional[dict] = None,
    max_tokens: int = 8192,
    top_p: float = 1.0,
    reasoning_config: Optional[dict] = None,
) -> LLMResult:
    """带 usage 采集的 LLM 调用。

    职责：与旧 call_llm 行为完全一致，额外采集 response.usage 与延迟。
    业务场景：观测层（Phase 0 T1）逐调用计量 token 成本。
    使用方式：配合 RunRecorder 落库：
        async with RunRecorder(db, chapter_id, run_id, stage, model_slot) as r:
            result = await call_llm_with_usage(...)
            r.record(result)

    Raises:
        Exception: LLM 调用失败（tenacity 重试耗尽后向上抛出）。
    """
    import httpx

    profile = get_model_profile(model_type)
    api_key = profile["api_key"]
    provider = profile["provider"]
    base_url = profile["base_url"] or DEFAULT_PROVIDER_URLS.get(provider, "https://openrouter.ai/api/v1")
    resolved_model = resolve_model_name(model, model_type)

    if reasoning_config is None:
        reasoning_config = get_default_reasoning_config(model_type)

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")
    http_client = httpx.AsyncClient(trust_env=False, proxy=_get_active_proxy(), timeout=600.0)
    client_kwargs["http_client"] = http_client
    client = AsyncOpenAI(**client_kwargs)

    start_ts = time.perf_counter()
    try:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        create_kwargs = {
            "model": resolved_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        if response_format:
            create_kwargs["response_format"] = response_format

        if reasoning_config:
            create_kwargs["extra_body"] = reasoning_config

        response = await _create_chat_completion(client=client, **create_kwargs)
        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content
        usage = _parse_usage(response)
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        return LLMResult(content=content, usage=usage, model_name=resolved_model, latency_ms=latency_ms)
    except json.JSONDecodeError:
        # 兼容旧 call_llm 行为：JSON 解析异常返回空内容（不抛出）
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        return LLMResult(content="", usage=None, model_name=resolved_model, latency_ms=latency_ms)
    finally:
        if http_client is not None:
            await http_client.aclose()


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    model_type: str = "default",
    temperature: float = 0.7,
    response_format: Optional[dict] = None,
    max_tokens: int = 8192,
    top_p: float = 1.0,
    reasoning_config: Optional[dict] = None,
) -> str:
    """旧版 LLM 调用接口（保持兼容）。

    职责：包装 call_llm_with_usage，剥离 usage 数据返回纯文本。
    设计意图：Phase 0 新增观测层时，为不破坏 9 处现有调用方，保留此签名。
    新代码应使用 call_llm_with_usage（带 usage 计量）。
    """
    result = await call_llm_with_usage(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        model_type=model_type,
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
        top_p=top_p,
        reasoning_config=reasoning_config,
    )
    return result.content


async def optimize_selection_with_llm(
    selected_text: str,
    context_before: str,
    context_after: str,
    outline: str,
    user_instruction: str,
    model: Optional[str] = None,
    model_type: str = "default",
    mode: str = "rewrite",
    tone: Optional[str] = None,
) -> str:
    """选区级改写（CP4.1 蓝图 §4.9）。

    按 mode 分派 system prompt（5 种模式），tone_shift 时注入 tone。
    user_instruction 作为附加指令（mode 是大方向，user_instruction 是细节）。

    Args:
        mode: rewrite / describe / expand / compress / tone_shift（默认 rewrite，向后兼容）
        tone: 仅 mode=tone_shift 时生效，目标语气
    """
    from backend.services.llm.selection_rewrite import (
        build_selection_rewrite_system_prompt,
        build_selection_rewrite_user_prompt,
    )

    system_prompt = build_selection_rewrite_system_prompt(mode=mode, tone=tone)
    user_prompt = build_selection_rewrite_user_prompt(
        selected_text=selected_text,
        context_before=context_before,
        context_after=context_after,
        outline=outline,
        user_instruction=user_instruction,
    )

    return await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        model_type=model_type,
        temperature=0.7,
    )

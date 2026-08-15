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
import re
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
from backend.services.observability.run_trace import trace_event
from backend.services.llm.proxy import (
    get_proxy_config,
    set_proxy_config,
    get_active_proxy as _get_active_proxy,
)
from backend.services.llm.embedding import get_embedding
from backend.services.llm.reasoning_adapter import adapt_reasoning_config
from backend.core.model_config import get_model_profile, resolve_model_name, get_default_reasoning_config, DEFAULT_BASE_URL


logger = logging.getLogger(__name__)
svc_logger_rag = ServiceLogger(logger, LOG_PREFIX_RAG)
svc_logger_summary = ServiceLogger(logger, LOG_PREFIX_SUMMARY)


# 显式关闭 thinking 的 extra_body（OpenRouter reasoning 协议）。
# ⚠ 绝不能传空 dict 代替：call_llm_with_usage 里 `if reasoning_config:` 对 {}
# 为 falsy，extra_body 根本不会设置，推理模型（如 deepseek-v4-pro）回落到
# 服务端默认 thinking 开启——小预算调用（状态卡 max_tokens=400）会被思考
# 过程吃光 token 预算，finish=length 空输出（实测 5 次抽取 3 次失败）。
REASONING_DISABLED: dict = {"reasoning": {"enabled": False}}


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


# 采样参数锁定报错："invalid temperature: only 1 is allowed for this model" 等
_PARAM_LOCK_RE = re.compile(r"invalid (\w+): only ([\d.]+) is allowed", re.IGNORECASE)
# 允许自适应改写的参数白名单（防错误消息注入任意参数）
_ADAPTIVE_PARAMS = {"temperature", "top_p", "frequency_penalty", "presence_penalty"}


async def _create_chat_completion_adaptive(client: AsyncOpenAI, **kwargs):
    """带参数锁自适应的补全调用。

    业务场景：部分模型把采样参数锁死（kimi-k3 锁 temperature=1、top_p=0.95；
    OpenAI o 系列 / GPT-5 锁 temperature=1），显式传其他值直接报 400。
    此处解析 "invalid X: only Y is allowed" 错误，按锁定值改写参数重试，
    最多自适应 2 个参数（如同时锁 temperature + top_p）。
    无法解析的旧式锁温报错兜底为去掉 temperature 重试一次。
    400 不会触发 tenacity 重试（_should_retry_exception 只放行 5xx/429/连接错误），
    所以自适应路径是即时的，不会拖慢正常失败。
    """
    adapted = 0
    while True:
        try:
            return await _create_chat_completion(client=client, **kwargs)
        except Exception as e:
            msg = str(e)
            m = _PARAM_LOCK_RE.search(msg)
            if m and m.group(1).lower() in _ADAPTIVE_PARAMS and adapted < 2:
                param, value = m.group(1).lower(), float(m.group(2))
                kwargs[param] = value
                adapted += 1
                logger.warning(f"[LLM] 模型锁定 {param}={value}，已按锁定值重试: {msg[:120]}")
                continue
            lowered = msg.lower()
            if "temperature" in lowered and "invalid" in lowered and "temperature" in kwargs:
                kwargs.pop("temperature")
                logger.warning(f"[LLM] 模型锁死 temperature，已改用服务端默认值重试: {msg[:120]}")
                continue
            raise


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
    base_url = profile["base_url"] or DEFAULT_BASE_URL
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
            # Provider 适配：把统一中间表示 {reasoning:{enabled,effort}} 转成各厂商原生参数
            # （DeepSeek→thinking.type+reasoning_effort、OpenAI→reasoning_effort、Qwen→enable_thinking
            # +thinking_budget 等）。base_url 和 resolved_model 在作用域内，供 provider 识别。
            adapted = adapt_reasoning_config(reasoning_config, base_url, resolved_model)
            if adapted:
                create_kwargs["extra_body"] = adapted

        stream = await _create_chat_completion_adaptive(client=client, **create_kwargs)
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
        finish_reason: 模型停止原因（"stop"/"length"/"content_filter"/...）； None 表示未获取。
            "length" 表示因撞 max_tokens 上限被截断——下游（如 ADF segment_writer）应据此
            重试或清残句，避免把半句话当成功用。
    """
    content: str
    usage: Optional[dict]
    model_name: str
    latency_ms: int
    finish_reason: Optional[str] = None


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
    base_url = profile["base_url"] or DEFAULT_BASE_URL
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
            # Provider 适配：把统一中间表示 {reasoning:{enabled,effort}} 转成各厂商原生参数
            # （DeepSeek→thinking.type+reasoning_effort、OpenAI→reasoning_effort、Qwen→enable_thinking
            # +thinking_budget 等）。base_url 和 resolved_model 在作用域内，供 provider 识别。
            adapted = adapt_reasoning_config(reasoning_config, base_url, resolved_model)
            if adapted:
                create_kwargs["extra_body"] = adapted

        response = await _create_chat_completion_adaptive(client=client, **create_kwargs)
        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content
        usage = _parse_usage(response)
        finish_reason = None
        try:
            finish_reason = response.choices[0].finish_reason if response.choices else None
        except (AttributeError, IndexError):
            finish_reason = None
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        # 全流程 trace 埋点（无 trace 时 no-op；prompt/响应全文记录供 debug）
        trace_event(
            "llm_call",
            model_type=model_type,
            model_name=resolved_model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            content=content,
            usage=usage,
            latency_ms=latency_ms,
            finish_reason=finish_reason,
        )
        return LLMResult(
            content=content, usage=usage, model_name=resolved_model,
            latency_ms=latency_ms, finish_reason=finish_reason,
        )
    except json.JSONDecodeError:
        # 兼容旧 call_llm 行为：JSON 解析异常返回空内容（不抛出）
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        trace_event(
            "llm_error",
            model_type=model_type,
            model_name=resolved_model,
            error="json_decode",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            latency_ms=latency_ms,
        )
        return LLMResult(content="", usage=None, model_name=resolved_model, latency_ms=latency_ms)
    except Exception as e:
        latency_ms = int((time.perf_counter() - start_ts) * 1000)
        trace_event(
            "llm_error",
            model_type=model_type,
            model_name=resolved_model,
            error=f"{type(e).__name__}: {str(e)[:300]}",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            latency_ms=latency_ms,
        )
        raise
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

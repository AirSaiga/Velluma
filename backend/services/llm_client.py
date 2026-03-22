# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
from typing import Optional
import asyncio

from openai import AsyncOpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    retry_if_exception,
)
import logging

logger = logging.getLogger(__name__)

_default_proxy = "http://127.0.0.1:4780"
PROXY_URL = os.getenv("PROXY_URL", _default_proxy)
if not PROXY_URL:
    PROXY_URL = None

_proxy_config = {
    "enabled": True,
    "url": PROXY_URL
}


def get_proxy_config() -> dict:
    """获取当前代理配置"""
    return _proxy_config


def set_proxy_config(enabled: bool, url: str):
    """设置代理配置"""
    _proxy_config["enabled"] = enabled
    _proxy_config["url"] = url


def _get_active_proxy() -> Optional[str]:
    """获取当前生效的代理地址，如果未启用代理则返回 None"""
    if not _proxy_config.get("enabled", True):
        return None
    url = _proxy_config.get("url")
    if not url:
        return None
    return url


def _clear_proxy_env():
    """
    清除代理环境变量，防止企业内网环境下调用 LLM API 时被代理干扰。

    副作用：修改进程级环境变量，影响全局 HTTP 行为。
    权衡：生产环境应使用配置管理而非运行时清理。
    """
    for env_var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        if env_var in os.environ:
            del os.environ[env_var]


def _should_retry_exception(exception: Exception) -> bool:
    from openai import APIConnectionError, RateLimitError, InternalServerError, APIStatusError
    
    if isinstance(exception, (APIConnectionError, RateLimitError, InternalServerError)):
        return True
    if isinstance(exception, APIStatusError):
        # Retry on 5xx errors
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
    """
    带有重试机制的 OpenAI Chat Completion 创建函数。
    仅重试网络错误、限流和 5xx 服务器错误。
    """
    return await client.chat.completions.create(**kwargs)


async def generate_stream_response(system_prompt: str, user_prompt: str, api_key: str, base_url: Optional[str], model: str, max_tokens: int = 8192, reasoning_config: Optional[dict] = None):
    """
    流式响应生成器，用于 SSE (Server-Sent Events) 实时输出 LLM 推理结果。

    数据流：
    - 输入：system_prompt (角色定义) + user_prompt (用户输入) → LLM API
    - 输出：SSE 格式的 data 帧，逐块yield给前端

    关键设计点：
    1. 首帧发送完整 prompt (用于前端调试/展示)
    2. 末尾发送 done=true 标记结束
    3. 异常时发送 error 帧但不中断流，确保前端能收到终止信号
    4. 支持 reasoning_config 参数传递给 OpenRouter 推理模型

    性能考量：httpx.AsyncClient 手动管理而非全局复用，避免连接泄漏。
    """
    import httpx

    # _clear_proxy_env()
    # 首帧：输出 prompt 供前端调试
    yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
    http_client = None
    try:
        # 构建客户端：支持自定义 base_url (兼容 OpenAI 兼容 API)
        client_kwargs = {"api_key": api_key}
        if base_url:
            # 移除末尾的斜杠以避免双重斜杠问题，这是常见的 API 兼容性陷阱
            client_kwargs["base_url"] = base_url.rstrip("/")
        http_client = httpx.AsyncClient(trust_env=False, proxy=_get_active_proxy(), timeout=600.0)
        client_kwargs["http_client"] = http_client
        client = AsyncOpenAI(**client_kwargs)
        
        # 构建调用参数
        create_kwargs = {
            "model": model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "stream": True,
            "temperature": 0.7,
            "max_tokens": max_tokens,
        }
        
        # reasoning_config 支持 OpenRouter 推理模式
        if reasoning_config:
            create_kwargs["extra_body"] = reasoning_config
        
        # 流式调用
        stream = await _create_chat_completion(client=client, **create_kwargs)
        # 逐块转发 LLM 输出，保持实时性
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
        # 正常结束标记
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    except Exception as e:
        # 异常聚合：提取多种错误信息供调试，截断过长响应防止 SSE 帧溢出
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
        # 发送错误帧后仍发送 done 帧，确保前端不会无限等待
        yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    finally:
        # 显式关闭 HTTP 客户端，释放连接池资源
        if http_client is not None:
            await http_client.aclose()


async def generate_summary(
    text: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "google/gemini-2.0-flash-001",
) -> str:
    """
    生成章节摘要。
    """
    import asyncio
    
    system_prompt = "你是一个专业的小说编辑。请为以下章节生成 200 字以内的摘要，概括主要情节和关键伏笔。"
    
    # 简单的指数退避重试 (最多 3 次)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return await call_llm(
                system_prompt=system_prompt,
                user_prompt=text,
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
        except Exception as e:
            if attempt == max_retries - 1:
                logger.error(f"[Summary] Final attempt failed: {e}")
                raise
            wait_time = (2 ** attempt) * 1  # 1s, 2s, 4s
            logger.warning(f"[Summary] Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
            await asyncio.sleep(wait_time)
    return ""


async def format_text_with_llm(
    text: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "google/gemini-2.0-flash-001",
) -> str:
    """
    使用 LLM 智能整理文本格式。
    """
    system_prompt = """你是一个专业的文本编辑助手。你的任务是整理用户提供的文本格式。
具体要求：
1. 智能分段：根据语义和上下文，将过长的段落拆分为合理的短段落，增强阅读体验。
2. 标点修正：修正文中错误或缺失的标点符号。
3. 格式规范：确保段落之间有适当的空行（如果需要），去除多余的空格。
4. 内容保持：绝对不要修改文本的原意、语气或用词，只调整格式和标点。
请直接返回整理后的纯文本，不要使用 Markdown 代码块标记（如 ```），也不要包含任何解释或额外的对话。"""
    
    return await call_llm(
        system_prompt=system_prompt,
        user_prompt=text,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.3, # 低温确保格式稳定
    )


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    temperature: float = 0.7,
    response_format: Optional[dict] = None,
    max_tokens: int = 8192,
    top_p: float = 1.0,
    reasoning_config: Optional[dict] = None,
) -> str:
    """
    同步调用 LLM API 获取完整响应。

    已集成 tenacity 重试策略：
    - 网络错误/5xx 错误：指数退避重试 (2s -> 4s -> ... -> 30s)
    - 4xx 错误 (除 429)：直接抛出
    - JSON 解析失败：返回空字符串 (保持原行为)

    数据流：
    - 输入：prompt + 配置参数 → LLM API
    - 输出：LLM 生成的文本内容

    特殊处理：
    - JSON 解析失败时返回空字符串 (静默失败，供上游处理)
    - response_format 支持强制 JSON 输出 (依赖模型支持)
    - reasoning_config 支持 OpenRouter 推理模式参数传递
    """
    import httpx

    # _clear_proxy_env()
    client_kwargs = {"api_key": api_key}
    if base_url:
        # 移除末尾的斜杠以避免双重斜杠问题
        client_kwargs["base_url"] = base_url.rstrip("/")
    http_client = httpx.AsyncClient(trust_env=False, proxy=_get_active_proxy(), timeout=600.0)
    client_kwargs["http_client"] = http_client
    client = AsyncOpenAI(**client_kwargs)

    try:
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        create_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "top_p": top_p,
        }
        # response_format 强制模型输出结构化 JSON (需要模型支持 json_object 模式)
        if response_format:
            create_kwargs["response_format"] = response_format
        
        # reasoning_config 支持 OpenRouter 推理模式
        # 通过 extra_body 传递，OpenAI SDK 会将其作为额外参数发送
        if reasoning_config:
            create_kwargs["extra_body"] = reasoning_config
        
        response = await _create_chat_completion(client=client, **create_kwargs)
        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content
        return content
    except json.JSONDecodeError:
        # JSON 解析失败返回空字符串，避免上层崩溃
        return ""
    except Exception:
        raise
    finally:
        # 显式关闭，释放连接
        if http_client is not None:
            await http_client.aclose()


async def get_embedding(
    text: str,
    api_key: str = None,
    base_url: Optional[str] = None,
    model: str = "text-embedding-v3",
    timeout: int = 60,
) -> list[float]:
    """
    调用阿里云 DashScope Embedding API 获取文本向量。
    始终从环境变量 DASHSCOPE_API_KEY 读取，不使用前端传入的 api_key。
    """
    import dashscope
    import os
    from dashscope import TextEmbedding

    api_key_to_use = os.getenv("DASHSCOPE_API_KEY")
    if not api_key_to_use:
        # 尝试重新加载环境变量（应对某些极端情况）
        from dotenv import load_dotenv
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ENV_PATH = os.path.join(BASE_DIR, ".env")
        if os.path.exists(ENV_PATH):
            load_dotenv(ENV_PATH)
            api_key_to_use = os.getenv("DASHSCOPE_API_KEY")
            
    if not api_key_to_use:
        logger.error(f"[Embedding] No api key provided. CWD: {os.getcwd()}")
        return []
    
    dashscope.api_key = api_key_to_use

    try:
        response = TextEmbedding.call(
            model=TextEmbedding.Models.text_embedding_v2,
            input=text,
            timeout=timeout
        )

        if response.status_code == 200:
            return response.output['embeddings'][0]['embedding']
        else:
            logger.error(f"[Embedding] Status: {response.status_code}, Message: {response.message}")
            return []
    except Exception as e:
        logger.error(f"[Embedding] {e}")
        return []


async def optimize_selection_with_llm(
    selected_text: str,
    context_before: str,
    context_after: str,
    outline: str,
    user_instruction: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> str:
    """
    使用 LLM 优化选中的文本片段。
    """
    system_prompt = """你是一个专业的小说编辑和写作助手。
你的任务是根据用户的指令，优化选中的文本片段。
请专注于文风、细节描写、情感表达等方面的提升，尽量不要改变原有的剧情走向，除非用户指令中明确要求。

参考信息：
1. 选中文本的前后文（用于保持上下文连贯）。
2. 章节大纲（用于把握整体基调，权重较低）。
3. 用户指令（最重要的优化依据）。

重要规则：
1. 请直接返回优化后的文本，不要包含任何解释、前言或后续。
2. 必须输出完整的优化文本，严禁截断或省略未修改的段落。
3. 如果用户未指定具体修改方向，请默认进行润色，提升文学性。"""

    user_prompt = f"""
【章节大纲】
{outline}

【前文】
{context_before}

【选中文本】
{selected_text}

【后文】
{context_after}

【用户指令】
{user_instruction}

请提供【选中文本】的优化版本：
"""

    return await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.7,
    )

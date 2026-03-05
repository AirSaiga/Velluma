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


async def generate_stream_response(system_prompt: str, user_prompt: str, api_key: str, base_url: Optional[str], model: str, max_tokens: int = 8192):
    """
    流式响应生成器，用于 SSE (Server-Sent Events) 实时输出 LLM 推理结果。

    数据流：
    - 输入：system_prompt (角色定义) + user_prompt (用户输入) → LLM API
    - 输出：SSE 格式的 data 帧，逐块yield给前端

    关键设计点：
    1. 首帧发送完整 prompt (用于前端调试/展示)
    2. 末尾发送 done=true 标记结束
    3. 异常时发送 error 帧但不中断流，确保前端能收到终止信号

    性能考量：httpx.AsyncClient 手动管理而非全局复用，避免连接泄漏。
    """
    import httpx

    _clear_proxy_env()
    # 首帧：输出 prompt 供前端调试
    yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
    http_client = None
    try:
        # 构建客户端：支持自定义 base_url (兼容 OpenAI 兼容 API)
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        # 禁用 httpx 默认代理继承，避免被系统代理截获
        http_client = httpx.AsyncClient(trust_env=False, timeout=600.0)
        client_kwargs["http_client"] = http_client
        client = AsyncOpenAI(**client_kwargs)
        # 流式调用：temperature=0.7 平衡创造力与稳定性，max_tokens 防止无限生成
        stream = await _create_chat_completion(
            client=client,
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            stream=True,
            temperature=0.7,
            max_tokens=max_tokens,
        )
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
                print(f"[Summary Error] Final attempt failed: {e}")
                raise e
            wait_time = (2 ** attempt) * 1  # 1s, 2s, 4s
            print(f"[Summary Warning] Attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
            await asyncio.sleep(wait_time)
    return ""



async def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    temperature: float = 0.7,
    response_format: Optional[dict] = None,
    max_tokens: int = 8192,
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
    """
    import httpx

    _clear_proxy_env()
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    http_client = httpx.AsyncClient(trust_env=False, timeout=600.0)
    client_kwargs["http_client"] = http_client
    try:
        client = AsyncOpenAI(**client_kwargs)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        create_kwargs = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        # response_format 强制模型输出结构化 JSON (需要模型支持 json_object 模式)
        if response_format:
            create_kwargs["response_format"] = response_format
        response = await _create_chat_completion(client=client, **create_kwargs)
        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content
        return content
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        # 静默失败：JSON 解析异常返回空字符串，避免上层崩溃
        if "JSONDecodeError" in error_type or "Expecting value" in error_msg:
            return ""
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
        print(f"[Embedding Error] No api key provided. CWD: {os.getcwd()}")
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
            print(f"[Embedding Error] Status: {response.status_code}, Message: {response.message}")
            return []
    except Exception as e:
        print(f"[Embedding Error] {e}")
        return []


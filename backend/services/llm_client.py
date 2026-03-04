import json
import os
from typing import Optional

from openai import AsyncOpenAI


def _clear_proxy_env():
    for env_var in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        if env_var in os.environ:
            del os.environ[env_var]


async def generate_stream_response(system_prompt: str, user_prompt: str, api_key: str, base_url: Optional[str], model: str):
    import httpx

    _clear_proxy_env()
    yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
    http_client = None
    try:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        http_client = httpx.AsyncClient(trust_env=False)
        client_kwargs["http_client"] = http_client
        client = AsyncOpenAI(**client_kwargs)
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            stream=True,
            temperature=0.7,
            max_tokens=4000,
        )
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
        yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    finally:
        if http_client is not None:
            await http_client.aclose()


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    temperature: float = 0.7,
    response_format: Optional[dict] = None,
) -> str:
    import httpx

    _clear_proxy_env()
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    http_client = httpx.AsyncClient(trust_env=False)
    client_kwargs["http_client"] = http_client
    try:
        client = AsyncOpenAI(**client_kwargs)
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
        create_kwargs = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": 4000}
        if response_format:
            create_kwargs["response_format"] = response_format
        response = await client.chat.completions.create(**create_kwargs)
        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content
        return content
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        if "JSONDecodeError" in error_type or "Expecting value" in error_msg:
            return ""
        raise
    finally:
        await http_client.aclose()

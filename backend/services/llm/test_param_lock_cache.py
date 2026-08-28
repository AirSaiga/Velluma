# Velluma - 采样参数锁自适应 + 进程级缓存 单元测试（纯 mock，不连真实 LLM）
# AGPL-3.0
"""
锁行为对拍（2026-08-28 kimi-k2.6 实测事故驱动的护栏）：

kimi-k2.6/k3 服务端把采样参数锁死（temperature=1、top_p=0.95），显式传
其他值报 400。_create_chat_completion_adaptive 负责解析 "invalid X: only
Y is allowed" 并按锁定值重试；发现即写入 _PARAM_LOCK_CACHE，同一
端点+模型的后续调用预应用锁定值——不再每次都吃两发 400 往返。
"""
import asyncio

import pytest

from backend.services.llm.client import (
    _PARAM_LOCK_CACHE,
    _create_chat_completion_adaptive,
)


class FakeCompletions:
    """按脚本回放的假补全端点：脚本项是 Exception 则抛、是值则返回。"""

    def __init__(self, script):
        self.script = list(script)
        self.received = []

    async def create(self, **kwargs):
        self.received.append(kwargs)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class FakeClient:
    def __init__(self, script, base_url="https://api.moonshot.cn/v1"):
        self.base_url = base_url

        class _Chat:
            completions = FakeCompletions(script)

        self.chat = _Chat()


TEMP_ERR = Exception(
    "Error code: 400 - {'error': {'message': "
    "'invalid temperature: only 1 is allowed for this model', "
    "'type': 'invalid_request_error'}}"
)
TOPP_ERR = Exception(
    "Error code: 400 - {'error': {'message': "
    "'invalid top_p: only 0.95 is allowed for this model', "
    "'type': 'invalid_request_error'}}"
)


@pytest.fixture(autouse=True)
def _clean_cache():
    _PARAM_LOCK_CACHE.clear()
    yield
    _PARAM_LOCK_CACHE.clear()


def test_double_lock_discovered_then_adapted():
    """双锁发现：temperature/top_p 各吃一发 400 后第三次成功，锁入缓存。"""
    client = FakeClient([TEMP_ERR, TOPP_ERR, "OK"])
    result = asyncio.run(_create_chat_completion_adaptive(
        client=client, model="kimi-k2.6", temperature=0.7, top_p=1.0,
    ))
    assert result == "OK"
    assert len(client.chat.completions.received) == 3
    final = client.chat.completions.received[-1]
    assert final["temperature"] == 1.0
    assert final["top_p"] == 0.95
    assert _PARAM_LOCK_CACHE == {
        "https://api.moonshot.cn/v1|kimi-k2.6": {"temperature": 1.0, "top_p": 0.95},
    }


def test_cached_lock_skips_400_roundtrips():
    """缓存命中：后续调用直发锁定值，零 400 往返。"""
    _PARAM_LOCK_CACHE["https://api.moonshot.cn/v1|kimi-k2.6"] = {
        "temperature": 1.0, "top_p": 0.95,
    }
    client = FakeClient(["OK1", "OK2"])
    r1 = asyncio.run(_create_chat_completion_adaptive(
        client=client, model="kimi-k2.6", temperature=0.7, top_p=1.0,
    ))
    r2 = asyncio.run(_create_chat_completion_adaptive(
        client=client, model="kimi-k2.6", temperature=0.3,
    ))
    assert (r1, r2) == ("OK1", "OK2")
    assert len(client.chat.completions.received) == 2  # 每次一发直中，零重试
    for kw in client.chat.completions.received:
        assert kw["temperature"] == 1.0
        assert kw["top_p"] == 0.95


def test_cache_scoped_to_model():
    """缓存按端点+模型隔离：别的模型不受锁污染，参数原样发出。"""
    _PARAM_LOCK_CACHE["https://api.moonshot.cn/v1|kimi-k2.6"] = {
        "temperature": 1.0, "top_p": 0.95,
    }
    client = FakeClient(["OK"])
    asyncio.run(_create_chat_completion_adaptive(
        client=client, model="mimo-v2.5", temperature=0.7,
    ))
    assert client.chat.completions.received[0]["temperature"] == 0.7
    assert "top_p" not in client.chat.completions.received[0]


def test_unrelated_400_still_raises():
    """与参数锁无关的 400 照常上抛（自适应只吞白名单内可解析形态）。"""
    client = FakeClient([Exception("Error code: 400 - model not found")])
    with pytest.raises(Exception, match="model not found"):
        asyncio.run(_create_chat_completion_adaptive(
            client=client, model="kimi-k2.6", temperature=0.7,
        ))
    assert _PARAM_LOCK_CACHE == {}

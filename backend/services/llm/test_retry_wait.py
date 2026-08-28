# Velluma - 429 重试等待策略 单元测试（纯算法，不连真实 LLM）
# AGPL-3.0
"""
背景（2026-08-28 Kimi Tier0 限流实测）：429 文案明说「please try again
after 1 seconds」，指数退避却排到 16 秒——白等还挤占停顿组件 12s 超时。
_wait_with_retry_after 优先按服务端提示（Retry-After 头 / 文案）+ 20% 余量，
钳 1~30s；无提示的错误回落指数退避。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from backend.services.llm.client import _parse_retry_after_hint, _wait_with_retry_after


class _Resp:
    def __init__(self, headers: dict):
        self.headers = headers


class _Outcome:
    def __init__(self, exc):
        self._exc = exc

    def exception(self):
        return self._exc


class _State:
    """tenacity RetryCallState 的鸭子替身（wait 回调只读 outcome + attempt_number）。"""

    def __init__(self, exc, attempt_number: int = 1):
        self.outcome = _Outcome(exc)
        self.attempt_number = attempt_number


RATE_LIMIT_MSG = (
    "Error code: 429 - {'error': {'message': 'Your account ... request reached "
    "organization max RPM: 3, please try again after 1 seconds', "
    "'type': 'rate_limit_reached_error'}}"
)


def test_parse_from_message():
    assert _parse_retry_after_hint(Exception(RATE_LIMIT_MSG)) == 1.0


def test_parse_from_retry_after_header():
    class _Exc(Exception):
        response = _Resp({"retry-after": "7"})

    assert _parse_retry_after_hint(_Exc("Error code: 429")) == 7.0


def test_parse_none_when_no_hint():
    assert _parse_retry_after_hint(Exception("Error code: 500 - boom")) is None


def test_wait_honors_server_hint():
    """文案提示 1s → 等 1*1.2+0.5=1.7s（不是指数序列的 16s）。"""
    assert _wait_with_retry_after(_State(Exception(RATE_LIMIT_MSG))) == 1.7


def test_wait_clamps_tiny_hint_to_floor():
    assert _wait_with_retry_after(_State(Exception("... try again after 0.1 seconds"))) == 1.0


def test_wait_falls_back_to_exponential_without_hint():
    state = _State(Exception("connection error"))
    # 无提示：与旧策略一致的指数序列（首试 min=2）
    assert _wait_with_retry_after(state) == 2

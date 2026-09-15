# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""本地端点连接错误快速失败（2026-09-15 槽位治理）。

背景（logs/dev_backend.log 实证）：分析槽指到本地 Ollama 后服务退出，
每次 Tab 重算烧满 5 连指数退避（2/4/8/16s ≈30s）才报错——本地端点连接
失败≈「服务没启动」，30 秒内不会自愈，重试纯属浪费。改动后 localhost/
127.0.0.1/::1 的 APIConnectionError 不再重试（远端保持重试——瞬时网络
抖动真实存在）。
"""
import httpx
import pytest
from openai import APIConnectionError

from backend.services.llm.client import _should_retry_exception


def _conn_error(url: str) -> APIConnectionError:
    return APIConnectionError(
        message="Connection error.", request=httpx.Request("POST", url)
    )


class TestLocalEndpointFastFail:
    def test_localhost_not_retried(self):
        assert _should_retry_exception(
            _conn_error("http://localhost:11434/v1/chat/completions")
        ) is False

    def test_loopback_ipv4_not_retried(self):
        assert _should_retry_exception(
            _conn_error("http://127.0.0.1:11434/v1/chat/completions")
        ) is False

    def test_loopback_ipv6_not_retried(self):
        assert _should_retry_exception(
            _conn_error("http://[::1]:11434/v1/chat/completions")
        ) is False

    def test_remote_connection_error_still_retried(self):
        # 远端连接错误可能是瞬时网络抖动——重试语义不变
        assert _should_retry_exception(
            _conn_error("https://api.deepseek.com/v1/chat/completions")
        ) is True

    def test_remote_lan_ip_still_retried(self):
        # 局域网地址（非环回）：保守起见仍走重试（可能是 NAS 网关自愈场景）
        assert _should_retry_exception(
            _conn_error("http://192.168.1.10:8000/v1/chat/completions")
        ) is True

    def test_no_request_attribute_still_retried(self):
        # 异常没带 request（防御分支）：按远端语义重试（宁可多试不可错杀）
        from types import SimpleNamespace
        from backend.services.llm.client import _is_local_endpoint_exception

        assert _is_local_endpoint_exception(SimpleNamespace()) is False
        assert _is_local_endpoint_exception(
            SimpleNamespace(request=SimpleNamespace(url=httpx.URL("https://api.deepseek.com/v1")))
        ) is False

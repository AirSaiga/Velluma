# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""
workflows 测试目录共享 fixture。

职责：修复异步测试间的事件循环污染
业务场景：IsolatedAsyncioTestCase（adf/test_beat_patcher.py、
         test_consistency_guard.py 等）与 asyncio.run 会在收尾时把事件循环
         策略的 _set_called 置位且 current loop 置空，导致同进程后续测试里
         asyncio.get_event_loop() 抛 RuntimeError（典型受害者：
         bsadf/test_downgrade.py、test_slot_builder.py）。
主要功能：每个测试结束后重置一个全新的 current event loop，
         恢复 get_event_loop() 的默认语义。
依赖项：pytest、asyncio
"""

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _restore_event_loop():
    yield
    asyncio.set_event_loop(asyncio.new_event_loop())

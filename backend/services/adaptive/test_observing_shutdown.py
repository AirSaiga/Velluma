# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - adaptive 观测层停机冲账单测（02 候选回流修缮 P2a）
"""flush_all_adaptive_records / atexit 兜底的行为契约：

- 全量冲账遍历所有章节 recorder，逐章调用 flush_adaptive_records
- 单章失败不连坐其余（防御分支：停机路径绝不因一章炸掉丢掉其他章的账）
- atexit 包装吞异常（解释器收尾阶段任何环节都可能掉，只留日志不崩）

落库行为本身（drain/落库/失败塞回）由既有 test_observing_records 类锁；
此处只锁停机编排。运行：
python -m pytest backend/services/adaptive/test_observing_shutdown.py -v
"""

import asyncio
from unittest.mock import AsyncMock

import backend.services.adaptive.observing as obs


def test_flush_all_iterates_all_recorders(monkeypatch):
    orig = dict(obs._RECORDERS)
    try:
        obs._RECORDERS.clear()
        obs._RECORDERS["ch-1"] = object()
        obs._RECORDERS["ch-2"] = object()
        flush = AsyncMock(return_value=3)
        monkeypatch.setattr(obs, "flush_adaptive_records", flush)

        total = asyncio.run(obs.flush_all_adaptive_records())

        assert total == 6  # 2 章 × 3 条
        assert flush.await_count == 2
        assert {c.args[0] for c in flush.await_args_list} == {"ch-1", "ch-2"}
    finally:
        obs._RECORDERS.clear()
        obs._RECORDERS.update(orig)


def test_flush_all_single_failure_does_not_block_rest(monkeypatch):
    """第一章炸掉不影响第二章冲账——停机路径的防御纪律。"""
    orig = dict(obs._RECORDERS)
    try:
        obs._RECORDERS.clear()
        obs._RECORDERS["bad"] = object()
        obs._RECORDERS["good"] = object()
        flush = AsyncMock(side_effect=[RuntimeError("db gone"), 2])
        monkeypatch.setattr(obs, "flush_adaptive_records", flush)

        total = asyncio.run(obs.flush_all_adaptive_records())

        assert total == 2
        assert flush.await_count == 2
    finally:
        obs._RECORDERS.clear()
        obs._RECORDERS.update(orig)


def test_atexit_wrapper_swallows_exceptions(monkeypatch):
    """atexit 包装绝不向上抛（解释器收尾崩栈比丢账更糟）。"""

    async def _boom():
        raise RuntimeError("teardown")

    monkeypatch.setattr(obs, "flush_all_adaptive_records", _boom)
    obs._flush_all_atexit()  # 不抛即通过

"""BS-ADF 状态卡抽取降级的可观测性测试（mock LLM / mock extract）。

真实事故：5 次状态卡抽取全部空输出，失败静默无 degraded 记录，
Loop 1 状态矛盾闸门整章裸奔。修复后：空输出/废卡/异常都必须
保留旧卡 + 显式记 result.degraded（phase=state_tracker，含段号）。
"""
# Velluma - BS-ADF state card degraded tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.workflows.adf.state_tracker import SceneStateCard
from backend.services.workflows.bsadf.bsadf_workflow import (
    _extract_state_card_or_keep_old,
)

_EXTRACT = "backend.services.workflows.bsadf.bsadf_workflow.extract_state_card"


def _run(coro):
    """用独立 event loop 跑异步（不用 asyncio.run——它会把事件循环策略的
    _set_called 置位，导致同进程后续测试的 asyncio.get_event_loop() 抛
    RuntimeError，详见 bsadf/dde/test_decision_set.py 的同款注释）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_result():
    return SimpleNamespace(degraded=[])


class TestExtractStateCardOrKeepOld:
    def test_fallback_same_object_records_degraded(self):
        """extract 内部降级返回同一旧卡对象 → 记 degraded，保留旧卡。"""
        old = SceneStateCard(pov="林尘", present=["林尘"])
        result = _make_result()

        with patch(_EXTRACT, new=AsyncMock(return_value=old)):
            new_card = _run(_extract_state_card_or_keep_old(
                old, "他推开舱门。", None, None, 2, result,
            ))

        assert new_card is old
        assert len(result.degraded) == 1
        d = result.degraded[0]
        assert d["phase"] == "state_tracker"
        assert d["reason"] == "extract_empty"
        assert d["segment_index"] == 2  # 段号必须可查

    def test_empty_junk_card_records_degraded(self):
        """extract 返回全空废卡 → 不替换旧卡，记 degraded。"""
        old = SceneStateCard(pov="林尘", present=["林尘"])
        result = _make_result()

        with patch(_EXTRACT, new=AsyncMock(return_value=SceneStateCard())):
            new_card = _run(_extract_state_card_or_keep_old(
                old, "他推开舱门。", None, None, 0, result,
            ))

        assert new_card is old
        assert result.degraded[0]["reason"] == "extract_empty"

    def test_success_replaces_card_no_degraded(self):
        """抽取成功（非空新卡）→ 用新卡，无 degraded。"""
        old = SceneStateCard()
        new_card = SceneStateCard(pov="林尘", present=["林尘"])
        result = _make_result()

        with patch(_EXTRACT, new=AsyncMock(return_value=new_card)):
            out = _run(_extract_state_card_or_keep_old(
                old, "他推开舱门。", None, None, 0, result,
            ))

        assert out is new_card
        assert result.degraded == []

    def test_exception_records_degraded(self):
        """extract 抛异常 → 不阻塞，记 degraded（extract_exception）。"""
        old = SceneStateCard(pov="林尘")
        result = _make_result()

        with patch(_EXTRACT, new=AsyncMock(side_effect=RuntimeError("boom"))):
            new_card = _run(_extract_state_card_or_keep_old(
                old, "他推开舱门。", None, None, 1, result,
            ))

        assert new_card is old
        d = result.degraded[0]
        assert d["phase"] == "state_tracker"
        assert d["reason"] == "extract_exception"
        assert d["segment_index"] == 1

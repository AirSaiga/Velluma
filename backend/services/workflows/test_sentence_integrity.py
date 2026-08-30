# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""sentence_integrity 单测：残句扫描（高精确度正则）+ 定点修复流程（mock LLM）。

真实残句必须命中："但演习的警报是的、急促的"（缺中心语）、"白霆的了一下"
（缺动词）；正常中文句子必须零误报（宁漏勿误）。
"""
# Velluma - sentence_integrity tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.services.llm.client import REASONING_DISABLED
from backend.services.workflows.sentence_integrity import (
    MAX_SENTENCE_REPAIRS,
    repair_sentence_defects,
    scan_sentence_defects,
)

_LLM = "backend.services.workflows.sentence_integrity.call_llm_with_usage"


def _run(coro):
    """用独立 event loop 跑异步（不用 asyncio.run——它会把事件循环策略的
    _set_called 置位，导致同进程后续测试的 asyncio.get_event_loop() 抛
    RuntimeError，典型症状是 test_downgrade 在本文件之后运行时报错）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestScanner:
    def test_real_defect_missing_head_noun(self):
        """真实残句："但演习的警报是的、急促的"（缺中心语）必须命中。"""
        text = "演习开始了。但演习的警报是的、急促的。所有人都愣住了。"
        defects = scan_sentence_defects(text)
        assert len(defects) == 1
        d = defects[0]
        assert d["type"] == "missing_head_noun"
        assert d["sentence"] == "但演习的警报是的、急促的。"
        # position 必须指向原文精确子串（修复替换依赖它）
        assert text[d["position"]:d["position"] + len(d["sentence"])] == d["sentence"]

    def test_real_defect_missing_verb(self):
        """真实残句："白霆的了一下"（缺动词）必须命中。"""
        text = "白霆的了一下，舱门纹丝不动。"
        defects = scan_sentence_defects(text)
        assert len(defects) == 1
        assert defects[0]["type"] == "missing_verb"
        assert defects[0]["position"] == 0

    def test_dangling_auxiliary(self):
        """句末悬空"得/地"（"他猛推得。"）命中；"好的。"不命中。"""
        defects = scan_sentence_defects("他猛推得。")
        assert len(defects) == 1
        assert defects[0]["type"] == "dangling_auxiliary"
        assert scan_sentence_defects("好的。") == []

    def test_legal_sentences_zero_false_positives(self):
        """一批合法句必须零误报。"""
        legal = (
            "他笑了一下。好的。我的心是热的、真诚的。飞快地跑。"
            "他猛地推开锈住的舱门。警报声是急促的、尖锐的。"
            "目的、手段都写在纸上。他高兴得跳了起来。她慢慢地走了。"
        )
        assert scan_sentence_defects(legal) == []

    def test_empty_and_clean_text(self):
        assert scan_sentence_defects("") == []
        assert scan_sentence_defects("一切正常。没有残句。") == []

    def test_multiple_defects_across_paragraphs(self):
        """跨段落命中多条，且句跨度不吃换行（防替换吃掉段落分隔）。"""
        text = "他猛推得。\n\n白霆的了一下。"
        defects = scan_sentence_defects(text)
        assert len(defects) == 2
        assert all("\n" not in d["sentence"] for d in defects)
        for d in defects:
            assert text[d["position"]:d["position"] + len(d["sentence"])] == d["sentence"]


class TestRepairFlow:
    def test_fix_success_replaces(self):
        """修复成功：原句被替换，fixed=1，无失败。"""
        text = "演习开始了。但演习的警报是的、急促的。所有人都愣住了。"
        defects = scan_sentence_defects(text)
        mock_result = SimpleNamespace(content="但演习的警报是尖锐的、急促的。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)):
            new_text, fixed, failures = _run(repair_sentence_defects(text, defects))

        assert fixed == 1
        assert failures == []
        assert "但演习的警报是尖锐的、急促的。" in new_text
        assert "警报是的、" not in new_text
        # 上下文不动
        assert "演习开始了。" in new_text and "所有人都愣住了。" in new_text

    def test_fix_with_new_defect_rolled_back(self):
        """修复句仍命中缺陷模式 → 回滚保留原句，记失败。"""
        text = "白霆的了一下，舱门纹丝不动。"
        defects = scan_sentence_defects(text)
        mock_result = SimpleNamespace(content="白霆的了一下。")  # 照样残缺

        with patch(_LLM, new=AsyncMock(return_value=mock_result)):
            new_text, fixed, failures = _run(repair_sentence_defects(text, defects))

        assert new_text == text
        assert fixed == 0
        assert len(failures) == 1
        assert failures[0]["reason"] == "still_defective"

    def test_fix_length_out_of_bounds_rolled_back(self):
        """修复句长度超界（>2.0 倍）→ 回滚。"""
        text = "白霆的了一下，舱门纹丝不动。"  # 14 字，上限 28
        defects = scan_sentence_defects(text)
        mock_result = SimpleNamespace(content="白霆" + "踉跄了一下，" * 5 + "舱门纹丝不动。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)):
            new_text, fixed, failures = _run(repair_sentence_defects(text, defects))

        assert new_text == text
        assert fixed == 0
        assert failures[0]["reason"] == "length_out_of_bounds"

    def test_fix_drops_registered_name_rolled_back(self):
        """修复句删除原句中的注册专名 → 回滚。"""
        text = "白霆的了一下，舱门纹丝不动。"
        defects = scan_sentence_defects(text)
        mock_result = SimpleNamespace(content="他踉跄了一下，舱门纹丝不动。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)):
            new_text, fixed, failures = _run(repair_sentence_defects(
                text, defects, registered_names=["白霆"],
            ))

        assert new_text == text
        assert fixed == 0
        assert failures[0]["reason"] == "name_dropped"

    def test_fix_keeps_registered_name_accepted(self):
        """修复句保留注册专名 → 采纳。"""
        text = "白霆的了一下，舱门纹丝不动。"
        defects = scan_sentence_defects(text)
        mock_result = SimpleNamespace(content="白霆踉跄了一下，舱门纹丝不动。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)):
            new_text, fixed, failures = _run(repair_sentence_defects(
                text, defects, registered_names=["白霆"],
            ))

        assert fixed == 1
        assert failures == []
        assert "白霆踉跄了一下" in new_text

    def test_llm_error_recorded_as_failure(self):
        text = "白霆的了一下，舱门纹丝不动。"
        defects = scan_sentence_defects(text)

        with patch(_LLM, new=AsyncMock(side_effect=RuntimeError("boom"))):
            new_text, fixed, failures = _run(repair_sentence_defects(text, defects))

        assert new_text == text
        assert fixed == 0
        assert failures[0]["reason"] == "llm_error"

    def test_repair_cap_bounds_llm_calls(self):
        """超过 MAX_SENTENCE_REPAIRS 的缺陷不触发 LLM 调用，记 repair_cap。"""
        text = "。".join(f"他{i}猛推得" for i in range(MAX_SENTENCE_REPAIRS + 2)) + "。"
        defects = scan_sentence_defects(text)
        assert len(defects) == MAX_SENTENCE_REPAIRS + 2
        mock_result = SimpleNamespace(content="他用力推门。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)) as mock_llm:
            _new_text, fixed, failures = _run(repair_sentence_defects(text, defects))

        assert mock_llm.call_count == MAX_SENTENCE_REPAIRS
        assert fixed == MAX_SENTENCE_REPAIRS
        assert len(failures) == 2
        assert all(f["reason"] == "repair_cap" for f in failures)

    def test_llm_called_with_reasoning_disabled_and_budget(self):
        """关 thinking 必须显式传 REASONING_DISABLED，max_tokens ≥1600。"""
        text = "白霆的了一下，舱门纹丝不动。"
        defects = scan_sentence_defects(text)
        mock_result = SimpleNamespace(content="白霆踉跄了一下，舱门纹丝不动。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)) as mock_llm:
            _run(repair_sentence_defects(text, defects))

        kwargs = mock_llm.call_args.kwargs
        assert kwargs["reasoning_config"] == REASONING_DISABLED
        assert kwargs["max_tokens"] >= 1600

    def test_multiple_defects_positions_stay_valid(self):
        """多条缺陷替换后偏移不错位（倒序替换）。"""
        text = "他猛推得。白霆的了一下。"
        defects = scan_sentence_defects(text)
        assert len(defects) == 2
        mock_result = SimpleNamespace(content="他用力推门。")

        with patch(_LLM, new=AsyncMock(return_value=mock_result)):
            new_text, fixed, failures = _run(repair_sentence_defects(text, defects))

        assert fixed == 2
        assert failures == []
        assert new_text == "他用力推门。他用力推门。"

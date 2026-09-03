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



# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""手术执行单测——services/text_surgery/surgeon.py。

- apply_surgeries_to_text：纯函数（段落应用层——首段替换/多段拆填/
  applied=False 跳过/空段过滤/不改原 list）；
- execute_surgery 边界分支：LLM 全 mock——空章节无目标段、LLM 失败保原文、
  LLM 返回空保原文、成功路径带 target_indices。

在役消费方：ADF 一致性守卫（stage_prefix="adf.consistency_surgery"）。
"""

from types import SimpleNamespace

import pytest

import backend.services.text_surgery.surgeon as surgeon_mod
from backend.services.text_surgery.surgeon import (
    MAX_TARGET_PARAGRAPHS,
    apply_surgeries_to_text,
    execute_surgery,
)


class TestApplySurgeriesToText:
    def test_empty_paragraphs(self):
        assert apply_surgeries_to_text([], [{"applied": True, "target_indices": [0], "revised_text": "x"}]) == []

    def test_not_applied_skipped(self):
        paras = ["甲", "乙"]
        surgeries = [{"applied": False, "target_indices": [0], "revised_text": "改"}]
        assert apply_surgeries_to_text(paras, surgeries) == ["甲", "乙"]

    def test_single_paragraph_replaced(self):
        paras = ["甲", "乙", "丙"]
        surgeries = [{"applied": True, "target_indices": [1], "revised_text": "乙改"}]
        out = apply_surgeries_to_text(paras, surgeries)
        assert out == ["甲", "乙改", "丙"]

    def test_multi_paragraph_merge_fills_by_chunk(self):
        # 合并手术：revised 含两段 → 按段拆开逐段填入目标位
        paras = ["甲", "乙", "丙", "丁"]
        surgeries = [{
            "applied": True,
            "target_indices": [1, 2],
            "revised_text": "合并后第一段。\n\n合并后第二段。",
        }]
        out = apply_surgeries_to_text(paras, surgeries)
        assert out == ["甲", "合并后第一段。", "合并后第二段。", "丁"]

    def test_fewer_chunks_blank_out_extras(self):
        # revised 只有一段但目标两段 → 第二段清空（join 时自然消除）
        paras = ["甲", "乙", "丙"]
        surgeries = [{
            "applied": True,
            "target_indices": [1, 2],
            "revised_text": "合并成一段。",
        }]
        out = apply_surgeries_to_text(paras, surgeries)
        assert out == ["甲", "合并成一段。"]

    def test_original_list_untouched(self):
        paras = ["甲", "乙"]
        surgeries = [{"applied": True, "target_indices": [0], "revised_text": "改"}]
        apply_surgeries_to_text(paras, surgeries)
        assert paras == ["甲", "乙"]

    def test_out_of_range_index_ignored(self):
        paras = ["甲"]
        surgeries = [{"applied": True, "target_indices": [5], "revised_text": "改"}]
        assert apply_surgeries_to_text(paras, surgeries) == ["甲"]


class TestExecuteSurgeryBranches:
    @pytest.mark.asyncio
    async def test_no_target_and_empty_chapter(self):
        result = await execute_surgery({"id": "OP001"}, [])
        assert result["applied"] is False
        assert result["diff_summary"] == "无目标段"

    @pytest.mark.asyncio
    async def test_no_target_defaults_to_last_paragraph(self, monkeypatch):
        # 全局问题（weak_hook）无目标段 → 默认取最后一段
        captured = {}

        async def fake_llm(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content="改写后的章末段。")

        monkeypatch.setattr(surgeon_mod, "call_llm_with_usage", fake_llm)
        operation = {"id": "OP001", "target_paragraphs": [], "issues": [], "operation_type": "insert"}
        result = await execute_surgery(operation, ["第一段。", "第二段。", "章末段。"])
        assert result["applied"] is True
        assert result["target_indices"] == [2]

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_original(self, monkeypatch):
        async def fake_llm(**kwargs):
            raise RuntimeError("模型不可用")

        monkeypatch.setattr(surgeon_mod, "call_llm_with_usage", fake_llm)
        operation = {"id": "OP001", "target_paragraphs": [0], "issues": [], "operation_type": "rewrite"}
        result = await execute_surgery(operation, ["原文段。"])
        assert result["applied"] is False
        assert result["original_text"] == "原文段。"
        assert result["revised_text"] == "原文段。"

    @pytest.mark.asyncio
    async def test_llm_empty_output_keeps_original(self, monkeypatch):
        async def fake_llm(**kwargs):
            return SimpleNamespace(content="  ")

        monkeypatch.setattr(surgeon_mod, "call_llm_with_usage", fake_llm)
        operation = {"id": "OP001", "target_paragraphs": [0], "issues": [], "operation_type": "rewrite"}
        result = await execute_surgery(operation, ["原文段。"])
        assert result["applied"] is False
        assert result["revised_text"] == "原文段。"

    @pytest.mark.asyncio
    async def test_success_returns_revised(self, monkeypatch):
        async def fake_llm(**kwargs):
            return SimpleNamespace(content="修订后的段落。")

        monkeypatch.setattr(surgeon_mod, "call_llm_with_usage", fake_llm)
        operation = {
            "id": "OP002",
            "target_paragraphs": [1],
            "issues": [{"id": "I1", "description": "前后矛盾"}],
            "operation_type": "rewrite",
        }
        result = await execute_surgery(operation, ["第一段。", "第二段。"])
        assert result["applied"] is True
        assert result["revised_text"] == "修订后的段落。"
        assert result["target_indices"] == [1]
        assert "原文 4 字" in result["diff_summary"]

    @pytest.mark.asyncio
    async def test_target_paragraphs_capped(self, monkeypatch):
        captured = {}

        async def fake_llm(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content="改。")

        monkeypatch.setattr(surgeon_mod, "call_llm_with_usage", fake_llm)
        too_many = list(range(20))
        operation = {"id": "OP001", "target_paragraphs": too_many, "issues": [], "operation_type": "merge"}
        result = await execute_surgery(operation, [f"段{i}。" for i in range(20)])
        assert len(result["target_indices"]) == MAX_TARGET_PARAGRAPHS

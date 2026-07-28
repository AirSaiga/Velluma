# Velluma - Loop 3 Memory Ingestion Tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.
"""Loop 3 记忆倒灌单元测试。"""

import pytest
from unittest.mock import AsyncMock, patch

from backend.services.workflows.bsadf.memory_ingestion import extract_emergent_facts
from backend.services.workflows.bsadf.types import EmergentFacts


def test_emergent_facts_empty():
    facts = EmergentFacts()
    assert facts.is_empty() is True


def test_emergent_facts_non_empty():
    facts = EmergentFacts(new_entities=[{"name": "血噬", "type": "item"}])
    assert facts.is_empty() is False


def test_emergent_facts_to_dict():
    facts = EmergentFacts(
        new_entities=[{"name": "血噬"}],
        relationship_changes=[{"from": "林尘", "to": "白霆", "change": "敌对"}],
    )
    d = facts.to_dict()
    assert "new_entities" in d
    assert "relationship_changes" in d
    assert "new_locations" in d
    assert "outline_addenda" in d


@pytest.mark.asyncio
async def test_extract_emergent_facts_parses_llm_json():
    fake_resp = '{"new_entities":[{"name":"血噬","type":"item","description":"共生体武器"}],"relationship_changes":[],"new_locations":[],"outline_addenda":[]}'
    with patch(
        "backend.services.workflows.bsadf.memory_ingestion.call_llm_with_usage",
        new=AsyncMock(return_value=(fake_resp, {"total_tokens": 100})),
    ):
        facts = await extract_emergent_facts(
            segment_text="林尘与血噬完成了融合。",
            beat_id="B01",
            prev_state_summary="",
        )
    assert len(facts.new_entities) == 1
    assert facts.new_entities[0]["name"] == "血噬"


@pytest.mark.asyncio
async def test_extract_emergent_facts_failure_returns_empty():
    with patch(
        "backend.services.workflows.bsadf.memory_ingestion.call_llm_with_usage",
        new=AsyncMock(side_effect=Exception("network error")),
    ):
        facts = await extract_emergent_facts("正文", "B01", "")
    assert facts.is_empty() is True

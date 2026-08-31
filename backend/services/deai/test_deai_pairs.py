# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""deai 训练对收集账本单测（临时文件，零网络零 DB）。

配方：monkeypatch DEAI_PAIRS_FILE 到 tmp_path——账本真实路径是运行时
data/ 目录，测试绝不触碰。
"""
from __future__ import annotations

import json

import pytest

from backend.services.deai import pairs as deai_pairs
from backend.services.deai.pairs import (
    PairValidationError,
    count_pairs,
    delete_pair,
    save_pair,
)


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "deai_pairs.jsonl"
    monkeypatch.setattr(deai_pairs, "DEAI_PAIRS_FILE", str(path))
    return path


BAD = "综上所述，本次改版显著提升了页面加载速度，为后续增长夯实了基础。"
GOOD = "这轮改版后，页面加载快了不少，后面的增长也有底了。"


def test_save_and_count_roundtrip(ledger):
    r = save_pair(BAD, GOOD, book_id="bk1", chapter_id="ch1")
    assert r["total"] == 1 and r["id"].startswith("m")
    save_pair(BAD, GOOD)
    assert count_pairs() == 2
    # 行格式与 validate_pairs.parse_input 契约逐字兼容
    lines = ledger.read_text(encoding="utf-8").strip().splitlines()
    obj = json.loads(lines[0])
    assert set(obj.keys()) >= {"id", "bad", "good", "meta"}
    assert obj["bad"] == BAD and obj["good"] == GOOD
    assert isinstance(obj["meta"], dict) and obj["meta"]["source"] == "manual_mark"


def test_save_rejects_empty(ledger):
    with pytest.raises(PairValidationError):
        save_pair("", GOOD)
    with pytest.raises(PairValidationError):
        save_pair(BAD, "   ")


def test_save_rejects_over_100_bad(ledger):
    with pytest.raises(PairValidationError, match="100"):
        save_pair("字" * 101, "好" * 10)


def test_save_rejects_absurd_good(ledger):
    with pytest.raises(PairValidationError, match="异常"):
        save_pair(BAD, "好" * 601)


def test_delete_pair_removes_only_target(ledger):
    r1 = save_pair(BAD, GOOD)
    r2 = save_pair("另一段原文。", "另一段改后。")
    assert delete_pair(r1["id"]) is True
    assert count_pairs() == 1
    remaining = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert remaining["id"] == r2["id"]
    assert delete_pair(r1["id"]) is False  # 再删同名 = 不存在


def test_corrupt_line_does_not_kill_ledger(ledger):
    save_pair(BAD, GOOD)
    with ledger.open("a", encoding="utf-8") as f:
        f.write("{broken json\n")
    save_pair("又一段。", "再改一段。")
    assert count_pairs() == 2  # 损坏行跳过，不炸账本

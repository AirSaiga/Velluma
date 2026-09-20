# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 完稿审阅窗口 + 世界发现跳过原因单测（P3 治理，2026-08-25）
"""docs/reports/adaptive-assist-hardening.md P3 · C3/C6 的对拍：

- P3-3（C3）finish critique 首尾截取：_critique_text_window 首 3000 + 尾 3000
  拼接（中间省略记号），短于 6000 逐字节零变化；
- P3-4（C6）event_scout 跳过原因：no_chapter / short_text / no_entities
  三道前置闸返回 {created: 0, skipped: {code, reason}}（机器短码 + 人话一句）。

配方同 test_projection_freshness.py：独立 asyncio.run、UUID 带字母、
monkeypatch event_scout.WorldRepository（模块顶层 import，patch 模块属性即生效）。
运行：python -m pytest backend/services/adaptive/test_critique_and_scout.py -v
"""

import asyncio
import uuid

from backend.services.world import event_scout as es

CH_ID = str(uuid.UUID("bb270000-0000-4000-8000-0000000000c1"))


# ============================================================
# P3-3（C3）：_critique_text_window 首尾截取
# ============================================================

def test_critique_window_short_text_unchanged():
    """短文本（≤6000）原样返回——逐字节零变化，不插省略记号。"""
    from backend.services.adaptive.components.post_process import _critique_text_window

    text = "丙" * 6000
    assert _critique_text_window(text) == text          # 恰好 6000：边界内
    short = "一章短短的正文。"
    assert _critique_text_window(short) is short


def test_critique_window_head_tail_with_marker():
    """长文本：首 3000 + 尾 3000 + 中间省略记号（含省略字数）。"""
    from backend.services.adaptive.components.post_process import _critique_text_window

    text = ("甲" * 4000) + ("乙" * 4000)                 # 8000 字
    out = _critique_text_window(text)
    assert out.startswith("甲" * 3000)                   # 头保留
    assert out.endswith("乙" * 3000)                     # 尾保留（长章后半进视野）
    assert "省略" in out
    assert "2000" in out                                # 中间省略 8000-6000=2000 字
    assert ("甲" * 3001) not in out                     # 头被截在 3000
    # 中段的甲（3000~4000 位）不再完整出现
    assert ("甲" * 200) not in out[3000:]


# ============================================================
# P3-4（C6）：event_scout 跳过原因
# ============================================================

class _FakeChapter:
    book_id = "b1"

    def __init__(self, content=""):
        self.content_text = content


class _ScoutDB:
    def __init__(self, chapter):
        self._ch = chapter

    async def get(self, model, pk):
        return self._ch


def test_scout_skip_no_chapter():
    result = asyncio.run(es.run(CH_ID, _ScoutDB(None), {}, 1500))
    assert result["created"] == 0
    assert result["skipped"]["code"] == "no_chapter"
    assert result["skipped"]["reason"]                 # 人话一句非空


def test_scout_skip_short_text():
    chapter = _FakeChapter("太短")
    result = asyncio.run(es.run(
        CH_ID, _ScoutDB(chapter), {}, 1500, source="settle", text="十二个字而已",
    ))
    assert result["skipped"]["code"] == "short_text"


def test_scout_skip_no_entities(monkeypatch):
    class _EmptyLister:
        async def list_by_book(self, book_id):
            return []

    class _Repo:
        def __init__(self, db):
            self.entities = _EmptyLister()

    monkeypatch.setattr(es, "WorldRepository", _Repo)
    chapter = _FakeChapter("足够长的正文" * 10)
    result = asyncio.run(es.run(CH_ID, _ScoutDB(chapter), {}, 1500))
    assert result["skipped"]["code"] == "no_entities"
    assert "角色" in result["skipped"]["reason"]        # 作者语言：建角色提示

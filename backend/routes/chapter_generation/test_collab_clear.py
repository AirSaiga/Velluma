# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""清空本书协作埋点端点单测（测试用 DELETE，2026-09-11）。

覆盖：
- 只删本书事件，他书保留；当前份 + 轮转 .1 两份都重写
- 损坏行（非 JSON）原样保留
- 「学着闭嘴」两级派生缓存（hint 扫描 + 静音集）即时失效
- 路由注册（防手滑 404；端点挂 usage 路由=前缀 /api，路径语义为书级）
"""
# Velluma - collab events clear tests
# Copyright (C) 2026 Velluma. Licensed under AGPL-3.0.

import asyncio
import json

from backend.routes.chapter_generation.adaptive.events import (
    _append_collab_event,
)
from backend.routes.chapter_generation.usage import (
    clear_book_collab_events,
    router as usage_router,
)


def _run(coro):
    """独立 event loop（事件循环策略污染防御，同 test_usage.py）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _patch_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.routes.chapter_generation.adaptive.events._collab_events_path",
        lambda: tmp_path / "collab_events.jsonl",
    )
    monkeypatch.setattr(
        "backend.routes.chapter_generation.adaptive.events._collab_events_rotated_path",
        lambda: tmp_path / "collab_events.jsonl.1",
    )


def _ev(book_id, kind="ghost_request", ch="ch-1"):
    return json.dumps({"ts": "2026-09-11T00:00:00+00:00", "book_id": book_id,
                       "chapter_id": ch, "kind": kind, "detail": {}}, ensure_ascii=False) + "\n"


def _read_json_lines(path):
    """读 JSONL 文件，跳过损坏行（返回 (合法事件列表, 原始行列表)。"""
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    events = []
    for line in raw_lines:
        try:
            events.append(json.loads(line))
        except Exception:
            continue
    return events, raw_lines


class TestClearCollabEvents:
    def test_clears_only_target_book_across_both_files(self, tmp_path, monkeypatch):
        _patch_paths(monkeypatch, tmp_path)
        cur = tmp_path / "collab_events.jsonl"
        rot = tmp_path / "collab_events.jsonl.1"
        cur.write_text("".join([_ev("bk-a"), _ev("bk-b"), "corrupted-not-json\n", _ev("bk-a")]),
                       encoding="utf-8")
        rot.write_text("".join([_ev("bk-a", kind="hint_dismiss"), _ev("bk-b")]), encoding="utf-8")

        resp = _run(clear_book_collab_events("bk-a"))

        assert resp == {"book_id": "bk-a", "deleted": 3}  # 当前 2 + 轮转 1
        cur_events, cur_raw = _read_json_lines(cur)
        assert [e["book_id"] for e in cur_events] == ["bk-b"]  # 他书保留
        assert "corrupted-not-json" in cur_raw  # 损坏行原样保留
        rot_events, _ = _read_json_lines(rot)
        assert [e["book_id"] for e in rot_events] == ["bk-b"]

    def test_no_files_is_noop(self, tmp_path, monkeypatch):
        _patch_paths(monkeypatch, tmp_path)
        resp = _run(clear_book_collab_events("bk-x"))
        assert resp == {"book_id": "bk-x", "deleted": 0}

    def test_invalidates_quiet_learning_caches(self, tmp_path, monkeypatch):
        from backend.services.adaptive import quiet_learning as ql

        _patch_paths(monkeypatch, tmp_path)
        (tmp_path / "collab_events.jsonl").write_text(
            _ev("bk-a", kind="hint_dismiss"), encoding="utf-8")
        # 预热缓存（模拟静音派生已读过旧数据）
        import time as _time
        ql._mutes_cache["bk-a"] = (_time.monotonic(), {"x"})
        ql._hint_scan_cache["bk-a"] = (_time.monotonic(), [(_time.time(), "contradiction")])

        _run(clear_book_collab_events("bk-a"))

        assert "bk-a" not in ql._mutes_cache
        assert "bk-a" not in ql._hint_scan_cache

    def test_append_then_clear_roundtrip(self, tmp_path, monkeypatch):
        """写侧真实落笔 → 清空 → 文件为空（端到端路径一致性）。"""
        _patch_paths(monkeypatch, tmp_path)
        _append_collab_event("bk-a", "ch-1", "ghost_request", {})
        assert (tmp_path / "collab_events.jsonl").exists()
        resp = _run(clear_book_collab_events("bk-a"))
        assert resp["deleted"] == 1
        assert (tmp_path / "collab_events.jsonl").read_text(encoding="utf-8") == ""


class TestRouterWiring:
    def test_delete_path_registered(self):
        registered = {
            (r.path, frozenset(r.methods or ()))
            for r in usage_router.routes
        }
        assert ("/api/books/{book_id}/adaptive/collab-events", frozenset({"DELETE"})) in registered

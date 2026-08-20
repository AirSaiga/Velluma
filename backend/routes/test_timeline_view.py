"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""merge_timeline_view 契约测试（时间轴 UI 状态键级合并 + 值校验）。"""

import unittest

from backend.routes.books import merge_timeline_view


class MergeTimelineViewTest(unittest.TestCase):
    def test_empty_existing_accepts_cursor_and_range(self):
        merged = merge_timeline_view(None, {"cursor": 500, "range": {"start": 3, "end": 2177}})
        self.assertEqual(merged, {"cursor": 500, "range": {"start": 3, "end": 2177}})

    def test_merge_preserves_untouched_keys(self):
        existing = {"cursor": 100, "range": {"start": 1, "end": 50}}
        merged = merge_timeline_view(existing, {"cursor": 200})
        self.assertEqual(merged["cursor"], 200)
        self.assertEqual(merged["range"], {"start": 1, "end": 50})

    def test_explicit_null_deletes_key(self):
        existing = {"cursor": 100, "range": {"start": 1, "end": 50}}
        merged = merge_timeline_view(existing, {"range": None})
        self.assertNotIn("range", merged)
        self.assertEqual(merged["cursor"], 100)

    def test_unknown_keys_ignored(self):
        merged = merge_timeline_view({"cursor": 1}, {"future_field": "x"})
        self.assertEqual(merged, {"cursor": 1})

    def test_does_not_mutate_existing(self):
        existing = {"cursor": 1}
        merge_timeline_view(existing, {"cursor": 2})
        self.assertEqual(existing, {"cursor": 1})

    def test_rejects_invalid_cursor(self):
        for bad in (-1, 1.5, "100", True, {"x": 1}):
            with self.assertRaises(ValueError, msg=f"cursor={bad!r}"):
                merge_timeline_view(None, {"cursor": bad})

    def test_rejects_invalid_range(self):
        for bad in (
            {"start": 0, "end": 5},      # start < 1
            {"start": 5, "end": 5},      # end <= start
            {"start": 6, "end": 5},
            {"start": 1.5, "end": 5},    # 非整数
            {"start": 1},                # 缺键
            {"start": True, "end": 5},   # bool 不是 int
            "1-5",
            [1, 5],
        ):
            with self.assertRaises(ValueError, msg=f"range={bad!r}"):
                merge_timeline_view(None, {"range": bad})


if __name__ == "__main__":
    unittest.main()

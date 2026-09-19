# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""写作规矩（质感契约按书覆盖）端点契约测试（2026-09 收编批）。

纯函数对拍（与 test_timeline_view.py 同风格，不起服务不连库）：
normalize_texture_overrides 的净化口径 + _build_view 的合并视图。
"""

import unittest
from types import SimpleNamespace

from backend.routes.style.contracts import _build_view
from backend.services.style.texture_contracts import (
    CONTRACTS,
    normalize_texture_overrides,
)


class NormalizeOverridesTest(unittest.TestCase):
    def test_valid_body_kept(self):
        out = normalize_texture_overrides(
            {"anti_pseudo_sensory": {"body": "自定义规矩"}},
        )
        self.assertEqual(out, {"anti_pseudo_sensory": {"body": "自定义规矩"}})

    def test_disabled_rules_kept(self):
        out = normalize_texture_overrides(
            {"anti_pseudo_sensory": {"disabled_rules": ["plain_style", "no_comma_pad"]}},
        )
        self.assertEqual(
            out,
            {"anti_pseudo_sensory": {"disabled_rules": ["plain_style", "no_comma_pad"]}},
        )

    def test_disabled_rules_unknown_keys_filtered(self):
        out = normalize_texture_overrides(
            {"anti_pseudo_sensory": {"disabled_rules": ["plain_style", "future_rule"]}},
        )
        self.assertEqual(out, {"anti_pseudo_sensory": {"disabled_rules": ["plain_style"]}})

    def test_disabled_rules_empty_means_restore(self):
        out = normalize_texture_overrides(
            {"anti_pseudo_sensory": {"disabled_rules": []}},
        )
        self.assertEqual(out, {})

    def test_body_beats_disabled_rules(self):
        out = normalize_texture_overrides(
            {"anti_pseudo_sensory": {"body": "整文", "disabled_rules": ["plain_style"]}},
        )
        self.assertEqual(out, {"anti_pseudo_sensory": {"body": "整文"}})

    def test_blank_body_means_restore_default(self):
        for blank in ("", "   ", None):
            out = normalize_texture_overrides(
                {"anti_pseudo_sensory": {"body": blank}},
            )
            self.assertEqual(out, {}, f"body={blank!r} 应丢弃（恢复默认）")

    def test_unknown_key_dropped(self):
        out = normalize_texture_overrides(
            {"anti_pseudo_sensory": {"body": "x"}, "future_contract": {"body": "y"}},
        )
        self.assertEqual(out, {"anti_pseudo_sensory": {"body": "x"}})

    def test_malformed_values_dropped(self):
        for bad in ("oops", 123, ["x"]):
            out = normalize_texture_overrides({"anti_pseudo_sensory": bad})
            self.assertEqual(out, {}, f"值 {bad!r} 应丢弃")
        self.assertEqual(normalize_texture_overrides(None), {})
        self.assertEqual(normalize_texture_overrides(["oops"]), {})

    def test_empty_dict_means_restore_all(self):
        self.assertEqual(normalize_texture_overrides({}), {})


class BuildViewTest(unittest.TestCase):
    def _book(self, texture_contracts):
        return SimpleNamespace(texture_contracts=texture_contracts)

    def test_no_column_or_none_is_all_default(self):
        for raw in (None, {}, "oops", []):
            view = _build_view(self._book(raw))
            self.assertEqual(len(view.contracts), len(CONTRACTS))
            for item in view.contracts:
                self.assertTrue(item.is_default)
                self.assertEqual(item.body, item.default_body)

    def test_customized_flag_and_effective_body(self):
        view = _build_view(self._book(
            {"anti_pseudo_sensory": {"body": "本书规矩", "updated_at": "2026-09-17T00:00:00"}},
        ))
        item = next(i for i in view.contracts if i.key == "anti_pseudo_sensory")
        self.assertFalse(item.is_default)
        self.assertEqual(item.customized_via, "body")
        self.assertEqual(item.body, "本书规矩")
        self.assertNotEqual(item.body, item.default_body)

    def test_disabled_rules_view_flags(self):
        view = _build_view(self._book(
            {"anti_pseudo_sensory": {"disabled_rules": ["plain_style"], "updated_at": "t"}},
        ))
        item = next(i for i in view.contracts if i.key == "anti_pseudo_sensory")
        self.assertFalse(item.is_default)
        self.assertEqual(item.customized_via, "rules")
        enabled = {r.key: r.enabled for r in item.rules}
        self.assertEqual(enabled["plain_style"], False)
        self.assertEqual(enabled["pseudo_sensory"], True)
        self.assertEqual(len(item.rules), 4)
        self.assertNotIn("北方硬朗白描", item.body)  # 生效正文已按开关摘条
        self.assertNotEqual(item.body, item.default_body)

    def test_blank_body_override_reads_as_default(self):
        view = _build_view(self._book(
            {"anti_pseudo_sensory": {"body": "  "}},
        ))
        item = next(i for i in view.contracts if i.key == "anti_pseudo_sensory")
        self.assertTrue(item.is_default)
        self.assertEqual(item.customized_via, "")
        self.assertEqual(item.body, item.default_body)


if __name__ == "__main__":
    unittest.main()

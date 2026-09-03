# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""地图图层/笔迹创建的幂等 id 通道锁（2026-09-04 审计修复）。

背景：前端地图编辑的 undo→redo 此前断链——undo 重建得新 id、redo 仍删旧
id → 404、图层累积重复。修复：Create schema 增可选 id（同地点/实体幂等
重建先例），route 透传。本锁防通道再脱落。
"""
import ast
import unittest
from pathlib import Path
from uuid import uuid4

import backend.routes.world as w

SRC = (Path(__file__).parent / "world.py").read_text(encoding="utf-8")


class TestMapIdempotentId(unittest.TestCase):
    def test_create_schemas_accept_explicit_id(self):
        bid = uuid4()
        layer = w.WorldMapLayerCreate(
            book_id=bid, image_url="u", x=0, y=0, w=1, h=1, id=uuid4())
        self.assertIsNotNone(layer.id)
        layer_default = w.WorldMapLayerCreate(
            book_id=bid, image_url="u", x=0, y=0, w=1, h=1)
        self.assertIsNone(layer_default.id)  # 缺省不传（零变化契约）
        stroke = w.WorldMapStrokeCreate(
            book_id=bid, points=[[0, 0], [1, 1]], id=uuid4())
        self.assertIsNotNone(stroke.id)

    def test_stroke_route_passes_payload_id(self):
        """create_map_stroke 函数体必须把 payload.id 透传给仓储（幂等重建）。

        实现允许两种形态：id=payload.id 关键字，或 **{"id": payload.id} 条件展开。
        """
        tree = ast.parse(SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_map_stroke")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "create"]
        self.assertEqual(len(calls), 1)
        kwargs = {k.arg for k in calls[0].keywords if k.arg}
        ok = "id" in kwargs
        if not ok:
            # ** 展开形态：检查 create 调用源码段含 "id": payload.id
            seg = ast.get_source_segment(SRC, calls[0]) or ""
            ok = '"id": payload.id' in seg
        self.assertTrue(ok, "create_map_stroke 未透传 payload.id——undo/redo 幂等断链回归")

    def test_layer_route_dump_includes_id(self):
        """create_map_layer 的 model_dump 不得排除 id（排除=透传断裂）。"""
        tree = ast.parse(SRC)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "create_map_layer")
        dumps = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "model_dump"]
        self.assertTrue(dumps)
        for d in dumps:
            for kw in d.keywords:
                if kw.arg == "exclude":
                    names = {e.attr for e in ast.walk(kw.value)
                             if isinstance(e, ast.Attribute)}
                    names |= {e.value for e in ast.walk(kw.value)
                              if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                    self.assertNotIn("id", names, "model_dump 排除了 id——幂等重建通道断裂")


if __name__ == "__main__":
    unittest.main()

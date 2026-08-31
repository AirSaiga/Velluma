# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""update_location 父地点闸回归锁（2026-09-01 审计轮）。

背景：create_location 有父地点存在性校验，update_location 没有——可把
parent_id 改成不存在的地点、自身或自己的子级（造环）。读侧
location_path/ancestor_chain 有防环护栏不会崩，但会留脏树（面包屑截断、
场景作用域漏祖先）。本测试直接调用路由函数（FakeDb 桩，配方同
test_world_kernel_routes），锁四向闸 + 合法路径 + 显式 null 脱离。
"""
import asyncio
import unittest
from types import SimpleNamespace as _Sns
from uuid import uuid4

from fastapi import HTTPException

import backend.routes.world as w

BOOK = uuid4()


def _loc(loc_id, parent_id, name="某地"):
    return _Sns(id=loc_id, parent_id=parent_id, name=name, kind="point",
                coord_x=None, coord_y=None, geometry={}, intro="", tags=[])


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class _FakeDb:
    """execute → 返回全书地点列表；get(WorldLocation) → 按 id 命中 stub。"""

    def __init__(self, locations):
        self._locs = locations

    async def get(self, model, pk):
        if model.__name__ == "WorldLocation":
            for l in self._locs:
                if str(l.id) == str(pk):
                    return l
        return None

    async def execute(self, stmt):
        return _FakeResult(self._locs)

    def add(self, obj):
        pass

    async def flush(self):
        pass

    async def commit(self):
        pass


class TestUpdateLocationParentGate(unittest.TestCase):
    def setUp(self):
        # 树形：基地(BASE) → 拘留层(CELL)；顶层独立点(OUTER)
        self.base = _loc(uuid4(), None, name="基地")
        self.cell = _loc(uuid4(), self.base.id, name="拘留层")
        self.outer = _loc(uuid4(), None, name="哨站")
        self.db = _FakeDb([self.base, self.cell, self.outer])

    def _update(self, loc, parent_id):
        payload = w.WorldLocationUpdate(parent_id=parent_id)
        return asyncio.run(w.update_location(BOOK, loc.id, payload, db=self.db))

    def test_reject_self_parent(self):
        with self.assertRaises(HTTPException) as ctx:
            self._update(self.base, self.base.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("自身", ctx.exception.detail)

    def test_reject_missing_parent(self):
        with self.assertRaises(HTTPException) as ctx:
            self._update(self.outer, uuid4())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("不存在", ctx.exception.detail)

    def test_reject_descendant_parent_cycle(self):
        # 把基地的 parent 改成自己的子级（拘留层）→ 成环，必须 400
        with self.assertRaises(HTTPException) as ctx:
            self._update(self.base, self.cell.id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("环", ctx.exception.detail)

    def test_valid_parent_applies(self):
        updated = self._update(self.cell, self.outer.id)
        self.assertEqual(str(updated.parent_id), str(self.outer.id))

    def test_explicit_none_detaches(self):
        # 显式 null = 脱离子树（「键存在即设」契约）——不得被闸拦下
        updated = self._update(self.cell, None)
        self.assertIsNone(updated.parent_id)


if __name__ == "__main__":
    unittest.main()

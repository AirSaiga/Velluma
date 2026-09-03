# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""实体单分组（group_name）回归锁（2026-09-03 资产抽屉分组）。

锁定两条本会话引入的契约：
1. WorldEntityRepository.update 的 None 跳过白名单——「显式传 None = 清空分组」
   必须真的写成 NULL（旧实现 `if v is not None` 会把清空操作静默吞掉，
   路由 exclude_unset 传来的显式 null 到不了数据库）。
2. 未携带 group_name 键的更新不得触碰既有分组（None=「不改」语义不变）。

顺带验证 SQLite 路径 MIGRATIONS 补列生效（init_db_sqlite 即应用）。

配方与 test_data_layer_fixes 同款（UUID 带字母防全数字坑；换新会话查
锁「真的落库」而非会话缓存）。
"""
import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path

import backend.models as m
from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite
from backend.repositories.world_repository import WorldRepository

BOOK = uuid.UUID("d1a00000-0000-4000-8000-00000000000b")


def _stack(tmp_path: Path, name: str):
    engine = build_sqlite_engine(tmp_path / name)
    maker = build_sqlite_sessionmaker(engine)
    asyncio.run(init_db_sqlite(engine, maker))
    return engine, maker


class TestEntityGroupName(unittest.TestCase):
    def _run(self, fn):
        """fn 收 sessionmaker，逐步开独立会话（跨会话验证落库）。"""
        with tempfile.TemporaryDirectory() as td:
            engine, maker = _stack(Path(td), "group.db")
            try:
                async def go():
                    async with maker() as s:
                        s.add(m.Book(id=BOOK, title="分组回归书"))
                        await s.commit()
                    return await fn(maker)
                return asyncio.run(go())
            finally:
                asyncio.run(engine.dispose())

    def test_create_update_clear_cycle(self):
        async def fn(maker):
            async with maker() as s:
                ent = await WorldRepository(s).entities.create(
                    book_id=str(BOOK), entity_type="asset", name="红月", group_name="机甲",
                )
                await s.commit()
                ent_id = ent.id
            # 改名分组
            async with maker() as s:
                updated = await WorldRepository(s).entities.update(ent_id, group_name="武器")
                await s.commit()
                assert updated is not None and updated.group_name == "武器"
            # 显式 None = 清空（白名单路径；旧代码此处静默吞 null）
            async with maker() as s:
                updated = await WorldRepository(s).entities.update(ent_id, group_name=None)
                await s.commit()
                assert updated is not None and updated.group_name is None
            # 换新会话锁「真的落库」
            async with maker() as s:
                fresh = await WorldRepository(s).entities.get(ent_id)
                assert fresh is not None and fresh.group_name is None
        self._run(fn)

    def test_update_without_key_keeps_group(self):
        async def fn(maker):
            async with maker() as s:
                ent = await WorldRepository(s).entities.create(
                    book_id=str(BOOK), entity_type="asset", name="红月", group_name="机甲",
                )
                await s.commit()
                ent_id = ent.id
            # 未携带 group_name 键的更新不得触碰既有分组
            async with maker() as s:
                updated = await WorldRepository(s).entities.update(ent_id, intro="A 级机甲")
                await s.commit()
                assert updated is not None and updated.group_name == "机甲"
            async with maker() as s:
                fresh = await WorldRepository(s).entities.get(ent_id)
                assert fresh is not None and fresh.group_name == "机甲" and fresh.intro == "A 级机甲"
        self._run(fn)


if __name__ == "__main__":
    unittest.main()

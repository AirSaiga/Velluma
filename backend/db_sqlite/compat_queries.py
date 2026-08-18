# -*- coding: utf-8 -*-
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

"""
跨方言查询构件（canon_repository 4 处 PG 专有 JSONB 查询的 SQLite 等价物）。

⚠ 现状：本模块已就绪但未接入——canon_repository.py 在准备期保持原样
（PG 路径零改动）。切换日动作：canon_repository 各查询点按 dialect_name
分派，PG 分支保留现有 text() 原文（行为字节级不变），SQLite 分支用本模块。

语义对照（每条都与 PG 原版逐一对齐，含边界行为）：
- PG  `tags ? CAST(:tag AS text)`
  SQLite `EXISTS (SELECT 1 FROM json_each(canon_nodes.tags) WHERE json_each.value = :tag)`
  （`?` 对 JSON 数组 = 顶层元素相等；tags 恒为 List[str]。json_each 对
  NULL/非数组输入返回空集，与 PG `?` 对 NULL 返回 NULL→不命中一致。）
- PG  `metadata->>'status' = :status`
  SQLite `json_extract(canon_nodes.metadata, '$.status') = :status`
  （`$.status` 缺失时 json_extract 返回 NULL，等号不命中——与 `->>` 一致。）
- PG  `appeared_in @> CAST(:chap AS jsonb)`（chap 是 json.dumps([n])）
  SQLite `EXISTS (SELECT 1 FROM json_each(canon_nodes.appeared_in) WHERE json_each.value = :chap)`
  （原查询是单元素子数组包含；appeared_in 恒为平铺 List[int] 无嵌套，
  逐元素相等即等价。⚠ 参数形态不同：PG 版传 JSON 字符串 '[3]'，
  本构件直接传 int 3。）

性能：canon_nodes 单书量级（≤2000，get_book_graph 上限即此规模）全表扫
json_each 完全无压力；若未来量级上涨，SQLite 侧可加 JSON 索引表（切换后
再议，勿提前优化）。
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def dialect_name(db: AsyncSession) -> str:
    """取会话绑定方言名（"postgresql" / "sqlite"）。

    警示：依赖 session.bind 非空（FastAPI Depends(get_db) 注入的会话满足；
    手工构造无绑定会话的测试需自行保证）。
    """
    return db.bind.dialect.name if db.bind is not None else ""


def is_sqlite(db: AsyncSession) -> bool:
    return dialect_name(db) == "sqlite"


def tags_has_tag(tag: str):
    """canon_repository.list_by_book 的 tag 过滤（SQLite 分支用）。"""
    return text(
        "EXISTS (SELECT 1 FROM json_each(canon_nodes.tags) "
        "WHERE json_each.value = :tag)"
    ).bindparams(tag=tag)


def metadata_status_equals(status: str):
    """canon_repository.find_hooks 的 status 过滤（SQLite 分支用）。"""
    return text(
        "json_extract(canon_nodes.metadata, '$.status') = :status"
    ).bindparams(status=status)


def appeared_in_contains_chapter(chapter_number: int):
    """canon_repository.find_related_to_chapter 的章节包含过滤（SQLite 分支用）。

    ⚠ 参数是 int（PG 原版传 json.dumps([n])——接入时别照抄调用侧的 dumps）。
    """
    return text(
        "EXISTS (SELECT 1 FROM json_each(canon_nodes.appeared_in) "
        "WHERE json_each.value = :chap)"
    ).bindparams(chap=chapter_number)

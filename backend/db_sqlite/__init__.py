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
SQLite 后端（PG → SQLite 迁移准备期模块，⚠ 切换日前不被任何现有代码 import）。

定位与红线（docs 决策：渐进准备、一次性切换）：
- 本包是 SQLite 后端的全部实现：引擎/pragma、方言类型适配、建表与列迁移、
  跨方言查询构件。现有 PG 路径（backend/database.py 等）零改动零引用本包，
  保证准备期生产行为与迁移前完全一致。
- 切换日动作（见模块各自文档字符串与任务清单）：main.py 的 init_db 分支、
  canon_repository 接入 compat_queries、requirements 加 aiosqlite、
  启动脚本/打包配置数据目录落地。
- models.py 不做任何修改：PG 方言类型（UUID/JSONB/Vector）靠 type_compat
  的方言编译注册在 SQLite 侧等效渲染（UUID 天然兼容，PoC 验证）。

模块地图：
- engine.py        引擎与会话工厂（WAL / busy_timeout / foreign_keys 连接级 pragma）
- type_compat.py   JSONB/Vector → SQLite 的方言编译注册（幂等，import 即生效）
- schema.py        init_db_sqlite：建表 + SQLite 版列迁移 + 数据迁移 + 种子化
- compat_queries.py canon_repository 4 处 PG 专有 JSONB 查询的 SQLite 等价构件
"""

from backend.db_sqlite.engine import build_sqlite_engine, build_sqlite_sessionmaker
from backend.db_sqlite.schema import init_db_sqlite

__all__ = ["build_sqlite_engine", "build_sqlite_sessionmaker", "init_db_sqlite"]

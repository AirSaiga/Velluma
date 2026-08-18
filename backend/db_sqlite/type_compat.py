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
SQLite 方言类型适配（PG 专有 ORM 类型 → SQLite DDL 渲染）。

背景（PoC scripts/sqlite_poc_probe.py 验证结论）：
- postgresql.UUID(as_uuid=True)：SQLite 方言天然可渲染（DDL 类型名 "UUID"，
  实际按 TEXT 存储读写往返无损），零适配。
- postgresql.JSONB：SQLite 类型编译器无 visit_JSONB，直接炸——注册为 "JSON"
  （SQLite JSON1 即 TEXT 存储，无 B 树索引差异可言，等价）。
- pgvector.sqlalchemy.Vector：同为方言专有类型——注册为 "TEXT"。
  SQLite 模式下 embedding 恒不用（向量记忆是 PG+pgvector 的专业级可选功能，
  未配置 embedding 时记忆流自动降级为结构化+词法检索），该列永远 NULL，
  TEXT 仅作占位以维持 models.py 零改动。

副作用警示：@compiles 注册是进程级全局的（但仅作用于 sqlite 方言的渲染，
PostgreSQL 方言编译路径零影响）。register_sqlite_type_compat() 幂等，
engine.build_sqlite_engine 会自动调用；直接使用本模块编译产物的场景
（如离线 DDL 导出）需先显式调用。
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.sqltypes import Uuid as _SaUuid

import uuid as _uuid

_registered = False


def _patch_uuid_str_tolerance() -> None:
    """UUID 绑定的字符串容忍（2026-08-19 真机事故修复）。

    根因：代码库大量调用点向 UUID 列传 str（repo 签名惯约 `book_id: str`）。
    PG+asyncpg 驱动层容忍 str；SQLite 方言下通用 Uuid 的绑定处理器执行
    `value.hex` → AttributeError('str' object has no attribute 'hex') → 500
    （受害端点：/world/entities 等全部 world 查询）。

    修法：包装原绑定处理器——str 入参先解析为 uuid.UUID 再走原逻辑；
    uuid.UUID 入参零变化，PG 路径处理器为 None 时原样返回。进程级一次性
    补丁（幂等），对所有方言无害。
    """
    if getattr(_SaUuid, "_velluma_str_tolerant", False):
        return
    _orig_bind_processor = _SaUuid.bind_processor

    def _tolerant_bind_processor(self, dialect):
        proc = _orig_bind_processor(self, dialect)
        if proc is None:
            return None

        def process(value):
            if isinstance(value, str):
                value = _uuid.UUID(value)
            return proc(value)

        return process

    _SaUuid.bind_processor = _tolerant_bind_processor
    _SaUuid._velluma_str_tolerant = True


def register_sqlite_type_compat() -> None:
    """幂等注册 JSONB/Vector 在 SQLite 方言下的 DDL 编译 + UUID 字符串容忍。"""
    global _registered
    if _registered:
        return

    _patch_uuid_str_tolerance()

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - 编译回调
        return "JSON"

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(element, compiler, **kw):  # pragma: no cover - 编译回调
        return "TEXT"

    _registered = True

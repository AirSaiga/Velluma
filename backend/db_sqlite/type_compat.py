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
- postgresql.UUID(as_uuid=True)：SQLite 方言可渲染，但裸类型名 "UUID" 不含
  INT/CHAR/TEXT/BLOB 等关键词 → SQLite 判为 **NUMERIC 亲和性**——32 位全数字
  hex（如 0000…001）会被转存 INTEGER，读回 Python int 后结果处理器
  `uuid.UUID(int)` 直接 AttributeError（2026-08-19 实验复现；uuid4() 生产撞上
  概率 ≈4.4e-7，测试/导入类确定性 ID 必中）。
  修法两层：①治本——DDL 编译为 CHAR(32)（text 亲和性，hex 恒按字符串存）；
  ②治存量——已有库按旧 "UUID" DDL 建表且 SQLite 无 ALTER COLUMN，结果侧
  包装 `Uuid.result_processor` 把 int 还原为 uuid.UUID(int=…)（见
  _patch_uuid_int_tolerance）。
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
from sqlalchemy.dialects.postgresql import UUID as _PgUuid
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


def _patch_uuid_int_tolerance() -> None:
    """UUID 结果侧 int 容忍（存量库 NUMERIC 亲和性治理，2026-08-19）。

    根因：存量 SQLite 库的 UUID 列按旧 DDL "UUID" 建表 → NUMERIC 亲和性 →
    32 位全数字 hex 被转存 INTEGER → 读回 Python int → 原结果处理器
    `uuid.UUID(value)` 内部走 `value.replace('-','')` →
    AttributeError('int' object has no attribute 'replace')。
    （SQLite 无 ALTER COLUMN，存量表无法改列类型，只能在结果侧包装。）

    修法：包装原结果处理器——int 入参（NUMERIC 亲和性产物）直接按 128 位
    整数还原 uuid.UUID(int=value) 返回（int 恰好是 uuid.UUID 的一等构造入参，
    绕开只吃字符串的原逻辑，无损）；str 入参（带/不带连字符 hex）零变化走
    原逻辑；PG 路径处理器为 None 时原样返回。进程级一次性补丁（幂等），
    对所有方言无害。与 _patch_uuid_str_tolerance 同风格成对。
    """
    if getattr(_SaUuid, "_velluma_int_tolerant", False):
        return
    _orig_result_processor = _SaUuid.result_processor

    def _tolerant_result_processor(self, dialect, coltype=None):
        # 注意签名三参（self, dialect, coltype）——TypeEngine.result_processor
        # 由 _cached_result_processor 以位置参数原样透传，缺 coltype 会 TypeError。
        proc = _orig_result_processor(self, dialect, coltype)
        if proc is None:
            return None

        def process(value):
            if isinstance(value, int):
                # 存量行被 NUMERIC 亲和性转存的 INTEGER：按整数值直接还原，
                # 与原 hex 字符串解析等价（uuid.UUID(int=n) == uuid.UUID(32位hex(n))）
                return _uuid.UUID(int=value)
            return proc(value)

        return process

    _SaUuid.result_processor = _tolerant_result_processor
    _SaUuid._velluma_int_tolerant = True


def register_sqlite_type_compat() -> None:
    """幂等注册 JSONB/Vector/UUID 在 SQLite 方言下的 DDL 编译 + UUID 双向容忍。"""
    global _registered
    if _registered:
        return

    _patch_uuid_str_tolerance()
    _patch_uuid_int_tolerance()

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(element, compiler, **kw):  # pragma: no cover - 编译回调
        return "JSON"

    @compiles(Vector, "sqlite")
    def _compile_vector_sqlite(element, compiler, **kw):  # pragma: no cover - 编译回调
        return "TEXT"

    # 治本：UUID 列 DDL 渲染为 CHAR(32)（含 "CHAR" → text 亲和性，hex 恒按
    # 字符串存，杜绝 NUMERIC 亲和性转 INTEGER）。⚠ 必须对 postgresql.UUID
    # 本类注册：@compiles 不被子类继承——Visitable 每个子类经
    # _generate_compiler_dispatch 生成了自己的 _compiler_dispatch（只查本类
    # __dict__ 的 _compiler_dispatcher），在通用 Uuid 上注册对 PG UUID 渲染
    # 无效（实测 2.0.48）。通用 Uuid 一并注册作防御（如有直接使用者）。
    # 均仅 sqlite 方言，PG 原生 UUID 渲染零影响。存量表仍是 "UUID" 列类型，
    # 由 result 侧 int 容忍补丁兜底（见 _patch_uuid_int_tolerance）。
    @compiles(_PgUuid, "sqlite")
    def _compile_pg_uuid_sqlite(element, compiler, **kw):  # pragma: no cover - 编译回调
        return "CHAR(32)"

    @compiles(_SaUuid, "sqlite")
    def _compile_uuid_sqlite(element, compiler, **kw):  # pragma: no cover - 编译回调
        return "CHAR(32)"

    _registered = True

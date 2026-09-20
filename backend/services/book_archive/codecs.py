# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""备份文件的列值编解码——ORM 值 ↔ JSON 可序列化值的双向转换。

设计意图：
- 类型驱动：按 Column.type 判定转换方式，不逐表手写字段清单——
  新增列（模型演进）自动获得编解码，无需改本模块。
- UUID → str / datetime → isoformat：JSON 原生可表达。
- Vector(1536) embedding → {"$b64f32": base64, "dim": N}：float32 打包
  比 JSON 浮点数组省 ~75% 体积（6KB vs 25KB/条）。无向量重建例程
  （只有完稿时 index_chapter_memories 增量），导出丢弃 = PG 用户还原后
  向量召回永久降级，故必须随备份走。
- 反向仅 PG 回填向量：SQLite 方言下 Vector 列编译为 TEXT 且恒 NULL
  （db_sqlite/type_compat.py 契约），传非 None 会破坏该契约。
"""
import base64
import struct
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import UUID as PGUUID

try:  # pgvector 是 PG 路径依赖；SQLite-only 环境兜底不影响导入
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = ()  # type: ignore[assignment]

_B64F32_KEY = "$b64f32"
_B64_KEY = "$b64"


# ============================================================
# 序列化：ORM 值 → JSON 值
# ============================================================

def serialize_column_value(column: Column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray)):
        return {_B64_KEY: base64.b64encode(bytes(value)).decode("ascii")}
    if Vector and isinstance(column.type, Vector):
        floats = _vector_to_floats(value)
        if floats is None:
            return None
        return {
            _B64F32_KEY: _floats_to_b64(floats),
            "dim": len(floats),
        }
    return value


def _vector_to_floats(value: Any) -> Optional[list]:
    """把各驱动形态的向量值统一成 float 列表。

    PG+asyncpg 读出的 Vector 列可能是 str（pgvector 文本格式 "[0.1,0.2]"）、
    list/tuple 或 ndarray（pgvector.sqlalchemy 结果处理器装了 numpy 时）。
    """
    if isinstance(value, str):
        text = value.strip()
        if not (text.startswith("[") and text.endswith("]")):
            return None
        try:
            parsed = [float(x) for x in text[1:-1].split(",") if x.strip()]
            return parsed or None
        except ValueError:
            return None
    if hasattr(value, "tolist"):  # numpy ndarray
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        try:
            return [float(x) for x in value]
        except (TypeError, ValueError):
            return None
    return None


def _floats_to_b64(floats: list) -> str:
    return base64.b64encode(struct.pack(f"<{len(floats)}f", *floats)).decode("ascii")


# ============================================================
# 反序列化：JSON 值 → ORM 值
# ============================================================

def deserialize_column_value(column: Column, value: Any, dialect_name: str) -> Any:
    if value is None:
        return None
    col_type = column.type
    if Vector and isinstance(col_type, Vector):
        # SQLite 方言向量列恒 NULL（type_compat 契约）——只回填 PG
        if dialect_name != "postgresql":
            return None
        if isinstance(value, dict) and _B64F32_KEY in value:
            return _b64_to_floats(value[_B64F32_KEY])
        return None
    if isinstance(col_type, PGUUID):
        return value if isinstance(value, UUID) else UUID(str(value))
    if isinstance(col_type, DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value)
    if isinstance(value, dict) and set(value.keys()) == {_B64_KEY}:
        return base64.b64decode(value[_B64_KEY])
    return value


def _b64_to_floats(b64_text: str) -> list:
    raw = base64.b64decode(b64_text)
    count = len(raw) // 4
    return list(struct.unpack(f"<{count}f", raw[: count * 4]))

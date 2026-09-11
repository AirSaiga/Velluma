# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""Canon 真相层：CanonNode / CanonEdge（作者脑中世界的叙事知识图谱）及类型常量。"""
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Column, String, Text, Integer, DateTime, Float, ForeignKey, UniqueConstraint, Boolean, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from backend.database import Base

from ._common import generate_uuid, utc_now


# ============================================================
# V4.0 Canon — 作者脑中世界的叙事知识图谱
# ============================================================
# 设计依据：docs/generation-v4.0-canon.md §2
#
# 核心定位：
# - Canon 是作者脑中真相的结构化存储（不依赖已发布文本推断）
# - private 字段绝不许泄露到正文（由一致性引擎 + prompt 注入保障）
# - 图谱结构（节点+边）天然支持可视化、连锁分析、路径检索
#
# 节点类型（NODE_TYPE_*）：
#   CHARACTER  角色（metadata: identity/power/motivation/arc_position）
#   EVENT      事件（metadata: when/where/who/consequence）
#   OBJECT     物件（metadata: owner/ability/origin）
#   PLACE      地点（metadata: description/inhabitants）
#   HOOK       伏笔节点（metadata: strength/bury_style/payoff_style/status）
#
# 边类型（EDGE_TYPE_*）：
#   CAUSES     因果（A 导致 B）
#   BEFORE     时序（A 在 B 之前）
#   HINTS      弱伏笔暗示
#   SETUPS     强伏笔铺设
#   CALLBACKS  回收
#   ECHOES     呼应（已回收后的二次呼应）
#
# 可见性（VISIBILITY_*）：
#   PUBLIC     已在正文写出（读者已知）
#   PRIVATE    仅作者知道（绝不许泄露到正文）
#   PARTIAL    部分揭示（读者知道一部分）
#
# 表设计决策：
# - 用邻接表 + JSONB 属性（不引入 Neo4j）
# - 图算法在前端 Cytoscape.js 做，后端只做 CRUD + 基础查询
# - 两张表通过 book_id 隔离，不与现有 Character/PlotLedger 直接关联
#   （独立层，避免迁移风险；可通过 metadata.ref_id 软关联现有实体）

# ---- 节点类型常量 ----
NODE_TYPE_CHARACTER = "character"
NODE_TYPE_EVENT = "event"
NODE_TYPE_OBJECT = "object"
NODE_TYPE_PLACE = "place"
NODE_TYPE_HOOK = "hook"
NODE_TYPES = {
    NODE_TYPE_CHARACTER, NODE_TYPE_EVENT, NODE_TYPE_OBJECT,
    NODE_TYPE_PLACE, NODE_TYPE_HOOK,
}

# ---- 边类型常量 ----
EDGE_TYPE_CAUSES = "causes"
EDGE_TYPE_BEFORE = "before"
EDGE_TYPE_HINTS = "hints"
EDGE_TYPE_SETUPS = "setups"
EDGE_TYPE_CALLBACKS = "callbacks"
EDGE_TYPE_ECHOES = "echoes"
EDGE_TYPES = {
    EDGE_TYPE_CAUSES, EDGE_TYPE_BEFORE, EDGE_TYPE_HINTS,
    EDGE_TYPE_SETUPS, EDGE_TYPE_CALLBACKS, EDGE_TYPE_ECHOES,
}

# ---- 可见性常量 ----
VISIBILITY_PUBLIC = "public"
VISIBILITY_PRIVATE = "private"
VISIBILITY_PARTIAL = "partial"
VISIBILITIES = {VISIBILITY_PUBLIC, VISIBILITY_PRIVATE, VISIBILITY_PARTIAL}


class CanonNode(Base):
    """Canon 节点 — 作者脑中世界的一个事实/设定/伏笔。

    业务含义：
    - canon_text 是作者脑中的完整真相
    - public_text 是读者目前在正文里看到的（可能截断/伪装/完全不同）
    - visibility 控制生成时是否允许在正文出现
      · public：可直接出现
      · private：绝不许直接出现，但可作为角色行为的隐藏动机
      · partial：可出现 public_text 部分，canon_text 的其余部分仍 private

    使用场景：
    - 作者在 Canon 编辑器手动创建
    - 自动提取器从已发布文本提取（source=auto_extracted，confidence=tentative）
    - 生成流水线 Phase 0 加载，注入到 prompt 作为强约束
    - 一致性引擎对照检查新文本是否泄露 private 字段

    警示：metadata.ref_id 是软关联现有实体（Character.id 等），无外键约束。
    软关联失败时（如原实体被删），通过 metadata.ref_type 仍可识别。
    """

    __tablename__ = "canon_nodes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    # uow 依赖边：flush 跨表排序按 relationship 而非裸 FK（无此声明时与 Book 同
    # flush 的插入序不确定，SQLite FK 开启下会 IntegrityError——world.py 同款）
    book = relationship("Book")
    type = Column(String(20), nullable=False, index=True)
    label = Column(String(200), nullable=False)

    # 内容双层
    canon_text = Column(Text, default="")
    public_text = Column(Text, default="")

    # 可见性
    visibility = Column(String(20), default=VISIBILITY_PUBLIC)

    # 章节追溯
    appeared_in = Column(JSONB, default=list)  # [chapter_number, ...]
    revealed_in = Column(JSONB, default=list)  # [chapter_number, ...]

    # 揭示计划
    reveal_plan = Column(Text, default="")
    expected_reveal_chapter = Column(Integer, nullable=True)

    # 元数据
    tags = Column(JSONB, default=list)
    confidence = Column(String(20), default="confirmed")  # confirmed | tentative | draft
    source = Column(String(20), default="author")  # author | auto_extracted | mixed
    metadata_ = Column("metadata", JSONB, default=dict)  # 自由扩展（避开 SQL 保留字）

    # C2 信息面挂接（docs/canon-world-fusion.md §4.1）：ref 指向世界对象
    # （entity | location | ledger），label/type 读取时由世界对象推演（根治名字漂移
    # →泄密漏检）。无单一外键（三possible 目标），唯一性与级联清理在应用层：
    # migrate-canon 建立 / world 对象删除时同步清 overlay（world_repository）。
    ref_type = Column(String(20), nullable=True)  # entity | location | ledger | NULL=自由节点
    ref_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # 关系（双向）
    out_edges = relationship(
        "CanonEdge",
        foreign_keys="CanonEdge.source_id",
        back_populates="source",
        cascade="all, delete-orphan",
    )
    in_edges = relationship(
        "CanonEdge",
        foreign_keys="CanonEdge.target_id",
        back_populates="target",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<CanonNode {self.type}:{self.label}>"


class CanonEdge(Base):
    """Canon 边 — 两个节点之间的叙事关系。

    业务含义：
    - type 决定关系语义（因果/时序/伏笔链）
    - visibility 决定该关系是否已在正文揭示
    - strength 1-10，影响连锁分析的优先级
    - established_in 记录该关系在哪些章节建立（用于追溯）

    使用场景：
    - 作者手动建立（如"兰星 → causes → 复仇动机"）
    - 自动提取（如检测到"兰星父之死"和"复仇"共现，推断因果关系）
    - 变更连锁分析的核心数据源（改一个节点，沿边追溯影响）
    """

    __tablename__ = "canon_edges"
    __table_args__ = (
        # 防止重复边（同源同目标同类型只能有一条）
        UniqueConstraint("source_id", "target_id", "type", name="uq_canon_edge_triplet"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    book_id = Column(UUID(as_uuid=True), ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(UUID(as_uuid=True), ForeignKey("canon_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(UUID(as_uuid=True), ForeignKey("canon_nodes.id", ondelete="CASCADE"), nullable=False, index=True)

    type = Column(String(20), nullable=False)
    strength = Column(Integer, default=5)  # 1-10
    visibility = Column(String(20), default=VISIBILITY_PUBLIC)
    note = Column(Text, default="")
    established_in = Column(JSONB, default=list)  # [chapter_number, ...]
    metadata_ = Column("metadata", JSONB, default=dict)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    source = relationship("CanonNode", foreign_keys=[source_id], back_populates="out_edges")
    target = relationship("CanonNode", foreign_keys=[target_id], back_populates="in_edges")

    def __repr__(self):
        return f"<CanonEdge {self.type} strength={self.strength}>"



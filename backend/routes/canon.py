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
Canon REST API 路由（V4.0 新建）。

职责：暴露 Canon 节点/边 CRUD + 图查询 + 一致性检查 + 连锁分析 + 自动提取。

API 端点（前缀 /api/books/{book_id}/canon）：
- GET    /                  获取整书图谱（前端可视化主查询）
- GET    /nodes             列出节点（支持过滤）
- POST   /nodes             创建节点
- PUT    /nodes/{node_id}   更新节点
- DELETE /nodes/{node_id}   删除节点
- GET    /edges             列出边
- POST   /edges             创建边
- PUT    /edges/{edge_id}   更新边
- DELETE /edges/{edge_id}   删除边
- GET    /nodes/{node_id}/neighbors   取邻居（含 BFS depth 参数）
- POST   /check             一致性检查（body: {text}）
- POST   /impact/{node_id}  变更连锁分析
- POST   /extract           自动提取（body: {chapter_id, auto_commit}）
- GET    /hooks             悬空伏笔列表

使用方式：
    GET /api/books/{book_id}/canon
    POST /api/books/{book_id}/canon/nodes  body: CanonNodeCreate
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_db
from backend.models import (
    CanonNode,
    CanonEdge,
    NODE_TYPES,
    EDGE_TYPES,
    VISIBILITIES,
    VISIBILITY_PUBLIC,
)
from backend.repositories import CanonRepository
from backend.schemas.canon import (
    CanonNodeCreate,
    CanonNodeUpdate,
    CanonNodeResponse,
    CanonEdgeCreate,
    CanonEdgeUpdate,
    CanonEdgeResponse,
    ConsistencyCheckResponse,
    ImpactAnalysisResponse,
    CanonExtractionRequest,
    CanonExtractionResponse,
)
from backend.services.canon import (
    check_consistency,
    analyze_change_impact,
    extract_from_chapter,
)
from backend.services.utils.logging import get_runtime_logger

logger = get_runtime_logger(__name__)

router = APIRouter(prefix="/api/books", tags=["canon-v4.0"])


# ============================================================
# 工具：ORM → dict（处理 metadata_ → metadata 别名）
# ============================================================

def _node_to_dict(node: CanonNode) -> dict:
    return {
        "id": str(node.id),
        "book_id": str(node.book_id),
        "type": node.type,
        "label": node.label,
        "canon_text": node.canon_text or "",
        "public_text": node.public_text or "",
        "visibility": node.visibility,
        "appeared_in": node.appeared_in or [],
        "revealed_in": node.revealed_in or [],
        "reveal_plan": node.reveal_plan or "",
        "expected_reveal_chapter": node.expected_reveal_chapter,
        "tags": node.tags or [],
        "confidence": node.confidence,
        "source": node.source,
        "metadata": node.metadata_ or {},
        "ref_type": node.ref_type,
        "ref_id": str(node.ref_id) if node.ref_id else None,
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def _edge_to_dict(edge: CanonEdge) -> dict:
    return {
        "id": str(edge.id),
        "book_id": str(edge.book_id),
        "source_id": str(edge.source_id),
        "target_id": str(edge.target_id),
        "type": edge.type,
        "strength": edge.strength,
        "visibility": edge.visibility,
        "note": edge.note or "",
        "established_in": edge.established_in or [],
        "metadata": edge.metadata_ or {},
        "created_at": edge.created_at.isoformat() if edge.created_at else None,
        "updated_at": edge.updated_at.isoformat() if edge.updated_at else None,
    }


# ============================================================
# 整书图谱（可视化主查询）
# ============================================================

@router.get("/{book_id}/canon")
async def get_book_graph(
    book_id: UUID,
    node_type: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取整书图谱（前端 Cytoscape 主查询）。"""
    repo = CanonRepository(db)
    graph = await repo.get_book_graph(book_id, node_type=node_type, visibility=visibility)
    return {
        "nodes": [_node_to_dict(n) for n in graph["nodes"]],
        "edges": [_edge_to_dict(e) for e in graph["edges"]],
    }


# ============================================================
# 节点 CRUD
# ============================================================

@router.get("/{book_id}/canon/nodes")
async def list_nodes(
    book_id: UUID,
    node_type: Optional[str] = Query(None),
    visibility: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """列出节点（支持过滤）。"""
    repo = CanonRepository(db)
    nodes = await repo.nodes.list_by_book(
        book_id, node_type=node_type, visibility=visibility, tag=tag,
    )
    return [_node_to_dict(n) for n in nodes]


@router.post("/{book_id}/canon/nodes")
async def create_node(
    book_id: UUID,
    payload: CanonNodeCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建节点。"""
    if payload.type not in NODE_TYPES:
        raise HTTPException(400, f"无效节点类型：{payload.type}")
    if payload.visibility not in VISIBILITIES:
        raise HTTPException(400, f"无效可见性：{payload.visibility}")
    # 强制 book_id 一致
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不一致")

    # 构造 payload dict（处理 metadata_ 别名）
    create_dict = payload.model_dump(by_alias=True, exclude_none=True)
    # model_dump with alias 会产出 "metadata" 键，但 ORM 字段是 metadata_
    if "metadata" in create_dict:
        create_dict["metadata_"] = create_dict.pop("metadata")
    create_dict.pop("book_id", None)  # 已在 URL
    create_dict["book_id"] = book_id

    repo = CanonRepository(db)
    try:
        # 检查同名
        existing = await repo.nodes.find_by_label(book_id, payload.label)
        if existing:
            raise HTTPException(409, f"同名节点已存在：{payload.label}")
        # C2 幂等护栏：同一世界对象至多一条信息面 overlay（应用层唯一性——
        # EntityDetailDrawer「读者认知」分区重复点创建返回既有条目而非报错）
        if payload.ref_type and payload.ref_id:
            from sqlalchemy import select as sa_select
            from backend.models import CanonNode as _CanonNode
            hit = (
                await db.execute(
                    sa_select(_CanonNode).where(
                        _CanonNode.book_id == book_id,
                        _CanonNode.ref_type == payload.ref_type,
                        _CanonNode.ref_id == payload.ref_id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if hit:
                return _node_to_dict(hit)
        node = await repo.nodes.create(create_dict)
        return _node_to_dict(node)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Canon] 创建节点失败: {e}")
        raise HTTPException(500, f"创建失败: {e}")


@router.put("/{book_id}/canon/nodes/{node_id}")
async def update_node(
    book_id: UUID,
    node_id: UUID,
    payload: CanonNodeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新节点。"""
    repo = CanonRepository(db)
    node = await repo.nodes.get_by_id(node_id)
    if not node or node.book_id != book_id:
        raise HTTPException(404, "节点不存在")

    update_dict = payload.model_dump(by_alias=True, exclude_unset=True)
    if "metadata" in update_dict:
        update_dict["metadata_"] = update_dict.pop("metadata")
    # 空数组/None 不覆盖（exclude_unset 已排除 None，但空数组要保留以允许清空）

    try:
        updated = await repo.nodes.update(node, update_dict)
        return _node_to_dict(updated)
    except Exception as e:
        logger.exception(f"[Canon] 更新节点失败: {e}")
        raise HTTPException(500, f"更新失败: {e}")


@router.delete("/{book_id}/canon/nodes/{node_id}")
async def delete_node(
    book_id: UUID,
    node_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除节点（级联删除相连边）。"""
    repo = CanonRepository(db)
    node = await repo.nodes.get_by_id(node_id)
    if not node or node.book_id != book_id:
        raise HTTPException(404, "节点不存在")
    try:
        await repo.nodes.delete(node)
        return {"deleted": True, "id": str(node_id)}
    except Exception as e:
        logger.exception(f"[Canon] 删除节点失败: {e}")
        raise HTTPException(500, f"删除失败: {e}")


# ============================================================
# 边 CRUD
# ============================================================

@router.get("/{book_id}/canon/edges")
async def list_edges(
    book_id: UUID,
    edge_type: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """列出边。"""
    repo = CanonRepository(db)
    edges = await repo.edges.list_by_book(book_id, edge_type=edge_type)
    return [_edge_to_dict(e) for e in edges]


@router.post("/{book_id}/canon/edges")
async def create_edge(
    book_id: UUID,
    payload: CanonEdgeCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建边。"""
    if payload.type not in EDGE_TYPES:
        raise HTTPException(400, f"无效边类型：{payload.type}")
    if payload.book_id != book_id:
        raise HTTPException(400, "book_id 不一致")

    create_dict = payload.model_dump(by_alias=True, exclude_none=True)
    if "metadata" in create_dict:
        create_dict["metadata_"] = create_dict.pop("metadata")
    create_dict.pop("book_id", None)
    create_dict["book_id"] = book_id

    repo = CanonRepository(db)
    try:
        # upsert
        edge = await repo.upsert_edge(
            book_id=book_id,
            source_id=create_dict["source_id"],
            target_id=create_dict["target_id"],
            edge_type=create_dict["type"],
            strength=create_dict.get("strength", 5),
            visibility=create_dict.get("visibility", "public"),
            note=create_dict.get("note", ""),
            established_in=create_dict.get("established_in", []),
            metadata=create_dict.get("metadata_", {}),
        )
        return _edge_to_dict(edge)
    except Exception as e:
        logger.exception(f"[Canon] 创建边失败: {e}")
        raise HTTPException(500, f"创建失败: {e}")


@router.put("/{book_id}/canon/edges/{edge_id}")
async def update_edge(
    book_id: UUID,
    edge_id: UUID,
    payload: CanonEdgeUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新边。"""
    repo = CanonRepository(db)
    edge = await repo.edges.get_by_id(edge_id)
    if not edge or edge.book_id != book_id:
        raise HTTPException(404, "边不存在")

    update_dict = payload.model_dump(by_alias=True, exclude_unset=True)
    if "metadata" in update_dict:
        update_dict["metadata_"] = update_dict.pop("metadata")

    try:
        updated = await repo.edges.update(edge, update_dict)
        return _edge_to_dict(updated)
    except Exception as e:
        logger.exception(f"[Canon] 更新边失败: {e}")
        raise HTTPException(500, f"更新失败: {e}")


@router.delete("/{book_id}/canon/edges/{edge_id}")
async def delete_edge(
    book_id: UUID,
    edge_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """删除边。"""
    repo = CanonRepository(db)
    edge = await repo.edges.get_by_id(edge_id)
    if not edge or edge.book_id != book_id:
        raise HTTPException(404, "边不存在")
    try:
        await repo.edges.delete(edge)
        return {"deleted": True, "id": str(edge_id)}
    except Exception as e:
        logger.exception(f"[Canon] 删除边失败: {e}")
        raise HTTPException(500, f"删除失败: {e}")


# ============================================================
# 图查询
# ============================================================

@router.get("/{book_id}/canon/nodes/{node_id}/neighbors")
async def get_neighbors(
    book_id: UUID,
    node_id: UUID,
    depth: int = Query(2, ge=1, le=4),
    db: AsyncSession = Depends(get_db),
):
    """取邻居（BFS，用于可视化聚焦 + 连锁分析）。"""
    repo = CanonRepository(db)
    graph = await repo.find_neighbors(node_id, max_depth=depth)
    if not graph:
        raise HTTPException(404, "节点不存在")
    return {
        "center": _node_to_dict(graph["center"]),
        "nodes": [_node_to_dict(n) for n in graph["nodes"]],
        "edges": [_edge_to_dict(e) for e in graph["edges"]],
    }


@router.get("/{book_id}/canon/hooks")
async def list_hooks(
    book_id: UUID,
    only_open: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    """列出伏笔节点（默认只看 status=open）。"""
    repo = CanonRepository(db)
    hooks = await repo.nodes.find_hooks(book_id, only_open=only_open)
    return [_node_to_dict(h) for h in hooks]


# ============================================================
# 一致性检查
# ============================================================

class ConsistencyCheckRequest(BaseModel):
    """一致性检查请求体。"""
    text: str
    include_llm_check: bool = False


@router.post("/{book_id}/canon/check", response_model=ConsistencyCheckResponse)
async def check_text_consistency(
    book_id: UUID,
    payload: ConsistencyCheckRequest,
    db: AsyncSession = Depends(get_db),
):
    """对文本做一致性检查（对照 Canon）。"""
    issues, stats = await check_consistency(
        db, book_id, payload.text, include_llm_check=payload.include_llm_check,
    )
    return ConsistencyCheckResponse(issues=issues, stats=stats)


# ============================================================
# 变更连锁分析
# ============================================================

class ImpactRequest(BaseModel):
    """连锁分析请求体。"""
    proposed_change: Optional[Dict[str, Any]] = None
    max_depth: int = 2


@router.post("/{book_id}/canon/impact/{node_id}", response_model=ImpactAnalysisResponse)
async def get_change_impact(
    book_id: UUID,
    node_id: UUID,
    payload: ImpactRequest,
    db: AsyncSession = Depends(get_db),
):
    """变更连锁分析。"""
    result = await analyze_change_impact(
        db, node_id, payload.proposed_change, max_depth=payload.max_depth,
    )
    if not result:
        raise HTTPException(404, "节点不存在")
    # 序列化
    changed_node = result["changed_node"]
    return ImpactAnalysisResponse(
        changed_node=CanonNodeResponse.model_validate(_node_to_dict(changed_node)),
        affected=result["affected"],
        total_affected=result["total_affected"],
    )


# ============================================================
# 自动提取
# ============================================================

@router.post("/{book_id}/canon/extract", response_model=CanonExtractionResponse)
async def extract_canon(
    book_id: UUID,
    payload: CanonExtractionRequest,
    db: AsyncSession = Depends(get_db),
):
    """从章节自动提取 Canon 候选。"""
    result = await extract_from_chapter(
        db, payload.chapter_id, auto_commit=payload.auto_commit,
    )
    return CanonExtractionResponse(
        extracted_nodes=result["extracted_nodes"],
        extracted_edges=result["extracted_edges"],
        committed=result["committed"],
        message=result["message"],
    )

"""
地图/地点管理路由模块。

职责：提供地点的 CRUD API，管理书籍中的地理位置数据。

业务场景：
- 创建地点（如"长安城"、"新手村"）
- 获取书籍的地点列表
- 获取地点详情
- 更新地点信息（描述、坐标等）
- 删除地点
- 章节与地点的关联管理

设计说明：
- 地点从属于书籍，支持层级结构（如"长安城→朱雀大街"）
- 章节与地点的关联记录在 ChapterMapLocation 表

数据模型：
- MapLocation: 地点实体
- ChapterMapLocation: 章节-地点关联
"""

import asyncio
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_chapter_repository, get_map_repository
from backend.repositories import BookRepository, ChapterRepository, MapLocationRepository
from backend.schemas import (
    MapLocationCreate,
    MapLocationUpdate,
    MapLocationResponse,
    ChapterMapLocationCreate,
    ChapterMapLocationResponse,
)

router = APIRouter(prefix="/api", tags=["maps"])

# =============================================================================
# 地点基础管理
# =============================================================================

@router.get("/books/{book_id}/locations", response_model=List[MapLocationResponse])
async def list_book_locations(
    book_id: UUID,
    repo: MapLocationRepository = Depends(get_map_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    """获取书籍下的所有地点"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await repo.list_by_book(book_id)

@router.post("/books/{book_id}/locations", response_model=MapLocationResponse, status_code=201)
async def create_location(
    book_id: UUID,
    location_data: MapLocationCreate,
    repo: MapLocationRepository = Depends(get_map_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    """创建新地点"""
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    if location_data.book_id != book_id:
        raise HTTPException(status_code=400, detail="书籍ID不匹配")
    
    return await repo.create(location_data.model_dump())

@router.put("/locations/{location_id}", response_model=MapLocationResponse)
async def update_location(
    location_id: UUID,
    location_data: MapLocationUpdate,
    repo: MapLocationRepository = Depends(get_map_repository),
):
    """更新地点信息"""
    location = await repo.get_by_id(location_id)
    if not location:
        raise HTTPException(status_code=404, detail="地点不存在")
    return await repo.update(location, location_data.model_dump(exclude_unset=True))

@router.delete("/locations/{location_id}", status_code=204)
async def delete_location(
    location_id: UUID,
    repo: MapLocationRepository = Depends(get_map_repository),
):
    """删除地点"""
    location = await repo.get_by_id(location_id)
    if not location:
        raise HTTPException(status_code=404, detail="地点不存在")
    await repo.delete(location)

# =============================================================================
# 章节-地点关联管理
# =============================================================================

@router.get("/chapters/{chapter_id}/locations", response_model=List[ChapterMapLocationResponse])
async def list_chapter_locations(
    chapter_id: UUID,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """获取章节关联的所有地点"""
    return await chapter_repo.list_locations_with_details(chapter_id)

@router.post("/chapters/{chapter_id}/locations", response_model=ChapterMapLocationResponse, status_code=201)
async def add_location_to_chapter(
    chapter_id: UUID,
    payload: ChapterMapLocationCreate,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    map_repo: MapLocationRepository = Depends(get_map_repository),
):
    """关联地点到章节"""
    location = await map_repo.get_by_id(payload.location_id)
    if not location:
        raise HTTPException(status_code=404, detail="地点不存在")
    
    # 检查是否已关联
    existing = await chapter_repo.list_locations(chapter_id)
    for rel in existing:
        if rel.location_id == payload.location_id:
            raise HTTPException(status_code=400, detail="地点已关联")
            
    await chapter_repo.add_location(chapter_id, payload.location_id)
    
    # 重新获取包含详情的关联对象
    all_rels = await chapter_repo.list_locations_with_details(chapter_id)
    for rel in all_rels:
        if rel.location_id == payload.location_id:
            return rel
    raise HTTPException(status_code=500, detail="关联失败")

@router.delete("/chapters/{chapter_id}/locations/{location_id}", status_code=204)
async def remove_location_from_chapter(
    chapter_id: UUID,
    location_id: UUID,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """移除章节关联的地点
    
    注意：location_id 参数实际上是 map_locations 表的 ID (即 location_id)，
    而不是 chapter_map_locations 关联表的 ID。
    """
    await chapter_repo.remove_location_by_ids(chapter_id, location_id)
    # 即使没有删除任何行（本来就不存在），也视为成功，保持幂等性，不抛出 404

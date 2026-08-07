from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.core.dependencies import get_asset_repository, get_chapter_asset_repository
from backend.repositories.asset_repository import AssetRepository, ChapterAssetRepository
from backend.schemas.assets import AssetCreate, AssetResponse, AssetUpdate, ChapterAssetResponse

router = APIRouter(prefix="/api", tags=["Assets"])

@router.get("/books/{book_id}/assets", response_model=List[AssetResponse])
async def list_assets(
    book_id: UUID,
    repo: AssetRepository = Depends(get_asset_repository),
):
    return await repo.list_by_book(book_id)

@router.post("/books/{book_id}/assets", response_model=AssetResponse, status_code=201)
async def create_asset(
    book_id: UUID,
    data: AssetCreate,
    repo: AssetRepository = Depends(get_asset_repository),
):
    payload = {**data.model_dump(), "book_id": book_id}
    return await repo.create(payload)

@router.get("/assets/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    repo: AssetRepository = Depends(get_asset_repository),
):
    asset = await repo.get_by_id(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset

@router.put("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: UUID,
    data: AssetUpdate,
    repo: AssetRepository = Depends(get_asset_repository),
):
    asset = await repo.get_by_id(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return await repo.update(asset, data.model_dump(exclude_unset=True))

@router.delete("/assets/{asset_id}", status_code=204)
async def delete_asset(
    asset_id: UUID,
    repo: AssetRepository = Depends(get_asset_repository),
):
    asset = await repo.get_by_id(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    await repo.delete(asset)

@router.get("/chapters/{chapter_id}/assets", response_model=List[ChapterAssetResponse])
async def list_chapter_assets(
    chapter_id: UUID,
    repo: ChapterAssetRepository = Depends(get_chapter_asset_repository),
):
    return await repo.list_by_chapter(chapter_id)

@router.put("/chapters/{chapter_id}/assets", response_model=List[ChapterAssetResponse])
async def update_chapter_assets(
    chapter_id: UUID,
    asset_ids: List[UUID] = Query(default=[], description="本章要关联的资产 ID 列表（重复的 query 键；空列表表示清空全部关联）"),
    repo: ChapterAssetRepository = Depends(get_chapter_asset_repository),
):
    await repo.delete_by_chapter(chapter_id)
    for aid in asset_ids:
        await repo.create({"chapter_id": chapter_id, "asset_id": aid})
    return await repo.list_by_chapter(chapter_id)

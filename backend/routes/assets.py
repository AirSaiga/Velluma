from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.core.dependencies import get_asset_repository, get_chapter_asset_repository
from backend.models import Asset, ChapterAsset
from backend.repositories.asset_repository import AssetRepository, ChapterAssetRepository
from backend.schemas.assets import AssetCreate, AssetResponse, AssetUpdate, ChapterAssetResponse

router = APIRouter(tags=["Assets"])

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
    asset = Asset(**data.model_dump(), book_id=book_id)
    return await repo.create(asset)

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
    asset_ids: List[UUID],
    repo: ChapterAssetRepository = Depends(get_chapter_asset_repository),
):
    await repo.delete_by_chapter(chapter_id)
    new_assets = [ChapterAsset(chapter_id=chapter_id, asset_id=aid) for aid in asset_ids]
    for asset in new_assets:
        await repo.create(asset)
    return await repo.list_by_chapter(chapter_id)

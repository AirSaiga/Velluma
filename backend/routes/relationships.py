from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_character_repository, get_relationship_repository
from backend.repositories import CharacterRepository, RelationshipRepository
from backend.schemas import RelationshipCreate, RelationshipResponse

router = APIRouter(prefix="/api", tags=["relationships"])


@router.get("/relationships", response_model=List[RelationshipResponse])
async def get_relationships(
    book_id: Optional[UUID] = None, repo: RelationshipRepository = Depends(get_relationship_repository)
):
    return await repo.list(book_id)


@router.post("/relationships", response_model=RelationshipResponse, status_code=201)
async def create_relationship(
    relationship_data: RelationshipCreate,
    relationship_repo: RelationshipRepository = Depends(get_relationship_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    source_char = await character_repo.get_by_id(relationship_data.source_char_id)
    if not source_char:
        raise HTTPException(status_code=404, detail="源角色不存在")
    target_char = await character_repo.get_by_id(relationship_data.target_char_id)
    if not target_char:
        raise HTTPException(status_code=404, detail="目标角色不存在")
    existing = await relationship_repo.get_by_pair(relationship_data.source_char_id, relationship_data.target_char_id)
    if existing:
        raise HTTPException(status_code=400, detail="关系已存在")
    return await relationship_repo.create(relationship_data.model_dump())


@router.delete("/relationships/{relationship_id}")
async def delete_relationship(relationship_id: UUID, repo: RelationshipRepository = Depends(get_relationship_repository)):
    relationship = await repo.get_by_id(relationship_id)
    if not relationship:
        raise HTTPException(status_code=404, detail="关系不存在")
    await repo.delete(relationship)
    return {"message": "关系已删除", "id": str(relationship_id)}

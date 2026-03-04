from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_chapter_repository, get_character_repository
from backend.repositories import BookRepository, ChapterRepository, CharacterRepository
from backend.schemas import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterDynamicStateUpdateRequest,
    CharacterDynamicStateUpdateResponse,
)
from backend.services.chapter_generation import update_character_dynamic_state

router = APIRouter(prefix="/api", tags=["characters"])


@router.get("/books/{book_id}/characters", response_model=List[CharacterResponse])
async def get_characters(book_id: UUID, repo: CharacterRepository = Depends(get_character_repository)):
    return await repo.list_by_book(book_id)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: UUID, repo: CharacterRepository = Depends(get_character_repository)):
    character = await repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return character


@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    character_data: CharacterCreate,
    character_repo: CharacterRepository = Depends(get_character_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    book = await book_repo.get_by_id(character_data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await character_repo.create(character_data.model_dump())


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: UUID,
    character_data: CharacterUpdate,
    repo: CharacterRepository = Depends(get_character_repository),
):
    character = await repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return await repo.update(character, character_data.model_dump(exclude_unset=True))


@router.delete("/characters/{character_id}")
async def delete_character(character_id: UUID, repo: CharacterRepository = Depends(get_character_repository)):
    character = await repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    await repo.delete(character)
    return {"message": "角色已删除", "id": str(character_id)}


@router.post("/characters/{character_id}/update-dynamic-state")
async def update_character_dynamic_state_endpoint(
    character_id: UUID,
    request: CharacterDynamicStateUpdateRequest,
    character_repo: CharacterRepository = Depends(get_character_repository),
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    character = await character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.status != "published":
        raise HTTPException(status_code=400, detail="只能基于已发布的章节更新角色状态")
    result = await update_character_dynamic_state(
        character=character,
        chapter=chapter,
        db=chapter_repo.db,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    return CharacterDynamicStateUpdateResponse(
        character_id=character_id,
        old_dynamic_state=result["old_dynamic_state"],
        new_dynamic_state=result["new_dynamic_state"],
    )

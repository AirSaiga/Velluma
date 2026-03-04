from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_memory_repository
from backend.repositories import BookRepository, MemoryRepository
from backend.schemas import MemoryChunkCreate, MemoryChunkResponse

router = APIRouter(prefix="/api", tags=["memories"])


@router.get("/memories", response_model=List[MemoryChunkResponse])
async def get_memories(
    book_id: Optional[UUID] = None,
    chapter_id: Optional[UUID] = None,
    repo: MemoryRepository = Depends(get_memory_repository),
):
    return await repo.list(book_id, chapter_id)


@router.post("/memories", response_model=MemoryChunkResponse, status_code=201)
async def create_memory(
    memory_data: MemoryChunkCreate,
    memory_repo: MemoryRepository = Depends(get_memory_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    book = await book_repo.get_by_id(memory_data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await memory_repo.create(memory_data.model_dump())


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: UUID, repo: MemoryRepository = Depends(get_memory_repository)):
    memory = await repo.get_by_id(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="记忆片段不存在")
    await repo.delete(memory)
    return {"message": "记忆片段已删除", "id": str(memory_id)}

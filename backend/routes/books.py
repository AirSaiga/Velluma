from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.dependencies import get_book_repository
from backend.repositories import BookRepository
from backend.schemas import BookCreate, BookUpdate, BookResponse, ChapterResponse, WorldviewUpdate

router = APIRouter(prefix="/api", tags=["books"])


@router.get("/books", response_model=List[BookResponse])
async def get_books(
    repo: BookRepository = Depends(get_book_repository),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    return await repo.list(skip, limit)


@router.get("/books/{book_id}", response_model=BookResponse)
async def get_book(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return book


@router.post("/books", response_model=BookResponse, status_code=201)
async def create_book(book_data: BookCreate, repo: BookRepository = Depends(get_book_repository)):
    return await repo.create(book_data.model_dump())


@router.put("/books/{book_id}", response_model=BookResponse)
async def update_book(book_id: UUID, book_data: BookUpdate, repo: BookRepository = Depends(get_book_repository)):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await repo.update(book, book_data.model_dump(exclude_unset=True))


@router.delete("/books/{book_id}")
async def delete_book(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    await repo.delete(book)
    return {"message": "书籍已删除", "id": str(book_id)}


@router.get("/books/{book_id}/worldview")
async def get_worldview_settings(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"worldview_settings": book.worldview_settings or {}}


@router.patch("/books/{book_id}/worldview")
async def update_worldview_settings(
    book_id: UUID,
    payload: WorldviewUpdate,
    repo: BookRepository = Depends(get_book_repository),
):
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    await repo.update(book, {"worldview_settings": payload.worldview_settings or {}})
    return {"worldview_settings": book.worldview_settings}


@router.get("/books/{book_id}/chapters", response_model=List[ChapterResponse])
async def get_chapters(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    return await repo.list_chapters(book_id)

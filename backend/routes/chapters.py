from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_chapter_repository, get_character_repository
from backend.repositories import BookRepository, ChapterRepository, CharacterRepository
from backend.schemas import (
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    ChapterEntityCreate,
    ChapterPublishRequest,
    ChapterPublishResponse,
    CharacterStateChange,
)
from backend.services.chapter_generation import update_character_dynamic_state

router = APIRouter(prefix="/api", tags=["chapters"])


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(chapter_id: UUID, chapter_repo: ChapterRepository = Depends(get_chapter_repository)):
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.post("/books/{book_id}/chapters", response_model=ChapterResponse, status_code=201)
async def create_chapter(
    book_id: UUID,
    chapter_data: ChapterCreate,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    chapter_payload = chapter_data.model_dump()
    if not chapter_payload.get("chapter_name"):
        chapter_payload["chapter_name"] = f"第{chapter_payload['chapter_number']}章"
    return await chapter_repo.create(chapter_payload)


@router.put("/chapters/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    chapter_id: UUID,
    chapter_data: ChapterUpdate,
    repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    update_dict = chapter_data.model_dump(exclude_unset=True)
    merged_dict = dict(update_dict)
    if "chapter_name" not in merged_dict and not chapter.chapter_name:
        merged_dict["chapter_name"] = f"第{merged_dict.get('chapter_number', chapter.chapter_number)}章"
    if "chapter_name" in merged_dict and not merged_dict["chapter_name"]:
        merged_dict["chapter_name"] = f"第{merged_dict.get('chapter_number', chapter.chapter_number)}章"
    if not merged_dict and not chapter.chapter_name:
        chapter.chapter_name = f"第{chapter.chapter_number}章"
    return await repo.update(chapter, merged_dict)


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: UUID, repo: ChapterRepository = Depends(get_chapter_repository)):
    chapter = await repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await repo.delete(chapter)
    return {"message": "章节已删除", "id": str(chapter_id)}


@router.put("/chapters/{chapter_id}/entities")
async def update_chapter_entities(
    chapter_id: UUID,
    entity_ids: List[UUID],
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    existing_entities = await chapter_repo.list_entities(chapter_id)
    existing_ids = {e.entity_id for e in existing_entities}
    new_ids = set(entity_ids)
    for entity_id in new_ids - existing_ids:
        if await character_repo.get_by_id(entity_id):
            await chapter_repo.add_entity(chapter_id=chapter_id, entity_id=entity_id, entity_type="character")
    for existing in existing_entities:
        if existing.entity_id not in new_ids:
            await chapter_repo.delete_entity(existing)
    await chapter_repo.commit()
    return {"message": "角色关联已更新", "chapter_id": str(chapter_id)}


@router.get("/chapters/{chapter_id}/entities")
async def get_chapter_entities(chapter_id: UUID, repo: ChapterRepository = Depends(get_chapter_repository)):
    entities = await repo.list_entities(chapter_id)
    return {"entity_ids": [str(e.entity_id) for e in entities]}


@router.post("/chapters/{chapter_id}/entities", response_model=ChapterResponse)
async def link_entity_to_chapter(
    chapter_id: UUID,
    entity_data: ChapterEntityCreate,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    entity = await character_repo.get_by_id(entity_data.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="角色不存在")
    await chapter_repo.add_entity(
        chapter_id=chapter_id,
        entity_id=entity_data.entity_id,
        entity_type=entity_data.entity_type,
    )
    return chapter


@router.patch("/chapters/{chapter_id}/publish", response_model=ChapterPublishResponse)
async def publish_chapter(
    chapter_id: UUID,
    request: Optional[ChapterPublishRequest] = None,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.status == "published":
        raise HTTPException(status_code=400, detail="章节已经是发布状态")
    chapter.status = "published"
    character_updates = []
    if request and request.api_key:
        character_list = []
        seen_char_ids = set()
        entities = await chapter_repo.list_entities_with_character(chapter_id)
        if entities:
            for entity in entities:
                if entity.character and entity.character.id not in seen_char_ids:
                    character_list.append(entity.character)
                    seen_char_ids.add(entity.character.id)
        else:
            chapter_char_ids = getattr(chapter, "character_ids", None)
            if chapter_char_ids:
                chars = await character_repo.list_by_ids(chapter_char_ids)
                for char in chars:
                    if char.id not in seen_char_ids:
                        character_list.append(char)
                        seen_char_ids.add(char.id)
        for character in character_list:
            if character:
                try:
                    old_state = character.dynamic_state or "暂无动态状态"
                    await update_character_dynamic_state(
                        character=character,
                        chapter=chapter,
                        db=chapter_repo.db,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                    )
                    new_state = character.dynamic_state or "暂无动态状态"
                    character_updates.append(
                        CharacterStateChange(
                            character_id=character.id,
                            character_name=character.name,
                            old_state=old_state,
                            new_state=new_state,
                        )
                    )
                except Exception:
                    pass
    await chapter_repo.commit()
    await chapter_repo.refresh(chapter)
    return ChapterPublishResponse(chapter_id=chapter.id, status=chapter.status, character_updates=character_updates)

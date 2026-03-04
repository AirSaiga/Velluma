from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.schemas import GenerateChapterRequest, GenerateChapterAgenticRequest
from backend.services.chapter_generation import (
    build_chapter_prompt,
    generate_stream_response,
    call_llm,
    generate_agentic_chapter_stream,
)

router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate_chapter")
async def generate_chapter(
    request: GenerateChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    word_count = request.word_count or 2000
    prompt_data = await build_chapter_prompt(request.chapter_id, chapter_repo.db, word_count)
    return StreamingResponse(
        generate_stream_response(
            system_prompt=prompt_data["system_prompt"],
            user_prompt=prompt_data["user_prompt"],
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.post("/generate_chapter_sync")
async def generate_chapter_sync(
    request: GenerateChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    word_count = request.word_count or 2000
    prompt_data = await build_chapter_prompt(request.chapter_id, chapter_repo.db, word_count)
    content = await call_llm(
        system_prompt=prompt_data["system_prompt"],
        user_prompt=prompt_data["user_prompt"],
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
        temperature=0.7,
    )
    return {"content": content, "prompt": {"system_prompt": prompt_data["system_prompt"], "user_prompt": prompt_data["user_prompt"]}}


@router.post("/generate_chapter_agentic")
async def generate_chapter_agentic(
    request: GenerateChapterAgenticRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return StreamingResponse(
        generate_agentic_chapter_stream(request, chapter_repo.db),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

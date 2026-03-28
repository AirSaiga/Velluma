from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.schemas import (
    GenerateChapterRequest,
    GenerateChapterAgenticRequest,
    GenerateChapterAgenticPreviewResponse,
)
from backend.services.chapter_generation import (
    build_chapter_prompt,
    generate_stream_response,
    call_llm,
    preview_agentic_beats,
)

router = APIRouter(prefix="/api", tags=["chapter_generation"])


@router.post("/generate_chapter")
async def generate_chapter(
    request: GenerateChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：流式生成章节内容，用于实时展示 AI 写作过程。

    参数来源：
    - request: 请求体，包含 chapter_id（目标章节）、word_count、api_key、base_url、model

    数据流：
    1. 获取章节信息（用于上下文）
    2. 构建 prompt（包含世界观、角色设定、记忆片段等）
    3. 以 SSE（Server-Sent Events）流式返回 AI 生成内容

    副作用：
    - 不写入数据库，仅返回流式文本
    - 章节内容需用户确认后手动保存

    性能考量：
    - 流式响应降低首字节时间（TTFB），用户体验更好
    - 需要前端支持 event-stream 解析

    风险点：
    - API Key 暴露风险：前端传 vs 后端配置
    - 当前设计由前端传入，适合 SaaS 场景；内部部署应考虑后端配置
    """
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
    """业务目的：同步生成章节内容，适用于不需要实时预览的场景。

    参数来源：
    - 与流式接口相同

    数据流：
    1-2. 同流式接口
    3. 等待完整响应后一次性返回

    权衡点 vs 流式接口：
    - 优点：实现简单，前端处理容易
    - 缺点：长文本生成时等待时间长（可能超时）
    - 适用场景：短章节、API 超时限制宽松、离线批处理

    性能考量：
    - 默认 temperature=0.7，兼顾创造性与稳定性
    - 返回完整 prompt 便于调试和追溯
    """
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


@router.post("/generate_chapter_agentic_preview_beats", response_model=GenerateChapterAgenticPreviewResponse)
async def generate_chapter_agentic_preview_beats(
    request: GenerateChapterAgenticRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return await preview_agentic_beats(request, chapter_repo.db)



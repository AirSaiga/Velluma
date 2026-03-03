"""
FastAPI 核心接口与路由
StoryWeaver-Core 长篇小说特化 AI 写作平台后端 API

包含:
- 叙事主干系统 CRUD (Book, Chapter)
- 世界观与关系图谱 CRUD (Character, CharacterRelationship)
- 向量记忆 CRUD (MemoryChunk)
- 核心 AI 章节生成引擎 (generate_chapter)
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import json
import os
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from openai import AsyncOpenAI

from backend.database import get_db, init_db
from backend.models import Book, Chapter, Character, CharacterRelationship, MemoryChunk, ChapterEntity
from backend.schemas import (
    BookCreate, BookUpdate, BookResponse,
    ChapterCreate, ChapterUpdate, ChapterResponse,
    CharacterCreate, CharacterUpdate, CharacterResponse,
    RelationshipCreate, RelationshipResponse,
    MemoryChunkCreate, MemoryChunkResponse,
    GenerateChapterRequest,
    GenerateChapterAgenticRequest,
    ChapterEntityCreate,
    WorldviewUpdate,
    CharacterDynamicStateUpdateRequest,
    CharacterDynamicStateUpdateResponse,
    ChapterPublishRequest,
    ChapterPublishResponse,
    CharacterStateChange
)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")
ACTUAL_PORT = None

os.makedirs(DATA_DIR, exist_ok=True)


def save_port(port: int):
    """保存端口号到文件"""
    global ACTUAL_PORT
    ACTUAL_PORT = port
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        f.write(str(port))


def load_port() -> Optional[int]:
    """从文件读取端口号"""
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            pass
    return None


app = FastAPI(
    title="StoryWeaver-Core API",
    description="长篇小说特化 AI 写作平台后端引擎",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "frontend", "dist"
)


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化数据库"""
    await init_db()


@app.get("/")
async def serve_index():
    """服务前端入口页面"""
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "service": "StoryWeaver-Core"}


@app.get("/api/port")
async def get_port():
    """获取当前服务端口号"""
    return {"port": ACTUAL_PORT}


@app.get("/api/books", response_model=List[BookResponse])
async def get_books(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000)
):
    """获取所有书籍列表"""
    result = await db.execute(select(Book).offset(skip).limit(limit))
    return result.scalars().all()


@app.get("/api/books/{book_id}", response_model=BookResponse)
async def get_book(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取单个书籍详情"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return book


@app.post("/api/books", response_model=BookResponse, status_code=201)
async def create_book(book_data: BookCreate, db: AsyncSession = Depends(get_db)):
    """创建新书籍"""
    book = Book(**book_data.model_dump())
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


@app.put("/api/books/{book_id}", response_model=BookResponse)
async def update_book(book_id: UUID, book_data: BookUpdate, db: AsyncSession = Depends(get_db)):
    """更新书籍"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    update_dict = book_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(book, key, value)

    await db.commit()
    await db.refresh(book)
    return book


@app.delete("/api/books/{book_id}")
async def delete_book(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除书籍"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    await db.delete(book)
    await db.commit()
    return {"message": "书籍已删除", "id": str(book_id)}


@app.get("/api/books/{book_id}/worldview")
async def get_worldview_settings(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取书籍的世界观设定"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"worldview_settings": book.worldview_settings or {}}


@app.patch("/api/books/{book_id}/worldview")
async def update_worldview_settings(
    book_id: UUID,
    payload: WorldviewUpdate,
    db: AsyncSession = Depends(get_db)
):
    """更新书籍的世界观设定"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    book.worldview_settings = payload.worldview_settings or {}
    await db.commit()
    await db.refresh(book)
    return {"worldview_settings": book.worldview_settings}


@app.get("/api/books/{book_id}/chapters", response_model=List[ChapterResponse])
async def get_chapters(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取书籍的所有章节"""
    result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == book_id)
        .order_by(Chapter.chapter_number)
    )
    return result.scalars().all()


@app.get("/api/chapters/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(chapter_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取单个章节详情"""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@app.post("/api/books/{book_id}/chapters", response_model=ChapterResponse, status_code=201)
async def create_chapter(book_id: UUID, chapter_data: ChapterCreate, db: AsyncSession = Depends(get_db)):
    """创建新章节"""
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    chapter = Chapter(**chapter_data.model_dump())
    db.add(chapter)
    await db.commit()
    await db.refresh(chapter)
    return chapter


@app.put("/api/chapters/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(chapter_id: UUID, chapter_data: ChapterUpdate, db: AsyncSession = Depends(get_db)):
    """更新章节"""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    update_dict = chapter_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(chapter, key, value)

    await db.commit()
    await db.refresh(chapter)
    return chapter


@app.delete("/api/chapters/{chapter_id}")
async def delete_chapter(chapter_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除章节"""
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    await db.delete(chapter)
    await db.commit()
    return {"message": "章节已删除", "id": str(chapter_id)}


@app.put("/api/chapters/{chapter_id}/entities")
async def update_chapter_entities(
    chapter_id: UUID,
    entity_ids: List[UUID],
    db: AsyncSession = Depends(get_db)
):
    """批量更新章节的角色关联"""
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    existing_result = await db.execute(
        select(ChapterEntity).where(ChapterEntity.chapter_id == chapter_id)
    )
    existing_entities = existing_result.scalars().all()
    existing_ids = {e.entity_id for e in existing_entities}

    new_ids = set(entity_ids)

    for entity_id in new_ids - existing_ids:
        character_result = await db.execute(select(Character).where(Character.id == entity_id))
        if character_result.scalar_one_or_none():
            new_entity = ChapterEntity(
                chapter_id=chapter_id,
                entity_id=entity_id,
                entity_type="character"
            )
            db.add(new_entity)

    for existing in existing_entities:
        if existing.entity_id not in new_ids:
            await db.delete(existing)

    await db.commit()

    return {"message": "角色关联已更新", "chapter_id": str(chapter_id)}


@app.get("/api/chapters/{chapter_id}/entities")
async def get_chapter_entities(
    chapter_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取章节的角色关联"""
    result = await db.execute(
        select(ChapterEntity).where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = result.scalars().all()
    return {"entity_ids": [str(e.entity_id) for e in entities]}


@app.post("/api/chapters/{chapter_id}/entities", response_model=ChapterResponse)
async def link_entity_to_chapter(
    chapter_id: UUID,
    entity_data: ChapterEntityCreate,
    db: AsyncSession = Depends(get_db)
):
    """将角色关联到章节"""
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    entity_result = await db.execute(select(Character).where(Character.id == entity_data.entity_id))
    entity = entity_result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="角色不存在")

    chapter_entity = ChapterEntity(
        chapter_id=chapter_id,
        entity_id=entity_data.entity_id,
        entity_type=entity_data.entity_type
    )
    db.add(chapter_entity)
    await db.commit()

    return chapter


@app.get("/api/books/{book_id}/characters", response_model=List[CharacterResponse])
async def get_characters(book_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取书籍的所有角色"""
    result = await db.execute(
        select(Character)
        .where(Character.book_id == book_id)
        .order_by(Character.importance_level.desc())
    )
    return result.scalars().all()


@app.get("/api/characters/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: UUID, db: AsyncSession = Depends(get_db)):
    """获取单个角色详情"""
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return character


@app.post("/api/characters", response_model=CharacterResponse, status_code=201)
async def create_character(character_data: CharacterCreate, db: AsyncSession = Depends(get_db)):
    """创建新角色"""
    result = await db.execute(select(Book).where(Book.id == character_data.book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    character = Character(**character_data.model_dump())
    db.add(character)
    await db.commit()
    await db.refresh(character)
    return character


@app.put("/api/characters/{character_id}", response_model=CharacterResponse)
async def update_character(character_id: UUID, character_data: CharacterUpdate, db: AsyncSession = Depends(get_db)):
    """更新角色"""
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    update_dict = character_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(character, key, value)

    await db.commit()
    await db.refresh(character)
    return character


@app.delete("/api/characters/{character_id}")
async def delete_character(character_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除角色"""
    result = await db.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")

    await db.delete(character)
    await db.commit()
    return {"message": "角色已删除", "id": str(character_id)}


@app.get("/api/relationships", response_model=List[RelationshipResponse])
async def get_relationships(
    book_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取角色关系列表"""
    if book_id:
        result = await db.execute(
            select(CharacterRelationship)
            .join(Character, CharacterRelationship.source_char_id == Character.id)
            .where(Character.book_id == book_id)
        )
    else:
        result = await db.execute(select(CharacterRelationship))
    return result.scalars().all()


@app.post("/api/relationships", response_model=RelationshipResponse, status_code=201)
async def create_relationship(relationship_data: RelationshipCreate, db: AsyncSession = Depends(get_db)):
    """创建角色关系"""
    source_result = await db.execute(select(Character).where(Character.id == relationship_data.source_char_id))
    source_char = source_result.scalar_one_or_none()
    if not source_char:
        raise HTTPException(status_code=404, detail="源角色不存在")

    target_result = await db.execute(select(Character).where(Character.id == relationship_data.target_char_id))
    target_char = target_result.scalar_one_or_none()
    if not target_char:
        raise HTTPException(status_code=404, detail="目标角色不存在")

    existing = await db.execute(
        select(CharacterRelationship).where(
            CharacterRelationship.source_char_id == relationship_data.source_char_id,
            CharacterRelationship.target_char_id == relationship_data.target_char_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="关系已存在")

    relationship = CharacterRelationship(**relationship_data.model_dump())
    db.add(relationship)
    await db.commit()
    await db.refresh(relationship)
    return relationship


@app.delete("/api/relationships/{relationship_id}")
async def delete_relationship(relationship_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除角色关系"""
    result = await db.execute(select(CharacterRelationship).where(CharacterRelationship.id == relationship_id))
    relationship = result.scalar_one_or_none()
    if not relationship:
        raise HTTPException(status_code=404, detail="关系不存在")

    await db.delete(relationship)
    await db.commit()
    return {"message": "关系已删除", "id": str(relationship_id)}


@app.get("/api/memories", response_model=List[MemoryChunkResponse])
async def get_memories(
    book_id: Optional[UUID] = None,
    chapter_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """获取记忆片段列表"""
    query = select(MemoryChunk)
    if book_id:
        query = query.where(MemoryChunk.book_id == book_id)
    if chapter_id:
        query = query.where(MemoryChunk.chapter_id == chapter_id)

    result = await db.execute(query.order_by(MemoryChunk.created_at.desc()))
    return result.scalars().all()


@app.post("/api/memories", response_model=MemoryChunkResponse, status_code=201)
async def create_memory(memory_data: MemoryChunkCreate, db: AsyncSession = Depends(get_db)):
    """创建记忆片段"""
    result = await db.execute(select(Book).where(Book.id == memory_data.book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")

    memory = MemoryChunk(**memory_data.model_dump())
    db.add(memory)
    await db.commit()
    await db.refresh(memory)
    return memory


@app.delete("/api/memories/{memory_id}")
async def delete_memory(memory_id: UUID, db: AsyncSession = Depends(get_db)):
    """删除记忆片段"""
    result = await db.execute(select(MemoryChunk).where(MemoryChunk.id == memory_id))
    memory = result.scalar_one_or_none()
    if not memory:
        raise HTTPException(status_code=404, detail="记忆片段不存在")

    await db.delete(memory)
    await db.commit()
    return {"message": "记忆片段已删除", "id": str(memory_id)}


async def build_chapter_prompt(chapter_id: UUID, db: AsyncSession, word_count: int = 2000) -> dict:
    """
    构建章节生成所需的完整 Prompt

    组装公式: Prompt_Total = F_Sys_Global + F_Static_State + F_Dynamic_State + F_Relationships + F_Task_Outline

    Returns:
        dict: 包含 system_prompt 和 user_prompt 的字典
    """
    print(f"[DEBUG] build_chapter_prompt: 开始构建, chapter_id={chapter_id}")
    
    chapter_result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.book))
        .where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        print(f"[DEBUG] build_chapter_prompt: 章节不存在")
        raise HTTPException(status_code=404, detail="章节不存在")

    print(f"[DEBUG] build_chapter_prompt: 找到章节: {chapter.title}")

    book = chapter.book
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings
    worldview_prompt = f"【世界观设定】\n{worldview_settings}" if worldview_settings else None

    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()
    print(f"[DEBUG] build_chapter_prompt: 找到 {len(entities)} 个实体")

    static_states = []
    dynamic_states = []
    character_ids = []

    for entity in entities:
        character = entity.character
        if character:
            character_ids.append(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")

    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids)
        )
    )
    relationships = relationships_result.scalars().all()

    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")

    system_prompt_parts = [
        global_sys_prompt,
        worldview_prompt if worldview_prompt else "",
        "\n\n## 角色静态设定",
        "\n".join(static_states) if static_states else "暂无角色设定",
        "\n\n## 角色动态状态",
        "\n".join(dynamic_states) if dynamic_states else "暂无动态状态",
        "\n\n## 角色互动约束",
        "\n".join(relationship_prompts) if relationship_prompts else "暂无互动约束",
        "\n\n## 【强制字数要求 - 最高优先级】",
        f"★ 生成内容必须精确控制在 {word_count} 字 (±100字误差可接受)",
        "★ 这是最强约束，必须严格遵守，不得少于或超过此字数限制",
        "★ 规划好内容结构，确保最终字数符合要求",
        "\n\n## 核心规则",
        "1. 严格遵循章节大纲进行创作",
        "2. 保持角色性格和互动方式的连贯性",
        "3. 根据角色关系约束调整互动氛围",
        "4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等",
        "5. 生成内容必须满足上述字数要求",
    ]

    system_prompt = "\n".join(system_prompt_parts)

    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

请直接输出小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""

    print(f"[DEBUG] build_chapter_prompt: 构建完成")
    
    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "chapter": chapter
    }


async def generate_stream_response(system_prompt: str, user_prompt: str, api_key: str, base_url: Optional[str], model: str):
    """
    生成 SSE 流式响应的异步生成器

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        api_key: OpenAI API Key
        base_url: 自定义 API 端点
        model: 使用的模型名称

    Yields:
        SSE 格式的文本片段
    """
    import os
    import traceback
    import httpx
    for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        if env_var in os.environ:
            del os.environ[env_var]
    print(f"[DEBUG] generate_stream_response: 开始生成, model={model}, base_url={base_url}")
    print(f"[DEBUG] api_key 前5位: {api_key[:5] if api_key else 'None'}")
    print(f"[DEBUG] 环境变量检查: HTTP_PROXY={os.environ.get('HTTP_PROXY')}, HTTPS_PROXY={os.environ.get('HTTPS_PROXY')}, ALL_PROXY={os.environ.get('ALL_PROXY')}")
    
    yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
    
    http_client = None
    try:
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        http_client = httpx.AsyncClient(trust_env=False)
        client_kwargs["http_client"] = http_client

        print(f"[DEBUG] client_kwargs: {list(client_kwargs.keys())}")
        
        print(f"[DEBUG] 即将创建 AsyncOpenAI...")
        client = AsyncOpenAI(**client_kwargs)
        print(f"[DEBUG] AsyncOpenAI 创建成功")

        stream = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            stream=True,
            temperature=0.7,
            max_tokens=4000
        )
        print(f"[DEBUG] generate_stream_response: API 调用成功, 开始流式输出...")

        chunk_count = 0
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                chunk_count += 1
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        print(f"[DEBUG] generate_stream_response: 流式输出完成, 共 {chunk_count} 个 chunks")
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    except Exception as e:
        import traceback
        raw_error_msg = str(e).strip()
        error_type = type(e).__name__
        response = getattr(e, "response", None)
        status_code = getattr(response, "status_code", None) if response is not None else None
        response_text = None
        if response is not None:
            try:
                response_text = response.text
            except Exception:
                response_text = None
        if isinstance(response_text, str):
            response_text = response_text.strip()
            if len(response_text) > 500:
                response_text = response_text[:500] + "..."
        parts = [error_type]
        if raw_error_msg:
            parts.append(raw_error_msg)
        if status_code:
            parts.append(f"status={status_code}")
        if response_text:
            parts.append(response_text)
        error_msg = " | ".join(parts)
        traceback.print_exc()
        print(f"[DEBUG] generate_stream_response: 发生异常: {error_msg}")
        yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    finally:
        if http_client is not None:
            await http_client.aclose()


@app.post("/api/generate_chapter")
async def generate_chapter(
    request: GenerateChapterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    核心 AI 章节生成接口

    执行完整的 Prompt 组装流水线并返回 SSE 流式响应

    Prompt 组装公式:
    Prompt_Total = F_Sys_Global + F_Static_State + F_Dynamic_State + F_Relationships + F_Task_Outline
    """
    print(f"[DEBUG] generate_chapter: 开始处理章节 {request.chapter_id}")
    
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        print(f"[DEBUG] generate_chapter: 章节不存在 {request.chapter_id}")
        raise HTTPException(status_code=404, detail="章节不存在")

    print(f"[DEBUG] generate_chapter: 正在构建 Prompt...")
    word_count = request.word_count or 2000
    print(f"[DEBUG] generate_chapter: 字数要求: {word_count}")
    prompt_data = await build_chapter_prompt(request.chapter_id, db, word_count)
    print(f"[DEBUG] generate_chapter: Prompt 构建完成, system_prompt 长度: {len(prompt_data['system_prompt'])}, user_prompt 长度: {len(prompt_data['user_prompt'])}")

    print(f"[DEBUG] generate_chapter: 开始流式响应...")
    return StreamingResponse(
        generate_stream_response(
            system_prompt=prompt_data["system_prompt"],
            user_prompt=prompt_data["user_prompt"],
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@app.post("/api/generate_chapter_sync")
async def generate_chapter_sync(
    request: GenerateChapterRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    非流式章节生成接口

    等待完整内容生成后一次性返回
    """
    import httpx
    
    print(f"[DEBUG] generate_chapter_sync: 开始处理章节 {request.chapter_id}")
    
    for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        if env_var in os.environ:
            del os.environ[env_var]
    
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        print(f"[DEBUG] generate_chapter_sync: 章节不存在 {request.chapter_id}")
        raise HTTPException(status_code=404, detail="章节不存在")

    print(f"[DEBUG] generate_chapter_sync: 正在构建 Prompt...")
    word_count = request.word_count or 2000
    prompt_data = await build_chapter_prompt(request.chapter_id, db, word_count)
    print(f"[DEBUG] generate_chapter_sync: Prompt 构建完成")

    print(f"[DEBUG] generate_chapter_sync: 开始非流式生成...")
    
    client_kwargs = {"api_key": request.api_key}
    if request.base_url:
        client_kwargs["base_url"] = request.base_url
    
    http_client = httpx.AsyncClient(trust_env=False)
    client_kwargs["http_client"] = http_client
    
    try:
        client = AsyncOpenAI(**client_kwargs)
        
        response = await client.chat.completions.create(
            model=request.model,
            messages=[
                {"role": "system", "content": prompt_data["system_prompt"]},
                {"role": "user", "content": prompt_data["user_prompt"]}
            ],
            temperature=0.7,
            max_tokens=4000
        )
        
        content = response.choices[0].message.content if response.choices else ""
        print(f"[DEBUG] generate_chapter_sync: 生成完成, 内容长度: {len(content)}")
        
        return {"content": content}
    finally:
        await http_client.aclose()


def build_draft_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, word_count: int) -> tuple:
    """
    构建 Draft Agent (主笔) 的 Prompt
    
    Returns:
        (system_prompt, user_prompt)
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    
    static_states = []
    dynamic_states = []
    for entity in entities:
        character = entity.character if hasattr(entity, 'character') else entity
        if character:
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")
    
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")
    
    system_prompt = f"""{global_sys_prompt}

{worldview_prompt if worldview_prompt else ''}

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## 【强制字数要求 - 最高优先级】
★ 生成内容必须精确控制在 {word_count} 字 (±100字误差可接受)
★ 这是最强约束，必须严格遵守，不得少于或超过此字数限制

## 核心规则
1. 严格遵循章节大纲进行创作
2. 保持角色性格和互动方式的连贯性
3. 根据角色关系约束调整互动氛围
4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等
5. 生成内容必须满足上述字数要求"""

    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

请直接输出小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""

    return system_prompt, user_prompt


def build_review_agent_prompt(
    book: Book,
    entities: list,
    relationships: list,
    chapter_outline: str,
    draft_text: str
) -> tuple:
    """
    构建 Review Agent (审阅) 的 Prompt
    强制要求 JSON 输出格式
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    
    static_states = []
    for entity in entities:
        character = entity.character if hasattr(entity, 'character') else entity
        if character and character.static_prompt:
            static_states.append(f"【{character.name}】{character.static_prompt}")
    
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")

    system_prompt = f"""{global_sys_prompt}

你是一个严格的小说质量审查员。你不负责写小说，只负责检查初稿是否符合要求。

{worldview_prompt if worldview_prompt else ''}

## 角色设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## 你的任务
1. 检查初稿是否遵循了章节大纲要求
2. 检查角色是否出现 OOC (Out Of Character，人设崩塌)
3. 检查是否有逻辑硬伤或情节漏洞
4. 检查是否遗漏了应该有的剧情点

## 输出格式要求
你必须以 JSON 格式输出，结构如下：
{{
    "pass": true/false,
    "issues": [
        {{
            "type": "OOC/剧情遗漏/逻辑硬伤",
            "severity": "high/medium/low",
            "description": "详细描述问题"
        }}
    ],
    "revision_plan": "给出具体的重写建议"
}}

- pass: true 表示所有检查通过，可以直接输出
- pass: false 表示存在问题，需要重写
- issues: 列出发现的问题
- revision_plan: 给出具体的重写指导

注意：你必须输出合法的 JSON 格式，不要输出任何其他内容！"""

    user_prompt = f"""请审查以下初稿:

【章节大纲】
{chapter_outline}

【初稿内容】
{draft_text}

请输出 JSON 格式的审查结果。"""

    return system_prompt, user_prompt


def build_refine_agent_prompt(
    chapter: Chapter,
    book: Book,
    entities: list,
    relationships: list,
    draft_text: str,
    revision_plan: str,
    word_count: int
) -> tuple:
    """
    构建 Refine Agent (精修) 的 Prompt
    根据审查意见重写初稿
    """
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    
    static_states = []
    dynamic_states = []
    for entity in entities:
        character = entity.character if hasattr(entity, 'character') else entity
        if character:
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")
    
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")

    system_prompt = f"""{global_sys_prompt}

{worldview_prompt if worldview_prompt else ''}

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## 【强制字数要求 - 最高优先级】
★ 生成内容必须精确控制在 {word_count} 字 (±100字误差可接受)
★ 这是最强约束，必须严格遵守，不得少于或超过此字数限制

## 你的任务
你是一个精修编辑，需要根据审查意见对初稿进行针对性重写。
请仔细阅读以下审查意见和初稿，然后生成修改后的版本。

## 核心规则
1. 严格遵循审查意见进行修改
2. 保持原有优秀的部分
3. 修正被指出的问题
4. 确保修改后的内容符合章节大纲
5. 保持角色性格一致性
6. 生成内容必须满足上述字数要求"""

    user_prompt = f"""请根据以下审查意见重写初稿:

【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【字数要求】必须生成恰好 {word_count} 字的小说正文（±100字误差可接受）

【审查意见】
{revision_plan}

【当前初稿】
{draft_text}

请直接输出修改后的完整小说正文，不需要任何额外说明或标记。确保最终输出字数符合上述要求！"""

    return system_prompt, user_prompt


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    temperature: float = 0.7,
    response_format: Optional[dict] = None
) -> str:
    """
    调用 LLM 的辅助函数
    """
    import httpx
    import json
    
    for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        if env_var in os.environ:
            del os.environ[env_var]
    
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    
    http_client = httpx.AsyncClient(trust_env=False)
    client_kwargs["http_client"] = http_client
    
    try:
        client = AsyncOpenAI(**client_kwargs)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        create_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 4000
        }
        
        if response_format:
            create_kwargs["response_format"] = response_format
        
        response = await client.chat.completions.create(**create_kwargs)
        
        content = ""
        if response.choices and response.choices[0].message.content:
            content = response.choices[0].message.content
        
        print(f"[DEBUG] LLM 返回内容长度: {len(content)}")
        return content
    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)
        print(f"[ERROR] LLM 调用失败: {error_type} - {error_msg}")
        
        if "JSONDecodeError" in error_type or "Expecting value" in error_msg:
            return ""
        
        raise
    finally:
        await http_client.aclose()


async def generate_agentic_chapter_stream(
    request: GenerateChapterAgenticRequest,
    db: AsyncSession
):
    """
    Actor-Critic 模式章节生成核心函数
    实现 Draft -> Review -> Refine 三阶段工作流
    """
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        yield f"data: {json.dumps({'error': '章节不存在'}, ensure_ascii=False)}\n\n"
        return
    
    max_iterations = request.max_iterations
    word_count = request.word_count or 2000
    
    yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在从数据库抽取人物卡与关系网...'}, ensure_ascii=False)}\n\n"
    
    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()
    
    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == request.chapter_id)
    )
    entities = entities_result.scalars().all()
    
    character_ids = [e.entity_id for e in entities]
    
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids)
        )
    )
    relationships = relationships_result.scalars().all()
    
    current_draft = ""
    revision_plan = ""
    iteration = 0
    review_passed = False
    
    while iteration < max_iterations:
        iteration += 1
        print(f"[DEBUG] Actor-Critic Workflow: 第 {iteration} 轮迭代")
        
        if iteration == 1:
            yield f"data: {json.dumps({'event': 'DRAFTING', 'message': '主笔 Agent 正在创作初稿...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            
            system_prompt, user_prompt = build_draft_agent_prompt(
                chapter, book, entities, relationships, word_count
            )
            
            current_draft = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.7
            )
            
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
            
            print(f"[DEBUG] Actor-Critic Workflow: Draft 完成, 长度={len(current_draft)}")
        else:
            yield f"data: {json.dumps({'event': 'REFINING', 'message': f'发现逻辑遗漏，正在通知责编重写 (第{iteration}次)...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            
            system_prompt, user_prompt = build_refine_agent_prompt(
                chapter, book, entities, relationships,
                current_draft, revision_plan, word_count
            )
            
            current_draft = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.7
            )
            
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
            
            print(f"[DEBUG] Actor-Critic Workflow: Refine 完成, 长度={len(current_draft)}")
        
        yield f"data: {json.dumps({'event': 'REVIEWING', 'message': '审阅 Agent 正在进行逻辑校验和 OOC 排查...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
        
        system_prompt, user_prompt = build_review_agent_prompt(
            book, entities, relationships,
            chapter.outline_text or '', current_draft
        )
        
        review_result_json = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        print(f"[DEBUG] Review Agent 返回内容长度: {len(review_result_json) if review_result_json else 0}")
        
        try:
            if not review_result_json or not review_result_json.strip():
                raise ValueError("Empty response from Review Agent")
            review_result = json.loads(review_result_json)
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[WARN] Review JSON 解析失败: {e}, 使用默认通过")
            review_result = {
                "pass": True,
                "issues": [],
                "revision_plan": "JSON 解析失败，跳过审查"
            }
        
        chapter.review_feedback = review_result
        await db.commit()
        
        print(f"[DEBUG] Actor-Critic Workflow: Review 完成, pass={review_result.get('pass', True)}")
        
        if review_result.get("pass", True):
            review_passed = True
            print(f"[DEBUG] Actor-Critic Workflow: 审查通过，迭代结束")
            break
        else:
            revision_plan = review_result.get("revision_plan", "")
            issues = review_result.get("issues", [])
            print(f"[DEBUG] Actor-Critic Workflow: 审查未通过, issues={len(issues)}")
    
    chapter.content_text = current_draft
    await db.commit()
    
    yield f"data: {json.dumps({'event': 'FINAL_TEXT_STREAM', 'message': '正在输出最终文本...', 'passed': review_passed, 'iterations': iteration}, ensure_ascii=False)}\n\n"
    
    for char in current_draft:
        yield f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': char}, ensure_ascii=False)}\n\n"
    
    yield f"data: {json.dumps({'event': 'DONE', 'passed': review_passed, 'iterations': iteration, 'revision_count': iteration}, ensure_ascii=False)}\n\n"


@app.post("/api/generate_chapter_agentic")
async def generate_chapter_agentic(
    request: GenerateChapterAgenticRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Actor-Critic 模式章节生成接口
    
    实现三阶段工作流: Draft -> Review -> Refine
    通过 SSE 推送各阶段状态事件
    """
    print(f"[DEBUG] generate_chapter_agentic: 开始处理章节 {request.chapter_id}")
    
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    return StreamingResponse(
        generate_agentic_chapter_stream(request, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


async def update_character_dynamic_state(
    character: Character,
    chapter: Chapter,
    db: AsyncSession,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini"
) -> dict:
    """
    更新角色动态状态的辅助函数
    
    Args:
        character: 角色对象
        chapter: 章节对象
        db: 数据库会话
        api_key: OpenAI API Key
        base_url: 自定义 API 端点
        model: 使用的模型名称
    
    Returns:
        dict: 包含 old_dynamic_state 和 new_dynamic_state 的字典
    """
    import httpx
    
    old_dynamic_state = character.dynamic_state or "暂无动态状态"
    
    history_states = []
    if character.dynamic_state_history:
        for item in character.dynamic_state_history[-3:]:
            state = item.get("state", "")
            updated_at = item.get("updated_at", "")
            if state:
                history_states.append(f"- {updated_at}: {state}")
    
    history_str = "\n".join(history_states) if history_states else "暂无历史状态"
    
    prompt = f"""角色动态状态更新提示词：

【角色信息】
角色名：{character.name}
角色设定：{character.static_prompt or "暂无设定"}

【当前动态状态】
{old_dynamic_state}

【历史动态状态】
{history_str}

【本章情节】
章节标题：{chapter.title or "未命名"}
章节大纲：{chapter.outline_text or "暂无大纲"}
章节正文：{chapter.content_text or "暂无正文"}

【任务】
请分析上述角色在本章中的表现和状态变化，更新角色的动态状态描述。
要求：
1. 保持角色性格的一致性
2. 描述角色当前的心理状态、情感、与其他角色的关系变化
3. 输出简洁的动态状态描述（100-300字）
4. 直接输出更新后的动态状态，不要有额外说明
"""
    
    for env_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        if env_var in os.environ:
            del os.environ[env_var]
    
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    
    http_client = httpx.AsyncClient(trust_env=False)
    client_kwargs["http_client"] = http_client
    
    try:
        client = AsyncOpenAI(**client_kwargs)
        
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的小说写作助手，擅长分析角色心理和情感变化。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        
        new_dynamic_state = response.choices[0].message.content if response.choices else old_dynamic_state
        new_dynamic_state = new_dynamic_state.strip()
        
        character.dynamic_state = new_dynamic_state
        
        history = character.dynamic_state_history or []
        history.append({
            "state": new_dynamic_state,
            "updated_at": datetime.utcnow().isoformat()
        })
        
        if len(history) > 10:
            history = history[-10:]
        
        character.dynamic_state_history = history
        
        await db.commit()
        await db.refresh(character)
        
        return {
            "old_dynamic_state": old_dynamic_state,
            "new_dynamic_state": new_dynamic_state
        }
    finally:
        await http_client.aclose()


@app.patch("/api/chapters/{chapter_id}/publish", response_model=ChapterPublishResponse)
async def publish_chapter(
    chapter_id: UUID,
    request: Optional[ChapterPublishRequest] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    发布章节并将章节状态从 "draft" 变更为 "published"
    如果提供了 api_key，则同时触发关联角色的动态状态更新
    """
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if chapter.status == "published":
        raise HTTPException(status_code=400, detail="章节已经是发布状态")
    
    chapter.status = "published"
    
    character_updates = []
    
    if request and request.api_key:
        character_list = []
        
        entities_result = await db.execute(
            select(ChapterEntity)
            .options(selectinload(ChapterEntity.character))
            .where(ChapterEntity.chapter_id == chapter_id)
        )
        entities = entities_result.scalars().all()
        print(f"[DEBUG] publish_chapter: 找到 {len(entities)} 个 ChapterEntity")
        
        if entities:
            for entity in entities:
                if entity.character:
                    character_list.append(entity.character)
                    print(f"[DEBUG] publish_chapter: 添加角色 {entity.character.name}")
        else:
            print(f"[DEBUG] publish_chapter: 没有 ChapterEntity，尝试从 character_ids 获取")
            chapter_char_ids = getattr(chapter, 'character_ids', None)
            print(f"[DEBUG] publish_chapter: chapter_char_ids = {chapter_char_ids}")
            if chapter_char_ids:
                char_result = await db.execute(
                    select(Character).where(Character.id.in_(chapter_char_ids))
                )
                character_list = list(char_result.scalars().all())
        
        print(f"[DEBUG] publish_chapter: 最终 character_list 长度为 {len(character_list)}")
        
        for character in character_list:
            if character:
                try:
                    old_state = character.dynamic_state or "暂无动态状态"
                    await update_character_dynamic_state(
                        character=character,
                        chapter=chapter,
                        db=db,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model
                    )
                    new_state = character.dynamic_state or "暂无动态状态"
                    character_updates.append(CharacterStateChange(
                        character_id=character.id,
                        character_name=character.name,
                        old_state=old_state,
                        new_state=new_state
                    ))
                except Exception as e:
                    print(f"[WARN] 更新角色 {character.name} 动态状态失败: {e}")
    
    await db.commit()
    await db.refresh(chapter)
    
    return ChapterPublishResponse(
        chapter_id=chapter.id,
        status=chapter.status,
        character_updates=character_updates
    )


@app.post("/api/characters/{character_id}/update-dynamic-state")
async def update_character_dynamic_state_endpoint(
    character_id: UUID,
    request: CharacterDynamicStateUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    更新角色动态状态的 API 端点
    
    根据章节内容，使用 LLM 生成角色新的动态状态，
    并保存到 dynamic_state 字段，同时追加到 dynamic_state_history
    """
    character_result = await db.execute(select(Character).where(Character.id == character_id))
    character = character_result.scalar_one_or_none()
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    if chapter.status != "published":
        raise HTTPException(status_code=400, detail="只能基于已发布的章节更新角色状态")
    
    result = await update_character_dynamic_state(
        character=character,
        chapter=chapter,
        db=db,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model
    )
    
    return CharacterDynamicStateUpdateResponse(
        character_id=character_id,
        old_dynamic_state=result["old_dynamic_state"],
        new_dynamic_state=result["new_dynamic_state"]
    )


@app.get("/{path:path}")
async def serve_static(path: str):
    """服务静态文件"""
    # 显式禁止 API 路径回退到 index.html，避免混淆
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")

    file_path = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = 8002
    print(f"🚀 后端服务启动，固定端口: {port}")

    config = uvicorn.Config(app, host="127.0.0.1", port=port)
    server = uvicorn.Server(config)

    print(f"✅ StoryWeaver-Core 后端服务启动")

    server.run()

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
    ChapterEntityCreate
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


@app.get("/{path:path}")
async def serve_static(path: str):
    """服务静态文件"""
    file_path = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


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


async def build_chapter_prompt(chapter_id: UUID, db: AsyncSession) -> dict:
    """
    构建章节生成所需的完整 Prompt

    组装公式: Prompt_Total = F_Sys_Global + F_Static_State + F_Dynamic_State + F_Relationships + F_Task_Outline

    Returns:
        dict: 包含 system_prompt 和 user_prompt 的字典
    """
    chapter_result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.book))
        .where(Chapter.id == chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    book = chapter.book
    global_sys_prompt = book.global_sys_prompt or "你是一个专业的小说写作助手。"

    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()

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
        select(CharacterRelationship).where(
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
        "\n\n## 角色静态设定",
        "\n".join(static_states) if static_states else "暂无角色设定",
        "\n\n## 角色动态状态",
        "\n".join(dynamic_states) if dynamic_states else "暂无动态状态",
        "\n\n## 角色互动约束",
        "\n".join(relationship_prompts) if relationship_prompts else "暂无互动约束",
        "\n\n## 核心规则",
        "1. 严格遵循章节大纲进行创作",
        "2. 保持角色性格和互动方式的连贯性",
        "3. 根据角色关系约束调整互动氛围",
        "4. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等",
    ]

    system_prompt = "\n".join(system_prompt_parts)

    user_prompt = f"""请根据以下章节大纲进行扩写:

【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}

请直接输出小说正文，不需要任何额外说明或标记。"""

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "chapter": chapter
    }


async def generate_stream_response(chapter_id: UUID, api_key: str, base_url: Optional[str], model: str, db: AsyncSession):
    """
    生成 SSE 流式响应的异步生成器

    Args:
        chapter_id: 章节ID
        api_key: OpenAI API Key
        base_url: 自定义 API 端点
        model: 使用的模型名称
        db: 数据库会话

    Yields:
        SSE 格式的文本片段
    """
    prompt_data = await build_chapter_prompt(chapter_id, db)
    system_prompt = prompt_data["system_prompt"]
    user_prompt = prompt_data["user_prompt"]

    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url

    client = AsyncOpenAI(**client_kwargs)

    try:
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

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    except Exception as e:
        error_msg = str(e)
        yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"


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
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    return StreamingResponse(
        generate_stream_response(
            chapter_id=request.chapter_id,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            db=db
        ),
        media_type="text/event-stream"
    )


if __name__ == "__main__":
    import uvicorn

    env_port = os.environ.get('VELLUMA_PORT')
    if env_port:
        port = int(env_port)
        print(f"🚀 使用环境变量指定的端口: {port}")
    else:
        port = 0
        print(f"🚀 使用动态端口分配")

    config = uvicorn.Config(app, host="127.0.0.1", port=port)
    server = uvicorn.Server(config)

    print(f"✅ StoryWeaver-Core 后端服务启动")

    server.run()

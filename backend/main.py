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
    ChapterEntityCreate,
    WorldviewUpdate
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

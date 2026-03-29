"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
记忆/RAG 管理路由模块。

职责：提供记忆块的 CRUD API，支持 AI 写作的上下文检索（RAG）功能。

业务场景：
- 创建记忆块（手动或自动从章节提取）
- 检索记忆块（基于向量相似度）
- 获取记忆列表（支持按书籍/章节过滤）
- 更新记忆内容
- 删除记忆

设计说明：
- 记忆块包含 embedding 向量，用于语义检索
- 检索时计算余弦相似度，结合时间衰减和伏笔权重
- 支持全局、书籍级、章节级三种粒度

数据模型：
- MemoryChunk: 记忆实体（含 embedding）
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_book_repository, get_memory_repository, get_chapter_repository, get_db
from backend.models import MemoryChunk
from backend.repositories import BookRepository, ChapterRepository, MemoryRepository
from backend.repositories.base import QuerySpec
from backend.schemas import MemoryChunkCreate, MemoryChunkResponse, GenerateEmbeddingRequest

router = APIRouter(prefix="/api", tags=["memories"])


# =============================================================================
# 记忆片段查询 - 支持多维度筛选
# =============================================================================

@router.get("/memories", response_model=List[MemoryChunkResponse])
async def get_memories(
    book_id: Optional[UUID] = None,
    chapter_id: Optional[UUID] = None,
    repo: MemoryRepository = Depends(get_memory_repository),
):
    """业务目的：查询记忆片段，支持按书籍或章节筛选。

    参数来源：
    - book_id: 可选 Query 参数，按书籍筛选
    - chapter_id: 可选 Query 参数，按章节筛选
    - 两者都传时如何处理取决于 repo.list() 实现

    数据流：
    - 传入的参数会下推到 SQL WHERE 条件
    - 无参数时返回所有记忆片段（可能量大，需考虑分页扩展）

    性能考量：
    - 无分页参数，大数据集场景可能引发性能问题
    - 建议：未来增加 skip/limit 参数支持分页
    - 记忆片段内容可能较长，注意数据库文本字段类型选择
    """
    return await repo.list(book_id, chapter_id)


# =============================================================================
# 记忆片段生命周期
# =============================================================================

@router.post("/memories", response_model=MemoryChunkResponse, status_code=201)
async def create_memory(
    memory_data: MemoryChunkCreate,
    memory_repo: MemoryRepository = Depends(get_memory_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    """业务目的：创建新的记忆片段，用于存储重要的世界观信息或剧情要点。

    参数来源：
    - memory_data: 请求体，包含 content、book_id、chapter_id（可选）等

    数据流：
    1. 验证书籍存在（记忆片段必须属于某本书）
    2. 写入数据库
    3. 返回新创建的记忆

    副作用：
    - 数据库 INSERT 操作

    业务定位：
    - 记忆片段是"世界观的持久化存储"，区别于角色的 dynamic_state
    - 典型用途：存储重要事件、伏线提示、世界规则等
    - 会在 AI 生成时被注入上下文，提升内容一致性
    """
    book = await book_repo.get_by_id(memory_data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await memory_repo.create(memory_data.model_dump())


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: UUID, repo: MemoryRepository = Depends(get_memory_repository)):
    """业务目的：删除不再需要的记忆片段。

    参数来源：
    - memory_id: 路径参数

    副作用：
    - 数据库 DELETE 操作，物理删除记录

    权衡点：
    - 未实现 soft_delete，因为记忆片段作为辅助信息，
      误删影响相对可控（可重新创建）
    - 对比：书籍/章节删除采用物理删除，因为涉及级联关系
    """
    memory = await repo.get_by_id(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="记忆片段不存在")
    await repo.delete(memory)
    return {"message": "记忆片段已删除", "id": str(memory_id)}


# =============================================================================
# 章节向量生成 - 用于测试 RAG 功能
# =============================================================================

@router.post("/chapters/{chapter_id}/generate-embedding")
async def generate_chapter_embedding(
    chapter_id: UUID,
    request: GenerateEmbeddingRequest = None,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    memory_repo: MemoryRepository = Depends(get_memory_repository),
    db: AsyncSession = Depends(get_db),
):
    """手动为章节生成向量并存储到记忆库（用于测试 RAG 功能）

    参数来源：
    - chapter_id: 路径参数，章节 ID
    - request: 请求体，包含 api_key, base_url, model

    业务逻辑：
    1. 获取章节的 summary 字段
    2. 调用 embedding API 生成向量
    3. 存储到 memory_chunks 表
    """
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    if not chapter.summary:
        raise HTTPException(status_code=400, detail="章节暂无摘要，请先发布章节生成摘要")

    from backend.services.llm import get_embedding

    embedding = await get_embedding(
        text=chapter.summary,
        api_key=request.api_key,
        base_url=request.base_url
    )

    if not embedding:
        raise HTTPException(status_code=500, detail="向量生成失败，请检查 API Key 配置")

    existing = await memory_repo.find_all(
        spec=QuerySpec.create().where(MemoryChunk.chapter_id == chapter_id)
    )
    for mem in existing:
        await memory_repo.delete(mem)

    memory_data = {
        "book_id": chapter.book_id,
        "chapter_id": chapter_id,
        "chunk_text": f"【第{chapter.chapter_number}章摘要】{chapter.summary}",
        "embedding": embedding
    }
    await memory_repo.create(memory_data)

    return {
        "message": "向量生成成功",
        "chapter_id": str(chapter_id),
        "vector_dim": len(embedding),
        "preview": chapter.summary[:100] + "..." if len(chapter.summary) > 100 else chapter.summary
    }

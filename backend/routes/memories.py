from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_memory_repository
from backend.repositories import BookRepository, MemoryRepository
from backend.schemas import MemoryChunkCreate, MemoryChunkResponse

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

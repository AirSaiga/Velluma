"""
书籍管理路由模块。

职责：提供书籍的 CRUD API，包括创建、读取、更新、删除操作。

业务场景：
- 创建新书籍（设置世界观、角色设定）
- 获取书籍列表（支持分页）
- 获取书籍详情（包含章节、角色统计）
- 更新书籍信息（大纲、设定、状态）
- 删除书籍（级联删除关联数据）

数据模型：
- Book: 核心书籍实体
- WorldviewUpdate: 世界观/设定更新
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.core.dependencies import get_book_repository
from backend.repositories import BookRepository
from backend.schemas import BookCreate, BookUpdate, BookResponse, ChapterResponse, WorldviewUpdate

router = APIRouter(prefix="/api", tags=["books"])


# =============================================================================
# 书籍查询接口 - 为前端提供基础数据加载能力
# =============================================================================

@router.get("/books", response_model=List[BookResponse])
async def get_books(
    repo: BookRepository = Depends(get_book_repository),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    """业务目的：提供书籍列表的分页查询，支持前端无限滚动或分页加载场景。

    参数来源：
    - skip/limit: Query 参数，用于分页控制，默认全取第一页（0-100条）
    - 返回数据：书籍基础信息列表，不包含章节/角色等关联数据（按需加载原则）

    副作用：
    - 数据库读操作，无状态变更

    性能考量：
    - limit 上限设为 1000 防止一次查询过多记录导致内存溢出
    - 超过 1000 条书籍的场景建议使用搜索功能而非全量加载
    """
    return await repo.list(skip, limit)


@router.get("/books/{book_id}", response_model=BookResponse)
async def get_book(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：获取单本书籍的完整信息，用于书籍详情页或编辑页面数据回显。

    参数来源：
    - book_id: 路径参数，前端路由传递的 UUID

    错误处理考量：
    - 返回 404 而非空对象，因为书籍不存在是客户端错误（ID 无效或已删除）
    - 明确错误信息便于前端定位问题
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return book


# =============================================================================
# 书籍写操作 - 核心业务数据变更入口
# =============================================================================

@router.post("/books", response_model=BookResponse, status_code=201)
async def create_book(book_data: BookCreate, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：创建新书籍，初始化项目基础结构。

    参数来源：
    - book_data: 请求体 JSON，包含书籍基础字段（name, description 等）

    副作用：
    - 数据库 INSERT 操作，生成新的书籍记录和 UUID
    - 返回 201 Created 状态码，明确告知前端资源创建成功

    权衡点：
    - 未在此处自动创建"楔子"章节，保留业务灵活性让用户自行决定
    - WorldviewSettings 初始化为 null，由前端按需填充
    """
    return await repo.create(book_data.model_dump())


@router.put("/books/{book_id}", response_model=BookResponse)
async def update_book(book_id: UUID, book_data: BookUpdate, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：完整更新书籍信息，用于编辑页面保存场景。

    参数来源：
    - book_id: 路径参数
    - book_data: 请求体，使用 PATCH 语义但用 PUT 方法（FastAPI 惯例）

    副作用：
    - 数据库 UPDATE 操作
    - model_dump(exclude_unset=True) 确保只更新传入的字段，保留未传字段原值

    错误处理：
    - 先查询再更新，避免静默失败（更新不存在的记录应返回 404）
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await repo.update(book, book_data.model_dump(exclude_unset=True))


@router.delete("/books/{book_id}")
async def delete_book(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：删除书籍及其所有关联数据。

    参数来源：
    - book_id: 路径参数

    副作用：
    - 数据库 DELETE 操作
    - 警示：此操作会触发级联删除（章节、角色、关系等），不可逆

    权衡点：
    - 未实现软删除（is_deleted 标志），因为书籍作为顶层聚合根，
      物理删除更符合"项目"的概念（类似 Git 仓库删除）
    - 前端应有二次确认弹窗
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    await repo.delete(book)
    return {"message": "书籍已删除", "id": str(book_id)}


# =============================================================================
# 世界观设置 - 书籍级别的上下文配置
# =============================================================================

@router.get("/books/{book_id}/worldview")
async def get_worldview_settings(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：获取书籍的世界观设置，用于 AI 生成时的上下文注入。

    参数来源：
    - book_id: 路径参数

    数据流：
    - 从 book.worldview_settings 字段读取（JSON 类型）
    - 返回结构化对象，不存在时返回空字典而非 null

    用途：
    - 生成章节时作为 system_prompt 的一部分
    - 定义故事背景、规则约束、关键设定等
    """
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
    """业务目的：增量更新世界观设置，保留未修改的字段。

    参数来源：
    - book_id: 路径参数
    - payload: PATCH 请求体，只包含需要更新的字段

    副作用：
    - 数据库 UPDATE 操作，只更新 worldview_settings 字段
    - 使用 patch 语义而非全量替换，适应前端渐进式编辑场景

    设计考量：
    - WorldviewUpdate 采用 optional 字段，前端可只传需要更新的部分
    - null 值会被转换为空字典，避免存储 null 导致的前端处理复杂度
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    await repo.update(book, {"worldview_settings": payload.worldview_settings or {}})
    return {"worldview_settings": book.worldview_settings}


# =============================================================================
# 章节导航 - 书籍与章节的层级关联
# =============================================================================

@router.get("/books/{book_id}/chapters", response_model=List[ChapterResponse])
async def get_chapters(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：获取书籍下的所有章节，用于目录页和章节列表展示。

    参数来源：
    - book_id: 路径参数，用于筛选属于该书籍的章节

    数据流：
    - repo.list_chapters() 内部按 chapter_number 排序返回
    - 返回完整的 ChapterResponse，包含章节内容预览

    性能考量：
    - 章节内容可能较大，此接口不应用于章节编辑（应使用独立 GET /chapters/{id}）
    - 未来考虑拆分为 list（仅标题+摘要）和 detail（完整内容）两个接口
    """
    return await repo.list_chapters(book_id)

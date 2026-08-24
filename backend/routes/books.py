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

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_book_repository, get_plot_ledger_repository, get_db
from backend.repositories import BookRepository, PlotLedgerRepository
from backend.schemas import BookCreate, BookUpdate, BookResponse, ChapterResponse, WorldviewUpdate, PlotLedgerResponse, PlotLedgerCreate, PlotLedgerUpdate


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
    data = book_data.model_dump(exclude_unset=True)
    # D4 比例尺：显式空 dict = 清除标定（存 NULL，未标定语义统一）
    if "map_scale" in data and not data["map_scale"]:
        data["map_scale"] = None
    return await repo.update(book, data)


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
# 时间轴 UI 状态 - 世界页游标时刻 + 视野窗口（按书持久化，前端端口漂移免疫）
# =============================================================================

def merge_timeline_view(existing: Optional[dict], patch: Dict[str, Any]) -> dict:
    """合并时间轴 UI 状态补丁（纯函数，便于单测）。

    契约（与前端 engine/timelineView.ts 同构）：
    - cursor：日计数，非负整数（非 bool）；None = 删除键（回创世）
    - range：{start, end} 年份，整数且 1 <= start < end；None = 删除键（回自动视野）
    - 未知键静默忽略（前向兼容）；已知键值非法抛 ValueError（路由层转 400）
    """
    merged = dict(existing or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
            continue
        if key == "cursor":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("cursor 须为非负整数日计数")
            merged[key] = value
        elif key == "range":
            if (
                not isinstance(value, dict)
                or isinstance(value.get("start"), bool)
                or isinstance(value.get("end"), bool)
                or not isinstance(value.get("start"), int)
                or not isinstance(value.get("end"), int)
                or value["start"] < 1
                or value["end"] <= value["start"]
            ):
                raise ValueError("range 须为 {start, end} 整数年份，且 1 <= start < end")
            merged[key] = {"start": value["start"], "end": value["end"]}
        # 未知键：忽略
    return merged


@router.get("/books/{book_id}/timeline-view")
async def get_timeline_view(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：读取书籍的时间轴 UI 状态（游标时刻 + 手动视野窗口）。

    数据流：从 book.timeline_view 读取（JSONB），未设置返回空字典（前端回退自动视野）。
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"timeline_view": book.timeline_view or {}}


@router.patch("/books/{book_id}/timeline-view")
async def patch_timeline_view(
    book_id: UUID,
    payload: Dict[str, Any] = Body(...),
    repo: BookRepository = Depends(get_book_repository),
):
    """业务目的：增量合并时间轴 UI 状态（键级 merge，显式 null 删除该键）。

    设计考量：
    - 游标（拖动去抖高频写）与视野窗口（点击低频写）是两个独立写入方，
      键级合并避免整对象覆盖互相踩踏
    - 值非法返回 400 而非静默忽略，防止坏状态落库后污染每次加载
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    try:
        merged = merge_timeline_view(book.timeline_view, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await repo.update(book, {"timeline_view": merged})
    return {"timeline_view": merged}


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


# =============================================================================
# 伏笔账本 - 书籍级伏笔查询（V3.1 F4 伏笔账本面板的后端支撑）
# =============================================================================

@router.get("/books/{book_id}/ledgers", response_model=List[PlotLedgerResponse])
async def get_book_ledgers(
    book_id: UUID,
    status: Optional[str] = Query(None, pattern="^(open|closed|dropped)$"),
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=2000),
    repo: PlotLedgerRepository = Depends(get_plot_ledger_repository),
):
    """业务目的：获取书籍的全部伏笔账本条目，支撑前端伏笔账本面板的列表展示。

    参数来源：
    - book_id: 路径参数，书籍 UUID
    - status: Query 参数，可选状态过滤（open/closed/dropped），不传返回全部状态
    - skip/limit: Query 参数，分页控制，默认返回最近 500 条

    数据流：
    - PlotLedgerRepository.get_by_book() 按创建时间倒序返回
    - 响应字段与前端 plotLedgerApi.listByBook 的契约一一对应
    - meta 字段承载伏笔的扩展信息（如登记来源、支持证据等）

    副作用：
    - 数据库读操作，无状态变更

    性能考量：
    - limit 上限 2000，单书伏笔量级通常在数百以内，无需游标分页
    - 书籍不存在时返回空列表而非 404（与 get_chapters 行为保持一致）
    """
    return await repo.get_by_book(book_id, status=status, skip=skip, limit=limit)


@router.post("/books/{book_id}/ledgers", response_model=PlotLedgerResponse, status_code=201)
async def create_book_ledger(
    book_id: UUID,
    payload: PlotLedgerCreate,
    repo: PlotLedgerRepository = Depends(get_plot_ledger_repository),
):
    """业务目的：手动创建伏笔条目（伏笔账本面板"手动添加"入口）。

    参数来源：
    - book_id: 路径参数，书籍 UUID（以此为准，覆盖请求体中的 book_id）
    - payload: PlotLedgerCreate（ledger_key/content 必填，其余有默认值）

    副作用：
    - 数据库写操作：新增一行 plot_ledgers 记录
    - 注意 book_id+ledger_key 有唯一约束（uq_plot_ledger_book_key），重复 key 会触发 500，
      前端应保证 ledger_key 唯一（默认生成时间戳 key）
    """
    data = payload.model_dump()
    data["book_id"] = book_id
    return await repo.create(data)


@router.put("/ledgers/{ledger_id}", response_model=PlotLedgerResponse)
async def update_ledger(
    ledger_id: UUID,
    payload: PlotLedgerUpdate,
    repo: PlotLedgerRepository = Depends(get_plot_ledger_repository),
):
    """业务目的：更新伏笔条目（编辑内容/类型，或变更状态：埋设中→已回收/已废弃）。

    参数来源：
    - ledger_id: 路径参数
    - payload: PlotLedgerUpdate（全字段可选，仅更新显式传入的字段）

    副作用：
    - 数据库写操作：更新 plot_ledgers 对应行
    """
    ledger = await repo.get_by_id(ledger_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return ledger
    return await repo.update(ledger, updates)


@router.delete("/ledgers/{ledger_id}")
async def delete_ledger(
    ledger_id: UUID,
    db: AsyncSession = Depends(get_db),
    repo: PlotLedgerRepository = Depends(get_plot_ledger_repository),
):
    """业务目的：删除伏笔条目（物理删除；若仅是不再需要建议改用 status=dropped）。

    参数来源：
    - ledger_id: 路径参数

    副作用：
    - 数据库写操作：删除 plot_ledgers 对应行
    - C2：挂接的信息面 overlay 同步清理（应用层级联，防悬空 ref）
    """
    ledger = await repo.get_by_id(ledger_id)
    if not ledger:
        raise HTTPException(status_code=404, detail="伏笔不存在")
    await repo.delete(ledger)
    from sqlalchemy import delete as sa_delete
    from backend.models import CanonNode as _CanonNode
    await db.execute(sa_delete(_CanonNode).where(_CanonNode.ref_id == ledger_id, _CanonNode.ref_type == "ledger"))
    await db.commit()
    return {"ok": True}


# =============================================================================
# 黄金锚点（只读归档）- 旧 books.golden_snippets 表
# =============================================================================
# 双写收敛（任务包 B）：写作台「黄金片段」改只写文风样本库（styleApi.createSample），
# 旧表冻结只读——GET 保留作文风页 from-golden 导入与存量计数的依赖；PUT 端点
# 已删（前端 updateGoldenSnippets 无调用方）。历史书级黑名单 REST 通道
# （GET/PUT /books/{id}/style-blacklist）已整体删除，负面清单唯一入口是
# style_cards.negative_list（/books/{id}/style-card）。

@router.get("/books/{book_id}/golden-snippets")
async def get_golden_snippets(book_id: UUID, repo: BookRepository = Depends(get_book_repository)):
    """业务目的：获取书籍的黄金锚点片段（旧表只读归档，文风页 from-golden 导入依赖）。

    参数来源：
    - book_id: 路径参数

    数据流：
    - 从 book.golden_snippets 字段读取（JSONB 数组类型）
    - 返回字符串数组
    """
    book = await repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return {"golden_snippets": book.golden_snippets or []}

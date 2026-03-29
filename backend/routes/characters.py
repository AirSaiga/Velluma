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
角色管理路由模块。

职责：提供角色的 CRUD API，管理书籍中的角色实体。

业务场景：
- 创建新角色（设置静态设定、重要性等级）
- 获取书籍的角色列表
- 获取角色详情
- 更新角色信息（设定、状态）
- 删除角色
- 更新角色动态状态（章节生成后自动更新）

数据模型：
- Character: 角色实体
- CharacterResponse: API 响应模型
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_chapter_repository, get_character_repository
from backend.repositories import BookRepository, ChapterRepository, CharacterRepository
from backend.schemas import (
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterDynamicStateUpdateRequest,
    CharacterDynamicStateUpdateResponse,
)
from backend.services.generation.chapter import update_character_dynamic_state

router = APIRouter(prefix="/api", tags=["characters"])


# =============================================================================
# 角色查询接口 - 书籍内的角色列表与详情
# =============================================================================

@router.get("/books/{book_id}/characters", response_model=List[CharacterResponse])
async def get_characters(book_id: UUID, repo: CharacterRepository = Depends(get_character_repository)):
    """业务目的：获取指定书籍下的所有角色，用于角色管理面板。

    参数来源：
    - book_id: 路径参数，用于筛选该书籍创建的角色

    数据流：
    - 调用 repo.list_by_book() 按创建时间排序返回角色列表
    - 返回完整的 CharacterResponse，包含角色静态信息（名称、描述、头像等）
    - 不包含 dynamic_state（动态状态通过其他接口获取）

    性能考量：
    - 若书籍下角色过多（>500），考虑前端分页或搜索过滤
    - dynamic_state 未在此返回因可能包含长文本
    """
    return await repo.list_by_book(book_id)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(character_id: UUID, repo: CharacterRepository = Depends(get_character_repository)):
    """业务目的：获取单个角色的完整信息，用于角色详情页或编辑页面。

    参数来源：
    - character_id: 路径参数

    错误处理：
    - 角色不存在时返回 404，因为 UUID 不匹配意味着访问无效资源
    - 此接口不验证角色所属书籍（由前端保证 URL 正确性）
    """
    character = await repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return character


# =============================================================================
# 角色生命周期 - 创建/更新/删除
# =============================================================================

@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    character_data: CharacterCreate,
    character_repo: CharacterRepository = Depends(get_character_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    """业务目的：在指定书籍下创建新角色。

    参数来源：
    - character_data: 请求体，包含 name（必填）、description、avatar、book_id 等

    数据流：
    1. 验证书籍存在（book_id 必须是已有书籍）
    2. 创建角色记录，初始化 dynamic_state 为 null
    3. 返回新创建的角色

    副作用：
    - 数据库 INSERT 操作，生成新 UUID
    - dynamic_state 初始为 null，发布章节后由 AI 更新

    权衡点：
    - 未自动创建角色间的关系，关系需要手动维护
    - 这样做符合"角色优先、关系后建"的工作流
    """
    book = await book_repo.get_by_id(character_data.book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    return await character_repo.create(character_data.model_dump())


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    character_id: UUID,
    character_data: CharacterUpdate,
    repo: CharacterRepository = Depends(get_character_repository),
):
    """业务目的：更新角色信息，用于角色编辑保存。

    参数来源：
    - character_id: 路径参数
    - character_data: 请求体，使用 exclude_unset=True 实现部分更新

    副作用：
    - 数据库 UPDATE 操作
    - 不会更新 dynamic_state（动态状态只能通过章节发布或专门接口更新）

    错误处理：
    - 角色不存在时返回 404
    - 这样做避免静默失败，前端需处理 404 场景
    """
    character = await repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    return await repo.update(character, character_data.model_dump(exclude_unset=True))


@router.delete("/characters/{character_id}")
async def delete_character(character_id: UUID, repo: CharacterRepository = Depends(get_character_repository)):
    """业务目的：删除角色。

    参数来源：
    - character_id: 路径参数

    副作用：
    - 数据库 DELETE 操作
    - 警示：会级联删除该角色的关系记录（relationships 表）
    - 不会删除章节引用该角色的记录（chapter_entities），可能产生孤立引用

    权衡点：
    - 关系必须删除（无意义的孤立关系不应保留）
    - 章节引用选择保留而非级联删除，因为：
      a) 保留历史记录有助于理解章节内容
      b) 避免级联删除导致的数据一致性复杂性
    - 前端需处理章节详情页显示"已删除角色"的边缘情况
    """
    character = await repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    await repo.delete(character)
    return {"message": "角色已删除", "id": str(character_id)}


# =============================================================================
# 角色动态状态更新 - AI 驱动的角色演进
# =============================================================================

@router.post("/characters/{character_id}/update-dynamic-state")
async def update_character_dynamic_state_endpoint(
    character_id: UUID,
    request: CharacterDynamicStateUpdateRequest,
    character_repo: CharacterRepository = Depends(get_character_repository),
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：手动触发角色动态状态更新，基于指定章节内容重新生成。

    参数来源：
    - character_id: 路径参数
    - request: 请求体，包含 chapter_id、api_key、base_url、model

    数据流：
    1. 验证角色存在
    2. 验证章节存在
    3. 验证书籍状态为"已发布"（只有发布后的内容才是"确定的事实"）
    4. 调用 update_character_dynamic_state 服务更新 dynamic_state
    5. 返回新旧状态对比

    业务约束：
    - 只能基于已发布章节更新状态，因为草稿内容尚未定稿，不应影响角色发展
    - 这是防止"状态漂移"的设计：避免角色状态基于不确定内容演进

    错误处理：
    - 返回 400 若章节未发布，明确告知前端原因
    - AI 调用失败会抛出异常，上层统一处理
    """
    character = await character_repo.get_by_id(character_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.status != "published":
        raise HTTPException(status_code=400, detail="只能基于已发布的章节更新角色状态")
    result = await update_character_dynamic_state(
        character=character,
        chapter=chapter,
        db=chapter_repo.get_session(),
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
        manual_current_state=request.manual_current_state,
        proxy_enabled=request.proxy_enabled,
        proxy_url=request.proxy_url,
    )
    return CharacterDynamicStateUpdateResponse(
        character_id=character_id,
        old_dynamic_state=result["old_dynamic_state"],
        new_dynamic_state=result["new_dynamic_state"],
    )

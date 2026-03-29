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
章节管理路由模块。

职责：提供章节的基础 CRUD API，处理章节的创建、读取、更新、删除操作。

业务场景：
- 创建新章节（自动编号）
- 获取书籍的章节列表
- 获取章节详情
- 更新章节信息（大纲、标题、状态）
- 删除章节

数据模型：
- Chapter: 章节实体

注意：章节与角色的关联（ChapterEntity）由 chapter_entities.py 管理
注意：章节与地点的关联由 chapter_entities.py 或 maps.py 管理
注意：章节的发布流程由 chapter_publishing.py 管理
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_chapter_repository
from backend.repositories import BookRepository, ChapterRepository
from backend.schemas import ChapterCreate, ChapterUpdate, ChapterResponse


router = APIRouter(prefix="/api", tags=["chapters"])


@router.get("/chapters/{chapter_id}", response_model=ChapterResponse)
async def get_chapter(chapter_id: UUID, chapter_repo: ChapterRepository = Depends(get_chapter_repository)):
    """业务目的：获取单章节详情，用于章节编辑页面。

    参数来源：
    - chapter_id: 路径参数

    错误处理：
    - 返回 404 场景：章节不存在或属于其他书籍（隐式安全检查）
    - 前端需根据 404 判断用户是否有权访问该章节
    """
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.post("/books/{book_id}/chapters", response_model=ChapterResponse, status_code=201)
async def create_chapter(
    book_id: UUID,
    chapter_data: ChapterCreate,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    book_repo: BookRepository = Depends(get_book_repository),
):
    """业务目的：在指定书籍下创建新章节。

    参数来源：
    - book_id: 路径参数，隐式指定章节所属书籍
    - chapter_data: 请求体，包含 chapter_number（必填）、title、content 等

    数据流：
    1. 验证书籍存在（book_id 必须属于已有书籍）
    2. 构造章节数据，若未提供 chapter_name 则自动生成"第X章"格式
    3. 写入数据库，返回新创建的章节

    权衡点：
    - 未自动检测 chapter_number 连续性，允许跳章创建（如先创建第5章）
    - 这是有意设计，支持楔子/番外等非顺序章节
    - 前端可自行实现顺序校验
    """
    book = await book_repo.get_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="书籍不存在")
    chapter_payload = chapter_data.model_dump()
    if not chapter_payload.get("chapter_name"):
        chapter_payload["chapter_name"] = f"第{chapter_payload['chapter_number']}章"
    return await chapter_repo.create(chapter_payload)


@router.put("/chapters/{chapter_id}", response_model=ChapterResponse)
async def update_chapter(
    chapter_id: UUID,
    chapter_data: ChapterUpdate,
    repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：更新章节内容或元数据。

    参数来源：
    - chapter_id: 路径参数
    - chapter_data: 请求体，使用 exclude_unset=True 确保部分更新

    副作用：
    - 数据库 UPDATE 操作
    - 自动补全逻辑：如果既没有传入 chapter_name 也没有现有值，生成默认名称

    边界处理：
    - 允许 chapter_name 为空字符串，会触发自动生成默认名称
    - 这是为了兼容前端"清空章节名"的需求
    """
    chapter = await repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    update_dict = chapter_data.model_dump(exclude_unset=True)
    merged_dict = dict(update_dict)
    if "chapter_name" not in merged_dict and not chapter.chapter_name:
        merged_dict["chapter_name"] = f"第{merged_dict.get('chapter_number', chapter.chapter_number)}章"
    if "chapter_name" in merged_dict and not merged_dict["chapter_name"]:
        merged_dict["chapter_name"] = f"第{merged_dict.get('chapter_number', chapter.chapter_number)}章"
    if not merged_dict and not chapter.chapter_name:
        chapter.chapter_name = f"第{chapter.chapter_number}章"
        
    if "content_text" in merged_dict:
        merged_dict["draft_text"] = merged_dict["content_text"]
    elif "draft_text" in merged_dict:
        merged_dict["content_text"] = merged_dict["draft_text"]
        
    return await repo.update(chapter, merged_dict)


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: UUID, repo: ChapterRepository = Depends(get_chapter_repository)):
    """业务目的：删除章节。

    参数来源：
    - chapter_id: 路径参数

    副作用：
    - 数据库 DELETE 操作
    - 警示：会同时删除章节与角色的关联关系（chapter_entities 表）
    - 不会删除角色本身

    权衡点：
    - 未实现章节内容归档，删除即永久丢失
    - 可考虑增加 soft_delete 机制（暂未实现）
    """
    chapter = await repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    await repo.delete(chapter)
    return {"message": "章节已删除", "id": str(chapter_id)}

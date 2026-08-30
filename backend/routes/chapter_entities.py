# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
# [旧表冻结声明 2026-08-19] 本模块仍读 characters/assets 等旧表（roadmap P2.4 显式冻结）：
# 世界页（world_*）是唯一编辑源；此处旧表读取冻结不动，下次实质改造时换源 world。
# 新代码勿再新增旧表依赖。

"""
章节-实体关联管理路由模块。

职责：管理章节与角色/地点的关联关系，支持多对多关联。

业务场景：
- 为章节添加角色出场
- 为章节添加地点设定
- 获取章节关联的所有实体
- 移除章节的实体关联

设计说明：
- ChapterEntity 为多态关联表，通过 entity_type 区分关联类型
- 支持角色（character）和地点（location）两种实体类型
- 同一实体可多次关联同一章节（表示多次出场）

数据模型：
- ChapterEntity: 多态关联表
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_chapter_repository, get_character_repository
from backend.repositories import ChapterRepository, CharacterRepository
from backend.schemas import ChapterEntityCreate, ChapterResponse


router = APIRouter(prefix="/api", tags=["chapter-entities"])


@router.put("/chapters/{chapter_id}/entities")
async def update_chapter_entities(
    chapter_id: UUID,
    entity_ids: List[UUID],
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """业务目的：批量更新章节关联的角色列表，实现场景人物管理。

    参数来源：
    - chapter_id: 路径参数
    - entity_ids: 请求体，期望关联的角色 UUID 列表

    数据流（完整流程）：
    1. 获取现有关联（从 chapter_entities 表查询）
    2. 计算差集：新增关联 = new_ids - existing_ids
    3. 计算差集：删除关联 = existing_ids - new_ids
    4. 逐个执行增删操作
    5. 提交事务

    副作用：
    - 多次数据库操作（add_entity, delete_entity），事务保证一致性
    - 仅验证角色存在性，不检查是否属于同一书籍（潜在漏洞）

    性能考量：
    - 循环中的 await 调用可能引发 N+1 查询问题
    - 未来考虑批量操作优化
    """
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    existing_entities = await chapter_repo.list_entities(chapter_id)
    existing_ids = {e.entity_id for e in existing_entities}
    new_ids = set(entity_ids)
    for entity_id in new_ids - existing_ids:
        if await character_repo.get_by_id(entity_id):
            await chapter_repo.add_entity(chapter_id=chapter_id, entity_id=entity_id, entity_type="character")
    for existing in existing_entities:
        if existing.entity_id not in new_ids:
            await chapter_repo.delete_entity(existing)
    await chapter_repo.commit()
    return {"message": "角色关联已更新", "chapter_id": str(chapter_id)}


@router.get("/chapters/{chapter_id}/entities")
async def get_chapter_entities(chapter_id: UUID, repo: ChapterRepository = Depends(get_chapter_repository)):
    """业务目的：查询章节关联的所有角色 ID。

    参数来源：
    - chapter_id: 路径参数

    数据流：
    - 从 chapter_entities 表查询，返回 entity_id 列表
    - 前端据此渲染"本章出场人物"模块
    """
    entities = await repo.list_entities(chapter_id)
    return {"entity_ids": [str(e.entity_id) for e in entities]}


@router.post("/chapters/{chapter_id}/entities", response_model=ChapterResponse)
async def link_entity_to_chapter(
    chapter_id: UUID,
    entity_data: ChapterEntityCreate,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """业务目的：手动添加章节与角色的单一关联。

    参数来源：
    - chapter_id: 路径参数
    - entity_data: 请求体，包含 entity_id 和 entity_type

    数据流：
    1. 验证章节存在
    2. 验证角色存在（entity_id 指向的角色必须存在）
    3. 添加关联记录

    错误处理：
    - 若角色不存在，返回 404（而非静默忽略）
    - 这确保前端知道关联失败的具体原因
    """
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    entity = await character_repo.get_by_id(entity_data.entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail="角色不存在")
    await chapter_repo.add_entity(
        chapter_id=chapter_id,
        entity_id=entity_data.entity_id,
        entity_type=entity_data.entity_type,
    )
    return chapter

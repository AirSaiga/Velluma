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
角色关系管理路由模块。

职责：提供角色之间关系的 CRUD API，管理角色间的关联。

业务场景：
- 创建角色关系（指定关系类型、描述）
- 获取书籍的角色关系列表
- 获取两个角色间的关系详情
- 更新关系信息
- 删除关系

设计说明：
- 关系模型为有向边（A → B），需双向查询获得完整关系图
- 支持多种关系类型（亲友、敌对、师生等）

数据模型：
- CharacterRelationship: 关系实体（有向边）
- RelationshipResponse: API 响应模型
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_character_repository, get_relationship_repository
from backend.repositories import CharacterRepository, RelationshipRepository
from backend.schemas import RelationshipCreate, RelationshipResponse, RelationshipUpdate

router = APIRouter(prefix="/api", tags=["relationships"])


# =============================================================================
# 关系查询 - 角色间关联的可视化数据源
# =============================================================================

@router.get("/relationships", response_model=List[RelationshipResponse])
async def get_relationships(
    book_id: Optional[UUID] = None, repo: RelationshipRepository = Depends(get_relationship_repository)
):
    """业务目的：查询角色间关系，用于关系图谱展示。

    参数来源：
    - book_id: 可选 Query 参数，按书籍筛选

    数据流：
    - 返回指定书籍下所有角色关系
    - 关系是双向的（A→B 和 B→A 视为同一条记录）
    - 包含关系类型、描述等属性

    性能考量：
    - 关系数量通常是角色数的 O(n^2) 级别，但实际会远少于此
    - 无分页，大型项目可能需要优化
    """
    return await repo.list(book_id)


# =============================================================================
# 关系生命周期 - 创建/删除
# =============================================================================

@router.post("/relationships", response_model=RelationshipResponse, status_code=201)
async def create_relationship(
    relationship_data: RelationshipCreate,
    relationship_repo: RelationshipRepository = Depends(get_relationship_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """业务目的：创建两个角色之间的关系。

    参数来源：
    - relationship_data: 请求体，包含 source_char_id、target_char_id、type、description 等

    数据流：
    1. 验证源角色存在
    2. 验证目标角色存在
    3. 验证书籍下不存在相同的关系对（防止重复创建）
    4. 写入数据库

    业务约束：
    - 关系是单向存储的（A→B），但语义上是双向的
    - 防止重复：已存在相同 source→target 时返回 400

    副作用：
    - 数据库 INSERT 操作

    权衡点：
    - 为什么不支持双向自动创建？
      因为关系类型可能不对称（如"师生"vs"学生"），需要分开描述
    - 这是有意的设计决策，保留关系描述的灵活性
    """
    source_char = await character_repo.get_by_id(relationship_data.source_char_id)
    if not source_char:
        raise HTTPException(status_code=404, detail="源角色不存在")
    target_char = await character_repo.get_by_id(relationship_data.target_char_id)
    if not target_char:
        raise HTTPException(status_code=404, detail="目标角色不存在")
    existing = await relationship_repo.get_by_pair(relationship_data.source_char_id, relationship_data.target_char_id)
    if existing:
        raise HTTPException(status_code=400, detail="关系已存在")
    return await relationship_repo.create(relationship_data.model_dump())


@router.put("/relationships/{relationship_id}", response_model=RelationshipResponse)
async def update_relationship(
    relationship_id: UUID,
    relationship_data: RelationshipUpdate,
    repo: RelationshipRepository = Depends(get_relationship_repository),
):
    """业务目的：更新角色间关系。

    参数来源：
    - relationship_id: 路径参数
    - relationship_data: 请求体，包含要更新的字段

    数据流：
    1. 验证关系是否存在
    2. 执行更新
    3. 返回更新后的对象

    副作用：
    - 数据库 UPDATE 操作
    """
    relationship = await repo.get_by_id(relationship_id)
    if not relationship:
        raise HTTPException(status_code=404, detail="关系不存在")
    return await repo.update(relationship, relationship_data.model_dump(exclude_unset=True))


@router.delete("/relationships/{relationship_id}")
async def delete_relationship(relationship_id: UUID, repo: RelationshipRepository = Depends(get_relationship_repository)):
    """业务目的：删除角色间关系。

    参数来源：
    - relationship_id: 路径参数

    副作用：
    - 数据库 DELETE 操作
    - 警示：不会同时删除反向关系（如果存在）

    权衡点：
    - 需要手动处理反向关系的删除
    - 前端删除 A→B 时，应考虑是否同时删除 B→A
    - 这样设计是给前端控制权，而非自动级联
    """
    relationship = await repo.get_by_id(relationship_id)
    if not relationship:
        raise HTTPException(status_code=404, detail="关系不存在")
    await repo.delete(relationship)
    return {"message": "关系已删除", "id": str(relationship_id)}

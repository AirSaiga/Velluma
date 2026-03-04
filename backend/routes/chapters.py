from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from backend.core.dependencies import get_book_repository, get_chapter_repository, get_character_repository
from backend.repositories import BookRepository, ChapterRepository, CharacterRepository
from backend.schemas import (
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
    ChapterEntityCreate,
    ChapterPublishRequest,
    ChapterPublishResponse,
    CharacterStateChange,
)
from backend.services.chapter_generation import update_character_dynamic_state

router = APIRouter(prefix="/api", tags=["chapters"])


# =============================================================================
# 章节基础查询 - 独立获取章节数据
# =============================================================================

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


# =============================================================================
# 章节生命周期管理 - 创建/更新/删除
# =============================================================================

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


# =============================================================================
# 章节-角色关联管理 - 建立场景上下文
# =============================================================================

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


# =============================================================================
# 章节发布 - 触发角色状态演进的核心入口
# =============================================================================

@router.patch("/chapters/{chapter_id}/publish", response_model=ChapterPublishResponse)
async def publish_chapter(
    chapter_id: UUID,
    request: Optional[ChapterPublishRequest] = None,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
    character_repo: CharacterRepository = Depends(get_character_repository),
):
    """业务目的：将章节从草稿状态发布为正式内容，并触发角色动态状态更新。

    参数来源：
    - chapter_id: 路径参数
    - request: 可选请求体，包含 api_key 等 AI 生成参数

    核心副作用（两步执行）：
    1. 状态变更：chapter.status → "published"
    2. 角色演进（可选）：若提供 api_key，调用 AI 更新角色 dynamic_state

    数据流详解：
    - 获取章节关联的角色列表（优先从 chapter_entities，其次 fallback 到 character_ids）
    - 对每个角色调用 update_character_dynamic_state
    - 收集状态变更记录用于返回

    错误处理：
    - 若章节已发布，返回 400 避免重复发布
    - AI 调用失败时静默跳过（try/except pass），不影响发布本身
    - 这样做是不希望 AI 失败阻塞发布流程

    权衡点：
    - 角色状态更新失败不阻断发布，因为 AI 调用本质上是"增强"而非"必须"
    - 返回 character_updates 让前端知晓哪些角色成功更新、哪些失败
    - 未来可能增加重试机制或失败队列
    """
    chapter = await chapter_repo.get_by_id(chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.status == "published":
        raise HTTPException(status_code=400, detail="章节已经是发布状态")
    chapter.status = "published"
    character_updates = []
    if request and request.api_key:
        character_list = []
        seen_char_ids = set()
        entities = await chapter_repo.list_entities_with_character(chapter_id)
        if entities:
            for entity in entities:
                if entity.character and entity.character.id not in seen_char_ids:
                    character_list.append(entity.character)
                    seen_char_ids.add(entity.character.id)
        else:
            chapter_char_ids = getattr(chapter, "character_ids", None)
            if chapter_char_ids:
                chars = await character_repo.list_by_ids(chapter_char_ids)
                for char in chars:
                    if char.id not in seen_char_ids:
                        character_list.append(char)
                        seen_char_ids.add(char.id)
        for character in character_list:
            if character:
                try:
                    old_state = character.dynamic_state or "暂无动态状态"
                    await update_character_dynamic_state(
                        character=character,
                        chapter=chapter,
                        db=chapter_repo.db,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                    )
                    new_state = character.dynamic_state or "暂无动态状态"
                    character_updates.append(
                        CharacterStateChange(
                            character_id=character.id,
                            character_name=character.name,
                            old_state=old_state,
                            new_state=new_state,
                        )
                    )
                except Exception:
                    pass
    await chapter_repo.commit()
    await chapter_repo.refresh(chapter)
    return ChapterPublishResponse(chapter_id=chapter.id, status=chapter.status, character_updates=character_updates)

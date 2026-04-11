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
上下文加载服务模块 (Context Loader Service)

职责：
- 封装章节生成所需的上下文数据加载逻辑
- 统一处理数据库查询，避免路由层直接操作数据库
- 提供标准化的上下文数据结构

迁移说明 (2026-03-30)：
- 所有函数已迁移到使用 Repository 模式
- 请使用新函数（不带 _legacy 后缀）
- 旧函数保留但标记为废弃

使用方式：
    from backend.repositories import (
        ChapterRepository, BookRepository, MemoryRepository, 
        PlotLedgerRepository, MapLocationRepository, RelationshipRepository
    )
    repos = {
        "chapter": ChapterRepository(db),
        "book": BookRepository(db),
        "memory": MemoryRepository(db),
        "plot_ledger": PlotLedgerRepository(db),
        "map_location": MapLocationRepository(db),
        "relationship": RelationshipRepository(db),
    }
    context = await load_full_chapter_context(chapter_id, repos, rag_params, api_key)
"""

from typing import List, Optional, Dict, Any, TYPE_CHECKING
from uuid import UUID

from backend.models import (
    Chapter, Book, ChapterEntity, CharacterRelationship,
    ChapterMapLocation, PlotLedger, StoryBeat
)
from backend.services.llm import get_embedding
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_RAG

if TYPE_CHECKING:
    from backend.repositories import (
        ChapterRepository, BookRepository, MemoryRepository,
        PlotLedgerRepository, MapLocationRepository, RelationshipRepository
    )

from backend.repositories.base import QuerySpec

import logging

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_RAG)


RepositoriesDict = Dict[str, Any]


async def load_chapter(
    repositories: RepositoriesDict,
    chapter_id: str
) -> Optional[Chapter]:
    """加载章节及其关联的 story_beats"""
    chapter_repo: "ChapterRepository" = repositories.get("chapter")
    if not chapter_repo:
        raise ValueError("ChapterRepository 未配置")
    
    # 使用 selectinload 预加载 story_beats，避免在异步上下文中触发懒加载
    from backend.models import StoryBeat
    from sqlalchemy.orm import selectinload
    spec = QuerySpec.create(Chapter).where(
        Chapter.id == chapter_id
    ).with_options(
        selectinload(Chapter.story_beats)
    )
    return await chapter_repo.find_one(spec=spec)


async def load_book(
    repositories: RepositoriesDict,
    book_id: str
) -> Optional[Book]:
    """加载书籍基本信息"""
    book_repo: "BookRepository" = repositories.get("book")
    if not book_repo:
        raise ValueError("BookRepository 未配置")
    return await book_repo.get_by_id(book_id)


async def load_chapter_entities(
    repositories: RepositoriesDict,
    chapter_id: str
) -> List[ChapterEntity]:
    """加载章节关联的实体（角色）"""
    chapter_repo: "ChapterRepository" = repositories.get("chapter")
    if not chapter_repo:
        raise ValueError("ChapterRepository 未配置")

    from backend.models import ChapterEntity
    from sqlalchemy.orm import selectinload
    spec = QuerySpec.create(ChapterEntity).where(
        ChapterEntity.chapter_id == chapter_id
    ).with_options(
        selectinload(ChapterEntity.character)
    )
    return await chapter_repo.find_all(spec=spec)


async def load_character_relationships(
    repositories: RepositoriesDict,
    entities: List[ChapterEntity]
) -> List[CharacterRelationship]:
    """加载角色之间的关系网络"""
    relationship_repo: "RelationshipRepository" = repositories.get("relationship")
    if not relationship_repo:
        return []

    character_ids = [e.entity_id for e in entities if e.entity_id]
    if not character_ids:
        return []

    from backend.models import CharacterRelationship
    spec = QuerySpec.create(CharacterRelationship).where(
        CharacterRelationship.source_char_id.in_(character_ids),
        CharacterRelationship.target_char_id.in_(character_ids),
    )
    return await relationship_repo.find_all(spec=spec)


async def load_previous_chapter_summary(
    repositories: RepositoriesDict,
    chapter: Chapter
) -> Optional[str]:
    """加载上一章摘要"""
    if not chapter.book_id or chapter.chapter_number <= 1:
        return None
    
    chapter_repo: "ChapterRepository" = repositories.get("chapter")
    if not chapter_repo:
        return None
    
    prev_chapter = await chapter_repo.find_one(
        conditions=[
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1
        ]
    )
    
    if not prev_chapter:
        return None
    
    if prev_chapter.summary:
        return prev_chapter.summary
    elif prev_chapter.draft_text:
        return f"（上一章末尾原文）...{prev_chapter.draft_text[-1000:]}"
    elif prev_chapter.content_text:
        return f"（上一章末尾原文）...{prev_chapter.content_text[-1000:]}"
    else:
        prev_name = prev_chapter.chapter_name or f"第{prev_chapter.chapter_number}章"
        return f"（上一章【{prev_name}】内容未生成，标题：{prev_chapter.title or '未命名'}）"


async def load_previous_world_snapshot(
    repositories: RepositoriesDict,
    chapter: Chapter
) -> Optional[dict]:
    """加载上一章的世界状态快照"""
    if not chapter.book_id or chapter.chapter_number <= 1:
        return None
    
    chapter_repo: "ChapterRepository" = repositories.get("chapter")
    if not chapter_repo:
        return None
    
    prev_chapter = await chapter_repo.find_one(
        conditions=[
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1
        ]
    )
    
    return prev_chapter.world_snapshot if prev_chapter else None


async def load_open_hooks(
    repositories: RepositoriesDict,
    chapter: Chapter
) -> List[Dict[str, str]]:
    """加载开放的伏笔/情节点"""
    plot_repo: "PlotLedgerRepository" = repositories.get("plot_ledger")
    if not plot_repo or not chapter.book_id:
        return []
    
    hooks = await plot_repo.get_open_hooks(
        book_id=chapter.book_id,
        before_chapter=chapter.chapter_number,
    )
    
    result = []
    for row in hooks:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        result.append({
            "hook_id": str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip(),
            "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
            "content": content,
        })
    
    return result


async def load_chapter_locations(
    repositories: RepositoriesDict,
    chapter_id: str
) -> List[ChapterMapLocation]:
    """加载章节关联的地图位置"""
    map_repo: "MapLocationRepository" = repositories.get("map_location")
    if not map_repo:
        raise ValueError("MapLocationRepository 未配置")

    from backend.models import ChapterMapLocation
    spec = QuerySpec.create(ChapterMapLocation).where(ChapterMapLocation.chapter_id == chapter_id)
    return await map_repo.find_all(spec=spec)


async def load_relevant_memories(
    repositories: RepositoriesDict,
    chapter: Chapter,
    outline_text: str,
    book_id: str,
    chapter_number: int,
    api_key: str,
    base_url: Optional[str],
    rag_params: Dict[str, Any]
) -> List[Any]:
    """加载 RAG 相关记忆"""
    if not outline_text:
        return []
    
    memory_repo: "MemoryRepository" = repositories.get("memory")
    if not memory_repo:
        svc_logger.warning("MemoryRepository 未配置，跳过 RAG 检索")
        return []
    
    try:
        embedding = await get_embedding(outline_text, api_key, base_url)
        if not embedding:
            svc_logger.warning("Embedding generation returned empty")
            return []
        
        memories = await memory_repo.search_similar(
            embedding,
            book_id,
            limit=rag_params.get("top_k", 5),
            alpha=rag_params.get("alpha", 0.6),
            beta=rag_params.get("beta", 0.2),
            gamma=rag_params.get("gamma", 0.2),
            lambda_decay=rag_params.get("lambda", 0.01),
            exclude_chapter_id=chapter.id if chapter else None,
            max_chapter_number=chapter_number - 1,
        )
        
        svc_logger.debug(
            "RAG search completed",
            count=len(memories),
            top_k=rag_params.get("top_k"),
            alpha=rag_params.get("alpha")
        )
        return memories
    except Exception as e:
        svc_logger.error("RAG search failed", error=str(e))
        return []


class ChapterContext:
    """章节上下文数据容器"""
    
    def __init__(
        self,
        chapter: Chapter,
        book: Optional[Book] = None,
        entities: Optional[List[ChapterEntity]] = None,
        relationships: Optional[List[CharacterRelationship]] = None,
        previous_summary: Optional[str] = None,
        previous_world_snapshot: Optional[dict] = None,
        open_hooks: Optional[List[Dict[str, str]]] = None,
        locations: Optional[List[Any]] = None,
        relevant_memories: Optional[List[Any]] = None,
    ):
        self.chapter = chapter
        self.book = book
        self.entities = entities or []
        self.relationships = relationships or []
        self.previous_summary = previous_summary
        self.previous_world_snapshot = previous_world_snapshot
        self.open_hooks = open_hooks or []
        self.locations = locations or []
        self.relevant_memories = relevant_memories or []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_id": str(self.chapter.id) if self.chapter else None,
            "book_id": str(self.book.id) if self.book else None,
            "entities_count": len(self.entities),
            "relationships_count": len(self.relationships),
            "has_previous_summary": bool(self.previous_summary),
            "has_world_snapshot": bool(self.previous_world_snapshot),
            "open_hooks_count": len(self.open_hooks),
            "locations_count": len(self.locations),
            "memories_count": len(self.relevant_memories),
        }


async def load_full_chapter_context(
    chapter_id: str,
    repositories: RepositoriesDict,
    rag_params: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[ChapterContext]:
    """加载完整的章节上下文（一站式加载所有数据）

    新接口：使用 repositories 参数

    Args:
        chapter_id: 章节 ID
        repositories: Repository 字典
        rag_params: 可选的 RAG 参数
        api_key: 可选的 API Key
        base_url: 可选的 Base URL

    Returns:
        ChapterContext 数据容器，或 None
    """
    chapter = await load_chapter(repositories, chapter_id)
    if not chapter:
        return None

    book = await load_book(repositories, chapter.book_id) if chapter.book_id else None
    entities = await load_chapter_entities(repositories, chapter_id)
    relationships = await load_character_relationships(repositories, entities)
    previous_summary = await load_previous_chapter_summary(repositories, chapter)
    previous_world_snapshot = await load_previous_world_snapshot(repositories, chapter)
    open_hooks = await load_open_hooks(repositories, chapter)
    locations = await load_chapter_locations(repositories, chapter_id)

    relevant_memories = []
    if rag_params and api_key and chapter.outline_text:
        relevant_memories = await load_relevant_memories(
            repositories, chapter, chapter.outline_text,
            chapter.book_id, chapter.chapter_number,
            api_key, base_url, rag_params
        )

    return ChapterContext(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        previous_summary=previous_summary,
        previous_world_snapshot=previous_world_snapshot,
        open_hooks=open_hooks,
        locations=locations,
        relevant_memories=relevant_memories,
    )

"""
上下文加载服务模块 (Context Loader Service)

职责：
- 封装章节生成所需的上下文数据加载逻辑
- 统一处理数据库查询，避免路由层直接操作数据库
- 提供标准化的上下文数据结构

设计原则：
- 单一职责：每个加载函数只负责一种数据类型
- 可复用：可被多个路由/服务共享
- 类型安全：返回类型明确，便于 IDE 提示

业务场景：
- AI 章节生成工作流启动前，需要组装完整的上下文信息
- 上下文包括：章节本身、关联角色、角色关系、上一章摘要、开放伏笔、RAG 记忆等
- 这些数据的加载逻辑被统一封装在此模块，供 Agentic Workflow 调用

依赖项：
- SQLAlchemy (异步 ORM)
- MemoryRepository (向量记忆检索)
- LLM Client (Embedding 生成)

使用方式：
    # 方式1：一站式加载完整上下文
    context = await load_full_chapter_context(db, chapter_id, rag_params, api_key)
    
    # 方式2：按需加载特定数据
    chapter = await load_chapter(db, chapter_id)
    entities = await load_chapter_entities(db, chapter_id)
    memories = await load_relevant_memories(db, chapter, outline, ...)
"""

from typing import List, Optional, Dict, Any
from sqlalchemy import select, and_, or_, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import (
    Chapter, Book, ChapterEntity, CharacterRelationship,
    ChapterMapLocation, PlotLedger, StoryBeat
)
from backend.repositories import MemoryRepository
from backend.services.llm import get_embedding
from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_RAG

import logging

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_RAG)


# =============================================================================
# 数据加载函数
# =============================================================================

async def load_chapter(db: AsyncSession, chapter_id: str) -> Optional[Chapter]:
    """
    加载章节及其关联的 story_beats
    
    业务目的：
    - 获取章节的基本信息（标题、大纲、字数目标等）
    - 同时预加载关联的 story_beats，避免后续 N+1 查询问题
    
    设计决策：
    - 使用 selectinload 进行预加载，将关联查询优化为两条 SQL 语句
    - 返回 Optional，调用方需要处理章节不存在的情况
    
    Args:
        db: 数据库会话（由 FastAPI Depends 注入）
        chapter_id: 章节唯一标识符（UUID 字符串）
        
    Returns:
        Chapter 对象（包含预加载的 story_beats）或 None
        
    副作用：
    - 执行数据库查询，可能触发网络 I/O
    - 如果 chapter_id 无效，返回 None 而不是抛出异常
    """
    result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.story_beats))
        .where(Chapter.id == chapter_id)
    )
    return result.scalar_one_or_none()


async def load_book(db: AsyncSession, book_id: str) -> Optional[Book]:
    """
    加载书籍基本信息
    
    业务目的：
    - 获取书籍的元数据（书名、世界观设定、风格指南等）
    - 用于在 Prompt 中提供全局上下文
    
    Args:
        db: 数据库会话
        book_id: 书籍唯一标识符
        
    Returns:
        Book 对象或 None
        
    注意：
    - 当前实现为简单查询，未来可能需要预加载关联数据
    """
    result = await db.execute(select(Book).where(Book.id == book_id))
    return result.scalar_one_or_none()


async def load_chapter_entities(db: AsyncSession, chapter_id: str) -> List[ChapterEntity]:
    """
    加载章节关联的实体（角色）
    
    业务目的：
    - 获取本章出场的所有角色列表
    - 预加载角色详细信息（姓名、性格、外貌等）
    - 用于构建角色卡片，注入到 Prompt 中
    
    数据流：
    ChapterEntity 是关联表，关联 Chapter 和 Character
    - ChapterEntity.character: 指向 Character 实体（预加载）
    - ChapterEntity.role: 角色在本章中的角色定位（主角/配角等）
    
    Args:
        db: 数据库会话
        chapter_id: 章节 ID
        
    Returns:
        ChapterEntity 列表（每个元素包含关联的 Character 数据）
        
    注意：
    - 如果章节没有关联角色，返回空列表而非 None
    - 使用 selectinload 避免 N+1 查询
    """
    result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    return list(result.scalars().all())


async def load_character_relationships(
    db: AsyncSession, 
    entities: List[ChapterEntity]
) -> List[CharacterRelationship]:
    """
    加载角色之间的关系网络
    
    业务目的：
    - 获取本章出场角色之间的所有关系
    - 用于构建关系图谱，帮助 AI 理解角色互动
    
    设计决策：
    - 关系是双向的：只查询 source 和 target 都在出场角色列表中的关系
    - 预加载 source_character 和 target_character，避免后续查询
    
    数据流：
    ChapterEntity[] → character_ids[] → CharacterRelationship[]
    
    Args:
        db: 数据库会话
        entities: 章节关联的实体列表（来自 load_chapter_entities）
        
    Returns:
        CharacterRelationship 列表（包含关联的角色对象）
        
    边缘情况：
    - 如果 entities 为空，直接返回空列表
    - 如果角色之间没有关系，返回空列表
    
    性能考虑：
    - 使用 IN 查询一次性获取所有关系，避免循环查询
    """
    # 提取所有有效的角色 ID
    character_ids = [e.entity_id for e in entities if e.entity_id]
    if not character_ids:
        return []
    
    # 查询这些角色之间的关系（双向都在列表中）
    result = await db.execute(
        select(CharacterRelationship)
        .options(
            selectinload(CharacterRelationship.source_character),
            selectinload(CharacterRelationship.target_character)
        )
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    return list(result.scalars().all())


async def load_previous_chapter_summary(db: AsyncSession, chapter: Chapter) -> Optional[str]:
    """
    加载上一章摘要，用于提供叙事连续性上下文
    
    业务目的：
    - 为 AI 提供上一章的剧情回顾，确保叙事连贯
    - 支持多层级回退策略，最大化获取可用信息
    
    优先级策略（从高到低）：
    1. summary: 人工编写或 AI 生成的摘要（最理想）
    2. draft_text: 草稿文本的最后 1000 字（次选）
    3. content_text: 正式内容的最后 1000 字（备选）
    4. 章节信息提示: 仅显示章节名称（保底）
    
    设计决策：
    - 限制提取长度为 1000 字，避免 Prompt 过长
    - 对于草稿/正式内容，添加前缀说明来源
    
    Args:
        db: 数据库会话
        chapter: 当前章节对象（用于获取 book_id 和 chapter_number）
        
    Returns:
        上一章的摘要文本，或 None（如果是第一章或无法获取）
        
    边缘情况：
    - 第一章没有上一章，返回 None
    - 上一章数据不存在，返回 None
    - 上一章没有任何内容，返回提示信息
    """
    # 边界检查：第一章没有上一章
    if not chapter.book_id or chapter.chapter_number <= 1:
        return None
    
    # 查询上一章
    result = await db.execute(
        select(Chapter)
        .where(
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1
        )
    )
    prev_chapter = result.scalar_one_or_none()
    
    if not prev_chapter:
        return None
    
    # 按优先级返回可用内容
    if prev_chapter.summary:
        # 最理想：有预先生成的摘要
        return prev_chapter.summary
    elif prev_chapter.draft_text:
        # 次选：从草稿末尾提取
        return f"（上一章末尾原文）...{prev_chapter.draft_text[-1000:]}"
    elif prev_chapter.content_text:
        # 备选：从正式内容末尾提取
        return f"（上一章末尾原文）...{prev_chapter.content_text[-1000:]}"
    else:
        # 保底：仅返回章节信息
        prev_name = prev_chapter.chapter_name or f"第{prev_chapter.chapter_number}章"
        return f"（上一章【{prev_name}】内容未生成，标题：{prev_chapter.title or '未命名'}）"


async def load_previous_world_snapshot(db: AsyncSession, chapter: Chapter) -> Optional[dict]:
    """
    加载上一章的世界状态快照（World Terminal State）
    
    业务目的：
    - 获取上一章结束时的世界状态，用于跨章状态连续性约束
    - 确保角色位置、物品状态、时间线等在章节间保持一致
    
    数据格式：
    world_snapshot 是一个 JSON/dict，包含：
    - character_locations: 角色位置信息
    - item_states: 关键物品状态
    - time_info: 时间线信息
    - plot_flags: 剧情标记
    
    设计模式：
    - World Terminal State 模式：每章结束时记录世界状态
    - 下一章开始时读取该状态作为初始约束
    
    Args:
        db: 数据库会话
        chapter: 当前章节对象
        
    Returns:
        世界状态快照字典，或 None
        
    注意：
    - 如果上一章没有记录快照，返回 None
    - 调用方需要处理 None 的情况（使用默认初始状态）
    """
    if not chapter.book_id or chapter.chapter_number <= 1:
        return None
    
    result = await db.execute(
        select(Chapter)
        .where(
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1
        )
    )
    prev_chapter = result.scalar_one_or_none()
    
    return prev_chapter.world_snapshot if prev_chapter else None


async def load_open_hooks(db: AsyncSession, chapter: Chapter) -> List[Dict[str, str]]:
    """
    加载开放的伏笔/情节点（Plot Hooks）
    
    业务目的：
    - 获取当前章节之前埋下的、尚未闭合的伏笔
    - 提醒 AI 在生成本章内容时考虑这些开放情节点
    - 支持剧情连贯性和伏笔回收
    
    查询逻辑：
    1. 只查询状态为 "open" 的伏笔
    2. 只查询在当前章节之前创建的伏笔（避免未来信息泄露）
    3. 支持两种创建方式标记：
       - created_at_chapter: 显式记录的章节号
       - chapter_id 关联: 通过外键关联到历史章节
    
    数据模型：
    PlotLedger（情节账本）记录：
    - hook_id: 伏笔唯一标识
    - ledger_key: 账本键（用于分类）
    - content: 伏笔内容描述
    - status: open/closed（是否已闭合）
    
    Args:
        db: 数据库会话
        chapter: 当前章节对象
        
    Returns:
        开放伏笔列表，每个元素包含 hook_id、ledger_key、content
        
    边缘情况：
    - 没有 book_id 时返回空列表（孤立章节）
    - 第一章没有前置伏笔，通常返回空列表
    - 过滤掉 content 为空的无效记录
    
    FIXME: 当前查询逻辑较复杂，考虑后续优化为更简单的条件判断
    """
    if not chapter.book_id:
        return []
    
    # 只查询当前章节之前创建的伏笔
    hook_max_chapter_number = chapter.chapter_number - 1
    
    # 构建存在性检查子查询：验证 chapter_id 指向的是历史章节
    historical_chapter_exists = (
        select(Chapter.id)
        .where(
            Chapter.id == PlotLedger.chapter_id,
            Chapter.chapter_number <= hook_max_chapter_number,
        )
        .exists()
    )
    
    # 查询开放伏笔
    result = await db.execute(
        select(PlotLedger)
        .where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            or_(
                # 情况1：显式记录的章节号 <= 当前章节-1
                PlotLedger.created_at_chapter <= hook_max_chapter_number,
                # 情况2：没有显式记录，但关联的章节是历史章节
                and_(
                    PlotLedger.created_at_chapter.is_(None),
                    or_(PlotLedger.chapter_id.is_(None), historical_chapter_exists),
                ),
            ),
        )
    )
    
    # 转换为标准格式，过滤无效记录
    hooks = []
    for row in result.scalars().all():
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        # 兼容两种 ID 字段命名
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        hooks.append({
            "hook_id": hook_id,
            "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
            "content": content,
        })
    
    return hooks


async def load_chapter_locations(db: AsyncSession, chapter_id: str) -> List[Any]:
    """
    加载章节关联的地图位置
    
    业务目的：
    - 获取本章涉及的所有地点/场景
    - 预加载地点详细信息（名称、描述、地理坐标等）
    - 用于构建场景设定，帮助 AI 理解空间背景
    
    数据模型：
    ChapterMapLocation 是关联表，关联 Chapter 和 MapLocation
    - ChapterMapLocation.location: 指向 MapLocation 实体（预加载）
    - ChapterMapLocation.significance: 地点在本章中的重要性
    
    Args:
        db: 数据库会话
        chapter_id: 章节 ID
        
    Returns:
        ChapterMapLocation 列表（包含关联的 MapLocation 数据）
        
    注意：
    - 如果章节没有关联地点，返回空列表
    """
    result = await db.execute(
        select(ChapterMapLocation)
        .options(selectinload(ChapterMapLocation.location))
        .where(ChapterMapLocation.chapter_id == chapter_id)
    )
    return list(result.scalars().all())


async def load_relevant_memories(
    db: AsyncSession,
    chapter: Chapter,
    outline_text: str,
    book_id: str,
    chapter_number: int,
    api_key: str,
    base_url: Optional[str],
    rag_params: Dict[str, Any]
) -> List[Any]:
    """
    加载 RAG（检索增强生成）相关记忆
    
    业务目的：
    - 基于当前章节大纲进行语义检索，找到相关的历史记忆
    - 为 AI 提供可能遗忘的背景信息，增强生成质量
    - 实现"长期记忆"功能，突破上下文长度限制
    
    工作流程：
    1. 使用 Embedding API 将 outline_text 转换为向量
    2. 在向量数据库中搜索相似的记忆片段
    3. 应用混合评分策略（语义相似度 + 时间衰减 + 剧情权重）
    4. 返回最相关的记忆列表
    
    RAG 参数说明：
    - top_k: 返回的记忆数量上限
    - alpha: 语义相似度权重（默认 0.6）
    - beta: 时间衰减权重（默认 0.2）
    - gamma: 剧情伏笔权重（默认 0.2）
    - lambda: 时间衰减系数（默认 0.01）
    
    安全设计：
    - 排除当前章节的记忆（避免检索到刚写入的内容）
    - 限制检索范围为当前章节之前（避免未来信息泄露）
    - 异常时返回空列表，不中断主流程
    
    Args:
        db: 数据库会话
        chapter: 章节实体（用于排除当前章节）
        outline_text: 用于生成 embedding 的文本（通常是大纲）
        book_id: 书籍 ID（检索范围限制）
        chapter_number: 章节编号（时间范围限制）
        api_key: Embedding API Key
        base_url: Embedding API Base URL
        rag_params: RAG 参数字典
        
    Returns:
        MemoryChunk 列表（相关记忆片段）
        
    副作用：
    - 调用外部 Embedding API（网络 I/O）
    - 查询向量数据库（pgvector）
    - 记录调试日志
    
    异常处理：
    - Embedding 生成失败：返回空列表
    - 向量检索失败：返回空列表
    - 任何异常都被捕获，不影响主流程
    """
    if not outline_text:
        return []
    
    try:
        # Step 1: 生成查询向量
        embedding = await get_embedding(outline_text, api_key, base_url)
        if not embedding:
            svc_logger.warning("Embedding generation returned empty")
            return []
        
        # Step 2: 向量检索
        memory_repo = MemoryRepository(db)
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
        
        # Step 3: 记录检索结果
        svc_logger.debug(
            "RAG search completed",
            count=len(memories),
            top_k=rag_params.get("top_k"),
            alpha=rag_params.get("alpha")
        )
        return memories
    except Exception as e:
        # 错误降级：记录日志但不中断流程
        svc_logger.error("RAG search failed", error=str(e))
        return []


# =============================================================================
# 批量上下文加载
# =============================================================================

class ChapterContext:
    """
    章节上下文数据容器 (Data Transfer Object)
    
    职责：
    - 封装章节生成所需的全部上下文数据
    - 提供统一的数据访问接口
    - 支持序列化为字典（用于日志和调试）
    
    设计模式：
    - DTO (Data Transfer Object): 用于跨层数据传输
    - 不可变设计：初始化后数据不变，避免副作用
    
    数据组成：
    - chapter: 当前章节实体（核心）
    - book: 书籍元数据（全局上下文）
    - entities: 出场角色列表
    - relationships: 角色关系网络
    - previous_summary: 上一章摘要（连续性）
    - previous_world_snapshot: 上一章世界状态（状态连续性）
    - open_hooks: 开放伏笔列表（剧情连贯性）
    - locations: 涉及地点列表（空间背景）
    - relevant_memories: RAG 检索到的相关记忆（长期记忆）
    
    使用场景：
    - Agentic Workflow 启动时作为输入参数
    - Prompt Builder 构建 Prompt 时的数据源
    - 调试时输出上下文摘要
    """
    
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
        # 核心数据
        self.chapter = chapter
        self.book = book
        
        # 角色相关
        self.entities = entities or []
        self.relationships = relationships or []
        
        # 连续性数据
        self.previous_summary = previous_summary
        self.previous_world_snapshot = previous_world_snapshot
        
        # 剧情数据
        self.open_hooks = open_hooks or []
        self.locations = locations or []
        
        # 记忆数据
        self.relevant_memories = relevant_memories or []
    
    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典格式（用于日志记录和调试）
        
        注意：
        - 只输出统计信息，不输出完整内容（避免日志过大）
        - ID 转换为字符串（便于 JSON 序列化）
        """
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
    db: AsyncSession,
    chapter_id: str,
    rag_params: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Optional[ChapterContext]:
    """
    加载完整的章节上下文（一站式加载所有数据）
    
    业务目的：
    - 为 Agentic Workflow 提供统一的上下文加载入口
    - 并行/顺序加载所有需要的上下文数据
    - 封装数据加载的复杂性，对外提供简单的调用接口
    
    数据加载顺序：
    1. 核心数据（章节、书籍、角色）- 必须
    2. 角色关系 - 依赖角色数据
    3. 历史数据（上一章摘要、世界状态）- 依赖章节数据
    4. 剧情数据（伏笔、地点）- 独立加载
    5. RAG 记忆 - 可选，依赖外部 API
    
    设计决策：
    - 使用顺序加载而非并行，避免数据库连接池压力
    - RAG 记忆为可选功能，参数缺失时跳过
    - 章节不存在时返回 None，调用方需处理
    
    Args:
        db: 数据库会话
        chapter_id: 章节 ID
        rag_params: 可选的 RAG 参数（提供时启用记忆检索）
        api_key: 可选的 API Key（RAG 需要）
        base_url: 可选的 Base URL（RAG 需要）
        
    Returns:
        ChapterContext 数据容器，或 None（如果章节不存在）
        
    使用示例：
        context = await load_full_chapter_context(
            db, 
            chapter_id="uuid-string",
            rag_params={"top_k": 5, "alpha": 0.6},
            api_key="sk-xxx"
        )
        if not context:
            raise HTTPException(status_code=404, detail="Chapter not found")
        
        # 使用上下文数据
        prompt = build_prompt(context)
    
    性能考虑：
    - 当前为顺序加载，数据量大时可能需要优化为并行
    - 每个加载函数内部已使用预加载优化
    
    异常处理：
    - 章节不存在：返回 None
    - RAG 失败：记录日志，继续返回其他数据
    - 其他异常：向上抛出
    """
    # Step 1: 加载核心数据
    chapter = await load_chapter(db, chapter_id)
    if not chapter:
        return None
    
    book = await load_book(db, chapter.book_id) if chapter.book_id else None
    entities = await load_chapter_entities(db, chapter_id)
    relationships = await load_character_relationships(db, entities)
    
    # Step 2: 加载历史数据（用于连续性约束）
    previous_summary = await load_previous_chapter_summary(db, chapter)
    previous_world_snapshot = await load_previous_world_snapshot(db, chapter)
    
    # Step 3: 加载剧情数据
    open_hooks = await load_open_hooks(db, chapter)
    locations = await load_chapter_locations(db, chapter_id)
    
    # Step 4: 可选加载 RAG 记忆
    relevant_memories = []
    if rag_params and api_key and chapter.outline_text:
        relevant_memories = await load_relevant_memories(
            db, chapter, chapter.outline_text,
            chapter.book_id, chapter.chapter_number,
            api_key, base_url, rag_params
        )
    
    # Step 5: 组装上下文对象
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

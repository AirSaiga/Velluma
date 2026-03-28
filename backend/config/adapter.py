# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
统一配置适配层 (Unified Configuration Adapter)

职责：
- 为现有代码提供渐进式迁移路径
- 将 GenerateChapterAgenticRequest 转换为 GenerationConfig
- 集成新 RAG 检索系统
- 保持向后兼容性

使用方式：
    # 方式1：从请求构建配置
    config = adapt_request_to_config(request, chapter, book)
    
    # 方式2：在路由中使用依赖注入
    @router.post("/generate")
    async def generate(
        request: GenerateChapterAgenticRequest,
        config: GenerationConfig = Depends(get_generation_config),
    ):
        ...
    
    # 方式3：使用新 RAG 系统加载上下文
    context = await build_runtime_context_with_rag(db, config, api_key)
"""

from typing import Any, Dict, Optional
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import (
    GenerationConfig,
    StoryConfig,
    ChapterPlan,
    LLMConfig,
    RAGPolicy,
    WorkflowPolicy,
    ValidationPolicy,
    FeatureFlags,
    DerivationEngine,
    ConfigValidator,
    MemoryStrategy,
    CreativityLevel,
    RefinementDepth,
    EditorMode,
)
from backend.schemas import GenerateChapterAgenticRequest

logger = logging.getLogger(__name__)


def adapt_request_to_config(
    request: GenerateChapterAgenticRequest,
    chapter: Optional[Any] = None,
    book: Optional[Any] = None,
) -> GenerationConfig:
    """
    将旧版请求对象适配为统一配置对象
    
    V3.8 更新：支持基础模式和专家模式
    - 基础模式：只传递高层语义参数，后端自动推导底层技术参数
    - 专家模式：传递完整技术参数，后端不做推导
    
    Args:
        request: GenerateChapterAgenticRequest 实例
        chapter: Chapter 实体（可选）
        book: Book 实体（可选）
    
    Returns:
        GenerationConfig: 统一配置对象
    """
    # 确定编辑模式
    # V3.8+ 简化：仅支持意图驱动模式
    editor_mode = EditorMode.INTENT
    is_basic = True  # 始终使用参数推导逻辑
    
    # 构建 StoryConfig
    story_config = StoryConfig()
    if book:
        story_config = StoryConfig.from_book(book)
    
    # 构建 ChapterPlan
    chapter_plan = ChapterPlan(
        chapter_number=getattr(chapter, "chapter_number", 1) if chapter else 1,
        title=getattr(chapter, "title", "") or getattr(chapter, "chapter_name", "") if chapter else "",
        outline=getattr(chapter, "outline_text", "") if chapter else "",
        author_intent=request.author_intent or "",
        target_word_count=request.word_count or 3000,
        tension_level=request.tension_level or 3,
        pacing_style=request.pacing_style or "balanced",
    )
    
    # 构建 LLMConfig
    llm_config = LLMConfig(
        api_key=request.api_key,
        base_url=request.base_url,
        default_model=request.model,
        reasoning_model=request.reasoning_model,
        creative_model=request.creative_model,
    )
    
    # 设置推理配置
    if request.reasoning_config:
        llm_config.default_reasoning_config.enabled = request.reasoning_config.enabled
        llm_config.default_reasoning_config.effort = request.reasoning_config.effort or "medium"
        if request.reasoning_config.max_tokens:
            llm_config.default_reasoning_config.max_tokens = request.reasoning_config.max_tokens
    
    if request.reasoning_model_reasoning_config:
        llm_config.reasoning_model_config.enabled = request.reasoning_model_reasoning_config.enabled
        llm_config.reasoning_model_config.effort = request.reasoning_model_reasoning_config.effort or "high"
    
    if request.creative_model_reasoning_config:
        llm_config.creative_model_config.enabled = request.creative_model_reasoning_config.enabled
        llm_config.creative_model_config.effort = request.creative_model_reasoning_config.effort or "low"
    
    # === 构建 RAGPolicy（自动推导）===
    # 解析记忆策略
    memory_strategy = MemoryStrategy.BALANCED_REFERENCE
    if request.memory_strategy:
        try:
            memory_strategy = MemoryStrategy(request.memory_strategy)
        except ValueError:
            logger.warning(f"[Adapter] 未知的记忆策略: {request.memory_strategy}")
    
    # V3.8+ 简化：始终使用策略预设，自动推导 RAG 参数
    rag_policy = RAGPolicy(memory_strategy=memory_strategy)
    rag_policy.apply_strategy_preset()
    
    # === 构建 WorkflowPolicy（自动推导）===
    # 解析创作自由度
    creativity_level = CreativityLevel.BALANCED_CREATION
    if request.creativity_level:
        try:
            creativity_level = CreativityLevel(request.creativity_level)
        except ValueError:
            logger.warning(f"[Adapter] 未知的创作自由度: {request.creativity_level}")
    
    
    # 解析精修深度
    refinement_depth = RefinementDepth.STANDARD
    if request.refinement_depth:
        try:
            refinement_depth = RefinementDepth(request.refinement_depth)
        except ValueError:
            logger.warning(f"[Adapter] 未知的精修深度: {request.refinement_depth}")
    
    workflow_policy = WorkflowPolicy(
        creativity_level=creativity_level,
        refinement_depth=refinement_depth,
        max_iterations=request.max_iterations,
        fast_mode=request.fast_mode,
        skip_minor_refine=request.skip_minor_refine,
    )
    
    # V3.8+ 简化：始终根据 refinement_depth 推导 max_iterations
    workflow_policy.derive_from_refinement_depth()
    
    # 从 feature_flags 提取配置
    if request.feature_flags:
        workflow_policy.force_parallel_prose = request.feature_flags.force_parallel_prose
        workflow_policy.semi_parallel_prose = request.feature_flags.semi_parallel_prose
        
        # 双轨配置（如果请求中有）
        if hasattr(request, "enable_sketch_track"):
            workflow_policy.dual_track.enable_sketch_track = request.enable_sketch_track
        if hasattr(request, "enable_adversarial_alignment"):
            workflow_policy.dual_track.enable_adversarial_alignment = request.enable_adversarial_alignment
        if hasattr(request, "alignment_threshold"):
            workflow_policy.dual_track.alignment_threshold = request.alignment_threshold
        if hasattr(request, "sketch_ratio"):
            workflow_policy.dual_track.sketch_ratio = request.sketch_ratio
    
    # 构建 ValidationPolicy
    validation_policy = ValidationPolicy(
        refinement_depth=refinement_depth,  # 传递精修深度
    )
    if request.feature_flags:
        validation_policy.enable_fail_fast = request.feature_flags.enable_fail_fast
        validation_policy.fail_fast_max_attempts = request.feature_flags.fail_fast_max_attempts
        validation_policy.fail_fast_temperature_step = request.feature_flags.fail_fast_temperature_step
        validation_policy.enable_emotional_scratchpad = request.feature_flags.enable_emotional_scratchpad
    
    # 构建 FeatureFlags
    feature_flags = FeatureFlags()
    if request.feature_flags:
        feature_flags.enable_whisper_memory = request.feature_flags.enable_whisper_memory
    
    # 组装统一配置
    config = GenerationConfig(
        editor_mode=editor_mode,
        chapter_id=request.chapter_id,
        story=story_config,
        chapter=chapter_plan,
        llm=llm_config,
        rag=rag_policy,
        workflow=workflow_policy,
        validation=validation_policy,
        features=feature_flags,
    )
    
    # 执行参数推导
    engine = DerivationEngine()
    config = engine.derive(config)
    
    # 验证
    valid, errors = ConfigValidator.validate(config)
    if not valid:
        logger.warning(f"[adapt_request_to_config] 配置验证警告: {errors}")
    
    return config


def config_to_legacy_dict(config: GenerationConfig) -> Dict[str, Any]:
    """
    将统一配置转换为旧版字典格式（向后兼容）
    
    用于平滑迁移期间，与现有代码兼容
    
    Args:
        config: GenerationConfig 实例
    
    Returns:
        Dict: 旧版参数字典
    """
    return config.to_legacy_format()


def get_generation_config(
    request: GenerateChapterAgenticRequest,
    chapter: Optional[Any] = None,
    book: Optional[Any] = None,
) -> GenerationConfig:
    """
    依赖注入：获取统一配置
    
    用于 FastAPI 依赖注入
    
    Args:
        request: 请求对象
        chapter: Chapter 实体
        book: Book 实体
    
    Returns:
        GenerationConfig: 统一配置
    """
    return adapt_request_to_config(request, chapter, book)


# =============================================================================
# 高层语义参数处理器
# =============================================================================

class HighLevelParameterProcessor:
    """
    高层语义参数处理器
    
    职责：
    - 处理前端传入的高层语义参数
    - 自动推导底层技术参数
    """
    
    @staticmethod
    def process_memory_strategy(
        strategy: MemoryStrategy,
        rag_policy: RAGPolicy,
    ) -> RAGPolicy:
        """
        处理记忆检索策略
        
        根据策略预设自动设置 RAG 参数
        """
        from backend.config.derivation import MEMORY_STRATEGY_PRESETS
        
        preset = MEMORY_STRATEGY_PRESETS.get(strategy, {})
        if preset:
            rag_policy.top_k = preset.get("top_k", rag_policy.top_k)
            rag_policy.semantic_weight = preset.get("semantic_weight", rag_policy.semantic_weight)
            rag_policy.time_decay_weight = preset.get("time_decay_weight", rag_policy.time_decay_weight)
            rag_policy.foreshadowing_weight = preset.get("foreshadowing_weight", rag_policy.foreshadowing_weight)
            rag_policy.decay_factor = preset.get("decay_factor", rag_policy.decay_factor)
        
        return rag_policy
    
    @staticmethod
    def process_creativity_level(
        level: CreativityLevel,
        workflow_policy: WorkflowPolicy,
    ) -> WorkflowPolicy:
        """
        处理创作自由度
        
        根据创作自由度调整并行策略
        """
        if level == CreativityLevel.STRICT_PROMPT:
            workflow_policy.force_parallel_prose = False
            workflow_policy.semi_parallel_prose = False
        elif level == CreativityLevel.WILD_IMAGINATION:
            workflow_policy.force_parallel_prose = True
            workflow_policy.semi_parallel_prose = True
        else:  # BALANCED_CREATION
            workflow_policy.force_parallel_prose = False
            workflow_policy.semi_parallel_prose = True
        
        return workflow_policy
    
    @staticmethod
    def process_refinement_depth(
        depth: RefinementDepth,
        validation_policy: ValidationPolicy,
    ) -> ValidationPolicy:
        """
        处理精修深度
        
        根据精修深度调整校验阈值
        """
        thresholds = {
            RefinementDepth.LIGHT: 0.6,
            RefinementDepth.STANDARD: 0.7,
            RefinementDepth.DEEP: 0.85,
        }
        validation_policy.quality_threshold = thresholds.get(depth, 0.7)
        return validation_policy


# =============================================================================
# 运行时上下文构建器
# =============================================================================

class RuntimeContextBuilder:
    """
    运行时上下文构建器
    
    职责：
    - 从数据库加载上下文数据
    - 构建 RuntimeContext 对象
    """
    
    @staticmethod
    async def build(
        db: AsyncSession,
        config: GenerationConfig,
    ) -> Dict[str, Any]:
        """
        构建运行时上下文
        
        Args:
            db: 数据库会话
            config: 统一配置
        
        Returns:
            Dict: 运行时上下文
        """
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from backend.models import (
            Chapter, Book, Character, CharacterRelationship,
            ChapterEntity, PlotLedger, ChapterMapLocation,
        )
        
        context = {
            "chapter": None,
            "book": None,
            "characters": [],
            "relationships": [],
            "locations": [],
            "open_hooks": [],
            "previous_summary": None,
            "relevant_memories": [],
        }
        
        if not config.chapter_id:
            return context
        
        # 加载章节
        chapter_result = await db.execute(
            select(Chapter)
            .options(selectinload(Chapter.story_beats))
            .where(Chapter.id == config.chapter_id)
        )
        chapter = chapter_result.scalar_one_or_none()
        context["chapter"] = chapter
        
        if not chapter:
            return context
        
        # 加载书籍
        book_result = await db.execute(
            select(Book).where(Book.id == chapter.book_id)
        )
        context["book"] = book_result.scalar_one_or_none()
        
        # 加载角色
        entities_result = await db.execute(
            select(ChapterEntity)
            .options(selectinload(ChapterEntity.character))
            .where(ChapterEntity.chapter_id == config.chapter_id)
        )
        entities = entities_result.scalars().all()
        context["characters"] = [e.character for e in entities if e.character]
        
        # 加载关系
        character_ids = [e.entity_id for e in entities]
        if character_ids:
            from sqlalchemy import or_, and_
            rel_result = await db.execute(
                select(CharacterRelationship)
                .options(
                    selectinload(CharacterRelationship.source_character),
                    selectinload(CharacterRelationship.target_character),
                )
                .where(
                    CharacterRelationship.source_char_id.in_(character_ids),
                    CharacterRelationship.target_char_id.in_(character_ids),
                )
            )
            context["relationships"] = rel_result.scalars().all()
        
        # 加载地点
        locations_result = await db.execute(
            select(ChapterMapLocation)
            .options(selectinload(ChapterMapLocation.location))
            .where(ChapterMapLocation.chapter_id == config.chapter_id)
        )
        context["locations"] = locations_result.scalars().all()
        
        # 加载开放伏笔
        from sqlalchemy import or_, and_
        hook_result = await db.execute(
            select(PlotLedger).where(
                PlotLedger.book_id == chapter.book_id,
                PlotLedger.status == "open",
                PlotLedger.created_at_chapter <= chapter.chapter_number,
            )
        )
        context["open_hooks"] = [
            {
                "hook_id": getattr(row, "hook_id", ""),
                "ledger_key": getattr(row, "ledger_key", ""),
                "content": getattr(row, "content", ""),
            }
            for row in hook_result.scalars().all()
        ]
        
        # 加载上一章摘要
        prev_result = await db.execute(
            select(Chapter).where(
                Chapter.book_id == chapter.book_id,
                Chapter.chapter_number == chapter.chapter_number - 1,
            )
        )
        prev_chapter = prev_result.scalar_one_or_none()
        if prev_chapter:
            context["previous_summary"] = prev_chapter.summary or (
                prev_chapter.draft_text[-1000:] if prev_chapter.draft_text else None
            )

        return context


# =============================================================================
# 新 RAG 系统集成
# =============================================================================

async def build_runtime_context_with_rag(
    db: AsyncSession,
    config: GenerationConfig,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用新 RAG 系统构建运行时上下文
    
    这是迁移到新 RAG 架构的主要入口，替代旧的 load_chapter_context。
    
    Args:
        db: 数据库会话
        config: 统一配置
        api_key: API Key
        base_url: Base URL
        
    Returns:
        Dict: 运行时上下文，包含：
        - chapter: 章节实体
        - book: 书籍实体
        - characters: 角色列表
        - relationships: 关系列表
        - locations: 地点列表
        - open_hooks: 开放伏笔
        - previous_summary: 上一章摘要
        - rag_result: RAG 检索结果
        - context_package: 打包后的上下文
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from backend.models import (
        Chapter, Book, Character, CharacterRelationship,
        ChapterEntity, PlotLedger, ChapterMapLocation,
    )
    from backend.services.rag import (
        WorkflowRetrievalIntegrator,
        WorkflowStage,
        WorkflowIntegrationConfig,
    )
    
    context = {
        "chapter": None,
        "book": None,
        "characters": [],
        "relationships": [],
        "locations": [],
        "open_hooks": [],
        "previous_summary": None,
        "relevant_memories": [],
        "rag_result": None,
        "context_package": None,
    }
    
    if not config.chapter_id:
        return context
    
    # 加载基础数据（保持与旧接口兼容）
    chapter_result = await db.execute(
        select(Chapter)
        .options(selectinload(Chapter.story_beats))
        .where(Chapter.id == config.chapter_id)
    )
    chapter = chapter_result.scalar_one_or_none()
    context["chapter"] = chapter
    
    if not chapter:
        return context
    
    # 加载书籍
    book_result = await db.execute(
        select(Book).where(Book.id == chapter.book_id)
    )
    context["book"] = book_result.scalar_one_or_none()
    
    # 加载角色
    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == config.chapter_id)
    )
    entities = entities_result.scalars().all()
    context["characters"] = [e.character for e in entities if e.character]
    
    # 加载关系
    character_ids = [e.entity_id for e in entities]
    if character_ids:
        from sqlalchemy import or_, and_
        rel_result = await db.execute(
            select(CharacterRelationship)
            .options(
                selectinload(CharacterRelationship.source_character),
                selectinload(CharacterRelationship.target_character),
            )
            .where(
                CharacterRelationship.source_char_id.in_(character_ids),
                CharacterRelationship.target_char_id.in_(character_ids),
            )
        )
        context["relationships"] = rel_result.scalars().all()
    
    # 加载地点
    locations_result = await db.execute(
        select(ChapterMapLocation)
        .options(selectinload(ChapterMapLocation.location))
        .where(ChapterMapLocation.chapter_id == config.chapter_id)
    )
    context["locations"] = locations_result.scalars().all()
    
    # 加载上一章摘要
    prev_result = await db.execute(
        select(Chapter).where(
            Chapter.book_id == chapter.book_id,
            Chapter.chapter_number == chapter.chapter_number - 1,
        )
    )
    prev_chapter = prev_result.scalar_one_or_none()
    if prev_chapter:
        context["previous_summary"] = prev_chapter.summary or (
            prev_chapter.draft_text[-1000:] if prev_chapter.draft_text else None
        )
    
    # === 使用新 RAG 系统执行检索 ===
    try:
        # 构建工作流集成配置
        rag_config = WorkflowIntegrationConfig(
            default_strategy=_map_rag_policy_to_strategy(config.rag),
            enable_vector_search=config.rag.top_k > 0,
        )
        
        integrator = WorkflowRetrievalIntegrator(db, rag_config)
        
        # 执行检索
        package, result = await integrator.retrieve_chapter_context(
            chapter_id=config.chapter_id,
            api_key=api_key,
            base_url=base_url,
            stage=WorkflowStage.ASSEMBLING,
        )
        
        context["context_package"] = package
        context["rag_result"] = result
        
        # 从 RAG 结果提取开放伏笔
        from backend.services.rag import MemoryType
        hook_items = result.get_items_by_type(MemoryType.OPEN_HOOK)
        context["open_hooks"] = [
            {
                "hook_id": item.source_id,
                "ledger_key": item.source_id,
                "content": item.content,
            }
            for item in hook_items
        ]
        
        # 从 RAG 结果提取相关记忆
        memory_items = result.get_items_by_type(MemoryType.MEMORY_CHUNK)
        context["relevant_memories"] = [
            {"content": item.content, "chapter_number": item.chapter_number}
            for item in memory_items
        ]
        
        logger.info(
            f"[build_runtime_context_with_rag] RAG 检索完成: "
            f"{result.total_items} 项, 上下文 {package.total_length} 字"
        )
        
    except Exception as e:
        logger.warning(f"[build_runtime_context_with_rag] RAG 检索失败，使用降级: {e}")
        # 降级：使用旧的伏笔加载方式
        context["open_hooks"] = await _load_open_hooks_fallback(chapter, db)
    
    return context


def _map_rag_policy_to_strategy(rag_policy) -> "RetrievalStrategy":
    """
    将 RAGPolicy 映射到检索策略
    
    Args:
        rag_policy: RAGPolicy 实例
        
    Returns:
        RetrievalStrategy: 检索策略枚举
    """
    from backend.services.rag import RetrievalStrategy
    
    # 根据 top_k 判断
    if rag_policy.top_k <= 3:
        return RetrievalStrategy.FAST_TRACK
    elif rag_policy.top_k >= 8:
        return RetrievalStrategy.DEEP_DIVE
    else:
        return RetrievalStrategy.BALANCED_REFERENCE


async def _load_open_hooks_fallback(chapter, db) -> list:
    """
    降级：使用旧方式加载开放伏笔
    """
    from sqlalchemy import or_, and_
    hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
            PlotLedger.created_at_chapter <= chapter.chapter_number,
        )
    )
    return [
        {
            "hook_id": getattr(row, "hook_id", "") or getattr(row, "ledger_key", ""),
            "ledger_key": getattr(row, "ledger_key", ""),
            "content": getattr(row, "content", ""),
        }
        for row in hook_result.scalars().all()
    ]

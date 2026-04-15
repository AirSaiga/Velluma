"""
SSE 流处理器 (Stream Handler) - 双轨生成路由的流式响应处理。

职责：
- 处理 SSE 流式响应的生成器逻辑
- 管理生成流程的各个阶段
- 处理进度事件和心跳机制

主要功能：
- 上下文加载和准备
- 节拍确认和 POV 分配
- 工作流执行和结果处理
- 错误处理和资源清理

依赖项：
- backend.routes.chapter_generation.progress_tracker: 进度追踪器
- backend.routes.chapter_generation.checkpoint_manager: 检查点管理器
- backend.services.workflows.dual_track: 双轨工作流

使用方式：
    from backend.routes.chapter_generation.stream_handler import DualTrackStreamHandler

    handler = DualTrackStreamHandler(chapter_id, request, db, repos)
    async for event in handler.stream():
        yield event
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chapter
from backend.repositories import (
    ChapterRepository, BookRepository, MemoryRepository,
    PlotLedgerRepository, MapLocationRepository, RelationshipRepository,
)
from backend.services.orchestration import resolve_high_level_params, normalize_confirmed_beats
from backend.services.workflows.dual_track import (
    DualTrackWorkflow,
    DualTrackConfig,
    DualTrackResult,
)
from backend.services.workflows.sketch_generator import SketchGeneratorConfig
from backend.services.workflows.adversarial_aligner import AdversarialAlignerConfig
from backend.services.utils.prompt_logger import create_logger
from backend.services.utils.logging import (
    ServiceLogger, LOG_PREFIX_DUAL_TRACK, get_runtime_logger,
    build_sse_event, build_sse_done,
)
from backend.services.context import (
    load_full_chapter_context,
    save_story_beats,
    build_physical_state_lock,
)
from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.routes.chapter_generation.progress_tracker import (
    ProgressTracker,
    StreamEventBuilder,
)
from backend.routes.chapter_generation.checkpoint_manager import CheckpointManager

logger = get_runtime_logger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_DUAL_TRACK)

# 心跳间隔（秒）
HEARTBEAT_INTERVAL = 30


class DualTrackGenerationRequest(GenerateChapterAgenticRequest):
    """双轨生成请求（扩展原有请求）"""

    # 用户在 beat 预览弹窗中确认的节拍（若提供则跳过内部 PLANNING，直接使用）
    beats: Optional[List[ConfirmedStoryBeat]] = None

    # 双轨特有配置
    enable_sketch_track: bool = True
    enable_adversarial_alignment: bool = True
    use_sketch_for_refinement: bool = True
    alignment_threshold: float = 70.0

    # Sketch 配置
    sketch_ratio: float = 0.45  # Sketch 字数占比

    # 模型选择
    sketch_model: Optional[str] = None  # 默认使用 creative_model


class DualTrackStreamHandler:
    """
    双轨生成流处理器。

    职责：
    - 管理 SSE 流式响应的完整生命周期
    - 协调上下文加载、工作流执行、结果处理
    - 处理进度事件和心跳

    设计决策：
    - 使用 AsyncGenerator 进行流式响应
    - 内部管理所有状态，不依赖外部状态
    - 错误处理确保资源正确清理
    """

    def __init__(
        self,
        chapter_id: str,
        request: DualTrackGenerationRequest,
        db: AsyncSession,
        repos: Dict[str, Any],
    ):
        """
        初始化流处理器。

        Args:
            chapter_id: 章节 ID
            request: 生成请求
            db: 数据库会话
            repos: 仓库字典
        """
        self.chapter_id = chapter_id
        self.request = request
        self.db = db
        self.repos = repos

        # 初始化组件
        self.checkpoint_manager = CheckpointManager(db)
        self.progress_tracker = ProgressTracker()

        # 状态变量
        self.chapter: Optional[Chapter] = None
        self.book: Optional[Any] = None
        self.run_id: Optional[str] = None
        self.prompt_logger = None
        self.workflow_task: Optional[asyncio.Task] = None
        self.partial_result: Optional[DualTrackResult] = None
        self.beats_result: Optional[Tuple[List[dict], Optional[str]]] = None  # (beats, anchor_pov)

        # 工作流结果
        self.result: Optional[DualTrackResult] = None

    def _resolve_run_id(self, chapter: Optional[Chapter] = None) -> str:
        """解析运行 ID"""
        if self.request.generation_run_id:
            return self.request.generation_run_id
        if self.request.resume_from_checkpoint and chapter and chapter.generation_run_id:
            return str(chapter.generation_run_id)
        return f"run_{uuid4().hex}"

    async def stream(self) -> AsyncGenerator[str, None]:
        """
        生成 SSE 流式响应。

        Yields:
            SSE 格式的事件字符串
        """
        # 初始化
        self.prompt_logger = create_logger(chapter_id=self.chapter_id, book_id=None)
        self.prompt_logger._finalized = False
        self.prompt_logger._final_text_length = 0
        self.prompt_logger._total_iterations = 1
        self.prompt_logger._review_passed = False

        try:
            # 执行生成流程
            async for event in self._execute_generation():
                yield event

        except Exception as e:
            async for msg in self._handle_error(e):
                yield msg

        finally:
            # 确保清理资源
            await self._cleanup()

    async def _execute_generation(self) -> AsyncGenerator[str, None]:
        """执行完整的生成流程"""
        # ===================================================================
        # Phase 0: 初始化
        # ===================================================================
        resolved_params = resolve_high_level_params(self.request)
        self.run_id = self._resolve_run_id(None)

        svc_logger.info(
            f"[Generation] 阶段=START 状态=RUNNING chapter_id={self.chapter_id}",
            run_id=self.run_id,
        )

        yield build_sse_event("ASSEMBLING_CONTEXT", "加载章节上下文...")

        # ===================================================================
        # Phase 1: 加载上下文
        # ===================================================================
        context = await load_full_chapter_context(
            self.chapter_id,
            self.repos,
            rag_params=resolved_params if self.request.is_basic_mode() else None,
        )

        if not context:
            yield build_sse_event("ERROR", "章节不存在")
            return

        self.chapter = context.chapter
        self.book = context.book
        self.run_id = self._resolve_run_id(self.chapter)

        effective_word_count = self.request.word_count or 2000

        # 更新章节状态
        self.chapter.generation_run_id = self.run_id
        self.chapter.generation_status = {
            **(self.chapter.generation_status or {}),
            "run_id": self.run_id,
            "status": "running",
            "stage": "ASSEMBLING_CONTEXT",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self.db.commit()
        yield build_sse_event("GENERATION_RUN", "生成任务已初始化", generation_run_id=self.run_id)

        self.prompt_logger.book_id = str(self.chapter.book_id) if self.chapter.book_id else None

        # 更新章节设置
        if self.request.tension_level is not None:
            self.chapter.tension_level = self.request.tension_level
        if self.request.pacing_style:
            self.chapter.pacing_style = self.request.pacing_style
        await self.db.commit()

        # ===================================================================
        # Phase 2: 加载实体和关系数据
        # ===================================================================
        yield build_sse_event("ASSEMBLING_CONTEXT", "正在回顾前文与检索相关伏笔...")

        entities_list = list(context.entities)
        relationships_list = list(context.relationships)

        yield StreamEventBuilder.build_metric(
            "ASSEMBLING_CONTEXT_DONE",
            iteration=0,
            extra={
                "entities_count": len(entities_list),
                "relationships_count": len(relationships_list),
            },
        )

        await self.checkpoint_manager.persist(
            chapter=self.chapter,
            run_id=self.run_id,
            stage="ASSEMBLING_CONTEXT_DONE",
            status="running",
            payload={
                "entities": len(entities_list),
                "relationships": len(relationships_list),
                "memories": len(context.relevant_memories),
                "locations": len(context.locations),
            },
        )

        self.prompt_logger.set_context(
            chapter_info={
                "id": str(self.chapter.id),
                "title": self.chapter.title,
                "chapter_number": self.chapter.chapter_number,
                "chapter_name": self.chapter.chapter_name,
                "outline_preview": self.chapter.outline_text[:500] if self.chapter.outline_text else "",
            },
            book_info={
                "id": str(self.book.id) if self.book else None,
                "title": self.book.title if self.book else None,
                "genre": self.book.genre if self.book else None,
            },
            entities=entities_list,
            relationships=relationships_list,
            request_params={
                "run_id": self.run_id,
                "max_iterations": resolved_params["max_iterations"],
                "rag_top_k": resolved_params["rag_top_k"],
                "word_count": effective_word_count,
            },
        )

        yield StreamEventBuilder.build_context_loaded(
            len(entities_list),
            len(relationships_list),
        )

        # ===================================================================
        # Phase 3: 处理节拍
        # ===================================================================
        async for event in self._process_beats_stream(context, effective_word_count):
            yield event
        beats, anchor_pov = self.beats_result or ([], None)

        # ===================================================================
        # Phase 4: 执行双轨工作流
        # ===================================================================
        async for event in self._execute_workflow(
            beats=beats,
            anchor_pov=anchor_pov,
            context=context,
            effective_word_count=effective_word_count,
        ):
            yield event

    async def _process_beats_stream(
        self,
        context: Any,
        effective_word_count: int,
    ) -> AsyncGenerator[str, None]:
        """
        处理节拍数据并生成 SSE 事件的异步生成器。

        这是 _process_beats 的包装方法，确保正确处理异步生成器。

        Args:
            context: 章节上下文
            effective_word_count: 目标字数

        Yields:
            SSE 格式的事件字符串
        """
        async for event in self._process_beats(context, effective_word_count):
            yield event

    async def _process_beats(
        self,
        context: Any,
        effective_word_count: int,
    ) -> AsyncGenerator[str, None]:
        """
        处理节拍数据并生成 SSE 事件。

        职责：
        - 检查缓存的生成结果
        - 获取或生成节拍数据
        - 注入世界状态约束
        - 分配 POV 角色
        - 保存节拍到数据库

        Args:
            context: 章节上下文
            effective_word_count: 目标字数

        Yields:
            SSE 格式的事件字符串

        注意:
            结果存储在 self.beats_result 属性中，供调用方使用
        """
        from backend.services.workflows.planning import assign_pov_to_beats
        from backend.services.prompts.world_state_prompts import format_snapshot_for_planner

        # 检查缓存
        latest_status = self.chapter.generation_status or {}
        if (
            self.request.resume_from_checkpoint
            and latest_status.get("run_id") == self.run_id
            and latest_status.get("status") == "completed"
        ):
            cached_text = latest_status.get("final_text") or self.chapter.draft_text or ""
            if cached_text:
                yield StreamEventBuilder.build_done(
                    final_text=cached_text,
                    stats=latest_status.get("stats") or {},
                    passed=bool(latest_status.get("passed", True)),
                    iterations=1,
                    revision_count=int(latest_status.get("revision_count", 0) or 0),
                    generation_run_id=self.run_id,
                    resumed=True,
                )
                self.result = True  # 标记为已完成
                self.beats_result = [], None  # 存储结果
                return  # async generator

        # 获取节拍
        beats = []
        if self.request.beats:
            beats = normalize_confirmed_beats(self.request.beats, effective_word_count)
        elif self.request.resume_from_checkpoint and latest_status.get("run_id") == self.run_id:
            for checkpoint in reversed(self.chapter.generation_checkpoints or []):
                if checkpoint.get("stage") == "BEATS_CONFIRMED":
                    beats = checkpoint.get("payload", {}).get("beats", [])
                    if beats:
                        break

        if not beats:
            raise ValueError("恢复失败：缺少可用 beats，请重新预览并确认节拍")

        # 注入世界状态约束
        if context.previous_world_snapshot:
            world_snapshot = format_snapshot_for_planner(context.previous_world_snapshot)
            for beat_dict in beats:
                beat_dict["_world_snapshot_constraints"] = world_snapshot
            svc_logger.info("[Generation] 阶段=WORLD_SNAPSHOT 状态=ENABLED")

        chapter_narrative_anchor = next(
            (b.get("pov_character") or "" for b in beats if b.get("pov_character")),
            "",
        )

        yield StreamEventBuilder.build_beats_confirmed(len(beats))

        # 记录节拍
        self.prompt_logger.start_stage("BEATS_CONFIRMED", iteration=1)
        self.prompt_logger.log_inputs(
            word_count=effective_word_count,
            has_previous_summary=bool(context.previous_summary),
            source="user_confirmed_beats",
        )
        self.prompt_logger.log_outputs(
            beat_count=len(beats),
            beats_preview=[
                {"id": b.get("beat_id"), "summary": b.get("summary", "")[:100]} for b in beats
            ],
            chapter_narrative_anchor=chapter_narrative_anchor or None,
        )
        self.prompt_logger.end_stage(success=True)

        await self.checkpoint_manager.persist(
            chapter=self.chapter,
            run_id=self.run_id,
            stage="BEATS_CONFIRMED",
            status="running",
            payload={
                "beats": beats,
                "chapter_narrative_anchor": chapter_narrative_anchor or "",
            },
        )

        yield StreamEventBuilder.build_metric(
            "PLANNING_DONE",
            iteration=1,
            extra={
                "beat_count": len(beats),
                "chapter_narrative_anchor": chapter_narrative_anchor,
            },
        )

        # POV 分配
        try:
            yield build_sse_event("POV_ASSIGNMENT", "正在为剧情节拍分配 POV 角色...", iteration=1)

            seen_char_ids: set = set()
            pov_candidates = []
            for e in context.entities:
                if e.character and str(e.character.id) not in seen_char_ids:
                    seen_char_ids.add(str(e.character.id))
                    pov_candidates.append({
                        "name": e.character.name,
                        "role": "Main" if e.character.importance_level >= 8 else "Supporting",
                        "description": e.character.static_prompt or "",
                    })

            book_title = self.book.title if self.book else "Unknown Book"
            story_premise = f"Title: {book_title}\nChapter Outline: {self.chapter.outline_text or ''}"

            beats, pov_prompt_data = await assign_pov_to_beats(
                beats=beats,
                characters=pov_candidates,
                story_premise=story_premise,
                previous_chapter_summary=context.previous_summary,
                prompt_logger=self.prompt_logger,
                chapter_narrative_anchor=chapter_narrative_anchor,
            )

            yield f"data: {json.dumps({'prompt': pov_prompt_data}, ensure_ascii=False)}\n\n"
            svc_logger.info("[Generation] 阶段=POV_ASSIGNMENT 状态=SUCCESS")

        except Exception as e:
            svc_logger.error("POV Assignment failed", error=str(e))

        anchor_pov = beats[0].get("pov_character") if beats else None

        # 保存节拍到数据库
        story_beats = await save_story_beats(self.db, self.chapter, beats)
        svc_logger.info(
            f"[Generation] 阶段=STATE_PERSISTENCE 状态=SUCCESS story_beats={len(story_beats)}"
        )

        await self.checkpoint_manager.persist(
            chapter=self.chapter,
            run_id=self.run_id,
            stage="STATE_PERSISTENCE",
            status="running",
            payload={"saved_story_beats": len(story_beats)},
        )

        # 存储结果供调用方使用
        self.beats_result = beats, anchor_pov

    async def _execute_workflow(
        self,
        beats: List[dict],
        anchor_pov: Optional[str],
        context: Any,
        effective_word_count: int,
    ) -> AsyncGenerator[str, None]:
        """执行双轨工作流"""
        physical_state_lock = build_physical_state_lock(beats)

        # 构建配置
        config = DualTrackConfig(
            enable_sketch_track=self.request.enable_sketch_track,
            enable_adversarial_alignment=self.request.enable_adversarial_alignment,
            use_sketch_for_refinement=self.request.use_sketch_for_refinement,
            alignment_threshold=self.request.alignment_threshold,
            sketch_config=SketchGeneratorConfig(
                sketch_ratio=self.request.sketch_ratio,
            ),
            aligner_config=AdversarialAlignerConfig(
                min_acceptable_score=self.request.alignment_threshold,
            ),
        )

        # 创建工作流
        workflow = DualTrackWorkflow(
            config=config,
            prompt_logger=self.prompt_logger,
        )

        yield build_sse_event("DUAL_TRACK_START", "启动双轨并行生成...")
        yield build_sse_event("DRAFTING", "主笔 Agent 正在并行扩写节拍...", iteration=1)

        # 定义进度回调
        async def progress_callback(event: str, message: str, **kwargs):
            await self.progress_tracker.emit(event, message, **kwargs)

        # 执行工作流
        async def run_workflow():
            try:
                return await workflow.execute(
                    chapter=self.chapter,
                    book=self.book,
                    beats=beats,
                    entities=context.entities,
                    relationships=context.relationships,
                    word_count=effective_word_count,
                    previous_summary=context.previous_summary,
                    relevant_memories=context.relevant_memories,
                    locations=context.locations,
                    physical_state_lock=physical_state_lock,
                    chapter_assets_schema=self.chapter.chapter_assets_schema or "",
                    anchor_pov=anchor_pov,
                    progress_callback=progress_callback,
                )
            finally:
                self.progress_tracker.mark_done()

        # 并发执行工作流和进度事件处理
        self.workflow_task = asyncio.create_task(run_workflow())
        last_heartbeat_time = datetime.now(timezone.utc).timestamp()

        try:
            while True:
                # 等待进度事件
                event_data = await self.progress_tracker.get_event(timeout=0.5)

                if event_data is None:
                    # 超时，检查是否需要心跳
                    current_time = datetime.now(timezone.utc).timestamp()
                    if current_time - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                        yield StreamEventBuilder.build_heartbeat(self.run_id)
                        last_heartbeat_time = current_time

                    # 检查工作流是否完成
                    if self.workflow_task.done():
                        # 处理剩余事件
                        for pending in await self.progress_tracker.get_all_pending():
                            yield f"data: {json.dumps(pending, ensure_ascii=False)}\n\n"
                        break
                    continue

                # 发送事件
                yield f"data: {json.dumps(event_data, ensure_ascii=False)}\n\n"
                last_heartbeat_time = datetime.now(timezone.utc).timestamp()

                # 检查工作流是否完成
                if self.workflow_task.done():
                    break

            # 获取结果
            self.result = await self.workflow_task

        except (GeneratorExit, asyncio.CancelledError) as cancel_e:
            async for event in self._handle_cancellation(cancel_e):
                yield event
            raise

        # 处理结果
        async for event in self._process_result():
            yield event

    async def _process_result(self) -> AsyncGenerator[str, None]:
        """处理工作流结果"""
        if not self.result or not hasattr(self.result, 'final_text'):
            return

        result = self.result

        # 更新 prompt logger
        self.prompt_logger._final_text_length = len(result.final_text) if result.final_text else 0
        self.prompt_logger._review_passed = not (
            result.adjustment_plan and result.adjustment_plan.needs_adjustment
        )

        needs_adjustment = result.adjustment_plan.needs_adjustment if result.adjustment_plan else False

        # 发送 Track A 完成
        yield StreamEventBuilder.build_track_a_done(len(result.beat_drafts))

        # 保存部分结果
        if result.beat_drafts:
            partial_text = "\n\n".join([d.draft_chunk for d in result.beat_drafts if d.draft_chunk])
            if partial_text:
                self.chapter.draft_text = partial_text
                self.chapter.generation_status = {
                    **(self.chapter.generation_status or {}),
                    "run_id": self.run_id,
                    "status": "running",
                    "stage": "PARTIAL_SAVE",
                    "partial_beats_count": len(result.beat_drafts),
                    "partial_text_length": len(partial_text),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                await self.db.commit()
                yield build_sse_event(
                    "PARTIAL_SAVE",
                    f"已保存 {len(result.beat_drafts)} 个节拍的草稿（{len(partial_text)} 字）",
                    partial_text_length=len(partial_text),
                    beat_count=len(result.beat_drafts),
                )

        # 发送 Track B 完成
        if result.sketch_result:
            yield StreamEventBuilder.build_track_b_done(result.sketch_result.word_count)

        # 发送审阅结果
        yield StreamEventBuilder.build_stitching()

        if result.adjustment_plan:
            yield StreamEventBuilder.build_reviewing(
                score=result.adjustment_plan.alignment_score,
                needs_fix=result.adjustment_plan.needs_adjustment,
            )

        # 发送最终文本流
        yield StreamEventBuilder.build_final_text_stream(passed=not needs_adjustment)

        # 流式输出文本
        final_text = result.final_text or ""
        chunk_size = 100
        for i in range(0, len(final_text), chunk_size):
            chunk = final_text[i:i + chunk_size]
            try:
                yield StreamEventBuilder.build_text_chunk(chunk)
            except Exception:
                raise GeneratorExit("Client disconnected")

        # 保存最终结果
        self.chapter.draft_text = result.final_text
        self.chapter.review_feedback = {
            **(self.chapter.review_feedback or {}),
            "generation_run_id": self.run_id,
            "alignment_score": (
                result.adjustment_plan.alignment_score
                if result.adjustment_plan else None
            ),
            "needs_adjustment": needs_adjustment,
            "stats": result.stats,
        }
        self.chapter.revision_count = 1 if needs_adjustment else 0

        # 完成状态
        self.chapter.generation_status = {
            **(self.chapter.generation_status or {}),
            "run_id": self.run_id,
            "status": "completed",
            "stage": "DONE",
            "passed": not needs_adjustment,
            "revision_count": self.chapter.revision_count,
            "stats": result.stats,
            "final_text": result.final_text,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        await self.checkpoint_manager.persist(
            chapter=self.chapter,
            run_id=self.run_id,
            stage="DONE",
            status="completed",
            payload={
                "alignment_score": (
                    result.adjustment_plan.alignment_score
                    if result.adjustment_plan else None
                ),
                "final_length": len(result.final_text or ""),
                "stats": result.stats,
            },
        )

        # 发送完成事件
        yield StreamEventBuilder.build_done(
            final_text=result.final_text,
            stats=result.stats,
            passed=not needs_adjustment,
            iterations=1,
            revision_count=1 if needs_adjustment else 0,
            generation_run_id=self.run_id,
            resumed=self.request.resume_from_checkpoint,
            alignment_score=(
                result.adjustment_plan.alignment_score
                if result.adjustment_plan else None
            ),
        )

        # 完成日志
        self.prompt_logger.finalize(
            final_text_length=self.prompt_logger._final_text_length,
            total_iterations=1,
            review_passed=self.prompt_logger._review_passed,
        )
        self.prompt_logger._finalized = True

    async def _handle_cancellation(self, cancel_e: Exception) -> AsyncGenerator[str, None]:
        """处理取消/断开连接"""
        svc_logger.warning(
            "[Generation] 阶段=CANCELLED 状态=RUNNING 原因=客户端取消",
            run_id=self.run_id,
            exc_type=type(cancel_e).__name__,
        )

        if self.workflow_task and not self.workflow_task.done():
            self.workflow_task.cancel()
            try:
                self.partial_result = await self.workflow_task
            except asyncio.CancelledError:
                svc_logger.info(
                    "[Generation] 阶段=CANCELLED 状态=SUCCESS task=workflow_cancelled",
                    run_id=self.run_id,
                )
            except Exception as workflow_e:
                svc_logger.warning(
                    "[Generation] 阶段=CANCELLED 状态=WARNING 原因=工作流取消时异常",
                    run_id=self.run_id,
                    error=str(workflow_e),
                )

        # 保存部分结果
        if (
            self.partial_result
            and hasattr(self.partial_result, 'final_text')
            and self.partial_result.final_text
        ):
            try:
                self.chapter.draft_text = self.partial_result.final_text
                self.chapter.generation_status = {
                    **(self.chapter.generation_status or {}),
                    "run_id": self.run_id,
                    "status": "cancelled",
                    "stage": "CANCELLED",
                    "partial_text_length": len(self.partial_result.final_text),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                await self.checkpoint_manager.persist(
                    chapter=self.chapter,
                    run_id=self.run_id,
                    stage="CANCELLED",
                    status="cancelled",
                    payload={
                        "reason": "client_disconnected",
                        "partial_text_length": len(self.partial_result.final_text),
                    },
                )
                svc_logger.info(
                    "[Generation] 阶段=CANCELLED 状态=PARTIAL_SAVED",
                    run_id=self.run_id,
                    text_length=len(self.partial_result.final_text),
                )
            except Exception as save_e:
                svc_logger.error(
                    "[Generation] 阶段=CANCELLED 状态=ERROR 原因=保存部分结果失败",
                    run_id=self.run_id,
                    error=str(save_e),
                )

        try:
            yield build_sse_event("CANCELLED", "生成任务已取消", run_id=self.run_id)
        except Exception:
            pass

    async def _handle_error(self, e: Exception) -> AsyncGenerator[str, None]:
        """处理错误"""
        exc_type = type(e).__name__
        error_msg = f"生成失败 ({exc_type}): {str(e)}"

        svc_logger.error(
            f"[Generation] 阶段=ERROR 状态=FAILED 异常类型={exc_type}",
            error=str(e),
        )

        is_cancelled = isinstance(e, (GeneratorExit, asyncio.CancelledError))
        target_status = "cancelled" if is_cancelled else "failed"

        # 保存失败状态
        if self.chapter is not None and self.run_id is not None:
            try:
                asyncio.create_task(
                    self.checkpoint_manager.persist(
                        chapter=self.chapter,
                        run_id=self.run_id,
                        stage=target_status.upper(),
                        status=target_status,
                        payload={"error": str(e), "exception_type": exc_type},
                    )
                )
            except Exception:
                pass

        # 发送错误事件
        try:
            yield StreamEventBuilder.build_error(
                message=error_msg,
                error_type=exc_type,
                run_id=self.run_id,
            )
            yield StreamEventBuilder.build_done(
                final_text="",
                stats={},
                passed=False,
                iterations=1,
                revision_count=0,
                generation_run_id=self.run_id,
            )
        except Exception:
            pass

        if is_cancelled:
            return  # 异步生成器可使用 return 提前终止

    async def _cleanup(self) -> None:
        """清理资源"""
        if self.prompt_logger and not getattr(self.prompt_logger, '_finalized', False):
            try:
                self.prompt_logger.finalize(
                    final_text_length=getattr(self.prompt_logger, '_final_text_length', 0),
                    total_iterations=getattr(self.prompt_logger, '_total_iterations', 1),
                    review_passed=getattr(self.prompt_logger, '_review_passed', False),
                )
                self.prompt_logger._finalized = True
            except Exception as finalize_e:
                svc_logger.error(
                    "[Generation] 阶段=FINALIZE 状态=ERROR 原因=日志终结失败",
                    error=str(finalize_e),
                )

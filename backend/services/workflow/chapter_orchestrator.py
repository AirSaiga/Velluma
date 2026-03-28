# Velluma - AI Novel Writing Assistant
# 章节生成工作流编排器

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable, AsyncGenerator
from pydantic import BaseModel, Field
from datetime import datetime
import asyncio
import logging

from backend.config import GenerationConfig, DerivationEngine, ConfigValidator
from backend.services.validation.pre_generation_checklist import (
    PreGenerationChecklist,
    PreGenerationReport,
    CheckSeverity,
)
from backend.services.validation.review_repair import (
    ReviewRepairCycle,
    ReviewReport,
    RepairStrategy,
)
from backend.services.state_machine.character_state import (
    CharacterStateMachine,
    CharacterStaticPortrait,
    CharacterDynamicState,
    StateChangeType,
)
from backend.services.state_machine.relationship_state import (
    RelationshipStateMachine,
    RelationshipState,
    RelationshipChangeType,
)

logger = logging.getLogger(__name__)


# =============================================================================
# 工作流阶段定义
# =============================================================================

class WorkflowStage(str, Enum):
    """工作流阶段"""
    IDLE = "IDLE"
    ASSEMBLING_CONTEXT = "ASSEMBLING_CONTEXT"
    PRE_CHECK = "PRE_CHECK"
    PLANNING = "PLANNING"
    POV_ASSIGNMENT = "POV_ASSIGNMENT"
    DRAFTING = "DRAFTING"
    SKETCH_GENERATION = "SKETCH_GENERATION"
    STITCHING = "STITCHING"
    ADVERSARIAL_ALIGNMENT = "ADVERSARIAL_ALIGNMENT"
    REVIEWING = "REVIEWING"
    REFINING = "REFINING"
    STITCHING_AFTER_REFINE = "STITCHING_AFTER_REFINE"
    POST_CHECK = "POST_CHECK"
    STATE_PERSISTENCE = "STATE_PERSISTENCE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class WorkflowState(BaseModel):
    """工作流状态"""
    current_stage: WorkflowStage = WorkflowStage.IDLE
    iteration: int = 0
    max_iterations: int = 2
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    
    # 各阶段结果
    pre_check_passed: bool = False
    beats: List[Dict] = Field(default_factory=list)
    beat_drafts: List[Dict] = Field(default_factory=list)
    sketch_result: Optional[Dict] = None
    stitched_text: str = ""
    alignment_score: float = 0.0
    review_report: Optional[Dict] = None
    final_text: str = ""
    
    # 错误信息
    error_message: str = ""
    error_stage: Optional[str] = None
    
    # 统计信息
    llm_calls: int = 0
    total_tokens: int = 0


# =============================================================================
# 工作流结果
# =============================================================================

class WorkflowResult(BaseModel):
    """工作流执行结果"""
    success: bool
    final_text: str = ""
    word_count: int = 0
    
    # 状态变化
    character_state_changes: List[Dict] = Field(default_factory=list)
    relationship_state_changes: List[Dict] = Field(default_factory=list)
    
    # 报告
    pre_check_report: Optional[Dict] = None
    review_report: Optional[Dict] = None
    
    # 统计
    iterations: int = 0
    llm_calls: int = 0
    
    # 错误
    error: str = ""


# =============================================================================
# 章节生成工作流编排器
# =============================================================================

class ChapterGenerationOrchestrator:
    """
    章节生成工作流编排器
    
    职责：
    - 编排章节生成的完整流程
    - 协调生成前检查、生成、审阅、修复
    - 管理状态机的读取与写回
    - 处理失败重试与 fail-fast
    
    工作流阶段：
    1. ASSEMBLING_CONTEXT - 组装上下文
    2. PRE_CHECK - 生成前检查
    3. PLANNING - 规划节拍
    4. POV_ASSIGNMENT - 视角分配
    5. DRAFTING - 起草正文
    6. SKETCH_GENERATION - 短文生成（双轨）
    7. STITCHING - 统稿
    8. ADVERSARIAL_ALIGNMENT - 对抗校对
    9. REVIEWING - 审阅
    10. REFINING - 精修（如需）
    11. STITCHING_AFTER_REFINE - 精修后统稿
    12. POST_CHECK - 生成后检查
    13. STATE_PERSISTENCE - 状态持久化
    14. COMPLETED - 完成
    
    设计原则：
    - 生成一次 + 审修循环（PLANNING/DRAFTING/STITCHING 只执行一次）
    - 生成前检查阻断致命错误
    - 审阅-修复闭环减少整章重写
    """
    
    def __init__(
        self,
        config: GenerationConfig,
        llm_client: Callable,
        db_session: Any = None,
    ):
        self.config = config
        self.llm_client = llm_client
        self.db_session = db_session
        self.state = WorkflowState()
        
        # 状态机
        self.character_machines: Dict[str, CharacterStateMachine] = {}
        self.relationship_machines: Dict[Tuple[str, str], RelationshipStateMachine] = {}
        
        # 回调
        self._progress_callback: Optional[Callable] = None
        self._log_callback: Optional[Callable] = None
    
    def set_progress_callback(self, callback: Callable) -> None:
        """设置进度回调"""
        self._progress_callback = callback
    
    def set_log_callback(self, callback: Callable) -> None:
        """设置日志回调"""
        self._log_callback = callback
    
    async def _emit_progress(
        self,
        stage: WorkflowStage,
        message: str,
        **kwargs,
    ) -> None:
        """发送进度事件"""
        if self._progress_callback:
            await self._progress_callback(stage.value, message, **kwargs)
    
    def _log(self, message: str, level: str = "info") -> None:
        """记录日志"""
        if self._log_callback:
            self._log_callback(message, level)
        
        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)
    
    async def execute(
        self,
        context: Dict[str, Any],
    ) -> WorkflowResult:
        """
        执行完整工作流
        
        Args:
            context: 生成上下文，包含：
                - chapter: Chapter 实体
                - book: Book 实体
                - entities: 出场角色列表
                - relationships: 关系列表
                - open_hooks: 开放伏笔
                - previous_summary: 上一章摘要
                - previous_world_snapshot: 世界快照
                - relevant_memories: RAG 检索结果
                - locations: 地点列表
        
        Returns:
            WorkflowResult: 工作流结果
        """
        result = WorkflowResult(success=False)
        self.state = WorkflowState(
            max_iterations=self.config.workflow.max_iterations,
            start_time=datetime.now().isoformat(),
        )
        
        try:
            # ================================================================
            # Phase 1: ASSEMBLING_CONTEXT - 组装上下文
            # ================================================================
            self.state.current_stage = WorkflowStage.ASSEMBLING_CONTEXT
            await self._emit_progress(
                WorkflowStage.ASSEMBLING_CONTEXT,
                "正在组装章节上下文..."
            )
            
            # 构建状态机
            await self._build_state_machines(context)
            
            # ================================================================
            # Phase 2: PRE_CHECK - 生成前检查
            # ================================================================
            self.state.current_stage = WorkflowStage.PRE_CHECK
            await self._emit_progress(
                WorkflowStage.PRE_CHECK,
                "正在执行生成前检查..."
            )
            
            checklist = PreGenerationChecklist()
            pre_check_report = checklist.run_all_checks(context)
            result.pre_check_report = pre_check_report.model_dump()
            
            if not pre_check_report.can_proceed():
                self.state.error_message = f"生成前检查失败: {pre_check_report.blocking_issues}"
                self.state.current_stage = WorkflowStage.FAILED
                result.error = self.state.error_message
                return result
            
            self.state.pre_check_passed = True
            self._log(f"生成前检查通过，{pre_check_report.warning_count} 个警告")
            
            # ================================================================
            # Phase 3: PLANNING - 规划节拍（仅执行一次）
            # ================================================================
            self.state.current_stage = WorkflowStage.PLANNING
            await self._emit_progress(
                WorkflowStage.PLANNING,
                "正在规划故事节拍..."
            )
            
            beats = await self._execute_planning(context)
            self.state.beats = beats
            
            if not beats:
                self.state.error_message = "规划阶段未能生成有效节拍"
                self.state.current_stage = WorkflowStage.FAILED
                result.error = self.state.error_message
                return result
            
            self._log(f"规划完成，生成 {len(beats)} 个节拍")
            
            # ================================================================
            # Phase 4: POV_ASSIGNMENT - 视角分配
            # ================================================================
            self.state.current_stage = WorkflowStage.POV_ASSIGNMENT
            await self._emit_progress(
                WorkflowStage.POV_ASSIGNMENT,
                "正在分配叙事视角..."
            )
            
            beats = await self._execute_pov_assignment(context, beats)
            self.state.beats = beats
            
            # ================================================================
            # Phase 5-8: 生成阶段（双轨模式）
            # ================================================================
            self.state.current_stage = WorkflowStage.DRAFTING
            await self._emit_progress(
                WorkflowStage.DRAFTING,
                "正在起草章节正文..."
            )
            
            # 执行双轨生成
            draft_result = await self._execute_dual_track_generation(
                context, beats
            )
            
            self.state.beat_drafts = draft_result.get("beat_drafts", [])
            self.state.sketch_result = draft_result.get("sketch_result")
            self.state.stitched_text = draft_result.get("stitched_text", "")
            self.state.alignment_score = draft_result.get("alignment_score", 0)
            
            self.state.llm_calls += draft_result.get("llm_calls", 0)
            
            # ================================================================
            # 审阅-修复循环
            # ================================================================
            current_text = self.state.stitched_text
            
            while self.state.iteration < self.state.max_iterations:
                self.state.iteration += 1
                
                # ============================================================
                # Phase 9: REVIEWING - 审阅
                # ============================================================
                self.state.current_stage = WorkflowStage.REVIEWING
                await self._emit_progress(
                    WorkflowStage.REVIEWING,
                    f"正在审阅（第 {self.state.iteration} 轮）..."
                )
                
                review_report = await self._execute_reviewing(
                    current_text, context
                )
                self.state.review_report = review_report
                
                # 检查是否通过
                if review_report.get("passed", False):
                    self._log(f"审阅通过，得分: {review_report.get('overall_score', 0):.1f}")
                    break
                
                # 检查是否需要整章重写
                strategy = RepairStrategy(
                    review_report.get("repair_recommendation", "local_repair")
                )
                
                if strategy == RepairStrategy.FULL_CHAPTER_REWRITE:
                    self._log("审阅建议整章重写，终止修复循环", "warning")
                    break
                
                # ============================================================
                # Phase 10: REFINING - 精修
                # ============================================================
                self.state.current_stage = WorkflowStage.REFINING
                await self._emit_progress(
                    WorkflowStage.REFINING,
                    f"正在精修（第 {self.state.iteration} 轮）..."
                )
                
                refined_text = await self._execute_refining(
                    current_text, review_report, context
                )
                
                if refined_text:
                    current_text = refined_text
                    
                    # Phase 11: STITCHING_AFTER_REFINE
                    self.state.current_stage = WorkflowStage.STITCHING_AFTER_REFINE
                    await self._emit_progress(
                        WorkflowStage.STITCHING_AFTER_REFINE,
                        "正在统稿精修内容..."
                    )
                    
                    # 精修后的统稿处理
                    current_text = await self._execute_post_refine_stitch(
                        current_text, context
                    )
            
            self.state.final_text = current_text
            
            # ================================================================
            # Phase 12: POST_CHECK - 生成后检查
            # ================================================================
            self.state.current_stage = WorkflowStage.POST_CHECK
            await self._emit_progress(
                WorkflowStage.POST_CHECK,
                "正在执行生成后检查..."
            )
            
            post_check_result = await self._execute_post_check(
                current_text, context
            )
            
            # ================================================================
            # Phase 13: STATE_PERSISTENCE - 状态持久化
            # ================================================================
            self.state.current_stage = WorkflowStage.STATE_PERSISTENCE
            await self._emit_progress(
                WorkflowStage.STATE_PERSISTENCE,
                "正在保存状态变化..."
            )
            
            state_changes = await self._persist_state_changes(context)
            result.character_state_changes = state_changes.get("characters", [])
            result.relationship_state_changes = state_changes.get("relationships", [])
            
            # ================================================================
            # Phase 14: COMPLETED - 完成
            # ================================================================
            self.state.current_stage = WorkflowStage.COMPLETED
            self.state.end_time = datetime.now().isoformat()
            
            result.success = True
            result.final_text = self.state.final_text
            result.word_count = len(self.state.final_text)
            result.iterations = self.state.iteration
            result.llm_calls = self.state.llm_calls
            result.review_report = self.state.review_report
            
            await self._emit_progress(
                WorkflowStage.COMPLETED,
                f"生成完成，共 {result.word_count} 字"
            )
            
            return result
            
        except Exception as e:
            self.state.current_stage = WorkflowStage.FAILED
            self.state.error_message = str(e)
            result.error = str(e)
            self._log(f"工作流执行失败: {e}", "error")
            return result
    
    # =========================================================================
    # 阶段实现方法
    # =========================================================================
    
    async def _build_state_machines(self, context: Dict[str, Any]) -> None:
        """构建角色和关系状态机"""
        entities = context.get("entities", [])
        relationships = context.get("relationships", [])
        
        # 构建角色状态机
        for entity in entities:
            character = getattr(entity, "character", None)
            if not character:
                continue
            
            char_id = str(getattr(character, "id", ""))
            if not char_id:
                continue
            
            # 创建静态画像
            static_portrait = CharacterStaticPortrait(
                name=getattr(character, "name", "未知"),
                aliases=getattr(character, "aliases", []) or [],
                appearance=self._extract_section(
                    getattr(character, "static_prompt", "") or "",
                    "外貌"
                ),
                personality=self._extract_section(
                    getattr(character, "static_prompt", "") or "",
                    "性格"
                ),
            )
            
            # 创建动态状态
            dynamic_state = CharacterDynamicState()
            
            self.character_machines[char_id] = CharacterStateMachine(
                static_portrait, dynamic_state
            )
        
        # 构建关系状态机
        for rel in relationships:
            source_char = getattr(rel, "source_character", None)
            target_char = getattr(rel, "target_character", None)
            
            if not source_char or not target_char:
                continue
            
            source_name = getattr(source_char, "name", "")
            target_name = getattr(target_char, "name", "")
            
            state = RelationshipState(
                source_char_name=source_name,
                target_char_name=target_name,
                relation_type=getattr(rel, "relation_type", "acquaintance") or "acquaintance",
            )
            state.metrics.affinity = getattr(rel, "affinity_score", 0) or 0
            
            key = (source_name, target_name)
            self.relationship_machines[key] = RelationshipStateMachine(state)
        
        self._log(
            f"构建状态机: {len(self.character_machines)} 角色, "
            f"{len(self.relationship_machines)} 关系"
        )
    
    def _extract_section(self, text: str, section_name: str) -> str:
        """提取文本段落"""
        import re
        pattern = rf"【{section_name}】(.+?)(?=【|$)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
    
    async def _execute_planning(self, context: Dict[str, Any]) -> List[Dict]:
        """执行规划阶段"""
        # 调用实际的规划逻辑
        # 这里简化实现，实际应调用 agentic_workflow 或 planning 模块
        chapter = context.get("chapter")
        book = context.get("book")
        
        if not chapter:
            return []
        
        # 返回简化节拍
        outline = getattr(chapter, "outline_text", "") or ""
        word_count = self.config.chapter.target_word_count
        
        # 简化：将大纲拆分为 3-5 个节拍
        beats = []
        sections = outline.split("。")
        beat_count = min(5, max(3, len(sections)))
        words_per_beat = word_count // beat_count
        
        for i, section in enumerate(sections[:beat_count]):
            if section.strip():
                beats.append({
                    "position": i + 1,
                    "beat_id": f"beat-{i+1}",
                    "summary": section.strip()[:100],
                    "target_words": words_per_beat,
                    "pov_character": None,
                })
        
        return beats
    
    async def _execute_pov_assignment(
        self,
        context: Dict[str, Any],
        beats: List[Dict],
    ) -> List[Dict]:
        """执行视角分配"""
        entities = context.get("entities", [])
        
        # 获取主角候选
        protagonists = []
        for entity in entities:
            character = getattr(entity, "character", None)
            if character:
                importance = getattr(character, "importance_level", 1) or 1
                if importance >= 8:
                    protagonists.append(getattr(character, "name", ""))
        
        # 分配 POV
        anchor_pov = protagonists[0] if protagonists else None
        
        for beat in beats:
            if not beat.get("pov_character"):
                beat["pov_character"] = anchor_pov
        
        return beats
    
    async def _execute_dual_track_generation(
        self,
        context: Dict[str, Any],
        beats: List[Dict],
    ) -> Dict[str, Any]:
        """执行双轨生成"""
        # 简化实现
        # 实际应调用 DualTrackWorkflow
        
        word_count = self.config.chapter.target_word_count
        text_per_beat = word_count // max(1, len(beats))
        
        beat_drafts = []
        for beat in beats:
            # 简化：生成占位文本
            beat_drafts.append({
                "beat_id": beat.get("beat_id"),
                "text": f"[{beat.get('summary', '')}...] " * (text_per_beat // 20),
                "word_count": text_per_beat,
            })
        
        # 统稿
        stitched_text = " ".join(d.get("text", "") for d in beat_drafts)
        
        return {
            "beat_drafts": beat_drafts,
            "sketch_result": None,
            "stitched_text": stitched_text,
            "alignment_score": 85.0,
            "llm_calls": len(beats) + 2,
        }
    
    async def _execute_reviewing(
        self,
        text: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行审阅"""
        # 构建审阅上下文
        characters = []
        for entity in context.get("entities", []):
            char = getattr(entity, "character", None)
            if char:
                characters.append({
                    "name": getattr(char, "name", ""),
                    "dynamic_state": getattr(char, "dynamic_state", "") or "",
                })
        
        relationships = []
        for rel in context.get("relationships", []):
            source = getattr(rel, "source_character", None)
            target = getattr(rel, "target_character", None)
            if source and target:
                relationships.append({
                    "source_name": getattr(source, "name", ""),
                    "target_name": getattr(target, "name", ""),
                    "affinity_score": getattr(rel, "affinity_score", 0) or 0,
                })
        
        # 执行审阅
        cycle = ReviewRepairCycle(self.llm_client)
        _, report = await cycle.execute(
            chapter_text=text,
            chapter_outline=getattr(context.get("chapter"), "outline_text", "") or "",
            characters=characters,
            relationships=relationships,
            open_hooks=context.get("open_hooks", []),
            previous_summary=context.get("previous_summary"),
        )
        
        return report.model_dump()
    
    async def _execute_refining(
        self,
        text: str,
        review_report: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[str]:
        """执行精修"""
        # 简化实现
        # 实际应调用 refining 模块
        
        issues = review_report.get("issues", [])
        critical_issues = [
            i for i in issues
            if i.get("severity") in ["critical", "major"]
        ]
        
        if not critical_issues:
            return None
        
        # 返回修正后的文本（简化）
        return text
    
    async def _execute_post_refine_stitch(
        self,
        text: str,
        context: Dict[str, Any],
    ) -> str:
        """执行精修后统稿"""
        return text
    
    async def _execute_post_check(
        self,
        text: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行生成后检查"""
        return {
            "passed": True,
            "word_count": len(text),
        }
    
    async def _persist_state_changes(
        self,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """持久化状态变化"""
        changes = {
            "characters": [],
            "relationships": [],
        }
        
        # 收集角色状态变化
        for char_id, machine in self.character_machines.items():
            if machine._history:
                latest = machine._history[-1]
                changes["characters"].append({
                    "character_id": char_id,
                    "change_type": latest.change_type.value,
                    "reason": latest.change_reason,
                })
        
        # 收集关系状态变化
        for key, machine in self.relationship_machines.items():
            if machine._history:
                latest = machine._history[-1]
                changes["relationships"].append({
                    "source_name": key[0],
                    "target_name": key[1],
                    "change_type": latest.get("change_type", "unknown"),
                    "reason": latest.get("change_reason", ""),
                })
        
        return changes


# =============================================================================
# 便捷函数
# =============================================================================

async def generate_chapter_with_workflow(
    config: GenerationConfig,
    context: Dict[str, Any],
    llm_client: Callable,
    progress_callback: Optional[Callable] = None,
) -> WorkflowResult:
    """
    便捷函数：使用工作流生成章节
    
    Args:
        config: 生成配置
        context: 生成上下文
        llm_client: LLM 客户端
        progress_callback: 进度回调
    
    Returns:
        WorkflowResult: 生成结果
    """
    orchestrator = ChapterGenerationOrchestrator(config, llm_client)
    
    if progress_callback:
        orchestrator.set_progress_callback(progress_callback)
    
    return await orchestrator.execute(context)
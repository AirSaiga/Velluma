"""
对抗校对器 (Adversarial Aligner) - 双轨架构核心组件。

职责：
- 对比节拍统稿 (Draft A) 和连贯速写 (Sketch)
- 检测结构差异、情绪差异和信息差异
- 生成修复方案指导精修

核心流程：
1. 结构对齐检测 - 检查节拍边界是否匹配
2. 情绪曲线对比 - 对比两者的情感走向
3. 转折点对齐 - 验证关键转折位置
4. 生成调整计划 - 输出具体的修复建议

依赖项：
- backend.services.llm: LLM 调用接口
- backend.services.workflows.sketch_generator: Sketch 生成结果

使用方式：
    from backend.services.workflows.dual_track.alignment import AdversarialAligner

    aligner = AdversarialAligner(api_key, base_url, model, config)
    plan = await aligner.align(draft_text, sketch_result, beats, ...)
"""

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from pydantic import BaseModel

from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.services.workflows.sketch_generator import SketchResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GapType(str, Enum):
    """差异类型"""
    STRUCTURAL = "structural"  # 结构差异
    EMOTIONAL = "emotional"    # 情绪差异
    INFORMATION = "information"  # 信息差异
    TRANSITION = "transition"  # 过渡差异
    OPENING = "opening"        # 开头差异
    ENDING = "ending"          # 结尾差异


class GapSource(str, Enum):
    """问题根源"""
    BEAT_DESIGN = "beat_design"           # 节拍设计问题
    EXPANSION_DRIFT = "expansion_drift"   # 扩写偏离
    SEGMENT_BOUNDARY = "segment_boundary"  # 段落边界问题
    SKETCH_HALLUCINATION = "sketch_hallucination"  # 速写幻觉
    UNKNOWN = "unknown"                    # 未知原因


class GapSeverity(str, Enum):
    """严重程度"""
    HIGH = "high"     # 高 - 必须修复
    MEDIUM = "medium" # 中 - 建议修复
    LOW = "low"       # 低 - 可选修复


@dataclass
class AlignmentGap:
    """
    对齐差异项。

    描述 Draft 和 Sketch 之间的具体差异。

    字段说明：
    - gap_type: 差异类型（结构/情绪/信息等）
    - severity: 严重程度
    - beat_index: 涉及的节拍索引（1-based）
    - description: 差异描述
    - draft_value: Draft 中的值
    - sketch_value: Sketch 中的值
    - source: 问题根源
    - fix_suggestion: 修复建议
    """
    gap_type: GapType
    severity: GapSeverity
    beat_index: Optional[int]
    beat_id: Optional[str]
    description: str
    draft_value: str
    sketch_value: str
    source: GapSource
    fix_suggestion: str
    position_percent: Optional[float] = None


@dataclass
class AdjustmentPlan:
    """
    修复计划。

    包含对抗校对的完整结果和修复指导。

    字段说明：
    - alignment_score: 对齐分数 (0-100)
    - needs_adjustment: 是否需要调整
    - gaps: 差异列表
    - beat_adjustments: 按节拍的调整计划
    - global_adjustments: 全局调整建议
    - analysis_prompts: 调试信息 - 分析时的 prompt 历史
    """
    alignment_score: float
    needs_adjustment: bool
    gaps: List[AlignmentGap]
    beat_adjustments: Dict[int, List[str]]
    global_adjustments: List[str]
    analysis_prompts: List[dict] = field(default_factory=list)


@dataclass
class AdversarialAlignerConfig:
    """对抗校对器配置"""
    # 结构偏移阈值（百分比）
    structural_offset_threshold: float = 15.0

    # 情绪差异阈值
    emotion_diff_threshold: float = 2.0

    # 可接受的最低分数
    min_acceptable_score: float = 70.0

    # LLM 温度
    temperature: float = 0.1

    # 最大分析 token 数
    max_analysis_tokens: int = 2000


class AdversarialAligner:
    """
    对抗校对器。

    职责：
    - 对比 Draft 和 Sketch 的差异
    - 生成结构化的调整计划

    设计决策：
    - 使用 LLM 进行语义级别的差异分析
    - 支持按节拍粒度的调整
    - 提供全局和局部两种修复模式
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        config: Optional[AdversarialAlignerConfig] = None,
    ):
        """
        初始化对抗校对器。

        Args:
            api_key: API 密钥
            base_url: API 端点
            model: 分析用模型
            config: 配置对象
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.config = config or AdversarialAlignerConfig()

    async def align(
        self,
        draft_text: str,
        sketch_result: SketchResult,
        beats: List[dict],
        chapter: Any,
        book: Any,
    ) -> AdjustmentPlan:
        """
        执行对抗校对。

        职责：分析 Draft 和 Sketch 的差异，生成调整计划。

        Args:
            draft_text: 统稿后的草稿文本
            sketch_result: Sketch 生成结果
            beats: 节拍列表
            chapter: 章节对象
            book: 书籍对象

        Returns:
            AdjustmentPlan: 调整计划

        处理流程：
        1. 调用 LLM 进行结构差异分析
        2. 调用 LLM 进行情绪曲线对比
        3. 综合分析结果，计算对齐分数
        4. 生成按节拍的调整计划
        """
        logger.info(
            f"[AdversarialAligner] 开始对抗校对，"
            f"Draft={len(draft_text)}字, Sketch={sketch_result.word_count}字"
        )

        gaps: List[AlignmentGap] = []
        analysis_prompts = []

        # Step 1: 结构对齐检测
        structural_result = await self._analyze_structural_alignment(
            draft_text=draft_text,
            sketch_result=sketch_result,
            beats=beats,
        )
        gaps.extend(structural_result.gaps)
        analysis_prompts.extend(structural_result.prompts)

        # Step 2: 情绪曲线对比
        emotion_result = await self._analyze_emotion_alignment(
            draft_text=draft_text,
            sketch_result=sketch_result,
        )
        gaps.extend(emotion_result.gaps)
        analysis_prompts.extend(emotion_result.prompts)

        # Step 3: 计算综合分数
        alignment_score = self._calculate_alignment_score(gaps)
        needs_adjustment = alignment_score < self.config.min_acceptable_score

        # Step 4: 生成调整计划
        beat_adjustments, global_adjustments = self._build_adjustment_plan(
            gaps=gaps,
            alignment_score=alignment_score,
        )

        logger.info(
            f"[AdversarialAligner] 对齐分析完成，"
            f"score={alignment_score:.1f}, needs_adjustment={needs_adjustment}, "
            f"gaps={len(gaps)}"
        )

        return AdjustmentPlan(
            alignment_score=alignment_score,
            needs_adjustment=needs_adjustment,
            gaps=gaps,
            beat_adjustments=beat_adjustments,
            global_adjustments=global_adjustments,
            analysis_prompts=analysis_prompts,
        )

    async def _analyze_structural_alignment(
        self,
        draft_text: str,
        sketch_result: SketchResult,
        beats: List[dict],
    ) -> "AnalysisResult":
        """
        分析结构对齐。

        检测 Draft 和 Sketch 在以下方面的差异：
        - 节拍边界位置
        - 转折点分布
        - 段落长度比例
        """
        prompts_history = []

        system_prompt = """你是一个专业的文学编辑，擅长分析小说文本的结构特征。

请分析以下两段文本的结构差异：
1. Draft A：基于节拍扩写的文本
2. Sketch：连贯叙述的参考文本

输出 JSON 格式：
{
    "gaps": [
        {
            "type": "structural|transition|emotional",
            "severity": "high|medium|low",
            "beat_index": 1,
            "beat_id": "xxx",
            "description": "差异描述",
            "draft_value": "Draft中的描述",
            "sketch_value": "Sketch中的描述",
            "source": "beat_design|expansion_drift|segment_boundary|unknown",
            "fix_suggestion": "修复建议"
        }
    ],
    "summary": "总体评估"
}"""

        user_prompt = f"""分析以下两段文本的结构差异：

【Draft A】(约 {len(draft_text)} 字):
{draft_text[:3000]}...

【Sketch】(约 {sketch_result.word_count} 字):
{sketch_result.sketch_text[:3000]}...

【节拍信息】:
{json.dumps(beats[:5], ensure_ascii=False)}"""

        prompts_history.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "stage": "STRUCTURAL_ALIGNMENT",
        })

        try:
            response = await call_llm(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_analysis_tokens,
            )

            parsed = json.loads(clean_llm_output(response))
            gaps = [
                AlignmentGap(
                    gap_type=GapType(g.get("type", "unknown")),
                    severity=GapSeverity(g.get("severity", "medium")),
                    beat_index=g.get("beat_index"),
                    beat_id=g.get("beat_id"),
                    description=g.get("description", ""),
                    draft_value=g.get("draft_value", ""),
                    sketch_value=g.get("sketch_value", ""),
                    source=GapSource(g.get("source", "unknown")),
                    fix_suggestion=g.get("fix_suggestion", ""),
                )
                for g in parsed.get("gaps", [])
            ]

            return AnalysisResult(gaps=gaps, prompts=prompts_history)

        except Exception as e:
            logger.warning(f"[AdversarialAligner] 结构分析失败: {e}")
            return AnalysisResult(gaps=[], prompts=prompts_history)

    async def _analyze_emotion_alignment(
        self,
        draft_text: str,
        sketch_result: SketchResult,
    ) -> "AnalysisResult":
        """
        分析情绪对齐。

        对比 Draft 和 Sketch 的情绪曲线。
        """
        prompts_history = []

        # 如果 Sketch 没有情绪数据，跳过分析
        if not sketch_result.emotion_arc:
            return AnalysisResult(gaps=[], prompts=prompts_history)

        system_prompt = """分析以下两段文本的情绪走向差异。

输出 JSON 格式：
{
    "gaps": [
        {
            "type": "emotional",
            "severity": "high|medium|low",
            "beat_index": 1,
            "description": "情绪差异描述",
            "draft_emotion": "Draft中的情绪",
            "sketch_emotion": "Sketch中的情绪",
            "source": "expansion_drift|beat_design|unknown",
            "fix_suggestion": "修复建议"
        }
    ]
}"""

        user_prompt = f"""【Draft A】:
{draft_text[:2000]}...

【Sketch 情绪曲线】:
{json.dumps(sketch_result.emotion_arc, ensure_ascii=False)}"""

        prompts_history.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "stage": "EMOTION_ALIGNMENT",
        })

        try:
            response = await call_llm(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_analysis_tokens,
            )

            parsed = json.loads(clean_llm_output(response))
            gaps = [
                AlignmentGap(
                    gap_type=GapType.EMOTIONAL,
                    severity=GapSeverity(g.get("severity", "medium")),
                    beat_index=g.get("beat_index"),
                    beat_id=None,
                    description=g.get("description", ""),
                    draft_value=g.get("draft_emotion", ""),
                    sketch_value=g.get("sketch_emotion", ""),
                    source=GapSource(g.get("source", "unknown")),
                    fix_suggestion=g.get("fix_suggestion", ""),
                )
                for g in parsed.get("gaps", [])
            ]

            return AnalysisResult(gaps=gaps, prompts=prompts_history)

        except Exception as e:
            logger.warning(f"[AdversarialAligner] 情绪分析失败: {e}")
            return AnalysisResult(gaps=[], prompts=prompts_history)

    def _calculate_alignment_score(self, gaps: List[AlignmentGap]) -> float:
        """
        计算对齐分数。

        基于差异的严重程度计算：
        - HIGH: -20分
        - MEDIUM: -10分
        - LOW: -5分

        初始分数为 100，最低为 0。
        """
        if not gaps:
            return 100.0

        deductions = {
            GapSeverity.HIGH: 20.0,
            GapSeverity.MEDIUM: 10.0,
            GapSeverity.LOW: 5.0,
        }

        total_deduction = sum(deductions.get(g.severity, 10.0) for g in gaps)
        return max(0.0, 100.0 - total_deduction)

    def _build_adjustment_plan(
        self,
        gaps: List[AlignmentGap],
        alignment_score: float,
    ) -> tuple[Dict[int, List[str]], List[str]]:
        """
        构建调整计划。

        Args:
            gaps: 差异列表
            alignment_score: 对齐分数

        Returns:
            Tuple[Dict[int, List[str]], List[str]]:
            - beat_adjustments: 按节拍的调整计划
            - global_adjustments: 全局调整建议
        """
        beat_adjustments: Dict[int, List[str]] = {}
        global_adjustments: List[str] = []

        for gap in gaps:
            if gap.beat_index:
                if gap.beat_index not in beat_adjustments:
                    beat_adjustments[gap.beat_index] = []
                beat_adjustments[gap.beat_index].append(gap.fix_suggestion)
            else:
                global_adjustments.append(gap.fix_suggestion)

        return beat_adjustments, global_adjustments


# 内部辅助类
@dataclass
class AnalysisResult:
    """分析结果"""
    gaps: List[AlignmentGap]
    prompts: List[dict]

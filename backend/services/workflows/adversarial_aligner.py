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
对抗校对器 (Adversarial Aligner) - 双轨架构核心组件

职责：对比节拍统稿 (Draft A) 和连贯速写 (Sketch)，检测差异并生成修复方案。
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pydantic import BaseModel

from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.services.workflows.sketch_generator import SketchResult

logger = logging.getLogger(__name__)


class GapType(str, Enum):
    """差异类型"""
    STRUCTURAL = "structural"
    EMOTIONAL = "emotional"
    INFORMATION = "information"
    TRANSITION = "transition"
    OPENING = "opening"
    ENDING = "ending"


class GapSource(str, Enum):
    """问题根源"""
    BEAT_DESIGN = "beat_design"
    EXPANSION_DRIFT = "expansion_drift"
    SEGMENT_BOUNDARY = "segment_boundary"
    SKETCH_HALLUCINATION = "sketch_hallucination"
    UNKNOWN = "unknown"


class GapSeverity(str, Enum):
    """严重程度"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AlignmentGap:
    """对齐差异项"""
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
    """修复计划"""
    alignment_score: float
    needs_adjustment: bool
    gaps: List[AlignmentGap]
    beat_adjustments: Dict[int, List[str]]
    global_adjustments: List[str]
    analysis_prompts: List[dict] = field(default_factory=list)


@dataclass
class AdversarialAlignerConfig:
    """对抗校对器配置"""
    structural_offset_threshold: float = 15.0
    emotion_diff_threshold: float = 2.0
    min_acceptable_score: float = 70.0
    temperature: float = 0.1
    max_analysis_tokens: int = 2000


class AdversarialAligner:
    """对抗校对器"""
    
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        config: Optional[AdversarialAlignerConfig] = None,
    ):
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
        """执行对抗校对"""
        logger.info(f"[AdversarialAligner] 开始对抗校对，Draft 字数: {len(draft_text)}，Sketch 字数: {sketch_result.word_count}")
        
        gaps: List[AlignmentGap] = []
        prompts_history = []
        
        # Step 1: 结构对齐检测
        structural_gaps = self._detect_structural_gaps(draft_text, sketch_result, beats)
        gaps.extend(structural_gaps)
        
        # Step 2: 情绪对齐检测
        emotional_gaps = await self._detect_emotional_gaps(draft_text, sketch_result, beats)
        gaps.extend(emotional_gaps)
        
        # Step 3: 信息对齐检测
        info_gaps, info_prompts = await self._detect_information_gaps(
            draft_text, sketch_result.sketch_text, beats, chapter, book
        )
        gaps.extend(info_gaps)
        prompts_history.extend(info_prompts)
        
        # Step 4: 开头结尾检测
        boundary_gaps = await self._detect_boundary_gaps(draft_text, sketch_result.sketch_text, beats)
        gaps.extend(boundary_gaps)
        
        # Step 5: 归因分析
        gaps = self._attribute_gaps(gaps, beats)
        
        # Step 6: 生成修复方案
        beat_adjustments, global_adjustments = self._generate_adjustments(gaps, beats)
        
        # Step 7: 计算得分
        alignment_score = self._calculate_alignment_score(gaps)
        needs_adjustment = alignment_score < self.config.min_acceptable_score
        
        logger.info(f"[AdversarialAligner] 校对完成，对齐度得分: {alignment_score:.1f}，发现 {len(gaps)} 个差异")
        
        return AdjustmentPlan(
            alignment_score=alignment_score,
            needs_adjustment=needs_adjustment,
            gaps=gaps,
            beat_adjustments=beat_adjustments,
            global_adjustments=global_adjustments,
            analysis_prompts=prompts_history,
        )
    
    def _detect_structural_gaps(self, draft_text: str, sketch_result: SketchResult, beats: List[dict]) -> List[AlignmentGap]:
        """
        检测结构差异。
        
        原有逻辑以 Sketch 自报告的节拍位置为"标准"来评判 Draft，
        但 Sketch 的位置信息只是 Sketch 自身的分布，无法作为 Draft 的质量标准。
        因此此方法返回空列表，结构问题通过 LLM 质量比较步骤处理。
        """
        return []
    
    async def _detect_emotional_gaps(self, draft_text: str, sketch_result: SketchResult, beats: List[dict]) -> List[AlignmentGap]:
        """
        检测情绪参考信息。
        
        Sketch 的 emotion_arc 是 Sketch 自身的情绪弧度，不能作为 Draft 情绪的质量标准。
        此方法仅作为 LOW 级别的参考信息，不触发融合精修。
        实际质量判断由 _detect_information_gaps 的 LLM 质量比较步骤负责。
        """
        gaps = []
        emotion_arc = sketch_result.emotion_arc
        
        if not emotion_arc or len(emotion_arc) < 2 or not draft_text:
            return gaps
        
        # 仅记录极端情绪跳跃作为 LOW 级别参考（不触发精修）
        for i in range(len(emotion_arc) - 1):
            current = emotion_arc[i]
            next_point = emotion_arc[i + 1]
            current_intensity = current.get("intensity", 5)
            next_intensity = next_point.get("intensity", 5)
            intensity_diff = abs(next_intensity - current_intensity)
            
            # 仅报告极端跳跃（> 5），且只作为 LOW 级参考
            if intensity_diff > 5:
                position = current.get("position", "")
                beat_index = self._estimate_beat_from_position(position, len(beats))
                gaps.append(AlignmentGap(
                    gap_type=GapType.EMOTIONAL,
                    severity=GapSeverity.LOW,  # 始终为 LOW，不触发精修
                    beat_index=beat_index,
                    beat_id=beats[beat_index - 1].get("beat_id") if beat_index and beat_index <= len(beats) else None,
                    description=f"[参考] Sketch 情绪弧度在 {position} 处有较大跳跃（{current.get('emotion', '?')} → {next_point.get('emotion', '?')}，差值 {intensity_diff}）",
                    draft_value="Draft 此处情绪过渡是否自然，需人工判断",
                    sketch_value=f"Sketch 情绪强度变化: {intensity_diff}",
                    source=GapSource.UNKNOWN,
                    fix_suggestion=f"可参考 Sketch 在 {position} 附近的情绪过渡方式",
                ))
        
        return gaps
    
    def _estimate_beat_from_position(self, position: str, total_beats: int) -> Optional[int]:
        """
        根据位置描述估算 beat 索引
        
        position 可能是：开头、中段、结尾、1/3处 等
        """
        if not position or total_beats == 0:
            return None
        
        position_lower = position.lower()
        
        if "开头" in position_lower or "开始" in position_lower or "首" in position_lower:
            return 1
        elif "结尾" in position_lower or "末尾" in position_lower or "结束" in position_lower:
            return total_beats
        elif "中" in position_lower:
            return (total_beats + 1) // 2
        elif "1/3" in position_lower or "三分之一" in position_lower:
            return max(1, total_beats // 3)
        elif "2/3" in position_lower or "三分之二" in position_lower:
            return max(1, (total_beats * 2) // 3)
        
        return None
    
    async def _detect_information_gaps(
        self, draft_text: str, sketch_text: str, beats: List[dict], chapter: Any, book: Any
    ) -> Tuple[List[AlignmentGap], List[dict]]:
        """
        质量比较分析。
        
        对比 Draft 和 Sketch 在各叙事节点的质量，判断哪个版本更优秀。
        只有当 Sketch 的处理明显优于 Draft 时才生成改进建议，
        而不是让 Draft 与 Sketch 对齐。
        """
        gaps = []
        prompts = []
        
        system_prompt = """你是一位资深文学编辑，专注于提升小说叙事质量。

任务：对比同一故事情节的两个版本（节拍统稿 Draft 和连贯速写 Sketch），在关键叙事节点处判断哪个版本更优秀。

评判标准：
- 逻辑合理性：人物行为动机是否清晰，情节发展是否自然
- 叙事流畅性：段落衔接是否顺滑，节奏是否恰当
- 信息揭示节奏：关键信息引入时机是否合适

重要原则：
- 目标是改进 Draft，而非让 Draft 模仿 Sketch
- 只有当 Sketch 的处理明显优于 Draft 时，才输出改进建议
- 如果 Draft 已处理得更好或两者质量相当，该节点不输出任何条目
- Sketch 可能存在细节错误（幻觉），遇到时应忽略该对比点

【必须且只能输出一个合法的 JSON 对象，不要输出任何其他内容，不要 markdown 代码块】

输出格式：
{
  "quality_comparisons": [
    {
      "narrative_point": "描述对比的叙事节点（简短）",
      "better_version": "sketch",
      "reason": "Sketch 更好的原因（具体指出 Draft 的弱点）",
      "draft_improvement": "Draft 应如何改进（借鉴 Sketch 哪个具体做法，不要说'参考Sketch'这种模糊指令）",
      "severity": "high 或 medium"
    }
  ]
}

注意：better_version 只能填 "sketch"，只输出 Draft 需要改进的条目。"""

        key_beats = [b for b in beats if self._is_key_beat(b)]
        # 当命中关键词的节拍太少时（少于3个或少于总数的一半），
        # 退化为使用全部节拍，保证 LLM 质量比较覆盖足够场景。
        min_required = min(3, len(beats))
        if len(key_beats) < min_required:
            key_beats = beats[:6]  # 最多取 6 个，避免 token 过长
        if len(key_beats) == 0:
            return gaps, prompts
        
        beats_summary = "\n".join([
            f"节拍 {b.get('position', i)}: {b.get('summary', '')}"
            for i, b in enumerate(key_beats, 1)
        ])
        
        user_prompt = f"""【节拍框架 - 叙事参考】
{beats_summary}

【版本 A：节拍统稿（Draft）】
{draft_text[:2000]}

【版本 B：连贯速写（Sketch）】
{sketch_text[:2000]}

请对比以上两个版本，找出 Draft 在哪些叙事节点处不如 Sketch，并给出具体改进建议。若 Draft 整体质量较好，quality_comparisons 可以为空数组。"""

        try:
            prompts.append({"stage": "QUALITY_COMPARISON_ANALYSIS", "system_prompt": system_prompt, "user_prompt": user_prompt})
            
            response = await call_llm(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_analysis_tokens,
            )
            
            result = json.loads(clean_llm_output(response))
            comparisons = result.get("quality_comparisons", [])
            
            for comp in comparisons:
                # 只处理 Sketch 更好的情况
                if comp.get("better_version") != "sketch":
                    continue
                
                severity_str = comp.get("severity", "medium")
                severity = GapSeverity(severity_str) if severity_str in ["high", "medium", "low"] else GapSeverity.MEDIUM
                
                gaps.append(AlignmentGap(
                    gap_type=GapType.INFORMATION,
                    severity=severity,
                    beat_index=None,
                    beat_id=None,
                    description=f"{comp.get('narrative_point', '')}: {comp.get('reason', '')}",
                    draft_value="Draft 此处处理较弱",
                    sketch_value="Sketch 此处处理更优",
                    source=GapSource.EXPANSION_DRIFT,
                    fix_suggestion=comp.get("draft_improvement", ""),
                ))
        except Exception as e:
            logger.warning(f"[AdversarialAligner] 质量比较分析失败: {e}")
        
        return gaps, prompts
    
    async def _detect_boundary_gaps(self, draft_text: str, sketch_text: str, beats: List[dict]) -> List[AlignmentGap]:
        """
        检测结尾质量问题。
        
        只检查 Draft 自身的结尾完整性，不要求开头风格与 Sketch 一致。
        （开头风格是两轨并行生成的自然差异，不是问题）
        """
        gaps = []
        
        if not draft_text or not sketch_text:
            return gaps
        
        draft_ending = draft_text[-300:].strip()
        sketch_ending = sketch_text[-300:].strip()
        
        # 检测 1: Draft 结尾是否有明确的情节收束
        draft_has_closure = self._has_narrative_closure(draft_ending)
        sketch_has_closure = self._has_narrative_closure(sketch_ending)
        
        if not draft_has_closure and sketch_has_closure:
            gaps.append(AlignmentGap(
                gap_type=GapType.ENDING,
                severity=GapSeverity.MEDIUM,
                beat_index=len(beats) if beats else None,
                beat_id=beats[-1].get("beat_id") if beats else None,
                description="结尾缺少情节收束感，Sketch 有明确的收束而 Draft 没有",
                draft_value="Draft 结尾可能显得仓促或戛然而止",
                sketch_value="Sketch 结尾有明确的情节收束",
                source=GapSource.BEAT_DESIGN,
                fix_suggestion="为结尾添加适当的情节收束：情绪落点、悬念设置或场景定格均可",
            ))
        
        # 检测 2: 结尾是否以对话或省略号突然中断
        if draft_ending.endswith('"') or draft_ending.endswith('\u201d') or draft_ending.endswith('——'):
            gaps.append(AlignmentGap(
                gap_type=GapType.ENDING,
                severity=GapSeverity.LOW,
                beat_index=len(beats) if beats else None,
                beat_id=beats[-1].get("beat_id") if beats else None,
                description="结尾以对话或省略结束，可能显得不完整",
                draft_value=f"Draft 结尾: ...{draft_ending[-50:]}",
                sketch_value="建议添加叙述性收束",
                source=GapSource.EXPANSION_DRIFT,
                fix_suggestion="在对话后添加简短的叙述或动作描写作为收束",
            ))
        
        return gaps
    
    def _has_scene_description(self, text: str) -> bool:
        """
        检测文本是否包含场景描写
        
        通过关键词启发式判断
        """
        scene_keywords = [
            "阳光", "月光", "风", "雨", "雪", "天空", "大地",
            "房间", "街道", "树", "花", "水", "火",
            "站在", "坐在", "躺在", "走进", "走出",
            "看着", "望着", "凝视",
        ]
        return any(kw in text for kw in scene_keywords)
    
    def _has_narrative_closure(self, text: str) -> bool:
        """
        检测文本是否有叙事收束感
        
        通过句末标点和关键词判断
        """
        # 检查是否以陈述句结尾（句号、省略号）
        closure_endings = ["。", "……", '。"', '……"']
        has_proper_ending = any(text.rstrip().endswith(e) for e in closure_endings)
        
        # 检查是否有收束性关键词
        closure_keywords = [
            "终于", "最终", "至此", "就这样", "从此",
            "不再", "结束", "完成", "落幕", "告一段落",
        ]
        has_closure_keyword = any(kw in text[-100:] for kw in closure_keywords)
        
        return has_proper_ending or has_closure_keyword
    
    def _attribute_gaps(self, gaps: List[AlignmentGap], beats: List[dict]) -> List[AlignmentGap]:
        """归因分析"""
        attributed_gaps = []
        
        for gap in gaps:
            source = self._determine_gap_source(gap, beats)
            gap.source = source
            attributed_gaps.append(gap)
        
        return attributed_gaps
    
    def _determine_gap_source(self, gap: AlignmentGap, beats: List[dict]) -> GapSource:
        """确定问题根源"""
        if gap.gap_type == GapType.STRUCTURAL:
            if gap.beat_index == 1 or gap.beat_index == len(beats):
                return GapSource.BEAT_DESIGN
            else:
                return GapSource.EXPANSION_DRIFT
        
        if gap.gap_type == GapType.TRANSITION:
            return GapSource.SEGMENT_BOUNDARY
        
        if gap.gap_type == GapType.EMOTIONAL:
            return GapSource.EXPANSION_DRIFT
        
        if gap.gap_type == GapType.INFORMATION:
            return GapSource.EXPANSION_DRIFT
        
        if gap.gap_type in [GapType.OPENING, GapType.ENDING]:
            return GapSource.BEAT_DESIGN
        
        return GapSource.UNKNOWN
    
    def _generate_adjustments(self, gaps: List[AlignmentGap], beats: List[dict]) -> Tuple[Dict[int, List[str]], List[str]]:
        """生成修复方案"""
        beat_adjustments: Dict[int, List[str]] = {}
        global_adjustments = []
        
        for gap in gaps:
            if gap.severity == GapSeverity.LOW:
                continue
            
            instruction = self._generate_fix_instruction(gap)
            
            if gap.beat_index is not None:
                if gap.beat_index not in beat_adjustments:
                    beat_adjustments[gap.beat_index] = []
                beat_adjustments[gap.beat_index].append(instruction)
            else:
                global_adjustments.append(instruction)
        
        return beat_adjustments, global_adjustments
    
    def _generate_fix_instruction(self, gap: AlignmentGap) -> str:
        """生成修复指令"""
        base_instruction = gap.fix_suggestion
        
        if gap.source == GapSource.SEGMENT_BOUNDARY:
            base_instruction += " [注意：这是节拍衔接问题，需要软化过渡]"
        elif gap.source == GapSource.BEAT_DESIGN:
            base_instruction += " [注意：这是节拍设计问题，可能需要调整 entry/exit state]"
        elif gap.source == GapSource.SKETCH_HALLUCINATION:
            base_instruction += " [注意：Sketch 可能过度发挥，请谨慎评估是否采纳]"
        
        return base_instruction
    
    def _calculate_alignment_score(self, gaps: List[AlignmentGap]) -> float:
        """计算整体对齐度得分"""
        if not gaps:
            return 100.0
        
        base_score = 100.0
        
        for gap in gaps:
            if gap.severity == GapSeverity.HIGH:
                base_score -= 15
            elif gap.severity == GapSeverity.MEDIUM:
                base_score -= 8
            elif gap.severity == GapSeverity.LOW:
                base_score -= 3
        
        return max(0.0, base_score)
    
    def _is_key_beat(self, beat: dict) -> bool:
        """判断是否为关键节拍"""
        summary = beat.get("summary", "").lower()
        key_keywords = ["发现", "转折", "决定", "冲突", "高潮"]
        return any(kw in summary for kw in key_keywords)


async def perform_adversarial_alignment(
    draft_text: str,
    sketch_result: SketchResult,
    beats: List[dict],
    chapter: Any,
    book: Any,
    api_key: str,
    base_url: str,
    model: str,
) -> AdjustmentPlan:
    """便捷函数：执行对抗校对"""
    aligner = AdversarialAligner(api_key=api_key, base_url=base_url, model=model)
    return await aligner.align(draft_text=draft_text, sketch_result=sketch_result, beats=beats, chapter=chapter, book=book)

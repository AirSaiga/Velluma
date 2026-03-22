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
        """检测结构偏移差异"""
        gaps = []
        turn_markers = sketch_result.turn_markers
        
        if not turn_markers:
            return gaps
        
        draft_length = len(draft_text)
        if draft_length == 0:
            return gaps
        
        for i, beat in enumerate(beats, 1):
            beat_id = beat.get("beat_id", f"beat-{i}")
            
            sketch_marker = None
            for marker in turn_markers:
                if marker.beat_index == i:
                    sketch_marker = marker
                    break
            
            if not sketch_marker:
                continue
            
            expected_position = ((i - 0.5) / len(beats)) * 100
            sketch_position = sketch_marker.position_percent
            offset = abs(sketch_position - expected_position)
            
            if offset > self.config.structural_offset_threshold:
                severity = GapSeverity.HIGH if offset > 25 else GapSeverity.MEDIUM
                
                gaps.append(AlignmentGap(
                    gap_type=GapType.STRUCTURAL,
                    severity=severity,
                    beat_index=i,
                    beat_id=beat_id,
                    description=f"节拍 {i} 位置偏移过大（Sketch: {sketch_position:.1f}%, Draft 预期: {expected_position:.1f}%）",
                    draft_value=f"预期位置: {expected_position:.1f}%",
                    sketch_value=f"实际位置: {sketch_position:.1f}%",
                    source=GapSource.UNKNOWN,
                    fix_suggestion=f"调整节拍 {i} 的内容比重，使其在文中位置接近 {sketch_position:.1f}%",
                    position_percent=expected_position,
                ))
        
        return gaps
    
    async def _detect_emotional_gaps(self, draft_text: str, sketch_result: SketchResult, beats: List[dict]) -> List[AlignmentGap]:
        """检测情绪对齐差异"""
        gaps = []
        emotion_arc = sketch_result.emotion_arc
        
        if not emotion_arc:
            return gaps
        
        return gaps
    
    async def _detect_information_gaps(
        self, draft_text: str, sketch_text: str, beats: List[dict], chapter: Any, book: Any
    ) -> Tuple[List[AlignmentGap], List[dict]]:
        """检测信息对齐差异"""
        gaps = []
        prompts = []
        
        system_prompt = """你是一位信息对齐分析专家。对比两份同一故事的不同版本，分析关键信息揭示的时机和方式是否一致。

【重要】你必须且只能输出一个合法的 JSON 对象，不要输出任何其他内容。不要添加解释、不要添加 markdown 代码块、只输出纯 JSON。

输出格式：
{
  "info_alignments": [
    {
      "info_key": "信息描述",
      "draft_position": "在Draft中的大致位置",
      "sketch_position": "在Sketch中的大致位置",
      "aligned": true/false,
      "issue": "如果未对齐，描述问题",
      "severity": "high/medium/low"
    }
  ]
}"""

        key_beats = [b for b in beats if self._is_key_beat(b)]
        if len(key_beats) == 0:
            return gaps, prompts
        
        beats_summary = "\n".join([
            f"节拍 {b.get('position', i)}: {b.get('summary', '')}"
            for i, b in enumerate(key_beats, 1)
        ])
        
        user_prompt = f"""【节拍框架 - 关键情节点】
{beats_summary}

【版本 A：节拍统稿】
{draft_text[:2000]}...

【版本 B：连贯速写】
{sketch_text[:2000]}...

请分析以上两个版本中，关键信息揭示的时机是否一致。输出 JSON 格式的分析结果。"""

        try:
            prompts.append({"stage": "INFO_ALIGNMENT_ANALYSIS", "system_prompt": system_prompt, "user_prompt": user_prompt})
            
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
            alignments = result.get("info_alignments", [])
            
            for alignment in alignments:
                if not alignment.get("aligned", True):
                    severity_str = alignment.get("severity", "medium")
                    severity = GapSeverity(severity_str) if severity_str in ["high", "medium", "low"] else GapSeverity.MEDIUM
                    
                    gaps.append(AlignmentGap(
                        gap_type=GapType.INFORMATION,
                        severity=severity,
                        beat_index=None,
                        beat_id=None,
                        description=alignment.get("issue", "信息揭示时机不一致"),
                        draft_value=alignment.get("draft_position", "未知"),
                        sketch_value=alignment.get("sketch_position", "未知"),
                        source=GapSource.UNKNOWN,
                        fix_suggestion=f"调整'{alignment.get('info_key')}'的揭示时机和方式，参考 Sketch 的自然过渡",
                    ))
        except Exception as e:
            logger.warning(f"[AdversarialAligner] 信息对齐分析失败: {e}")
        
        return gaps, prompts
    
    async def _detect_boundary_gaps(self, draft_text: str, sketch_text: str, beats: List[dict]) -> List[AlignmentGap]:
        """检测开头和结尾的对齐差异"""
        gaps = []
        return gaps
    
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

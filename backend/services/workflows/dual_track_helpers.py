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
双轨辅助函数模块 - 支持双轨工作流的工具函数。

职责：
- 文本分段（按 Beat 比例）
- 修复指导构建
- Sketch 参考提取
- 差异聚合

业务场景：
- 双轨工作流的数据处理
- Draft A 文本分析
- 修复方案格式化

主要功能：
- 按 Beat 数量比例分段
- 聚合差异生成修复指导
- 提取 Sketch 中的参考片段

依赖项：
- backend.services.workflows.adversarial_aligner: 差异类型定义
- backend.services.workflows.sketch_generator: Sketch 结果

使用方式：
    segments = segment_draft_by_beats(draft_text, beats)
"""

import logging
from typing import Any, List

from backend.services.workflows.adversarial_aligner import GapSource
from backend.services.workflows.sketch_generator import SketchResult


logger = logging.getLogger(__name__)


def segment_draft_by_beats(draft_text: str, beats: List[dict]) -> List[str]:
    if not beats:
        return [draft_text]

    paragraphs = [p.strip() for p in draft_text.split("\n\n") if p.strip()]

    if not paragraphs:
        paragraphs = [p.strip() for p in draft_text.split("\n") if p.strip()]

    if not paragraphs:
        return [draft_text]

    total_target = sum(beat.get("word_count_target", 1) or beat.get("target_words", 1) or 1 for beat in beats)
    beat_ratios = []
    for beat in beats:
        target = beat.get("word_count_target", 1) or beat.get("target_words", 1) or 1
        beat_ratios.append(target / total_target)

    total_chars = sum(len(p) for p in paragraphs)
    segments = []
    para_idx = 0

    for beat_idx, ratio in enumerate(beat_ratios):
        target_chars = int(total_chars * ratio)
        segment_paragraphs = []
        current_chars = 0

        while para_idx < len(paragraphs) and current_chars < target_chars:
            segment_paragraphs.append(paragraphs[para_idx])
            current_chars += len(paragraphs[para_idx])
            para_idx += 1

        if beat_idx == len(beat_ratios) - 1:
            segment_paragraphs.extend(paragraphs[para_idx:])

        segments.append("\n\n".join(segment_paragraphs) if segment_paragraphs else "")

    return segments


def build_revision_guide(
    issues: List[str],
    gaps: List[Any],
    sketch_result: SketchResult,
    beat_index: int,
    total_beats: int,
) -> str:
    guide_parts = []

    if issues:
        guide_parts.append("【需要修复的问题】")
        for issue in issues:
            guide_parts.append(f"- {issue}")

    has_hallucination = False
    for gap in gaps:
        if gap.source == GapSource.SEGMENT_BOUNDARY:
            guide_parts.append("\n【特殊处理】这是节拍衔接问题，请参考 Sketch 中自然流畅的过渡方式，软化生硬的场景切换。")
        elif gap.source == GapSource.BEAT_DESIGN:
            guide_parts.append(f"\n【特殊处理】这是节拍设计问题，请确保 entry_state 和 exit_state 正确衔接。")
        elif gap.source == GapSource.SKETCH_HALLUCINATION:
            has_hallucination = True
            guide_parts.append(f"\n【防幻觉警告】注意：参考的 Sketch 在此处偏离了原定节拍设定，请忽略 Sketch 的偏离情节，严格遵循当前 Beat 的逻辑要求！")

    sketch_reference = extract_sketch_reference(
        sketch_result=sketch_result,
        beat_index=beat_index,
        total_beats=total_beats,
    )
    if sketch_reference and not has_hallucination:
        guide_parts.append(f"\n【Sketch 连贯性参考】\n以下是 Sketch 中对应位置的文本，参考其自然过渡和情绪流动：\n---\n{sketch_reference}\n---")
    elif sketch_reference and has_hallucination:
        guide_parts.append(f"\n【Sketch 连贯性参考】\n（注意：该段 Sketch 存在幻觉偏离，**仅参考其情绪流动和文字过渡**，切勿照抄其错误情节！）\n---\n{sketch_reference}\n---")

    return "\n".join(guide_parts)


def extract_sketch_reference(
    sketch_result: SketchResult,
    beat_index: int,
    total_beats: int,
) -> str:
    """从 SketchResult 提取对应 beat 的连贯性参考片段。

    CP1.2 改造（decisions U3a）：
    - 优先用 sketch_result.segments（按 beat_index 精确匹配，编辑天然对齐）
    - segments 为空时 fallback 到旧的 turn_markers position_percent 切片
    - 全部失败时按字符比例均分
    """
    if not sketch_result:
        return ""

    # 主路径：segments 精确匹配
    segments = getattr(sketch_result, "segments", None) or []
    if segments:
        match = next((s for s in segments if s.beat_index == beat_index), None)
        if match and match.text:
            text = match.text.strip()
            if len(text) > 800:
                text = text[:800] + "..."
            return text

    # Fallback：旧的 turn_markers position_percent 方式
    sketch_text = sketch_result.sketch_text
    if not sketch_text or total_beats == 0:
        return ""

    sketch_length = len(sketch_text)
    start_ratio = max(0, (beat_index - 1) / total_beats - 0.05)
    end_ratio = min(1, beat_index / total_beats + 0.05)

    turn_markers = getattr(sketch_result, "turn_markers", None) or []
    if turn_markers:
        markers = sorted(turn_markers, key=lambda m: m.beat_index)
        start_marker = next((m for m in reversed(markers) if m.beat_index < beat_index), None)
        if start_marker:
            start_ratio = max(0, start_marker.position_percent / 100.0 - 0.05)
        else:
            start_ratio = 0.0

        end_marker = next((m for m in markers if m.beat_index >= beat_index), None)
        if end_marker:
            end_ratio = min(1.0, end_marker.position_percent / 100.0 + 0.05)
        else:
            end_ratio = 1.0

    start_pos = int(sketch_length * start_ratio)
    end_pos = int(sketch_length * end_ratio)

    while start_pos > 0 and sketch_text[start_pos] not in "\n。！？":
        start_pos -= 1
    while end_pos < sketch_length - 1 and sketch_text[end_pos] not in "\n。！？":
        end_pos += 1

    reference = sketch_text[start_pos:end_pos + 1].strip()

    if len(reference) > 800:
        reference = reference[:800] + "..."

    return reference

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

    for gap in gaps:
        if gap.source == GapSource.SEGMENT_BOUNDARY:
            guide_parts.append("\n【特殊处理】这是节拍衔接问题，请参考 Sketch 中自然流畅的过渡方式，软化生硬的场景切换。")
        elif gap.source == GapSource.BEAT_DESIGN:
            guide_parts.append(f"\n【特殊处理】这是节拍设计问题，请确保 entry_state 和 exit_state 正确衔接。")

    sketch_reference = extract_sketch_reference(
        sketch_text=sketch_result.sketch_text,
        beat_index=beat_index,
        total_beats=total_beats,
    )
    if sketch_reference:
        guide_parts.append(f"\n【Sketch 连贯性参考】\n以下是 Sketch 中对应位置的文本，参考其自然过渡和情绪流动：\n---\n{sketch_reference}\n---")

    return "\n".join(guide_parts)


def extract_sketch_reference(
    sketch_text: str,
    beat_index: int,
    total_beats: int,
) -> str:
    if not sketch_text or total_beats == 0:
        return ""

    sketch_length = len(sketch_text)

    start_ratio = max(0, (beat_index - 1) / total_beats - 0.05)
    end_ratio = min(1, beat_index / total_beats + 0.05)

    start_pos = int(sketch_length * start_ratio)
    end_pos = int(sketch_length * end_ratio)

    while start_pos > 0 and sketch_text[start_pos] not in "\n。！？":
        start_pos -= 1
    while end_pos < sketch_length - 1 and sketch_text[end_pos] not in "\n。！？":
        end_pos += 1

    reference = sketch_text[start_pos:end_pos + 1].strip()

    if len(reference) > 500:
        reference = reference[:500] + "..."

    return reference

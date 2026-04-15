"""
统稿器模块 (Stitching) - 将多个节拍片段拼接为完整章节。

职责：
- 管理节拍片段的拼接
- 构建持久状态锚点
- 处理过渡文本

主要功能：
- 拼接多个 Beat 生成的片段
- 添加节拍间的过渡文本
- 维护章节整体连贯性

依赖项：
- backend.services.workflows.stitching: 原有统稿逻辑

使用方式：
    from backend.services.workflows.dual_track.stitching import stitch_beats

    stitched = await stitch_beats(beats, chunks, ...)
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.services.workflows.stitching import stitch_chunks

logger = logging.getLogger(__name__)


async def stitch_beats(
    chapter: Any,
    book: Any,
    beats: List[dict],
    beat_drafts: List[Any],
    word_count: int,
    anchor_pov: Optional[str] = None,
    sketch_text: Optional[str] = None,
    persistent_state_anchors: Optional[List[Dict[str, str]]] = None,
    prompt_logger: Optional[Any] = None,
) -> Tuple[str, float]:
    """
    将节拍片段拼接为完整章节。

    Args:
        chapter: 章节对象
        book: 书籍对象
        beats: 节拍列表
        beat_drafts: 节拍草案列表
        word_count: 目标字数
        anchor_pov: 锚点视角角色
        sketch_text: 速写参考文本
        persistent_state_anchors: 持久状态锚点
        api_key: API 密钥
        base_url: API 端点
        model: 模型名称
        prompt_logger: Prompt 日志记录器

    Returns:
        Tuple[str, float]: (拼接后的文本, 耗时)
    """
    import time
    stitch_start = time.perf_counter()

    chunks = [draft.draft_chunk for draft in beat_drafts]

    stitched_draft = await stitch_chunks(
        chapter=chapter,
        beats=beats,
        chunks=chunks,
        word_count=word_count,
        anchor_pov=anchor_pov,
        prompt_logger=prompt_logger,
        sketch_text=sketch_text,
        book=book,
        persistent_state_anchors=persistent_state_anchors or None,
    )

    stitch_time = time.perf_counter() - stitch_start
    logger.info(
        f"[Stitching] 统稿完成，耗时={stitch_time:.2f}s，"
        f"字数={len(stitched_draft)}"
    )

    return stitched_draft, stitch_time


def build_persistent_state_anchors(beats: List[dict]) -> List[Dict[str, str]]:
    """
    构建持久状态锚点。

    从节拍中提取退出状态作为持久锚点。

    Args:
        beats: 节拍列表

    Returns:
        持久状态锚点列表
    """
    anchors: List[Dict[str, str]] = []
    for i, beat in enumerate(beats):
        exit_state = beat.get("exit_state", "")
        if exit_state:
            anchors.append({
                "anchor_type": f"beat_{i + 1}_exit",
                "description": f"Beat {i + 1} 退出状态: {exit_state}",
            })
    return anchors


class StitchingConfig:
    """
    统稿配置。

    字段说明：
    - use_llm_transition: 是否使用 LLM 生成过渡文本
    - max_transition_length: 最大过渡文本长度
    - preserve_beat_markers: 是否保留节拍标记
    """
    use_llm_transition: bool = True
    max_transition_length: int = 200
    preserve_beat_markers: bool = False

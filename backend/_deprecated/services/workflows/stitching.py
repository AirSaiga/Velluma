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
统稿阶段工作流 - 将并行生成的文本片段缝合为连贯章节。

职责：
- 合并多个 Beat 生成的文本片段
- 处理片段间的过渡和衔接
- 确保叙事连贯性和风格一致

业务场景：
- Drafting 阶段之后的统稿步骤
- 并行生成多个 Beat 后整合为完整章节
- 支持反蒙太奇剪辑规则

主要功能：
- Beat 文本缝合
- 过渡词/场景转换处理
- 叙事连贯性保证

CP3.2 改造（蓝图 §4.7）：
- 默认**局部缝合**：只重写拍间接缝段落（以 sketch segments 的 transition_to_next 为锚）
  输入只含"接缝前后各约 200 字"（而非全文），显著降低 max_tokens（预估 15000 → 3000）
- 保留"全文统稿"为高档位选项：full_stitch=True 开启（原行为）

依赖项：
- backend.services.prompts: Stitch Prompt 模板
- backend.services.llm: LLM 调用接口

使用方式：
    # 默认局部缝合（CP3.2）
    final_text = await stitch_chunks(chapter, beats, chunks, word_count, ...)
    # 全文统稿（高档位）
    final_text = await stitch_chunks(..., full_stitch=True)
"""

from typing import Any, List, Optional

from backend.services.prompts import build_stitch_prompt, build_local_seam_prompt
from backend.services.llm import call_llm, call_llm_with_usage
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter
from backend.services.utils.prompt_logger import PromptLogger


# CP3.2 局部缝合参数（蓝图 §4.7）
SEAM_WINDOW_CHARS = 200          # 接缝前后各取的字符数
SEAM_MAX_TOKENS = 1200           # 单次接缝重写的 max_tokens 上限
SEAM_FALLBACK_MIN_TOKENS = 400   # 接缝输出过短的兜底阈值（字符）


async def stitch_chunks(
    chapter: Chapter,
    beats: List[dict],
    chunks: List[str],
    word_count: int,
    anchor_pov: Optional[str] = None,
    prompt_logger: Optional[PromptLogger] = None,
    sketch_text: Optional[str] = None,
    book: Optional[Any] = None,
    persistent_state_anchors: Optional[list[dict]] = None,
    recorder: Optional[Any] = None,
    full_stitch: bool = False,
) -> str:
    """将多个并行生成的 chunks 统稿成连贯的章节正文。

    CP3.2 改造：默认走局部缝合（full_stitch=False），只重写拍间接缝段落。
    蓝图 §4.7：局部缝合以 sketch segments 的 transition_to_next 为锚，
    输入只含接缝前后各 200 字，显著降低 max_tokens（15000 → ~3000）。

    Args:
        chapter: 章节实体
        beats: 剧情节拍列表
        chunks: 已生成的文本片段列表
        word_count: 目标字数
        anchor_pov: 主导视角角色名，启用反蒙太奇剪辑规则
        prompt_logger: 可选的日志记录器，用于记录统稿 prompt
        sketch_text: 连贯速写文本，作为连贯性参考（双轨模式）
        book: 书籍实体，用于获取文风控制数据
        persistent_state_anchors: 持久状态锚点列表，用于跨 Beat 状态平滑 (V4.0)
        recorder: 可选的 RunRecorder 实例（Phase 0 观测层）
        full_stitch: CP3.2 高档位开关；True 走全文统稿（原行为），False 走局部缝合（默认）

    Returns:
        str: 统稿后的正文
    """
    # 单 chunk 或空 chunks：无需缝合，直接拼接返回（保留原 clean 行为）
    if not chunks:
        return ""
    if len(chunks) == 1:
        return clean_llm_output(chunks[0]) or chunks[0]

    # CP3.2：默认局部缝合
    if not full_stitch:
        return await _stitch_local_seams(
            chapter=chapter,
            beats=beats,
            chunks=chunks,
            anchor_pov=anchor_pov,
            prompt_logger=prompt_logger,
            sketch_text=sketch_text,
            book=book,
            persistent_state_anchors=persistent_state_anchors,
            recorder=recorder,
        )

    # 全文统稿（高档位，原行为）
    return await _stitch_full(
        chapter=chapter,
        beats=beats,
        chunks=chunks,
        word_count=word_count,
        anchor_pov=anchor_pov,
        prompt_logger=prompt_logger,
        sketch_text=sketch_text,
        book=book,
        persistent_state_anchors=persistent_state_anchors,
        recorder=recorder,
    )


# ============================================================
# 局部缝合（CP3.2 默认路径，蓝图 §4.7）
# ============================================================

async def _stitch_local_seams(
    *,
    chapter: Chapter,
    beats: List[dict],
    chunks: List[str],
    anchor_pov: Optional[str],
    prompt_logger: Optional[PromptLogger],
    sketch_text: Optional[str],
    book: Optional[Any],
    persistent_state_anchors: Optional[list[dict]],
    recorder: Optional[Any],
) -> str:
    """局部缝合：逐个接缝重写，保留各 chunk 主体。

    算法：
    - 共 N 个 chunk → N-1 个接缝
    - 每个接缝取 chunk[i] 末尾 200 字 + chunk[i+1] 开头 200 字为窗口
    - 调 LLM 只重写该窗口的过渡段（小 max_tokens）
    - 拼装：chunk[0][:−200] + seam_0 + chunk[1][200:−200] + seam_1 + ... + chunk[N-1][200:]

    兜底：若 LLM 返回空或过短，该接缝用原始拼接（chunk[i] 末尾 + chunk[i+1] 开头）。
    """
    n = len(chunks)
    # 预切各 chunk 的接缝窗口
    # chunk[i] 的"尾部窗口"和 chunk[i+1] 的"头部窗口"构成接缝 i
    seams: List[tuple] = []  # [(left_chunk_idx, left_window, right_window), ...]
    for i in range(n - 1):
        left = chunks[i]
        right = chunks[i + 1]
        left_window = left[-SEAM_WINDOW_CHARS:] if len(left) > SEAM_WINDOW_CHARS else left
        right_window = right[:SEAM_WINDOW_CHARS] if len(right) > SEAM_WINDOW_CHARS else right
        seams.append((i, left_window, right_window))

    rewritten_seams: List[str] = []
    for idx, (i, left_window, right_window) in enumerate(seams):
        seam_system, seam_user = build_local_seam_prompt(
            chapter=chapter,
            beats=beats,
            seam_index=idx,
            total_seams=len(seams),
            left_chunk_index=i,
            right_chunk_index=i + 1,
            left_window=left_window,
            right_window=right_window,
            anchor_pov=anchor_pov,
            sketch_text=sketch_text,
            book=book,
        )

        if prompt_logger:
            prompt_logger.log_prompts(
                system_prompt=seam_system,
                user_prompt=seam_user,
                temperature=0.4,
                max_tokens=SEAM_MAX_TOKENS,
                prompt_label=f"STITCH_SEAM_{idx}",
            )

        # 调用 LLM 重写接缝（小 max_tokens）
        try:
            if recorder is not None:
                async with recorder.record_call(
                    stage=f"stitching.seam.{idx}",
                    model_slot="creative",
                ) as ctx:
                    llm_result = await call_llm_with_usage(
                        system_prompt=seam_system,
                        user_prompt=seam_user,
                        temperature=0.4,
                        max_tokens=SEAM_MAX_TOKENS,
                        model_type="creative",
                    )
                    ctx.set_result(llm_result)
                seam_text = llm_result.content
            else:
                seam_text = await call_llm(
                    system_prompt=seam_system,
                    user_prompt=seam_user,
                    temperature=0.4,
                    max_tokens=SEAM_MAX_TOKENS,
                    model_type="creative",
                )
            seam_text = clean_llm_output(seam_text)
        except Exception as e:
            # 接缝重写失败 → 降级为原始拼接（不阻断整体缝合）
            import logging
            logging.getLogger(__name__).warning(
                f"[Stitch] 接缝 {idx} 重写失败，降级原始拼接: {type(e).__name__}: {e}"
            )
            if recorder is not None:
                recorder.record_degraded(
                    stage=f"stitching.seam.{idx}",
                    reason="seam_rewrite_exception",
                    action="fallback_raw_concat",
                    model_slot="creative",
                    detail=f"{type(e).__name__}: {str(e)[:200]}",
                )
            seam_text = ""

        # 兜底：LLM 返回空或过短 → 用原始窗口拼接
        if not seam_text or len(seam_text) < SEAM_FALLBACK_MIN_TOKENS // 2:
            seam_text = left_window + "\n\n" + right_window

        rewritten_seams.append(seam_text)

    # 拼装最终正文：chunk[0] 去尾部 + seam[0] + chunk[1] 去头尾 + seam[1] + ... + chunk[N-1] 去头部
    parts: List[str] = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            # 首个 chunk：保留去尾部窗口的部分
            head = chunk[:-SEAM_WINDOW_CHARS] if len(chunk) > SEAM_WINDOW_CHARS else ""
            parts.append(head)
        elif i == n - 1:
            # 末个 chunk：保留去头部窗口的部分
            tail = chunk[SEAM_WINDOW_CHARS:] if len(chunk) > SEAM_WINDOW_CHARS else chunk
            parts.append(tail)
        else:
            # 中间 chunk：去头尾窗口
            if len(chunk) > 2 * SEAM_WINDOW_CHARS:
                parts.append(chunk[SEAM_WINDOW_CHARS:-SEAM_WINDOW_CHARS])
            else:
                parts.append("")  # 过短的中间 chunk 主体为空
        # 在 chunk 后插入对应的接缝（除了最后一个 chunk）
        if i < n - 1:
            parts.append(rewritten_seams[i])

    final_text = "".join(p for p in parts if p).strip()
    # 段落分隔规范化（去除多余空行）
    final_text = "\n\n".join(p.strip() for p in final_text.split("\n\n") if p.strip())
    if not final_text:
        # 极端兜底
        final_text = "\n\n".join(c.strip() for c in chunks if c.strip())
    return final_text


# ============================================================
# 全文统稿（CP3.2 高档位路径，原 stitch_chunks 行为）
# ============================================================

async def _stitch_full(
    *,
    chapter: Chapter,
    beats: List[dict],
    chunks: List[str],
    word_count: int,
    anchor_pov: Optional[str],
    prompt_logger: Optional[PromptLogger],
    sketch_text: Optional[str],
    book: Optional[Any],
    persistent_state_anchors: Optional[list[dict]],
    recorder: Optional[Any],
) -> str:
    """全文统稿（高档位，原 stitch_chunks 行为）。

    保留此路径作为 full_stitch=True 时的退化选项。max_tokens 沿用原公式。
    """
    stitch_system_prompt, stitch_user_prompt = build_stitch_prompt(
        chapter=chapter,
        beats=beats,
        chunks=chunks,
        word_count=word_count,
        anchor_pov=anchor_pov,
        book=book,
        sketch_text=sketch_text,
        persistent_state_anchors=persistent_state_anchors,
    )

    # 按原始 chunks 总字数 * 3 作为上限（中文 token 约 1.5字/token，预留 buffer）
    total_chunks_chars = sum(len(c) for c in chunks)
    safe_max_tokens = max(10000, total_chunks_chars * 3)

    # 记录统稿 prompt
    if prompt_logger:
        prompt_logger.log_prompts(
            system_prompt=stitch_system_prompt,
            user_prompt=stitch_user_prompt,
            temperature=0.4,
            max_tokens=safe_max_tokens,
            prompt_label="STITCH_FULL",
        )

    # T1 观测层 + T2 creative 槽
    if recorder is not None:
        async with recorder.record_call(stage="stitching", model_slot="creative") as ctx:
            llm_result = await call_llm_with_usage(
                system_prompt=stitch_system_prompt,
                user_prompt=stitch_user_prompt,
                temperature=0.4,
                max_tokens=safe_max_tokens,
                model_type="creative",
            )
            ctx.set_result(llm_result)
        stitched_text = llm_result.content
    else:
        stitched_text = await call_llm(
            system_prompt=stitch_system_prompt,
            user_prompt=stitch_user_prompt,
            temperature=0.4,
            max_tokens=safe_max_tokens,
            model_type="creative",
        )

    stitched_text = clean_llm_output(stitched_text)

    if not stitched_text.strip():
        stitched_text = "\n\n".join(chunks).strip()

    return stitched_text

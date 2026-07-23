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
组装器（V3.0 新建）。

职责（设计文档 §5 Phase 5）：
按 reading_order 拼接铺垫段 + 爆发段，处理接缝（铺垫最后一段与爆发段开头的过渡句打磨）。

设计要点（D2 爆炸先写 + 呼吸连续性）：
- 爆炸与铺垫共享同一因果脊柱，接缝天然柔软
- 不再有全文统稿（与 2.0 stitching 的本质区别）
- 接缝只做"抵达处理"：0~1 次 creative 调用，输入仅两端各 500 字
- >5000 字复杂章才退回 stitching fallback（Slice C）

业务场景：
- workflow.execute 内部调用（铺垫写作完成后）
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from backend.services.llm import call_llm_with_usage
from backend.services.workflows.detonation.types import FuseSegment

logger = logging.getLogger(__name__)


# 组装参数
SEAM_MAX_TOKENS = 1024
SEAM_TEMPERATURE = 0.7
SEAM_WINDOW = 500  # 接缝处理输入窗口（字符）


async def assemble_chapter(
    fuse_segments: List[FuseSegment],
    payload_text: str,
    seam_polish: bool = True,
    recorder: Optional[Any] = None,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """按 reading_order 拼接铺垫段 + 爆发段，可选打磨接缝。

    Args:
        fuse_segments: 铺垫段列表（已按 reading_order 排列）
        payload_text: 爆发段成文
        seam_polish: 是否打磨接缝（铺垫末段与爆发段开头）
        recorder: 可选 RunRecorder

    Returns:
        tuple: (full_text, seam_info)
        - full_text: 组装后的完整正文
        - seam_info: 接缝处理信息（None 表示未打磨）
    """
    # 拼接铺垫段（每段之间用换行分隔）
    fuse_text_parts = [seg.text for seg in fuse_segments if seg.text]
    fuse_text = "\n\n".join(fuse_text_parts)

    if not fuse_text:
        # 纯爆发章（无铺垫）
        logger.info("[Assembler] 无铺垫段，直接返回爆发段")
        return payload_text.strip(), None

    if not seam_polish:
        # 不打磨：简单拼接
        full_text = f"{fuse_text}\n\n{payload_text.strip()}"
        return full_text, None

    # 打磨接缝：铺垫末段尾部 + 爆发段开头，生成过渡句
    last_segment_tail = fuse_segments[-1].text[-SEAM_WINDOW:] if fuse_segments else ""
    payload_head = payload_text[:SEAM_WINDOW] if payload_text else ""

    seam_sentence = await await_seam_polish(
        fuse_tail=last_segment_tail,
        payload_head=payload_head,
        recorder=recorder,
    )

    if seam_sentence:
        # 插入过渡句（作为独立段落）
        full_text = f"{fuse_text}\n\n{seam_sentence}\n\n{payload_text.strip()}"
        seam_info = {"polished": True, "seam_sentence": seam_sentence}
    else:
        # 打磨失败或不需要 → 简单拼接
        full_text = f"{fuse_text}\n\n{payload_text.strip()}"
        seam_info = {"polished": False, "reason": "no_seam_needed_or_failed"}

    logger.info(f"[Assembler] 组装完成：铺垫 {len(fuse_text)} 字 + 接缝 + 爆发 {len(payload_text)} 字")
    return full_text, seam_info


async def await_seam_polish(
    fuse_tail: str,
    payload_head: str,
    recorder: Optional[Any] = None,
) -> Optional[str]:
    """打磨接缝过渡句（0~1 次 creative 调用）。

    输入仅两端各 ~500 字。输出一句（或两小句）过渡句。
    """
    if not fuse_tail or not payload_head:
        return None

    system_prompt = """你是一位小说编辑。给你一段铺垫的结尾和一段爆发段的开头，请写一句（最多两句）自然的过渡句，让铺垫的结尾与爆发段的开头呼吸连续。

要求：
- 只输出过渡句本身，不要任何解释/前言/标题
- 过渡句要克制，不要剧透爆发段的内容
- 允许不写（如果两端已经自然衔接）——此时输出空字符串"""

    user_prompt = f"""【铺垫段结尾】
{fuse_tail}

【爆发段开头】
{payload_head}

请写过渡句（若两端已自然衔接则输出空行）："""

    try:
        if recorder is not None:
            async with recorder.record_call(
                stage="detonation.assembler.seam",
                model_slot="creative",
            ) as ctx:
                result = await call_llm_with_usage(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model_type="creative",
                    temperature=SEAM_TEMPERATURE,
                    max_tokens=SEAM_MAX_TOKENS,
                )
                ctx.set_result(result)
        else:
            result = await call_llm_with_usage(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model_type="creative",
                temperature=SEAM_TEMPERATURE,
                max_tokens=SEAM_MAX_TOKENS,
            )
    except Exception as e:
        logger.warning(f"[Assembler] 接缝打磨失败: {e}")
        return None

    seam = (result.content or "").strip()
    # 空行或明显无内容的标记 → 不需要过渡句
    if not seam or seam in ("", "无", "（无）", "不需要"):
        return None
    return seam

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

from typing import Any, List, Optional

from backend.services.prompts import build_stitch_prompt
from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter
from backend.services.utils.prompt_logger import PromptLogger


async def stitch_chunks(
    chapter: Chapter,
    beats: List[dict],
    chunks: List[str],
    word_count: int,
    api_key: str,
    base_url: str,
    model: str,
    anchor_pov: Optional[str] = None,
    prompt_logger: Optional[PromptLogger] = None,
    sketch_text: Optional[str] = None,
    book: Optional[Any] = None,
    persistent_state_anchors: Optional[list[dict]] = None,
) -> str:
    """将多个并行生成的 chunks 统稿成连贯的章节正文。

    Args:
        chapter: 章节实体
        beats: 剧情节拍列表
        chunks: 已生成的文本片段列表
        word_count: 目标字数
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        anchor_pov: 主导视角角色名，启用反蒙太奇剪辑规则
        prompt_logger: 可选的日志记录器，用于记录统稿 prompt
        sketch_text: 连贯速写文本，作为连贯性参考（双轨模式）
        book: 书籍实体，用于获取文风控制数据
        persistent_state_anchors: 持久状态锚点列表，用于跨 Beat 状态平滑 (V3.5)

    Returns:
        str: 统稿后的正文
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
            model=model,
            temperature=0.4,
            max_tokens=safe_max_tokens,
            prompt_label="STITCH",
        )
    
    stitched_text = await call_llm(
        system_prompt=stitch_system_prompt,
        user_prompt=stitch_user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.4,
        max_tokens=safe_max_tokens,
    )
    
    stitched_text = clean_llm_output(stitched_text)
    
    if not stitched_text.strip():
        stitched_text = "\n\n".join(chunks).strip()
    
    return stitched_text

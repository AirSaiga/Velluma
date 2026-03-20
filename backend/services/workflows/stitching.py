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

from typing import Any, List

from backend.services.prompts import build_stitch_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.models import Chapter


async def stitch_chunks(
    chapter: Chapter,
    beats: List[dict],
    chunks: List[str],
    word_count: int,
    api_key: str,
    base_url: str,
    model: str,
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

    Returns:
        str: 统稿后的正文
    """
    stitch_system_prompt, stitch_user_prompt = build_stitch_prompt(
        chapter=chapter,
        beats=beats,
        chunks=chunks,
        word_count=word_count,
    )
    
    stitched_text = await call_llm(
        system_prompt=stitch_system_prompt,
        user_prompt=stitch_user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.4,
    )
    
    stitched_text = clean_llm_output(stitched_text)
    
    if not stitched_text.strip():
        stitched_text = "\n\n".join(chunks).strip()
    
    return stitched_text

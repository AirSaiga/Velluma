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

import logging
from fastapi import APIRouter, Depends, HTTPException
from backend.core.dependencies import get_chapter_repository
from backend.core.exceptions import not_found, generation_error
from backend.repositories import ChapterRepository
from backend.schemas import InspirationRequest, InspirationResponse
from backend.services.generation.inspiration import load_inspiration_context, generate_inspirations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["inspiration"])


@router.post("/generate_inspiration", response_model=InspirationResponse)
async def generate_inspiration(
    request: InspirationRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """点子启发 API - 为作者提供后续剧情灵感

    轻量级接口，只加载最少断连的上下文：
    1. 核心世界观
    2. 前情提要
    3. 核心角色简介
    4. 开放状态的伏笔

    使用高 Temperature (默认 0.9) 增强发散性，
    强制返回结构化的 JSON 灵感卡片。
    """
    db = chapter_repo.get_session()

    context = await load_inspiration_context(
        db=db,
        book_id=request.book_id,
        chapter_id=request.chapter_id,
        active_character_ids=request.active_character_ids,
    )

    if not context:
        raise not_found("书籍或章节", f"book_id={request.book_id}, chapter_id={request.chapter_id}")

    try:
        inspiration_items = await generate_inspirations(
            context=context,
            chapter_title=request.chapter_title or "",
            temperature=request.temperature,
            global_taboos=None,
            author_intent=request.author_intent,
        )

        if not inspiration_items:
            raise ValueError("生成结果为空，可能是大模型返回格式不符合要求或内容被过滤")

        inspirations = [item.to_dict() for item in inspiration_items]
        return InspirationResponse(inspirations=inspirations)

    except ValueError as e:
        logger.error(f"Inspiration generation failed: {e}")
        raise generation_error("生成灵感失败", e)

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

from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from backend.core.dependencies import get_chapter_repository
from backend.repositories import ChapterRepository
from backend.models import Chapter, ChapterEntity, CharacterRelationship
from backend.schemas import OptimizeChapterRequest, OptimizeSelectionRequest
from backend.services.generation.chapter import refine_draft
from backend.services.llm import optimize_selection_with_llm

router = APIRouter(prefix="/api", tags=["chapter_optimization"])


@router.post("/optimize_chapter")
async def optimize_chapter(
    request: OptimizeChapterRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """业务目的：根据用户反馈优化章节内容。

    参数来源：
    - request: 包含 chapter_id, optimization_feedback（V4.1: 模型配置已从 model_config.json 读取）

    数据流：
    1. 获取章节、书籍、角色、关系上下文
    2. 调用 Refine Agent 进行重写
    3. 返回优化后的内容

    注意：此操作不会直接修改数据库，需要用户确认后保存
    """
    db = chapter_repo.get_session()
    chapter_id = request.chapter_id

    result = await db.execute(
        select(Chapter)
        .options(
            selectinload(Chapter.book),
            selectinload(Chapter.story_beats)
        )
        .where(Chapter.id == chapter_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    
    book = chapter.book

    entities_result = await db.execute(
        select(ChapterEntity)
        .options(selectinload(ChapterEntity.character))
        .where(ChapterEntity.chapter_id == chapter_id)
    )
    entities = entities_result.scalars().all()
    
    character_ids = []
    seen_ids = set()
    for e in entities:
        if e.character and e.character.id not in seen_ids:
            seen_ids.add(e.character.id)
            character_ids.append(e.character.id)
            
    relationships = []
    if character_ids:
        relationships_result = await db.execute(
            select(CharacterRelationship)
            .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
            .where(
                CharacterRelationship.source_char_id.in_(character_ids),
                CharacterRelationship.target_char_id.in_(character_ids),
            )
        )
        relationships = relationships_result.scalars().all()

    current_draft = chapter.content_text or chapter.draft_text or ""
    if not current_draft:
        raise HTTPException(status_code=400, detail="当前章节没有内容可优化")
    
    refined_text = await refine_draft(
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        current_draft=current_draft,
        revision_plan=request.optimization_feedback,
        word_count=request.word_count,
    )
    
    return {"optimized_content": refined_text}


@router.post("/optimize_selection")
async def optimize_selection(
    request: OptimizeSelectionRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """
    对用户选中的文本进行优化。

    S2 E5：注入文风约束（画像/避免用词/笔迹示范）——此前选区改写完全不读
    文风卡，"AI 润色"默认把文字往通用腔上拉，与文风目标背道而驰。
    无文风卡/样本 → style_context 为空，行为与原先一致。
    """
    chapter = await chapter_repo.get_by_id(request.chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")

    outline = chapter.outline_text or "（暂无大纲）"
    style_context = await _build_selection_style_context(chapter_repo.get_session(), chapter)

    optimized_text = await optimize_selection_with_llm(
        selected_text=request.selected_text,
        context_before=request.context_before,
        context_after=request.context_after,
        outline=outline,
        user_instruction=request.user_instruction,
        mode=request.mode,
        tone=request.tone,
        style_context=style_context,
    )

    return {"optimized_text": optimized_text}


async def _build_selection_style_context(db, chapter) -> str:
    """拼装选区改写的文风约束块（书级文风卡画像+禁词 + 1 条笔迹示范）。

    纯增量：任一部分缺失就跳过；全空返回 ""（调用方 prompt 零变化）。
    """
    parts = []
    try:
        from backend.models import StyleCard as StyleCardModel
        from backend.services.context.settings_bundle import render_style_positive

        result = await db.execute(
            select(StyleCardModel).where(
                StyleCardModel.book_id == chapter.book_id,
                StyleCardModel.chapter_id.is_(None),
            ).limit(1)
        )
        style_card = result.scalar_one_or_none()
        if style_card:
            positive = render_style_positive(style_card)
            if positive:
                parts.append(positive)
            negatives = [
                (item.get("word") or item.get("phrase") or "")
                for item in (style_card.negative_list or [])
                if isinstance(item, dict) and (item.get("word") or item.get("phrase"))
            ]
            if negatives:
                parts.append("避免用词：" + "、".join(negatives[:30]))
    except Exception:
        pass  # 文风卡加载失败不阻塞改写

    try:
        from backend.services.style.retrieval import retrieve_author_samples

        samples = await retrieve_author_samples(
            db, str(chapter.book_id),
            (chapter.outline_text or "")[:200],
            k=1, max_chars=800,
        )
        if samples:
            parts.append(f"笔迹示范（学其语感，禁止复制内容）：\n{samples[0]}")
    except Exception:
        pass  # 样本加载失败不阻塞改写

    return "\n\n".join(parts)


# ============================================================
# NLE-ADF 2.0：深度清脂（De-Fat Dial 深度档，Alt+Shift+↓）
# ============================================================

class DefatSelectionRequest(BaseModel):
    """深度清脂请求：任意段落文本（不限于生成会话内）。"""
    text: str = Field(..., min_length=1, max_length=5000)
    must_keep: Optional[List[str]] = Field(
        None, description="洗涤必须保留的锚点词（防洗掉情节硬元素）"
    )
    chapter_id: Optional[str] = Field(None, description="章节 ID（取书级负面清单喂洗涤）")
    book_id: Optional[str] = Field(None, description="书籍 ID（无章节上下文时的兜底）")


@router.post("/defat_selection")
async def defat_selection(
    request: DefatSelectionRequest,
    chapter_repo: ChapterRepository = Depends(get_chapter_repository),
):
    """深度清脂：AI 味密度超阈值时调 LLM 重洗，未超标走正则轻裁。

    与本地词级规则（前端 Alt+↓）的分工：本地规则即时/免费/可预测但只能删
    套路词；本端点是"还嫌油"时的深度档——比喻句改写、心理升华句转白描
    由 wash LLM 完成。未超阈值不烧 LLM（wash_segment_if_too_ai 内置闸门）。
    """
    from backend.services.nlg.ai_taste_meter import measure_ai_taste
    from backend.services.nlg.de_ai_washer import wash_segment_if_too_ai

    text = request.text.strip()
    report = measure_ai_taste(text)
    # 禁忌面归一（任务包 A）：四源合并（系统陈词 + 文风卡负面清单 + 书级
    # 黑名单 + 静态反 AI 词）取「词（→ 替代）」格式前 30 条喂洗涤；
    # 加载失败 → 空列表，行为不变
    extra_banned: list[str] = []
    db = chapter_repo.get_session()
    chapter = await chapter_repo.get_by_id(request.chapter_id) if request.chapter_id else None
    book_id = str(chapter.book_id) if chapter else (request.book_id or "")
    if book_id:
        try:
            from backend.models import Book as BookModel, StyleCard as StyleCardModel
            sc_result = await db.execute(
                select(StyleCardModel).where(
                    StyleCardModel.book_id == book_id,
                    StyleCardModel.chapter_id.is_(None),
                ).limit(1)
            )
            card = sc_result.scalar_one_or_none()
            from backend.services.style.prohibitions import load_prohibition_set
            ps = await load_prohibition_set(
                db, book=await db.get(BookModel, book_id), style_card=card,
            )
            extra_banned = [
                e.pattern + (f"（→ {e.alternative}）" if e.alternative else "")
                for e in ps.entries
            ][:30]
        except Exception:
            pass
    result = await wash_segment_if_too_ai(
        text, report, must_keep=request.must_keep, extra_banned_words=extra_banned or None,
    )
    return {
        "text": result.text,
        "washed": result.washed,
        "original_score": result.original_score,
        "final_score": result.final_score,
        "reason": result.reason,
    }

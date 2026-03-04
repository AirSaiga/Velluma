import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity
from backend.schemas import GenerateChapterAgenticRequest
from backend.services.llm_client import call_llm
from backend.services.prompt_builder import (
    build_draft_agent_prompt,
    build_refine_agent_prompt,
    build_review_agent_prompt,
    parse_review_result,
)


async def generate_agentic_chapter_stream(request: GenerateChapterAgenticRequest, db: AsyncSession):
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        yield f"data: {json.dumps({'error': '章节不存在'}, ensure_ascii=False)}\n\n"
        return
    max_iterations = request.max_iterations
    word_count = request.word_count or 2000
    yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在从数据库抽取人物卡与关系网...'}, ensure_ascii=False)}\n\n"
    book_result = await db.execute(select(Book).where(Book.id == chapter.book_id))
    book = book_result.scalar_one_or_none()
    entities_result = await db.execute(
        select(ChapterEntity).options(selectinload(ChapterEntity.character)).where(ChapterEntity.chapter_id == request.chapter_id)
    )
    entities = entities_result.scalars().all()
    character_ids = [e.entity_id for e in entities]
    relationships_result = await db.execute(
        select(CharacterRelationship)
        .options(selectinload(CharacterRelationship.source_character), selectinload(CharacterRelationship.target_character))
        .where(
            CharacterRelationship.source_char_id.in_(character_ids),
            CharacterRelationship.target_char_id.in_(character_ids),
        )
    )
    relationships = relationships_result.scalars().all()
    current_draft = ""
    revision_plan = ""
    iteration = 0
    review_passed = False
    while iteration < max_iterations:
        iteration += 1
        if iteration == 1:
            yield f"data: {json.dumps({'event': 'DRAFTING', 'message': '主笔 Agent 正在创作初稿...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            system_prompt, user_prompt = build_draft_agent_prompt(chapter, book, entities, relationships, word_count)
            yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
            current_draft = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.7,
            )
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
        else:
            yield f"data: {json.dumps({'event': 'REFINING', 'message': f'发现逻辑遗漏，正在通知责编重写 (第{iteration}次)...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            system_prompt, user_prompt = build_refine_agent_prompt(
                chapter, book, entities, relationships, current_draft, revision_plan, word_count
            )
            current_draft = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.7,
            )
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
        yield f"data: {json.dumps({'event': 'REVIEWING', 'message': '审阅 Agent 正在进行逻辑校验和 OOC 排查...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
        system_prompt, user_prompt = build_review_agent_prompt(
            chapter, book, entities, relationships, chapter.outline_text or "", current_draft
        )
        review_result_json = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=request.api_key,
            base_url=request.base_url,
            model=request.model,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        review_result, _ = parse_review_result(review_result_json)
        chapter.review_feedback = review_result
        await db.commit()
        if review_result.get("pass", True):
            review_passed = True
            break
        revision_plan = review_result.get("revision_plan", "")
    chapter.content_text = current_draft
    await db.commit()
    yield f"data: {json.dumps({'event': 'FINAL_TEXT_STREAM', 'message': '正在输出最终文本...', 'passed': review_passed, 'iterations': iteration}, ensure_ascii=False)}\n\n"
    for char in current_draft:
        yield f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': char}, ensure_ascii=False)}\n\n"
    yield f"data: {json.dumps({'event': 'DONE', 'passed': review_passed, 'iterations': iteration, 'revision_count': iteration}, ensure_ascii=False)}\n\n"

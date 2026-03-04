import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, MemoryChunk
from backend.repositories import MemoryRepository
from backend.schemas import GenerateChapterAgenticRequest
from backend.services.llm_client import call_llm, get_embedding, generate_summary
from backend.services.prompt_builder import (
    build_draft_agent_prompt,
    build_refine_agent_prompt,
    build_review_agent_prompt,
    parse_review_result,
)


async def generate_agentic_chapter_stream(request: GenerateChapterAgenticRequest, db: AsyncSession):
    """
    代理工作流章节生成 (多轮迭代)。

    工作流步骤：
    1. 上下文组装 (ASSEMBLING_CONTEXT) - 从 DB 加载角色、关系
    2. 初稿生成 (DRAFTING) - Draft Agent 创作初稿
    3. 质量审查 (REVIEWING) - Review Agent 检查质量
    4. 迭代精修 (REFINING) - 若审查未通过，基于 revision_plan 重写
    5. 最终输出 (FINAL_TEXT_STREAM) - 输出最终文本

    状态传递：
    - iteration: 当前迭代轮次 (从1开始)
    - current_draft: 当前版本的正文 (初稿或精修稿)
    - revision_plan: 来自 Review Agent 的修改建议
    - review_passed: 审查是否通过

    上下文管理：
    - 角色和关系在首次迭代前一次性加载 (避免重复查询)
    - 章节大纲 (outline_text) 在各阶段保持不变
    - 动态状态不在此流程中更新 (需单独调用 character_state 服务)

    权衡：使用 while 循环 + break 实现迭代，最多为 max_iterations 次。
    警告：若审查一直不通过，会达到最大迭代次数后退出，可能产生低质量内容。
    """
    # 步骤1：加载章节基础信息
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == request.chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        yield f"data: {json.dumps({'error': '章节不存在'}, ensure_ascii=False)}\n\n"
        return
    max_iterations = request.max_iterations
    word_count = request.word_count or 2000
    yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在从数据库抽取人物卡与关系网...'}, ensure_ascii=False)}\n\n"

    # 步骤2：加载书籍和角色上下文 (一次性加载，避免N+1)
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

    # 步骤2.5：增强上下文 (前情提要 + RAG)
    yield f"data: {json.dumps({'event': 'ASSEMBLING_CONTEXT', 'message': '正在回顾前文与检索相关伏笔...'}, ensure_ascii=False)}\n\n"

    # 1. 获取上一章摘要
    prev_chapter_result = await db.execute(
        select(Chapter)
        .where(Chapter.book_id == chapter.book_id, Chapter.chapter_number == chapter.chapter_number - 1)
    )
    prev_chapter = prev_chapter_result.scalar_one_or_none()
    previous_summary = prev_chapter.summary if prev_chapter else None
    
    # Debug log for context injection
    print(f"[DEBUG] Context Injection - Chapter {chapter.chapter_number}")
    print(f"[DEBUG] Previous Summary (Ch {chapter.chapter_number - 1}): {bool(previous_summary)}")
    if previous_summary:
        print(f"[DEBUG] Summary Preview: {previous_summary[:50]}...")

    # 2. RAG 检索
    relevant_memories = []
    if chapter.outline_text:
        try:
            embedding = await get_embedding(chapter.outline_text, request.api_key, request.base_url)
            if embedding:
                memory_repo = MemoryRepository(db)
                relevant_memories = await memory_repo.search_similar(embedding, chapter.book_id, limit=3)
                print(f"[DEBUG] RAG Search: Found {len(relevant_memories)} relevant memories")
                for m in relevant_memories:
                    print(f"[DEBUG] Memory: {m.chunk_text[:50]}...")
            else:
                print("[DEBUG] RAG Search: Failed to generate embedding")
        except Exception as e:
            print(f"[RAG Error] {e}")

    # 迭代状态初始化
    current_draft = ""
    revision_plan = ""
    iteration = 0
    review_passed = False

    # 步骤3：迭代工作流 (Draft → Review → Refine 循环)
    while iteration < max_iterations:
        iteration += 1
        if iteration == 1:
            # 首次迭代：生成初稿
            yield f"data: {json.dumps({'event': 'DRAFTING', 'message': '主笔 Agent 正在创作初稿...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            system_prompt, user_prompt = build_draft_agent_prompt(
                chapter, book, entities, relationships, word_count,
                previous_summary=previous_summary,
                relevant_memories=relevant_memories
            )
            yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
            current_draft = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.7,
            )
            # 持久化初稿到 DB，支持断点续传
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
        else:
            # 后续迭代：根据审查意见精修
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

        # 步骤4：质量审查 (每轮迭代后必执行)
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

        # 步骤5：检查审查结果
        if review_result.get("pass", True):
            review_passed = True
            break
        # 提取修改建议，进入下一轮精修
        revision_plan = review_result.get("revision_plan", "")

    # 步骤6：最终定稿 (无论是否通过审查都输出内容)
    chapter.content_text = current_draft
    await db.commit()
    yield f"data: {json.dumps({'event': 'FINAL_TEXT_STREAM', 'message': '正在输出最终文本...', 'passed': review_passed, 'iterations': iteration}, ensure_ascii=False)}\n\n"

    # 逐字符输出 (模拟打字机效果，同时便于前端逐段接收)
    for char in current_draft:
        yield f"data: {json.dumps({'event': 'TEXT_CHUNK', 'content': char}, ensure_ascii=False)}\n\n"

    yield f"data: {json.dumps({'event': 'DONE', 'passed': review_passed, 'iterations': iteration, 'revision_count': iteration}, ensure_ascii=False)}\n\n"

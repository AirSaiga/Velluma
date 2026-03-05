import asyncio
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, CharacterRelationship, ChapterEntity, PlotLedger, SceneIntent, StoryBeat
from backend.repositories import MemoryRepository
from backend.schemas import GenerateChapterAgenticRequest
from backend.services.llm_client import call_llm, get_embedding
from backend.services.prompt_builder import (
    build_chunk_draft_prompt,
    build_draft_agent_prompt,
    build_planner_agent_prompt,
    build_refine_agent_prompt,
    build_review_agent_prompt,
    build_scene_intent_prompt,
    build_stitch_prompt,
    parse_planner_result,
    parse_review_result,
    parse_scene_intent_result,
)


def _clean_llm_output(text: str) -> str:
    """
    清理 LLM 输出，尝试解析 JSON 并提取内容，或移除 Markdown 标记。
    """
    if not text:
        return ""
    
    text = text.strip()
    
    # 尝试作为 JSON 解析 (处理 {"title": "...", "content": "..."} 的情况)
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            # 如果包含 content 字段，优先返回 content
            if isinstance(data, dict) and "content" in data:
                return str(data["content"]).strip()
            # 否则如果是纯文本的 value，可能返回整个 dict，视情况而定
            # 这里保守起见，如果解析成功但没有 content，可能不是我们要的格式，
            # 但如果是 {"chunk": "text"} 这种也可以尝试
            if isinstance(data, dict):
                # 尝试常见的字段
                for key in ["content", "text", "body", "chunk", "draft"]:
                    if key in data and isinstance(data[key], str):
                        return data[key].strip()
        except json.JSONDecodeError:
            pass

    # 移除 markdown 代码块 (``` ... ```)
    if text.startswith("```"):
        lines = text.split("\n")
        if len(lines) >= 2:
            # 移除第一行和最后一行
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            return "\n".join(lines).strip()
            
    return text


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
    open_hook_result = await db.execute(
        select(PlotLedger).where(
            PlotLedger.book_id == chapter.book_id,
            PlotLedger.status == "open",
        )
    )
    open_hook_rows = open_hook_result.scalars().all()
    open_hooks = []
    for row in open_hook_rows:
        content = str(getattr(row, "content", "") or "").strip()
        if not content:
            continue
        hook_id = str(getattr(row, "hook_id", None) or getattr(row, "ledger_key", None) or "").strip()
        open_hooks.append(
            {
                "hook_id": hook_id,
                "ledger_key": str(getattr(row, "ledger_key", "") or "").strip(),
                "content": content,
            }
        )
    
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
                relevant_memories = await memory_repo.search_similar(
                    embedding,
                    chapter.book_id,
                    limit=request.rag_top_k,
                    alpha=request.rag_alpha,
                    beta=request.rag_beta,
                    gamma=request.rag_gamma,
                    lambda_decay=request.rag_lambda,
                    exclude_chapter_id=chapter.id,
                )
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
            yield f"data: {json.dumps({'event': 'PLANNING', 'message': 'Planner 正在拆分章节 beats...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            planner_system_prompt, planner_user_prompt = build_planner_agent_prompt(
                chapter=chapter,
                book=book,
                entities=entities,
                relationships=relationships,
                word_count=word_count,
                open_hooks=open_hooks,
            )
            yield f"data: {json.dumps({'prompt': {'system_prompt': planner_system_prompt, 'user_prompt': planner_user_prompt}}, ensure_ascii=False)}\n\n"
            planner_result_raw = await call_llm(
                system_prompt=planner_system_prompt,
                user_prompt=planner_user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            beats = parse_planner_result(planner_result_raw, chapter.outline_text or "", word_count)
            generated_chunks = [None] * len(beats)
            story_beats = []

            # 1. 预先创建所有 StoryBeat 记录 (串行 DB 操作)
            for beat_index, beat in enumerate(beats, start=1):
                story_beat = StoryBeat(
                    book_id=chapter.book_id,
                    chapter_id=chapter.id,
                    beat_id=beat.get("beat_id"),
                    beat_type="progression",
                    position=beat.get("position", beat_index),
                    location=beat.get("location"),
                    pov_character=beat.get("pov_character"),
                    action_summary=beat.get("action_summary"),
                    worldbuilding_instruction=beat.get("worldbuilding_instruction"),
                    word_count_target=beat.get("word_count_target", beat.get("target_words", 0)),
                    summary=beat.get("summary", ""),
                    meta={"target_words": beat.get("target_words", 0)},
                    status="planned",
                )
                db.add(story_beat)
                story_beats.append(story_beat)
            await db.flush()

            # 2. 定义并行处理函数
            async def process_beat(beat_index, beat, story_beat):
                try:
                    # 计算 open_hooks
                    beat_hook_ids = set(beat.get("hook_ids", []))
                    beat_open_hooks = []
                    if beat_hook_ids:
                        beat_open_hooks = [
                            item
                            for item in open_hooks
                            if item["hook_id"] in beat_hook_ids or item["ledger_key"] in beat_hook_ids
                        ]
                    if not beat_open_hooks and beat_index == 1:
                        beat_open_hooks = open_hooks[:2]

                    # Scene Intent
                    scene_system_prompt, scene_user_prompt = build_scene_intent_prompt(
                        chapter=chapter,
                        beat=beat,
                        open_hooks=beat_open_hooks,
                    )
                    scene_intent_raw = await call_llm(
                        system_prompt=scene_system_prompt,
                        user_prompt=scene_user_prompt,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                        temperature=0.2,
                        response_format={"type": "json_object"},
                    )
                    scene_intent_data = parse_scene_intent_result(scene_intent_raw, beat.get("summary", ""))
                    
                    # 这里的 SceneIntent 写入需要注意并发，但 AsyncSession 不支持并发写入
                    # 暂时跳过写入 SceneIntent 到 DB，或者稍后统一写入
                    # 为了性能，这里仅保留内存对象用于传递给 Draft Agent
                    
                    target_words = beat.get("word_count_target")
                    if not isinstance(target_words, int) or target_words <= 0:
                        target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))

                    # Calculate context summaries
                    context_summaries = {}
                    if beat_index > 1:
                        context_summaries['prev'] = beats[beat_index - 2].get('summary', '')
                    if beat_index < len(beats):
                        context_summaries['next'] = beats[beat_index].get('summary', '')

                    # Draft Chunk
                    # 注意：并行时 previous_chunks 为空，依赖 Stitcher 修复连贯性
                    chunk_system_prompt, chunk_user_prompt = build_chunk_draft_prompt(
                        chapter=chapter,
                        book=book,
                        entities=entities,
                        relationships=relationships,
                        beat=beat,
                        scene_intent=scene_intent_data,
                        target_words=target_words,
                        previous_chunks=[], 
                        previous_summary=previous_summary,
                        relevant_memories=relevant_memories,
                        hook_contexts=beat_open_hooks,
                        context_beat_summaries=context_summaries,
                    )
                    
                    chunk_text = await call_llm(
                        system_prompt=chunk_system_prompt,
                        user_prompt=chunk_user_prompt,
                        api_key=request.api_key,
                        base_url=request.base_url,
                        model=request.model,
                        temperature=0.7,
                    )
                    return beat_index - 1, _clean_llm_output(chunk_text)
                except Exception as e:
                    print(f"[Beat Error] Beat {beat_index} failed: {e}")
                    return beat_index - 1, ""

            # 3. 并行执行所有 beats
            yield f"data: {json.dumps({'event': 'DRAFTING', 'message': f'正在并行创作 {len(beats)} 个剧情片段...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            
            # 使用 Semaphore 限制并发数
            sem = asyncio.Semaphore(5)
            async def sem_task(task):
                async with sem:
                    return await task

            tasks = [
                sem_task(process_beat(i, b, sb)) 
                for i, b, sb in zip(range(1, len(beats)+1), beats, story_beats)
            ]
            
            results = await asyncio.gather(*tasks)
            
            # 4. 收集结果
            generated_chunks = [""] * len(beats)
            for idx, text in results:
                generated_chunks[idx] = text

            yield f"data: {json.dumps({'event': 'STITCHING', 'message': '统稿 Agent 正在拼接 chunks...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            stitch_system_prompt, stitch_user_prompt = build_stitch_prompt(
                chapter=chapter,
                beats=beats,
                chunks=generated_chunks,
                word_count=word_count,
            )
            yield f"data: {json.dumps({'prompt': {'system_prompt': stitch_system_prompt, 'user_prompt': stitch_user_prompt}}, ensure_ascii=False)}\n\n"
            current_draft = await call_llm(
                system_prompt=stitch_system_prompt,
                user_prompt=stitch_user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=0.4,
            )
            current_draft = _clean_llm_output(current_draft)
            if not current_draft.strip():
                current_draft = "\n\n".join(generated_chunks).strip()
            if not current_draft.strip():
                fallback_system_prompt, fallback_user_prompt = build_draft_agent_prompt(
                    chapter,
                    book,
                    entities,
                    relationships,
                    word_count,
                    previous_summary=previous_summary,
                    relevant_memories=relevant_memories,
                )
                yield f"data: {json.dumps({'prompt': {'system_prompt': fallback_system_prompt, 'user_prompt': fallback_user_prompt}}, ensure_ascii=False)}\n\n"
                current_draft = await call_llm(
                    system_prompt=fallback_system_prompt,
                    user_prompt=fallback_user_prompt,
                    api_key=request.api_key,
                    base_url=request.base_url,
                    model=request.model,
                    temperature=0.7,
                )
                current_draft = _clean_llm_output(current_draft)
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()
        else:
            # 后续迭代：根据审查意见精修
            yield f"data: {json.dumps({'event': 'REFINING', 'message': f'发现逻辑遗漏，正在通知责编重写 (第{iteration}次)...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
            system_prompt, user_prompt = build_refine_agent_prompt(
                chapter, book, entities, relationships, current_draft, revision_plan, word_count
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
            current_draft = _clean_llm_output(current_draft)
            chapter.draft_text = current_draft
            chapter.revision_count = iteration
            await db.commit()

        # 步骤4：质量审查 (每轮迭代后必执行)
        yield f"data: {json.dumps({'event': 'REVIEWING', 'message': '审阅 Agent 正在进行逻辑校验和 OOC 排查...', 'iteration': iteration}, ensure_ascii=False)}\n\n"
        system_prompt, user_prompt = build_review_agent_prompt(
            chapter, book, entities, relationships, chapter.outline_text or "", current_draft
        )
        yield f"data: {json.dumps({'prompt': {'system_prompt': system_prompt, 'user_prompt': user_prompt}}, ensure_ascii=False)}\n\n"
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

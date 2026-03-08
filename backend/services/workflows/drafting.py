"""
起草模块。

职责：提供章节内容并行生成功能。

主要功能：
- generate_chunks_parallel: 并行生成多个故事节拍的正文片段
- _process_single_beat: 处理单个节拍的生成流程
- _build_beat_hooks: 构建节拍关联的伏笔上下文
"""

import asyncio
from typing import Any, List, Optional

from backend.services.prompts import build_scene_intent_prompt, parse_scene_intent_result, build_chunk_draft_prompt
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output


async def generate_chunks_parallel(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    story_beats: List[Any],
    open_hooks: List[dict],
    previous_summary: Optional[str],
    relevant_memories: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    word_count: int,
) -> List[str]:
    """并行生成多个故事节拍的正文片段。

    使用信号量限制并发数为 5，确保系统稳定性。

    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        beats: 节拍数据列表
        story_beats: 数据库中的 StoryBeat 实体列表
        open_hooks: 开放伏笔列表
        previous_summary: 上一章摘要
        relevant_memories: RAG 检索的相关记忆
        api_key: LLM API Key
        base_url: LLM Base URL
        model: LLM Model Name
        word_count: 目标总字数

    Returns:
        List[str]: 生成的 chunks 列表，按节拍顺序排列
    """
    async def process_single_beat(beat_index: int, beat: dict, story_beat: Any) -> tuple[int, str]:
        """处理单个节拍的生成流程。

        包含两个 LLM 调用：
        1. Scene Intent - 生成场景意图
        2. Chunk Draft - 生成正文内容

        Args:
            beat_index: 节拍索引（从1开始）
            beat: 节拍数据字典
            story_beat: StoryBeat 实体

        Returns:
            tuple[int, str]: (索引, 生成的文本)
        """
        try:
            beat_hooks = _build_beat_hooks(beat, open_hooks, beat_index)

            scene_system_prompt, scene_user_prompt = build_scene_intent_prompt(
                chapter=chapter,
                beat=beat,
                open_hooks=beat_hooks,
            )
            scene_intent_raw = await call_llm(
                system_prompt=scene_system_prompt,
                user_prompt=scene_user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            scene_intent_data = parse_scene_intent_result(scene_intent_raw, beat.get("summary", ""))

            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))

            context_summaries = _build_context_summaries(beat_index, beats, len(beats))

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
                hook_contexts=beat_hooks,
                context_beat_summaries=context_summaries,
            )

            chunk_text = await call_llm(
                system_prompt=chunk_system_prompt,
                user_prompt=chunk_user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.7,
            )
            return beat_index - 1, clean_llm_output(chunk_text)
        except Exception as e:
            print(f"[Beat Error] Beat {beat_index} failed: {e}")
            return beat_index - 1, ""

    def _build_beat_hooks(beat: dict, all_hooks: List[dict], beat_index: int) -> List[dict]:
        """构建节拍关联的伏笔上下文。

        规则：
        - 若 beat 指定了 hook_ids，匹配对应的伏笔
        - 若无指定且为第一个节拍，取前两个全局伏笔

        Args:
            beat: 节拍数据
            all_hooks: 所有开放伏笔
            beat_index: 节拍索引

        Returns:
            List[dict]: 该节拍关联的伏笔列表
        """
        beat_hook_ids = set(beat.get("hook_ids", []))
        if beat_hook_ids:
            return [
                item
                for item in all_hooks
                if item["hook_id"] in beat_hook_ids or item["ledger_key"] in beat_hook_ids
            ]
        if beat_index == 1:
            return all_hooks[:2]
        return []

    def _build_context_summaries(beat_index: int, beats: List[dict], total_beats: int) -> dict:
        """构建前后节拍的摘要上下文。

        Args:
            beat_index: 当前节拍索引（从1开始）
            beats: 所有节拍列表
            total_beats: 总节拍数

        Returns:
            dict: 包含 prev 和 next 键的上下文字典
        """
        summaries = {}
        if beat_index > 1:
            summaries["prev"] = beats[beat_index - 2].get("summary", "")
        if beat_index < total_beats:
            summaries["next"] = beats[beat_index].get("summary", "")
        return summaries

    sem = asyncio.Semaphore(5)

    async def sem_task(task):
        async with sem:
            return await task

    tasks = [
        sem_task(process_single_beat(i, b, sb))
        for i, b, sb in zip(range(1, len(beats) + 1), beats, story_beats)
    ]

    results = await asyncio.gather(*tasks)

    generated_chunks = [""] * len(beats)
    for idx, text in results:
        generated_chunks[idx] = text

    return generated_chunks

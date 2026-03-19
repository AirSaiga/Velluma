"""
起草模块 - 冰山模型与混合流水线实现。

职责：提供基于"潜意识-正文"双层架构的章节内容生成功能。

核心架构：
- 双模型路由：逻辑推理模型(Reasoning) vs 创意生成模型(Creative)
- 混合流水线：Scene Intent + Subconscious 并行生成，Prose Draft 串行滑动窗口生成
- Rolling Prefix：Beat n 接收 Beat n-1 的末尾 300 字符作为上下文

主要功能：
- execute_draft_stage: 主入口，执行完整的混合流水线
- _generate_subconscious_batch: 并行生成潜意识层
- _generate_scene_intent_batch: 并行生成场景意图
- _generate_prose_serial: 串行生成正文（Rolling Prefix）
"""

import asyncio
import time
from typing import Any, List, Optional
from pydantic import BaseModel

from backend.services.prompts import (
    build_scene_intent_prompt,
    parse_scene_intent_result,
    build_subconscious_prompt,
    build_prose_draft_prompt,
    build_chunk_review_prompt,
    build_chunk_refine_prompt,
)
from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output


class BeatDraftResult(BaseModel):
    """
    Beat 生成结果数据结构。
    
    职责：封装单个 Beat 的完整生成结果，包括潜意识层和正文层。
    
    Attributes:
        beat_id: Beat 唯一标识
        beat_index: Beat 在章节中的位置索引（从1开始）
        scene_intent: Scene Intent 分析结果（目标/风险/约束）
        subconscious_thought: 角色的潜意识/内心独白网络（50-100字）
        draft_chunk: 生成的小说正文
        prompts: 调试用的提示词历史列表
    """
    beat_id: str
    beat_index: int
    scene_intent: dict
    subconscious_thought: str
    draft_chunk: str
    prompts: List[dict] = []


async def execute_draft_stage(
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    beats: List[dict],
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    reasoning_model: str,
    creative_model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
) -> List[BeatDraftResult]:
    """
    执行混合流水线起草阶段。
    
    职责：协调双层生成流程，先并行生成轻量级思考层，再串行滑动窗口生成正文。
    
    流程:
        1. 并行生成所有 Beat 的 Scene Intent 和 Subconscious (步骤 A)
        2. 串行滑动窗口生成正文，使用 Rolling Prefix 机制保证连贯性 (步骤 B)
        3. 可选的 Chunk QC 质检与修复
    
    Args:
        chapter: 章节实体
        book: 书籍实体
        entities: 章节关联的角色实体列表
        relationships: 角色关系列表
        beats: 节拍数据列表
        open_hooks: 开放伏笔列表
        api_key: LLM API Key
        base_url: LLM Base URL
        reasoning_model: 高逻辑模型（用于 Scene Intent + Subconscious）
        creative_model: 高创意模型（用于 Prose Draft，当前可与 reasoning_model 相同）
        word_count: 目标总字数
        previous_summary: 上一章摘要（可选）
        relevant_memories: RAG 检索的相关记忆（可选）
        locations: 地图地点列表（可选）
        enable_qc: 是否启用自动质检（默认 True）
    
    Returns:
        List[BeatDraftResult]: 按 Beat 顺序排列的生成结果列表
    """
    if not beats:
        return []
    
    print(f"[Draft Stage] 开始混合流水线，共 {len(beats)} 个 Beats")
    stage_start = time.perf_counter()
    
    # ========================================================================
    # 步骤 A: 并行生成轻量级思考层（无文本依赖）
    # ========================================================================
    print("[Draft Stage] 步骤 A: 并行生成 Scene Intent + Subconscious...")
    step_a_start = time.perf_counter()
    
    # A-1: 并行生成 Scene Intent
    scene_intent_results = await _generate_scene_intent_batch(
        beats=beats,
        chapter=chapter,
        open_hooks=open_hooks,
        api_key=api_key,
        base_url=base_url,
        model=reasoning_model,
    )
    
    # A-2: 并行生成 Subconscious（依赖 Scene Intent）
    subconscious_results = await _generate_subconscious_batch(
        beats=beats,
        scene_intent_results=scene_intent_results,
        chapter=chapter,
        entities=entities,
        api_key=api_key,
        base_url=base_url,
        model=reasoning_model,
    )
    
    print(f"[Draft Stage] 步骤 A 完成，耗时 {time.perf_counter() - step_a_start:.2f}s")
    
    # ========================================================================
    # 步骤 B: 串行滑动窗口生成正文（Rolling Prefix）
    # ========================================================================
    print("[Draft Stage] 步骤 B: 串行生成正文（Rolling Prefix）...")
    step_b_start = time.perf_counter()
    
    prose_results = await _generate_prose_serial(
        beats=beats,
        scene_intent_results=scene_intent_results,
        subconscious_results=subconscious_results,
        chapter=chapter,
        book=book,
        entities=entities,
        relationships=relationships,
        api_key=api_key,
        base_url=base_url,
        model=creative_model,
        word_count=word_count,
        previous_summary=previous_summary,
        relevant_memories=relevant_memories,
        locations=locations,
        enable_qc=enable_qc,
    )
    
    print(f"[Draft Stage] 步骤 B 完成，耗时 {time.perf_counter() - step_b_start:.2f}s")
    
    # ========================================================================
    # 组装结果
    # ========================================================================
    results: List[BeatDraftResult] = []
    for i, beat in enumerate(beats):
        beat_id = str(beat.get("beat_id", f"beat-{i+1}"))
        result = BeatDraftResult(
            beat_id=beat_id,
            beat_index=i + 1,
            scene_intent=scene_intent_results[i],
            subconscious_thought=subconscious_results[i],
            draft_chunk=prose_results[i]["text"],
            prompts=prose_results[i]["prompts"],
        )
        results.append(result)
    
    print(f"[Draft Stage] 混合流水线完成，总耗时 {time.perf_counter() - stage_start:.2f}s")
    return results


async def _generate_scene_intent_batch(
    beats: List[dict],
    chapter: Any,
    open_hooks: List[dict],
    api_key: str,
    base_url: str,
    model: str,
) -> List[dict]:
    """
    步骤 A-1: 批量并行生成 Scene Intent。
    
    Scene Intent 是轻量级的逻辑分析，包含场景目标、风险、约束。
    所有 Beat 的 Scene Intent 可以安全并行生成（无文本依赖）。
    
    Args:
        beats: 节拍数据列表
        chapter: 章节实体
        open_hooks: 开放伏笔列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
    
    Returns:
        List[dict]: 按 Beat 顺序排列的 Scene Intent 结果列表
    """
    async def _single_scene_intent(beat: dict, beat_index: int) -> dict:
        """生成单个 Beat 的 Scene Intent。"""
        try:
            # 构建该 Beat 关联的 hooks
            beat_hook_ids = set(beat.get("hook_ids", []))
            beat_hooks = []
            if beat_hook_ids:
                beat_hooks = [
                    item for item in open_hooks
                    if item.get("hook_id") in beat_hook_ids or item.get("ledger_key") in beat_hook_ids
                ]
            if not beat_hooks and beat_index == 1:
                beat_hooks = open_hooks[:2] if len(open_hooks) >= 2 else open_hooks
            
            system_prompt, user_prompt = build_scene_intent_prompt(
                chapter=chapter,
                beat=beat,
                open_hooks=beat_hooks,
            )
            
            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                response_format={"type": "json_object"},
                max_tokens=600,
            )
            
            scene_intent = parse_scene_intent_result(response, beat.get("summary", ""))
            return scene_intent
            
        except Exception as e:
            print(f"[Scene Intent Error] Beat {beat_index}: {e}")
            # 返回默认的 Scene Intent
            return {
                "intent_label": "推进剧情",
                "goal": beat.get("summary", "推进剧情"),
                "stakes": None,
                "constraints": [],
                "sensory_translation_rule": None,
            }
    
    # 并行生成所有 Scene Intent
    tasks = [
        _single_scene_intent(beat, i + 1)
        for i, beat in enumerate(beats)
    ]
    
    results = await asyncio.gather(*tasks)
    return list(results)


async def _generate_subconscious_batch(
    beats: List[dict],
    scene_intent_results: List[dict],
    chapter: Any,
    entities: List[Any],
    api_key: str,
    base_url: str,
    model: str,
) -> List[str]:
    """
    步骤 A-2: 批量并行生成 Subconscious（潜意识层）。
    
    Subconscious 是 50-100 字的第一人称内心独白，为后续 Prose 生成提供情感锚点。
    所有 Beat 的 Subconscious 可以安全并行生成（依赖 Scene Intent，但不依赖其他 Beat 的文本）。
    
    Args:
        beats: 节拍数据列表
        scene_intent_results: 对应的 Scene Intent 结果列表
        chapter: 章节实体
        entities: 角色实体列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
    
    Returns:
        List[str]: 按 Beat 顺序排列的潜意识独白列表
    """
    async def _single_subconscious(beat: dict, scene_intent: dict, beat_index: int) -> str:
        """生成单个 Beat 的 Subconscious。"""
        try:
            system_prompt, user_prompt = build_subconscious_prompt(
                chapter=chapter,
                beat=beat,
                scene_intent=scene_intent,
                entities=entities,
            )
            
            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.6,  # 略高于 Scene Intent，允许更多情感波动
                max_tokens=200,
            )
            
            # 清理输出，确保 50-100 字范围
            thought = clean_llm_output(response).strip()
            # 限制长度在 50-150 字之间
            if len(thought) > 150:
                thought = thought[:147] + "..."
            if len(thought) < 20:
                thought = f"{thought}... 内心的紧张感在蔓延。"
            
            return thought
            
        except Exception as e:
            print(f"[Subconscious Error] Beat {beat_index}: {e}")
            # 返回默认的内心独白
            pov_character = beat.get("pov_character", "我")
            return f"{pov_character}深吸一口气，试图平复内心的波动。接下来该怎么办？"
    
    # 并行生成所有 Subconscious
    tasks = [
        _single_subconscious(beat, scene_intent_results[i], i + 1)
        for i, beat in enumerate(beats)
    ]
    
    results = await asyncio.gather(*tasks)
    return list(results)


async def _generate_prose_serial(
    beats: List[dict],
    scene_intent_results: List[dict],
    subconscious_results: List[str],
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    relevant_memories: Optional[List[Any]] = None,
    locations: Optional[List[Any]] = None,
    enable_qc: bool = True,
) -> List[dict]:
    """
    步骤 B: 串行滑动窗口生成正文（Rolling Prefix 机制）。
    
    核心机制：
    - Beat 1: 基于 Subconscious_1 生成 Prose_1，提取末尾 300 字符作为 Tail_1
    - Beat 2: 基于 Subconscious_2 + Tail_1 生成 Prose_2，提取末尾 300 字符作为 Tail_2
    - Beat N: 基于 Subconscious_N + Tail_(N-1) 生成 Prose_N
    
    公式: Context_n = Subconscious_n + LastTail_(n-1)
    
    Args:
        beats: 节拍数据列表
        scene_intent_results: Scene Intent 结果列表
        subconscious_results: Subconscious 结果列表
        chapter: 章节实体
        book: 书籍实体
        entities: 角色实体列表
        relationships: 角色关系列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        word_count: 目标总字数
        previous_summary: 上一章摘要
        relevant_memories: RAG 相关记忆
        locations: 地图地点列表
        enable_qc: 是否启用质检
    
    Returns:
        List[dict]: 按 Beat 顺序排列的结果列表，每项包含 {"text": str, "prompts": list}
    """
    results: List[dict] = []
    previous_tail = ""  # Rolling Prefix：存储上一个 Beat 的末尾文本
    
    for i, beat in enumerate(beats):
        beat_index = i + 1
        beat_id = str(beat.get("beat_id", f"beat-{beat_index}"))
        
        try:
            # 计算目标字数
            target_words = beat.get("word_count_target")
            if not isinstance(target_words, int) or target_words <= 0:
                target_words = beat.get("target_words", max(200, word_count // max(1, len(beats))))
            
            # 构建 Prose Draft Prompt（极简输入）
            system_prompt, user_prompt = build_prose_draft_prompt(
                chapter=chapter,
                book=book,
                beat=beat,
                scene_intent=scene_intent_results[i],
                subconscious_thought=subconscious_results[i],
                previous_tail=previous_tail,
                target_words=target_words,
            )
            
            prompts_history = [{
                "stage": "PROSE_DRAFT",
                "beat_index": beat_index,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }]
            
            print(f"[Prose Draft] Beat {beat_index}/{len(beats)} 开始生成...")
            prose_start = time.perf_counter()
            
            # 生成正文
            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.75,  # 比原来略高，增强创意
                max_tokens=_clamp_tokens(target_words),
            )
            
            prose_text = clean_llm_output(response).strip()
            print(f"[Prose Draft] Beat {beat_index} 完成，耗时 {time.perf_counter() - prose_start:.2f}s，字数 {len(prose_text)}")
            
            # 可选：自动质检与修复
            if enable_qc:
                prose_text, qc_prompts = await _quick_qc(
                    prose_text=prose_text,
                    beat=beat,
                    beat_index=beat_index,
                    chapter=chapter,
                    book=book,
                    entities=entities,
                    relationships=relationships,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    target_words=target_words,
                )
                prompts_history.extend(qc_prompts)
            
            # 提取末尾 300 字符作为下一个 Beat 的 Rolling Prefix
            previous_tail = _extract_tail(prose_text, max_chars=300)
            
            results.append({
                "text": prose_text,
                "prompts": prompts_history,
            })
            
        except Exception as e:
            print(f"[Prose Draft Error] Beat {beat_index}: {e}")
            # 返回空文本，但保持 Rolling Prefix 不变（尝试用上一个 tail 继续）
            results.append({
                "text": "",
                "prompts": [],
            })
    
    return results


async def _quick_qc(
    prose_text: str,
    beat: dict,
    beat_index: int,
    chapter: Any,
    book: Any,
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    target_words: int,
) -> tuple[str, List[dict]]:
    """
    快速质检与修复。
    
    触发条件：
    - 字数异常：生成内容 < 目标字数的 50%
    - 结构异常：长文本但无段落分隔（\n\n）
    
    Args:
        prose_text: 待质检的文本
        beat: Beat 数据
        beat_index: Beat 索引
        chapter: 章节实体
        book: 书籍实体
        entities: 角色实体列表
        relationships: 角色关系列表
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 模型名称
        target_words: 目标字数
    
    Returns:
        tuple[str, List[dict]]: (修复后的文本, QC 阶段提示词历史)
    """
    prompts = []
    
    # 异常检测
    compact_text = prose_text.replace("\n", "").replace(" ", "")
    has_abnormal_length = len(compact_text) < max(120, int(target_words * 0.5))
    has_abnormal_structure = ("\n\n" not in prose_text) and len(prose_text) > 500
    
    if not has_abnormal_length and not has_abnormal_structure:
        return prose_text, prompts
    
    print(f"[QC] Beat {beat_index} 检测到异常，开始修复...")
    
    try:
        # 构建 Review Prompt
        review_system, review_user = build_chunk_review_prompt(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beat_summary=beat.get("summary", ""),
            chunk_text=prose_text,
        )
        
        prompts.append({
            "stage": "CHUNK_REVIEW",
            "beat_index": beat_index,
            "system_prompt": review_system,
            "user_prompt": review_user,
        })
        
        review_response = await call_llm(
            system_prompt=review_system,
            user_prompt=review_user,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.1,
            response_format={"type": "json_object"},
            max_tokens=800,
        )
        
        import json
        try:
            review_result = json.loads(clean_llm_output(review_response))
        except json.JSONDecodeError:
            return prose_text, prompts
        
        if review_result.get("pass", True):
            return prose_text, prompts
        
        # 需要修复
        instruction = review_result.get("revision_instruction", "")
        if not instruction:
            issues = review_result.get("issues", [])
            instruction = "; ".join(issues) if issues else "修正文本质量问题"
        
        print(f"[QC] Beat {beat_index} 修复指令: {instruction[:50]}...")
        
        # 构建 Refine Prompt
        refine_system, refine_user = build_chunk_refine_prompt(
            chapter=chapter,
            book=book,
            entities=entities,
            relationships=relationships,
            beat_summary=beat.get("summary", ""),
            chunk_text=prose_text,
            revision_instruction=instruction,
        )
        
        prompts.append({
            "stage": "CHUNK_REFINE",
            "beat_index": beat_index,
            "system_prompt": refine_system,
            "user_prompt": refine_user,
        })
        
        refine_response = await call_llm(
            system_prompt=refine_system,
            user_prompt=refine_user,
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.7,
            max_tokens=_clamp_tokens(target_words),
        )
        
        refined_text = clean_llm_output(refine_response).strip()
        print(f"[QC] Beat {beat_index} 修复完成，新字数 {len(refined_text)}")
        
        return refined_text, prompts
        
    except Exception as e:
        print(f"[QC Error] Beat {beat_index}: {e}")
        return prose_text, prompts


def _extract_tail(text: str, max_chars: int = 300) -> str:
    """
    提取文本末尾指定长度的内容，作为 Rolling Prefix。
    
    策略：
    - 如果文本长度 <= max_chars，返回全文
    - 如果文本长度 > max_chars，从最后一个段落边界截取
    - 确保截取的内容语义完整（不从句子中间切断）
    
    Args:
        text: 原始文本
        max_chars: 最大字符数（默认 300）
    
    Returns:
        str: 末尾文本片段
    """
    if not text:
        return ""
    
    if len(text) <= max_chars:
        return text
    
    # 尝试从段落边界截取
    paragraphs = text.split("\n\n")
    tail_parts = []
    current_length = 0
    
    # 从后向前收集段落
    for para in reversed(paragraphs):
        if current_length + len(para) + 2 > max_chars:
            # 如果加上这个段落会超长度，尝试只加一部分
            remaining = max_chars - current_length
            if remaining > 50:  # 至少还有 50 字符空间
                # 尝试在句子边界切断
                sentences = para.split("。")
                partial = ""
                for sent in reversed(sentences):
                    if len(partial) + len(sent) + 1 <= remaining:
                        partial = sent + "。" + partial if partial else sent + "。"
                    else:
                        break
                if partial:
                    tail_parts.insert(0, partial)
            break
        tail_parts.insert(0, para)
        current_length += len(para) + 2
    
    result = "\n\n".join(tail_parts)
    
    # 如果还是太长，强制截断
    if len(result) > max_chars:
        result = result[-max_chars:]
        # 确保不从句子中间切断（简单策略：找到最近的句号）
        first_period = result.find("。")
        if first_period > 0 and first_period < 50:  # 如果句号在前50字符内
            result = result[first_period + 1:]
    
    return result.strip()


def _clamp_tokens(target_words: int) -> int:
    """
    根据目标字数计算合理的 max_tokens。
    
    中文字符与 token 的大致比例约为 1:1.5，这里使用安全系数。
    
    Args:
        target_words: 目标字数
    
    Returns:
        int: 建议的 max_tokens 值
    """
    # 中文字数 -> tokens 估算：乘以 2 作为安全系数
    estimated_tokens = int(target_words * 2)
    # 限制在合理范围内
    return max(1200, min(estimated_tokens, 5200))


# ========================================================================
# 兼容性保留：原有的并行生成函数
# ========================================================================

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
    """
    【兼容性保留】并行生成多个故事节拍的正文片段。
    
    警告：此函数为旧版实现，使用完全并行的方式生成，可能导致 Beat 间语气不连贯。
    新项目请使用 execute_draft_stage。
    
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
    from backend.services.prompts import build_chunk_draft_prompt
    
    async def process_single_beat(beat_index: int, beat: dict, story_beat: Any) -> tuple[int, str]:
        """处理单个节拍的生成流程。"""
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
        """构建节拍关联的伏笔上下文。"""
        beat_hook_ids = set(beat.get("hook_ids", []))
        if beat_hook_ids:
            return [
                item for item in all_hooks
                if item.get("hook_id") in beat_hook_ids or item.get("ledger_key") in beat_hook_ids
            ]
        if beat_index == 1:
            return all_hooks[:2] if len(all_hooks) >= 2 else all_hooks
        return []
    
    def _build_context_summaries(beat_index: int, beats: List[dict], total_beats: int) -> dict:
        """构建前后节拍的摘要上下文。"""
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

from fastapi import APIRouter, HTTPException
import logging
import json
from backend.schemas import CritiqueRequest, CritiqueResponse
from backend.services.chapter_generation import call_llm
from backend.services.prompts.critique_prompts import build_critique_system_prompt, build_critique_user_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["critique"])

@router.post("/critique_chapter", response_model=CritiqueResponse)
async def critique_chapter(request: CritiqueRequest):
    """章节审阅 API - 为作者提供毒舌编辑视角的审阅报告

    这是一个纯粹基于文本内容的审阅，不需要复杂的数据库上下文。
    直接接收前端传入的章节内容进行分析。
    """
    
    system_prompt = build_critique_system_prompt()
    user_prompt = build_critique_user_prompt(request.chapter_content, request.chapter_title)
    
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            logger.info(f"开始生成审阅报告，尝试 {attempt + 1}/{max_retries}")
            
            # 使用流式输出或者非流式输出
            # 这里参考 inspiration.py 使用 call_llm，非流式
            raw_content = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=request.api_key,
                base_url=request.base_url,
                model=request.model,
                temperature=request.temperature,
                top_p=0.9,
                max_tokens=2048,
                response_format={"type": "json_object"}
            )
            
            if not raw_content:
                raise ValueError("LLM 返回空内容")
                
            try:
                # 解析 JSON 响应
                data = json.loads(raw_content)
                return CritiqueResponse(**data)
            except json.JSONDecodeError:
                logger.error(f"LLM 返回的内容不是有效的 JSON: {raw_content[:200]}...")
                raise ValueError("LLM 返回的内容无法解析为 JSON")
            
        except Exception as e:
            logger.error(f"生成审阅报告失败 (尝试 {attempt + 1}/{max_retries}): {e}", exc_info=True)
            last_error = e
            if attempt < max_retries - 1:
                import asyncio
                await asyncio.sleep(1 * (attempt + 1))
                continue
                
    logger.error(f"生成审阅报告最终失败: {last_error}")
    raise HTTPException(status_code=500, detail=f"生成审阅报告失败: {last_error}")

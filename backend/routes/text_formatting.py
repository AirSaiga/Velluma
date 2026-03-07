"""
文本格式整理路由模块。

职责：提供文本格式智能整理 API，用于优化 AI 生成内容的段落结构、标点符号、空行等。

业务场景：
- AI 生成内容格式混乱时的自动整理
- 用户手动输入后的格式规范化
- 导出前的最终排版

设计意图：使用 LLM 进行格式整理，相比规则引擎更能理解语义并做出合理分段。
"""

from fastapi import APIRouter, HTTPException
from backend.schemas import FormatTextRequest
from backend.services.llm_client import format_text_with_llm

router = APIRouter(prefix="/api", tags=["text_formatting"])


@router.post("/format_text")
async def format_text(request: FormatTextRequest):
    """智能整理文本格式（分段、标点、空格等）。

    业务目的：将原始文本整理为符合阅读习惯的格式，包括：
    - 合理分段（避免过长或过短段落）
    - 标点规范化（引号、书名号等）
    - 空格统一（全角/半角标准化）
    - 段落首行缩进处理

    参数来源：
    - request.text: 待整理的原始文本
    - request.api_key: LLM API 密钥（前端传入）

    数据流：
    1. 接收原始文本
    2. 调用 LLM 进行格式整理
    3. 返回整理后的文本

    副作用：
    - 不修改数据库，仅返回处理结果
    - LLM 调用会产生费用

    边界处理：
    - 空文本直接返回空字符串，避免无意义 API 调用

    权衡点 vs 规则引擎：
    - LLM 方案成本较高但效果更好，能理解语义
    - 规则引擎成本低但效果有限
    - 当前选择 LLM 方案保证输出质量
    """
    if not request.text.strip():
        return {"formatted_text": ""}
        
    formatted_text = await format_text_with_llm(
        text=request.text,
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model,
    )
    return {"formatted_text": formatted_text}

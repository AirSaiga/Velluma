"""
灵感生成服务模块

职责：
- 封装灵感生成所需的上下文数据加载逻辑
- 提供标准化的灵感生成功能
- 处理灵感数据的解析和验证

设计原则：
- 单一职责：灵感生成相关逻辑集中管理
- 可复用：可被多个路由/服务共享
- 错误处理：提供清晰的错误信息和重试机制
"""

import json
import logging
import asyncio
from typing import List, Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, Character, PlotLedger, PlotLedgerStatus, ChapterMapLocation
from backend.services.llm_client import call_llm
from backend.services.prompts.inspiration_prompts import build_inspiration_agent_prompt
from backend.services.logging_utils import ServiceLogger, LOG_PREFIX_WORKFLOW

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)


# =============================================================================
# 数据模型
# =============================================================================

class InspirationContext:
    """灵感生成上下文数据容器"""
    
    def __init__(
        self,
        worldview_summary: str,
        recent_context: str,
        characters_brief: str,
        open_hooks_text: str,
        location_context: str,
        current_chapter_context: str,
    ):
        self.worldview_summary = worldview_summary
        self.recent_context = recent_context
        self.characters_brief = characters_brief
        self.open_hooks_text = open_hooks_text
        self.location_context = location_context
        self.current_chapter_context = current_chapter_context


class InspirationItem:
    """灵感条目"""
    
    def __init__(
        self,
        idea_type: str,
        title: str,
        description: str,
        impact: str,
    ):
        self.idea_type = idea_type
        self.title = title
        self.description = description
        self.impact = impact
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "idea_type": self.idea_type,
            "title": self.title,
            "description": self.description,
            "impact": self.impact,
        }


# =============================================================================
# 上下文加载函数
# =============================================================================

async def load_inspiration_context(
    db: AsyncSession,
    book_id: str,
    chapter_id: str,
    active_character_ids: Optional[List[str]] = None,
) -> Optional[InspirationContext]:
    """
    加载灵感生成所需的上下文数据
    
    Args:
        db: 数据库会话
        book_id: 书籍 ID
        chapter_id: 章节 ID
        active_character_ids: 活跃角色 ID 列表
        
    Returns:
        InspirationContext 或 None（如果书籍/章节不存在）
    """
    # 加载书籍
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        return None
    
    # 加载章节
    chapter_result = await db.execute(select(Chapter).where(Chapter.id == chapter_id))
    chapter = chapter_result.scalar_one_or_none()
    if not chapter:
        return None
    
    # 构建世界观摘要
    worldview_summary = _build_worldview_summary(book)
    
    # 加载前文上下文
    recent_context = await _load_recent_context(db, book_id, chapter.chapter_number)
    
    # 加载当前章节上下文
    current_chapter_context = _build_current_chapter_context(chapter)
    
    # 加载角色简介
    characters_brief = await _load_characters_brief(db, active_character_ids)
    
    # 加载伏笔信息
    open_hooks_text = await _load_hooks_context(db, book_id)
    
    # 加载地点信息
    location_context = await _load_location_context(db, chapter_id)
    
    return InspirationContext(
        worldview_summary=worldview_summary,
        recent_context=recent_context,
        characters_brief=characters_brief,
        open_hooks_text=open_hooks_text,
        location_context=location_context,
        current_chapter_context=current_chapter_context,
    )


def _build_worldview_summary(book: Book) -> str:
    """构建世界观摘要"""
    worldview_summary = ""
    if book.worldview_settings:
        settings = book.worldview_settings
        if isinstance(settings, dict):
            genre = settings.get("genre", "")
            timeline = settings.get("timeline", "")
            rules = settings.get("rules", "")
            locations = settings.get("locations", "")
            worldview_summary = f"题材类型：{genre}\n时间线：{timeline}\n世界规则：{rules}\n主要地点：{locations}"
    if book.global_sys_prompt:
        worldview_summary += f"\n全局设定：{book.global_sys_prompt[:500]}"
    if not worldview_summary:
        worldview_summary = "（暂无详细世界观设定）"
    return worldview_summary


async def _load_recent_context(db: AsyncSession, book_id: str, current_chapter_number: int) -> str:
    """加载前文上下文"""
    prev_chapters_result = await db.execute(
        select(Chapter)
        .where(
            Chapter.book_id == book_id,
            Chapter.chapter_number < current_chapter_number
        )
        .order_by(Chapter.chapter_number.desc())
        .limit(1)
    )
    prev_chapter = prev_chapters_result.scalar_one_or_none()
    
    if not prev_chapter:
        return "（暂无前情提要）"
    
    context_parts = []
    ch_title = f"第{prev_chapter.chapter_number}章"
    if prev_chapter.outline_text:
        context_parts.append(f"{ch_title}大纲：{prev_chapter.outline_text[:300]}")
    if prev_chapter.content_text:
        context_parts.append(f"{ch_title}结尾：{prev_chapter.content_text[-300:]}")
    if prev_chapter.summary:
        context_parts.append(f"{ch_title}摘要：{prev_chapter.summary[:200]}")
    
    return "\n".join(context_parts) if context_parts else "（暂无前情提要）"


def _build_current_chapter_context(chapter: Chapter) -> str:
    """构建当前章节上下文"""
    context_parts = []
    if chapter.outline_text:
        context_parts.append(f"当前本章已有大纲：{chapter.outline_text[:500]}")
    if chapter.content_text and len(chapter.content_text) > 50:
        content_preview = chapter.content_text[-300:]
        context_parts.append(f"当前本章正文已写：{content_preview}")
    
    return "\n".join(context_parts) if context_parts else ""


async def _load_characters_brief(
    db: AsyncSession,
    active_character_ids: Optional[List[str]]
) -> str:
    """加载角色简介"""
    if not active_character_ids:
        return "（当前场景暂无指定角色）"
    
    char_ids = [cid for cid in active_character_ids if cid]
    if not char_ids:
        return "（当前场景暂无指定角色）"
    
    try:
        uuid_char_ids = [UUID(cid) for cid in char_ids]
    except ValueError:
        return "（角色 ID 格式错误）"
    
    char_result = await db.execute(
        select(Character).where(Character.id.in_(uuid_char_ids))
    )
    characters = char_result.scalars().all()
    
    if not characters:
        return "（当前场景暂无指定角色）"
    
    char_lines = []
    for char in characters:
        brief = char.static_prompt[:100] if char.static_prompt else "暂无设定"
        char_lines.append(f"- {char.name}: {brief}")
    
    return "\n".join(char_lines)


async def _load_hooks_context(db: AsyncSession, book_id: str) -> str:
    """加载伏笔上下文"""
    hooks_result = await db.execute(
        select(PlotLedger)
        .where(PlotLedger.book_id == book_id)
        .order_by(PlotLedger.created_at.desc())
        .limit(20)
    )
    all_hooks = hooks_result.scalars().all()
    
    if not all_hooks:
        return "（暂无伏笔记录）"
    
    open_hooks = [h for h in all_hooks if h.status == PlotLedgerStatus.OPEN.value]
    recent_hooks = all_hooks[:10]
    hooks_to_show = open_hooks[:10] if len(open_hooks) >= 10 else (open_hooks + recent_hooks[:10 - len(open_hooks)])
    
    hook_lines = []
    for hook in hooks_to_show:
        status_tag = "[未解决]" if hook.status == PlotLedgerStatus.OPEN.value else "[已解决]"
        hook_lines.append(f"- {hook.ledger_key} {status_tag}: {hook.content[:80]}")
    
    return "\n".join(hook_lines)


async def _load_location_context(db: AsyncSession, chapter_id: str) -> str:
    """加载地点上下文"""
    chapter_locations_result = await db.execute(
        select(ChapterMapLocation)
        .where(ChapterMapLocation.chapter_id == chapter_id)
        .options(selectinload(ChapterMapLocation.location))
    )
    chapter_locations = chapter_locations_result.scalars().all()
    
    if not chapter_locations:
        return ""
    
    location_names = []
    for cl in chapter_locations:
        if cl.location:
            location_names.append(cl.location.name)
    
    if location_names:
        return f"本章涉及地点：{', '.join(location_names)}"
    return ""


# =============================================================================
# 灵感生成核心函数
# =============================================================================

async def generate_inspirations(
    context: InspirationContext,
    chapter_title: str,
    api_key: str,
    base_url: Optional[str],
    model: str,
    temperature: float = 0.9,
    global_taboos: Optional[str] = None,
    author_intent: Optional[str] = None,
    max_retries: int = 3,
) -> List[InspirationItem]:
    """
    生成灵感列表
    
    Args:
        context: 灵感生成上下文
        chapter_title: 章节标题
        api_key: API Key
        base_url: Base URL
        model: 模型名称
        temperature: 温度参数
        global_taboos: 全局禁忌/核心设定
        author_intent: 作者意图
        max_retries: 最大重试次数
        
    Returns:
        灵感条目列表
        
    Raises:
        ValueError: 如果生成失败或返回数据格式错误
    """
    # 构建 Prompt
    prompt_messages = build_inspiration_agent_prompt(
        worldview_summary=context.worldview_summary,
        recent_context=context.recent_context,
        characters_brief=context.characters_brief,
        open_hooks=context.open_hooks_text,
        location_context=context.location_context,
        current_chapter_context=context.current_chapter_context,
        chapter_title=chapter_title,
        global_taboos=global_taboos,
        author_intent=author_intent,
    )
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            svc_logger.info("Starting inspiration generation", attempt=attempt + 1, max_retries=max_retries)
            
            raw_content = await call_llm(
                system_prompt=prompt_messages[0]["content"],
                user_prompt=prompt_messages[1]["content"],
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                top_p=0.9,
                response_format={"type": "json_object"},
                max_tokens=2048,
            )
            
            if not raw_content:
                raise ValueError("LLM 返回空内容")
            
            return _parse_inspiration_response(raw_content)
            
        except Exception as e:
            svc_logger.error(
                "Inspiration generation failed",
                attempt=attempt + 1,
                max_retries=max_retries,
                error=str(e)
            )
            last_error = e
            
            if attempt < max_retries - 1:
                wait_time = 1 * (attempt + 1)
                await asyncio.sleep(wait_time)
                continue
    
    raise ValueError(f"生成灵感失败，已重试 {max_retries} 次: {last_error}")


def _parse_inspiration_response(raw_content: str) -> List[InspirationItem]:
    """
    解析灵感生成的响应内容
    
    Args:
        raw_content: LLM 返回的原始 JSON 字符串
        
    Returns:
        灵感条目列表
        
    Raises:
        ValueError: 如果解析失败或数据格式错误
    """
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 解析失败: {e}")
    
    # 提取灵感数据
    inspirations_data: List[Dict] = []
    if isinstance(data, list):
        inspirations_data = data
    elif isinstance(data, dict):
        inspirations_data = data.get("inspirations", [])
        if not inspirations_data or len(inspirations_data) < 3:
            inspirations_data = data.get("ideas", []) or data.get("results", []) or []
    else:
        raise ValueError(f"LLM 返回了不支持的 JSON 结构: {type(data)}")
    
    # 过滤非字典项
    inspirations_data = [item for item in inspirations_data if isinstance(item, dict)]
    
    if len(inspirations_data) < 4:
        raise ValueError(f"返回的有效灵感数量不足：{len(inspirations_data)}")
    
    # 限制数量并转换为 InspirationItem
    inspirations_data = inspirations_data[:4]
    inspirations = []
    
    for item in inspirations_data:
        idea_type = item.get("idea_type", "plot_twist")
        if idea_type not in ["plot_twist", "key_conflict", "new_hook", "smooth_narrative"]:
            idea_type = "plot_twist"
        
        inspirations.append(InspirationItem(
            idea_type=idea_type,
            title=item.get("title", "未命名点子"),
            description=item.get("description", ""),
            impact=item.get("impact", ""),
        ))
    
    return inspirations

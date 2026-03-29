"""
灵感服务模块。

职责：提供灵感/大纲扩展相关的 LLM 调用逻辑。

主要功能：
- 扩展写作灵感
- 扩展章节大纲

使用场景：
- routes/inspiration.py: 灵感路由调用
"""

import json
from typing import Optional, List, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Book, Chapter, Character, PlotLedger
from backend.services.llm import call_llm


class InspirationContext:
    """灵感生成上下文"""

    def __init__(
        self,
        book: Book,
        current_chapter: Optional[Chapter],
        previous_chapter: Optional[Chapter],
        characters: List[Character],
        open_hooks: List[Any],
    ):
        self.book = book
        self.current_chapter = current_chapter
        self.previous_chapter = previous_chapter
        self.characters = characters
        self.open_hooks = open_hooks


class InspirationItem:
    """灵感项"""

    def __init__(
        self,
        idea: str,
        character: Optional[str] = None,
        type: str = "plot",
        trigger: Optional[str] = None,
    ):
        self.idea = idea
        self.character = character
        self.type = type
        self.trigger = trigger

    def to_dict(self) -> dict:
        return {
            "idea": self.idea,
            "character": self.character,
            "type": self.type,
            "trigger": self.trigger,
        }


async def load_inspiration_context(
    db: AsyncSession,
    book_id: str,
    chapter_id: Optional[str] = None,
    active_character_ids: Optional[List[str]] = None,
) -> Optional[InspirationContext]:
    """
    加载灵感生成的上下文。

    Args:
        db: 数据库会话
        book_id: 书籍 ID
        chapter_id: 章节 ID（可选）
        active_character_ids: 活跃角色 ID 列表

    Returns:
        灵感上下文或 None
    """
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        return None

    current_chapter = None
    previous_chapter = None
    if chapter_id:
        chapter_result = await db.execute(
            select(Chapter)
            .options(selectinload(Chapter.story_beats))
            .where(Chapter.id == chapter_id)
        )
        current_chapter = chapter_result.scalar_one_or_none()

        if current_chapter and current_chapter.chapter_number > 1:
            prev_result = await db.execute(
                select(Chapter)
                .where(
                    Chapter.book_id == book_id,
                    Chapter.chapter_number == current_chapter.chapter_number - 1
                )
            )
            previous_chapter = prev_result.scalar_one_or_none()

    characters = []
    if active_character_ids:
        char_result = await db.execute(
            select(Character).where(Character.id.in_(active_character_ids))
        )
        characters = list(char_result.scalars().all())
    else:
        char_result = await db.execute(select(Character).where(Character.book_id == book_id))
        characters = list(char_result.scalars().all())

    hooks_result = await db.execute(
        select(PlotLedger)
        .where(
            PlotLedger.book_id == book_id,
            PlotLedger.status == "open"
        )
    )
    open_hooks = list(hooks_result.scalars().all())

    return InspirationContext(
        book=book,
        current_chapter=current_chapter,
        previous_chapter=previous_chapter,
        characters=characters,
        open_hooks=open_hooks,
    )


async def generate_inspirations(
    context: InspirationContext,
    chapter_title: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.9,
    global_taboos: Optional[str] = None,
    author_intent: Optional[str] = None,
) -> List[InspirationItem]:
    """
    生成灵感列表。

    Args:
        context: 灵感上下文
        chapter_title: 章节标题
        api_key: API Key
        base_url: Base URL
        model: 模型名称
        temperature: 温度参数
        global_taboos: 全局禁忌
        author_intent: 作者意图

    Returns:
        灵感列表
    """
    characters_text = "\n".join(
        [f"- {c.name}: {c.static_prompt or '暂无设定'}" for c in context.characters[:5]]
    )

    hooks_text = ""
    if context.open_hooks:
        hooks_text = "【开放伏笔】\n" + "\n".join(
            [f"- {h.content}" for h in context.open_hooks[:5]]
        )

    summary_text = ""
    if context.previous_chapter:
        summary_text = context.previous_chapter.summary or context.previous_chapter.content_text or ""
        if len(summary_text) > 500:
            summary_text = summary_text[:500] + "..."

    system_prompt = """你是一个专业的小说创作灵感助手。你的任务是基于给定的上下文，生成3-5个创意性的后续剧情灵感。

每个灵感应该包含：
1. idea: 灵感描述（100-200字）
2. character: 涉及的主要角色
3. type: 灵感类型（plot/character/setting/twist）
4. trigger: 触发条件（可选）

请确保灵感：
- 具有创意性和戏剧性
- 与前文逻辑连贯
- 不违反全局禁忌
- 能够推动剧情发展"""

    user_prompt = f"""【书籍信息】
书名：{context.book.title or '未命名'}
类型：{context.book.genre or '未知'}

【世界观设定】
{context.book.worldview_settings or '暂无世界观设定'}

【全局禁忌】
{global_taboos or '暂无禁忌'}

【作者意图】
{author_intent or '暂无特定意图'}

【前情提要】
{summary_text or '暂无前情提要'}

【核心角色】
{characters_text or '暂无角色信息'}

{hooks_text if hooks_text else ''}

【当前章节】
{chapter_title or '未命名'}

请生成3-5个创意性的后续剧情灵感：
"""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model or "google/gemini-2.0-flash-001",
            temperature=temperature,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )

        if not response:
            return []

        data = json.loads(response)
        inspirations = data.get("inspirations", [])

        return [
            InspirationItem(
                idea=item.get("idea", ""),
                character=item.get("character"),
                type=item.get("type", "plot"),
                trigger=item.get("trigger"),
            )
            for item in inspirations
            if item.get("idea")
        ]
    except Exception as e:
        return []


async def expand_inspiration(
    user_prompt: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.8,
) -> Optional[dict]:
    """
    扩展写作灵感。

    Args:
        user_prompt: 用户输入的灵感描述
        api_key: API Key
        base_url: Base URL
        model: 模型名称
        max_tokens: 最大 token 数
        temperature: 温度参数

    Returns:
        扩展后的灵感内容字典或 None
    """
    system_prompt = """你是一个创意写作助手。根据用户提供的简短灵感片段，扩展成一个丰富的写作场景。

请生成包含以下要素的扩展内容：
1. 场景设定：时间、地点、环境
2. 主要人物：外貌、性格、心理
3. 冲突萌芽：即将发生的关键事件
4. 悬念钩子：让读者想继续阅读的元素

请以 JSON 格式返回，包含以下字段：
- scene_setting: 场景设定（100-200字）
- main_characters: 主要人物列表（每个100-150字）
- conflict_seed: 冲突萌芽（50-100字）
- hook: 悬念钩子（50-100字）

确保内容具有创意性和文学性。"""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model or "google/gemini-2.0-flash-001",
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        if response:
            return json.loads(response)
        return None
    except Exception as e:
        return None


async def expand_outline(
    user_prompt: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> Optional[str]:
    """
    扩展章节大纲。

    Args:
        user_prompt: 用户输入的大纲描述
        api_key: API Key
        base_url: Base URL
        model: 模型名称
        max_tokens: 最大 token 数
        temperature: 温度参数

    Returns:
        扩展后的大纲文本或 None
    """
    system_prompt = """你是一个专业的小说大纲助手。根据用户提供的简短大纲，扩展成一个结构完整、细节丰富的章节大纲。

请生成包含以下要素的扩展大纲：
1. 章节主题：核心思想和情感基调
2. 情节点：按顺序列出3-5个关键情节点
3. 角色弧线：本章中角色的心理变化
4. 高潮设计：冲突爆发的具体设计
5. 结尾悬念：为下一章埋下的钩子

请用清晰的结构化格式输出，便于后续写作参考。"""

    try:
        response = await call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            api_key=api_key,
            base_url=base_url,
            model=model or "google/gemini-2.0-flash-001",
            temperature=temperature,
            max_tokens=max_tokens,
        )

        return response if response else None
    except Exception as e:
        return None

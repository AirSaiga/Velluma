import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Character, Chapter
from backend.services.llm_client import call_llm

logger = logging.getLogger(__name__)


async def update_character_dynamic_state(
    character: Character,
    chapter: Chapter,
    db: AsyncSession,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
    manual_current_state: Optional[str] = None,
    proxy_enabled: bool = True,
    proxy_url: Optional[str] = None,
) -> dict:
    """
    更新角色动态状态 (角色在特定章节中的心理/情感变化)。

    业务规则：
    1. 动态状态 = 角色当前的心理状态、情感、与其他角色的关系变化
    2. 每次更新记录到 history (最多保留10条)，支持追溯
    3. 仅分析涉及该角色的章节，未出场则不更新
    4. manual_current_state: 若提供，则以此作为"当前状态"进行更新，而非数据库中的值（用于用户手动干预/重试）

    触发条件：
    - 章节生成完成后自动触发 (章节内容已写入 DB)
    - 需要章节的 outline_text 和 content_text 作为分析依据

    数据流：
    - character (ORM对象) + chapter (ORM对象) → LLM 分析 → new_dynamic_state
    - 更新 character.dynamic_state (当前状态)
    - 追加到 character.dynamic_state_history (历史记录)

    权衡：使用 gpt-4o-mini 而非更强模型降低成本，但可能影响分析质量。
    警示：若章节内容为空，LLM 可能产生不准确的推理。
    """

    old_dynamic_state = manual_current_state if manual_current_state is not None else (character.dynamic_state or "暂无动态状态")
    history_states = []
    if character.dynamic_state_history:
        for item in character.dynamic_state_history[-3:]:
            state = item.get("state", "")
            updated_at = item.get("updated_at", "")
            if state:
                history_states.append(f"- {updated_at}: {state}")
    history_str = "\n".join(history_states) if history_states else "暂无历史状态"

    system_prompt = "你是一个专业的小说写作助手，擅长分析角色心理和情感变化。"
    user_prompt = f"""角色动态状态更新提示词：

【角色信息】
角色名：{character.name}
角色设定：{character.static_prompt or "暂无设定"}

【当前动态状态】
{old_dynamic_state}

【历史动态状态】
{history_str}

【本章情节】
章节标题：{chapter.title or "未命名"}
章节大纲：{chapter.outline_text or "暂无大纲"}
章节正文：{chapter.content_text or "暂无正文"}

【任务】
请基于"当前动态状态"，结合"本章情节"中的新发展，更新角色的动态状态描述。

【核心要求】
1. **必须保留**关键身份信息（如年龄、家族、核心能力、职业等），不要丢失上下文。
2. **整合**本章中发生的重大事件、心理变化和人际关系进展。
3. 保持角色性格一致性。
4. 字数控制在 100-200 字之间，内容要充实但精炼。
5. 严禁罗列流水账，侧重于"状态"和"影响"。
6. 直接输出更新后的段落，不要包含"更新后："等前缀。
"""

    new_state = await call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0.7,
        max_tokens=1000,
        proxy_enabled=proxy_enabled,
        proxy_url=proxy_url,
    )

    if new_state:
        llm_content = new_state
        if not llm_content:
            return {}

        new_dynamic_state = llm_content.strip()

        new_dynamic_state = re.sub(r"^[【\[].*?[】\]]\s*", "", new_dynamic_state.strip())
        new_dynamic_state = re.sub(r"^角色动态状态[：:]\s*", "", new_dynamic_state)
        new_dynamic_state = re.sub(r"^更新后的动态状态[：:]\s*", "", new_dynamic_state)
        new_dynamic_state = new_dynamic_state.strip()

        character.dynamic_state = new_dynamic_state
        history = character.dynamic_state_history or []
        history.append({"state": new_dynamic_state, "updated_at": datetime.now(timezone.utc).isoformat()})
        if len(history) > 10:
            history = history[-10:]
        character.dynamic_state_history = history

        await db.commit()
        await db.refresh(character)
        return {"old_dynamic_state": old_dynamic_state, "new_dynamic_state": new_dynamic_state}

    return {}

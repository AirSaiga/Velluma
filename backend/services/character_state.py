import re
from datetime import datetime
from typing import Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Character, Chapter
from backend.services.llm_client import _clear_proxy_env


async def update_character_dynamic_state(
    character: Character,
    chapter: Chapter,
    db: AsyncSession,
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
) -> dict:
    """
    更新角色动态状态 (角色在特定章节中的心理/情感变化)。

    业务规则：
    1. 动态状态 = 角色当前的心理状态、情感、与其他角色的关系变化
    2. 每次更新记录到 history (最多保留10条)，支持追溯
    3. 仅分析涉及该角色的章节，未出场则不更新

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
    import httpx

    # 步骤1：准备历史状态上下文 (最近3条)，帮助 LLM 理解状态演变
    old_dynamic_state = character.dynamic_state or "暂无动态状态"
    history_states = []
    if character.dynamic_state_history:
        for item in character.dynamic_state_history[-3:]:
            state = item.get("state", "")
            updated_at = item.get("updated_at", "")
            if state:
                history_states.append(f"- {updated_at}: {state}")
    history_str = "\n".join(history_states) if history_states else "暂无历史状态"

    # 步骤2：构建分析 prompt，强制输出简洁的动态状态描述
    prompt = f"""角色动态状态更新提示词：

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
请分析上述角色在本章中的表现和状态变化，更新角色的动态状态描述。
要求：
1. 保持角色性格的一致性
2. 描述角色当前的心理状态、情感、与其他角色的关系变化
3. 输出简洁的动态状态描述，字数必须严格控制在 50-150 字之间，严禁超长
4. 严禁罗列剧情流水账，只提取关键状态变化
5. 直接输出更新后的动态状态，不要有额外说明
"""

    # 步骤3：调用 LLM 分析并更新状态
    _clear_proxy_env()
    client_kwargs = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    http_client = httpx.AsyncClient(trust_env=False)
    client_kwargs["http_client"] = http_client
    try:
        client = AsyncOpenAI(**client_kwargs)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个专业的小说写作助手，擅长分析角色心理和情感变化。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1000,
        )
        # 步骤4：后处理 LLM 输出，去除常见的前缀干扰
        new_dynamic_state = response.choices[0].message.content if response.choices else old_dynamic_state
        new_dynamic_state = re.sub(r"^[【\[].*?[】\]]\s*", "", new_dynamic_state.strip())
        new_dynamic_state = re.sub(r"^角色动态状态[：:]\s*", "", new_dynamic_state)
        new_dynamic_state = re.sub(r"^更新后的动态状态[：:]\s*", "", new_dynamic_state)
        new_dynamic_state = new_dynamic_state.strip()

        # 步骤5：更新角色状态并记录历史
        character.dynamic_state = new_dynamic_state
        history = character.dynamic_state_history or []
        history.append({"state": new_dynamic_state, "updated_at": datetime.utcnow().isoformat()})
        # 裁剪历史记录，保持最近10条 (防止无限增长)
        if len(history) > 10:
            history = history[-10:]
        character.dynamic_state_history = history

        await db.commit()
        await db.refresh(character)
        return {"old_dynamic_state": old_dynamic_state, "new_dynamic_state": new_dynamic_state}
    finally:
        await http_client.aclose()

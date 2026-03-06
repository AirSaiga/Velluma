"""
点子启发 Prompt 构建模块

提供轻量级的 Prompt 构建函数，用于生成灵感卡片。
仅加载 4 个支柱上下文：世界观、前情提要、角色简介、开放伏笔。
"""

from typing import List


def build_inspiration_agent_prompt(
    worldview_summary: str,
    recent_context: str,
    characters_brief: str,
    open_hooks: str,
) -> List[dict]:
    """
    构建点子启发 Agent 的 Prompt。

    只加载最少断连的上下文，高 Temperature 调用 LLM，
    强制返回结构化的 JSON 灵感卡片。

    Args:
        worldview_summary: 核心世界观的极简设定摘要
        recent_context: 前情提要/当前在此处的剧情
        characters_brief: 在场核心角色的一句话快照
        open_hooks: 当前未解决的悬念/伏笔列表

    Returns:
        符合 OpenAI messages 格式的列表，包含 system 和 user prompt
    """
    sys_prompt = """你是一位顶尖的网文金牌编辑和剧情规划师。当前作者思路卡壳，需要你提供后续剧情的灵感碎片。

你必须输出符合特定 JSON Schema 的结果，包含 3 个不同维度的剧情点子：

1. plot_twist (剧情转折点)：一个意外的事件走向或外力介入，打破当前的僵局。

2. key_conflict (关键冲突点)：揭示或激化在场角色之间的核心矛盾，推高情绪张力。

3. new_hook (新设伏笔/草蛇灰线)：抛出一个看似不起眼的诡异细节或神秘线索，利用现有伏笔或为未来做铺垫。

格式要求：必须返回合法的 JSON 对象，包含 3 个点子，每个点子包含以下字段：
- idea_type: "plot_twist" | "key_conflict" | "new_hook"
- title: 点子的简短标题
- description: 百字左右的具体事件描述
- impact: 这步棋对后续格局的影响/好处

请严格按照 JSON 格式输出，不要包含任何其他文字。"""

    user_prompt = f"""### 1. 故事基本盘

{worldview_summary}

### 2. 前情提要/当前在此处的剧情

{recent_context}

### 3. 在场核心角色 (快照)

{characters_brief}

### 4. 当前未解决的悬念/伏笔 (Plot Ledger)

{open_hooks}

请根据以上受限的上下文，头脑风暴并输出紧扣这四个支柱的 3 个灵感卡片。不要生成正文对话，只要干练的情节梗概！"""

    return [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]

"""
统稿提示词模块。

职责：提供章节统稿（Stitch）阶段的提示词构建和结果解析功能。

业务场景：
- 将多个并行生成的剧情片段（chunks）融合成连贯的章节正文
- 修复片段之间的连接问题，消除突兀的场景转换
- 统一人称、时态与语气，移除元数据残留

工作流位置：
- 位于 Agentic 工作流的 DRAFTING 阶段之后
- 输入：多个已生成的 chunks、剧情节拍列表、章节大纲
- 输出：融合后的连贯章节正文
"""

from backend.models import Chapter, Book


def build_stitch_prompt(
    chapter: Chapter,
    beats: list[dict],
    chunks: list[str],
    word_count: int,
    anchor_pov: str = None,
    book: Book = None,
) -> tuple[str, str]:
    """构建统稿阶段的提示词。

    将多个并行生成的剧情片段融合成连贯的章节正文。

    Args:
        chapter: 章节实体，包含章节名、大纲等信息
        beats: 剧情节拍列表，每个节拍包含 summary、position 等信息
        chunks: 已生成的文本片段列表
        word_count: 目标字数（保留参数，当前统稿阶段不做字数约束）
        anchor_pov: 主导视角角色名，用于反蒙太奇剪辑规则
        book: 书籍实体，用于获取 style_blacklist 等文风控制数据

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)

    提示词设计说明：
    - system_prompt: 统稿规则，包含融合要求、修复重点、质量标准
    - user_prompt: 具体待统稿的内容，包含章节信息、节拍大纲、原始 chunks
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_lines = [f"{idx + 1}. {beat.get('summary', '')}" for idx, beat in enumerate(beats)]
    chunk_lines = [f"### Chunk {idx + 1}\n{chunk}" for idx, chunk in enumerate(chunks)]

    style_blacklist = []
    if book:
        style_blacklist = getattr(book, 'style_blacklist', None) or []
        if isinstance(style_blacklist, list):
            style_blacklist = [s for s in style_blacklist if s]
        else:
            style_blacklist = []

    blacklist_section = ""
    if style_blacklist:
        blacklist_text = "、".join(style_blacklist)
        blacklist_section = f"\n\n## 黑名单词库约束（最高优先级）\n在平滑缝合各个 Chunk 时，你的原创过渡句绝对不能包含以下黑名单词汇：{blacklist_text}。一旦发现此类词汇，请立即替换为更自然的表达。"

    if anchor_pov:
        system_prompt = f"""你是小说统稿编辑，但现在你是一个**反蒙太奇剪辑师**。你的任务是将多个并行生成的 chunk 融合成单一连续时间线的章节正文。

## 核心剪辑规则（最高优先级）

1. **单一连续时间线**：如果收到的 Chunks 中出现了空间跨越（例如 Chunk A 在地下，Chunk B 切到了天上），你拥有最高剪辑权。你必须抹去非【{anchor_pov}】视角的描写，将其合并为主视角的背景板感知流，确保文章时间线顺滑地流淌，无割裂感。

2. **抹除劣质胶水词**：全文检索并强行删去"与此同时"、"视角回到"、"在这关键时刻"等着相的转场词。用具体的动作和物理状态（如视线偏移、耳边的轰鸣）代替结构性的生硬拼接。

3. **收束去AI味**：去除段落末尾那种尝试总结命运、拔高立意的"旁白说教"。
{blacklist_section}

## 输出要求
- 输出纯文本，不要标题或解释
- 统稿时不设字数上限，不得通过粗暴删段来压缩文本
- 优先保留并融合各 chunk 的有效剧情信息，确保章节结构完整、过渡自然"""
    else:
        system_prompt = f"""你是小说统稿编辑。请将多个并行生成的 chunk 融合成连贯的章节正文。

要求：
1. **重点修复**：检查各 Chunk 之间的连接点，消除任何突兀的场景转换或逻辑断裂。如果前后文不搭，请重写过渡段落。
2. 保持剧情顺序与逻辑连贯。
3. 消除重复信息与风格断裂。
4. 统一人称、时态与语气。
5. 移除任何残留的元数据（如 JSON 标记、Markdown 代码块等）。
6. **抹除劣质胶水词**：全文检索并强行删去"与此同时"、"视角回到"、"在这关键时刻"等着相的转场词。用具体的动作和物理状态（如视线偏移、耳边的轰鸣）代替结构性的生硬拼接。
7. 输出纯文本，不要标题或解释。
8. 统稿时不设字数上限，不得通过粗暴删段来压缩文本。
9. 优先保留并融合各 chunk 的有效剧情信息，确保章节结构完整、过渡自然。{blacklist_section}"""

    user_prompt = f"""请统稿以下内容：

【章节名】{chapter_name}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【Story Beats】
{chr(10).join(beat_lines) if beat_lines else "暂无"}

【Chunks】
{chr(10).join(chunk_lines) if chunk_lines else "暂无"}
"""
    return system_prompt, user_prompt

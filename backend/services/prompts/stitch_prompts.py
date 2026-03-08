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

from backend.models import Chapter


def build_stitch_prompt(
    chapter: Chapter,
    beats: list[dict],
    chunks: list[str],
    word_count: int,
) -> tuple[str, str]:
    """构建统稿阶段的提示词。

    将多个并行生成的剧情片段融合成连贯的章节正文。

    Args:
        chapter: 章节实体，包含章节名、大纲等信息
        beats: 剧情节拍列表，每个节拍包含 summary、position 等信息
        chunks: 已生成的文本片段列表
        word_count: 目标字数

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)

    提示词设计说明：
    - system_prompt: 统稿规则，包含融合要求、修复重点、质量标准
    - user_prompt: 具体待统稿的内容，包含章节信息、节拍大纲、原始 chunks
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_lines = [f"{idx + 1}. {beat.get('summary', '')}" for idx, beat in enumerate(beats)]
    chunk_lines = [f"### Chunk {idx + 1}\n{chunk}" for idx, chunk in enumerate(chunks)]
    system_prompt = f"""你是小说统稿编辑。请将多个并行生成的 chunk 融合成连贯的章节正文。

要求：
1. **重点修复**：检查各 Chunk 之间的连接点，消除任何突兀的场景转换或逻辑断裂。如果前后文不搭，请重写过渡段落。
2. 保持剧情顺序与逻辑连贯。
3. 消除重复信息与风格断裂。
4. 统一人称、时态与语气。
5. 移除任何残留的元数据（如 JSON 标记、Markdown 代码块等）。
6. 输出纯文本，不要标题或解释。
7. **字数说明**：目标字数约 {word_count} 字仅供参考。请优先保证剧情的完整性与流畅度，不要为了凑字数或减字数而牺牲阅读体验。"""
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

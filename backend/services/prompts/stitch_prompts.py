from backend.models import Chapter


def build_stitch_prompt(chapter: Chapter, beats: list[dict], chunks: list[str], word_count: int):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_lines = [f"{idx + 1}. {beat.get('summary', '')}" for idx, beat in enumerate(beats)]
    chunk_lines = [f"### Chunk {idx + 1}\n{chunk}" for idx, chunk in enumerate(chunks)]
    system_prompt = f"""你是小说统稿编辑。请将多个并行生成的 chunk 融合成连贯的章节正文，并保持约 {word_count} 字（±100）。

要求：
1. **重点修复**：检查各 Chunk 之间的连接点，消除任何突兀的场景转换或逻辑断裂。如果前后文不搭，请重写过渡段落。
2. 保持剧情顺序与逻辑连贯。
3. 消除重复信息与风格断裂。
4. 统一人称、时态与语气。
5. 移除任何残留的元数据（如 JSON 标记、Markdown 代码块等）。
6. 输出纯文本，不要标题或解释。"""
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

"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
统稿提示词模块。

职责：提供章节统稿（Stitch）阶段的提示词构建和结果解析功能。

业务场景：
- 将多个并行生成的剧情片段（chunks）融合成连贯的章节正文
- 修复片段之间的连接问题，消除突兀的场景转换
- 统一人称、时态与语气，移除元数据残留
- 双轨模式下参考连贯速写（Sketch）改善过渡连贯性

工作流位置：
- 位于 Agentic 工作流的 DRAFTING 阶段之后
- 输入：多个已生成的 chunks、剧情节拍列表、章节大纲、可选的连贯速写
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
    sketch_text: str = None,
    persistent_state_anchors: list[dict] = None,
    previous_chapter_snapshot: dict = None,
) -> tuple[str, str]:
    """构建统稿阶段的提示词。

    将多个并行生成的剧情片段融合成连贯的章节正文。

    Args:
        chapter: 章节实体，包含章节名、大纲等信息
        beats: 剧情节拍列表，每个节拍包含 summary、position 等信息
        chunks: 已生成的文本片段列表
        word_count: 目标字数，用于字数下限约束
        anchor_pov: 主导视角角色名，用于反蒙太奇剪辑规则
        book: 书籍实体，用于获取 style_blacklist 等文风控制数据
        sketch_text: 连贯速写文本，作为连贯性参考（双轨模式）
        persistent_state_anchors: 持久状态锚点列表，用于跨 Beat 状态平滑 (V3.5)
        previous_chapter_snapshot: 上一章的世界状态快照，用于跨章连续性约束 (V3.5)

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)

    提示词设计说明：
    - system_prompt: 统稿规则，包含融合要求、修复重点、质量标准
    - user_prompt: 具体待统稿的内容，包含章节信息、节拍大纲、原始 chunks
    """
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    beat_lines = [f"{idx + 1}. {beat.get('summary', '')}" for idx, beat in enumerate(beats)]
    chunk_lines = [f"### Chunk {idx + 1}\n{chunk}" for idx, chunk in enumerate(chunks)]

    # 计算 chunks 总字数，用于字数下限约束
    total_chunks_chars = sum(len(c) for c in chunks)
    # anti-montage 路径（有 anchor_pov）会合法压缩非 POV 内容，下限为 85%
    # 通用路径无合并逻辑，严格保留 90%
    min_ratio = 0.85 if anchor_pov else 0.90
    min_chars = int(total_chunks_chars * min_ratio)

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

    # 字数约束提示（嵌入两种模式的 system_prompt）
    min_percent = int(min_ratio * 100)
    # V3.5.4: 明确字数下限优先于目标字数，避免LLM困惑
    effective_target = max(word_count, min_chars)
    word_count_constraint = f"""
## 字数约束（硬性规定 - 优先级最高）
- 原始 Chunks 总字数：约 {total_chunks_chars} 字
- **统稿结果字数下限：{min_chars} 字**（不得低于原始 chunks 总字数的 {min_percent}%）
- **必须满足字数下限，即使超过目标字数 {word_count} 字也优先保留下限**
- 统稿时不设上限，确保最终字数 ≥ {min_chars} 字
- **严禁通过粗暴删段、合并段落或省略剧情来缩减字数**
- 若过渡处需要补写新文字，必须写；若原有内容完整，则完整保留
- ⚠️ **重要**：如果删减后字数可能低于 {min_chars} 字，宁可保留原文也不要过度精简"""

    # 构建连贯性参考部分（双轨模式核心改进）
    coherence_reference = ""
    if sketch_text:
        # 截取 Sketch 作为参考（限制长度避免 token 过长）
        sketch_preview = sketch_text[:1500] if len(sketch_text) > 1500 else sketch_text
        coherence_reference = f"""

## 连贯性参考（来自连贯速写）
以下是一段连续生成的速写文本，展示了自然流畅的场景过渡方式。你可以参考其过渡技巧来改善 Chunks 之间的衔接：

【连贯速写参考】
{sketch_preview}

**参考要点**：
- 学习上述文本中场景转换的自然方式（如用动作、感官描写代替生硬的转场词）
- 注意情绪流动的平滑性，避免突兀的情绪跳跃
- 你的统稿正文应比速写更详细、更丰富，但过渡方式可借鉴
- 不要照搬速写内容，只借鉴其过渡技巧"""

    # V3.5: 构建状态平滑过渡指令
    state_bridge_section = ""
    if persistent_state_anchors:
        anchors_lines = []
        for anchor in persistent_state_anchors:
            if isinstance(anchor, dict):
                anchor_type = anchor.get("anchor_type", "unknown")
                description = anchor.get("description", "")
                if description:
                    anchors_lines.append(f"- [{anchor_type}] {description}")
        
        if anchors_lines:
            anchors_text = "\n".join(anchors_lines)
            state_bridge_section = f"""

## 状态平滑过渡 (State Bridging) - V3.5 最高优先级
在合并 Chunks 时，你必须处理状态锚点的平滑过渡：

**当前持久状态锚点**：
{anchors_text}

**Bridge Prompt 指令**：
"请作为剧情桥梁，处理从 [上节拍结尾状态] 向 [当前节拍起始状态] 的平滑过渡，确保情感与物理状态无断层。"

**具体要求**：
1. 检查相邻 Chunks 之间的情感基调是否连贯，禁止无逻辑的情绪突变
2. 确保物理位置依附关系在 Chunk 边界处保持一致
3. 未解决冲突必须在 Chunk 之间保持连续性
4. 如果检测到状态断层（如角色情绪突兀转变、物理位置瞬移），必须重写过渡段落以实现平滑过渡
5. 优先使用动作、感官描写来实现状态过渡，避免生硬的声明式说明
"""

    if anchor_pov:
        system_prompt = f"""你是小说统稿编辑，但现在你是一个**反蒙太奇剪辑师**。你的任务是将多个并行生成的 chunk 融合成单一连续时间线的章节正文。

## 核心剪辑规则（最高优先级）

1. **单一连续时间线**：如果收到的 Chunks 中出现了空间跨越（例如 Chunk A 在地下，Chunk B 切到了天上），你拥有最高剪辑权。你必须抹去非【{anchor_pov}】视角的描写，将其合并为主视角的背景板感知流，确保文章时间线顺滑地流淌，无割裂感。

2. **抹除劣质胶水词**：全文检索并强行删去"与此同时"、"视角回到"、"在这关键时刻"等生硬的转场词。用具体的动作和物理状态（如视线偏移、耳边的轰鸣）代替结构性的生硬拼接。

3. **收束去AI味**：去除段落末尾那种尝试总结命运、拔高立意的"旁白说教"。
{blacklist_section}
{word_count_constraint}{coherence_reference}{state_bridge_section}

## 输出要求
- 输出纯文本，不要标题或解释
- 优先保留并融合各 chunk 的有效剧情信息，确保章节结构完整、过渡自然"""
    else:
        system_prompt = f"""你是小说统稿编辑。请将多个并行生成的 chunk 融合成连贯的章节正文。

要求：
1. **重点修复**：检查各 Chunk 之间的连接点，消除任何突兀的场景转换或逻辑断裂。如果前后文不搭，请重写过渡段落。
2. 保持剧情顺序与逻辑连贯。
3. 消除重复信息与风格断裂。
4. 统一人称、时态与语气。
5. 移除任何残留的元数据（如 JSON 标记、Markdown 代码块等）。
6. **抹除劣质胶水词**：全文检索并强行删去"与此同时"、"视角回到"、"在这关键时刻"等生硬的转场词。用具体的动作和物理状态（如视线偏移、耳边的轰鸣）代替结构性的生硬拼接。
7. 输出纯文本，不要标题或解释。
8. 优先保留并融合各 chunk 的有效剧情信息，确保章节结构完整、过渡自然。{blacklist_section}
{word_count_constraint}{coherence_reference}{state_bridge_section}"""

    # 🔒 V3.5: 注入跨章物理连续性约束（P0级 - 不可跳过）
    cross_chapter_section = ""
    if previous_chapter_snapshot:
        from backend.services.prompts.world_state_prompts import format_snapshot_for_planner
        snapshot_text = format_snapshot_for_planner(previous_chapter_snapshot)
        if snapshot_text:
            cross_chapter_section = f"""
【跨章物理连续性约束 - 最高优先级】
{snapshot_text}

⚠️ 统稿时必须确保：
1. 第一章节（Beat 1）的entry_state与上述「上一章末尾世界状态快照」保持100%连续性
2. 严禁角色状态突变或瞬移
3. 关键锚点必须在正文中有明确处理或状态变化说明

"""

    user_prompt = f"""请统稿以下内容：

{cross_chapter_section}【章节名】{chapter_name}
【章节大纲】
{chapter.outline_text or '暂无大纲'}
【Story Beats】
{chr(10).join(beat_lines) if beat_lines else "暂无"}

【Chunks】
{chr(10).join(chunk_lines) if chunk_lines else "暂无"}
"""
    return system_prompt, user_prompt

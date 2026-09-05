# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Contributors

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
审阅提示词模块（2026-09-05 精简）。

职责：仅提供精修（Refine）阶段提示词构建——`build_refine_agent_prompt`
是本模块唯一在役函数（消费方 services/workflows/refining.py，章节优化路由）。

历史函数 build_review_agent_prompt / build_chunk_review_prompt /
build_chunk_refine_prompt 与 parse_review_result 转发已随 V3 生成链 +
global_sys_prompt 死线整体归档至 backend/_deprecated/services/prompts/
（见该目录 README 2026-09-05 节）。
"""

import json

from backend.models import Chapter, Book
from backend.services.prompts.review_prompts_utils import (
    render_boundary_brief as _render_boundary_brief,
)


def build_refine_agent_prompt(chapter: Chapter, book: Book, entities: list, relationships: list, draft_text: str, revision_plan: str, word_count: int):
    chapter_name = chapter.chapter_name or f"第{chapter.chapter_number}章"
    # global_sys_prompt 线已退役（2026-09-05）：原读书级创作笔记，唯一在役消费
    # 就此掐断；固定基线=原空值兜底文案，未填笔记的书 prompt 逐字节零变化。
    global_sys_prompt = "你是一个专业的小说写作助手。"
    worldview_settings = book.worldview_settings or {}
    worldview_prompt = f"【世界观设定】\n{json.dumps(worldview_settings, ensure_ascii=False)}" if worldview_settings else None
    static_states = []
    dynamic_states = []
    seen_character_ids = set()
    for entity in entities:
        character = entity.character if hasattr(entity, "character") else entity
        if character and character.id not in seen_character_ids:
            seen_character_ids.add(character.id)
            if character.static_prompt:
                static_states.append(f"【{character.name}】{character.static_prompt}")
            if character.dynamic_state:
                dynamic_states.append(f"【{character.name}】{character.dynamic_state}")
    relationship_prompts = []
    for rel in relationships:
        if rel.interaction_prompt:
            source_name = rel.source_character.name if rel.source_character else "角色"
            target_name = rel.target_character.name if rel.target_character else "角色"
            relationship_prompts.append(f"【{source_name} ↔ {target_name}】{rel.interaction_prompt}")
    boundary_brief = _render_boundary_brief(chapter)
    system_prompt = f"""{global_sys_prompt}

{worldview_prompt if worldview_prompt else ''}

## 角色静态设定
{chr(10).join(static_states) if static_states else '暂无角色设定'}

## 角色动态状态
{chr(10).join(dynamic_states) if dynamic_states else '暂无动态状态'}

## 角色互动约束
{chr(10).join(relationship_prompts) if relationship_prompts else '暂无互动约束'}

## Boundary & Pacing 边界基线
{boundary_brief}

## 你的任务
你是一个精修编辑，需要根据审查意见对初稿进行针对性重写。
请仔细阅读以下审查意见和初稿，然后生成修改后的版本。

## 字数硬性约束（最高优先级，不可违反）
- 原稿字数约 **{word_count} 字**
- 精修后字数**不得低于原稿的 90%**（即不得低于 {int(word_count * 0.9)} 字）
- 严禁通过删段、合并段落或省略细节来缩减字数
- 若审查意见要求修改某处，必须用等量或更多新文字替换，而非直接删除

## 核心规则
1. 严格遵循审查意见进行修改
2. 保持原有优秀的部分
3. 修正被指出的问题
4. 确保修改后的内容符合章节大纲
5. 保持角色性格一致性
6. 如审查意见包含 PACING_OVERFLOW，必须执行"回退-降速-悬停"策略：先回退越界剧情，再放慢推进，最后停在对应 exit_state
7. 重写时必须保留原稿的关键段落信息与叙事骨架，不得大幅删除段落
8. 若必须删除局部段落，必须以等价的新段落补回信息、动机与情绪链路，保证前后完整

## 🛑 精修文笔禁令（Negative Constraint - 最高优先级）
你只能通过修改具体的【动作动词】和【环境破坏力】来体现审查意见，严格遵循 'Show, don't tell' 原则。
在正文生成中，【严禁】使用任何判定式、解释式的说教词汇：
- ❌ 严禁出现：「不是...而是...」、「这并非...只是一种...」、「这说明了...」、「这意味着...」、「这代表了...」
- ❌ 严禁出现：「其实...」、「事实上...」、「实际上...」、「本质上...」
- ❌ 严禁出现：「从此...」、「于是...」、「因此...」（作为解释因果的副词）
- ❌ 严禁打破第四面墙对读者进行解释说明
- ✅ 正确做法：用具体的动作、感官细节和环境反应来表达审查要求的内容，让情节自己说话

**修正示例**：
- 错误：「这不是恐惧，只是一种本能的警觉。」
- 正确：「后颈的汗毛一根根竖了起来。」
- 错误：「这并非背叛，而是一种无奈的选择。」
- 正确：「他别过脸去，握剑的手指关节泛白。」"""
    user_prompt = f"""请根据以下审查意见重写初稿:

【章节名】{chapter_name}
【章节标题】{chapter.title or '未命名'}
【章节大纲】
{chapter.outline_text or '暂无大纲'}

【Boundary & Pacing 边界基线】
{boundary_brief}

【审查意见】
{revision_plan}

【当前初稿】
{draft_text}

若审查意见涉及 PACING_OVERFLOW，请执行以下策略：

**推荐策略（精准裁剪）**：
1. 定位越过 exit_state 的具体句子（通常是最后 1-3 句）
2. 不要删除整段，而是微调结尾动作
3. 通过添加收束句或微调动作，使文本停在规定的 exit_state 上
4. 保持原有文本的灵气和叙事节奏

**示例**：
- 原文结尾："他冲向门口，推开门，发现敌人已经在走廊尽头。"
- 目标 exit_state："准备开门，但未看到门外"
- 精准裁剪："他冲向门口，手搭在门把上，心跳如鼓。门后的未知让他迟疑了一瞬。"
- 这样既保留了动作张力，又遵守了边界约束

**回退策略（仅在严重越界时使用）**：
1) 删除越过 exit_state 之后的推进内容
2) 撤销触发 red_lines 的事件与行为  
3) 放慢叙事推进并停在对应 exit_state，保留必要悬念

**完整性保护原则**：
1) 优先使用精准裁剪，避免大幅删段
2) 必须保留原稿中的关键情节节点、动机链与情绪递进
3) 如需调整结构，只能重写优化，不可直接删去关键段落
4) 修改后的文本长度应与原文接近（±20%），严禁过度压缩

请直接输出修改后的完整小说正文，不需要任何额外说明或标记。请确保剧情完整连贯。"""
    return system_prompt, user_prompt

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
人物提取 Prompt 模板

职责：为人物提取服务提供结构化 Prompt
"""

from typing import List


def build_character_extraction_system_prompt() -> str:
    """
    构建人物提取的系统 Prompt
    
    Returns:
        系统提示文本
    """
    return """你是一个专业的小说人物分析助手，专门负责从小说章节中提取人物信息。

你的任务是：
1. 仔细阅读提供的章节内容
2. 识别所有出现的人物（包括有名字的角色、有称谓的角色、甚至有描述但无名的角色）
3. 区分新人物和已有角色
4. 分析人物之间的关系

重要规则：
- 必须返回合法的 JSON 格式
- is_new 字段必须正确设置：true 表示新角色，false 表示已有角色
- 不要遗漏任何人物，即使只是短暂出现
- 角色名称优先使用具体名字而非描述性称呼"""


def build_character_extraction_prompt(
    chapter_content: str,
    existing_character_names: List[str],
) -> str:
    """
    构建人物提取 Prompt
    
    Args:
        chapter_content: 章节内容（已截断）
        existing_character_names: 已有角色名称列表
        
    Returns:
        完整的 Prompt 文本
    """
    
    existing_chars_section = ""
    if existing_character_names:
        existing_chars_section = f"""
【已有角色列表 - 重要！】
以下角色已在系统中存在，如果在章节中出现了这些角色，必须标记为 is_new=false：
{', '.join(existing_character_names)}

如果章节中的人物不在上述列表中，则视为新角色，必须标记为 is_new=true。
"""
    else:
        existing_chars_section = """
【已有角色列表】
当前书籍中还没有任何角色，所以章节中出现的所有人物都是新角色，必须标记为 is_new=true。
"""
    
    prompt = f"""你是一个专业的小说人物分析助手。请仔细阅读以下小说章节内容，提取所有出现的人物信息。

## 任务说明

1. **识别人物**：找出章节中所有有名字或特定称谓的人物（包括路人、服务员、随从等有短暂出现的人物）
2. **判断新旧**：严格对照【已有角色列表】，列表中有的标记 is_new=false，列表中没有的标记 is_new=true
3. **分析关系**：识别人物之间的互动关系

## 输出格式 - 必须严格遵守

请输出合法的 JSON 格式，不要添加任何其他说明文字：

{{"characters":[{{"name":"主角名称","is_new":true,"description":"外貌穿着描述","role_type":"protagonist","aliases":["别名"],"importance_level":4}},{{"name":"反派名称","is_new":true,"description":"外貌描述","role_type":"antagonist","aliases":[],"importance_level":3}},{{"name":"配角名称","is_new":true,"description":"外貌描述","role_type":"supporting","aliases":[],"importance_level":2}},{{"name":"路人/龙套","is_new":true,"description":"外貌描述","role_type":"minor","aliases":[],"importance_level":1}}],"relationships":[{{"source":"人物A","target":"人物B","relation_type":"关系类型","description":"关系描述","affinity_score":0}}]}}

## 字段说明

- **name**: 人物的主要称呼名称（优先使用全名，如"伯恩斯"而非"贵族青年"）
- **is_new**: 
  - true = 新人物（不在【已有角色列表】中）
  - false = 已有角色（在【已有角色列表】中）
- **description**: 人物的外貌、穿着、气质等（50字以内）
- **role_type** 和 **importance_level** 对应关系（重要性等级只有 4 级）：
  - **minor** (路人/龙套): importance_level = 1
    *只有称谓无名字、或短暂出现、无对白的背景人物，对应显示标签"普通"*
  - **supporting** (配角): importance_level = 2
    *有名字、有对话，但戏份不多的辅助角色，对应显示标签"重要"*
  - **antagonist** (反派/对手): importance_level = 3
    *与主角有冲突的主要角色，推动剧情发展，对应显示标签"核心"（非主角）*
  - **protagonist** (主角): importance_level = 4
    *章节的叙事中心、POV角色，对应显示标签"主角"*
- **aliases**: 别名、称号、昵称等数组
- **relation_type**: 关系类型：friend/enemy/family/mentor/lover/rival/acquaintance/subordinate
- **affinity_score**: 亲密度 -100到100

{existing_chars_section}

## 章节内容

{chapter_content}

## 重要提示 - 请仔细阅读

1. **必须输出合法的 JSON 格式**，键名必须用双引号
2. **is_new 字段必须正确设置**：
   - 如果人物在【已有角色列表】中 → is_new=false
   - 如果人物不在【已有角色列表】中 → is_new=true
3. **role_type 和 importance_level 必须严格匹配（只使用 1-4）**：
   - **importance_level 只有 4 个等级，与 role_type 一一对应：**
   - minor (路人): importance_level = 1 → 显示为"普通"
   - supporting (配角): importance_level = 2 → 显示为"重要"
   - antagonist (反派): importance_level = 3 → 显示为"核心"
   - protagonist (主角): importance_level = 4 → 显示为"主角"
   - **注意："主角"这个词只用于 protagonist (等级4)，antagonist (等级3) 显示为"核心"**
   - 判断依据：戏份多少、是否有对白、是否推动剧情、是否被详细描写
4. **不要错过任何人物**：
   - 有名字的角色（如"兰星"、"伯恩斯"）
   - 有称谓的角色（如"书记员"、"法师"、"随从"）
   - 有描述的角色（如"棕发少年"、"佩戴紫水晶胸针的女法师"）
5. **不要编造信息**：只提取章节中明确出现的内容
6. **角色名称优先使用具体名字**：如使用"伯恩斯"而不是"贵族青年"
7. **大多数角色应该是配角或路人**：一个章节通常只有 1-2 个主角/反派，其他都是配角或路人
"""
    
    return prompt


def build_relationship_update_prompt(
    char1_name: str,
    char1_current_state: str,
    char2_name: str,
    char2_current_state: str,
    chapter_excerpt: str,
) -> str:
    """
    构建关系更新 Prompt
    
    用于分析两个角色在章节中的互动，判断是否需要更新关系
    
    Args:
        char1_name: 角色1名称
        char1_current_state: 角色1当前状态
        char2_name: 角色2名称
        char2_current_state: 角色2当前状态
        chapter_excerpt: 相关章节片段
        
    Returns:
        Prompt 文本
    """
    
    prompt = f"""分析以下两个角色在本章节中的互动，判断他们的关系是否发生变化。

【角色信息】
角色A：{char1_name}
当前状态：{char1_current_state}

角色B：{char2_name}
当前状态：{char2_current_state}

【章节互动片段】
{chapter_excerpt}

【分析任务】
1. 判断两人关系是否有实质性变化
2. 如果有变化，描述新的关系状态
3. 评估亲密度变化（-100到100）

【输出格式】
```json
{{
  "relationship_changed": true/false,
  "new_relation_type": "新的关系类型（如未变化则留空）",
  "change_description": "关系变化的描述",
  "new_affinity_score": 亲密度数值,
  "interaction_prompt": "对后续生成有意义的互动提示"
}}
```

注意：如果关系没有明显变化，relationship_changed 设为 false，其他字段可留空。"""
    
    return prompt

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
正文逆向提取 Prompt 模板（统一提取）。

职责：
- 从章节正文中一次性提取角色、关系、地点、资产、伏笔五类结构化数据
- 输出严格 JSON，供 ExtractionResult 解析

业务场景：
- 用户导入 .md 或对已有章节执行"分析正文"时，由 content_extractor 调用
- 单次 LLM 调用提取全部类型，保证一致性与成本效率

使用方式：
    from backend.services.prompts.content_extraction import (
        build_extraction_system_prompt,
        build_extraction_prompt,
    )
"""
from typing import List


def build_extraction_system_prompt() -> str:
    """
    正文逆向提取的系统 prompt。

    Returns:
        系统提示词字符串，定义角色、提取规则、JSON 输出格式。
    """
    return """你是一个专业的小说文本分析师。你的任务是从章节正文中提取结构化数据，包括：角色、角色间关系、地点、资产（重要道具）、伏笔。

## 提取规则

1. **角色**：提取所有有名字或有明确称呼的人物。忽略无名背景角色（如"路人""士兵甲"除非有对话或行动）。
2. **关系**：只提取有明确互动或亲属/敌友关系的人物对。不要凭空臆造关系。
3. **地点**：提取故事发生的地理位置或场景。只提取有名称或重要性的地点，忽略泛指（如"房间里"）。
4. **资产**：提取对剧情有重要作用的具体物品（武器、信物、道具等）。忽略普通日用品。
5. **伏笔**：提取作者埋下的、需要后续回收的悬念或线索。只提取明显的伏笔，不要过度解读。

## JSON 输出格式

你必须输出**合法的 JSON**（不带 markdown 代码块标记），结构如下：

```
{
  "characters": [
    {
      "name": "角色名",
      "description": "基于正文的简短描述（外貌、性格、身份，20-80字）",
      "role_type": "protagonist | antagonist | supporting | minor",
      "importance_level": 1-10,
      "aliases": ["别名", "绰号"]
    }
  ],
  "relationships": [
    {
      "source_name": "源角色名",
      "target_name": "目标角色名",
      "relation_type": "关系类型（如 师徒/父子/敌对/恋人/同盟）",
      "affinity_score": -100到100（-100=深仇, 0=中立, 100=挚爱）,
      "description": "关系简述（如'A暗中保护B'）"
    }
  ],
  "locations": [
    {
      "name": "地点名",
      "description": "地点描述（场景特征、氛围，20-60字）"
    }
  ],
  "assets": [
    {
      "name": "资产名",
      "description": "资产描述（外观、功能、来历，20-60字）",
      "importance_level": 1-5
    }
  ],
  "foreshadows": [
    {
      "ledger_key": "英文短横线风格唯一标识（如 mystery-letter-backstory）",
      "content": "伏笔内容描述（埋了什么线索）",
      "entry_type": "foreshadow | callback | twist",
      "status": "open | closed",
      "strength": 1-10（伏笔重要性）
    }
  ]
}

## 重要提示
- 所有键名必须用双引号
- 不要输出 JSON 以外的任何文字
- 如果某一类没有提取到任何内容，返回空数组 `[]`
- description 字段必须基于正文内容，不要编造
- importance_level 和 affinity_score 必须是整数
- 角色的 name 必须与正文中出现的名字一致"""


def build_extraction_prompt(
    chapter_content: str,
    chapter_number: int,
    existing_character_names: List[str] = None,
    existing_ledger_keys: List[str] = None,
) -> str:
    """
    构造用户 prompt，注入正文和已有实体信息。

    Args:
        chapter_content: 章节正文（调用方应已截断到合理长度）
        chapter_number: 章节序号
        existing_character_names: 已存在的角色名列表（提示 LLM 这些已入库）
        existing_ledger_keys: 已存在的伏笔 key 列表（避免 key 冲突）

    Returns:
        用户提示词字符串。
    """
    existing_chars_section = ""
    if existing_character_names:
        existing_chars_section = f"\n\n## 已存在的角色（无需重复提取，但可在关系中引用）\n{', '.join(existing_character_names)}"

    existing_ledger_section = ""
    if existing_ledger_keys:
        existing_ledger_section = f"\n\n## 已存在的伏笔 key（新伏笔的 ledger_key 不要与之重复）\n{', '.join(existing_ledger_keys)}"

    return f"""请分析以下第 {chapter_number} 章的正文，提取所有结构化数据。

## 正文内容

{chapter_content}{existing_chars_section}{existing_ledger_section}

请按照 JSON 格式输出提取结果。记住：只输出 JSON，不要任何其他文字。"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
Critique Prompt 构建模块
"""
from typing import Optional

def build_critique_system_prompt() -> str:
    """构建章节审阅的 System Prompt"""
    return """# 角色
你是一位拥有深厚商业小说与严肃文学双重功底的金牌主编（Beta Reader）。你的眼睛像鹰一样锐利，极其痛恨大模型生成的“死板塑料味”、“冗长的设定说明文”以及“缺乏起伏的流水账”。

# 任务
请阅读作者提交的这章小说，站在**最挑剔的文学编辑**视角，出具一份犀利、精准的审阅报告。
**绝对不要重写全文！只提供修改建议！**

# 诊断与扫描维度：
1. **“AI 味”扫雷与设定倾倒 (No Info-dumping)**：
   - 揪出在非必要时刻打断剧情去解释世界观的设定倾倒片段。
   - 揪出“命运的齿轮”、“与此同时”、“这场战斗将改变世界”等空洞的上帝视角废话。
2. **叙事节奏与句式排版 (Pacing)**：
   - 找出动作戏或紧张情节中，句式过于冗长、排版粘连的段落，提醒作者切分短句。
3. **具象化法则 (Show, Don't Tell)**：
   - 找出原文中滥用的“形容词堆砌”或直接概括情绪的词语（如“极度震撼”、“十分压抑”），建议作者将其转化为微观的物理反应和动作描写。

# 输出格式约束
你必须输出一个符合以下结构的 JSON 对象（不要输出 Markdown，只输出纯 JSON）：

```json
{
    "comments": [
        {
            "exact_quote": "定位片段 (引用原文中的 1-2 句话，必须精确)",
            "type": "毒点分类 (例如：严重设定倾倒 / 上帝视角溢出 / 节奏黏糊)",
            "reader_feeling": "读者体感 (一针见血地指出这为什么会让读者出戏或感到无聊)",
            "suggestion": "手术方案 (给出清晰的修改动作，并给出一个简短的、极具张力的改写示范)"
        }
    ],
    "overall_praise": "本章高光 (仅限50字内，精准表扬本章中写得最有张力、最抓人的一处文本，如果没有则指出需要剥离AI感)"
}
```

请确保输出是合法的 JSON 格式。建议数量控制在 10-15 条，覆盖全文的各个方面。
"""

def build_critique_user_prompt(chapter_content: str, chapter_title: Optional[str] = None) -> str:
    """构建章节审阅的 User Prompt"""
    title_info = f"章节标题：{chapter_title}\n\n" if chapter_title else ""
    return f"{title_info}章节正文内容如下：\n\n{chapter_content}"

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
StyleCard 提炼 Prompt 模板（Phase 1 CP2.2a 新建）。

职责：从作者样本提炼文风画像（Match My Style 式，蓝图 §6.2）。

设计依据：
- 调研报告 §4.3：作者样本 few-shot 是单一最有效去味手段
- 蓝图 §4.4 文风卡：正面画像 + 负面清单 + 量化指标
- 调研报告 §4.3：去味必须双管齐下（显式点名禁止默认特征 + 用真实样本锚定）

输出契约：
- LLM 必须输出 JSON，结构：
  {
    "positive_profile": {
      "sentence_rhythm": "短句与长句交替，平均 15 字左右",
      "vocabulary": "口语化，多用动词少用形容词",
      "register": "中性偏口语，允许俚语",
      "opening_habit": "常以动作或对话开篇",
      "ending_habit": "结尾多留悬念或情绪余韵"
    },
    "negative_list": [
      {"word": "命运的齿轮", "alternative": "直接描述事件因果"},
      ...
    ],
    "dialogue_ratio_target": 0.35,
    "paragraph_rhythm": "段落短促，常 2-3 句一段"
  }
- 解析失败：extractor 降级到 genre 默认画像 + 标 degraded
"""

import json
from typing import List, Optional, Tuple


def build_style_extract_prompt(
    samples: List[str],
    genre: Optional[str] = None,
) -> Tuple[str, str]:
    """构建文风画像提炼 prompt。

    Args:
        samples: 作者样本文本列表（1-5 段）
        genre: 可选题材（用于兜底画像提示）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    # 样本拼接（每段标号，便于 LLM 引用）
    samples_text = "\n\n".join(
        f"【样本 {i+1}】\n{s}" for i, s in enumerate(samples)
    )

    genre_hint = f"\n本书题材：{genre}（提炼时考虑题材惯例）" if genre else ""

    system_prompt = f"""你是一位资深的文学编辑和文风分析师。你的任务是从作者提供的样本文中提炼出结构化的文风画像。

## 你的分析维度

### 正面画像（positive_profile）
从样本中归纳作者的真实文风特征：
- sentence_rhythm: 句长节奏（短句/长句的交替模式，平均句长）
- vocabulary: 词汇层级（口语化/书面化/文言色彩，动词形容词比例）
- register: 语域（正式/中性/口语，是否允许俚语、口头语）
- opening_habit: 开头习惯（常以什么开篇：动作/对话/景物/心理）
- ending_habit: 结尾习惯（多留悬念/情绪余韵/动作收束/对话收尾）

### 负面清单（negative_list）
从样本中反推作者**不会使用**的措辞——这些通常是 AI 默认会写出但本作者不会写的：
- word: 禁用的词或短语
- alternative: 该禁词的正面替代规则（如何用作者的风格表达同样意思）

每条 negative_list 必须含 alternative，不能只列禁词不列替代。

### 量化指标
- dialogue_ratio_target: 对话占比目标（0-1 之间，0.3 表示约 30% 篇幅是对话）
- paragraph_rhythm: 段落节奏的自然语言描述

## 输出格式

只输出一个 JSON 块，不要任何解释或前后缀：

```json
{{
  "positive_profile": {{
    "sentence_rhythm": "...",
    "vocabulary": "...",
    "register": "...",
    "opening_habit": "...",
    "ending_habit": "..."
  }},
  "negative_list": [
    {{"word": "...", "alternative": "..."}}
  ],
  "dialogue_ratio_target": 0.0,
  "paragraph_rhythm": "..."
}}
```

## 关键原则

1. 正面画像要**具体**——"短句与长句交替，平均 15 字"比"节奏多变"有价值
2. 负面清单要**可执行**——每条禁词必须配替代规则
3. negative_list 至少 5 条，至多 15 条
4. 量化指标要**保守**——基于样本实测，不要拍脑袋
5. 不要列通用 AI 腔禁词（如"命运的齿轮"）——这些系统禁词表已有，只列与本作者文风冲突的"""

    user_prompt = f"""请分析以下作者样本，提炼文风画像。{genre_hint}

---

{samples_text}

---

请输出 JSON 格式的文风画像（含 positive_profile、negative_list、dialogue_ratio_target、paragraph_rhythm）。"""

    return system_prompt, user_prompt


def parse_style_extract_response(
    raw_response: str,
) -> Tuple[Optional[dict], Optional[List[dict]], Optional[float], Optional[str], Optional[str]]:
    """解析 LLM 文风画像提炼响应。

    Args:
        raw_response: LLM 原始响应文本

    Returns:
        tuple: (positive_profile, negative_list, dialogue_ratio_target, paragraph_rhythm, error)
        解析失败时前 4 项为 None，error 含失败原因
    """
    # 清理 markdown 标记
    text = raw_response.strip()
    if text.startswith("```"):
        # 去掉首尾 ```
        text = text.replace("```json", "", 1).replace("```", "", 1)
        text = text.strip()
        # 若还有残留 ```，再去一次
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, None, None, None, f"JSON 解析失败: {e}"

    positive_profile = data.get("positive_profile")
    if not isinstance(positive_profile, dict):
        positive_profile = {}

    negative_list = data.get("negative_list")
    if not isinstance(negative_list, list):
        negative_list = []
    # 过滤无效项
    cleaned_negative = []
    for item in negative_list:
        if not isinstance(item, dict):
            continue
        word = item.get("word") or item.get("phrase") or ""
        alt = item.get("alternative") or ""
        if word:
            cleaned_negative.append({"word": str(word), "alternative": str(alt)})

    dialogue_ratio = data.get("dialogue_ratio_target")
    if dialogue_ratio is not None:
        try:
            dialogue_ratio = float(dialogue_ratio)
            # 钳制到 [0, 1]
            dialogue_ratio = max(0.0, min(1.0, dialogue_ratio))
        except (TypeError, ValueError):
            dialogue_ratio = None

    paragraph_rhythm = data.get("paragraph_rhythm")
    if paragraph_rhythm is not None:
        paragraph_rhythm = str(paragraph_rhythm)[:500]

    return positive_profile, cleaned_negative, dialogue_ratio, paragraph_rhythm, None


def build_genre_fallback_profile(genre: Optional[str]) -> dict:
    """题材默认画像（提炼失败时的兜底）。

    依据：调研报告 §3.6 + 蓝图 §3.6 决策点。仅作最低保障，不替代真实样本。
    """
    if not genre:
        return {
            "sentence_rhythm": "短句与长句交替",
            "vocabulary": "中性",
            "register": "中性偏口语",
            "opening_habit": "动作或对话开篇",
            "ending_habit": "情绪余韵收尾",
        }
    genre_lower = genre.lower()
    if any(k in genre_lower for k in ["玄幻", "仙侠", "武侠"]):
        return {
            "sentence_rhythm": "短促有力，动作描写用短句",
            "vocabulary": "半文半白，允许古风词汇",
            "register": "中性，战斗场景紧凑",
            "opening_habit": "常以场景或动作开篇",
            "ending_habit": "悬念或转折收尾",
        }
    if any(k in genre_lower for k in ["言情", "都市"]):
        return {
            "sentence_rhythm": "灵活，对话与心理描写交替",
            "vocabulary": "现代口语化",
            "register": "口语，允许流行语",
            "opening_habit": "对话或心理开篇",
            "ending_habit": "情绪或关系变化收尾",
        }
    if any(k in genre_lower for k in ["悬疑", "推理"]):
        return {
            "sentence_rhythm": "短句制造紧张感",
            "vocabulary": "克制，少形容词",
            "register": "冷静客观",
            "opening_habit": "事件或细节开篇",
            "ending_habit": "悬念钩子收尾",
        }
    # 默认
    return {
        "sentence_rhythm": "短句与长句交替",
        "vocabulary": "中性",
        "register": "中性偏口语",
        "opening_habit": "动作或对话开篇",
        "ending_habit": "情绪余韵收尾",
    }

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
增强型检索评分器 - 大纲关键词提取器。

职责：从章节大纲提取关键词、事件类型、情感倾向等。

包含：
- OutlineKeywordExtractor: 大纲关键词提取器

使用场景：
- rag/enhanced/scorer.py: 评分器使用提取结果
"""

import re
from typing import Any, Dict, List, Set


class OutlineKeywordExtractor:
    """
    大纲关键词提取器

    职责：
    - 从章节大纲提取关键词
    - 识别角色名称
    - 识别事件类型
    - 识别地点信息
    """

    STOP_WORDS = {
        "的", "了", "是", "在", "我", "有", "和", "就", "不", "人",
        "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
        "你", "会", "着", "没有", "看", "好", "自己", "这", "那", "他",
        "她", "它", "们", "这个", "那个", "什么", "怎么", "这样", "那样",
        "因为", "所以", "但是", "然而", "如果", "虽然", "还是", "或者",
    }

    EVENT_KEYWORDS = {
        "战斗", "对决", "冲突", "相遇", "离别", "重逢", "发现", "觉醒",
        "突破", "修炼", "探险", "救援", "追杀", "逃亡", "复仇", "和解",
        "告白", "误会", "澄清", "揭秘", "阴谋", "背叛", "牺牲", "拯救",
    }

    EMOTION_KEYWORDS = {
        "愤怒", "悲伤", "喜悦", "恐惧", "惊讶", "期待", "失望", "感动",
        "爱慕", "仇恨", "羡慕", "嫉妒", "焦虑", "平静", "激动", "绝望",
    }

    def extract(self, outline: str) -> Dict[str, Any]:
        """
        从大纲提取关键信息

        Args:
            outline: 章节大纲文本

        Returns:
            Dict: 包含关键词、事件类型、情感倾向等
        """
        if not outline:
            return {"keywords": [], "events": [], "emotions": []}

        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,10}', outline)

        keywords = [w for w in chinese_words if w not in self.STOP_WORDS]

        seen = set()
        unique_keywords = []
        for w in keywords:
            if w not in seen:
                seen.add(w)
                unique_keywords.append(w)

        events = [w for w in unique_keywords if w in self.EVENT_KEYWORDS]
        emotions = [w for w in unique_keywords if w in self.EMOTION_KEYWORDS]

        return {
            "keywords": unique_keywords[:20],
            "events": events,
            "emotions": emotions,
            "keyword_set": set(unique_keywords),
        }

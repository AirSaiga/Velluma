# Velluma - AI Novel Writing Assistant
# Copyright (C) 2026 Velluma Project Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
短文生成器 (Sketch Generator) - 双轨架构 Track B

职责：基于节拍框架生成连贯的速写短文，作为连贯性锚点。

核心特性：
- 连续叙述流：不标记节拍边界，自然流淌
- 强连贯性：情绪、节奏、信息传递一气呵成
- 转折点映射：记录关键转折点在文中的实际位置
- 首尾呼应：确保开头和结尾的情感闭环

使用场景：
- 与 Track A (节拍扩写) 并行生成
- 为后续对抗校对提供连贯性参考
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from pydantic import BaseModel

from backend.services.llm_client import call_llm
from backend.services.workflows.utils import clean_llm_output

logger = logging.getLogger(__name__)


class TurnMarker(BaseModel):
    """转折点标记 - 记录 Sketch 中关键转折点的位置"""
    beat_index: int  # 对应的节拍索引（1-based）
    beat_id: str
    position_percent: float  # 在全文中的位置占比 (0-100)
    transition_type: str  # 转折类型：情绪/信息/冲突/决策
    description: str  # 转折点描述


class SketchResult(BaseModel):
    """短文生成结果"""
    sketch_text: str  # 完整的速写文本
    turn_markers: List[TurnMarker]  # 转折点位置映射
    emotion_arc: List[Dict[str, Any]]  # 情绪曲线
    word_count: int  # 实际字数
    
    # 调试信息
    prompts: List[dict] = []
    generation_time: float = 0.0


@dataclass
class SketchGeneratorConfig:
    """短文生成器配置"""
    # 字数比例：Sketch 字数 / 正文字数
    # 默认 40-50%，既保证连贯性又节省成本
    sketch_ratio: float = 0.45
    
    # 最小字数（防止过短）
    min_words: int = 500
    
    # 最大字数（防止过长）
    max_words: int = 3000
    
    # 温度：比正文稍高，鼓励流畅
    temperature: float = 0.8
    
    # 生成超时（秒）
    timeout: float = 120.0


class SketchGenerator:
    """
    短文生成器
    
    设计原则：
    1. 与节拍扩写并行，不互相等待
    2. 专注于流畅性而非精确性
    3. 提供节拍间过渡的自然范例
    """
    
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        config: Optional[SketchGeneratorConfig] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.config = config or SketchGeneratorConfig()
    
    async def generate(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        entities: List[Any],
        relationships: List[Any],
        word_count: int,
        previous_summary: Optional[str] = None,
        anchor_pov: Optional[str] = None,
    ) -> SketchResult:
        """
        生成连贯速写短文
        
        Args:
            chapter: 章节实体
            book: 书籍实体
            beats: 节拍列表
            entities: 角色实体列表
            relationships: 角色关系列表
            word_count: 目标总字数（正文）
            previous_summary: 上一章摘要
            anchor_pov: 锚定视角角色
            
        Returns:
            SketchResult: 生成结果
        """
        import time
        start_time = time.perf_counter()
        
        # 计算目标字数
        target_words = self._calculate_sketch_words(word_count, len(beats))
        
        logger.info(f"[SketchGenerator] 开始生成速写，目标字数: {target_words}，节拍数: {len(beats)}")
        
        # 构建 Prompt
        system_prompt, user_prompt = self.build_sketch_prompt(
            chapter=chapter,
            book=book,
            beats=beats,
            entities=entities,
            relationships=relationships,
            target_words=target_words,
            previous_summary=previous_summary,
            anchor_pov=anchor_pov,
        )
        
        prompts_history = [{
            "stage": "SKETCH_GENERATION",
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": self.config.temperature,
            "target_words": target_words,
        }]
        
        try:
            # 调用 LLM 生成速写
            response = await asyncio.wait_for(
                call_llm(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    model=self.model,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=self.config.temperature,
                    max_tokens=int(target_words * 2.5),  # 安全系数
                ),
                timeout=self.config.timeout,
            )
            
            sketch_text = clean_llm_output(response).strip()
            actual_words = len(sketch_text)
            
            logger.info(f"[SketchGenerator] 速写生成完成，实际字数: {actual_words}")
            
            # 解析转折点标记（如果模型输出了结构化数据）
            turn_markers, emotion_arc = self._parse_sketch_structure(sketch_text, beats)
            
            generation_time = time.perf_counter() - start_time
            
            return SketchResult(
                sketch_text=sketch_text,
                turn_markers=turn_markers,
                emotion_arc=emotion_arc,
                word_count=actual_words,
                prompts=prompts_history,
                generation_time=generation_time,
            )
            
        except asyncio.TimeoutError:
            logger.error(f"[SketchGenerator] 生成超时 ({self.config.timeout}s)")
            # 返回空结果，不影响主流程
            return SketchResult(
                sketch_text="",
                turn_markers=[],
                emotion_arc=[],
                word_count=0,
                prompts=prompts_history,
                generation_time=self.config.timeout,
            )
        except Exception as e:
            logger.error(f"[SketchGenerator] 生成失败: {e}")
            return SketchResult(
                sketch_text="",
                turn_markers=[],
                emotion_arc=[],
                word_count=0,
                prompts=prompts_history,
                generation_time=time.perf_counter() - start_time,
            )
    
    def _calculate_sketch_words(self, total_words: int, beat_count: int) -> int:
        """计算速写目标字数"""
        # 基础字数：总字数的比例
        base_words = int(total_words * self.config.sketch_ratio)
        
        # 根据节拍数调整（节拍越多，速写需要的信息量越大）
        # 每个节拍至少 100 字
        min_by_beats = beat_count * 100
        
        # 取两者较大值，但不超过最大值
        target = max(base_words, min_by_beats)
        target = max(self.config.min_words, min(target, self.config.max_words))
        
        return target
    
    def build_sketch_prompt(
        self,
        chapter: Any,
        book: Any,
        beats: List[dict],
        entities: List[Any],
        relationships: List[Any],
        target_words: int,
        previous_summary: Optional[str] = None,
        anchor_pov: Optional[str] = None,
    ) -> Tuple[str, str]:
        """构建速写生成的 Prompt"""
        
        # 构建节拍摘要（不含内部边界标记）
        beats_summary = self._build_beats_summary(beats)
        
        # 角色信息
        characters_info = self._build_characters_info(entities)
        
        # 关系信息
        relationships_info = self._build_relationships_info(relationships)
        
        # 世界观信息
        world_info = getattr(book, 'world_building', '') or ''
        
        # 上一章衔接
        continuity_hint = ""
        if previous_summary:
            continuity_hint = f"""
## 前文衔接
上一章结尾：{previous_summary[-300:] if len(previous_summary) > 300 else previous_summary}

重要：本章开头必须自然承接上文的情绪和状态。
"""
        
        system_prompt = f"""你是一位直觉型小说家，擅长用流畅的叙述书写故事速写。

## 你的任务
基于提供的节拍框架，写一篇**连续的速写短文**。

## 核心要求（按优先级排序）

### 1. 连续叙述流（最重要）
- **禁止**在文中标记节拍边界（不要写"第一拍"、"第二部分"等）
- 用自然的过渡句连接不同节拍的内容
- 情绪、节奏、信息传递必须一气呵成

### 2. 强连贯性
- 节拍间的过渡要自然流畅，像水流一样
- 避免生硬的"就在这时"、"与此同时"等转场词
- 情绪变化要有渐变过程，不能跳跃

### 3. 首尾呼应
- 开头要承接上一章的情绪状态
- 结尾要形成情感闭环，让读者有满足感
- 开头和结尾的情绪基调要有呼应关系

### 4. 转折点映射（关键输出）
在生成完正文后，你必须输出一个 JSON 块，标记每个关键转折点的位置：

```json
{{
  "turn_markers": [
    {{
      "beat_index": 1,
      "position_percent": 15.0,
      "transition_type": "情绪",
      "description": "从紧张转为警觉"
    }},
    {{
      "beat_index": 2, 
      "position_percent": 40.0,
      "transition_type": "信息",
      "description": "发现关键线索"
    }}
  ],
  "emotion_arc": [
    {{"position": "开头", "emotion": "焦虑", "intensity": 7}},
    {{"position": "中段", "emotion": "警觉", "intensity": 6}},
    {{"position": "结尾", "emotion": "决心", "intensity": 8}}
  ]
}}
```

### 5. 字数控制
目标字数：{target_words} 字左右（允许 ±20% 误差）

### 6. 视角锁定
{'视角角色：' + anchor_pov if anchor_pov else '使用第三人称或根据内容自然选择视角'}
- 绝对锁定在 POV 角色的感官范围内
- 非 POV 角色的事件必须转化为 POV 能感知的物理异象

## 禁止事项
- 不要写大纲式总结
- 不要使用"首先"、"其次"、"最后"等分点词
- 不要预告后续剧情（"这将是冒险的开始"等）
- 不要跳出故事进行旁白说教
"""

        user_prompt = f"""## 章节信息
标题：{getattr(chapter, 'title', '未命名章节')}
大纲：{getattr(chapter, 'outline_text', '')}

{continuity_hint}

## 角色信息
{characters_info}

## 角色关系
{relationships_info}

## 世界观背景
{world_info[:500] if world_info else '（无特殊设定）'}

## 节拍框架（仅作为情节路标，不要机械分段）
{beats_summary}

---

请基于以上信息，写一篇流畅的速写短文。

要求：
1. 连续叙述，**绝对禁止**标记节拍边界
2. 重点关注情绪流动和自然过渡
3. 确保开头承接上文，结尾形成闭环
4. 在正文后输出 JSON 格式的转折点映射
5. 字数控制在 {target_words} 字左右

请直接输出正文，然后是 JSON 块。"""

        return system_prompt, user_prompt
    
    def _build_beats_summary(self, beats: List[dict]) -> str:
        """构建节拍摘要（无边界标记版）"""
        lines = []
        for i, beat in enumerate(beats, 1):
            summary = beat.get('summary', '')
            entry = beat.get('entry_state', '')
            exit_state = beat.get('exit_state', '')
            
            lines.append(f"情节节点 {i}:")
            lines.append(f"  起始状态：{entry}")
            lines.append(f"  核心内容：{summary}")
            lines.append(f"  收束状态：{exit_state}")
            lines.append("")
        
        return "\n".join(lines)
    
    def _build_characters_info(self, entities: List[Any]) -> str:
        """构建角色信息摘要"""
        if not entities:
            return "（无特定角色）"
        
        lines = []
        for entity in entities:
            char = getattr(entity, 'character', None)
            if char:
                name = getattr(char, 'name', '未知')
                desc = getattr(char, 'static_prompt', '') or getattr(char, 'description', '')
                lines.append(f"- {name}: {desc[:100] if desc else '（无详细描述）'}")
        
        return "\n".join(lines) if lines else "（无特定角色）"
    
    def _build_relationships_info(self, relationships: List[Any]) -> str:
        """构建关系信息摘要"""
        if not relationships:
            return "（无特定关系）"
        
        lines = []
        for rel in relationships:
            source = getattr(getattr(rel, 'source_character', None), 'name', '?')
            target = getattr(getattr(rel, 'target_character', None), 'name', '?')
            rel_type = getattr(rel, 'relation_type', '未知关系')
            affinity = getattr(rel, 'affinity_score', 0)
            
            # 亲和度描述
            if affinity <= -50:
                affinity_desc = "敌对"
            elif affinity <= -20:
                affinity_desc = "不信任"
            elif affinity < 20:
                affinity_desc = "中立"
            elif affinity < 50:
                affinity_desc = "友好"
            else:
                affinity_desc = "亲密"
            
            lines.append(f"- {source} ↔ {target}: {rel_type}（{affinity_desc}）")
        
        return "\n".join(lines) if lines else "（无特定关系）"
    
    def _parse_sketch_structure(
        self,
        sketch_text: str,
        beats: List[dict],
    ) -> Tuple[List[TurnMarker], List[Dict[str, Any]]]:
        """解析 Sketch 中的结构化数据（转折点映射）"""
        turn_markers = []
        emotion_arc = []
        
        try:
            # 尝试从文本末尾提取 JSON
            # 查找最后一个 ```json 块
            json_start = sketch_text.rfind("```json")
            if json_start == -1:
                json_start = sketch_text.rfind("```")
            
            if json_start != -1:
                json_text = sketch_text[json_start:]
                # 清理 markdown 标记
                json_text = json_text.replace("```json", "").replace("```", "").strip()
                
                data = json.loads(json_text)
                
                # 解析 turn_markers
                raw_markers = data.get("turn_markers", [])
                for marker in raw_markers:
                    beat_index = marker.get("beat_index", 0)
                    if 1 <= beat_index <= len(beats):
                        turn_markers.append(TurnMarker(
                            beat_index=beat_index,
                            beat_id=beats[beat_index - 1].get("beat_id", f"beat-{beat_index}"),
                            position_percent=marker.get("position_percent", 0.0),
                            transition_type=marker.get("transition_type", "未知"),
                            description=marker.get("description", ""),
                        ))
                
                # 解析 emotion_arc
                emotion_arc = data.get("emotion_arc", [])
            
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"[SketchGenerator] 解析结构化数据失败: {e}")
            # 如果解析失败，根据节拍数生成默认的均匀分布
            for i, beat in enumerate(beats, 1):
                turn_markers.append(TurnMarker(
                    beat_index=i,
                    beat_id=beat.get("beat_id", f"beat-{i}"),
                    position_percent=(i / len(beats)) * 100,
                    transition_type="默认",
                    description=beat.get("summary", "")[:50],
                ))
        
        return turn_markers, emotion_arc


async def generate_sketch_for_alignment(
    chapter: Any,
    book: Any,
    beats: List[dict],
    entities: List[Any],
    relationships: List[Any],
    api_key: str,
    base_url: str,
    model: str,
    word_count: int,
    previous_summary: Optional[str] = None,
    anchor_pov: Optional[str] = None,
) -> SketchResult:
    """
    便捷函数：生成用于对抗校对的速写短文
    
    这是双轨架构中 Track B 的入口函数。
    """
    generator = SketchGenerator(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    
    return await generator.generate(
        chapter=chapter,
        book=book,
        beats=beats,
        entities=entities,
        relationships=relationships,
        word_count=word_count,
        previous_summary=previous_summary,
        anchor_pov=anchor_pov,
    )

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
SnapshotExtractorAgent - 章节末尾状态萃取 Agent (V3.6)

职责：
- 在章节发布后调用 reasoning_model 分析章节结尾
- 提取物理环境与角色动态为 WorldTerminalState 结构化对象
- 存储到数据库并与 chapter_id 关联

业务场景：
- 章节发布流程中自动触发
- 使用 reasoning_model 进行深度分析
- 生成 WorldTerminalState 作为下一章的初始约束

数据流：
Chapter Content + Character List → LLM Extraction → WorldTerminalState → DB Storage
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from backend.models import Chapter, Character
from backend.world_state_schemas import (
    WorldTerminalState,
    CharacterTerminalStatus,
    SceneTerminalStatus,
)
from backend.services.llm import call_llm
from backend.services.utils.prompt_logger import create_logger, PromptLogger

logger = logging.getLogger(__name__)


class SnapshotExtractorAgent:
    """
    世界状态快照萃取 Agent
    
    设计原则：
    1. 使用 reasoning_model 进行深度语义分析
    2. 强制 JSON 输出确保结构化
    3. 完整的日志记录支持
    4. 兼容旧版 snapshot 格式
    
    使用示例：
        agent = SnapshotExtractorAgent()
        state = await agent.extract(
            chapter_content=chapter.content_text,
            character_list=characters,
            reasoning_model="gpt-4o-mini",
            api_key=api_key,
            chapter_id=chapter.id,
            book_id=chapter.book_id
        )
    """
    
    def __init__(self):
        self.prompt_logger: Optional[PromptLogger] = None
    
    async def extract(
        self,
        chapter_content: str,
        character_list: List[Character],
        reasoning_model: str,
        api_key: str,
        base_url: Optional[str] = None,
        chapter_id: Optional[UUID] = None,
        book_id: Optional[UUID] = None,
        previous_state: Optional[WorldTerminalState] = None,
        enable_logging: bool = True,
    ) -> Optional[WorldTerminalState]:
        """
        提取章节末尾的世界终端状态
        
        Args:
            chapter_content: 章节正文内容
            character_list: 章节涉及的角色列表
            reasoning_model: 用于分析的模型（建议用推理模型）
            api_key: LLM API Key
            base_url: LLM Base URL
            chapter_id: 章节ID（用于日志）
            book_id: 书籍ID（用于日志）
            previous_state: 上一章的状态（可选，用于参考）
            enable_logging: 是否启用详细日志
            
        Returns:
            WorldTerminalState 对象，失败返回 None
        """
        # =================================================================
        # 初始化日志记录器
        # =================================================================
        if enable_logging and chapter_id:
            self.prompt_logger = create_logger(
                chapter_id=str(chapter_id),
                book_id=str(book_id) if book_id else None
            )
            self.prompt_logger.set_context(
                chapter_info={"id": str(chapter_id)} if chapter_id else None,
                book_info={"id": str(book_id)} if book_id else None
            )
            self.prompt_logger.start_stage("SNAPSHOT_EXTRACTION", iteration=1)
            self.prompt_logger.log_inputs(
                chapter_content_length=len(chapter_content) if chapter_content else 0,
                character_count=len(character_list),
                has_previous_state=bool(previous_state),
                reasoning_model=reasoning_model
            )
        
        try:
            # =================================================================
            # 构建提取 Prompt
            # =================================================================
            system_prompt, user_prompt = self._build_extraction_prompt(
                chapter_content=chapter_content,
                character_list=character_list,
                previous_state=previous_state
            )
            
            if self.prompt_logger:
                self.prompt_logger.log_prompts(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt[:2000] + "..." if len(user_prompt) > 2000 else user_prompt,
                    model=reasoning_model,
                    temperature=0.2,
                    max_tokens=3000,
                    prompt_label="SNAPSHOT_EXTRACTOR"
                )
            
            # =================================================================
            # 调用 LLM 进行提取
            # =================================================================
            logger.debug(f"[SnapshotExtractor] Extracting state with model: {reasoning_model}")
            
            import asyncio
            response = await asyncio.wait_for(
                call_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    api_key=api_key,
                    base_url=base_url,
                    model=reasoning_model,
                    temperature=0.2,
                    max_tokens=3000,
                    response_format={"type": "json_object"}
                ),
                timeout=120
            )
            
            # =================================================================
            # 解析提取结果
            # =================================================================
            extracted_state = self._parse_extraction_result(response)
            
            if extracted_state:
                # 设置元数据
                extracted_state.source_chapter_id = str(chapter_id) if chapter_id else None
                extracted_state.extracted_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
                
                logger.info(f"[SnapshotExtractor] State extracted successfully: {len(extracted_state.characters)} characters")
                
                if self.prompt_logger:
                    self.prompt_logger.log_outputs(
                        snapshot_keys=list(extracted_state.model_dump().keys()),
                        character_count=len(extracted_state.characters),
                        scene_location=extracted_state.scene.location_summary,
                        narrative_inertia=extracted_state.narrative_inertia[:100] + "..." if len(extracted_state.narrative_inertia) > 100 else extracted_state.narrative_inertia
                    )
                    self.prompt_logger.end_stage(success=True)
                    self.prompt_logger.finalize(
                        final_text_length=len(chapter_content) if chapter_content else 0,
                        total_iterations=1,
                        review_passed=True
                    )
                
                return extracted_state
            else:
                logger.warning("[SnapshotExtractor] Failed to parse extraction result")
                if self.prompt_logger:
                    self.prompt_logger.log_outputs(
                        raw_response=response[:500] if response else "Empty",
                        parse_error=True
                    )
                    self.prompt_logger.end_stage(success=False)
                    self.prompt_logger.finalize(
                        final_text_length=len(chapter_content) if chapter_content else 0,
                        total_iterations=1,
                        review_passed=False
                    )
                return None
                
        except asyncio.TimeoutError:
            logger.error("[SnapshotExtractor] Extraction timed out")
            if self.prompt_logger:
                self.prompt_logger.log_outputs(error="Timeout after 120s")
                self.prompt_logger.end_stage(success=False)
            return None
        except Exception as e:
            logger.error(f"[SnapshotExtractor] Extraction error: {e}")
            if self.prompt_logger:
                self.prompt_logger.log_outputs(error=str(e))
                self.prompt_logger.end_stage(success=False)
            return None
    
    def _build_extraction_prompt(
        self,
        chapter_content: str,
        character_list: List[Character],
        previous_state: Optional[WorldTerminalState] = None
    ) -> Tuple[str, str]:
        """
        构建状态提取 Prompt
        
        返回：
            (system_prompt, user_prompt)
        """
        # 格式化角色列表
        character_descriptions = []
        for char in character_list:
            if char:
                desc = f"【{char.name}】(ID: {char.id})"
                if char.static_prompt:
                    desc += f"\n  静态设定：{char.static_prompt[:100]}..."
                if char.dynamic_state:
                    desc += f"\n  动态状态：{char.dynamic_state}"
                character_descriptions.append(desc)
        
        character_list_text = "\n\n".join(character_descriptions) if character_descriptions else "无"
        
        # 上一章状态参考
        previous_state_text = ""
        if previous_state:
            previous_state_text = f"""
## 上一章末尾状态参考（仅作参照，以当前正文为准）
```json
{previous_state.to_compact_json()[:1000]}...
```
"""
        
        system_prompt = """你是世界状态审计员 (World State Auditor)。

你的任务：阅读章节正文，提取章节末尾的【世界终端状态快照 (World Terminal State)】。

核心原则：
1. **物理真实性优先**：所有状态必须基于正文中的实际描述，禁止推测或想象
2. **简洁直接**：使用物理状态描述，禁止文学修辞
3. **覆盖完整性**：必须覆盖所有曾在文中出现并产生互动的角色
4. **状态准确性**：如果角色已死亡或离开场景，必须标记为 inactive/dead

输出必须是合法的 JSON 格式，严格按照以下结构：

{
  "scene": {
    "location_summary": "当前详细地点描述 (如：废弃工厂地下二层)",
    "physical_anchors": ["遗落在地上的钥匙", "未熄灭的油灯"],
    "environment_tags": ["烟雾弥漫", "光线昏暗"],
    "damages": ["墙壁坍塌", "出口被封"],
    "atmosphere": "此刻场景氛围摘要"
  },
  "characters": {
    "角色名或ID": {
      "physical_condition": "active/injured/disabled/inactive/dead (必须是小写)",
      "current_location_desc": "在场景内的相对位置 (如：倒在角落/机甲驾驶舱内)",
      "immediate_intention": "此时此刻的意图 (如：寻找出口/等待救援)",
      "relationship_state": {"其他角色名": "关系描述"},
      "emotional_state": "情绪状态摘要，20字以内",
      "equipment_status": ["当前持有的物品/装备"]
    }
  },
  "narrative_inertia": "剧情惯性描述：延续的剧情趋势和情感状态"
}

字段说明：
- scene.location_summary: 精确描述场景位置
- scene.physical_anchors: 场景中仍需处理的关键物品或状态
- scene.environment_tags: 环境特征标签列表
- scene.damages: 场景破坏列表
- scene.atmosphere: 场景氛围，用于情感连贯性
- characters.{id}.physical_condition: 物理状态，必须是以下之一：
  - "active": 正常活跃
  - "injured": 受伤但仍能行动
  - "disabled": 重伤无法自主行动
  - "inactive": 离场/昏迷/暂时不在场
  - "dead": 死亡
- characters.{id}.current_location_desc: 相对于场景的位置描述
- characters.{id}.immediate_intention: 角色当前的即时意图
- characters.{id}.relationship_state: 与其他角色的关系状态字典
- characters.{id}.emotional_state: 情绪状态，简洁描述
- characters.{id}.equipment_status: 当前装备/持有物品列表
- narrative_inertia: 剧情惯性，描述当前的情感/关系/行动趋势

规则：
1. 如果某角色在文中已死亡，physical_condition 必须标记为 "dead"
2. 如果某角色已离开场景，physical_condition 必须标记为 "inactive"
3. 保持简洁，直接描述物理状态，禁止文学修辞
4. 必须覆盖所有曾在文中出现并产生互动的角色
5. 仅输出 JSON，不要任何解释性文字"""

        user_prompt = f"""请阅读以下章节正文，提取章节末尾的世界终端状态快照。

## 现有角色列表
{character_list_text}

{previous_state_text}

## 章节正文（末尾 3000 字）
```
{chapter_content[-3000:] if len(chapter_content) > 3000 else chapter_content}
```

请输出世界终端状态 JSON。重点关注：
1. 章节结束时每个角色的精确位置和物理状态
2. 场景中仍待处理的关键物品（physical_anchors）
3. 当前的情感氛围和剧情趋势（narrative_inertia）
4. 角色之间的关系状态变化"""

        return system_prompt, user_prompt
    
    def _parse_extraction_result(self, raw_result: str) -> Optional[WorldTerminalState]:
        """
        解析 LLM 提取结果
        
        Args:
            raw_result: LLM 返回的原始文本
            
        Returns:
            WorldTerminalState 对象，解析失败返回 None
        """
        if not raw_result:
            return None
        
        text = raw_result.strip()
        
        # 尝试多种方式提取 JSON
        candidates = []
        
        # 1. 直接尝试解析
        if text:
            candidates.append(text)
        
        # 2. 提取代码块中的 JSON
        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
        
        # 3. 提取花括号包裹的内容
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidates.append(text[first_brace : last_brace + 1].strip())
        
        # 尝试解析每个候选
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                
                # 验证必要字段
                if not isinstance(parsed, dict):
                    continue
                
                # 构建 WorldTerminalState
                state = self._normalize_state(parsed)
                if state:
                    return state
                    
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.debug(f"[SnapshotExtractor] JSON parse failed: {e}")
                continue
        
        return None
    
    def _normalize_state(self, parsed: Dict[str, Any]) -> Optional[WorldTerminalState]:
        """
        规范化解析后的状态数据
        """
        try:
            # 解析场景状态
            scene_data = parsed.get("scene", {})
            scene = SceneTerminalStatus(
                location_summary=scene_data.get("location_summary", ""),
                physical_anchors=self._ensure_string_list(scene_data.get("physical_anchors")),
                environment_tags=self._ensure_string_list(scene_data.get("environment_tags")),
                damages=self._ensure_string_list(scene_data.get("damages")),
                atmosphere=scene_data.get("atmosphere", "")
            )
            
            # 解析角色状态
            characters = {}
            char_data = parsed.get("characters", {})
            for char_id, char_info in char_data.items():
                if isinstance(char_info, dict):
                    characters[str(char_id)] = CharacterTerminalStatus(
                        physical_condition=char_info.get("physical_condition", "active"),
                        current_location_desc=char_info.get("current_location_desc", ""),
                        immediate_intention=char_info.get("immediate_intention", ""),
                        relationship_state=char_info.get("relationship_state", {}),
                        emotional_state=char_info.get("emotional_state", ""),
                        equipment_status=self._ensure_string_list(char_info.get("equipment_status"))
                    )
            
            return WorldTerminalState(
                scene=scene,
                characters=characters,
                narrative_inertia=parsed.get("narrative_inertia", ""),
                version="3.6"
            )
            
        except Exception as e:
            logger.warning(f"[SnapshotExtractor] Normalization failed: {e}")
            return None
    
    def _ensure_string_list(self, value: Any) -> List[str]:
        """确保值为字符串列表"""
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        return []


# =============================================================================
# 便捷函数
# =============================================================================

async def extract_world_terminal_state(
    chapter_content: str,
    character_list: List[Character],
    reasoning_model: str,
    api_key: str,
    base_url: Optional[str] = None,
    chapter_id: Optional[UUID] = None,
    book_id: Optional[UUID] = None,
    previous_state: Optional[WorldTerminalState] = None,
) -> Optional[WorldTerminalState]:
    """
    便捷函数：提取世界终端状态
    
    使用示例：
        state = await extract_world_terminal_state(
            chapter_content=chapter.content_text,
            character_list=characters,
            reasoning_model="gpt-4o-mini",
            api_key=api_key,
            chapter_id=chapter.id
        )
    """
    agent = SnapshotExtractorAgent()
    return await agent.extract(
        chapter_content=chapter_content,
        character_list=character_list,
        reasoning_model=reasoning_model,
        api_key=api_key,
        base_url=base_url,
        chapter_id=chapter_id,
        book_id=book_id,
        previous_state=previous_state
    )

"""
WorldTerminalState Schema 定义 - V3.6 状态驱动持久化

职责：定义用于存储世界终端状态的 Pydantic 模型

业务场景：
- 章节发布时提取世界状态快照
- 跨章节状态连续性约束
- 物理现实的持久化追踪

数据流：
- 章节发布 → SnapshotExtractorAgent 提取 → 存储到 chapter.world_snapshot
- 下一章生成 → ASSEMBLING_CONTEXT 加载 → 注入到 Planning/Drafting
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CharacterTerminalStatus(BaseModel):
    """
    角色终端状态 - 章节末尾的角色物理与心理状态快照
    
    业务含义：
    - 记录角色在章节结束时的精确状态
    - 作为下一章规划时的强制约束条件
    - 防止角色状态在章节间发生"瞬移"或突变
    """
    physical_condition: str = Field(
        default="active",
        description="物理状态: active(活跃)/injured(受伤)/disabled(无法行动)/inactive(离场)/dead(死亡)"
    )
    current_location_desc: str = Field(
        default="",
        description="当前位置描述，如'在机甲驾驶舱内'、'倒在废墟中'"
    )
    immediate_intention: str = Field(
        default="",
        description="即时意图，如'寻找出口'、'等待救援'、'准备反击'"
    )
    relationship_state: Dict[str, str] = Field(
        default_factory=dict,
        description="与其他角色的关系状态，键为角色名，值为关系描述"
    )
    emotional_state: str = Field(
        default="",
        description="情绪状态摘要，20字以内"
    )
    equipment_status: List[str] = Field(
        default_factory=list,
        description="当前装备/持有物品列表"
    )
    
    @field_validator('physical_condition')
    @classmethod
    def validate_condition(cls, v: str) -> str:
        valid_conditions = [
            "active", "injured", "disabled", "inactive", "dead",
            "昏迷", "轻伤", "重伤", "正常", "离场", "死亡"
        ]
        if v and v.lower() not in [c.lower() for c in valid_conditions]:
            # 允许自定义值，但记录警告
            pass
        return v


class SceneTerminalStatus(BaseModel):
    """
    场景终端状态 - 章节末尾的场景物理环境快照
    
    业务含义：
    - 记录章节结束时的精确场景状态
    - 包括位置、环境变化、待处理物品等
    - 确保下一章的场景描述具有物理连续性
    """
    location_summary: str = Field(
        default="",
        description="位置摘要，如'废弃工厂地下二层'、'机甲格纳库'"
    )
    physical_anchors: List[str] = Field(
        default_factory=list,
        description="物理锚点列表：场景中仍需处理的关键物品或状态"
    )
    environment_tags: List[str] = Field(
        default_factory=list,
        description="环境标签：如['烟雾弥漫', '光线昏暗', '温度极高']"
    )
    damages: List[str] = Field(
        default_factory=list,
        description="场景破坏列表：如['墙壁坍塌', '出口被封']"
    )
    atmosphere: str = Field(
        default="",
        description="氛围描述，用于保持情感连贯性"
    )
    
    @field_validator('physical_anchors', 'environment_tags', 'damages', mode='before')
    @classmethod
    def ensure_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v else []
        return list(v)


class WorldTerminalState(BaseModel):
    """
    世界终端状态 - 章节末尾的完整世界状态快照
    
    业务含义：
    - 封装场景状态和所有在场角色的终端状态
    - 作为跨章节物理连续性的权威数据源
    - 在 Planning 阶段作为不可违背的约束条件注入
    
    使用示例：
        # 提取状态
        state = await extractor.extract(chapter_content, characters)
        chapter.world_snapshot = state.model_dump()
        
        # 加载状态
        state = WorldTerminalState.from_chapter_snapshot(chapter.world_snapshot)
    """
    scene: SceneTerminalStatus = Field(
        default_factory=SceneTerminalStatus,
        description="场景终端状态"
    )
    characters: Dict[str, CharacterTerminalStatus] = Field(
        default_factory=dict,
        description="角色终端状态字典，键为角色ID或名称"
    )
    narrative_inertia: str = Field(
        default="",
        description="叙事惯性：剧情趋势和情感状态的延续描述"
    )
    extracted_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="状态提取时间戳"
    )
    source_chapter_id: Optional[str] = Field(
        default=None,
        description="源章节ID"
    )
    source_chapter_number: Optional[int] = Field(
        default=None,
        description="源章节序号"
    )
    
    # 元数据字段
    version: str = Field(
        default="3.6",
        description="Schema 版本"
    )
    
    @model_validator(mode='after')
    def validate_consistency(self):
        """验证状态一致性"""
        # 确保至少有一个角色或场景信息
        if not self.characters and not self.scene.location_summary:
            # 允许空状态（如第一章），但记录警告
            pass
        return self
    
    def to_compact_json(self) -> str:
        """
        返回压缩的 JSON 格式，减少 Token 占用
        
        用于：Prompt 注入时最小化 Token 消耗
        """
        import json
        return json.dumps(
            self.model_dump(exclude={'extracted_at'}, mode='json'),
            ensure_ascii=False,
            separators=(',', ':')
        )
    
    def to_prompt_format(self) -> str:
        """
        转换为 Prompt 友好的格式
        
        返回结构化的文本描述，便于 LLM 理解约束
        """
        lines = [
            "## 【前一章末尾世界状态快照】",
            "",
            f"**场景位置**: {self.scene.location_summary or '未指定'}",
        ]
        
        if self.scene.environment_tags:
            lines.append(f"**环境特征**: {', '.join(self.scene.environment_tags)}")
        
        if self.scene.damages:
            lines.append(f"**场景破坏**: {', '.join(self.scene.damages)}")
        
        if self.scene.physical_anchors:
            lines.append(f"**待处理锚点**: {', '.join(self.scene.physical_anchors)}")
        
        if self.characters:
            lines.extend(["", "**角色状态**:"])
            for char_id, char_status in self.characters.items():
                condition = char_status.physical_condition
                location = char_status.current_location_desc
                intention = char_status.immediate_intention
                
                char_line = f"- {char_id}: 状态[{condition}]"
                if location:
                    char_line += f", 位置[{location}]"
                if intention:
                    char_line += f", 意图[{intention}]"
                lines.append(char_line)
        
        if self.narrative_inertia:
            lines.extend(["", f"**剧情惯性**: {self.narrative_inertia}"])
        
        lines.extend([
            "",
            "⚠️ **约束提醒**: Beat 1 的 entry_state 必须与上述状态保持 100% 连续性！",
            "⚠️ **角色离场检查**: 状态为 inactive/dead 的角色严禁在本章分配 Beat！"
        ])
        
        return "\n".join(lines)
    
    @classmethod
    def from_legacy_snapshot(cls, legacy_snapshot: Dict[str, Any]) -> "WorldTerminalState":
        """
        从旧版 world_snapshot 格式迁移
        
        兼容性方法：将现有的 world_snapshot dict 转换为新的 Schema
        """
        if not legacy_snapshot:
            return cls()
        
        # 解析场景状态
        scene_data = legacy_snapshot.get("scene_state", {})
        scene = SceneTerminalStatus(
            location_summary=scene_data.get("location", ""),
            physical_anchors=scene_data.get("active_anchors", []),
            damages=scene_data.get("damages", []),
            atmosphere=scene_data.get("current_state", "")
        )
        
        # 解析角色状态
        characters = {}
        char_snapshots = legacy_snapshot.get("character_snapshots", {})
        for char_id, char_data in char_snapshots.items():
            if isinstance(char_data, dict):
                characters[char_id] = CharacterTerminalStatus(
                    physical_condition=char_data.get("status", "active"),
                    current_location_desc=char_data.get("location", ""),
                    immediate_intention=char_data.get("immediate_intention", ""),
                    emotional_state=char_data.get("current_state", "")
                )
        
        return cls(
            scene=scene,
            characters=characters,
            narrative_inertia=legacy_snapshot.get("narrative_momentum", "")
        )
    
    @classmethod
    def from_chapter_snapshot(cls, snapshot: Optional[Dict[str, Any]]) -> Optional["WorldTerminalState"]:
        """
        从章节存储的 snapshot 解析
        
        尝试解析为新的 Schema，失败时回退到 legacy 格式转换
        """
        if not snapshot:
            return None
        
        try:
            # 尝试直接解析为新格式
            return cls.model_validate(snapshot)
        except Exception:
            # 回退到 legacy 格式转换
            try:
                return cls.from_legacy_snapshot(snapshot)
            except Exception:
                return None
    
    def get_active_characters(self) -> Dict[str, CharacterTerminalStatus]:
        """获取活跃状态的角色（非 inactive/dead）"""
        active = {}
        for char_id, status in self.characters.items():
            raw_condition = status.physical_condition
            condition_lower = raw_condition.lower()
            # 英文状态检查
            is_inactive_english = condition_lower in ["inactive", "dead"]
            # 中文状态检查
            is_inactive_chinese = raw_condition in ["离场", "死亡", "昏迷", "失去意识", "重伤无法行动"]
            if not is_inactive_english and not is_inactive_chinese:
                active[char_id] = status
        return active
    
    def get_character_location(self, char_id: str) -> Optional[str]:
        """获取指定角色的位置"""
        char = self.characters.get(char_id)
        if char:
            return char.current_location_desc or self.scene.location_summary
        return None
    
    def has_character(self, char_id: str) -> bool:
        """检查是否包含指定角色"""
        return char_id in self.characters


# =============================================================================
# 验证结果模型
# =============================================================================

class StateValidationViolation(BaseModel):
    """状态验证违规项"""
    violation_type: str = Field(description="违规类型")
    message: str = Field(description="违规描述")
    severity: str = Field(default="warning", description="严重程度: error/warning")
    involved_character: Optional[str] = Field(default=None, description="涉及的角色")
    
    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class StateValidationResult(BaseModel):
    """状态验证结果"""
    passed: bool = Field(description="是否通过验证")
    violations: List[StateValidationViolation] = Field(default_factory=list)
    warnings: List[StateValidationViolation] = Field(default_factory=list)
    
    @property
    def has_errors(self) -> bool:
        """是否包含错误级别的违规"""
        return any(v.severity == "error" for v in self.violations)
    
    @property
    def has_warnings(self) -> bool:
        """是否包含警告"""
        return len(self.warnings) > 0 or any(v.severity == "warning" for v in self.violations)


# =============================================================================
# 辅助函数
# =============================================================================

def merge_world_states(
    previous: Optional[WorldTerminalState],
    current: WorldTerminalState
) -> WorldTerminalState:
    """
    合并两个世界状态（用于增量更新场景）
    
    以 current 为基础，补充 previous 中未改变的信息
    """
    if not previous:
        return current
    
    # 角色状态合并：current 覆盖 previous
    merged_chars = dict(previous.characters)
    merged_chars.update(current.characters)
    
    # 场景状态合并
    merged_scene = previous.scene.model_copy(update={
        k: v for k, v in current.scene.model_dump().items() if v
    })
    
    return WorldTerminalState(
        scene=merged_scene,
        characters=merged_chars,
        narrative_inertia=current.narrative_inertia or previous.narrative_inertia,
        source_chapter_id=current.source_chapter_id,
        extracted_at=current.extracted_at
    )

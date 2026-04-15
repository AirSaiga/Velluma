"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

"""
Drafting 模块类型定义

职责：提供 drafting 阶段使用的数据类和类型定义，减少函数参数数量。
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Callable

from backend.schemas import DraftingFeatureFlags


@dataclass
class DraftingModels:
    """LLM 模型配置"""
    creative_model: str
    reasoning_model: str


@dataclass  
class DraftingContext:
    """起草上下文数据"""
    chapter: Any
    book: Any
    entities: List[Any]
    relationships: List[Any]
    word_count: int
    previous_summary: Optional[str] = None
    relevant_memories: Optional[List[Any]] = None
    locations: Optional[List[Any]] = None
    assets: Optional[List[Any]] = None


@dataclass
class DraftingOptions:
    """起草选项配置"""
    enable_qc: bool = True
    feature_flags: Optional[DraftingFeatureFlags] = None
    physical_state_lock: Optional[str] = None
    entity_spatial_ledger: Optional[Dict[str, Any]] = None
    chapter_assets_schema: str = ""


@dataclass
class DraftingCallbacks:
    """起草回调函数"""
    stats_callback: Optional[Callable] = None


@dataclass
class ProseGenerationState:
    """单 Beat 生成状态"""
    attempt: int = 0
    max_attempts: int = 1
    chunk: str = ""
    is_valid: bool = False
    current_temp: float = 0.75
    prompts_history: List[Dict] = None
    pending_hint: str = ""
    
    def __post_init__(self):
        if self.prompts_history is None:
            self.prompts_history = []


@dataclass
class BeatDraftResult:
    """Beat 草稿结果"""
    text: str
    prompts: List[Dict]
    success: bool = True
    error: Optional[str] = None


@dataclass
class BeatContext:
    """
    单个 Beat 的上下文信息。
    
    用于减少 _generate_single_beat_* 函数的参数数量。
    """
    beat: dict
    beat_idx: int
    total_beats: int
    scene_intent: dict
    subconscious: str
    
    @property
    def beat_number(self) -> int:
        """Beat 编号（从1开始）"""
        return self.beat_idx + 1
    
    @property
    def is_first(self) -> bool:
        """是否为第一个 Beat"""
        return self.beat_idx == 0
    
    @property
    def is_last(self) -> bool:
        """是否为最后一个 Beat"""
        return self.beat_idx == self.total_beats - 1
    
    @property
    def pov_character(self) -> str:
        """POV 角色"""
        return self.beat.get("pov_character", "主角")
    
    @property
    def pov_perception_state(self) -> str:
        """POV 感知状态"""
        return self.beat.get("pov_perception_state") or self.beat.get("entry_state") or "正常"
    
    @property
    def target_words(self) -> int:
        """目标字数"""
        t = self.beat.get("word_count_target") or self.beat.get("target_words")
        if isinstance(t, int) and t > 0:
            return t
        return max(200, 2000 // max(1, self.total_beats))  # 默认计算


@dataclass
class GenerationAttempt:
    """单次生成尝试记录"""
    attempt: int
    temperature: float
    system_prompt: str
    user_prompt: str
    stage: str = "PROSE_DRAFT"
    
    def to_dict(self, beat_index: int) -> Dict:
        """转换为字典格式（用于 prompts_history）"""
        return {
            "stage": f"{self.stage}_ATTEMPT_{self.attempt}",
            "beat_index": beat_index,
            "temperature": self.temperature,
            "system_prompt": self.system_prompt,
            "user_prompt": self.user_prompt,
        }

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
    api_key: str
    base_url: str


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

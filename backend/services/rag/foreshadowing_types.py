import logging
from typing import List, Optional, Tuple, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class HookStatus(str, Enum):
    CREATED = "created"
    OPEN = "open"
    ADDRESSED = "addressed"
    CLOSED = "closed"
    DROPPED = "dropped"


class HookPriority(str, Enum):
    MAIN_PLOT = "main_plot"
    SUB_PLOT = "sub_plot"
    ATMOSPHERE = "atmosphere"
    DETAIL = "detail"
    WORLD_BUILDING = "world_building"


class HookClosureType(str, Enum):
    EXPLICIT = "explicit"
    IMPLICIT = "implicit"
    PARTIAL = "partial"
    ABANDONED = "abandoned"


class HookMetadata(BaseModel):
    hook_id: str = Field(default="", description="伏笔 ID")
    ledger_key: str = Field(default="", description="账本键")
    content: str = Field(default="", description="伏笔内容")

    status: HookStatus = Field(default=HookStatus.OPEN, description="状态")
    priority: HookPriority = Field(default=HookPriority.SUB_PLOT, description="优先级")
    closure_type: Optional[HookClosureType] = Field(None, description="闭合类型")

    created_at_chapter: int = Field(default=0, description="创建章节")
    addressed_at_chapters: List[int] = Field(default_factory=list, description="提及章节")
    closed_at_chapter: Optional[int] = Field(None, description="闭合章节")

    character_names: List[str] = Field(default_factory=list, description="涉及角色")
    location_names: List[str] = Field(default_factory=list, description="涉及地点")
    keywords: List[str] = Field(default_factory=list, description="关键词")

    mention_count: int = Field(default=0, description="提及次数")
    last_mention_chapter: Optional[int] = Field(None, description="最后提及章节")

    urgency_score: float = Field(default=0.0, description="紧急度")
    relevance_score: float = Field(default=0.0, description="相关度")


class HookDetectionResult(BaseModel):
    hook_id: str
    ledger_key: str = ""
    content: str

    detected_in_chapter: int = 0
    detection_confidence: float = 0.0
    detection_method: str = ""

    matched_text: str = ""
    match_type: str = ""

    suggested_status: Optional[HookStatus] = None
    is_closure: bool = False


class HookClosureCheckResult(BaseModel):
    hook_id: str
    hook_content: str

    is_addressed: bool = False
    is_closed: bool = False

    addressed_in_text: str = ""
    closure_type: str = ""

    suggestion: str = ""
    severity: str = "info"


@dataclass
class HookScoringConfig:
    open_duration_weight: float = 0.3
    priority_weight: float = 0.25
    mention_count_weight: float = 0.15

    main_plot_score: float = 1.0
    sub_plot_score: float = 0.7
    atmosphere_score: float = 0.4
    detail_score: float = 0.2

    urgent_threshold: int = 10
    attention_threshold: int = 5

    character_match_bonus: float = 0.2

import logging
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum

from backend.services.rag.retrieval_types import (
    RetrievalStrategy,
    RetrievalResult,
)


logger = logging.getLogger(__name__)


class WorkflowStage(str, Enum):
    ASSEMBLING = "assembling"
    PLANNING = "planning"
    DRAFTING = "drafting"
    REVIEWING = "reviewing"
    REFINING = "refining"
    PUBLISHING = "publishing"


class RetrievalFailureMode(str, Enum):
    GRACEFUL_DEGRADE = "graceful_degrade"
    MINIMAL_CONTEXT = "minimal_context"
    RAISE_ERROR = "raise_error"


@dataclass
class WorkflowIntegrationConfig:
    default_strategy: RetrievalStrategy = RetrievalStrategy.BALANCED_REFERENCE

    stage_strategies: Dict[str, RetrievalStrategy] = field(default_factory=lambda: {
        WorkflowStage.ASSEMBLING.value: RetrievalStrategy.BALANCED_REFERENCE,
        WorkflowStage.PLANNING.value: RetrievalStrategy.BALANCED_REFERENCE,
        WorkflowStage.DRAFTING.value: RetrievalStrategy.BALANCED_REFERENCE,
        WorkflowStage.REVIEWING.value: RetrievalStrategy.CHARACTER_FOCUSED,
        WorkflowStage.REFINING.value: RetrievalStrategy.DEEP_DIVE,
    })

    max_context_lengths: Dict[str, int] = field(default_factory=lambda: {
        WorkflowStage.ASSEMBLING.value: 10000,
        WorkflowStage.PLANNING.value: 6000,
        WorkflowStage.DRAFTING.value: 8000,
        WorkflowStage.REVIEWING.value: 4000,
        WorkflowStage.REFINING.value: 5000,
    })

    failure_mode: RetrievalFailureMode = RetrievalFailureMode.GRACEFUL_DEGRADE

    enable_vector_search: bool = True
    enable_hook_detection: bool = True
    enable_explainability: bool = True

    cache_retrieval_results: bool = True
    cache_ttl_seconds: int = 300


class RetrievalCache:

    def __init__(self, ttl_seconds: int = 300):
        self._cache: Dict[str, Tuple[RetrievalResult, datetime]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[RetrievalResult]:
        if key not in self._cache:
            return None

        result, timestamp = self._cache[key]
        age = (datetime.now(timezone.utc) - timestamp).total_seconds()

        if age > self._ttl:
            del self._cache[key]
            return None

        return result

    def set(self, key: str, result: RetrievalResult) -> None:
        self._cache[key] = (result, datetime.now(timezone.utc))

    def clear(self) -> None:
        self._cache.clear()

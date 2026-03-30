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

from .enums import (
    PacingStyle,
    PovAperture,
    PovMode,
    ReasoningEffortLevel,
    WorkflowTier,
)
from .book import (
    BookBase,
    BookCreate,
    BookUpdate,
    BookResponse,
    WorldviewUpdate,
)
from .chapter import (
    ChapterBase,
    ChapterCreate,
    ChapterUpdate,
    ChapterResponse,
)
from .character import (
    CharacterBase,
    CharacterCreate,
    CharacterUpdate,
    CharacterResponse,
    CharacterDynamicStateUpdateRequest,
    CharacterDynamicStateUpdateResponse,
    RelationshipBase,
    RelationshipCreate,
    RelationshipUpdate,
    RelationshipResponse,
)
from .map import (
    MapLocationBase,
    MapLocationCreate,
    MapLocationUpdate,
    MapLocationResponse,
    ChapterMapLocationCreate,
    ChapterMapLocationResponse,
)
from .memory import (
    MemoryChunkBase,
    MemoryChunkCreate,
    MemoryChunkResponse,
)
from .beat import (
    PersistentStateAnchor,
    StoryBeatBase,
    StoryBeatCreate,
    StoryBeatUpdate,
    StoryBeatResponse,
    SceneIntentBase,
    SceneIntentCreate,
    SceneIntentUpdate,
    SceneIntentResponse,
    PlotLedgerBase,
    PlotLedgerCreate,
    PlotLedgerUpdate,
    PlotLedgerResponse,
)
from .generation import (
    ReasoningConfig,
    DraftingFeatureFlags,
    CharacterPhysicalState,
    DynamicContext,
    DynamicStateUpdateResult,
    MicroReviewResult,
    AGENTIC_DEFAULT_WORD_COUNT,
    AGENTIC_DEFAULT_MAX_ITERATIONS,
    AGENTIC_DEFAULT_RAG_TOP_K,
    AGENTIC_DEFAULT_RAG_ALPHA,
    AGENTIC_DEFAULT_RAG_BETA,
    AGENTIC_DEFAULT_RAG_GAMMA,
    AGENTIC_DEFAULT_RAG_LAMBDA,
    GenerateChapterAgenticRequest,
    ConfirmedStoryBeat,
    GenerateChapterAgenticPreviewResponse,
    GenerateChapterAgenticWithBeatsRequest,
)
from .misc import (
    FormatTextRequest,
    GenerateChapterRequest,
    OptimizeChapterRequest,
    OptimizeSelectionRequest,
    ChapterEntityLink,
    ChapterEntityCreate,
    ChapterPublishRequest,
    CharacterStateChange,
    ChapterPublishResponse,
    InspirationRequest,
    InspirationIdea,
    InspirationResponse,
    CritiqueRequest,
    CritiqueItem,
    CritiqueResponse,
    GoldenSnippetsUpdate,
    StyleBlacklistUpdate,
    ProxyConfig,
    ModelTestRequest,
    ModelTestResponse,
    RecommendRequest,
    IntentDrivenGenerateRequest,
    GenerateEmbeddingRequest,
)
from .world_state import (
    CharacterTerminalStatus,
    SceneTerminalStatus,
    WorldTerminalState,
    StateValidationViolation,
    StateValidationResult,
    merge_world_states,
)


def map_tension_to_workflow_tier(tension_level: int) -> WorkflowTier:
    from backend.services.orchestration.tier_mapper import map_tension_to_workflow_tier as _mapper
    return _mapper(tension_level)

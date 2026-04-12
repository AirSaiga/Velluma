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

from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FormatTextRequest(BaseModel):
    text: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "google/gemini-2.0-flash-001"


class GenerateChapterRequest(BaseModel):
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")


class OptimizeChapterRequest(BaseModel):
    chapter_id: UUID
    optimization_feedback: str = Field(..., min_length=1, description="用户优化建议")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


class OptimizeSelectionRequest(BaseModel):
    chapter_id: UUID
    selected_text: str = Field(..., min_length=1)
    context_before: str = Field(default="")
    context_after: str = Field(default="")
    user_instruction: str = Field(default="")
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


class ChapterEntityLink(BaseModel):
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterEntityCreate(BaseModel):
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterPublishRequest(BaseModel):
    api_key: Optional[str] = Field(None, min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    proxy_enabled: bool = Field(default=True)
    proxy_url: Optional[str] = None


class CharacterStateChange(BaseModel):
    character_id: UUID
    character_name: str
    old_state: str
    new_state: str


class ChapterPublishResponse(BaseModel):
    chapter_id: UUID
    status: str
    summary: Optional[str] = None
    character_updates: List[CharacterStateChange] = Field(default_factory=list)
    world_snapshot: Optional[dict] = Field(default=None, description="本次发布提取的世界状态快照")


class InspirationRequest(BaseModel):
    book_id: UUID
    chapter_id: UUID
    chapter_title: Optional[str] = None
    current_context_snippet: str = Field(..., description="最近几百字的半成品正文或当前场景的一句话简述")
    active_character_ids: List[str] = Field(default=[], description="当前场景涉及的角色 ID")
    author_intent: Optional[str] = Field(None, description="作者的创作意图")
    temperature: float = Field(default=0.75, ge=0.0, le=2.0)
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


class InspirationIdea(BaseModel):
    idea_type: Literal["plot_twist", "key_conflict", "new_hook", "smooth_narrative"] = Field(
        ..., description="点子类型：剧情转折 / 关键冲突 / 新设伏笔 / 平稳叙事"
    )
    title: str = Field(..., description="点子的简短标题")
    description: str = Field(..., description="百字左右的具体事件描述")
    impact: str = Field(..., description="这步棋对后续格局的影响/好处")


class InspirationResponse(BaseModel):
    inspirations: List[InspirationIdea] = Field(..., min_length=1)


class CritiqueRequest(BaseModel):
    chapter_content: str = Field(..., min_length=10, description="待审阅的章节内容")
    chapter_title: Optional[str] = Field(None, description="章节标题")
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class CritiqueItem(BaseModel):
    exact_quote: str
    type: str
    reader_feeling: str
    suggestion: str


class CritiqueResponse(BaseModel):
    comments: List[CritiqueItem]
    overall_praise: str


class GoldenSnippetsUpdate(BaseModel):
    golden_snippets: List[str]


class StyleBlacklistUpdate(BaseModel):
    style_blacklist: List[str]


class ProxyConfig(BaseModel):
    enabled: bool
    url: str


class ModelTestRequest(BaseModel):
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    reasoning_enabled: bool = Field(default=False)
    reasoning_effort: str = Field(default="medium")


class ModelTestResponse(BaseModel):
    success: bool
    message: str
    model_info: Optional[dict] = None
    reasoning_supported: Optional[bool] = None
    reasoning_message: Optional[str] = None
    response_time_ms: Optional[float] = None


class RecommendRequest(BaseModel):
    creative_intents: List[str] = Field(..., max_length=2, description="创作意图列表")
    chapter_goals: Optional[List[str]] = Field(None, description="章节目标列表")


class GenerateEmbeddingRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None

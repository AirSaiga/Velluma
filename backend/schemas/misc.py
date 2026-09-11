# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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

from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class FormatTextRequest(BaseModel):
    text: str


class GenerateChapterRequest(BaseModel):
    chapter_id: UUID
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")


class OptimizeChapterRequest(BaseModel):
    chapter_id: UUID
    optimization_feedback: str = Field(..., min_length=1, description="用户优化建议")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")


class OptimizeSelectionRequest(BaseModel):
    chapter_id: UUID
    selected_text: str = Field(..., min_length=1)
    context_before: str = Field(default="")
    context_after: str = Field(default="")
    user_instruction: str = Field(default="")
    # CP4.1 选区级改写（蓝图 §4.9）：结构化模式 + 可选语气
    # mode 可选，默认 rewrite（向后兼容旧调用）
    mode: Literal["rewrite", "describe", "expand", "compress", "tone_shift"] = Field(
        default="rewrite",
        description="改写模式：rewrite 改写 / describe 描写 / expand 扩写 / compress 缩写 / tone_shift 换语气",
    )
    tone: Optional[str] = Field(
        default=None,
        description="换语气时的目标语气（如 冷峻 / 诙谐 / 抒情），仅 mode=tone_shift 时生效",
    )


class ChapterEntityLink(BaseModel):
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterEntityCreate(BaseModel):
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterPublishRequest(BaseModel):
    pass


class CharacterStateChange(BaseModel):
    character_id: UUID
    character_name: str
    old_state: str
    new_state: str


class ExtractedCharacterInfo(BaseModel):
    """提取的人物信息"""
    name: str
    is_new: bool
    existing_id: Optional[UUID] = None
    description: str = ""
    role_type: str = "supporting"
    aliases: List[str] = Field(default_factory=list)
    first_appearance: bool = False
    importance_level: int = 3


class InferredRelationshipInfo(BaseModel):
    """推断的关系信息"""
    source_name: str
    target_name: str
    relation_type: str
    description: str = ""
    affinity_score: int = 0
    is_new: bool = True


class CharacterExtractionSummary(BaseModel):
    """人物提取摘要"""
    extracted_characters: List[ExtractedCharacterInfo] = Field(default_factory=list)
    new_characters_count: int = 0
    existing_characters_count: int = 0
    inferred_relationships: List[InferredRelationshipInfo] = Field(default_factory=list)
    chapter_entity_links: List[str] = Field(default_factory=list)


class ChapterPublishResponse(BaseModel):
    chapter_id: UUID
    status: str
    summary: Optional[str] = None
    character_updates: List[CharacterStateChange] = Field(default_factory=list)
    world_snapshot: Optional[dict] = Field(default=None, description="本次发布提取的世界状态快照")
    character_extraction: Optional[CharacterExtractionSummary] = Field(default=None, description="人物提取结果")


class InspirationRequest(BaseModel):
    book_id: UUID
    chapter_id: UUID
    chapter_title: Optional[str] = None
    current_context_snippet: str = Field(..., description="最近几百字的半成品正文或当前场景的一句话简述")
    active_character_ids: List[str] = Field(default=[], description="当前场景涉及的角色 ID")
    author_intent: Optional[str] = Field(None, description="作者的创作意图")
    temperature: float = Field(default=0.75, ge=0.0, le=2.0)


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
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class CritiqueItem(BaseModel):
    exact_quote: str
    type: str
    reader_feeling: str
    suggestion: str


class CritiqueResponse(BaseModel):
    comments: List[CritiqueItem]
    overall_praise: str


class ProxyConfig(BaseModel):
    enabled: bool
    url: str


class LLMProfileUpdate(BaseModel):
    """LLM profile 更新（reasoning / creative）；None 字段保持原值。

    api_key 传空字符串或 None 表示保持不变（GET 端点只返回掩码，不回传明文）。
    """
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None
    effort: Optional[str] = None


class EmbeddingConfigUpdate(BaseModel):
    """Embedding 配置更新；None 字段保持原值。dimensions 变更需重启后端且会重建向量列。

    follow_llm=true 时连接（api_key/base_url）跟随文本模型槽，自管 api_key/base_url
    被忽略（保留原值，关掉跟随即可切回）。
    """
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    dimensions: Optional[int] = None
    follow_llm: Optional[bool] = None


class DeaiConfigUpdate(BaseModel):
    """deai 去AI味小模型配置更新（deai/ 子项目，docs/deai-integration.md）；None 字段保持原值。

    api_key 传空字符串或 None 表示保持不变（GET 端点只返回掩码，不回传明文）。
    base_url 留空 = DashScope 原生端点（调优模型不支持 OpenAI 兼容入口）。
    """
    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None


class ModelConfigUpdate(BaseModel):
    """模型配置整体更新（设置面板保存），各节均为可选。"""
    reasoning: Optional[LLMProfileUpdate] = None
    creative: Optional[LLMProfileUpdate] = None
    wash: Optional[LLMProfileUpdate] = None  # 洗涤槽（可选；不配则跟随 creative）
    embedding: Optional[EmbeddingConfigUpdate] = None
    deai: Optional[DeaiConfigUpdate] = None  # 去AI味小模型（可选；未配置=零变化直通）
    proxy: Optional[ProxyConfig] = None


class ModelPriceEntry(BaseModel):
    """单个模型价目（元 / 百万 token）。cached_input 可缺省（=按 input 全价计，
    保守估算——厂商缓存命中价没查到时不填即可）。"""
    input: float = Field(ge=0)
    cached_input: Optional[float] = Field(default=None, ge=0)
    output: float = Field(ge=0)


class ModelPricesUpdate(BaseModel):
    """价目表整表覆写（PUT /system/model-prices）。键=模型名（与
    generation_runs.model_name 对齐）。空 prices=清空价目回到未计价态。"""
    prices: Dict[str, ModelPriceEntry]


class EmbeddingProbePayload(BaseModel):
    """连接测试时的向量模型表单覆盖值（未保存也能测）；api_key 留空沿用已保存 Key。"""
    model: Optional[str] = None
    base_url: Optional[str] = None
    dimensions: Optional[int] = None
    follow_llm: Optional[bool] = None
    api_key: Optional[str] = None


class DeaiTestRequest(BaseModel):
    """deai 小模型「试一试」（POST /system/deai/test）请求体。

    表单实时值探测（未保存也能测，同 embedding probe 契约）：
    model/api_key/base_url 留空沿用已保存配置；text 缺省用内置示例片段。
    """
    text: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class DeaiTestResponse(BaseModel):
    """deai 试一试结果。success=调用链走通（改写被采纳或契约§6 保底回退均算走通；
    保底不是失败——它证明闸门在工作）。skipped=true 表示根本没起调用（未配 Key 等）。
    """
    success: bool
    message: str
    input_text: str
    output_text: str
    applied: bool = False
    skipped: bool = False
    fallback_reason: str = ""
    warnings: List[str] = Field(default_factory=list)
    model: str = ""
    elapsed_ms: float = 0.0


class ModelTestRequest(BaseModel):
    # V4.1: 若留空则自动从 model_config.json 读取对应模型的推理配置
    reasoning_enabled: Optional[bool] = Field(default=None)
    reasoning_effort: Optional[str] = Field(default=None)
    # 向量模型探测覆盖值（设置面板表单实时值）；None = 探测已保存配置
    embedding: Optional[EmbeddingProbePayload] = None


class ModelTestResponse(BaseModel):
    success: bool
    message: str
    model_info: Optional[dict] = None
    reasoning_supported: Optional[bool] = None
    reasoning_message: Optional[str] = None
    response_time_ms: Optional[float] = None



class GenerateEmbeddingRequest(BaseModel):
    pass

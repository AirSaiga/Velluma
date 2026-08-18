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
文风体系 Pydantic schemas（Phase 1 CP2.2 新建）。

涵盖：
- StyleCard（文风卡：正面画像 + 负面清单 + 量化指标）
- AuthorSample（作者样本库）
- SystemCliche（系统禁词表）
- StyleExtract（Match My Style 提炼请求/响应）

业务场景：
- routes/style.py 的 API 端点用这些 schema 做请求/响应校验
- ContextEngine 读取 StyleCard 渲染 P0 文风段
"""

from datetime import datetime
from typing import Any, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================
# StyleCard（文风卡）
# ============================================================

class StyleCardBase(BaseModel):
    """文风卡基础字段。"""
    positive_profile: dict = Field(
        default_factory=dict,
        description="正面画像：句长节奏/词汇层级/语域/开头结尾习惯等",
    )
    negative_list: List[dict] = Field(
        default_factory=list,
        description="负面清单：[{word/phrase, alternative}]，每条禁令配正面替代",
    )
    dialogue_ratio_target: Optional[float] = Field(
        None, ge=0.0, le=1.0,
        description="对话占比目标（0-1）",
    )
    paragraph_rhythm: Optional[str] = Field(None, description="段落节奏说明")
    notes: Optional[str] = Field(None, description="备注")
    style_knobs: Optional[dict] = Field(
        None,
        description="意图旋钮档位（S4）：{rhythm|register|density|warmth: tier 1-5}，缺键=自动档；None=不改，{}=清空",
    )
    locked_keys: Optional[List[str]] = Field(
        None,
        description="画像字段锁：被锁字段不被「从样本提炼」覆盖；None=不改，[]=清空",
    )


class StyleCardCreate(StyleCardBase):
    """创建文风卡（书级或章级覆盖）。"""
    chapter_id: Optional[UUID] = Field(None, description="非空表示章级覆盖")


class StyleCardUpdate(BaseModel):
    """更新文风卡（所有字段可选）。"""
    positive_profile: Optional[dict] = None
    negative_list: Optional[List[dict]] = None
    dialogue_ratio_target: Optional[float] = Field(None, ge=0.0, le=1.0)
    paragraph_rhythm: Optional[str] = None
    notes: Optional[str] = None


class StyleCardResponse(StyleCardBase):
    """文风卡响应。"""
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# AuthorSample（作者样本库）
# ============================================================

class AuthorSampleBase(BaseModel):
    """作者样本基础字段。"""
    scene_type: str = Field("general", description="场景类型：dialogue/action/lyrical/suspense/general")
    content: str = Field(..., min_length=1, description="样本原文")
    source: str = Field("manual", description="来源：manual/golden_snippet/published_chapter")
    era: str = Field("recent", description="时期：recent=近期（进语料聚合）/early=早期（仅存档）")
    favorite: bool = Field(False, description="收藏（检索兜底流优先）")


class AuthorSampleCreate(AuthorSampleBase):
    """创建作者样本。"""
    chapter_id: Optional[UUID] = None


class AuthorSampleResponse(AuthorSampleBase):
    """作者样本响应。"""
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    word_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class AuthorSampleSearchRequest(BaseModel):
    """作者样本向量检索请求。"""
    query_text: str = Field(..., min_length=1, description="查询文本（向量化后检索）")
    scene_type: Optional[str] = None
    limit: int = Field(3, ge=1, le=10)


class AuthorSampleSearchHit(BaseModel):
    """向量检索单条命中。"""
    sample: AuthorSampleResponse
    distance: float = Field(..., description="cosine 距离（越小越相似）")


# ============================================================
# SystemCliche（系统禁词表）
# ============================================================

class SystemClicheBase(BaseModel):
    """系统禁词基础字段。"""
    pattern: str = Field(..., min_length=1, max_length=200, description="字面词或正则")
    is_regex: bool = Field(False, description="是否为正则表达式")
    language: str = Field("zh", description="语言：zh/en")
    category: str = Field("cliche", description="类别：cliche/house_voice/transition")
    severity: str = Field("warning", description="严重性：warning/blocker")
    alternative: Optional[str] = Field(None, description="替代建议")
    enabled: bool = Field(True)


class SystemClicheCreate(SystemClicheBase):
    pass


class SystemClicheUpdate(BaseModel):
    pattern: Optional[str] = Field(None, min_length=1, max_length=200)
    is_regex: Optional[bool] = None
    language: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    alternative: Optional[str] = None
    enabled: Optional[bool] = None


class SystemClicheResponse(SystemClicheBase):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# StyleCard 提炼（Match My Style）
# ============================================================

class StyleExtractRequest(BaseModel):
    """文风画像提炼请求（蓝图 §6.2）。"""
    samples: List[str] = Field(
        ..., min_length=1, max_length=5,
        description="作者样本原文（1-5 段，建议每段 200-2000 字）",
    )
    genre: Optional[str] = Field(None, description="题材（用于兜底画像）")


class StyleExtractResponse(BaseModel):
    """文风画像提炼响应。"""
    positive_profile: dict = Field(..., description="正面画像")
    negative_list: List[dict] = Field(..., description="负面清单")
    dialogue_ratio_target: Optional[float] = None
    paragraph_rhythm: Optional[str] = None
    degraded: Optional[dict] = Field(None, description="提炼降级标记（如有）")


# ============================================================
# 文风指纹（文风模块重构 S1 测量层，docs/style-module-redesign.md §7.2）
# ============================================================

class StyleFingerprintResponse(BaseModel):
    """文风指纹响应：语料聚合指纹 + 逐样本指纹 + 可选章指纹（对账用）。

    指纹 dict 结构见 services/style/fingerprint.py 模块头注释；
    low_confidence：样本 <3 条，指纹仅供参考（设计稿 §6.6 诚实红线）。
    """
    corpus: dict = Field(..., description="语料聚合指纹（全量，含修辞密度；仅 era=recent 样本）")
    samples: List[dict] = Field(..., description="逐样本轻量指纹 [{sample_id, fingerprint}]")
    sample_count: int = Field(..., description="有效样本数")
    low_confidence: bool = Field(..., description="样本尚少（<3），仅供参考")
    chapters: Optional[List[dict]] = Field(
        None,
        description="章指纹（with_chapters=true 时返回，实时计算，light 模式）",
    )
    reference: dict = Field(
        ...,
        description="对账参考区间 {cv_healthy: [lo, hi], dialogue_target: float|null}",
    )
    negative_hit_counts: dict = Field(
        default_factory=dict,
        description="负面清单台账：各禁词在近 10 章正文的命中次数（with_chapters=true 时计算）",
    )


class SamplesFromChaptersRequest(BaseModel):
    """从已发布章节收编作者样本（零状态坡道兜底通路，设计稿 §6.3）。"""
    max_chapters: int = Field(3, ge=1, le=10, description="最多收编章数")
    excerpt_chars: int = Field(2000, ge=200, le=8000, description="每章摘取字数上限")


# ============================================================
# 文风收件箱 / 试听 / 禁词扫描（S3 交互环）
# ============================================================

class StyleInboxAddRequest(BaseModel):
    """投递文风候选进收件箱（写作台「这不像我」等入口）。"""
    kind: str = Field("negative_candidate", description="候选类型：negative_candidate / sample_candidate")
    payload: dict = Field(..., description="kind 对应载荷（negative_candidate: {word, alternative?, source_text?}）")
    source: str = Field("writing_desk", description="来源标记：writing_desk / scan / audit")


class StyleInboxItemResponse(BaseModel):
    """收件箱条目。"""
    id: UUID
    book_id: UUID
    kind: str
    payload: dict
    status: str
    source: str
    created_at: datetime

    class Config:
        from_attributes = True


class StyleAuditionRequest(BaseModel):
    """试听请求（文风页试衣间）：给定段落 + 文风配置 → 走真实注入管线改写。

    style_override 非空时用其渲染画像/禁词（未保存的草稿配置可试听，
    A/B 对照的机制基础）；为空用已存书级文风卡。
    """
    text: str = Field(..., min_length=10, max_length=4000, description="待试听段落")
    style_override: Optional[StyleCardBase] = Field(None, description="草稿文风配置（不落库）")
    use_samples: bool = Field(True, description="是否注入作者笔迹示范（A/B 基线版传 False）")
    target_chars: int = Field(400, ge=80, le=2000, description="目标字数（约等于原段）")


class StyleScanNegativeRequest(BaseModel):
    """负面清单/三层禁词扫描（E3 审稿模式的数据源）。"""
    chapter_id: Optional[UUID] = Field(None, description="扫描该章正文（content_text 优先）")
    text: Optional[str] = Field(None, max_length=200000, description="直接给文本（与 chapter_id 二选一）")


# ============================================================
# 补全批次（完整落地）：样本时期/收藏、豁免、埋点
# ============================================================

class AuthorSamplePatchRequest(BaseModel):
    """样本局部更新（时期标记 / 收藏 / 场景类型 / 正文）。

    content 变更时路由层会重算 word_count 并重新向量化（旧向量与新文本
    不再同义，重向量化失败或未配置 embedding 时清空为 None——宁缺勿旧）。
    """
    era: Optional[str] = Field(None, pattern="^(recent|early)$", description="recent/early")
    favorite: Optional[bool] = None
    scene_type: Optional[str] = Field(
        None, pattern="^(dialogue|action|lyrical|suspense|general)$", description="场景类型"
    )
    content: Optional[str] = Field(None, min_length=1, description="样本正文（变更时重算字数并重向量化）")


class ClicheExemptionsUpdate(BaseModel):
    """系统陈词库本书豁免列表（整体覆盖写）。"""
    patterns: List[str] = Field(default_factory=list, description="被豁免的 SystemCliche pattern 列表")


class StyleEventRequest(BaseModel):
    """文风使用埋点（本地 JSONL，无外部上报——桌面应用隐私边界内）。"""
    kind: str = Field(..., max_length=50, description="事件：audition_run/golden_to_sample/not_like_me/inbox_confirm/inbox_dismiss/apply_preset")
    detail: Optional[str] = Field(None, max_length=200)


# ============================================================
# ChapterCard（章节卡，CP2.3 用，先在这里定义）
# ============================================================

class MustHitEvent(BaseModel):
    """必达事件。"""
    event: str
    emotion: Optional[str] = None
    must: bool = True


class ChapterCardBase(BaseModel):
    """章节卡基础字段（蓝图 §4.1.3）。"""
    chapter_number: int = Field(..., ge=1)
    purpose: Optional[str] = Field(None, description="一句话主旨（场景化语言）")
    must_hit_events: List[dict] = Field(default_factory=list)
    involved_characters: List[dict] = Field(default_factory=list)
    foreshadow_ops: List[dict] = Field(default_factory=list)
    continuity: dict = Field(default_factory=dict)
    word_target: int = Field(3000, ge=100)
    pacing: str = Field("medium")
    tension: int = Field(5, ge=1, le=10)
    status: str = Field("draft")


class ChapterCardCreate(ChapterCardBase):
    chapter_id: Optional[UUID] = None


class ChapterCardUpdate(BaseModel):
    purpose: Optional[str] = None
    must_hit_events: Optional[List[dict]] = None
    involved_characters: Optional[List[dict]] = None
    foreshadow_ops: Optional[List[dict]] = None
    continuity: Optional[dict] = None
    word_target: Optional[int] = Field(None, ge=100)
    pacing: Optional[str] = None
    tension: Optional[int] = Field(None, ge=1, le=10)
    status: Optional[str] = None


class ChapterCardResponse(ChapterCardBase):
    id: UUID
    book_id: UUID
    chapter_id: Optional[UUID] = None
    style_override_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

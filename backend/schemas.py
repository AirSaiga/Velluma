"""
Pydantic 验证模型
定义 API 请求和响应的数据结构
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, Field, model_validator

PacingStyle = Literal["slow_burn", "balanced", "fast_paced"]


# ============================================================
# 书籍 Schema 层 - Book 实体的事务封装
# ============================================================
# 验证规则设计意图：
#   - min_length=1 防止空标题（空标题在业务上无意义）
#   - max_length=500 是 UI 渲染约束，避免前端布局崩溃
#   - worldview_settings 使用 default_factory=dict 确保字段始终存在（避免 None 判断）
#
# 序列化/反序列化业务规则：
#   - from_attributes = True 启用 ORM 模式，允许从 SQLAlchemy 模型直接构造
#   - 这是一个"只读"配置，写入时仍走 Create/Update 模型
class BookBase(BaseModel):
    """书籍基础模型

    业务规则：
    - title 必填，非空字符串（防止空格标题绕过验证）
    - genre 可选但有长度约束（保持分类体系一致性）
    - worldview_settings 默认为空字典（不是 None），简化前端渲染逻辑
    """
    title: str = Field(..., min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    global_sys_prompt: Optional[str] = None
    core_motifs_taboos: Optional[str] = None
    worldview_settings: Optional[dict] = Field(default_factory=dict)
    golden_snippets: Optional[list] = Field(default_factory=list)
    style_blacklist: Optional[list] = Field(default_factory=list)


class BookCreate(BookBase):
    """创建书籍请求模型

    设计意图：
    - 继承 BookBase 所有验证规则
    - 创建时不需要传 id（后端生成 UUID）
    - 不需要传 created_at（数据库自动填充）
    """
    pass


class BookUpdate(BaseModel):
    """更新书籍请求模型

    设计意图：
    - 所有字段 Optional，允许部分更新
    - min_length=1 确保更新时不能改为空标题
    - worldview_settings 允许设为 None（表示"清除"设定）

    警示：
    - Pydantic 默认行为：传 {} 会被解析为 None（如果字段 Optional）
    - 若需区分"不传"和"传空字典"，需自定义 validator
    """
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    global_sys_prompt: Optional[str] = None
    core_motifs_taboos: Optional[str] = None
    worldview_settings: Optional[dict] = None
    golden_snippets: Optional[list] = None
    style_blacklist: Optional[list] = None


class BookResponse(BookBase):
    """书籍响应模型

    业务规则：
    - 包含完整信息：id（前端路由关键字段）+ created_at（时间戳展示）
    - 响应模型应该稳定，避免向存量客户端暴露新字段导致解析失败
    """
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class WorldviewUpdate(BaseModel):
    """世界观设定更新请求

    用途：专门用于快速更新世界观设定，避免传递整个 Book 对象
    """
    worldview_settings: dict = Field(default_factory=dict)


class MapLocationBase(BaseModel):
    """地图/地点基础模型"""
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None


class MapLocationCreate(MapLocationBase):
    """创建地点请求模型"""
    book_id: UUID


class MapLocationUpdate(BaseModel):
    """更新地点请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None


class MapLocationResponse(MapLocationBase):
    """地点响应模型"""
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ChapterMapLocationCreate(BaseModel):
    """章节-地点关联创建请求"""
    location_id: UUID


class ChapterMapLocationResponse(BaseModel):
    """章节-地点关联响应"""
    id: UUID
    chapter_id: UUID
    location_id: UUID
    location: MapLocationResponse

    class Config:
        from_attributes = True


# ============================================================
# 章节 Schema 层 - 创作工作流的状态机
# ============================================================
# 验证规则设计意图：
#   - chapter_number: ge=1 确保章节编号从 1 开始（业务规范）
#   - revision_count: default=0 新章节初始重写次数为 0
#   - status: default="draft" 确保新章节处于可编辑状态
#
# 序列化/反序列化业务规则：
#   - content_text/draft_text 在响应中可能很长，需考虑分页或压缩
#   - review_feedback 是 JSONB，响应时保持结构化（前端可解析）
class ChapterBase(BaseModel):
    """章节基础模型

    业务规则：
    - chapter_number 必须是正整数（负数或零无意义）
    - status 字段虽无枚举约束，但业务层应限制为 ["draft", "published"]
    - review_feedback 默认为空字典（不是 None），简化前端渲染
    """
    chapter_number: int = Field(..., ge=1)
    chapter_name: Optional[str] = Field(None, max_length=200)
    title: Optional[str] = Field(None, max_length=500)
    outline_text: Optional[str] = None
    content_text: Optional[str] = None
    draft_text: Optional[str] = None
    summary: Optional[str] = None
    review_feedback: Optional[dict] = Field(default_factory=dict)
    map_activity_range: Optional[str] = None
    tension_level: int = Field(default=5, ge=1, le=10)
    pacing_style: PacingStyle = Field(default="balanced")
    revision_count: int = Field(default=0)
    status: str = Field(default="draft")


class ChapterCreate(ChapterBase):
    """创建章节请求模型

    业务规则：
    - 必须指定 book_id（章节必须归属于某本书）
    - book_id 通常来自 URL path 参数，后端应校验其存在性
    """
    book_id: UUID


class ChapterUpdate(BaseModel):
    """更新章节请求模型

    业务规则：
    - chapter_number 可更新但需确保唯一性（同一书籍内）
    - status 更新时需触发业务逻辑（发布时锁定内容）
    - content_text 更新受限：已发布章节不应允许修改（业务层校验）

    警示：
    - 不允许更新 draft_text/revision_count（这些由生成流程控制）
    - 若前端传了这些字段，应被忽略而非报错（使用 Field + exclude）
    """
    chapter_number: Optional[int] = Field(None, ge=1)
    chapter_name: Optional[str] = Field(None, max_length=200)
    title: Optional[str] = Field(None, max_length=500)
    outline_text: Optional[str] = None
    content_text: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[str] = None
    map_activity_range: Optional[str] = None
    tension_level: Optional[int] = Field(None, ge=1, le=10)
    pacing_style: Optional[PacingStyle] = None
    chapter_assets_schema: Optional[str] = None


class ChapterResponse(ChapterBase):
    """章节响应模型

    业务规则：
    - 包含 book_id（前端可能需要构建跳转链接）
    - 包含 created_at（用于排序或展示）
    """
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 角色 Schema 层 - 双态模型的设计考量
# ============================================================
# 验证规则设计意图：
#   - name: min_length=1 防止匿名角色（业务要求）
#   - importance_level: ge=1, le=10 限制在固定范围内（前端 UI 组件依赖）
#
# 序列化/反序列化业务规则：
#   - dynamic_state_history 在响应中返回（前端需要展示状态演变）
#   - Create 时不需要 history（后端初始化为空列表）
class CharacterBase(BaseModel):
    """角色基础模型

    业务规则：
    - name 必填且非空（角色必须有标识）
    - aliases 默认为空列表（角色可以没有别名）
    - importance_level 默认为 1（新角色默认低优先级）
    """
    name: str = Field(..., min_length=1, max_length=200)
    aliases: List[str] = Field(default_factory=list)
    static_prompt: Optional[str] = None
    dynamic_state: Optional[str] = None
    importance_level: int = Field(default=1, ge=1, le=10)


class CharacterCreate(CharacterBase):
    """创建角色请求模型

    业务规则：
    - 必须指定 book_id（角色必须归属于某本书）
    - 初始化时 dynamic_state_history 为空（由后续章节发布触发更新）
    """
    book_id: UUID


class CharacterUpdate(BaseModel):
    """更新角色请求模型

    业务规则：
    - 所有字段 Optional，允许部分更新
    - importance_level 范围校验防止前端传入非法值

    警示：
    - dynamic_state_history 不在此模型中（只能通过专用接口更新）
    - 这样做是为了将"状态更新"与"基本信息更新"分离，职责清晰
    """
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    aliases: Optional[List[str]] = None
    static_prompt: Optional[str] = None
    dynamic_state: Optional[str] = None
    importance_level: Optional[int] = Field(None, ge=1, le=10)


class CharacterResponse(CharacterBase):
    """角色响应模型

    业务规则：
    - 包含完整的 dynamic_state_history（用于前端状态展示）
    - 响应体积可能较大（history 累积后），考虑分页或压缩策略
    """
    id: UUID
    book_id: UUID
    created_at: datetime
    dynamic_state_history: List[dict] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CharacterDynamicStateUpdateRequest(BaseModel):
    """角色动态状态更新请求模型

    用途：专门用于 LLM 驱动的状态更新（而非手动编辑）

    业务规则：
    - chapter_id 必填（状态更新必须关联到特定章节）
    - api_key/base_url/model 用于调用 LLM 生成新的动态状态
    - 默认使用 gpt-4o-mini（成本优化）

    数据流：
    - 前端提交 → 后端提取角色信息 + 章节上下文 → 调用 LLM → 解析结果 → 更新 DB
    """
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    manual_current_state: Optional[str] = None
    proxy_enabled: bool = Field(default=True)
    proxy_url: Optional[str] = None


class CharacterDynamicStateUpdateResponse(BaseModel):
    """角色动态状态更新响应模型

    业务规则：
    - 返回 old_dynamic_state 和 new_dynamic_state（便于前端展示变化）
    """
    character_id: UUID
    old_dynamic_state: str
    new_dynamic_state: str


# ============================================================
# 关系 Schema 层 - 图谱构建的边界控制
# ============================================================
# 验证规则设计意图：
#   - affinity_score: ge=-100, le=100 限制在固定范围内（标准化处理）
#   - relation_type: max_length=100 防止过长的关系类型字符串
#
# 序列化/反序列化业务规则：
#   - is_public 默认为 True（大多数关系应对 LLM 可见）
#   - 关系创建后需触发图谱重建（若有缓存）
class RelationshipBase(BaseModel):
    """角色关系基础模型

    业务规则：
    - source_char_id ≠ target_char_id 需业务层校验（防止自环）
    - affinity_score 范围 [-100, 100]：负数=敌对，0=中立，正数=友好
    - is_public 控制 LLM 是否能"知道"这段关系
    """
    source_char_id: UUID
    target_char_id: UUID
    relation_type: str = Field(..., max_length=100)
    affinity_score: int = Field(default=0, ge=-100, le=100)
    interaction_prompt: Optional[str] = None
    is_public: bool = Field(default=True)


class RelationshipCreate(RelationshipBase):
    """创建角色关系请求模型

    设计意图：
    - 继承所有验证规则
    - 后端应校验 source_char_id 和 target_char_id 属于同一本书
    """
    pass


class RelationshipUpdate(BaseModel):
    """更新角色关系请求模型

    业务规则：
    - 仅允许更新关系属性，不允许修改 source/target（那是另一段关系）
    - 字段均为 Optional，支持部分更新
    """
    relation_type: Optional[str] = Field(None, max_length=100)
    affinity_score: Optional[int] = Field(None, ge=-100, le=100)
    interaction_prompt: Optional[str] = None
    is_public: Optional[bool] = None


class RelationshipResponse(RelationshipBase):
    """角色关系响应模型

    业务规则：
    - 包含 created_at（用于排序或展示）
    """
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# 记忆 Schema 层 - RAG 系统的输入契约
# ============================================================
# 验证规则设计意图：
#   - chunk_text: min_length=1 防止空记忆（检索无意义）
#   - chapter_id 可选（支持全局记忆）
#
# 序列化/反序列化业务规则：
#   - embedding 不在 Schema 中（向量由后端异步生成，前端不需要知道）
#   - 创建响应时不返回 embedding（减少响应体积）
class MemoryChunkBase(BaseModel):
    """记忆片段基础模型

    业务规则：
    - chunk_text 必填且非空（空文本无法向量化）
    - chapter_id 可选：None 表示全局记忆，否则为章节级记忆
    """
    chunk_text: str = Field(..., min_length=1)
    chapter_id: Optional[UUID] = None


class MemoryChunkCreate(MemoryChunkBase):
    """创建记忆片段请求模型

    业务规则：
    - 必须指定 book_id（记忆必须归属于某本书）
    - embedding 由后端在异步任务中生成（不在请求中）
    """
    book_id: UUID


class MemoryChunkResponse(MemoryChunkBase):
    """记忆片段响应模型

    业务规则：
    - 包含 book_id 和 created_at（用于检索或展示）
    - 不包含 embedding（前端不需要，后端向量检索返回时再给）
    """
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class StoryBeatBase(BaseModel):
    """
    故事节拍 (Story Beat) 的基础 Schema。

    业务含义：
    - 代表章节内的最小剧情单元，是 Agentic 工作流的核心数据模型
    - 用于支撑"并行生成 → 统稿"的工作流模式

    字段说明：
    - chapter_id: 所属章节 ID
    - beat_id: 节拍唯一标识（如 "beat-001"）
    - beat_type: 节拍类型 (progression/turnpoint/climax)
    - position: 位置索引，用于排序
    - location: 场景地点
    - pov_character: 视角角色名
    - action_summary: 动作化执行摘要
    - entry_state/exit_state: 进入/退出状态
    - red_lines: 红线约束列表
    - word_count_target: 目标字数
    - summary: 剧情概述
    - pacing_type: 节奏类型 (Fast/Medium/Slow)
    - weight: 权重 (1-5)
    """
    chapter_id: Optional[UUID] = None
    beat_id: Optional[str] = Field(None, min_length=1, max_length=120)
    beat_type: str = Field(default="progression", max_length=100)
    position: int = Field(default=0, ge=0)
    location: Optional[str] = None
    pov_character: Optional[str] = Field(None, max_length=120)
    action_summary: Optional[str] = None
    worldbuilding_instruction: Optional[str] = None
    entry_state: Optional[str] = Field(None, min_length=1)
    exit_state: Optional[str] = Field(None, min_length=1)
    red_lines: List[str] = Field(default_factory=list)
    word_count_target: int = Field(default=0, ge=0)
    summary: str = Field(..., min_length=1)
    meta: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="planned", max_length=50)
    pacing_type: Optional[str] = Field(None, max_length=50)
    weight: Optional[int] = Field(default=1, ge=1)


class StoryBeatCreate(StoryBeatBase):
    book_id: UUID


class StoryBeatUpdate(BaseModel):
    chapter_id: Optional[UUID] = None
    beat_id: Optional[str] = Field(None, min_length=1, max_length=120)
    beat_type: Optional[str] = Field(None, max_length=100)
    position: Optional[int] = Field(None, ge=0)
    location: Optional[str] = None
    pov_character: Optional[str] = Field(None, min_length=1, max_length=120)
    action_summary: Optional[str] = None
    worldbuilding_instruction: Optional[str] = None
    entry_state: Optional[str] = Field(None, min_length=1)
    exit_state: Optional[str] = Field(None, min_length=1)
    red_lines: Optional[List[str]] = None
    word_count_target: Optional[int] = Field(None, ge=0)
    summary: Optional[str] = Field(None, min_length=1)
    meta: Optional[dict[str, Any]] = None
    status: Optional[str] = Field(None, max_length=50)


class StoryBeatResponse(StoryBeatBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class SceneIntentBase(BaseModel):
    """
    场景意图 (Scene Intent) 的基础 Schema。

    业务含义：
    - 代表单个节拍 (Beat) 内的场景级 AI 生成指令
    - 包含目标 (goal)、障碍 (obstacle)、策略 (tactic)、风险 (stakes) 等元素
    - 用于在 Draft 阶段为 LLM 提供更精细的生成指导

    字段说明：
    - chapter_id: 所属章节 ID
    - story_beat_id: 关联的故事节拍 ID
    - intent_label: 意图标签（如 "说服"、"追逐"、"谈判"）
    - character_name: 涉及的角色名
    - goal: 场景目标/任务
    - obstacle: 需要克服的障碍
    - tactic: 达成目标的策略/手段
    - stakes: 失败的后果/风险
    - constraints: 约束条件列表
    - priority: 优先级
    """
    chapter_id: UUID
    story_beat_id: Optional[UUID] = None
    intent_label: str = Field(..., min_length=1, max_length=120)
    character_name: Optional[str] = Field(None, min_length=1, max_length=120)
    goal: str = Field(..., min_length=1)
    obstacle: Optional[str] = None
    tactic: Optional[str] = None
    stakes: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0)


class SceneIntentCreate(SceneIntentBase):
    book_id: UUID


class SceneIntentUpdate(BaseModel):
    chapter_id: Optional[UUID] = None
    story_beat_id: Optional[UUID] = None
    intent_label: Optional[str] = Field(None, min_length=1, max_length=120)
    character_name: Optional[str] = Field(None, min_length=1, max_length=120)
    goal: Optional[str] = Field(None, min_length=1)
    obstacle: Optional[str] = None
    tactic: Optional[str] = None
    stakes: Optional[str] = None
    constraints: Optional[List[str]] = None
    priority: Optional[int] = Field(None, ge=0)


class SceneIntentResponse(SceneIntentBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class PlotLedgerBase(BaseModel):
    """
    情节账本 (Plot Ledger) 的基础 Schema。

    业务含义：
    - 管理伏笔/钩子的生命周期
    - 支持伏笔的创建、绑定、解决、废弃等状态流转
    - 用于实现"草蛇灰线，伏脉千里"的叙事技法

    字段说明：
    - chapter_id: 所属章节 ID
    - story_beat_id: 关联的故事节拍 ID
    - ledger_key: 伏笔唯一标识（如 "hero-backstory-reveal"）
    - hook_id: 可读的唯一标识（如 "hk-001"）
    - entry_type: 伏笔类型 (foreshadow/callback/twist/revelation)
    - content: 伏笔内容描述
    - status: 状态 (open/closed/dropped)
    - created_at_chapter: 创建伏笔的章节序号
    - resolved_in_chapter_id: 解决伏笔的章节 ID
    """
    chapter_id: Optional[UUID] = None
    story_beat_id: Optional[UUID] = None
    ledger_key: str = Field(..., min_length=1, max_length=150)
    hook_id: Optional[str] = Field(None, min_length=1, max_length=150)
    entry_type: str = Field(default="foreshadow", max_length=50)
    content: str = Field(..., min_length=1)
    status: Literal["open", "closed", "dropped"] = Field(default="open")
    created_at_chapter: Optional[int] = Field(None, ge=1)
    resolved_in_chapter_id: Optional[UUID] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class PlotLedgerCreate(PlotLedgerBase):
    book_id: UUID


class PlotLedgerUpdate(BaseModel):
    chapter_id: Optional[UUID] = None
    story_beat_id: Optional[UUID] = None
    ledger_key: Optional[str] = Field(None, min_length=1, max_length=150)
    hook_id: Optional[str] = Field(None, min_length=1, max_length=150)
    entry_type: Optional[str] = Field(None, max_length=50)
    content: Optional[str] = Field(None, min_length=1)
    status: Optional[Literal["open", "closed", "dropped"]] = None
    created_at_chapter: Optional[int] = Field(None, ge=1)
    resolved_in_chapter_id: Optional[UUID] = None
    meta: Optional[dict[str, Any]] = None


class PlotLedgerResponse(PlotLedgerBase):
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================
# Agent 调用 Schema 层 - LLM 交互的边界定义
# ============================================================
# 设计意图：
#   - 统一管理 LLM 调用参数（api_key, base_url, model）
#   - word_count 是期望值而非硬约束（LLM 输出可能略有差异）
#   - max_iterations 控制重写循环次数，防止无限迭代
#
# 警示：
#   - api_key 是敏感字段，后端不应将其存入数据库或日志
#   - base_url 允许自定义（支持 OpenAI 兼容 API，如本地部署）
class FormatTextRequest(BaseModel):
    """文本格式整理请求"""
    text: str
    api_key: str
    base_url: Optional[str] = None
    model: str = "google/gemini-2.0-flash-001"


class GenerateChapterRequest(BaseModel):
    """章节生成请求模型

    业务规则：
    - api_key 必填（LLM 调用必需）
    - word_count 期望值，非严格约束
    - 默认使用 gpt-4o-mini（平衡成本与质量）
    """
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")


class OptimizeChapterRequest(BaseModel):
    """章节优化请求模型

    业务目的：
    - 根据用户反馈对已生成的章节内容进行优化

    参数来源：
    - chapter_id: 目标章节
    - optimization_feedback: 用户输入的优化建议
    - word_count: 期望字数（可选）
    - api_key/base_url/model: LLM 配置
    """
    chapter_id: UUID
    optimization_feedback: str = Field(..., min_length=1, description="用户优化建议")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


class OptimizeSelectionRequest(BaseModel):
    """文本选择优化请求模型
    
    业务目的：
    - 对用户选中的特定文本片段进行优化（润色、细节描写等）
    
    参数来源：
    - chapter_id: 目标章节
    - selected_text: 选中的文本
    - context_before: 选中文本的前文（用于上下文理解）
    - context_after: 选中文本的后文（用于上下文理解）
    - user_instruction: 用户的优化指令
    - api_key/base_url/model: LLM 配置
    """
    chapter_id: UUID
    selected_text: str = Field(..., min_length=1)
    context_before: str = Field(default="")
    context_after: str = Field(default="")
    user_instruction: str = Field(default="")
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


AGENTIC_DEFAULT_WORD_COUNT = 2000
AGENTIC_DEFAULT_MAX_ITERATIONS = 2
AGENTIC_DEFAULT_RAG_TOP_K = 3
AGENTIC_DEFAULT_RAG_ALPHA = 0.6
AGENTIC_DEFAULT_RAG_BETA = 0.2
AGENTIC_DEFAULT_RAG_GAMMA = 0.2
AGENTIC_DEFAULT_RAG_LAMBDA = 0.1


# ============================================================
# V2.5 Cognitive Streaming - 动态上下文与功能开关
# ============================================================

class DraftingFeatureFlags(BaseModel):
    """
    V2.5 认知流式生成功能开关配置
    
    设计意图：
    - 支持渐进式启用新特性，便于灰度测试与 A/B 对比
    - 每个开关控制一个轻量级认知组件的启用/禁用
    
    功能说明：
    - enable_fail_fast: 即时断言与回溯机制（防错重试）
    - enable_emotional_scratchpad: 动态情绪暂存器（性格微演变）
    - enable_whisper_memory: RAG 记忆暂存（预留接口）
    """
    enable_fail_fast: bool = Field(default=True, description="启用 Fail-Fast 断言检查与回溯重试")
    enable_emotional_scratchpad: bool = Field(default=True, description="启用动态情绪暂存器更新")
    enable_whisper_memory: bool = Field(default=False, description="启用 RAG 记忆暂存（预留）")
    fail_fast_max_attempts: int = Field(default=2, ge=1, le=3, description="Fail-Fast 最大重试次数")
    fail_fast_temperature_step: float = Field(default=0.2, ge=0.0, le=0.5, description="每次重试温度增量")


class CharacterPhysicalState(BaseModel):
    """角色的绝对物理形态与空间从属关系"""
    is_in_vehicle: bool = Field(default=False, description="是否处于载具/机甲内部")
    vehicle_or_mech_name: Optional[str] = Field(None, description="所在载具/机甲名称")
    equipped_weapons: List[str] = Field(default_factory=list, description="当前装备的武器列表")
    movement_constraints: str = Field(default="无特殊限制", description="移动限制说明，例如'深度昏迷，无法自主移动'")


class DynamicContext(BaseModel):
    """
    V2.5+ 动态流式上下文 - 跨 Beat 流转的状态容器（增强版）
    
    设计意图：
    - 在串行生成流水线中持续流转、变异
    - 承载五类认知状态：物理边界、情绪演化、上下文记忆、剧情摘要、关系状态
    
    字段说明：
    - previous_tail: Rolling Prefix 机制上文尾部（默认 300 字符）
    - current_emotional_state: 主角当前心理状态的动态描述
    - physical_state_lock: 绝对物理状态约束（防幻觉边界）
    - accumulated_summary: 宏观剧情累加器（跨 Beat 剧情摘要，$$L_{summary} \le 500$$）
    - relational_state_lock: 在场角色动态关系锁（防止关系错乱）
    - active_whispers: 激活的 RAG 记忆片段（预留）
    """
    previous_tail: str = Field(default="", description="上文尾部（Rolling Prefix）")
    current_emotional_state: str = Field(
        default="初始状态：未知", 
        description="主角当前心理状态（随剧情演变）"
    )
    physical_state_lock: str = Field(
        default="", 
        description="主角绝对物理状态约束（防幻觉）"
    )
    pov_perception_state: str = ""  # 当前 POV 角色的清醒程度与物理行动力
    # ========================================
    # NEW FIELDS for V2.5+ Relational Cognition
    # ========================================
    accumulated_summary: str = Field(
        default="", 
        max_length=500,  # 硬性约束：Token 预算控制
        description="已生成 Beat 的极简剧情摘要（宏观累加器）"
    )
    relational_state_lock: str = Field(
        default="", 
        description="在场角色之间的动态关系状态锁"
    )
    # ========================================
    active_whispers: dict[str, str] = Field(
        default_factory=dict, 
        description="激活的 RAG 记忆片段（预留）"
    )
    entity_spatial_ledger: Dict[str, CharacterPhysicalState] = Field(
        default_factory=dict,
        description="在场核心角色的绝对物理形态与空间从属映射，键为角色名"
    )

    class Config:
        """允许运行时动态更新字段"""
        validate_assignment = True
        
    def update_summary(self, new_beat_summary: str) -> None:
        """
        更新累加摘要，确保总长度不超过 500 字符。
        
        策略：
        - 追加新摘要，用 " → " 连接
        - 超限后，从最早的内容开始裁剪（保留最近剧情）
        - 数学约束: $$L_{total} = \sum_{i=1}^{n} L_{beat_i} + (n-1) \cdot L_{sep} \le 500$$
        """
        SEPARATOR = " → "
        MAX_LENGTH = 500
        
        if not self.accumulated_summary:
            self.accumulated_summary = new_beat_summary[:MAX_LENGTH]
            return
            
        new_accumulated = self.accumulated_summary + SEPARATOR + new_beat_summary
        
        if len(new_accumulated) <= MAX_LENGTH:
            self.accumulated_summary = new_accumulated
        else:
            # 超限裁剪：保留尾部（最近剧情更重要）
            self.accumulated_summary = new_accumulated[-MAX_LENGTH:]
            # 确保不从中间切断
            if SEPARATOR in self.accumulated_summary[1:]:
                first_sep_idx = self.accumulated_summary.find(SEPARATOR, 1)
                self.accumulated_summary = self.accumulated_summary[first_sep_idx + len(SEPARATOR):]


class DynamicStateUpdateResult(BaseModel):
    """
    V2.5+ 动态状态更新结果 - 结构化输出
    
    数学模型：
    $$State_{new} = State_{old} + \Delta_{emotion} + \Delta_{relationship} + Summary_{beat}$$
    
    字段说明：
    - new_emotional_state ($E_{new}$): 角色新生成的心理状态
    - relational_delta ($R_{delta}$): 角色关系的变化描述
    - beat_summary ($S_{new}$): 本段剧情的一句话摘要
    """
    new_emotional_state: str = Field(
        ..., 
        max_length=50,
        description="角色新的心理状态（20字以内）"
    )
    relational_delta: str = Field(
        default="", 
        max_length=100,
        description="角色关系变化（如'与XXX的信任度下降'）"
    )
    beat_summary: str = Field(
        ..., 
        max_length=80,
        description="本段剧情的一句话摘要（用于宏观累加）"
    )
    
    @model_validator(mode='after')
    def validate_lengths(self):
        """确保各字段长度符合约束"""
        if len(self.new_emotional_state) > 50:
            self.new_emotional_state = self.new_emotional_state[:47] + "..."
        if len(self.relational_delta) > 100:
            self.relational_delta = self.relational_delta[:97] + "..."
        if len(self.beat_summary) > 80:
            self.beat_summary = self.beat_summary[:77] + "..."
        return self


class MicroReviewResult(BaseModel):
    """
    Fail-Fast 断言检查结果
    
    设计意图：
    - 严格的 JSON 格式返回，便于程序化处理
    - 只检查物理/逻辑硬伤，不评判文笔
    """
    pass_check: bool = Field(..., description="是否通过断言检查")
    reason: str = Field(default="", description="未通过时的原因说明（一句话）")
    failed_checks: list[str] = Field(default_factory=list, description="失败的检查项编号列表")


class GenerateChapterAgenticRequest(BaseModel):
    """Actor-Critic 模式章节生成请求模型（双模型架构）

    业务规则：
    - max_iterations 限制重写次数，防止成本失控
    - 默认 2 次迭代：1 次初稿 + 1 次重写（平衡质量与成本）
    - 迭代上限 5 次是硬约束（超过后强制终止）
    
    双模型架构（冰山模型）：
    - reasoning_model: 高逻辑模型，用于 Scene Intent、Subconscious、Review 阶段
    - creative_model: 高创意模型，用于 Prose Draft 阶段
    - 如未提供 creative_model，则默认使用 reasoning_model（单模型模式）

    工作流：
    - 主笔生成初稿 → 审阅 Agent 质检 → 不合格则重写 → 达到迭代次数或合格则结束
    """
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini", description="默认模型（向后兼容）")
    reasoning_model: Optional[str] = Field(None, description="高逻辑模型（用于 Scene Intent / Subconscious / Review）")
    creative_model: Optional[str] = Field(None, description="高创意模型（用于 Prose Draft），默认使用 reasoning_model")
    word_count: Optional[int] = Field(default=AGENTIC_DEFAULT_WORD_COUNT, ge=1, description="期望生成的字数")
    author_intent: Optional[str] = Field(None, description="作者的创作意图")
    max_iterations: int = Field(default=AGENTIC_DEFAULT_MAX_ITERATIONS, ge=1, le=5, description="最大重写次数")
    rag_top_k: int = Field(default=AGENTIC_DEFAULT_RAG_TOP_K, ge=1, le=20, description="RAG 返回记忆数量")
    rag_alpha: float = Field(default=AGENTIC_DEFAULT_RAG_ALPHA, ge=0.0, le=1.0, description="语义相似度权重")
    rag_beta: float = Field(default=AGENTIC_DEFAULT_RAG_BETA, ge=0.0, le=1.0, description="时间衰减权重")
    rag_gamma: float = Field(default=AGENTIC_DEFAULT_RAG_GAMMA, ge=0.0, le=1.0, description="剧情伏笔权重")
    rag_lambda: float = Field(default=AGENTIC_DEFAULT_RAG_LAMBDA, ge=0.0, description="时间衰减系数")
    fast_mode: bool = Field(default=False, description="快速模式：仅生成首轮结果，不进入二轮重写")
    skip_minor_refine: bool = Field(default=True, description="仅轻微问题时跳过整章重写")
    tension_level: Optional[int] = Field(None, ge=1, le=10, description="剧情张力等级 (1-10)")
    pacing_style: Optional[str] = Field(None, description="叙事节奏偏好")
    feature_flags: Optional[DraftingFeatureFlags] = Field(
        default_factory=DraftingFeatureFlags,
        description="V2.5 认知流式生成功能开关配置"
    )

    @model_validator(mode="after")
    def validate_rag_weight_sum(self):
        total = round(self.rag_alpha + self.rag_beta + self.rag_gamma, 6)
        if abs(total - 1.0) > 1e-6:
            raise ValueError("rag_alpha + rag_beta + rag_gamma 必须等于 1")
        return self


class ConfirmedStoryBeat(BaseModel):
    position: int = Field(..., ge=1)
    beat_id: Optional[str] = Field(None, min_length=1, max_length=120)
    summary: str = Field(..., min_length=1)
    location: Optional[str] = None
    pov_character: Optional[str] = Field(None, min_length=1, max_length=120)
    action_summary: Optional[str] = None
    worldbuilding_instruction: Optional[str] = None
    entry_state: Optional[str] = Field(None, min_length=1)
    exit_state: Optional[str] = Field(None, min_length=1)
    red_lines: List[str] = Field(default_factory=list)
    word_count_target: int = Field(default=0, ge=0)
    target_words: int = Field(default=0, ge=0)
    hook_ids: List[str] = Field(default_factory=list)
    pacing_type: Optional[str] = Field(None, max_length=50)
    weight: Optional[int] = Field(default=1, ge=1)


class GenerateChapterAgenticPreviewResponse(BaseModel):
    beats: List[ConfirmedStoryBeat] = Field(default_factory=list)
    debug_prompt: Optional[dict] = None  # 新增调试字段


class GenerateChapterAgenticWithBeatsRequest(GenerateChapterAgenticRequest):
    beats: List[ConfirmedStoryBeat] = Field(..., min_length=1, max_length=6)


# ============================================================
# 章节-实体关联 Schema 层
# ============================================================
# 设计意图：
#   - 简化关联操作，无需传完整对象，只传 ID
#   - entity_type 预留扩展性（目前仅支持 character）
class ChapterEntityLink(BaseModel):
    """章节-角色关联模型

    用途：用于响应中返回关联信息
    """
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterEntityCreate(BaseModel):
    """创建章节-角色关联请求模型

    业务规则：
    - 需配合章节 ID 使用（URL path 参数）
    - 后端应校验 entity 属于同一本书
    """
    entity_id: UUID
    entity_type: str = Field(default="character")


# ============================================================
# 章节发布 Schema 层 - 状态变更的边界控制
# ============================================================
# 设计意图：
#   - 发布是单向操作（draft → published），不可逆
#   - 发布时可选择是否调用 LLM 进行最终润色（api_key 可选）
#   - 若不传 api_key，则直接发布已有 draft_text 作为 content_text
class ChapterPublishRequest(BaseModel):
    """章节发布请求模型

    业务规则：
    - api_key 可选：不传则跳过 LLM 润色步骤
    - model 默认 gpt-4o-mini（发布润色通常不需要高端模型）
    """
    api_key: Optional[str] = Field(None, min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    proxy_enabled: bool = Field(default=True)
    proxy_url: Optional[str] = None


class CharacterStateChange(BaseModel):
    """角色状态变更模型

    用途：章节发布后返回哪些角色的状态发生了变化
    """
    character_id: UUID
    character_name: str
    old_state: str
    new_state: str


class ChapterPublishResponse(BaseModel):
    """章节发布响应模型

    业务规则：
    - 包含 character_updates：展示本次发布触发的角色状态变化
    - 前端可根据此信息更新角色面板
    """
    chapter_id: UUID
    status: str
    summary: Optional[str] = None
    character_updates: List[CharacterStateChange] = Field(default_factory=list)


# ============================================================
# 点子启发 Schema 层 - 轻量级灵感获取
# ============================================================

class InspirationRequest(BaseModel):
    """点子启发请求模型

    业务规则：
    - book_id 和 chapter_id 必填，用于获取上下文
    - current_context_snippet 是当前场景的简短描述
    - active_character_ids 可选，标记当前场景涉及的角色
    - temperature 默认 0.9，高温度增强发散性
    """
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
    """灵感卡片模型

    业务规则：
    - idea_type 三选一：剧情转折、关键冲突、新设伏笔
    - title 简短标题
    - description 百字左右的事件描述
    - impact 对后续格局的影响
    """
    idea_type: Literal["plot_twist", "key_conflict", "new_hook", "smooth_narrative"] = Field(
        ..., description="点子类型：剧情转折 / 关键冲突 / 新设伏笔 / 平稳叙事"
    )
    title: str = Field(..., description="点子的简短标题，如'暗中的背叛者'")
    description: str = Field(..., description="百字左右的具体事件描述")
    impact: str = Field(..., description="这步棋对后续格局的影响/好处")


class InspirationResponse(BaseModel):
    """点子启发响应模型

    业务规则：
    - 返回 4 个不同维度的灵感卡片
    """
    inspirations: List[InspirationIdea] = Field(..., min_items=4, max_items=4)


# ============================================================
# 章节审阅 Critique Schema 层
# ============================================================

class CritiqueRequest(BaseModel):
    """章节审阅请求模型"""
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
    """章节审阅响应模型"""
    comments: List[CritiqueItem]
    overall_praise: str

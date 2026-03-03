"""
Pydantic 验证模型
定义 API 请求和响应的数据结构
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class BookBase(BaseModel):
    """书籍基础模型"""
    title: str = Field(..., min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    global_sys_prompt: Optional[str] = None
    worldview_settings: Optional[dict] = Field(default_factory=dict)


class BookCreate(BookBase):
    """创建书籍请求模型"""
    pass


class BookUpdate(BaseModel):
    """更新书籍请求模型"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    genre: Optional[str] = Field(None, max_length=100)
    global_sys_prompt: Optional[str] = None
    worldview_settings: Optional[dict] = None


class BookResponse(BookBase):
    """书籍响应模型"""
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class WorldviewUpdate(BaseModel):
    worldview_settings: dict = Field(default_factory=dict)


class ChapterBase(BaseModel):
    """章节基础模型"""
    chapter_number: int = Field(..., ge=1)
    title: Optional[str] = Field(None, max_length=500)
    outline_text: Optional[str] = None
    content_text: Optional[str] = None
    draft_text: Optional[str] = None
    review_feedback: Optional[dict] = Field(default_factory=dict)
    revision_count: int = Field(default=0)
    status: str = Field(default="draft")


class ChapterCreate(ChapterBase):
    """创建章节请求模型"""
    book_id: UUID


class ChapterUpdate(BaseModel):
    """更新章节请求模型"""
    chapter_number: Optional[int] = Field(None, ge=1)
    title: Optional[str] = Field(None, max_length=500)
    outline_text: Optional[str] = None
    content_text: Optional[str] = None
    status: Optional[str] = None


class ChapterResponse(ChapterBase):
    """章节响应模型"""
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class CharacterBase(BaseModel):
    """角色基础模型"""
    name: str = Field(..., min_length=1, max_length=200)
    aliases: List[str] = Field(default_factory=list)
    static_prompt: Optional[str] = None
    dynamic_state: Optional[str] = None
    importance_level: int = Field(default=1, ge=1, le=10)


class CharacterCreate(CharacterBase):
    """创建角色请求模型"""
    book_id: UUID


class CharacterUpdate(BaseModel):
    """更新角色请求模型"""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    aliases: Optional[List[str]] = None
    static_prompt: Optional[str] = None
    dynamic_state: Optional[str] = None
    importance_level: Optional[int] = Field(None, ge=1, le=10)


class CharacterResponse(CharacterBase):
    """角色响应模型"""
    id: UUID
    book_id: UUID
    created_at: datetime
    dynamic_state_history: List[dict] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CharacterDynamicStateUpdateRequest(BaseModel):
    """角色动态状态更新请求模型"""
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


class CharacterDynamicStateUpdateResponse(BaseModel):
    """角色动态状态更新响应模型"""
    character_id: UUID
    old_dynamic_state: str
    new_dynamic_state: str


class RelationshipBase(BaseModel):
    """角色关系基础模型"""
    source_char_id: UUID
    target_char_id: UUID
    relation_type: str = Field(..., max_length=100)
    affinity_score: int = Field(default=0, ge=-100, le=100)
    interaction_prompt: Optional[str] = None
    is_public: bool = Field(default=True)


class RelationshipCreate(RelationshipBase):
    """创建角色关系请求模型"""
    pass


class RelationshipResponse(RelationshipBase):
    """角色关系响应模型"""
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class MemoryChunkBase(BaseModel):
    """记忆片段基础模型"""
    chunk_text: str = Field(..., min_length=1)
    chapter_id: Optional[UUID] = None


class MemoryChunkCreate(MemoryChunkBase):
    """创建记忆片段请求模型"""
    book_id: UUID


class MemoryChunkResponse(MemoryChunkBase):
    """记忆片段响应模型"""
    id: UUID
    book_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class GenerateChapterRequest(BaseModel):
    """章节生成请求模型"""
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")


class GenerateChapterAgenticRequest(BaseModel):
    """Actor-Critic 模式章节生成请求模型"""
    chapter_id: UUID
    api_key: str = Field(..., min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")
    word_count: Optional[int] = Field(default=2000, description="期望生成的字数")
    max_iterations: int = Field(default=2, ge=1, le=5, description="最大重写次数")


class ChapterEntityLink(BaseModel):
    """章节-角色关联模型"""
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterEntityCreate(BaseModel):
    """创建章节-角色关联请求模型"""
    entity_id: UUID
    entity_type: str = Field(default="character")


class ChapterPublishRequest(BaseModel):
    """章节发布请求模型"""
    api_key: Optional[str] = Field(None, min_length=1)
    base_url: Optional[str] = None
    model: str = Field(default="gpt-4o-mini")


class CharacterStateChange(BaseModel):
    """角色状态变更模型"""
    character_id: UUID
    character_name: str
    old_state: str
    new_state: str


class ChapterPublishResponse(BaseModel):
    """章节发布响应模型"""
    chapter_id: UUID
    status: str
    character_updates: List[CharacterStateChange] = Field(default_factory=list)

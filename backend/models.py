"""
Pydantic 数据模型定义
定义 Entity(设定档案) 和 Beat(大纲节拍) 的数据结构
"""

from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid


class Entity(BaseModel):
    """
    设定档案 - 用于存储角色、世界观等设定信息
    
    Attributes:
        id: 唯一标识符
        name: 实体名称
        type: 实体类型 (character, world, item, etc.)
        description: 详细描述
        created_at: 创建时间
        updated_at: 更新时间
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., min_length=1, max_length=100, description="实体名称")
    type: str = Field(default="character", description="实体类型: character, world, item, etc.")
    description: str = Field(default="", description="详细描述")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "name": "艾莉亚·星语",
                "type": "character",
                "description": "一位拥有星辰之力的少女，性格坚毅但内心柔软...",
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T10:30:00"
            }
        }


class Beat(BaseModel):
    """
    大纲节拍 - 用于存储小说情节节点
    
    Attributes:
        id: 唯一标识符
        order: 排序序号
        instruction: 当前节拍剧情指令
        entity_ids: 引用的实体ID列表
        generated_text: AI生成的正文内容
        created_at: 创建时间
        updated_at: 更新时间
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    order: int = Field(default=0, description="排序序号")
    instruction: str = Field(default="", description="当前节拍剧情指令")
    entity_ids: List[str] = Field(default_factory=list, description="引用的实体ID列表")
    generated_text: str = Field(default="", description="AI生成的正文内容")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440001",
                "order": 1,
                "instruction": "艾莉亚在星陨之夜觉醒力量，发现自己能听见星辰的低语",
                "entity_ids": ["550e8400-e29b-41d4-a716-446655440000"],
                "generated_text": "",
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T10:30:00"
            }
        }


class EntityCreate(BaseModel):
    """创建实体请求模型"""
    name: str = Field(..., min_length=1, max_length=100)
    type: str = Field(default="character")
    description: str = Field(default="")


class EntityUpdate(BaseModel):
    """更新实体请求模型"""
    name: Optional[str] = Field(default=None, max_length=100)
    type: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None)


class BeatCreate(BaseModel):
    """创建节拍请求模型"""
    order: int = Field(default=0)
    instruction: str = Field(default="")
    entity_ids: List[str] = Field(default_factory=list)


class BeatUpdate(BaseModel):
    """更新节拍请求模型"""
    order: Optional[int] = Field(default=None)
    instruction: Optional[str] = Field(default=None)
    entity_ids: Optional[List[str]] = Field(default=None)
    generated_text: Optional[str] = Field(default=None)


class GenerateRequest(BaseModel):
    """
    生成请求模型
    
    Attributes:
        beat: 当前节拍信息
        style: 全局写作风格偏好
        api_key: OpenAI API Key
        base_url: OpenAI Base URL (可选，用于自定义端点)
        model: 使用的模型名称
    """
    beat: Beat
    style: str = Field(default="", description="全局写作风格偏好")
    api_key: str = Field(..., description="OpenAI API Key")
    base_url: Optional[str] = Field(default=None, description="自定义API端点")
    model: str = Field(default="gpt-4o-mini", description="使用的模型名称")


class Config(BaseModel):
    """
    应用配置模型
    
    Attributes:
        api_key: OpenAI API Key
        base_url: OpenAI Base URL
        model: 默认模型
        style: 全局写作风格
        theme: 主题设置 (light/dark)
    """
    api_key: str = Field(default="", description="OpenAI API Key")
    base_url: str = Field(default="", description="自定义API端点")
    model: str = Field(default="gpt-4o-mini", description="默认模型")
    style: str = Field(default="", description="全局写作风格偏好")
    theme: str = Field(default="light", description="主题设置 (light/dark)")

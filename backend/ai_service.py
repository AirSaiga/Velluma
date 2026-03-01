"""
AI 服务层
封装 OpenAI SDK 调用与 Prompt 拼装逻辑
提供流式文本生成功能
"""

import json
from typing import AsyncGenerator, List, Dict, Any
from openai import AsyncOpenAI
from backend.models import Beat, Entity


class AIService:
    """
    AI 小说生成服务
    
    负责:
    1. 动态拼装 System Prompt 和 User Prompt
    2. 调用 OpenAI API 进行流式生成
    3. 处理生成过程中的错误和异常
    """
    
    def __init__(self, api_key: str, base_url: str = None, model: str = "gpt-4o-mini"):
        """
        初始化 AI 服务
        
        Args:
            api_key: OpenAI API Key
            base_url: 自定义 API 端点 (可选)
            model: 使用的模型名称
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        
        # 初始化 OpenAI 客户端
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        
        self.client = AsyncOpenAI(**client_kwargs)
    
    def _build_system_prompt(self, style: str, entities: List[Entity]) -> str:
        """
        构建 System Prompt
        
        将全局文风设定和实体信息整合为系统提示词
        
        Args:
            style: 全局写作风格偏好
            entities: 当前场景涉及的实体列表
            
        Returns:
            完整的 System Prompt 字符串
        """
        # 构建实体信息文本
        lore_parts = []
        for entity in entities:
            entity_info = f"【{entity.type.upper()}】{entity.name}\n{entity.description}"
            lore_parts.append(entity_info)
        
        lore_text = "\n\n".join(lore_parts) if lore_parts else "暂无相关设定信息"
        
        # 构建 System Prompt
        system_prompt = f"""你是一个专业受限的长篇小说渲染引擎。你的任务是根据提供的剧情指令，将其扩写为高质量的小说正文。

## 全局文风设定
{style if style else '保持文学性和叙事流畅性'}

## 当前场景涉及的世界观与角色设定
{lore_text}

## 核心约束规则
1. 严格遵循剧情指令，仅扩写当前指定内容
2. 充分利用上述设定信息，保持角色性格和世界观的连贯性
3. 输出应为完整的小说段落，包含环境描写、动作描写、心理描写等
4. 语言风格需符合全局文风设定
5. 绝对禁止擅自推进后续剧情或添加未指定的情节发展
"""
        return system_prompt.strip()
    
    def _build_user_prompt(self, instruction: str) -> str:
        """
        构建 User Prompt
        
        强调防越狱要求，确保 AI 严格按指令执行
        
        Args:
            instruction: 当前节拍剧情指令
            
        Returns:
            User Prompt 字符串
        """
        user_prompt = f"""请根据以下节点指令进行扩写，将其转化为完整的小说正文段落。

【绝对约束】
- 仅扩写当前指令描述的内容
- 绝对不允许擅自推进后续剧情
- 绝对不允许添加未指定的情节转折
- 保持叙事视角和时态的一致性

【当前剧情指令】
{instruction}

请直接输出小说正文，不需要任何额外说明或标记。"""
        return user_prompt.strip()
    
    async def generate_stream(
        self, 
        beat: Beat, 
        entities: List[Entity], 
        style: str = ""
    ) -> AsyncGenerator[str, None]:
        """
        流式生成小说正文
        
        使用 SSE (Server-Sent Events) 格式返回生成的文本流
        
        Args:
            beat: 当前节拍信息
            entities: 当前场景涉及的实体列表
            style: 全局写作风格偏好
            
        Yields:
            生成的文本片段 (SSE 格式)
        """
        try:
            # 构建 Prompts
            system_prompt = self._build_system_prompt(style, entities)
            user_prompt = self._build_user_prompt(beat.instruction)
            
            # 调用 OpenAI API
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                stream=True,
                temperature=0.7,
                max_tokens=2000
            )
            
            # 处理流式响应
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    # 格式化为 SSE 格式
                    yield f"data: {json.dumps({'content': content}, ensure_ascii=False)}\n\n"
            
            # 发送完成标记
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
            
        except Exception as e:
            # 发送错误信息
            error_msg = str(e)
            yield f"data: {json.dumps({'error': error_msg}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
    
    async def generate_single(
        self, 
        beat: Beat, 
        entities: List[Entity], 
        style: str = ""
    ) -> str:
        """
        非流式生成小说正文 (备用方法)
        
        Args:
            beat: 当前节拍信息
            entities: 当前场景涉及的实体列表
            style: 全局写作风格偏好
            
        Returns:
            完整的生成文本
        """
        try:
            system_prompt = self._build_system_prompt(style, entities)
            user_prompt = self._build_user_prompt(beat.instruction)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=2000
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            return f"生成失败: {str(e)}"


# 全局 AI 服务实例缓存
_ai_service_cache: Dict[str, AIService] = {}


def get_ai_service(api_key: str, base_url: str = None, model: str = "gpt-4o-mini") -> AIService:
    """
    获取或创建 AI 服务实例
    
    使用缓存避免重复创建客户端
    
    Args:
        api_key: OpenAI API Key
        base_url: 自定义 API 端点
        model: 使用的模型名称
        
    Returns:
        AIService 实例
    """
    cache_key = f"{api_key}:{base_url}:{model}"
    
    if cache_key not in _ai_service_cache:
        _ai_service_cache[cache_key] = AIService(api_key, base_url, model)
    
    return _ai_service_cache[cache_key]

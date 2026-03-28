"""
世界状态服务模块

职责：
- 封装世界状态提取逻辑
- 提供章节发布相关的辅助服务
- 处理角色状态更新和摘要生成

设计原则：
- 单一职责：世界状态相关逻辑集中管理
- 可复用：可被多个路由/服务共享
- 错误处理：提供清晰的错误信息和降级策略
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any

from backend.services.llm_client import call_llm
from backend.services.prompts.world_state_prompts import (
    build_world_state_extraction_prompt,
    parse_world_state_snapshot,
)
from backend.services.logging_utils import ServiceLogger, LOG_PREFIX_WORKFLOW, TimeoutManager
from backend.services.prompt_logger import PromptLogger

# 全局超时管理器实例
_timeout_manager = TimeoutManager()

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)


# =============================================================================
# 数据模型
# =============================================================================

class CharacterInfo:
    """角色信息数据容器"""
    
    def __init__(
        self,
        char_id: str,
        name: str,
        static_prompt: str = "",
        dynamic_state: str = "",
    ):
        self.id = char_id
        self.name = name
        self.static_prompt = static_prompt
        self.dynamic_state = dynamic_state
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "static_prompt": self.static_prompt,
            "dynamic_state": self.dynamic_state,
        }


# =============================================================================
# 世界状态提取服务
# =============================================================================

async def extract_world_state_snapshot(
    chapter_content: str,
    character_list: List[Any],
    api_key: str,
    base_url: Optional[str] = None,
    model: str = "gpt-4o-mini",
    previous_snapshot: Optional[dict] = None,
    prompt_logger: Optional[PromptLogger] = None,
    timeout: int = 120,
) -> Optional[dict]:
    """
    提取章节末尾的世界状态快照。

    在章节发布阶段调用，基于正文内容提取物理状态约束。

    Args:
        chapter_content: 章节全文内容
        character_list: 角色列表（可以是 Character 对象或 CharacterInfo）
        api_key: LLM API Key
        base_url: LLM Base URL
        model: 使用的模型
        previous_snapshot: 上一章的状态快照（可选）
        prompt_logger: PromptLogger 实例（可选，用于记录 prompt）
        timeout: 超时时间（秒）

    Returns:
        Optional[dict]: 世界状态快照，失败返回 None
    """
    try:
        # 构建角色信息列表
        char_info_list = _build_character_info_list(character_list)

        # 构建提示词
        system_prompt, user_prompt = build_world_state_extraction_prompt(
            chapter_content=chapter_content,
            character_list=char_info_list,
            previous_snapshot=previous_snapshot,
        )

        # 记录 prompt 到日志
        _log_prompt(prompt_logger, system_prompt, user_prompt, previous_snapshot)

        svc_logger.debug("Extracting world state snapshot")
        response = await _timeout_manager.call_with_timeout(
            call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=0.2,
                max_tokens=2000,
            ),
            operation_type="world_state",
            custom_timeout=timeout,
        )

        # 解析结果
        snapshot = parse_world_state_snapshot(response)

        # 记录输出到日志
        _log_result(prompt_logger, snapshot, response)

        if snapshot:
            svc_logger.info("World state snapshot extracted successfully")
            return snapshot
        else:
            svc_logger.warning("Failed to parse world state snapshot")
            return None

    except asyncio.TimeoutError:
        _log_error(prompt_logger, "Timeout")
        svc_logger.warning("World state extraction timed out")
        return None
    except Exception as e:
        _log_error(prompt_logger, str(e))
        svc_logger.error("World state extraction error", error=str(e))
        return None


def _build_character_info_list(character_list: List[Any]) -> List[Dict[str, str]]:
    """构建角色信息列表"""
    char_info_list = []
    for char in character_list:
        if not char:
            continue
        
        # 处理 Character 对象
        if hasattr(char, 'id'):
            char_info = {
                "id": str(char.id),
                "name": getattr(char, 'name', 'Unknown'),
                "static_prompt": getattr(char, 'static_prompt', '') or "",
                "dynamic_state": getattr(char, 'dynamic_state', '') or "",
            }
        # 处理 CharacterInfo 对象
        elif isinstance(char, CharacterInfo):
            char_info = char.to_dict()
        # 处理字典
        elif isinstance(char, dict):
            char_info = {
                "id": str(char.get('id', '')),
                "name": char.get('name', 'Unknown'),
                "static_prompt": char.get('static_prompt', ''),
                "dynamic_state": char.get('dynamic_state', ''),
            }
        else:
            continue
        
        char_info_list.append(char_info)
    
    return char_info_list


def _log_prompt(
    prompt_logger: Optional[PromptLogger],
    system_prompt: str,
    user_prompt: str,
    previous_snapshot: Optional[dict],
) -> None:
    """记录 prompt 到日志"""
    if not prompt_logger:
        return
    
    prompt_logger.start_stage("WORLD_STATE_EXTRACTION", iteration=1)
    prompt_logger.log_inputs(
        chapter_content_length=len(user_prompt),
        character_count=user_prompt.count("角色名称"),
        has_previous_snapshot=bool(previous_snapshot)
    )
    prompt_logger.log_prompts(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model="gpt-4o-mini",
        temperature=0.2,
        max_tokens=2000,
        prompt_label="WORLD_STATE_EXTRACTOR"
    )


def _log_result(
    prompt_logger: Optional[PromptLogger],
    snapshot: Optional[dict],
    response: str,
) -> None:
    """记录结果到日志"""
    if not prompt_logger:
        return
    
    if snapshot:
        prompt_logger.log_outputs(
            snapshot_keys=list(snapshot.keys()),
            character_snapshots_count=len(snapshot.get("character_snapshots", {})),
            scene_state=snapshot.get("scene_state", {})
        )
        prompt_logger.end_stage(success=True)
    else:
        prompt_logger.log_outputs(raw_response=response[:500] if response else "Empty")
        prompt_logger.end_stage(success=False)


def _log_error(prompt_logger: Optional[PromptLogger], error: str) -> None:
    """记录错误到日志"""
    if prompt_logger:
        prompt_logger.log_outputs(error=error)
        prompt_logger.end_stage(success=False)


# =============================================================================
# 章节发布辅助服务
# =============================================================================

async def generate_chapter_summary(
    text: str,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 180,
) -> Optional[str]:
    """
    生成章节摘要
    
    Args:
        text: 章节文本
        api_key: API Key
        base_url: Base URL
        model: 模型名称
        timeout: 超时时间
        
    Returns:
        摘要文本或 None
    """
    from backend.services.llm_client import generate_summary as llm_generate_summary
    
    try:
        svc_logger.debug("Generating chapter summary", text_length=len(text))
        summary = await _timeout_manager.call_with_timeout(
            llm_generate_summary(
                text=text,
                api_key=api_key,
                base_url=base_url,
                model=model,
            ),
            operation_type="summary",
            custom_timeout=timeout,
        )
        svc_logger.debug("Summary generated", success=bool(summary))
        return summary
    except asyncio.TimeoutError:
        svc_logger.warning("Summary generation timed out")
        return None
    except Exception as e:
        svc_logger.error("Summary generation error", error=str(e))
        return None


async def generate_summary_embedding(
    summary: str,
    api_key: str,
    base_url: Optional[str] = None,
    timeout: int = 120,
) -> Optional[List[float]]:
    """
    生成摘要的 embedding
    
    Args:
        summary: 摘要文本
        api_key: API Key
        base_url: Base URL
        timeout: 超时时间
        
    Returns:
        embedding 向量或 None
    """
    from backend.services.llm_client import get_embedding
    
    try:
        svc_logger.debug("Generating summary embedding")
        embedding = await _timeout_manager.call_with_timeout(
            get_embedding(summary, api_key, base_url),
            operation_type="embedding",
            custom_timeout=timeout,
        )
        svc_logger.debug("Embedding generated", success=bool(embedding))
        return embedding
    except asyncio.TimeoutError:
        svc_logger.warning("Embedding generation timed out")
        return None
    except Exception as e:
        svc_logger.error("Embedding generation error", error=str(e))
        return None


# =============================================================================
# 角色状态更新服务
# =============================================================================

class CharacterUpdateResult:
    """角色更新结果"""
    
    def __init__(
        self,
        character_id: str,
        character_name: str,
        old_state: str,
        new_state: str,
        success: bool = True,
        error_message: str = "",
    ):
        self.character_id = character_id
        self.character_name = character_name
        self.old_state = old_state
        self.new_state = new_state
        self.success = success
        self.error_message = error_message
    
    def to_schema(self) -> dict:
        """转换为响应 schema"""
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "old_state": self.old_state,
            "new_state": self.new_state,
        }


async def update_character_states(
    character_list: List[Any],
    chapter: Any,
    db: Any,
    api_key: str,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    proxy_enabled: bool = True,
    proxy_url: Optional[str] = None,
    timeout: int = 180,
) -> List[CharacterUpdateResult]:
    """
    批量更新角色动态状态
    
    Args:
        character_list: 角色列表
        chapter: 章节对象
        db: 数据库会话
        api_key: API Key
        base_url: Base URL
        model: 模型名称
        proxy_enabled: 是否启用代理
        proxy_url: 代理 URL
        timeout: 超时时间
        
    Returns:
        角色更新结果列表
    """
    from backend.services.chapter_generation import update_character_dynamic_state
    
    results = []
    
    for character in character_list:
        if not character:
            continue
        
        result = await _update_single_character(
            character=character,
            chapter=chapter,
            db=db,
            api_key=api_key,
            base_url=base_url,
            model=model,
            proxy_enabled=proxy_enabled,
            proxy_url=proxy_url,
            timeout=timeout,
            update_func=update_character_dynamic_state,
        )
        results.append(result)
    
    return results


async def _update_single_character(
    character: Any,
    chapter: Any,
    db: Any,
    api_key: str,
    base_url: Optional[str],
    model: Optional[str],
    proxy_enabled: bool,
    proxy_url: Optional[str],
    timeout: int,
    update_func: Any,
) -> CharacterUpdateResult:
    """更新单个角色的状态"""
    old_state = character.dynamic_state or "暂无动态状态"
    char_id = str(character.id)
    char_name = character.name
    
    try:
        await _timeout_manager.call_with_timeout(
            update_func(
                character=character,
                chapter=chapter,
                db=db,
                api_key=api_key,
                base_url=base_url,
                model=model,
                proxy_enabled=proxy_enabled,
                proxy_url=proxy_url,
            ),
            operation_type="character_update",
            custom_timeout=timeout,
        )
        
        new_state = character.dynamic_state or "暂无动态状态"
        svc_logger.debug("Character state updated", character=char_name)
        
        return CharacterUpdateResult(
            character_id=char_id,
            character_name=char_name,
            old_state=old_state,
            new_state=new_state,
            success=True,
        )
        
    except asyncio.TimeoutError:
        svc_logger.warning("Character update timed out", character=char_name)
        return CharacterUpdateResult(
            character_id=char_id,
            character_name=char_name,
            old_state=old_state,
            new_state="更新失败: 请求超时",
            success=False,
            error_message="Timeout",
        )
        
    except Exception as e:
        svc_logger.error("Character update error", character=char_name, error=str(e))
        return CharacterUpdateResult(
            character_id=char_id,
            character_name=char_name,
            old_state=old_state,
            new_state=f"更新失败: {str(e)}",
            success=False,
            error_message=str(e),
        )

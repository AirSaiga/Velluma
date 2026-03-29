"""
章节发布辅助服务

职责：
- 章节摘要生成
- 摘要向量化 (embedding)
- 角色状态批量更新

设计原则：
- 独立于世界状态提取逻辑
- 可被多个路由/服务共享
- 提供清晰的错误信息和降级策略
"""

import asyncio
import logging
from typing import List, Optional, Any

from backend.services.utils.logging import ServiceLogger, LOG_PREFIX_WORKFLOW
from backend.services.utils.timeout import TimeoutManager

_timeout_manager = TimeoutManager()

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)


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
    from backend.services.llm import generate_summary as llm_generate_summary

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
    from backend.services.llm import get_embedding

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
    from backend.services.generation.chapter import update_character_dynamic_state

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

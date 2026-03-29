"""
世界状态服务模块

职责：
- 封装世界状态提取逻辑
- Re-export 章节发布相关的辅助服务（向后兼容）

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
from backend.services.chapter_publish_service import (
    generate_chapter_summary,
    generate_summary_embedding,
    update_character_states,
    CharacterUpdateResult,
)

_timeout_manager = TimeoutManager()

logger = logging.getLogger(__name__)
svc_logger = ServiceLogger(logger, LOG_PREFIX_WORKFLOW)


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
        char_info_list = _build_character_info_list(character_list)

        system_prompt, user_prompt = build_world_state_extraction_prompt(
            chapter_content=chapter_content,
            character_list=char_info_list,
            previous_snapshot=previous_snapshot,
        )

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

        snapshot = parse_world_state_snapshot(response)

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

        if hasattr(char, 'id'):
            char_info = {
                "id": str(char.id),
                "name": getattr(char, 'name', 'Unknown'),
                "static_prompt": getattr(char, 'static_prompt', '') or "",
                "dynamic_state": getattr(char, 'dynamic_state', '') or "",
            }
        elif isinstance(char, CharacterInfo):
            char_info = char.to_dict()
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

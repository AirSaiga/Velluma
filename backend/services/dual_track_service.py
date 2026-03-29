"""
双轨生成服务层。

职责：封装双轨章节生成的核心辅助逻辑，与路由层解耦。

主要功能：
- 参数解析与高层参数推导
- Checkpoint 持久化
- 上下文加载封装
- 事件构建

使用场景：
- routes/chapter_generation_dual_track.py: 双轨生成路由调用
"""

from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas import GenerateChapterAgenticRequest, ConfirmedStoryBeat
from backend.services.agentic_workflow import resolve_high_level_params


async def persist_checkpoint(
    db: AsyncSession,
    chapter: Any,
    run_id: str,
    stage: str,
    status: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    持久化生成检查点。

    用于在生成过程中保存进度，支持从检查点恢复。

    Args:
        db: 数据库会话
        chapter: 章节实体
        run_id: 运行 ID
        stage: 当前阶段
        status: 状态
        payload: 额外数据
    """
    from datetime import datetime, timezone

    checkpoint = {
        "run_id": run_id,
        "stage": stage,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }

    import json
    chapter.generation_checkpoints = json.dumps(checkpoint)
    chapter.generation_run_id = run_id
    await db.commit()


def resolve_run_id(
    request: "DualTrackGenerationRequest",
    chapter: Any,
) -> str:
    """
    解析运行 ID。

    优先级：请求指定 > 章节已有 > 新生成

    Args:
        request: 生成请求
        chapter: 章节实体

    Returns:
        运行 ID
    """
    if request.generation_run_id:
        return request.generation_run_id
    if request.resume_from_checkpoint and chapter.generation_run_id:
        return str(chapter.generation_run_id)
    return f"run_{uuid4().hex}"


def build_generation_run_info(
    request: Any,
    resolved_params: Dict[str, Any],
    effective_reasoning_model: str,
    effective_creative_model: str,
    effective_sketch_model: str,
    effective_word_count: int,
) -> Dict[str, Any]:
    """
    构建生成运行信息。

    Args:
        request: 生成请求
        resolved_params: 解析后的参数
        effective_reasoning_model: 推理模型
        effective_creative_model: 创意模型
        effective_sketch_model: Sketch 模型
        effective_word_count: 目标字数

    Returns:
        运行信息字典
    """
    from datetime import datetime, timezone

    return {
        "run_id": resolve_run_id(request, None),
        "status": "running",
        "stage": "ASSEMBLING_CONTEXT",
        "effective_config": resolved_params,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_sketch_config(
    request: Any,
    effective_sketch_model: str,
    effective_creative_model: str,
) -> Dict[str, Any]:
    """
    构建 Sketch 轨道配置。

    Args:
        request: 生成请求
        effective_sketch_model: Sketch 模型
        effective_creative_model: 创意模型

    Returns:
        Sketch 配置字典
    """
    return {
        "sketch_model": effective_sketch_model,
        "creative_model": effective_creative_model,
        "sketch_ratio": request.sketch_ratio,
        "enable_sketch_track": request.enable_sketch_track,
    }


def extract_effective_models(request: Any) -> Dict[str, str]:
    """
    提取有效的模型配置。

    Args:
        request: 生成请求

    Returns:
        包含 reasoning_model, creative_model, sketch_model 的字典
    """
    effective_reasoning = request.reasoning_model or request.model or "gpt-4o-mini"
    effective_creative = request.creative_model or effective_reasoning
    effective_sketch = request.sketch_model or effective_creative

    return {
        "reasoning_model": effective_reasoning,
        "creative_model": effective_creative,
        "sketch_model": effective_sketch,
    }

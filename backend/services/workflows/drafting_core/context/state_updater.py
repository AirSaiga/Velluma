"""
状态更新器 - 管理动态状态的更新逻辑。

职责：
- 更新情感状态
- 更新关系状态
- 更新累积摘要

使用方式：
    updater = StateUpdater(config)
    await updater.update_emotional_state(context, chunk, pov_character)
"""

import json
import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.services.prompts import (
    build_emotional_update_prompt,
    build_dynamic_state_update_prompt,
)
from backend.services.llm import call_llm
from backend.services.workflows.utils import clean_llm_output
from backend.schemas import DynamicStateUpdateResult

if TYPE_CHECKING:
    from backend.services.llm import LLMClient

logger = logging.getLogger(__name__)

# 关系状态最大长度
RELATIONAL_STATE_MAX_LEN = 300


class StateUpdater:
    """
    状态更新器。

    职责：
    - 管理动态上下文中各种状态的更新
    - 与 LLM 交互获取状态变化
    - 处理状态合并和截断

    设计决策：
    - 情感状态使用 LLM 分析变化
    - 关系状态增量合并
    - 摘要使用截断策略避免过长
    """

    def __init__(
        self,
        config: Dict[str, Any],
        llm_client: Optional["LLMClient"] = None,
    ):
        """
        初始化状态更新器。

        Args:
            config: 配置对象
            llm_client: LLM 客户端（可选）
        """
        self._config = config
        self._llm_client = llm_client
        self._feature_flags = config.get("feature_flags", {})

    async def update_emotional_state(
        self,
        context: Dict[str, Any],
        chunk: str,
        pov_character: str,
        current_emotional_state: str,
    ) -> str:
        """
        更新情感状态。

        Args:
            context: 上下文信息
            chunk: 当前生成的文本
            pov_character: POV 角色名
            current_emotional_state: 当前情感状态

        Returns:
            str: 更新后的情感状态
        """
        try:
            system_prompt, user_prompt = build_emotional_update_prompt(
                chunk_text=chunk,
                previous_emotional_state=current_emotional_state,
                pov_character=pov_character,
            )

            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=self._config.get("api_key", ""),
                base_url=self._config.get("base_url", ""),
                model=self._config.get("reasoning_model", ""),
                temperature=0.3,
                max_tokens=100,
            )

            new_emotion = clean_llm_output(response).strip()

            # 截断过长的情感状态
            if len(new_emotion) > 30:
                new_emotion = self._truncate_emotion(new_emotion)

            return new_emotion

        except Exception as e:
            logger.warning(f"[StateUpdater] 情感状态更新失败: {e}")
            return current_emotional_state

    async def update_dynamic_state(
        self,
        context: Dict[str, Any],
        chunk: str,
        current_emotional_state: str,
        pov_character: str,
        relational_state_lock: str = "",
        beat_context: Optional[dict] = None,
        book_genre: str = "通用小说",
    ) -> DynamicStateUpdateResult:
        """
        更新动态状态（综合）。

        包含：
        - 新情感状态
        - 关系状态增量
        - Beat 摘要

        Args:
            context: 上下文信息
            chunk: 当前生成的文本
            current_emotional_state: 当前情感状态
            pov_character: POV 角色名
            relational_state_lock: 当前关系状态
            beat_context: Beat 上下文
            book_genre: 书籍类型

        Returns:
            DynamicStateUpdateResult: 更新结果
        """
        try:
            system_prompt, user_prompt = build_dynamic_state_update_prompt(
                chunk_text=chunk,
                previous_emotional_state=current_emotional_state,
                pov_character=pov_character,
                relational_state_lock=relational_state_lock,
                beat_context=beat_context,
                book_genre=book_genre,
            )

            response = await call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                api_key=self._config.get("api_key", ""),
                base_url=self._config.get("base_url", ""),
                model=self._config.get("reasoning_model", ""),
                temperature=0.3,
                response_format={"type": "json_object"},
                max_tokens=300,
            )

            result_text = clean_llm_output(response).strip()
            result_json = json.loads(result_text)
            result = DynamicStateUpdateResult(**result_json)

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"[StateUpdater] JSON 解析失败: {e}")
            return DynamicStateUpdateResult(
                new_emotional_state=current_emotional_state,
                relational_delta="",
                beat_summary=self._extract_fallback_summary(chunk),
            )
        except Exception as e:
            logger.warning(f"[StateUpdater] 动态状态更新失败: {e}")
            return DynamicStateUpdateResult(
                new_emotional_state=current_emotional_state,
                relational_delta="",
                beat_summary=self._extract_fallback_summary(chunk),
            )

    def merge_relational_delta(
        self,
        current_state: str,
        delta: str,
    ) -> str:
        """
        合并关系状态增量。

        Args:
            current_state: 当前关系状态
            delta: 关系变化描述

        Returns:
            str: 合并后的关系状态
        """
        if not delta:
            return current_state

        new_state = f"{current_state}\n[更新]: {delta}" if current_state else delta

        # 截断过长内容
        if len(new_state) > RELATIONAL_STATE_MAX_LEN:
            return new_state[-RELATIONAL_STATE_MAX_LEN:]

        return new_state

    def update_summary(
        self,
        context: Dict[str, Any],
        beat_summary: str,
    ) -> None:
        """
        更新累积摘要。

        Args:
            context: 上下文信息（会被修改）
            beat_summary: 新增的 Beat 摘要
        """
        if not beat_summary:
            return

        current_summary = context.get("accumulated_summary", "")
        if current_summary:
            context["accumulated_summary"] = f"{current_summary}\n{beat_summary}"
        else:
            context["accumulated_summary"] = beat_summary

    def _truncate_emotion(self, emotion: str, max_len: int = 30) -> str:
        """
        截断情感状态。

        在标点符号处断句。

        Args:
            emotion: 情感状态文本
            max_len: 最大长度

        Returns:
            str: 截断后的文本
        """
        if len(emotion) <= max_len:
            return emotion

        truncated = emotion[:max_len]
        for punct in [".", "。", ",", "，"]:
            last_punct = truncated.rfind(punct, 0, max_len)
            if last_punct > 10:
                return truncated[:last_punct + 1]

        return truncated + "..."

    def _extract_fallback_summary(self, text: str, max_len: int = 40) -> str:
        """
        提取降级摘要。

        在标点符号处断句。

        Args:
            text: 原始文本
            max_len: 最大长度

        Returns:
            str: 摘要文本
        """
        if len(text) <= max_len:
            return text

        truncated = text[:max_len]
        for punct in ["，", "。", "！", "？", ",", ".", "!"]:
            idx = truncated.rfind(punct)
            if idx > 10:
                return truncated[:idx + 1]

        return truncated + "..."

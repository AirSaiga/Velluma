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
伏笔追踪器 - 管理伏笔的生命周期和闭合检测。

职责：
- 管理伏笔的创建、开放、闭合和归档
- 检测伏笔闭合模式
- 评估伏笔与当前章节的相关性

业务场景：
- 章节生成时加载相关伏笔
- 伏笔闭合检测
- 伏笔遗漏提醒

主要功能：
- 伏笔状态管理
- 闭合模式匹配
- 相关性评分

依赖项：
- backend.models: PlotLedger 模型
- backend.services.rag.foreshadowing_types: 伏笔类型定义
- backend.repositories.plot_ledger_repository: PlotLedgerRepository

使用方式：
    from backend.repositories import PlotLedgerRepository
    plot_repo = PlotLedgerRepository(db)
    tracker = EnhancedForeshadowingTracker(plot_repo)
    hooks = await tracker.get_open_hooks(book_id)

迁移说明 (2026-03-30)：
- 已移除废弃的 db 参数，强制使用 plot_repository
- 所有数据库操作通过 Repository 执行
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from uuid import UUID

from backend.models import PlotLedger
from backend.services.rag.foreshadowing_types import (
    HookStatus,
    HookPriority,
    HookMetadata,
    HookDetectionResult,
    HookClosureCheckResult,
    HookScoringConfig,
)

if TYPE_CHECKING:
    from backend.repositories.plot_ledger_repository import PlotLedgerRepository

logger = logging.getLogger(__name__)


class EnhancedForeshadowingTracker:

    CLOSURE_PATTERNS = [
        r"原来.*是",
        r"终于.*明白",
        r"真相.*大白",
        r"终于.*知道",
        r"原来如此",
        r"一切.*都.*解释",
        r"终于.*揭开",
        r"秘密.*揭开",
        r"谜底.*揭开",
        r"原来.*一直",
        r"终于.*发现",
        r"才知道",
    ]

    ADDRESS_PATTERNS = [
        r"想起",
        r"回忆起",
        r"想起.*说过",
        r"曾.*提到",
        r"记得",
        r"依稀记得",
        r"仿佛记得",
    ]

    def __init__(
        self,
        plot_repository: "PlotLedgerRepository",
        scoring_config: Optional[HookScoringConfig] = None,
    ):
        self._plot_repo = plot_repository
        self.config = scoring_config or HookScoringConfig()

    async def get_open_hooks(
        self,
        book_id: UUID,
        before_chapter: int,
        include_addressed: bool = True,
    ) -> List[Dict[str, Any]]:
        hooks = await self._plot_repo.get_open_hooks(
            book_id=book_id,
            before_chapter=before_chapter,
            include_addressed=include_addressed,
        )

        hook_list = []
        for hook in hooks:
            metadata = self._build_hook_metadata(hook, before_chapter)
            hook_list.append({
                "hook_id": str(hook.id),
                "ledger_key": hook.ledger_key or "",
                "content": hook.content or "",
                "chapter_number": hook.created_at_chapter or 0,
                "priority": metadata.priority.value,
                "status": metadata.status.value,
                "urgency_score": metadata.urgency_score,
                "character_names": metadata.character_names,
                "keywords": metadata.keywords,
            })

        hook_list.sort(key=lambda x: -x.get("urgency_score", 0))

        return hook_list

    async def detect_hooks_in_text(
        self,
        text: str,
        open_hooks: List[Dict[str, Any]],
        chapter_number: int,
    ) -> List[HookDetectionResult]:
        results = []
        text_lower = text.lower()

        for hook in open_hooks:
            content = hook.get("content", "")
            if not content:
                continue

            detection = await self._detect_single_hook(
                text, text_lower, hook, chapter_number
            )

            if detection:
                results.append(detection)

        return results

    async def _detect_single_hook(
        self,
        text: str,
        text_lower: str,
        hook: Dict[str, Any],
        chapter_number: int,
    ) -> Optional[HookDetectionResult]:
        content = hook.get("content", "")
        hook_id = hook.get("hook_id", "")
        ledger_key = hook.get("ledger_key", "")

        keywords = self._extract_keywords(content)
        matched_keywords = [kw for kw in keywords if kw.lower() in text_lower]

        hook_characters = hook.get("character_names", [])
        matched_characters = [c for c in hook_characters if c.lower() in text_lower]

        keyword_score = len(matched_keywords) / max(1, len(keywords))
        character_score = len(matched_characters) / max(1, len(hook_characters))
        combined_score = 0.6 * keyword_score + 0.4 * character_score

        if combined_score < 0.2:
            return None

        is_closure = False
        matched_text = ""

        for pattern in self.CLOSURE_PATTERNS:
            match = re.search(pattern, text)
            if match and combined_score > 0.3:
                is_closure = True
                matched_text = self._extract_context(text, match.start(), 50)
                break

        if not is_closure and combined_score > 0.3:
            for pattern in self.ADDRESS_PATTERNS:
                match = re.search(pattern, text)
                if match:
                    matched_text = self._extract_context(text, match.start(), 50)
                    break

        if not matched_text and matched_keywords:
            for kw in matched_keywords:
                idx = text_lower.find(kw.lower())
                if idx >= 0:
                    matched_text = self._extract_context(text, idx, 30)
                    break

        suggested_status = None
        if is_closure:
            suggested_status = HookStatus.CLOSED
        elif combined_score > 0.3 and matched_text:
            suggested_status = HookStatus.ADDRESSED

        return HookDetectionResult(
            hook_id=hook_id,
            ledger_key=ledger_key,
            content=content,
            detected_in_chapter=chapter_number,
            detection_confidence=combined_score,
            detection_method="multi_dimension",
            matched_text=matched_text,
            match_type="closure" if is_closure else "address",
            suggested_status=suggested_status,
            is_closure=is_closure,
        )

    async def check_closure(
        self,
        text: str,
        open_hooks: List[Dict[str, Any]],
        chapter_number: int,
    ) -> List[HookClosureCheckResult]:
        results = []

        detections = await self.detect_hooks_in_text(text, open_hooks, chapter_number)
        detection_map = {d.hook_id: d for d in detections}

        for hook in open_hooks:
            hook_id = hook.get("hook_id", "")
            content = hook.get("content", "")
            priority = hook.get("priority", HookPriority.SUB_PLOT.value)
            created_chapter = hook.get("chapter_number", 0)

            detection = detection_map.get(hook_id)

            open_duration = chapter_number - created_chapter

            severity = self._calculate_severity(priority, open_duration, detection)

            result = HookClosureCheckResult(
                hook_id=hook_id,
                hook_content=content,
                is_addressed=detection is not None and detection.detection_confidence > 0.2,
                is_closed=detection is not None and detection.is_closure,
                addressed_in_text=detection.matched_text if detection else "",
                closure_type=detection.match_type if detection else "",
                suggestion=self._generate_suggestion(priority, open_duration, detection),
                severity=severity,
            )

            results.append(result)

        return results

    async def update_hook_status(
        self,
        hook_id: UUID,
        new_status: HookStatus,
        chapter_number: Optional[int] = None,
        closure_note: str = "",
    ) -> bool:
        try:
            hook = await self._plot_repo.get_by_id(hook_id)

            if not hook:
                return False

            hook.status = new_status.value

            if new_status == HookStatus.CLOSED and chapter_number:
                hook.resolved_in_chapter_id = None

            await self._plot_repo.commit()
            return True

        except Exception as e:
            logger.error(f"[EnhancedForeshadowingTracker] 更新伏笔状态失败: {e}")
            return False

    def _build_hook_metadata(
        self,
        hook: PlotLedger,
        current_chapter: int,
    ) -> HookMetadata:
        metadata = HookMetadata(
            hook_id=str(hook.id),
            ledger_key=hook.ledger_key or "",
            content=hook.content or "",
            created_at_chapter=hook.created_at_chapter or 0,
        )

        metadata.status = HookStatus(hook.status) if hook.status in [s.value for s in HookStatus] else HookStatus.OPEN

        if hook.meta and isinstance(hook.meta, dict):
            priority_str = hook.meta.get("priority", "")
            if priority_str:
                try:
                    metadata.priority = HookPriority(priority_str)
                except ValueError:
                    pass

            metadata.character_names = hook.meta.get("characters", [])
            metadata.location_names = hook.meta.get("locations", [])
            metadata.keywords = hook.meta.get("keywords", [])

        metadata.urgency_score = self._calculate_urgency(
            metadata.priority,
            metadata.created_at_chapter,
            current_chapter,
            metadata.mention_count,
        )

        return metadata

    def _calculate_urgency(
        self,
        priority: HookPriority,
        created_chapter: int,
        current_chapter: int,
        mention_count: int,
    ) -> float:
        open_duration = current_chapter - created_chapter
        duration_score = min(1.0, open_duration / self.config.urgent_threshold)

        priority_scores = {
            HookPriority.MAIN_PLOT: self.config.main_plot_score,
            HookPriority.SUB_PLOT: self.config.sub_plot_score,
            HookPriority.ATMOSPHERE: self.config.atmosphere_score,
            HookPriority.DETAIL: self.config.detail_score,
            HookPriority.WORLD_BUILDING: self.config.atmosphere_score,
        }
        priority_score = priority_scores.get(priority, 0.5)

        mention_score = min(1.0, mention_count * 0.2)

        urgency = (
            self.config.open_duration_weight * duration_score +
            self.config.priority_weight * priority_score +
            self.config.mention_count_weight * mention_score
        )

        return min(1.0, urgency)

    def _calculate_severity(
        self,
        priority: str,
        open_duration: int,
        detection: Optional[HookDetectionResult],
    ) -> str:
        if detection and detection.is_closure:
            return "info"

        if priority == HookPriority.MAIN_PLOT.value:
            if open_duration >= 8:
                return "critical"
            elif open_duration >= 5:
                return "major"
            elif open_duration >= 3:
                return "minor"

        elif priority == HookPriority.SUB_PLOT.value:
            if open_duration >= 10:
                return "major"
            elif open_duration >= 6:
                return "minor"

        else:
            if open_duration >= 15:
                return "minor"

        return "info"

    def _generate_suggestion(
        self,
        priority: str,
        open_duration: int,
        detection: Optional[HookDetectionResult],
    ) -> str:
        if detection and detection.is_closure:
            return "伏笔已闭合"

        if detection and detection.detection_confidence > 0.3:
            return "伏笔已被提及，可考虑在后续章节完全闭合"

        if priority == HookPriority.MAIN_PLOT.value:
            if open_duration >= 5:
                return f"主线伏笔已开放{open_duration}章，建议优先安排闭合情节"
            return "主线伏笔需在近期章节中闭合"

        elif priority == HookPriority.SUB_PLOT.value:
            if open_duration >= 8:
                return f"支线伏笔已开放{open_duration}章，建议安排回应情节"
            return "建议在后续章节中逐步揭示"

        else:
            return "可作为背景线索或选择性处理"

    def _extract_keywords(self, content: str) -> List[str]:
        words = re.findall(r'[\u4e00-\u9fa5]{2,}', content)
        stop_words = {"这时", "那里", "这个", "那个", "什么", "怎么", "虽然", "但是", "一个"}
        return [w for w in words if w not in stop_words]

    def _extract_context(self, text: str, position: int, radius: int) -> str:
        start = max(0, position - radius)
        end = min(len(text), position + radius)
        return text[start:end]

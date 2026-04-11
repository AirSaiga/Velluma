"""
上下文管理器 - 管理生成过程中的上下文状态。

职责：
- 初始化各种生成策略所需的上下文
- 更新 Beat 之间的状态传递
- 管理 Rolling Prefix（滚动前缀）

上下文类型：
- DynamicContext: 动态上下文，跨 Beat 共享
- BeatContext: 单个 Beat 的上下文

使用方式：
    manager = ContextManager(config)
    dynamic_context = await manager.create_dynamic_context(beats, entities, relationships)
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING

from backend.schemas import DynamicContext

if TYPE_CHECKING:
    from backend.models import CharacterRelationship, ChapterEntity


class ContextManager:
    """
    上下文管理器。

    职责：
    - 创建和初始化动态上下文
    - 管理 Rolling Prefix
    - 更新跨 Beat 的状态传递

    设计决策：
    - 使用 dataclass 封装状态，减少参数传递
    - 支持多种策略的上下文初始化
    - Rolling Prefix 限制在 300 字符
    """

    # Rolling Prefix 最大字符数
    ROLLING_PREFIX_MAX_CHARS = 300

    def __init__(self, config: Dict[str, Any]):
        """
        初始化上下文管理器。

        Args:
            config: 配置对象
        """
        self._config = config

    def create_serial_context(
        self,
        beats: List[dict],
        entities: List["ChapterEntity"],
        relationships: List["CharacterRelationship"],
        physical_state_lock: Optional[str] = None,
        entity_spatial_ledger: Optional[Dict[str, Any]] = None,
    ) -> DynamicContext:
        """
        创建串行策略的动态上下文。

        串行策略特点：
        - 每个 Beat 实时更新上下文
        - previous_tail 包含上一 Beat 的真实尾部
        - 保持完整的上下文连贯性

        Args:
            beats: Beat 列表
            entities: 实体列表
            relationships: 关系列表
            physical_state_lock: 初始物理状态锁
            entity_spatial_ledger: 实体空间台账

        Returns:
            DynamicContext: 初始化后的动态上下文
        """
        # 提取初始情感状态
        initial_emotional_state = "初始状态：未知"
        if beats and beats[0].get("entry_state"):
            initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"

        # 构建初始关系状态
        initial_relational_state = self._build_initial_relational_state(
            relationships, entities
        )

        return DynamicContext(
            previous_tail="",
            current_emotional_state=initial_emotional_state,
            physical_state_lock=physical_state_lock or "",
            accumulated_summary="",
            relational_state_lock=initial_relational_state,
            entity_spatial_ledger=entity_spatial_ledger or {},
        )

    def create_parallel_context(
        self,
        beats: List[dict],
        entities: List["ChapterEntity"],
        relationships: List["CharacterRelationship"],
        physical_state_lock: Optional[str] = None,
    ) -> DynamicContext:
        """
        创建并行策略的动态上下文。

        并行策略特点：
        - 所有 Beat 共享初始状态
        - 不更新 previous_tail
        - 牺牲连贯性换取速度

        Args:
            beats: Beat 列表
            entities: 实体列表
            relationships: 关系列表
            physical_state_lock: 初始物理状态锁

        Returns:
            DynamicContext: 共享的初始上下文
        """
        initial_emotional_state = "初始状态：未知"
        if beats and beats[0].get("entry_state"):
            initial_emotional_state = f"初始状态：{beats[0].get('entry_state')}"

        initial_relational_state = self._build_initial_relational_state(
            relationships, entities
        )

        return DynamicContext(
            previous_tail="",  # 并行模式下始终为空
            current_emotional_state=initial_emotional_state,
            physical_state_lock=physical_state_lock or "",
            accumulated_summary="",
            relational_state_lock=initial_relational_state,
            entity_spatial_ledger={},  # 并行模式下不使用
        )

    def update_rolling_prefix(
        self,
        context: DynamicContext,
        chunk: str,
        beat: dict,
        beat_idx: int,
        beats: List[dict],
    ) -> None:
        """
        更新 Rolling Prefix。

        Rolling Prefix 是串行策略的关键机制：
        - 提取当前 Beat 生成文本的尾部
        - 添加 POV 锚点信息
        - 作为下一 Beat 的 previous_tail

        Args:
            context: 动态上下文（会被修改）
            chunk: 当前 Beat 生成的文本
            beat: 当前 Beat 数据
            beat_idx: 当前 Beat 索引
            beats: 所有 Beats
        """
        from backend.services.workflows.beat_utils import extract_tail

        pov_ch = beat.get("pov_character", "主角")
        beat_number = beat_idx + 1
        n = len(beats)

        if beat_idx >= n - 1:
            return

        next_entry = beats[beat_idx + 1].get("entry_state", "未指定")
        current_exit = beat.get("exit_state", "未指定")

        # 构建 POV 锚点
        pov_anchor = (
            f"\n[System Tracker: 当前主语视角强锁定为 {pov_ch} "
            f"| 当前退出状态: {current_exit} "
            f"| 下一拍进入状态: {next_entry}]"
        )

        # 更新 previous_tail
        context.previous_tail = extract_tail(chunk, max_chars=self.ROLLING_PREFIX_MAX_CHARS) + pov_anchor

    def update_physical_state(
        self,
        context: DynamicContext,
        beat: dict,
        beat_idx: int,
    ) -> None:
        """
        更新物理状态锁。

        Args:
            context: 动态上下文（会被修改）
            beat: 当前 Beat 数据
            beat_idx: 当前 Beat 索引
        """
        pov_ch = beat.get("pov_character", "主角")
        current_exit = beat.get("exit_state", "未指定")
        beat_number = beat_idx + 1

        if current_exit and current_exit != "未指定":
            context.physical_state_lock = (
                f"{pov_ch}当前态势（{beat.get('beat_title', f'Beat {beat_number}')}结束）：{current_exit}"
            )

    def _build_initial_relational_state(
        self,
        relationships: List["CharacterRelationship"],
        entities: List["ChapterEntity"],
    ) -> str:
        """
        构建初始关系状态描述。

        Args:
            relationships: 关系列表
            entities: 实体列表

        Returns:
            str: 格式化的关系状态字符串
        """
        if not relationships:
            return ""

        rel_descriptions = []

        for rel in relationships:
            source = (
                rel.source_character.name
                if hasattr(rel, "source_character") and rel.source_character
                else "?"
            )
            target = (
                rel.target_character.name
                if hasattr(rel, "target_character") and rel.target_character
                else "?"
            )
            rel_type = rel.relation_type if hasattr(rel, "relation_type") else "未知关系"
            affinity = rel.affinity_score if hasattr(rel, "affinity_score") else 0

            # 亲和度描述
            if affinity <= -50:
                affinity_desc = "敌对"
            elif affinity <= -20:
                affinity_desc = "不信任"
            elif affinity < 20:
                affinity_desc = "中立"
            elif affinity < 50:
                affinity_desc = "友好"
            else:
                affinity_desc = "亲密"

            desc = f"{source} ↔ {target}: {rel_type}（{affinity_desc}）"

            if hasattr(rel, "interaction_prompt") and rel.interaction_prompt:
                desc += f" - {rel.interaction_prompt}"

            rel_descriptions.append(desc)

        return "\n".join(rel_descriptions)

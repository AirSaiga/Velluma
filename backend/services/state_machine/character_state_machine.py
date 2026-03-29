import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from datetime import datetime

from backend.services.state_machine.character_state_types import (
    PhysicalCondition,
    EmotionalState,
    StateChangeType,
    StateTransitionRule,
    CharacterStaticPortrait,
    CharacterDynamicState,
    CharacterCurrentState,
    CharacterStateHistory,
)

logger = logging.getLogger(__name__)


class CharacterStateMachine:

    PHYSICAL_TRANSITIONS: Dict[Tuple[PhysicalCondition, PhysicalCondition], StateTransitionRule] = {
        (PhysicalCondition.HEALTHY, PhysicalCondition.FATIGUED): StateTransitionRule("healthy", "fatigued", True),
        (PhysicalCondition.HEALTHY, PhysicalCondition.INJURED): StateTransitionRule("healthy", "injured", True, True, 30),
        (PhysicalCondition.HEALTHY, PhysicalCondition.UNCONSCIOUS): StateTransitionRule("healthy", "unconscious", True, True, 50),
        (PhysicalCondition.HEALTHY, PhysicalCondition.INCAPACITATED): StateTransitionRule("healthy", "incapacitated", True, True, 100),

        (PhysicalCondition.FATIGUED, PhysicalCondition.HEALTHY): StateTransitionRule("fatigued", "healthy", True, True, 30),
        (PhysicalCondition.FATIGUED, PhysicalCondition.INJURED): StateTransitionRule("fatigued", "injured", True, True, 30),
        (PhysicalCondition.FATIGUED, PhysicalCondition.UNCONSCIOUS): StateTransitionRule("fatigued", "unconscious", True, True, 50),

        (PhysicalCondition.INJURED, PhysicalCondition.HEALTHY): StateTransitionRule("injured", "healthy", True, True, 100),
        (PhysicalCondition.INJURED, PhysicalCondition.FATIGUED): StateTransitionRule("injured", "fatigued", True),
        (PhysicalCondition.INJURED, PhysicalCondition.CRITICAL): StateTransitionRule("injured", "critical", True, True, 50),

        (PhysicalCondition.UNCONSCIOUS, PhysicalCondition.HEALTHY): StateTransitionRule("unconscious", "healthy", True, True, 50),
        (PhysicalCondition.UNCONSCIOUS, PhysicalCondition.INJURED): StateTransitionRule("unconscious", "injured", True),
    }

    EMOTIONAL_ABRUPT_ALLOWED: Set[Tuple[EmotionalState, EmotionalState]] = {
        (EmotionalState.CALM, EmotionalState.FEARFUL),
        (EmotionalState.NEUTRAL, EmotionalState.FEARFUL),
        (EmotionalState.JOYFUL, EmotionalState.FEARFUL),

        (EmotionalState.CALM, EmotionalState.ANGRY),
        (EmotionalState.SAD, EmotionalState.ANGRY),

        (EmotionalState.CALM, EmotionalState.SAD),
        (EmotionalState.JOYFUL, EmotionalState.SAD),
    }

    IMMUTABLE_ATTRIBUTES: Set[str] = {
        "name", "gender", "age", "core_traits", "immutable_facts"
    }

    def __init__(
        self,
        static_portrait: CharacterStaticPortrait,
        dynamic_state: CharacterDynamicState,
        current_state: Optional[CharacterCurrentState] = None,
    ):
        self.static_portrait = static_portrait
        self.dynamic_state = dynamic_state
        self.current_state = current_state or CharacterCurrentState()
        self._history: List[CharacterStateHistory] = []
        self._violations: List[str] = []

    def validate_transition(
        self,
        new_state: CharacterDynamicState,
        context: Optional[str] = None,
    ) -> Tuple[bool, StateChangeType, List[str]]:
        errors: List[str] = []
        warnings: List[str] = []

        physical_change_type = self._validate_physical_transition(
            self.dynamic_state.physical_condition,
            new_state.physical_condition,
            context,
            errors,
            warnings,
        )

        emotional_change_type = self._validate_emotional_transition(
            self.dynamic_state.emotional_state,
            new_state.emotional_state,
            context,
            warnings,
        )

        self._check_ooc_violations(new_state, errors, warnings)

        self._check_immutable_violations(new_state, errors)

        if errors:
            change_type = StateChangeType.INVALID
        elif physical_change_type == StateChangeType.CRITICAL or emotional_change_type == StateChangeType.CRITICAL:
            change_type = StateChangeType.CRITICAL
        elif physical_change_type == StateChangeType.ABRUPT or emotional_change_type == StateChangeType.ABRUPT:
            change_type = StateChangeType.ABRUPT
        else:
            change_type = StateChangeType.GRADUAL

        is_valid = len(errors) == 0
        return is_valid, change_type, errors + warnings

    def _validate_physical_transition(
        self,
        old: PhysicalCondition,
        new: PhysicalCondition,
        context: Optional[str],
        errors: List[str],
        warnings: List[str],
    ) -> StateChangeType:
        if old == new:
            return StateChangeType.GRADUAL

        key = (old, new)
        rule = self.PHYSICAL_TRANSITIONS.get(key)

        if rule is None:
            if new in [PhysicalCondition.HEALTHY]:
                if not context or len(context) < 50:
                    warnings.append(
                        f"物理状态从 {old.value} 恢复到 {new.value} 需要充分解释"
                    )
                return StateChangeType.ABRUPT
            return StateChangeType.GRADUAL

        if not rule.allowed:
            errors.append(
                f"非法物理状态转换：{old.value} → {new.value}"
            )
            return StateChangeType.INVALID

        if rule.requires_explanation:
            if not context or len(context) < rule.explanation_min_length:
                warnings.append(
                    f"物理状态从 {old.value} 变为 {new.value} 需要 "
                    f"至少 {rule.explanation_min_length} 字的解释"
                )
            return StateChangeType.ABRUPT

        return StateChangeType.GRADUAL

    def _validate_emotional_transition(
        self,
        old: EmotionalState,
        new: EmotionalState,
        context: Optional[str],
        warnings: List[str],
    ) -> StateChangeType:
        if old == new:
            return StateChangeType.GRADUAL

        if (old, new) in self.EMOTIONAL_ABRUPT_ALLOWED:
            return StateChangeType.ABRUPT

        if context:
            return StateChangeType.ABRUPT

        warnings.append(
            f"情感状态从 {old.value} 变为 {new.value} 建议提供上下文"
        )
        return StateChangeType.GRADUAL

    def _check_ooc_violations(
        self,
        new_state: CharacterDynamicState,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        for trait in self.static_portrait.core_traits:
            if self._is_trait_violated(trait, new_state):
                errors.append(f"核心特质违反：{trait}")

    def _is_trait_violated(self, trait: str, state: CharacterDynamicState) -> bool:
        return False

    def _check_immutable_violations(
        self,
        new_state: CharacterDynamicState,
        errors: List[str],
    ) -> None:
        for fact in self.static_portrait.immutable_facts:
            if self._is_fact_violated(fact, new_state):
                errors.append(f"不可变事实违反：{fact}")

    def _is_fact_violated(self, fact: str, state: CharacterDynamicState) -> bool:
        return False

    def apply_transition(
        self,
        new_state: CharacterDynamicState,
        chapter_number: int,
        reason: str,
        change_type: StateChangeType,
    ) -> CharacterStateHistory:
        history = CharacterStateHistory(
            chapter_number=chapter_number,
            timestamp=datetime.now(),
            previous_state=self.dynamic_state.model_copy(deep=True),
            new_state=new_state,
            change_reason=reason,
            change_type=change_type,
        )

        self.dynamic_state = new_state
        self._history.append(history)

        logger.info(
            f"[CharacterStateMachine] {self.static_portrait.name} "
            f"状态变更: {history.previous_state.physical_condition.value} → "
            f"{new_state.physical_condition.value} ({change_type.value})"
        )

        return history

    def get_ooc_report(self, proposed_actions: str) -> Dict[str, Any]:
        violations = []
        warnings = []

        if not self.dynamic_state.can_act:
            violations.append(
                f"{self.static_portrait.name} 当前无法行动，不能执行任何动作"
            )

        if not self.dynamic_state.is_conscious:
            violations.append(
                f"{self.static_portrait.name} 处于无意识状态，不能有主动行为"
            )

        if not self.current_state.is_present_in_scene:
            warnings.append(
                f"{self.static_portrait.name} 不在当前场景中"
            )

        return {
            "character_name": self.static_portrait.name,
            "is_valid": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "current_state_summary": self.dynamic_state.to_prompt_context(),
        }

    def to_character_card(self) -> str:
        parts = [
            "=== 角色状态卡片 ===",
            self.static_portrait.to_prompt_context(500),
            "",
            "--- 当前状态 ---",
            self.dynamic_state.to_prompt_context(),
        ]

        if self.current_state.action_in_progress:
            parts.append(f"正在进行：{self.current_state.action_in_progress}")

        return "\n".join(parts)

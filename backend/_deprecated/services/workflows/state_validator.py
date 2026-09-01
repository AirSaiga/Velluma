# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
StateValidator - 世界状态与 Beats 一致性验证器 (V4.0)

职责：
- 在 Planning 阶段验证生成的 beats 是否偏离 world snapshot
- 检查位置连续性、角色离场状态、意图一致性等
- 提供详细的违规报告用于调试

业务场景：
- Planning 阶段生成 beats 后调用
- 检测物理状态冲突和角色分配错误
- 自动中断或警告不符合物理约束的 beats
"""

import logging
from typing import Any, Dict, List, Optional, Set

from backend.world_state_schemas import (
    WorldTerminalState,
    CharacterTerminalStatus,
    StateValidationResult,
    StateValidationViolation,
)

logger = logging.getLogger(__name__)


class StateValidator:
    """
    世界状态验证器
    
    设计原则：
    1. 在 Planning 阶段作为检查点使用
    2. 检测物理约束违反和角色分配错误
    3. 提供结构化的验证结果
    
    使用示例：
        validator = StateValidator()
        result = validator.validate_beats_against_state(beats, world_state)
        if not result.passed:
            for violation in result.violations:
                logger.warning(f"State violation: {violation.message}")
    """
    
    def __init__(self, strict_mode: bool = False):
        """
        初始化验证器
        
        Args:
            strict_mode: 严格模式，任何警告都视为错误
        """
        self.strict_mode = strict_mode
    
    def validate_beats_against_state(
        self,
        beats: List[Dict[str, Any]],
        world_state: Optional[WorldTerminalState],
    ) -> StateValidationResult:
        """
        验证 beats 是否与 world state 保持一致
        
        Args:
            beats: 生成的 beats 列表
            world_state: 前一章的世界终端状态，None 表示第一章
            
        Returns:
            StateValidationResult: 验证结果
        """
        violations: List[StateValidationViolation] = []
        warnings: List[StateValidationViolation] = []
        
        # 如果没有 world_state（第一章），直接通过
        if not world_state:
            logger.debug("[StateValidator] No world state (first chapter), validation passed")
            return StateValidationResult(passed=True, violations=[], warnings=[])
        
        if not beats:
            violations.append(StateValidationViolation(
                violation_type="NO_BEATS",
                message="没有 beats 需要验证",
                severity="error"
            ))
            return StateValidationResult(passed=False, violations=violations, warnings=[])
        
        # 获取 Beat 1 的信息
        beat_1 = beats[0]
        
        # =================================================================
        # 检查 1: 位置连续性
        # =================================================================
        location_violation = self._check_location_continuity(
            beat_1, world_state
        )
        if location_violation:
            violations.append(location_violation)
        
        # =================================================================
        # 检查 2: 角色离场状态
        # =================================================================
        character_violations = self._check_character_activity(beats, world_state)
        violations.extend(character_violations)
        
        # =================================================================
        # 检查 3: 角色意图连续性
        # =================================================================
        intention_warnings = self._check_intention_continuity(beats, world_state)
        warnings.extend(intention_warnings)
        
        # =================================================================
        # 检查 4: 物理锚点处理
        # =================================================================
        anchor_warnings = self._check_physical_anchors(beats, world_state)
        warnings.extend(anchor_warnings)
        
        # 确定是否通过
        has_errors = any(v.severity == "error" for v in violations)
        passed = not has_errors and (not self.strict_mode or not warnings)
        
        logger.info(
            f"[StateValidator] Validation {'passed' if passed else 'failed'}: "
            f"{len(violations)} violations, {len(warnings)} warnings"
        )
        
        return StateValidationResult(
            passed=passed,
            violations=violations,
            warnings=warnings
        )
    
    def _check_location_continuity(
        self,
        beat_1: Dict[str, Any],
        world_state: WorldTerminalState
    ) -> Optional[StateValidationViolation]:
        """
        检查 Beat 1 的位置是否与 world state 连续
        
        验证：
        - beat_1.location 应该与 world_state.scene.location_summary 匹配
        - entry_state 应该反映 world state 中的场景描述
        """
        beat_location = beat_1.get("location", "")
        scene_location = world_state.scene.location_summary
        entry_state = beat_1.get("entry_state", "")
        
        # 如果 world state 没有场景位置，跳过检查
        if not scene_location:
            return None
        
        # 简单启发式检查：beat location 是否包含场景位置的关键词
        # 或者 entry_state 是否提到了场景
        location_match = False
        
        if beat_location:
            # 提取场景位置的关键词（简单实现）
            scene_keywords = scene_location.replace("。", "").replace("，", "").split()
            for keyword in scene_keywords:
                if len(keyword) >= 2 and keyword in beat_location:
                    location_match = True
                    break
        
        if entry_state and not location_match:
            # 检查 entry_state 是否包含场景信息
            if any(kw in entry_state for kw in scene_location.replace("。", "").split() if len(kw) >= 2):
                location_match = True
        
        # 如果不匹配，生成警告级别的违规
        if not location_match and beat_location:
            # 这不是严重错误，只是警告
            return StateValidationViolation(
                violation_type="LOCATION_MISMATCH",
                message=f"Beat 1 位置 '{beat_location}' 可能与前章场景 '{scene_location}' 不连续",
                severity="warning",
                involved_character=beat_1.get("pov_character")
            )
        
        return None
    
    def _check_character_activity(
        self,
        beats: List[Dict[str, Any]],
        world_state: WorldTerminalState
    ) -> List[StateValidationViolation]:
        """
        检查是否有 inactive/dead 的角色被分配了 beats
        
        这是严重错误，必须阻止
        """
        violations = []
        
        inactive_chars: Dict[str, str] = {}  # char_id -> condition
        
        for char_id, char_status in world_state.characters.items():
            raw_condition = char_status.physical_condition
            condition_lower = raw_condition.lower()
            # 英文状态检查（lower 后比较）
            is_inactive_english = condition_lower in ["inactive", "dead", "disabled"]
            # 中文状态检查（原始字符串比较）
            is_inactive_chinese = raw_condition in ["离场", "死亡", "昏迷", "失去意识", "重伤无法行动"]
            if is_inactive_english or is_inactive_chinese:
                inactive_chars[char_id] = raw_condition
        
        # 检查每个 beat
        for beat in beats:
            pov_char = beat.get("pov_character", "")
            if not pov_char:
                continue
            
            # 尝试匹配角色名（支持 name 和 id 匹配）
            for char_id, condition in inactive_chars.items():
                if pov_char == char_id or pov_char in char_id:
                    violations.append(StateValidationViolation(
                        violation_type="INACTIVE_CHARACTER_ASSIGNED",
                        message=f"角色 '{pov_char}' 状态为 '{condition}'，不应分配 POV Beat",
                        severity="error",
                        involved_character=pov_char
                    ))
                    break
        
        return violations
    
    def _check_intention_continuity(
        self,
        beats: List[Dict[str, Any]],
        world_state: WorldTerminalState
    ) -> List[StateValidationViolation]:
        """
        检查角色意图的连续性
        
        生成警告：
        - 如果角色的 immediate_intention 与 beat 的 action_summary 方向不一致
        """
        warnings = []
        
        for beat in beats:
            pov_char = beat.get("pov_character", "")
            action_summary = beat.get("action_summary", "")
            
            if not pov_char:
                continue
            
            # 查找角色的 world state
            char_state = None
            for char_id, state in world_state.characters.items():
                if pov_char == char_id or pov_char in char_id:
                    char_state = state
                    break
            
            if not char_state:
                continue
            
            intention = char_state.immediate_intention
            if not intention:
                continue
            
            # 简单启发式：检查 action_summary 是否包含意图关键词的反义
            # 例如：意图是"逃跑"，但 action 是"主动攻击"
            contradictory_keywords = {
                "逃跑": ["主动攻击", "正面迎战", "追击"],
                "隐藏": ["暴露自己", "大声呼喊", "主动现身"],
                "等待": ["立即行动", "主动出击", "抢先"],
                "救援": ["独自逃离", "放弃", "抛弃"],
            }
            
            for intent_key, contradicts in contradictory_keywords.items():
                if intent_key in intention:
                    for contra in contradicts:
                        if contra in action_summary:
                            warnings.append(StateValidationViolation(
                                violation_type="INTENTION_MISMATCH",
                                message=f"角色 '{pov_char}' 的意图是'{intention}'，但 Beat action '{action_summary}' 可能与之矛盾",
                                severity="warning",
                                involved_character=pov_char
                            ))
                            break
        
        return warnings
    
    def _check_physical_anchors(
        self,
        beats: List[Dict[str, Any]],
        world_state: WorldTerminalState
    ) -> List[StateValidationViolation]:
        """
        检查物理锚点是否被处理
        
        生成警告：
        - 如果 physical_anchors 列表中的项目在任何 beat 中都没有被提及
        """
        warnings = []
        anchors = world_state.scene.physical_anchors
        
        if not anchors:
            return []
        
        # 收集所有 beats 的文本内容
        all_beat_text = ""
        for beat in beats:
            all_beat_text += " " + beat.get("summary", "")
            all_beat_text += " " + beat.get("action_summary", "")
            all_beat_text += " " + beat.get("entry_state", "")
            all_beat_text += " " + beat.get("exit_state", "")
        
        all_beat_text = all_beat_text.lower()
        
        # 检查每个锚点是否被提及
        unhandled_anchors = []
        for anchor in anchors:
            # 简单检查：锚点关键词是否在 beat 文本中
            anchor_keywords = anchor.replace("。", "").replace("，", "").split()
            found = any(kw.lower() in all_beat_text for kw in anchor_keywords if len(kw) >= 2)
            if not found:
                unhandled_anchors.append(anchor)
        
        if unhandled_anchors:
            warnings.append(StateValidationViolation(
                violation_type="UNHANDLED_ANCHORS",
                message=f"以下物理锚点未在 Beats 中处理：{', '.join(unhandled_anchors)}",
                severity="warning"
            ))
        
        return warnings
    
    def get_active_character_ids(self, world_state: WorldTerminalState) -> Set[str]:
        """
        获取活跃状态的角色 ID 集合
        
        Returns:
            活跃角色 ID 集合（physical_condition 不为 inactive/dead）
        """
        active = set()
        for char_id, status in world_state.characters.items():
            raw_condition = status.physical_condition
            condition_lower = raw_condition.lower()
            # 英文状态检查
            is_inactive_english = condition_lower in ["inactive", "dead"]
            # 中文状态检查
            is_inactive_chinese = raw_condition in ["离场", "死亡", "昏迷", "失去意识", "重伤无法行动"]
            if not is_inactive_english and not is_inactive_chinese:
                active.add(char_id)
        return active


# =============================================================================
# 便捷函数
# =============================================================================

def validate_beats_world_state_consistency(
    beats: List[Dict[str, Any]],
    world_state: Optional[WorldTerminalState],
    strict_mode: bool = False
) -> StateValidationResult:
    """
    便捷函数：验证 beats 与世界状态的一致性
    
    使用示例：
        result = validate_beats_world_state_consistency(beats, world_state)
        if not result.passed:
            # 处理违规
            pass
    """
    validator = StateValidator(strict_mode=strict_mode)
    return validator.validate_beats_against_state(beats, world_state)

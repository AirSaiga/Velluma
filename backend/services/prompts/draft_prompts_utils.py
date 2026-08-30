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
起草提示词工具模块 - 起草相关的工具函数。

职责：
- 提供起草提示词的辅助函数
- 文本规范化处理
- 边界约束渲染
- 场景意图提示渲染

业务场景：
- 起草提示词构建的辅助函数
- 文本格式规范化

主要功能：
- 文本规范化
- 边界约束渲染
- 场景意图渲染
- 风格控制提示

依赖项：
- backend.models: 数据模型
"""

from typing import Optional, List

from backend.models import Book


def _normalize_text(value, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _normalize_text_list(value) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _render_boundary_constraints(entry_state: str, exit_state: str, red_lines: list[str]) -> str:
    red_line_text = "；".join(red_lines) if red_lines else "无"
    return (
        "## 【边界约束与剧情完整性 - 最高优先级】\n"
        "1. 本区块优先级高于其他所有写作建议。\n"
        f"2. 切入状态（entry_state）：{entry_state}\n"
        f"3. 目标收束状态（exit_state）：{exit_state}\n"
        f"4. 绝对禁忌（red_lines）：{red_line_text}\n"
        "5. 请确保本节拍的核心冲突和情感铺垫得到充分演绎，再自然收束于 exit_state。切勿为了赶进度而在高潮处突然中断！"
    )


def _render_scene_intent_prompt(scene_intent_data) -> Optional[str]:
    if isinstance(scene_intent_data, dict):
        constraints = _normalize_text_list(scene_intent_data.get("constraints"))
        return (
            "## SceneIntent\n"
            f"标签：{_normalize_text(scene_intent_data.get('intent_label'), '推进剧情')}\n"
            f"目标：{_normalize_text(scene_intent_data.get('goal'), '推进剧情')}\n"
            f"风险：{_normalize_text(scene_intent_data.get('stakes'), '无')}\n"
            f"约束：{', '.join(constraints) if constraints else '无'}"
        )
    if isinstance(scene_intent_data, list) and scene_intent_data:
        latest_intent = scene_intent_data[-1]
        if isinstance(latest_intent, dict):
            constraints = _normalize_text_list(latest_intent.get("constraints"))
            return (
                "## SceneIntent\n"
                f"标签：{_normalize_text(latest_intent.get('intent_label'), '推进剧情')}\n"
                f"目标：{_normalize_text(latest_intent.get('goal'), '推进剧情')}\n"
                f"风险：{_normalize_text(latest_intent.get('stakes'), '无')}\n"
                f"约束：{', '.join(constraints) if constraints else '无'}"
            )
        normalized_latest_intent = _normalize_text(latest_intent)
        return f"## SceneIntent\n{normalized_latest_intent}" if normalized_latest_intent else None
    normalized_scene_intent = _normalize_text(scene_intent_data)
    return f"## SceneIntent\n{normalized_scene_intent}" if normalized_scene_intent else None


def _render_style_control_prompt(book: Book) -> Optional[str]:
    # 双写收敛（任务包 B）：books.style_blacklist 黑名单段已删——历史数据已迁移
    # 并入 style_cards.negative_list（prohibitions.py 四源合并消费），该列冻结恒空，
    # 删除恒空渲染段是行为等价的。黄金锚点段保留（旧表只读归档，仍有存量数据）。
    golden_snippets = getattr(book, 'golden_snippets', None) or []

    if isinstance(golden_snippets, list):
        golden_snippets = [s for s in golden_snippets if s]
    else:
        golden_snippets = []

    if not golden_snippets:
        return None

    sections = []

    if golden_snippets:
        snippets_text = "\n\n".join(golden_snippets)
        sections.append(
            "### [表情] 必须模仿的文风基准（黄金锚点）：\n"
            "请仔细分析以下片段的**句式长短、信息密度、克制的情绪张力以及修辞手法**。\n"
            "你接下来的扩写，必须在咬字和语感上无限逼近这段文字的质感：\n"
            f"{snippets_text}"
        )

    if sections:
        return (
            "[特级文风走廊协议：防御大模型均值回归]\n"
            "为了防止文风漂移，你必须绝对服从以下\"一正一反\"的文风控制准则：\n\n"
            + "\n\n".join(sections)
        )
    return None


def _format_entity_spatial_ledger(ledger: dict) -> str:
    if not ledger:
        return ""
    lines = []
    for char_name, state in ledger.items():
        parts = [f"【{char_name}】"]
        if state.is_in_vehicle and state.vehicle_or_mech_name:
            parts.append(f"当前处于【{state.vehicle_or_mech_name}】内部（封闭状态）")
        elif state.is_in_vehicle:
            parts.append("当前处于载具/机甲内部（封闭状态）")
        else:
            parts.append("当前为肉身状态")
        if state.equipped_weapons:
            parts.append(f"装备：{', '.join(state.equipped_weapons)}")
        if state.movement_constraints and state.movement_constraints != "无特殊限制":
            parts.append(f"⚠ 限制：{state.movement_constraints}")
        lines.append(" → ".join(parts))
    return "\n".join(lines)

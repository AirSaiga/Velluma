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
世界状态快照提示词模块。

职责：提供章节末尾世界状态提取的提示词构建和结果解析功能。

业务场景：
- 在章节发布阶段，从章节正文中提取世界实时状态快照
- 状态快照将作为下一章生成的初始约束，保证物理真实性
- 包含场景状态、角色快照、剧情惯性等关键信息

工作流位置：
- 位于章节发布流程中
- 输入：章节正文、角色列表、上一章状态快照（参考）
- 输出：结构化的世界状态快照 JSON

数据流：
- Chapter.world_snapshot 存储提取的状态
- 下一章 PLANNING 阶段读取并注入为约束条件
"""

import json
import re
from typing import Optional


def build_world_state_extraction_prompt(
    chapter_content: str,
    character_list: list[dict],
    previous_snapshot: Optional[dict] = None,
) -> tuple[str, str]:
    """构建世界状态提取提示词。

    在章节发布阶段调用，提取章节末尾的世界实时状态快照。
    此输出将作为下一章生成的初始约束，必须保证 100% 物理真实性。

    Args:
        chapter_content: 章节全文内容
        character_list: 角色列表，包含角色ID、名称、当前状态等信息
        previous_snapshot: 上一章的状态快照（仅作为参考，以正文为准）

    Returns:
        tuple[str, str]: (system_prompt, user_prompt)
    """
    
    # 格式化角色列表
    character_descriptions = []
    for char in character_list:
        char_id = char.get("id", "unknown")
        char_name = char.get("name", "未知角色")
        char_static = char.get("static_prompt", "")
        char_dynamic = char.get("dynamic_state", "")
        
        desc = f"【{char_name}】(ID: {char_id})"
        if char_static:
            desc += f"\n  静态设定：{char_static[:100]}..."
        if char_dynamic:
            desc += f"\n  当前动态状态：{char_dynamic}"
        character_descriptions.append(desc)
    
    character_list_text = "\n\n".join(character_descriptions) if character_descriptions else "无"
    
    # 上一章快照参考
    previous_snapshot_text = ""
    if previous_snapshot:
        previous_snapshot_text = f"""
## 上一章状态快照（仅作参考，以正文为准）
```json
{json.dumps(previous_snapshot, ensure_ascii=False, indent=2)}
```
"""

    system_prompt = """你是剧情状态审计员 (Narrative State Auditor)。

你的任务：阅读章节正文，提取章节末尾的【世界实时状态快照 (World Snapshot)】。

核心原则：
1. **物理真实性优先**：所有状态必须基于正文中的实际描述，禁止推测或想象
2. **简洁直接**：使用物理状态描述，禁止文学修辞
3. **覆盖完整性**：必须覆盖所有曾在文中出现并产生互动的角色
4. **状态准确性**：如果角色已死亡或离开场景，必须标记为 inactive

输出必须是合法的 JSON 格式，严格按照以下结构：

{
  "scene_state": {
    "location": "当前详细地点及状态 (如：一片狼藉的战壕，空气中弥漫硝烟)",
    "current_state": "此刻场景状态摘要（50字以内，用于前端显示）",
    "damages": ["墙壁坍塌", "由于爆炸被封死的出口"],
    "active_anchors": ["遗落在地上的钥匙", "未熄灭的油灯"]
  },
  "character_snapshots": {
    "char_id_1": {
      "current_state": "此刻状态摘要（50字以内，用于前端显示）",
      "status": "当前的物理状态 (如：重伤无法行走/精力充沛)",
      "location": "当前在场景内的相对位置 (如：正在门口观察/角落里昏迷)",
      "immediate_intention": "此时此刻的动机 (如：想尽快离开/等待救援)",
      "relationship_impact": "与主角关系的即时变化：(如：因为上一章的打斗变得敌对)"
    }
  },
  "narrative_momentum": "从上一章延续下来的剧情惯性 (如：两人处于被迫合作的尴尬中)"
}

字段说明：
- scene_state.location: 精确描述场景位置和当前环境状态
- scene_state.current_state: 此刻场景状态的简短摘要（50字以内），用于前端场景卡显示
- scene_state.damages: 场景中发生的破坏或改变（空数组表示无）
- scene_state.active_anchors: 场景中仍需处理的关键物品或状态（空数组表示无）
- character_snapshots: 以角色ID为键的角色状态字典
  - current_state: 此刻状态摘要（50字以内），用于前端角色卡显示三种状态（静态、动态、此刻）
  - status: 物理状态详细描述，如"重伤无法行走"、"精力充沛"、"昏迷不醒"
  - location: 相对位置描述，如"正在门口观察"、"角落里昏迷"
  - immediate_intention: 当前意图，如"想尽快离开"、"等待救援"
  - relationship_impact: 关系变化的即时描述
- narrative_momentum: 剧情惯性，描述当前的情感/关系/行动趋势

规则：
1. 如果某角色在文中已死亡或离开场景，请标记为 "inactive" 状态
2. 保持简洁，直接描述物理状态，禁止文学修辞
3. 必须覆盖所有曾在文中出现并产生互动的角色
4. 仅输出 JSON，不要任何解释性文字"""

    user_prompt = f"""请阅读以下章节正文，提取章节末尾的世界实时状态快照。

## 现有角色列表
{character_list_text}

{previous_snapshot_text}

## 章节正文
```
{chapter_content}
```

请输出世界状态快照 JSON。"""

    return system_prompt, user_prompt


def parse_world_state_snapshot(raw_result: str) -> Optional[dict]:
    """解析世界状态提取结果。

    Args:
        raw_result: LLM 返回的原始文本

    Returns:
        Optional[dict]: 解析后的状态快照字典，解析失败返回 None
    """
    if not raw_result:
        return None
    
    text = raw_result.strip()
    
    # 尝试多种方式提取 JSON
    candidates = []
    
    # 1. 直接尝试解析
    if text:
        candidates.append(text)
    
    # 2. 提取代码块中的 JSON
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block and block.strip())
    
    # 3. 提取花括号包裹的内容
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        candidates.append(text[first_brace : last_brace + 1].strip())
    
    # 尝试解析每个候选
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            # 验证必要字段
            if isinstance(parsed, dict) and "scene_state" in parsed:
                return _normalize_snapshot(parsed)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    
    return None


def _normalize_snapshot(snapshot: dict) -> dict:
    """规范化状态快照结构。

    确保所有必要字段存在，并填充默认值。
    """
    # 确保 scene_state 结构完整
    scene_state = snapshot.get("scene_state", {})
    if not isinstance(scene_state, dict):
        scene_state = {}

    normalized = {
        "scene_state": {
            "location": str(scene_state.get("location", "未指定")).strip() or "未指定",
            "current_state": str(scene_state.get("current_state", "")).strip() or "场景状态未指定",
            "damages": _ensure_string_list(scene_state.get("damages")),
            "active_anchors": _ensure_string_list(scene_state.get("active_anchors")),
        },
        "character_snapshots": _normalize_character_snapshots(
            snapshot.get("character_snapshots", {})
        ),
        "narrative_momentum": str(
            snapshot.get("narrative_momentum", "延续上一章剧情")
        ).strip() or "延续上一章剧情",
    }

    return normalized


def _normalize_character_snapshots(snapshots: dict) -> dict:
    """规范化角色快照字典。"""
    if not isinstance(snapshots, dict):
        return {}

    normalized = {}
    for char_id, snapshot in snapshots.items():
        if not isinstance(snapshot, dict):
            continue

        normalized[str(char_id)] = {
            "current_state": str(snapshot.get("current_state", "")).strip() or "状态未指定",
            "status": str(snapshot.get("status", "状态未知")).strip() or "状态未知",
            "location": str(snapshot.get("location", "位置未知")).strip() or "位置未知",
            "immediate_intention": str(
                snapshot.get("immediate_intention", "意图不明")
            ).strip() or "意图不明",
            "relationship_impact": str(
                snapshot.get("relationship_impact", "关系无变化")
            ).strip() or "关系无变化",
        }

    return normalized


def _ensure_string_list(value) -> list[str]:
    """确保值为字符串列表。"""
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def build_world_state_constraint_prompt(snapshot: dict) -> str:
    """构建世界状态约束注入提示词。

    在 PLANNING 阶段的 System Prompt 中加入此约束，
    确保下一章的 beats 设计遵循物理约束。

    Args:
        snapshot: 世界状态快照字典

    Returns:
        str: 约束提示词文本
    """
    if not snapshot:
        return ""
    
    scene_state = snapshot.get("scene_state", {})
    character_snapshots = snapshot.get("character_snapshots", {})
    narrative_momentum = snapshot.get("narrative_momentum", "")
    
    # 场景状态格式化
    location = scene_state.get("location", "未指定")
    damages = scene_state.get("damages", [])
    active_anchors = scene_state.get("active_anchors", [])
    
    damages_text = json.dumps(damages, ensure_ascii=False) if damages else "[]"
    anchors_text = json.dumps(active_anchors, ensure_ascii=False) if active_anchors else "[]"
    
    # 角色约束矩阵格式化
    character_constraints = []
    for char_id, status in character_snapshots.items():
        if not isinstance(status, dict):
            continue
        char_status = status.get("status", "状态未知")
        char_location = status.get("location", "位置未知")
        char_intention = status.get("immediate_intention", "意图不明")
        
        constraint = f"- {char_id}: 物理状态[{char_status}]，位置[{char_location}]，当前意图[{char_intention}]"
        character_constraints.append(constraint)
    
    character_constraints_text = "\n".join(character_constraints) if character_constraints else "无角色约束"
    
    prompt_parts = [
        "# 【强制约束：世界状态快照 (World Snapshot)】",
        "",
        "在设计 Beats 之前，必须先读取以下物理/心理约束。",
        "这些约束是本章剧情的【物理基石】，如果 Beat 设计违背了以下快照，则该设计无效。",
        "",
        "## 场景状态限制",
        f"- 当前位置: {location}",
        f"- 场景破坏情况: {damages_text}",
        f"- 关键锚点 (必须处理或互动): {anchors_text}",
        "",
        "## 角色约束矩阵",
        character_constraints_text,
    ]
    
    if narrative_momentum:
        prompt_parts.extend([
            "",
            "## 剧情惯性",
            f"{narrative_momentum}",
        ])
    
    prompt_parts.extend([
        "",
        "# 执行守则 (Physical Constraint Protocol)",
        "1. **位置连续性**: 下一章的第一 Beat 开篇，必须立即衔接上述「位置信息」。",
        "2. **意图延续**: 严禁让角色瞬间改变目标，必须基于上述「当前意图」进行行为推演。",
        "3. **因果逻辑**: 如果场景有「破坏」，必须在描述中体现对其的影响，不允许发生「瞬间修复」现象。",
        "4. **锚点处理**: 关键锚点必须在某个 Beat 中被处理、互动或明确说明其状态变化。",
    ])
    
    return "\n".join(prompt_parts)


def format_snapshot_for_planner(snapshot: dict) -> str:
    """格式化快照供 Planner 使用。

    返回简洁的文本格式，便于插入到 Planner 的 user prompt 中。
    """
    if not snapshot:
        return ""
    
    scene_state = snapshot.get("scene_state", {})
    character_snapshots = snapshot.get("character_snapshots", {})
    narrative_momentum = snapshot.get("narrative_momentum", "")
    
    parts = [
        "## 【上一章末尾世界状态快照】",
        "",
        f"**场景位置**: {scene_state.get('location', '未指定')}",
    ]
    
    damages = scene_state.get("damages", [])
    if damages:
        parts.append(f"**场景破坏**: {', '.join(damages)}")
    
    anchors = scene_state.get("active_anchors", [])
    if anchors:
        parts.append(f"**待处理锚点**: {', '.join(anchors)}")
    
    if character_snapshots:
        parts.extend(["", "**角色状态**:"])
        for char_id, status in character_snapshots.items():
            if isinstance(status, dict):
                parts.append(
                    f"- {char_id}: {status.get('status', '状态未知')}，"
                    f"位于{status.get('location', '未知位置')}，"
                    f"意图：{status.get('immediate_intention', '不明')}"
                )
    
    if narrative_momentum:
        parts.extend(["", f"**剧情惯性**: {narrative_momentum}"])
    
    parts.extend([
        "",
        "⚠️ **约束提醒**: Beat 1 的 entry_state 必须与上述状态保持 100% 连续性！",
    ])
    
    return "\n".join(parts)

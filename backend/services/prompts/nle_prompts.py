# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF Prompts
"""
NLE-ADF（Loop 1 大纲自检 / Loop 3 记忆倒灌）的 LLM prompt 模板。

职责：
- build_outline_hard_facts_prompt: Loop 1 Pass 1 硬事实提取
- build_outline_critique_prompt: Loop 1 Pass 3 Critique 校验
- build_emergent_facts_prompt: Loop 3 涌现实体抽取
"""

# ============================================================
# Loop 1 Pass 1：硬事实提取
# ============================================================

_OUTLINE_HARD_FACTS_SYSTEM = """你是大纲硬事实提取器。

职责：从作者提供的章节粗大纲中，仅抽取**明确写出的客观事实**。

严禁：
- 推理角色动机或内心活动
- 补全文中没有的因果链
- 猜测情绪或主题隐喻
- 发明任何大纲未提及的实体、地点、道具

只抽取以下五类硬事实：
1. 角色动作（谁做了什么物理动作）
2. 地点转换（场景从哪到哪）
3. 道具/物体出现（什么关键物品登场）
4. 明确事件（发生了什么客观事件）
5. 明确对白/台词（大纲直接引用的话）

输出 JSON：
{
  "hard_facts": [
    {"category": "action|location|object|event|dialogue", "content": "事实陈述（≤30字）"}
  ]
}

只返回 JSON，不要任何解释。"""


def build_outline_hard_facts_prompt(outline_text: str, chapter_title: str) -> tuple:
    """构造 Loop 1 Pass 1 的 (system, user) prompt。"""
    user = f"""章节标题：{chapter_title or "（未命名）"}

粗大纲：
---
{outline_text or "（空大纲）"}
---

请抽取上述大纲中的全部硬事实。"""
    return _OUTLINE_HARD_FACTS_SYSTEM, user


# ============================================================
# Loop 1 Pass 3：Critique 校验
# ============================================================

_OUTLINE_CRITIQUE_SYSTEM = """你是大纲忠实度审计员。

职责：对比"作者原始大纲"与"系统拟生成的分镜槽位卡"，核对槽位卡是否包含大纲未授权的脑补内容。

判定规则：
- 槽位卡的 core_plot_event / key_anchors / text_carrier 中，若出现大纲未提及的具体实体、事件、动作，视为**脑补违规**。
- 例外：通用动作词（走/看/说）不算违规；只对专有名词、特定道具、特定事件判定。
- branch_directive 字段不算违规（这是 DDE 注入的走向，不是脑补）。

输出 JSON：
{
  "pass": true|false,
  "violations": [
    {"beat_id": "BS_CH..._BEAT_..", "field": "core_plot_event|key_anchors|text_carrier",
     "content": "违规内容", "reason": "大纲未提及此实体/事件"}
  ]
}

pass=true 时 violations 为空数组。只返回 JSON，不要解释。"""


def build_outline_critique_prompt(outline_text, hard_facts, beat_slots):
    """构造 Loop 1 Pass 3 的 (system, user) prompt。"""
    import json
    facts_text = "\n".join(
        f"- [{f.get('category', '?')}] {f.get('content', '')}" for f in hard_facts
    )
    slots_text = json.dumps(beat_slots, ensure_ascii=False, indent=2)
    user = f"""原始大纲：
---
{outline_text or "（空）"}
---

已提取的硬事实：
{facts_text or "（无）"}

拟生成的分镜槽位卡（JSON）：
{slots_text}

请审计槽位卡是否含大纲未授权的脑补内容。"""
    return _OUTLINE_CRITIQUE_SYSTEM, user


# ============================================================
# Loop 3：涌现实体抽取
# ============================================================

_EMERGENT_FACTS_SYSTEM = """你是正文涌现实体抽取器。

职责：从一段已定稿的正文（约 500 字）中，抽取**新涌现**的实体、关系变更、地点、大纲补遗。

只抽取：
- 正文中首次出现的**专有名词**（角色名、机甲名、招式名、组织名等）
- 明确的关系变更（A 与 B 的关系从 X 变为 Y）
- 新出现的地点（正文中场景切换到的具体地点）
- 值得回写大纲的剧情补遗（一句话）

严禁：
- 抽取通用名词（人/树/门）
- 推理隐含的关系
- 抽取大纲或前文已有的实体（除非关系发生变更）

输出 JSON：
{
  "new_entities": [{"name": "实体名", "type": "character|item|skill|org", "description": "一句话描述"}],
  "relationship_changes": [{"from": "角色A", "to": "角色B", "change": "关系变更一句话"}],
  "new_locations": [{"name": "地点名", "description": "一句话描述"}],
  "outline_addenda": [{"beat_id": "BS_CH..._BEAT_..", "suggested_text": "建议补充到大纲的一句话"}]
}

无任何涌现时返回四个空数组。只返回 JSON。"""


def build_emergent_facts_prompt(segment_text, beat_id, prev_state_summary=""):
    """构造 Loop 3 涌现实体抽取的 (system, user) prompt。"""
    user = f"""本段 beat_id：{beat_id}

前文已知状态摘要：
{prev_state_summary or "（本章首段，无前文）"}

本段正文：
---
{segment_text}
---

请抽取本段涌现实体。"""
    return _EMERGENT_FACTS_SYSTEM, user

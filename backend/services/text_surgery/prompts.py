# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""手术 prompt（自 services/prompts/refinery_prompts.py 的手术段逐字节抽迁，2026-09-12）。

仅含 surgeon 消费的两件：SURGERY_SYSTEM/SURGERY_USER_TEMPLATE 模板与
build_surgery_prompt/format_diagnosis_for_surgery 构建器。Refinery 的
诊断/回读/抛光 prompt 随引擎一并退役，不在此包。
"""

from typing import Any, Dict, List, Tuple

SURGERY_SYSTEM = """你是资深的小说编辑，专精"最小侵入式修改"。

任务：根据诊断结果，对指定段落做精确修改。

# 核心原则

1. **只改指定的段落**——绝不动其他段落
2. **保持与全文的情绪连贯**——你看到的"全文上下文摘要"是关键
3. **遵守 Canon 约束**——private 字段绝不许出现，public 事实必须保持一致
4. **字数灵活**——修改后可比原文短（允许删减），也可略长（补充细节）
5. **不要解释**——只输出修改后的完整段落，不输出修改理由

# 修改手法

- **rewrite**：重写段落（保留情节，改写方式）
- **merge**：合并多段为一段
- **delete**：删除冗余段（仅当诊断明确建议时）
- **insert**：在指定位置插入新内容（仅当诊断明确建议时）

# 输出要求

只输出修改后的段落正文本身。不要 [P0] 标记、不要 markdown、不要解释。"""


SURGERY_USER_TEMPLATE = """# 全文上下文摘要（让你有整体感）

## 本章主旨
{purpose}

## 情绪曲线
{emotion_curve}

## 角色状态
{character_states}

## Canon 约束（★ private 字段绝不许出现）
{canon_constraints}

## 活跃伏笔（修改时不要破坏）
{active_hooks}

# 当前要修改的段落（原文）

{target_text}

# 诊断与建议

{diagnosis_summary}

# 修改要求

请按诊断建议，修改上述段落。

- 操作类型：{operation_type}
- 字数：{word_hint}
- 必须保持与全文的情绪连贯
- 绝不许出现 private 字段：{forbidden_terms}

只输出修改后的段落正文本身。"""


def build_surgery_prompt(
    purpose: str,
    emotion_curve: str,
    character_states: str,
    canon_constraints: str,
    active_hooks: str,
    target_text: str,
    diagnosis_summary: str,
    operation_type: str = "rewrite",
    word_hint: str = "与原文相近或略短",
    forbidden_terms: str = "（无特别禁止）",
) -> Tuple[str, str]:
    """构建手术 prompt（原 Refinery 工序 4.5.4，逐字节同源）。

    关键设计：
    - 全文上下文摘要给 LLM 整体感（不是全文，避免重写）
    - target_text 是要改的局部段落
    - diagnosis_summary 是诊断的理由和建议

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    user_prompt = SURGERY_USER_TEMPLATE.format(
        purpose=purpose or "（未提供）",
        emotion_curve=emotion_curve or "（未提供）",
        character_states=character_states or "（未提供）",
        canon_constraints=canon_constraints or "（无）",
        active_hooks=active_hooks or "（无）",
        target_text=target_text,
        diagnosis_summary=diagnosis_summary,
        operation_type=operation_type,
        word_hint=word_hint,
        forbidden_terms=forbidden_terms,
    )
    return SURGERY_SYSTEM, user_prompt


def format_diagnosis_for_surgery(issues: List[Dict[str, Any]]) -> str:
    """把多个 issue 格式化为手术 prompt 用的诊断摘要。"""
    if not issues:
        return "（无诊断）"
    lines = []
    for issue in issues:
        sev = issue.get("severity", "?")
        typ = issue.get("type", "?")
        diag = issue.get("diagnosis", "")
        sugg = issue.get("suggestion", "")
        lines.append(f"- [{sev}/{typ}] {diag}")
        if sugg:
            lines.append(f"  建议：{sugg}")
    return "\n".join(lines)

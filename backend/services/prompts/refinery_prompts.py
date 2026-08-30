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
精修流水线（Refinery）prompt 模板（V4.1 新建）。

职责：
- 工序 4.5.1 诊断 prompt（build_diagnostic_prompt）
- 工序 4.5.4 局部手术 prompt（build_surgery_prompt）
- 工序 4.5.5 整体回读 prompt（build_holistic_read_prompt）
- 工序 4.5.6 抛光 prompt（build_polish_prompt）

设计意图（设计文档 §3）：
- 诊断：LLM 读全文找问题，输出结构化 JSON
- 手术：LLM 看全文摘要 + 局部段落，做最小侵入式修改（核心创新）
- 回读：LLM 检查手术之间是否冲突
- 抛光：文风统一 + 句式去重 + 钩子强化

使用方式：
    system, user = build_diagnostic_prompt(...)
    result = await call_llm_with_usage(system_prompt=system, user_prompt=user, ...)
"""

import re
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# 工序 4.5.1：诊断 prompt
# ============================================================

DIAGNOSTIC_SYSTEM = """你是资深的长篇小说编辑，专攻网文与类型小说。

任务：阅读一章小说初稿，找出所有需要改进的地方。

# 问题类型（按类型分类找问题）

1. **tell_not_show**（直陈该用动作）
   - 直陈句如"她控制得很好""她很稳""他显得很愤怒"
   - 应该用动作、感官、细节暗示代替直接告诉读者

2. **pacing_drag**（节奏拖沓）
   - 某段占比过重（如老人剥糖写得太细）
   - 连续多段都在日常，没有推进
   - 重复铺垫同一个信息

3. **pacing_break**（节奏断裂）
   - 段落之间拼接错位（前段没写完，后段重启）
   - 同一事件被写了两遍
   - 视角跳跃无过渡

4. **scene_jump**（场景切换突兀）
   - 场景切换没有过渡（如从大厅直接跳到二楼老人，没有运镜）
   - 时间跳跃没有交代
   - 视角切换没有缓冲

5. **info_leak**（信息泄露）
   - 叙述者代为点破本该暗示的信息（如直接说"弦月巅峰独属的印记"）
   - private 信息出现在正文（违反 Canon）
   - 提前揭示伏笔（破坏悬念）

6. **character_off**（角色行为不符）
   - 角色行为与已建立的人设矛盾
   - 对话风格与角色不符
   - 角色反应过激或过弱

7. **redundancy**（冗余重复）
   - 重复的句式（如多次"她.XXX"）
   - 重复的描写（同一个细节写两遍）
   - 重复的节奏标记（"盖章。咔嗒。下一个。"出现两次）

8. **weak_hook**（章末钩子弱）
   - 章末没有悬念
   - 章末悬念不够勾人

9. **emotion_mismatch**（情绪与曲线不符）
   - 当前段该是高潮但写得平淡
   - 当前段该是压抑但写得激烈

# 诊断原则

- **诚实**：不要为了凑数报告问题，只报告真实影响阅读的问题
- **具体**：每个问题必须带引文（quote）精确定位
- **建设性**：suggestion 必须给出具体的修改方向（不是"改一下"）
- **分级**：severity 要客观（high=严重影响阅读 / medium=明显可改进 / low=细节）
- **影响半径**：
  - local=只改一段
  - multi_paragraph=需要改多段（如合并）
  - global=影响全文（如章末钩子）

# 输出格式

严格 JSON：

```json
{
  "issues": [
    {
      "id": "I001",
      "location": {
        "paragraph": 5,
        "quote": "她控制得很好"
      },
      "type": "tell_not_show",
      "severity": "medium",
      "diagnosis": "直陈句，应该用动作暗示她的克制",
      "suggestion": "改成'她的指尖在袖口摩挲了一下，然后收回'",
      "impact_radius": "local"
    }
  ]
}
```

paragraph 是 0-based 段序号。如果问题跨段，用 paragraph_range: [12, 18]。
quote 必须是原文中的精确片段（便于定位）。"""


DIAGNOSTIC_USER_TEMPLATE = """# 本章信息

## 章节主旨
{purpose}

## 情绪曲线（作者预期）
{emotion_curve}

## Canon 约束（已检查，但请补充语义级判断）
{canon_summary}

## 作者意图（如有）
{author_intent}

# 待诊断的章节正文（已分段，[P0]/[P1]/[P2]... 标记段序号）

{segmented_text}

# 要求

请仔细阅读，找出所有需要改进的地方。返回严格 JSON。"""


def build_diagnostic_prompt(
    purpose: str,
    emotion_curve: str,
    canon_summary: str,
    author_intent: str,
    full_text: str,
) -> Tuple[str, str]:
    """构建诊断 prompt（工序 4.5.1）。

    Args:
        purpose: 章节主旨
        emotion_curve: 情绪曲线文本
        canon_summary: Canon 摘要（private 字段清单等）
        author_intent: 作者补充意图（如有）
        full_text: 完整正文

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    # 把正文按段落标记
    paragraphs = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    segmented_lines = []
    for i, p in enumerate(paragraphs):
        segmented_lines.append(f"[P{i}]\n{p[:800]}")  # 单段截到 800 字避免 token 失控
    segmented_text = "\n\n".join(segmented_lines)

    user_prompt = DIAGNOSTIC_USER_TEMPLATE.format(
        purpose=purpose or "（未提供）",
        emotion_curve=emotion_curve or "（未提供）",
        canon_summary=canon_summary or "（无 Canon 约束）",
        author_intent=author_intent or "（无）",
        segmented_text=segmented_text,
    )
    return DIAGNOSTIC_SYSTEM, user_prompt


def parse_diagnostic_response(content: str) -> List[Dict[str, Any]]:
    """解析诊断 LLM 响应为 issue dict 列表。"""
    if not content:
        return []
    import json
    # 尝试直接解析
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # 围栏
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fence:
            try:
                data = json.loads(fence.group(1))
            except json.JSONDecodeError:
                return []
        else:
            brace = re.search(r"\{.*\}", content, re.DOTALL)
            if brace:
                try:
                    data = json.loads(brace.group(0))
                except json.JSONDecodeError:
                    return []
            else:
                return []

    issues = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(issues, list):
        return []

    # 标准化
    result = []
    for i, issue in enumerate(issues):
        if not isinstance(issue, dict):
            continue
        loc = issue.get("location") or {}
        result.append({
            "id": str(issue.get("id") or f"I{i+1:03d}"),
            "location": {
                "paragraph": loc.get("paragraph"),
                "paragraph_range": loc.get("paragraph_range"),
                "quote": str(loc.get("quote", ""))[:200],
                "char_offset": loc.get("char_offset"),
            },
            "type": str(issue.get("type", "tell_not_show")),
            "severity": str(issue.get("severity", "medium")),
            "diagnosis": str(issue.get("diagnosis", ""))[:500],
            "suggestion": str(issue.get("suggestion", ""))[:500],
            "impact_radius": str(issue.get("impact_radius", "local")),
            "status": "pending",
        })
    return result


# ============================================================
# 工序 4.5.4：局部手术 prompt
# ============================================================

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
    """构建手术 prompt（工序 4.5.4）。

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


# ============================================================
# 工序 4.5.5：整体回读 prompt
# ============================================================

HOLISTIC_READ_SYSTEM = """你是资深的小说编辑。

任务：你刚才对一章小说做了几处局部修改。请再读一遍修改后的完整章节，检查：

1. **衔接自然**：修改处与前后文衔接是否自然？
2. **不破坏伏笔**：修改是否破坏了原有的伏笔/情绪积累？
3. **不引入矛盾**：修改是否引入了新的矛盾（与 Canon 或前文）？
4. **整体节奏**：整体节奏是否改善？

# 输出格式

严格 JSON：

```json
{
  "verdict": "pass" | "needs_final_touch",
  "remaining_issues": ["问题描述1", "问题描述2"],
  "final_touch_suggestion": "最后微调建议（如果 needs_final_touch）"
}
```

判定规则：
- 没有剩余问题 → pass
- 有 1-2 个小问题 → needs_final_touch（并给出具体建议）
- 有严重结构问题 → needs_final_touch（建议重做某个手术）"""

HOLISTIC_READ_USER_TEMPLATE = """# 本章主旨与情绪曲线
{purpose}
{emotion_curve}

# Canon 约束
{canon_constraints}

# 已做的修改摘要
{surgeries_summary}

# 修改后的完整章节

{full_text}

# 要求

请检查上述修改。返回严格 JSON。"""


def build_holistic_read_prompt(
    purpose: str,
    emotion_curve: str,
    canon_constraints: str,
    surgeries_summary: str,
    full_text: str,
) -> Tuple[str, str]:
    """构建整体回读 prompt（工序 4.5.5）。"""
    user_prompt = HOLISTIC_READ_USER_TEMPLATE.format(
        purpose=purpose or "（未提供）",
        emotion_curve=emotion_curve or "（未提供）",
        canon_constraints=canon_constraints or "（无）",
        surgeries_summary=surgeries_summary or "（无修改记录）",
        full_text=full_text[:6000],  # 截到 6000 字
    )
    return HOLISTIC_READ_SYSTEM, user_prompt


# ============================================================
# 工序 4.5.6：抛光 prompt
# ============================================================

POLISH_SYSTEM = """你是顶级的中文小说文字编辑，专精"最后一遍抛光"。

任务：对修改完成的章节做最后的表面抛光。

# 抛光范围（只做表面，不改情节）

1. **文风统一**：对照作者样本，统一语感
2. **句式去重**：检测重复的句式模式，替换为变体
   - 例：多次"她.XXX" → 部分改为"兰星.XXX"或省略主语
3. **章末钩子强化**：如果末段没有强悬念，加一个（一句话即可）
4. **细节微调**：标点、段落分隔、用词

# 严格禁止

- ❌ 不要改情节
- ❌ 不要改角色行为
- ❌ 不要改伏笔的埋设/回收
- ❌ 不要新增大段内容

# 输出

输出抛光后的完整章节正文。不要解释、不要 diff、只输出最终文本。"""

POLISH_USER_TEMPLATE = """# 作者样本（参考语感，不要复制内容）
{author_samples}

# 待抛光的章节正文

{full_text}

# 要求

请做最后一遍抛光。只改表面（文风/句式/钩子），不动情节和角色。输出完整章节正文。"""


def build_polish_prompt(
    full_text: str,
    author_samples: str = "",
) -> Tuple[str, str]:
    """构建抛光 prompt（工序 4.5.6）。"""
    user_prompt = POLISH_USER_TEMPLATE.format(
        author_samples=author_samples or "（无样本）",
        full_text=full_text,
    )
    return POLISH_SYSTEM, user_prompt


# ============================================================
# 辅助：构建诊断摘要（给手术 prompt 用）
# ============================================================

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

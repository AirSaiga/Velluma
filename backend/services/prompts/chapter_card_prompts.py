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
章节卡生成 Prompt 模板（Phase 1 CP2.3b 新建）。

职责：让 LLM 从书级大纲+前一章卡+滚动摘要生成结构化的章节卡。

设计依据（蓝图 §4.1.3）：
- 章节卡是"章节间胶水"（chapter glue），填补 Sudowrite 缺失的章间连贯
- purpose / must_hit_events 必须用【场景化情绪化语言】书写
  （写"她第一次对他说谎，手在抖"而非"完成信任危机铺垫"）——让约束本身带文风
- 决策依据：调研报告 §4.3"逻辑×文风平衡"

输出契约（JSON）：
{
  "purpose": "场景化的一句话主旨",
  "must_hit_events": [{"event","emotion","must"}],
  "involved_characters": [{"id","name","entry","exit"}],
  "foreshadow_ops": [{"action","note"}],
  "continuity": {"from_chapter","time_gap","location"},
  "word_target": 3000,
  "pacing": "medium",
  "tension": 5
}
"""

import json
from typing import Any, Dict, List, Optional, Tuple


def build_chapter_card_prompt(
    chapter: Any,
    book: Any,
    previous_card: Optional[Any] = None,
    rolling_summary: Optional[str] = None,
    open_hooks: Optional[List[Any]] = None,
    entities: Optional[List[Any]] = None,
) -> Tuple[str, str]:
    """构建章节卡生成 prompt。

    Args:
        chapter: Chapter ORM 对象
        book: Book ORM 对象（取 outline / global_sys_prompt / core_motifs_taboos）
        previous_card: 前一章的 ChapterCard（章节卡链回溯）
        rolling_summary: Book.rolling_summary 或上一章 chapter.summary
        open_hooks: 开放伏笔列表
        entities: 本章关联角色列表（ChapterEntity，含 .character）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    # ---- 上下文段拼接 ----
    sections: List[str] = []

    # 书级大纲
    book_outline = (getattr(book, "outline", "") or "").strip()
    if book_outline:
        # 截到合理长度（防止 token 爆炸）
        book_outline_text = book_outline[:2000] + ("…" if len(book_outline) > 2000 else "")
        sections.append(f"## 书级大纲\n{book_outline_text}")

    # 本章已有 outline_text（用户在前端填的章级大纲）
    chapter_outline = (getattr(chapter, "outline_text", "") or "").strip()
    if chapter_outline:
        co_text = chapter_outline[:1000] + ("…" if len(chapter_outline) > 1000 else "")
        sections.append(f"## 本章草稿大纲（用户已写）\n{co_text}")

    # 前一章卡（章节卡链）
    if previous_card is not None:
        prev_purpose = (getattr(previous_card, "purpose", "") or "").strip()
        prev_events = getattr(previous_card, "must_hit_events", []) or []
        prev_exit = ""
        for ent in (getattr(previous_card, "involved_characters", []) or []):
            if isinstance(ent, dict):
                exit_state = ent.get("exit", "")
                if exit_state:
                    prev_exit += f"- {ent.get('name', '某角色')}：{exit_state}\n"

        prev_parts = [f"前一章（第 {getattr(previous_card, 'chapter_number', '?')} 章）主旨：{prev_purpose}"]
        if prev_events:
            evs = []
            for ev in prev_events[:3]:
                if isinstance(ev, dict):
                    evs.append(f"  - {ev.get('event', '')}")
            if evs:
                prev_parts.append("前一章关键事件：\n" + "\n".join(evs))
        if prev_exit:
            prev_parts.append(f"前一章角色退场状态：\n{prev_exit}")
        sections.append("## 前一章衔接（章节卡链）\n" + "\n".join(prev_parts))

    # 滚动摘要（全局剧情进展）
    if rolling_summary:
        rs_text = rolling_summary[:1500] + ("…" if len(rolling_summary) > 1500 else "")
        sections.append(f"## 全书进展摘要（滚动摘要）\n{rs_text}")

    # 开放伏笔
    if open_hooks:
        hook_lines = []
        for h in open_hooks[:5]:
            if isinstance(h, dict):
                content = h.get("content", "") or ""
                hook_id = h.get("hook_id", "") or ""
            else:
                content = getattr(h, "content", "") or ""
                hook_id = getattr(h, "hook_id", "") or ""
            if content:
                prefix = f"[{hook_id}] " if hook_id else ""
                hook_lines.append(f"- {prefix}{content[:100]}")
        if hook_lines:
            sections.append("## 开放伏笔（本章可推进/呼应）\n" + "\n".join(hook_lines))

    # 涉及角色
    if entities:
        char_lines = []
        for ent in entities[:8]:
            char = getattr(ent, "character", None)
            if char is None:
                continue
            name = getattr(char, "name", "") or "未命名"
            static = (getattr(char, "static_prompt", "") or "").strip()
            if static:
                static = static[:120] + ("…" if len(static) > 120 else "")
                char_lines.append(f"- {name}：{static}")
            else:
                char_lines.append(f"- {name}")
        if char_lines:
            sections.append("## 本章可涉及角色\n" + "\n".join(char_lines))

    context_block = "\n\n".join(sections) if sections else "（无可用上下文）"

    # 章节基本信息
    chapter_number = getattr(chapter, "chapter_number", 1)
    chapter_name = getattr(chapter, "chapter_name", "") or f"第 {chapter_number} 章"
    word_count_hint = "（参考用户的 chapter_goals 或书级大纲推断）"

    system_prompt = f"""你是一位资深的小说策划。你的任务是为小说的某一章生成结构化的【章节卡】。

## 章节卡的作用
章节卡是"章节间胶水"——本章的主旨、必达事件、涉及角色、伏笔操作、与上一章的衔接。它既是规划节拍的输入，也是上下文引擎的章级锚点。

## 关键原则（务必遵守）

1. **purpose 与 must_hit_events 必须用场景化情绪化语言书写**：
   - ✅ 写"她第一次对他说谎，手在抖但语气平稳"
   - ❌ 写"完成信任危机铺垫"
   让约束本身带文风，下游起草时不再需要补充情绪描述。

2. **must_hit_events 是本章必须发生的关键事件**（3-6 个），每个含 emotion（情绪目标）。
   场景化描述，不要写成大纲式总结。

3. **involved_characters 是本章实际出场的角色**，含入/出场状态（与上一章衔接）。

4. **foreshadow_ops 是伏笔操作**（plant 新埋/advance 推进/payoff 兑现）。

5. **continuity 必须明确与上一章的衔接**（时间间隔、地点、状态延续）。

6. word_target / pacing / tension 要符合本章的剧情强度。

## 输出格式（严格 JSON）

只输出一个 JSON 块，不要任何解释：

```json
{{
  "purpose": "场景化的一句话主旨",
  "must_hit_events": [
    {{"event": "场景化事件描述", "emotion": "情绪目标", "must": true}}
  ],
  "involved_characters": [
    {{"name": "角色名", "entry": "入场状态", "exit": "出场状态"}}
  ],
  "foreshadow_ops": [
    {{"action": "plant|advance|payoff", "note": "伏笔说明"}}
  ],
  "continuity": {{
    "from_chapter": {chapter_number - 1},
    "time_gap": "与上章的时间间隔",
    "location": "本章主场景"
  }},
  "word_target": 3000,
  "pacing": "fast|medium|slow",
  "tension": 5
}}
```

pacing 取值：fast（紧凑动作）/ medium（均衡）/ slow（细腻描写）
tension 取值：1-10（1=平淡，10=高潮）"""

    user_prompt = f"""请为以下章节生成章节卡：

## 章节信息
- 章节号：第 {chapter_number} 章
- 章节名：{chapter_name}

{context_block}

---

请输出 JSON 格式的章节卡。"""

    return system_prompt, user_prompt


def parse_chapter_card_response(
    raw_response: str,
    chapter_number: int,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """解析章节卡 LLM 响应。

    Args:
        raw_response: LLM 原始响应
        chapter_number: 章节号（用于 continuity.from_chapter 兜底）

    Returns:
        tuple: (parsed_fields, error)
        parsed_fields 含 ChapterCard 兼容字段，可直接 ChapterCard(**fields)
    """
    text = raw_response.strip()
    # 清理 markdown 包裹
    if text.startswith("```"):
        text = text.replace("```json", "", 1).replace("```", "", 1).strip()
        if text.endswith("```"):
            text = text[:-3].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"JSON 解析失败: {e}"

    # purpose
    purpose = data.get("purpose")
    if purpose and not isinstance(purpose, str):
        purpose = str(purpose)
    if purpose:
        purpose = purpose[:1000]

    # must_hit_events
    must_hit_events = data.get("must_hit_events") or []
    if not isinstance(must_hit_events, list):
        must_hit_events = []
    cleaned_events = []
    for ev in must_hit_events[:8]:
        if isinstance(ev, dict):
            cleaned_events.append({
                "event": str(ev.get("event", ""))[:300],
                "emotion": str(ev.get("emotion", ""))[:100] if ev.get("emotion") else None,
                "must": bool(ev.get("must", True)),
            })

    # involved_characters
    involved = data.get("involved_characters") or []
    if not isinstance(involved, list):
        involved = []
    cleaned_involved = []
    for char in involved[:10]:
        if isinstance(char, dict):
            cleaned_involved.append({
                "name": str(char.get("name", ""))[:100],
                "entry": str(char.get("entry", ""))[:200] if char.get("entry") else None,
                "exit": str(char.get("exit", ""))[:200] if char.get("exit") else None,
            })

    # foreshadow_ops
    ops = data.get("foreshadow_ops") or []
    if not isinstance(ops, list):
        ops = []
    cleaned_ops = []
    for op in ops[:6]:
        if isinstance(op, dict):
            action = str(op.get("action", "advance"))[:30]
            if action not in ("plant", "advance", "payoff", "drop"):
                action = "advance"
            cleaned_ops.append({
                "action": action,
                "ledger_id": str(op.get("ledger_id", ""))[:100] if op.get("ledger_id") else None,
                "note": str(op.get("note", ""))[:200],
            })

    # continuity
    continuity = data.get("continuity") or {}
    if not isinstance(continuity, dict):
        continuity = {}
    cleaned_continuity = {
        "from_chapter": continuity.get("from_chapter", chapter_number - 1),
        "time_gap": str(continuity.get("time_gap", ""))[:100] if continuity.get("time_gap") else None,
        "location": str(continuity.get("location", ""))[:200] if continuity.get("location") else None,
    }

    # 量化字段
    try:
        word_target = int(data.get("word_target", 3000))
        word_target = max(500, min(20000, word_target))
    except (TypeError, ValueError):
        word_target = 3000

    pacing = str(data.get("pacing", "medium"))[:20]
    if pacing not in ("fast", "medium", "slow"):
        pacing = "medium"

    try:
        tension = int(data.get("tension", 5))
        tension = max(1, min(10, tension))
    except (TypeError, ValueError):
        tension = 5

    return {
        "purpose": purpose,
        "must_hit_events": cleaned_events,
        "involved_characters": cleaned_involved,
        "foreshadow_ops": cleaned_ops,
        "continuity": cleaned_continuity,
        "word_target": word_target,
        "pacing": pacing,
        "tension": tension,
    }, None


def build_fallback_card_fields(
    chapter: Any,
    book: Any,
) -> Dict[str, Any]:
    """章节卡生成失败的兜底（用 chapter.outline_text + book.outline 拼接）。

    依据：Phase 0 失败不静默原则——降级时仍返回可用结构，标 degraded。
    """
    parts = []
    chapter_outline = (getattr(chapter, "outline_text", "") or "").strip()
    book_outline = (getattr(book, "outline", "") or "").strip()
    if chapter_outline:
        parts.append(chapter_outline[:500])
    elif book_outline:
        parts.append(book_outline[:500])

    purpose = "；".join(parts)[:500] if parts else f"第 {getattr(chapter, 'chapter_number', 1)} 章"

    return {
        "purpose": purpose,
        "must_hit_events": [],
        "involved_characters": [],
        "foreshadow_ops": [],
        "continuity": {
            "from_chapter": getattr(chapter, "chapter_number", 1) - 1,
            "time_gap": None,
            "location": None,
        },
        "word_target": 3000,
        "pacing": "medium",
        "tension": 5,
    }

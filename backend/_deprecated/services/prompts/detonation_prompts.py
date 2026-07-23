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
爆发链 Prompt 模板（V3.0 新建）。

职责：承载 3.0 三个核心假设的 prompt 契约（设计文档 §7）：
- §7.1 高潮点候选生成：reasoning, T=0.5
- §7.2 铺垫树生长：reasoning, T=0.3，两段式（自由分析 → JSON 抽取）
- §7.3 铺垫写作：creative, T=0.8，距离指令模板（payload 锚注入）
- §7.4 有锚审计：reasoning, T=0.1（Slice B 占位）

设计依据（docs/generation-v3-design.md）：
- §2 设计原则 D2（爆炸先写）、D3（距离即指令）、D7（问题流保温）
- §5 各 Phase 的输入输出契约
- §7 prompt 契约要点（两段式输出、降级显式化）

输出契约：所有 prompt 遵守 2.0 契约规范：
- system 静态前缀保缓存（跨调用稳定）
- user 动态尾部（每次调用注入上下文）
- 两段式输出（自由分析 → JSON 抽取）
- 降级显式化（解析失败由调用方标记 degraded）
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def escape_control_chars_in_strings(s: str) -> str:
    """转义 JSON 字符串字面量内部的裸控制字符（\\n / \\r / \\t）。

    业务场景：LLM 输出的 JSON 里，长文本字段（如 description / content）偶尔
    含有未转义的控制字符（典型是换行），导致 json.loads 抛
    "Invalid control character"。本函数只转义 "..." 内部的控制字符，
    不影响 JSON 结构本身。

    设计：状态机遍历，跟踪 in_string / escaped 状态。

    Args:
        s: 从 LLM 响应中抽取的 JSON 字符串

    Returns:
        控制字符已转义的 JSON 字符串（可安全 json.loads）
    """
    result = []
    in_string = False
    escaped = False
    for ch in s:
        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            continue
        # 在字符串字面量内
        if escaped:
            # 前一个是反斜杠，本字符原样保留（已转义），重置 escaped
            result.append(ch)
            escaped = False
            continue
        if ch == "\\":
            result.append(ch)
            escaped = True
            continue
        if ch == '"':
            result.append(ch)
            in_string = False
            continue
        # 字符串内的普通字符：检查是否裸控制字符
        if ch == "\n":
            result.append("\\n")
        elif ch == "\r":
            result.append("\\r")
        elif ch == "\t":
            result.append("\\t")
        else:
            result.append(ch)
    return "".join(result)


def _safe_json_loads(raw_json: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    """安全解析 JSON：先尝试原样，失败则清洗控制字符后重试。

    所有 3 个 parser（payload_candidate / chain_grow / anchored_audit）共用。

    Args:
        raw_json: 从 LLM 响应中抽取的 JSON 字符串

    Returns:
        tuple: (parsed_data, degraded)
        - parsed_data: 解析成功则为 dict/list，失败则为 None
        - degraded: 失败时的降级标记（成功为 None）
    """
    # 第一次：原样解析
    try:
        return json.loads(raw_json), None
    except json.JSONDecodeError:
        pass
    # 第二次：清洗控制字符后重试
    try:
        cleaned = escape_control_chars_in_strings(raw_json)
        return json.loads(cleaned), None
    except json.JSONDecodeError as e:
        return None, {
            "reason": "json_decode_failed",
            "action": "empty_candidates",
            "detail": f"{type(e).__name__}: {str(e)[:120]}",
        }


# ============================================================
# §7.1 高潮点候选生成（reasoning, T=0.5）
# ============================================================
# 与章节卡生成合并调用（章节卡 prompt 末尾追加"同时产出 payload_candidates"）
# 也可独立调用作为"重生成高潮点候选"工具
#
# 输出契约（自由分析 → JSON 抽取）：
# {
#   "candidates": [
#     {
#       "description": "爆发瞬间描述（场景化语言）",
#       "emotional_target": "情绪目标（具体可感）",
#       "answers_question": "回答的读者正抱着的问题",
#       "opens_question": "打开的新问题",
#       "why_now": "为何在此章爆发（由前文张力导出）"
#     }
#   ]
# }


PAYLOAD_CANDIDATE_SYSTEM = """你是一位资深的类型小说结构编辑，专精"情绪高潮点"设计。

## 你的任务
给定章节卡与故事现状，为这一章设计若干个【高潮点候选】，并为每个候选评估【高潮强度】。

## 高潮点定义
高潮点是本章情绪势能的爆发瞬间——一个反转、揭盅、抉择，或关系的不可逆变化。它是全章最值得写好的一段（~800 字），是读者翻页动力的源头。

## 设计要求（务必遵守）

1. **必须由前文的既有张力自然导出**：禁止天降。高潮点不是突发事件，是积累的势能在本章找到出口。
2. **必须回答一个读者正抱着的问题，同时打开一个新问题**：这样既给台阶（情绪释放），又保温（继续翻页）。
3. **情绪目标必须具体可感**：禁止写"很震撼""很感动"。要写"压迫感在最高点反转成更深的失望""她终于哭出来，却不是因为难过"。
4. **过渡章也能爆发**：高潮点可以很小——一个眼神、一个安静的决定、一句没说出口的话。机制降级不失败。

## 高潮强度自评（climax_score，1-10，V3.1 §2.2 决策依据 1）
为每个候选打一个强度分（用于定档）：
- 8-10：大高潮/揭盅/决裂/卷尾（如：男主身份揭穿、决战败北、关系彻底破裂）
- 5-7：中等转折、重要推进（如：新对手登场、关键秘密部分揭露、关系明显变化）
- 3-4：小转折、日常推进（如：得到新线索、结识关键人物、小幅关系调整）
- 1-2：纯过渡、衔接（如：一个安静的决定、一个眼神、场景切换）

强度评分要诚实——定档器会据此决定本章的投资规模（宁低勿高原则）。
高估强度会导致过渡章硬造高潮（更伤），低估强度可靠中途升档修正。

## 输出格式
先用 2-3 段自由分析本章的情绪地形（哪里蓄力、哪里值得爆发、爆发后打开什么），然后用如下 JSON 给出候选：
```json
{
  "candidates": [
    {
      "description": "...",
      "emotional_target": "...",
      "answers_question": "...",
      "opens_question": "...",
      "why_now": "...",
      "climax_score": 7,
      "climax_score_reason": "本卷倒数第二章+男主身份揭穿=高强度反转"
    }
  ]
}
```
JSON 必须放在 ```json ``` 围栏内，便于解析。"""


PAYLOAD_CANDIDATE_USER_TEMPLATE = """## 本章信息
- 第 {chapter_number} 章{chapter_name_suffix}
- 章节主旨（purpose）：{purpose}

## 本章必达事件
{must_hit_events}

## 前文张力（前章摘要 + 滚动摘要）
{previous_tension}

## 开放伏笔（本章可推进/呼应）
{open_hooks}

## 本章可涉及角色
{characters}

## 要求
请基于上述信息，设计 {count} 个高潮点候选。每个候选都要回答"读者此刻最想看到什么发生"，并打开一个让读者继续翻页的新问题。"""


def build_payload_candidate_prompt(
    chapter: Any,
    chapter_card: Any,
    previous_summary: Optional[str],
    rolling_summary: Optional[str],
    open_hooks: Optional[List[Any]],
    entities: Optional[List[Any]],
    count: int = 3,
) -> Tuple[str, str]:
    """构建高潮点候选生成 prompt（§7.1）。

    Args:
        chapter: Chapter ORM 对象
        chapter_card: ChapterCard ORM 对象（含 purpose / must_hit_events）
        previous_summary: 前一章 summary
        rolling_summary: Book.rolling_summary
        open_hooks: 开放伏笔列表
        entities: 本章关联角色列表（ChapterEntity，含 .character）
        count: 候选数量（默认 3）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    chapter_number = getattr(chapter, "chapter_number", 1)
    chapter_name = getattr(chapter, "chapter_name", "") or ""
    chapter_name_suffix = f"：{chapter_name}" if chapter_name else ""

    # 章节主旨（优先取 chapter_card，fallback 到 chapter.chapter_goals）
    purpose = ""
    if chapter_card is not None:
        purpose = (getattr(chapter_card, "purpose", "") or "").strip()
    if not purpose:
        goals = getattr(chapter, "chapter_goals", []) or []
        if isinstance(goals, list) and goals:
            purpose = "；".join(str(g) for g in goals[:3])
    if not purpose:
        purpose = "（未提供，请从必达事件推断）"

    # 必达事件
    must_hit_events = []
    if chapter_card is not None:
        events = getattr(chapter_card, "must_hit_events", []) or []
        for ev in events[:5]:
            if isinstance(ev, dict):
                event_text = ev.get("event", "") or ""
                emotion = ev.get("emotion", "") or ""
                line = f"- {event_text}"
                if emotion:
                    line += f"（情绪：{emotion}）"
                must_hit_events.append(line)
    must_hit_events_text = "\n".join(must_hit_events) if must_hit_events else "（未指定）"

    # 前文张力（合并前章摘要 + 滚动摘要）
    tension_parts = []
    if previous_summary:
        tension_parts.append(f"前一章结尾：{previous_summary[:800]}")
    if rolling_summary:
        tension_parts.append(f"全书进展：{rolling_summary[:1000]}")
    previous_tension = "\n\n".join(tension_parts) if tension_parts else "（本章是第一章或无前文）"

    # 开放伏笔
    hook_lines = []
    for h in (open_hooks or [])[:5]:
        if isinstance(h, dict):
            content = h.get("content", "") or ""
            hook_id = h.get("hook_id", "") or ""
        else:
            content = getattr(h, "content", "") or ""
            hook_id = getattr(h, "hook_id", "") or ""
        if content:
            prefix = f"[{hook_id}] " if hook_id else ""
            hook_lines.append(f"- {prefix}{content[:100]}")
    open_hooks_text = "\n".join(hook_lines) if hook_lines else "（无）"

    # 角色
    char_lines = []
    for ent in (entities or [])[:8]:
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
    characters_text = "\n".join(char_lines) if char_lines else "（未指定）"

    user_prompt = PAYLOAD_CANDIDATE_USER_TEMPLATE.format(
        chapter_number=chapter_number,
        chapter_name_suffix=chapter_name_suffix,
        purpose=purpose,
        must_hit_events=must_hit_events_text,
        previous_tension=previous_tension,
        open_hooks=open_hooks_text,
        characters=characters_text,
        count=count,
    )

    return PAYLOAD_CANDIDATE_SYSTEM, user_prompt


def parse_payload_candidate_response(
    content: str,
    expected_count: int = 3,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """解析高潮点候选 LLM 响应。

    Args:
        content: LLM 返回的完整文本（含自由分析 + JSON 围栏）
        expected_count: 期望的候选数量

    Returns:
        tuple: (candidates, degraded)
        - candidates: 候选 dict 列表（每个含 description/emotional_target/answers_question/opens_question/why_now）
        - degraded: 降级标记（None 表示成功路径）
    """
    # 尝试从 ```json ``` 围栏中抽取
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    raw_json = json_match.group(1) if json_match else None

    if not raw_json:
        # fallback：尝试直接找最外层 { ... }
        brace_match = re.search(r"\{[^{}]*\"candidates\"[^{}]*\[[^\]]*\][^{}]*\}", content, re.DOTALL)
        if brace_match:
            raw_json = brace_match.group(0)

    if not raw_json:
        return [], {
            "reason": "no_json_fence",
            "action": "empty_candidates",
            "detail": "响应中未找到 JSON 围栏",
        }

    data, parse_degraded = _safe_json_loads(raw_json)
    if parse_degraded is not None:
        return [], parse_degraded

    candidates_raw = data.get("candidates", []) if isinstance(data, dict) else []
    if not isinstance(candidates_raw, list) or not candidates_raw:
        return [], {
            "reason": "empty_candidates",
            "action": "empty_candidates",
            "detail": "JSON 解析成功但 candidates 为空",
        }

    # 字段清洗 + 必填校验
    required_fields = ["description", "emotional_target", "answers_question", "opens_question"]
    cleaned = []
    for i, cand in enumerate(candidates_raw[:expected_count + 2]):  # 多解析几个备用
        if not isinstance(cand, dict):
            continue
        item = {
            "description": str(cand.get("description", "")).strip(),
            "emotional_target": str(cand.get("emotional_target", "")).strip(),
            "answers_question": str(cand.get("answers_question", "")).strip(),
            "opens_question": str(cand.get("opens_question", "")).strip(),
            "why_now": str(cand.get("why_now", "")).strip() or None,
        }
        # V3.1：解析高潮强度自评（climax_score / climax_score_reason）
        raw_score = cand.get("climax_score")
        try:
            score = int(raw_score) if raw_score is not None else None
            if score is not None and (score < 1 or score > 10):
                score = None
        except (TypeError, ValueError):
            score = None
        item["climax_score"] = score
        item["climax_score_reason"] = str(cand.get("climax_score_reason", "")).strip() or None
        # 必填校验（缺任一字段则跳过该候选）
        if all(item[f] for f in required_fields):
            cleaned.append(item)

    if not cleaned:
        return [], {
            "reason": "all_candidates_missing_required_fields",
            "action": "empty_candidates",
            "detail": f"解析到 {len(candidates_raw)} 个候选但均缺必填字段",
        }

    return cleaned[:expected_count], None


# ============================================================
# §7.2 铺垫树生长（reasoning, T=0.3，两段式）
# ============================================================
# 逆向递归：以高潮点为根，反复问"要让它炸响，读者此刻之前必须相信/感到/误会什么"
# 递归终止三条件：a) established_facts 覆盖；b) trivial（一句话带过）；c) 深度上限
#
# 输出契约（自由分析 → JSON 抽取）：
# {
#   "nodes": [
#     {
#       "id": "n1",
#       "type": "plant|development|diversion|texture",
#       "content": "...",
#       "sets_up": ["PAYLOAD"],
#       "distance_to_payload": 1,
#       "assignment": "suppress|tighten|release_partial|texture",
#       "question_delays": "...",
#       "restraint_note": "...",
#       "subtext": "...",
#       "satisfied_by_existing": null,
#       "trivial": false
#     }
#   ],
#   "reading_order": ["n3", "n2", "n1", "PAYLOAD"]
# }


CHAIN_GROW_SYSTEM = """你是一位专精"逆向叙事设计"的结构编辑。

## 你的任务
给定一个【高潮点】，通过逆向递归，长出一棵【铺垫树】。

## 核心方法：逆向递归
以高潮点为根，反复追问唯一一个问题：
「要让它（指向高潮点的节点）炸响，读者在此刻之前必须相信什么、感到什么、或误会什么？」

每个答案成为一个【铺垫节点】。然后对每个节点继续追问同样的问题，直到前提满足以下任一终止条件：
- a) 该前提已被【已成立事实】覆盖（引用其 id 或简述）
- b) 该前提可以用一句话带过（标记 trivial=true）
- c) 深度达到 {max_depth} 层

## 节点装饰（每个节点必须填写）
对每个节点，分配以下字段：
- **type**：
  - `plant`（埋设：伏笔/锚点/物件）
  - `development`（发展：收紧张力）
  - `diversion`（转移：红鲱鱼/岔笔，误导读者）
  - `texture`（闲笔：非因果的质感元素，如环境/氛围/配角小动作）
- **assignment**（本段的写作情绪任务）：
  - `suppress`（压抑：积累势能，不释放）
  - `tighten`（收紧：逼近爆炸）
  - `release_partial`（部分释放：给一个台阶，但留更大的）
  - `texture`（闲笔呼吸段，无情绪任务）
- **question_delays**：本段让读者抱着走的问题（不回答它，保温用）
- **restraint_note**：本段明确不说破的内容（人味原理：感动是读者自己干的活）
- **subtext**：人物未说出口的真实动机（潜台词层，供有锚审计用）

## 硬约束
1. **texture 节点占比不得超过 {texture_ratio_str}**：闲笔是被选择的，不是失控的。
2. **每个节点的 sets_up 必须指向另一个已存在的节点或 PAYLOAD**：孤儿节点在构造上不存在。
3. **reading_order 必须是拓扑序**：铺垫在前，爆发在后，末位固定为 "PAYLOAD"。
4. **禁止预告腔**：埋设必须自然，禁止『他不知道的是……』式预告。
5. **distance_to_payload 准确**：高潮点直接前置=1，再前置=2，以此类推。

## 输出格式
先用 2-3 段自由分析（高潮点需要什么前提？哪些已被事实覆盖？树的形状？），
然后用如下 JSON 给出完整树：
```json
{{
  "nodes": [
    {{
      "id": "n1",
      "type": "plant",
      "content": "读者必须相信/感到/误会什么",
      "sets_up": ["PAYLOAD"],
      "distance_to_payload": 1,
      "assignment": "tighten",
      "question_delays": "...",
      "restraint_note": "...",
      "subtext": "...",
      "satisfied_by_existing": null,
      "trivial": false
    }}
  ],
  "reading_order": ["n3", "n2", "n1", "PAYLOAD"]
}}
```
JSON 必须放在 ```json ``` 围栏内。"""


CHAIN_GROW_USER_TEMPLATE = """## 高潮点（本章情绪势能的爆发瞬间）
- 描述：{payload_description}
- 情绪目标：{payload_emotional_target}
- 回答的读者问题：{payload_answers_question}
- 打开的新问题：{payload_opens_question}

## 章节卡（上下文）
- 第 {chapter_number} 章主旨：{purpose}
- 必达事件：
{must_hit_events}

## 已成立事实（递归终止依据 a：前提被这些覆盖则不再往下长）
{established_facts}

## 开放伏笔账本（可作为 plant 节点的来源）
{open_hooks}

## 本章可涉及角色
{characters}

## 前文末尾（衔接依据）
{previous_tail}

## 要求
请逆向递归长出铺垫树。先自由分析（2-3 段），然后输出 JSON。
节点数量建议 4-8 个（不含 PAYLOAD）。reading_order 末位必须是 "PAYLOAD"。"""


def build_chain_grow_prompt(
    payload: Dict[str, Any],
    chapter: Any,
    chapter_card: Any,
    established_facts: List[Dict[str, Any]],
    open_hooks: Optional[List[Any]],
    entities: Optional[List[Any]],
    previous_summary: Optional[str],
    max_depth: int = 6,
    texture_budget_ratio: float = 0.15,
) -> Tuple[str, str]:
    """构建铺垫树生长 prompt（§7.2）。

    Args:
        payload: PayloadMoment dict（含 description/emotional_target 等）
        chapter: Chapter ORM 对象
        chapter_card: ChapterCard ORM 对象
        established_facts: 已成立事实清单（角色状态/快照/伏笔/滚动摘要中提取）
        open_hooks: 开放伏笔列表
        entities: 本章关联角色列表
        previous_summary: 前章摘要（衔接依据）
        max_depth: 递归深度上限（默认 6）
        texture_budget_ratio: texture 节点占比上限（默认 0.15）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    system_prompt = CHAIN_GROW_SYSTEM.format(
        max_depth=max_depth,
        texture_ratio_str=f"{int(texture_budget_ratio * 100)}%",
    )

    # 高潮点字段
    payload_description = payload.get("description", "")
    payload_emotional_target = payload.get("emotional_target", "")
    payload_answers_question = payload.get("answers_question", "")
    payload_opens_question = payload.get("opens_question", "") or "（未指定）"

    # 章节卡字段
    chapter_number = getattr(chapter, "chapter_number", 1)
    purpose = ""
    if chapter_card is not None:
        purpose = (getattr(chapter_card, "purpose", "") or "").strip()
    if not purpose:
        purpose = "（未提供）"

    must_hit_events = []
    if chapter_card is not None:
        events = getattr(chapter_card, "must_hit_events", []) or []
        for ev in events[:5]:
            if isinstance(ev, dict):
                event_text = ev.get("event", "") or ""
                if event_text:
                    must_hit_events.append(f"  - {event_text}")
    must_hit_events_text = "\n".join(must_hit_events) if must_hit_events else "（未指定）"

    # 已成立事实（格式化为 id + 简述）
    facts_lines = []
    for f in (established_facts or [])[:15]:
        if isinstance(f, dict):
            fid = f.get("id", "") or ""
            desc = f.get("description", "") or f.get("content", "") or ""
            if desc:
                prefix = f"[{fid}] " if fid else "- "
                facts_lines.append(f"{prefix}{desc[:120]}")
    established_facts_text = "\n".join(facts_lines) if facts_lines else "（无；所有前提都需要在文中铺设）"

    # 开放伏笔
    hook_lines = []
    for h in (open_hooks or [])[:5]:
        if isinstance(h, dict):
            content = h.get("content", "") or ""
            hook_id = h.get("hook_id", "") or ""
        else:
            content = getattr(h, "content", "") or ""
            hook_id = getattr(h, "hook_id", "") or ""
        if content:
            prefix = f"[{hook_id}] " if hook_id else "- "
            hook_lines.append(f"{prefix}{content[:100]}")
    open_hooks_text = "\n".join(hook_lines) if hook_lines else "（无）"

    # 角色
    char_lines = []
    for ent in (entities or [])[:8]:
        char = getattr(ent, "character", None)
        if char is None:
            continue
        name = getattr(char, "name", "") or "未命名"
        dynamic = (getattr(char, "dynamic_state", "") or "").strip()
        if dynamic:
            dynamic = dynamic[:150] + ("…" if len(dynamic) > 150 else "")
            char_lines.append(f"- {name}（当前状态）：{dynamic}")
        else:
            static = (getattr(char, "static_prompt", "") or "").strip()
            if static:
                static = static[:100] + ("…" if len(static) > 100 else "")
                char_lines.append(f"- {name}：{static}")
            else:
                char_lines.append(f"- {name}")
    characters_text = "\n".join(char_lines) if char_lines else "（未指定）"

    previous_tail = (previous_summary or "（本章是第一章或无前文）")[:800]

    user_prompt = CHAIN_GROW_USER_TEMPLATE.format(
        payload_description=payload_description,
        payload_emotional_target=payload_emotional_target,
        payload_answers_question=payload_answers_question,
        payload_opens_question=payload_opens_question,
        chapter_number=chapter_number,
        purpose=purpose,
        must_hit_events=must_hit_events_text,
        established_facts=established_facts_text,
        open_hooks=open_hooks_text,
        characters=characters_text,
        previous_tail=previous_tail,
    )

    return system_prompt, user_prompt


def parse_chain_grow_response(
    content: str,
) -> Tuple[List[Dict[str, Any]], List[str], Optional[Dict[str, Any]]]:
    """解析铺垫树生长 LLM 响应。

    Args:
        content: LLM 返回的完整文本

    Returns:
        tuple: (nodes, reading_order, degraded)
        - nodes: SetupNode dict 列表
        - reading_order: 节点 id 序（末位 "PAYLOAD"）
        - degraded: 降级标记
    """
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    raw_json = json_match.group(1) if json_match else None

    if not raw_json:
        brace_match = re.search(r'\{[^{}]*"nodes"[^{}]*\[.*?\][^{}]*\}', content, re.DOTALL)
        if brace_match:
            raw_json = brace_match.group(0)

    if not raw_json:
        return [], [], {
            "reason": "no_json_fence",
            "action": "empty_tree",
            "detail": "响应中未找到 JSON 围栏",
        }

    data, parse_degraded = _safe_json_loads(raw_json)
    if parse_degraded is not None:
        # chain_grow 的 degraded action 是 empty_tree（区别于 candidate 的 empty_candidates）
        parse_degraded["action"] = "empty_tree"
        return [], [], parse_degraded

    nodes_raw = data.get("nodes", []) if isinstance(data, dict) else []
    reading_order = data.get("reading_order", []) if isinstance(data, dict) else []

    if not isinstance(nodes_raw, list) or not nodes_raw:
        return [], [], {
            "reason": "empty_nodes",
            "action": "empty_tree",
            "detail": "JSON 解析成功但 nodes 为空",
        }

    valid_types = {"plant", "development", "diversion", "texture"}
    valid_assignments = {"suppress", "tighten", "release_partial", "texture"}

    cleaned_nodes = []
    for n in nodes_raw:
        if not isinstance(n, dict):
            continue
        node_id = str(n.get("id", "")).strip()
        content_text = str(n.get("content", "")).strip()
        if not node_id or not content_text:
            continue
        ntype = str(n.get("type", "plant")).strip()
        if ntype not in valid_types:
            ntype = "plant"
        assignment = str(n.get("assignment", "tighten")).strip()
        if assignment not in valid_assignments:
            # texture 节点强制 assignment=texture
            assignment = "texture" if ntype == "texture" else "tighten"
        sets_up = n.get("sets_up", ["PAYLOAD"])
        if not isinstance(sets_up, list):
            sets_up = ["PAYLOAD"]
        distance = n.get("distance_to_payload", 1)
        try:
            distance = int(distance)
        except (TypeError, ValueError):
            distance = 1
        cleaned_nodes.append({
            "id": node_id,
            "type": ntype,
            "content": content_text,
            "sets_up": sets_up,
            "distance_to_payload": max(0, distance),
            "assignment": assignment,
            "question_delays": str(n.get("question_delays", "") or "").strip() or None,
            "restraint_note": str(n.get("restraint_note", "") or "").strip() or None,
            "subtext": str(n.get("subtext", "") or "").strip() or None,
            "satisfied_by_existing": n.get("satisfied_by_existing"),
            "future_payoff": n.get("future_payoff"),
            "beat_id": n.get("beat_id"),
            "trivial": bool(n.get("trivial", False)),
            "planted_in_text": None,  # 审计回填，初始为空
        })

    if not cleaned_nodes:
        return [], [], {
            "reason": "all_nodes_invalid",
            "action": "empty_tree",
            "detail": "解析到节点但均缺 id 或 content",
        }

    # reading_order 清洗：确保是字符串列表，末位补 PAYLOAD
    if not isinstance(reading_order, list):
        reading_order = []
    reading_order = [str(x).strip() for x in reading_order if str(x).strip()]
    if not reading_order or reading_order[-1] != "PAYLOAD":
        reading_order.append("PAYLOAD")

    return cleaned_nodes, reading_order, None


# ============================================================
# §7.3 铺垫写作（creative, T=0.8，距离指令模板）
# ============================================================
# 爆发已成文（payload.text），铺垫段朝爆炸写
# 每段输入：P0 文风卡/样本（缓存前缀）→ P1 章节卡+本段节点+角色状态
#           → P2 爆炸成文锚 + 本段 distance 指令 + restraint_note + question 任务 + 前段尾巴
#
# 本函数只构建 system + user 两段；ContextEngine 层级的 P0/P1/P2 布局由 fuse_writer 调用方组装
# 这里给出的是"本段距离指令"的核心模板（直接进 user prompt 的尾部）


FUSE_WRITE_SYSTEM_TEMPLATE = """你是一位技艺精湛的小说家，正在写作一章小说的【铺垫段】——它最终将引向一个已经写好的【爆发段】。

## 文风契约（务必遵守）
{style_contract}

{author_samples_block}

## 铺垫写作的核心约束（D2/D3/D7 原则）

1. **朝爆炸写，禁止提前爆炸**：你已经知道爆发段写了什么（见下），但本段距离爆炸还有若干节点，禁止任何形式的提前释放——小高潮、情绪爆发、真相点破都是过早泄底。
2. **距离即指令**：本段与爆炸的距离决定你的任务（suppress=压抑积累 / tighten=收紧逼近 / release_partial=给一个台阶但留更大的 / texture=闲笔呼吸段）。
3. **问题流保温**：本段要让读者抱着一个问题走，且不回答它。压抑≠无聊。
4. **埋设自然**：本段需要埋设某些前提（sets_up），但禁止预告腔——『他不知道的是……』式写法是禁用的。
5. **克制不说破**：restraint_note 标注的内容，本段绝对不能说破。人味原理：感动是读者自己干的活，文本只负责布置条件。

## 写作要求
- 中文写作，跟随人物的呼吸节奏（句长跟着情绪的生理状态走）。
- 允许生产性的"错"：突然的短句、不合逻辑的联想、悲伤场景里的笑话——这些是人味的栖息地。
- 不要解释、不要总结、不要段末升华。把活留给读者。"""


FUSE_WRITE_USER_TEMPLATE = """【本章爆发段已成文】（供你对准情绪与文风，禁止复述其内容）：
{payload_anchor}

【你的铺垫段】任务书
- 本段距离高潮点还有 {distance} 个节点
- 本段情绪任务：{assignment}（{assignment释义}）
- 本段要让读者抱着这个问题走（不回答它）：「{question}」
- 本段需要埋设（sets_up，自然埋入，禁止预告腔）：{sets_up}
- 本段绝对不说破（restraint）：{restraint_note}
- 人物潜台词（subtext，只通过动作/对话弦外之音传达，禁止直陈）：{subtext}

【衔接】
- 前段结尾（保持呼吸连续）：{tail_500}

【字数目标】{target_words} 字（边写边倒数，接近目标时自然收束，不要硬凑）

请直接输出本段正文，不要任何前言/解释/标题。"""


# assignment 释义（D3）
_ASSIGNMENT_GLOSS = {
    "suppress": "压抑积累势能，不给任何释放；读者要感到『事情在压过来』但还没爆",
    "tighten": "收紧逼近爆炸；张力上升，但高潮点仍未到；每一步都让读者以为『是不是要爆了』而又没爆",
    "release_partial": "给读者一个台阶（小满足/小揭露），但留下更大的未释放；台阶是阶梯，不是顶点",
    "texture": "闲笔呼吸段；节奏放缓，写环境/氛围/配角小动作；为下一段的收紧蓄力",
}


def build_fuse_write_prompt(
    payload_text: str,
    node: Dict[str, Any],
    tail_500: str,
    target_words: int,
    style_card: Any = None,
    author_samples: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """构建铺垫段写作 prompt（§7.3）。

    Args:
        payload_text: 爆发段成文（或其关键段落锚，约 500-800 字）
        node: 当前要写的 SetupNode dict（含 distance_to_payload/assignment/question_delays/sets_up/restraint_note/subtext）
        tail_500: 前段结尾（约 500 字，保持呼吸连续）
        target_words: 本段字数目标
        style_card: 可选 StyleCard ORM 对象（文风契约）
        author_samples: 可选作者样本列表（few-shot 文风锚定）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    # 文风契约
    style_contract = "（未提供文风卡；按通用文学小说风格写作）"
    if style_card is not None:
        positive = getattr(style_card, "positive_profile", {}) or {}
        negative = getattr(style_card, "negative_list", []) or []
        dialogue_ratio = getattr(style_card, "dialogue_ratio_target", None)
        parts = []
        if positive:
            parts.append(f"正面画像：{json.dumps(positive, ensure_ascii=False)[:300]}")
        if negative:
            neg_items = []
            for item in negative[:10]:
                if isinstance(item, dict):
                    word = item.get("word") or item.get("phrase") or ""
                    alt = item.get("alternative", "")
                    if word:
                        neg_items.append(f"「{word}」→「{alt}」" if alt else f"「{word}」")
                elif isinstance(item, str):
                    neg_items.append(f"「{item}」")
            if neg_items:
                parts.append(f"禁用表达（命中即失败）：{', '.join(neg_items)}")
        if dialogue_ratio:
            parts.append(f"对话占比目标：{int(dialogue_ratio * 100)}%")
        if parts:
            style_contract = "\n".join(parts)

    # 作者样本（few-shot）
    author_samples_block = ""
    if author_samples:
        sample_lines = []
        for i, s in enumerate(author_samples[:3], 1):
            s_text = str(s)[:400]
            sample_lines.append(f"【样本 {i}】\n{s_text}")
        if sample_lines:
            author_samples_block = "## 作者样本（对齐这种文风）\n" + "\n\n".join(sample_lines)

    system_prompt = FUSE_WRITE_SYSTEM_TEMPLATE.format(
        style_contract=style_contract,
        author_samples_block=author_samples_block,
    )

    # 节点字段
    distance = node.get("distance_to_payload", 1)
    assignment = node.get("assignment", "tighten")
    assignment_gloss = _ASSIGNMENT_GLOSS.get(assignment, _ASSIGNMENT_GLOSS["tighten"])
    question = node.get("question_delays") or "（本段不强制问题流；自然推进即可）"
    sets_up_items = node.get("sets_up", [])
    if isinstance(sets_up_items, list):
        sets_up_text = "；".join(str(x) for x in sets_up_items) if sets_up_items else "（无显式埋设要求）"
    else:
        sets_up_text = str(sets_up_items) or "（无显式埋设要求）"
    # sets_up 是 id 列表，对作者无用；这里用 node.content 作为"要埋设什么"的描述
    sets_up_text = node.get("content", sets_up_text)
    restraint_note = node.get("restraint_note") or "（无显式克制要求；遵守通用『不解释、不升华』）"
    subtext = node.get("subtext") or "（无）"

    # payload 锚（截到 800 字，防 token 爆炸）
    payload_anchor = (payload_text or "")[:800]
    if not payload_anchor:
        payload_anchor = "（爆发段尚未成文；请按节点描述对准情绪方向）"

    user_prompt = FUSE_WRITE_USER_TEMPLATE.format(
        payload_anchor=payload_anchor,
        distance=distance,
        assignment=assignment,
        assignment释义=assignment_gloss,
        question=question,
        sets_up=sets_up_text,
        restraint_note=restraint_note,
        subtext=subtext,
        tail_500=(tail_500 or "（本段是首段，无前段衔接）")[:500],
        target_words=target_words,
    )

    return system_prompt, user_prompt


# ============================================================
# V3.1 §4.3 铺陈段写作（双轨工艺，去压抑约束，creative, T=0.8）
# ============================================================
# 规格 §4.3：
# - 前向滚动扩写（沿用现有 Track A / fuse_writer 实现）
# - 不施加"压抑"约束（离高潮远，无需压着写）
# - 双轨"每拍自我完满"的病灶在这个距离上不发作，所以无需压抑保温
# - 并发与速度优先
#
# 与 §7.3 铺垫写作（buildup 区）的区别：
# - 不注入"禁止提前释放"硬约束
# - 不强制 question 流保温
# - 自然推进，允许小满足与小情绪起伏
# - 仍遵守文风契约 + restraint_note + subtext（这些是"不破坏后续"的底线）


DEVELOPMENT_WRITE_SYSTEM_TEMPLATE = """你是一位技艺精湛的小说家，正在写作一章小说的【铺陈段】——离高潮较远的前段，任务是平稳推进叙事、自然埋设本段铺垫，把读者送到后段门口。

## 文风契约（务必遵守）
{style_contract}

{author_samples_block}

## 铺陈段写作的约束（V3.1 §4.3 双轨工艺）

1. **前向滚动扩写**：以前段尾巴为呼吸起点，自然延续叙事。每段自我完满——读者读到这一段能感到"推进了一步"。
2. **不压抑**：与靠近高潮的蓄势段不同，铺陈段离高潮远，无需"压着写"。允许小满足、小情绪起伏、闲笔呼吸。
3. **自然埋设**：本段需要埋设某些前提（sets_up），但禁止预告腔——『他不知道的是……』式写法是禁用的。
4. **克制底线**：restraint_note 标注的内容，本段不能说破。人味原理：感动是读者自己干的活。
5. **节奏即呼吸**：句长跟着情绪的生理状态走。

## 写作要求
- 中文写作，跟随人物的呼吸节奏。
- 允许生产性的"错"：突然的短句、不合逻辑的联想——这些是人味的栖息地。
- 不要解释、不要总结、不要段末升华。把活留给读者。"""


DEVELOPMENT_WRITE_USER_TEMPLATE = """【本章高潮段已成文】（供你了解全章走向，禁止复述其内容）：
{payload_anchor}

【你的铺陈段】任务书
- 本段离高潮较远（distance={distance}），任务是【平稳推进 + 自然埋设】，不施加压抑约束
- 本段需要埋设（sets_up，自然埋入，禁止预告腔）：{sets_up}
- 本段绝对不说破（restraint 底线）：{restraint_note}
- 人物潜台词（subtext，只通过动作/对话弦外之音传达，禁止直陈）：{subtext}

【衔接】
- 前段结尾（保持呼吸连续）：{tail_500}

【字数目标】{target_words} 字（边写边倒数，接近目标时自然收束，不要硬凑）

请直接输出本段正文，不要任何前言/解释/标题。"""


def build_development_write_prompt(
    payload_text: str,
    node: Dict[str, Any],
    tail_500: str,
    target_words: int,
    style_card: Any = None,
    author_samples: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """构建铺陈段写作 prompt（V3.1 §4.3，双轨工艺去约束版本）。

    与 build_fuse_write_prompt（蓄势段）的区别：
    - system prompt 不注入"禁止提前释放"硬约束
    - user prompt 不强制 question 流保温，强调"平稳推进 + 自然埋设"
    - 仍保留 sets_up / restraint_note / subtext（这些是"不破坏后续"的底线）

    Args:
        payload_text: 高潮段成文（或其关键段落锚）
        node: 当前要写的 SetupNode dict（含 distance_to_climax/sets_up/restraint_note/subtext）
        tail_500: 前段结尾（约 500 字，保持呼吸连续）
        target_words: 本段字数目标
        style_card: 可选 StyleCard ORM 对象（文风契约）
        author_samples: 可选作者样本列表

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    # 文风契约（与 build_fuse_write_prompt 一致的逻辑）
    style_contract = "（未提供文风卡；按通用文学小说风格写作）"
    if style_card is not None:
        positive = getattr(style_card, "positive_profile", {}) or {}
        negative = getattr(style_card, "negative_list", []) or []
        dialogue_ratio = getattr(style_card, "dialogue_ratio_target", None)
        parts = []
        if positive:
            parts.append(f"正面画像：{json.dumps(positive, ensure_ascii=False)[:300]}")
        if negative:
            neg_items = []
            for item in negative[:10]:
                if isinstance(item, dict):
                    word = item.get("word") or item.get("phrase") or ""
                    alt = item.get("alternative", "")
                    if word:
                        neg_items.append(f"「{word}」→「{alt}」" if alt else f"「{word}」")
                elif isinstance(item, str):
                    neg_items.append(f"「{item}」")
            if neg_items:
                parts.append(f"禁用表达（命中即失败）：{', '.join(neg_items)}")
        if dialogue_ratio:
            parts.append(f"对话占比目标：{int(dialogue_ratio * 100)}%")
        if parts:
            style_contract = "\n".join(parts)

    # 作者样本
    author_samples_block = ""
    if author_samples:
        sample_lines = []
        for i, s in enumerate(author_samples[:3], 1):
            s_text = str(s)[:400]
            sample_lines.append(f"【样本 {i}】\n{s_text}")
        if sample_lines:
            author_samples_block = "## 作者样本（对齐这种文风）\n" + "\n\n".join(sample_lines)

    system_prompt = DEVELOPMENT_WRITE_SYSTEM_TEMPLATE.format(
        style_contract=style_contract,
        author_samples_block=author_samples_block,
    )

    # 节点字段（双键兼容读取 distance）
    distance_raw = node.get("distance_to_climax")
    if distance_raw is None:
        distance_raw = node.get("distance_to_payload", 1)
    try:
        distance = int(distance_raw)
    except (TypeError, ValueError):
        distance = 1

    sets_up_items = node.get("sets_up", [])
    if isinstance(sets_up_items, list):
        sets_up_text = "；".join(str(x) for x in sets_up_items) if sets_up_items else "（无显式埋设要求）"
    else:
        sets_up_text = str(sets_up_items) or "（无显式埋设要求）"
    sets_up_text = node.get("content", sets_up_text)
    restraint_note = node.get("restraint_note") or "（无显式克制要求；遵守通用『不解释、不升华』）"
    subtext = node.get("subtext") or "（无）"

    # payload 锚（截到 800 字）
    payload_anchor = (payload_text or "")[:800]
    if not payload_anchor:
        payload_anchor = "（高潮段尚未成文；请按节点描述对准情绪方向）"

    user_prompt = DEVELOPMENT_WRITE_USER_TEMPLATE.format(
        payload_anchor=payload_anchor,
        distance=distance,
        sets_up=sets_up_text,
        restraint_note=restraint_note,
        subtext=subtext,
        tail_500=(tail_500 or "（本段是首段，无前段衔接）")[:500],
        target_words=target_words,
    )

    return system_prompt, user_prompt


# ============================================================
# §7.4 有锚审计（reasoning, T=0.1）—— Slice B 占位
# ============================================================
# 详细实现见 Slice B 的 anchored_auditor.py
# 这里仅给出 system prompt 与解析函数，供 Slice B 复用


ANCHORED_AUDIT_SYSTEM = """你是结构审计员。不做文学评价，只验证三件事，全部给证据：

① **落地**：每个铺垫节点是否在正文中真实落地？给原文引用+位置；没有则标记断线。
② **过早泄底**：各铺垫段是否存在提前释放（情绪峰值/真相泄露）？给引用。
③ **高潮爆发**：读爆发段及其前 500 字，你的情绪是否被爆发（1-10 分+一句话理由）？

## 输出格式
先用 1-2 段自由分析整体结论，然后用如下 JSON：
```json
{
  "planted": [{"node_id": "...", "quote": "...", "offset": [start, end]}],
  "broken": ["未落地的 node_id 列表"],
  "premature": [{"segment_index": 0, "quote": "...", "reason": "..."}],
  "detonation_score": 7,
  "detonation_reason": "..."
}
```
JSON 必须放在 ```json ``` 围栏内。"""


def build_anchored_audit_prompt(
    nodes: List[Dict[str, Any]],
    full_text: str,
) -> Tuple[str, str]:
    """构建有锚审计 prompt（§7.4，Slice B 使用）。

    Args:
        nodes: SetupNode dict 列表（含 id/content/restraint_note）
        full_text: 完整正文（铺垫段 + 爆发段）

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    nodes_block_lines = []
    for n in nodes:
        nid = n.get("id", "")
        content = n.get("content", "")[:120]
        restraint = n.get("restraint_note") or "（无）"
        nodes_block_lines.append(f"- [{nid}] {content}（不说破：{restraint}）")
    nodes_block = "\n".join(nodes_block_lines) if nodes_block_lines else "（无节点）"

    user_prompt = f"""## 铺垫树节点清单（需验证是否落地 + restraint 是否被违反）
{nodes_block}

## 正文全文（用于落地/过早泄底/高潮爆发验证）
{full_text[:8000]}

## 要求
逐节点验证落地（给原文引用+字符偏移），扫描过早泄底，给爆发段打分。输出 JSON。"""

    return ANCHORED_AUDIT_SYSTEM, user_prompt


def parse_anchored_audit_response(
    content: str,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """解析有锚审计响应（Slice B 使用）。

    Returns:
        tuple: (audit_result, degraded)
    """
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", content, re.DOTALL)
    raw_json = json_match.group(1) if json_match else None
    if not raw_json:
        return {}, {"reason": "no_json_fence", "action": "empty_audit"}
    data, parse_degraded = _safe_json_loads(raw_json)
    if parse_degraded is not None:
        parse_degraded["action"] = "empty_audit"
        return {}, parse_degraded
    return data, None

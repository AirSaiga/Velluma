# Velluma - 世界事件解析/抽取 Prompt（W3 速记 + W4 候选回流）
# AGPL-3.0
"""
世界事件的自然语言 → 结构化草稿（docs/world-writing-bridge.md §4.3 / §4.5）。

两条链路共用本文件的风格约定（对齐 nle_prompts 的 emergent_facts）：
- parse（W3）：作者一句话速记 → 单条事件草稿，前端预填表单，作者确认才入账。
- extract（W4）：settle/finish 的正文 → 多条候选事件草稿，进待确认池，作者 ✓ 才转正。

红线：两条链路都只产草稿、绝不落库（解析/落库分离，复刻 extract_emergent_facts 哲学）。
"""

import json

_EVENT_TYPE_DOC = """事件类型（11 种，选最贴切的一个）：
- birth 出生 | death 死亡 | move 移动/迁徙 | battle 战斗 | territory_change 疆域变更
- found 建立/创立 | destroy 摧毁/陷落 | alliance 结盟 | war_declare 宣战
- coronation 加冕/就任 | custom 其他（写不进以上类型的剧情事件）"""


def _roster_text(entities, locations) -> str:
    ents = []
    for e in entities:
        aliases = [str(a) for a in (getattr(e, "aliases", None) or []) if a]
        alias_part = f"（别名：{'、'.join(aliases)}）" if aliases else ""
        ents.append(f"- {e.name} [{e.entity_type}]{alias_part}")
    locs = [f"- {l.name} [地点]" for l in locations]
    return "\n".join(ents + locs) or "（世界页暂无实体与地点）"


# ============================================================
# W3：一句话速记 → 单条事件草稿
# ============================================================

_PARSE_SYSTEM = f"""你是小说世界设定的速记解析器。作者用一句口语记录一件世界大事，你把它解析成一条结构化事件草稿。

{_EVENT_TYPE_DOC}

规则：
- participants 只填角色名单中出现的人（名或别名精确对应），名单外的人不要编 id，留在 note 里
- location 填地点名单中的名字，名单外填 null
- day_offset：事件发生在「当前时刻」之后几天（之前为负数）；速记里通常没有时间信息，默认 0
- duration_days：事件持续天数（移动/迁徙类按常理估，其余默认 0）
- 宁缺勿滥：解析不出就 event_type 填 "custom"、participants 留空数组，不要编造

输出 JSON：
{{
  "event_type": "move",
  "summary": "一句话概括（≤20字）",
  "participants": ["角色名"],
  "location": "地点名或null",
  "day_offset": 0,
  "duration_days": 0,
  "note": "保留速记里的关键信息（谁对谁做了什么，≤40字）"
}}
只返回 JSON。"""


def build_parse_event_prompt(text: str, t: int, entities, locations):
    """构造 (system, user)：一句话速记 → 事件草稿。"""
    user = f"""当前世界时刻（连续日计数）：t = {t}

角色与地点名单：
{_roster_text(entities, locations)}

作者速记：
---
{text}
---

请解析成事件草稿。"""
    return _PARSE_SYSTEM, user


# ============================================================
# W4：正文 → 候选事件草稿（批量）
# ============================================================

_EXTRACT_SYSTEM = f"""你是小说世界设定的事件抽取器。从正文段落中抽取「改变了世界状态的事实」作为候选事件，供作者确认后进入世界事件账本。

{_EVENT_TYPE_DOC}

只抽确定性事实（正文明确发生了的），不抽计划、愿望、传闻和对话中的假设。
优先级：位置变化(move)、生死(birth/death)、势力消长(battle/found/destroy/alliance/war_declare/territory_change)。
每个候选给 day_offset：以本章时刻 t 为基准，段落内相对时序（同段多个事件用小偏移区分先后）。

输出 JSON：
{{
  "candidates": [
    {{
      "event_type": "move",
      "summary": "一句话概括（≤20字）",
      "participants": ["角色名"],
      "location": "地点名或null",
      "day_offset": 0,
      "duration_days": 0,
      "note": "正文依据（≤40字）"
    }}
  ]
}}
没有可抽取的事实时返回空数组。只返回 JSON。"""


def _recent_events_block(recent_events) -> str:
    """已入账事件排除块（A5a 候选去重）。空/无 note → 空串（零变化契约：
    无事件书的 user prompt 与旧版逐字节一致）。

    行格式「- 第N日 类型：note截断」：类型用原始 key（与 LLM 输出 JSON 的
    event_type 同词表，比对零翻译损耗）；note 截 40 字与速记链路同预算。
    """
    lines = []
    for e in recent_events or []:
        note = str(getattr(e, "note", None) or "").strip()
        if not note:
            continue  # 空 note 无文本比对价值，不占排除块行数
        etype = str(getattr(e, "event_type", None) or "")
        try:
            day = int(getattr(e, "time_start", 0) or 0)
        except (TypeError, ValueError):
            day = 0
        lines.append(f"- 第{day}日 {etype}：{note[:40]}")
    if not lines:
        return ""
    return (
        "\n已入账事件（以下事件已发生并记入账本，勿重复提取，同义换措辞也算重复）：\n"
        + "\n".join(lines)
        + "\n"
    )


def _muted_types_block(muted_types) -> str:
    """作者拒收史排除块（学着闭嘴，2026-08-25 战略定稿）。

    空 → 空串（零变化契约同 _recent_events_block：无拒收史的书 prompt
    逐字节不变）。类型用原始 key（与 LLM 输出 JSON 的 event_type 同词表，
    比对零翻译损耗，同 recent_events 块的选型理由）。
    """
    if not muted_types:
        return ""
    return (
        "\n作者已多次拒绝以下类型的候选，本次不要再提："
        + "、".join(str(t) for t in muted_types)
        + "\n"
    )


def build_event_candidates_prompt(
    text: str,
    t: int,
    entities,
    locations,
    max_candidates: int = 6,
    recent_events=None,
    muted_types=None,
):
    """构造 (system, user)：正文 → 候选事件草稿列表。

    recent_events：t 时刻之前的已入账事件（WorldEvent 或鸭子同形对象），
    注入排除块防 LLM 重复提取；None/空 → prompt 与旧版逐字节一致。
    muted_types：学着闭嘴的作者拒收类型（quiet_learning 派生）；None/空 → 零变化。
    """
    user = f"""当前世界时刻（连续日计数）：t = {t}

角色与地点名单：
{_roster_text(entities, locations)}
{_recent_events_block(recent_events)}{_muted_types_block(muted_types)}
正文：
---
{text[:4000]}
---

请抽取候选事件（最多 {max_candidates} 条，按叙事顺序）。"""
    return _EXTRACT_SYSTEM, user


def _safe_json(raw: str) -> dict:
    """容错 JSON 解析（LLM 输出可能带 markdown 围栏/前后缀）。"""
    try:
        return json.loads(raw)
    except Exception:
        pass
    try:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start : end + 1])
    except Exception:
        pass
    return {}

# Velluma - belief 域折叠（B3 · docs/world-kernel-foundation.md §2 决策 2）
# AGPL-3.0
"""认知平面的曝光级折叠：各角色以为发生了什么（纯函数，零 LLM/零 NLP）。

粒度纪律（决策 2）：
- Level 0 曝光（廉价默认）：在场/参与（participants 推导）+ told/discover/
  witness 事件——角色「经历过或被告知」某事件；
- Level 1 声明秘密（canon 命题注册表，按 id 引用）——told/discover 的
  proposition_ref 或 misbelieve 显式声明；
- 四值可答（决策 4）：knows / believes_false / unaware / unknown——
  unknown 合法且重要（证据不足≠不存在，诚实降级）；
- 明确不做：推理闭包（角色能推导出什么——逻辑全知是死路）。

payload 契约（与 fold.py 模块头一致）：
- told{subject, object_event|proposition_ref}
- discover{subject, evidence_of}
- misbelieve{subject, proposition_ref, false_content}
- witness{subject, object_event}

副作用：无（纯函数）。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

KNOWS = "knows"
BELIEVES_FALSE = "believes_false"
UNAWARE = "unaware"
UNKNOWN = "unknown"

EPISTEMIC_KINDS = ("told", "discover", "witness", "misbelieve")


def fold_belief(events: List[Any], t: int) -> Dict[str, Dict[str, Any]]:
    """事件流 → 认知状态（per-entity）。

    Args:
        events: 有序事件行（WorldEvent 或同形 dict；时间过滤由调用方完成）。
        t: 叙事时刻（仅用于忽略 time_start > t 的事件，防御性双保险）。

    Returns:
        {entity_id: {
            "knows_events": [event_id],
            "knows_propositions": [canon_node_id],
            "believes_false": [{proposition_ref, false_content}],
        }}
    """
    state: Dict[str, Dict[str, Any]] = {}

    def _slot(eid: str) -> Dict[str, Any]:
        if eid not in state:
            state[eid] = {
                "knows_events": [],
                "knows_propositions": [],
                "believes_false": [],
            }
        return state[eid]

    def _iter(event: Any, key: str, default=None):
        payload = getattr(event, "payload", None)
        if payload is None and isinstance(event, dict):
            payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        value = payload.get(key, default)
        if value is None and isinstance(event, dict):
            value = event.get(key, default)
        return value

    for event in events:
        try:
            etype = getattr(event, "event_type", None) or (
                event.get("event_type") if isinstance(event, dict) else None
            )
            t_start = getattr(event, "time_start", None)
            if t_start is None and isinstance(event, dict):
                t_start = event.get("time_start")
            if t_start is not None and t_start > t:
                continue
            eid = str(getattr(event, "id", "") or (event.get("id") if isinstance(event, dict) else "") or "")

            subjects: Set[str] = set()
            subject = _iter(event, "subject")
            if subject:
                subjects.add(str(subject))
            # 在场曝光：认知事件的参与者也视为知晓者（Level 0 推导）
            parts = getattr(event, "participant_ids", None)
            if parts is None and isinstance(event, dict):
                parts = event.get("participant_ids")
            for p in parts or []:
                subjects.add(str(p))

            if etype in ("told", "discover", "witness"):
                obj_event = _iter(event, "object_event") or _iter(event, "evidence_of")
                prop = _iter(event, "proposition_ref")
                for s in subjects:
                    slot = _slot(s)
                    if obj_event:
                        target = str(obj_event)
                        if target not in slot["knows_events"]:
                            slot["knows_events"].append(target)
                    if prop:
                        target = str(prop)
                        if target not in slot["knows_propositions"]:
                            slot["knows_propositions"].append(target)
            elif etype == "misbelieve":
                prop = _iter(event, "proposition_ref")
                false_content = str(_iter(event, "false_content") or "")
                for s in subjects:
                    slot = _slot(s)
                    if prop and not any(
                        b.get("proposition_ref") == str(prop) for b in slot["believes_false"]
                    ):
                        slot["believes_false"].append({
                            "proposition_ref": str(prop),
                            "false_content": false_content,
                        })
        except Exception:
            continue  # 单事件损坏不拖垮整域（诚实降级）
    return state


def proposition_status(
    proposition_ref: str,
    perspective_set: Iterable[str],
    belief_state: Dict[str, Dict[str, Any]],
) -> str:
    """视角集对某命题的四值回答（B3 的 clearance 查询面）。

    优先级：believes_false > knows > unaware > unknown——
    误信覆盖知晓（作者声明「他以为的」优先于「他知道的」）；
    perspective 内任一成员知晓即 knows（场景级配给的集体语义）；
    命题不在任何证据中 → unknown（区别于 unaware：unaware=有曝光证据
    证明其不知【本实现中由 knows_events 反推，暂不单独判定】，unknown=
    无证据——诚实降级，不猜）。
    """
    pids = [str(p) for p in perspective_set]
    if not pids:
        return UNKNOWN
    any_knows = False
    for pid in pids:
        slot = belief_state.get(pid) or {}
        if any(b.get("proposition_ref") == str(proposition_ref)
               for b in slot.get("believes_false") or []):
            return BELIEVES_FALSE
        if str(proposition_ref) in (slot.get("knows_propositions") or []):
            any_knows = True
    return KNOWS if any_knows else UNKNOWN

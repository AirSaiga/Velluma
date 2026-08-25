# Velluma - NLE-ADF 3.0 变化检测器
# AGPL-3.0
"""
纯算法变化检测——世界模型的"感觉器官"。

零 LLM、零 DB 写。输入作者状态心跳 + 世界模型快照，输出 ChangeSignal 列表。
调度器消费信号决定是否触发意图反推（Token 主战场）。

信号类型：
- scene_shift：段落首句含时间/地点标记词（"第二天"/"与此同时"）
- new_entity：层 1 最新事实含新角色名（不在已有 entities 里）
- segment_threshold：沉淀段数跨越节点（2→3, 4→5...）
- emotion_turn：情绪转折词密度突变（"突然"/"然而"密度上升）
- outline_updated：作者编辑了大纲文本

节流：detect 内部合并短窗口信号 + 最小间隔判断（实际节流由调度器 30s 闸门兜底）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ChangeSignal:
    """单个变化信号。"""
    kind: str               # scene_shift | new_entity | segment_threshold | emotion_turn | outline_updated
    evidence: str = ""      # 触发证据（如"段落首句含'第二天'"）
    severity: float = 0.5   # 0-1，影响调度决策（高 severity 更可能触发反推）


@dataclass
class AuthorState:
    """前端心跳上报的作者状态（纯数据，无逻辑）。"""
    chapter_id: str
    word_count: int = 0
    segment_count: int = 0
    paused_ms: int = 0
    cursor_at_paragraph_end: bool = False
    has_outline: bool = False
    outline_text: str = ""
    recent_text: str = ""        # 当前段落尾部（≤500字）
    latest_fact: Optional[Dict] = None  # 最新沉淀的层1事实（如有）
    summoned: bool = False       # Tab 显式点名要零件（豁免句子级闸门——作者主权）


# ============================================================
# 检测器
# ============================================================

# 场景切换标记词
_SCENE_SHIFT_MARKERS = (
    "第二天", "次日", "三天后", "一周后", "回到", "与此同时", "另一边",
    "不久", "随后", "后来", "那天晚上", "清晨", "黄昏", "入夜",
)
# 情绪转折词
_EMOTION_TURN_WORDS = ("突然", "然而", "可是", "不料", "谁知", "偏偏", "猛地", "骤然")
# 段落跨越节点（达到这些段数时触发重检）
_SEGMENT_THRESHOLDS = {2, 4, 6, 8, 10}


def detect(
    state: AuthorState,
    model_snapshot: Dict[str, Any],
    prev_outline_sig: str = "",
) -> List[ChangeSignal]:
    """检测变化信号。纯算法，零 LLM / 零 DB 写。

    Args:
        state: 作者状态心跳
        model_snapshot: 世界模型快照（WorldModelRepository.snapshot 产出）
        prev_outline_sig: 上次大纲签名（调度器缓存，检测 outline_updated）

    Returns:
        ChangeSignal 列表（可能为空）
    """
    signals: List[ChangeSignal] = []
    recent = (state.recent_text or "").strip()
    facts = model_snapshot.get("facts", [])
    fact_count = model_snapshot.get("fact_count", 0)

    # ---- 1. 场景切换 ----
    if recent:
        first_clause = recent.split("。", 1)[0][:40]  # 首句前 40 字
        for marker in _SCENE_SHIFT_MARKERS:
            if marker in first_clause:
                signals.append(ChangeSignal(
                    kind="scene_shift",
                    evidence=f"段落首句含「{marker}」",
                    severity=0.6,
                ))
                break

    # ---- 2. 新角色出场（最新事实含新实体）----
    latest_fact = state.latest_fact or (facts[-1] if facts else None)
    if latest_fact and latest_fact.get("entities"):
        existing_names = set()
        for f in facts[:-1]:  # 排除自身
            for e in f.get("entities", []):
                if isinstance(e, dict):
                    existing_names.add(e.get("name", ""))
        for e in latest_fact["entities"][:3]:
            name = e.get("name", "") if isinstance(e, dict) else ""
            if name and name not in existing_names:
                signals.append(ChangeSignal(
                    kind="new_entity",
                    evidence=f"新角色/实体「{name}」出场",
                    severity=0.7,
                ))
                break

    # ---- 3. 段落跨越阈值 ----
    if fact_count in _SEGMENT_THRESHOLDS:
        signals.append(ChangeSignal(
            kind="segment_threshold",
            evidence=f"已沉淀 {fact_count} 段",
            severity=0.5,
        ))

    # ---- 4. 情绪转折（密度突变）----
    if recent:
        turn_count = sum(recent.count(w) for w in _EMOTION_TURN_WORDS)
        if turn_count >= 2 and len(recent) < 300:
            signals.append(ChangeSignal(
                kind="emotion_turn",
                evidence=f"段落含 {turn_count} 个情绪转折词",
                severity=0.55,
            ))

    # ---- 5. 大纲变更 ----
    if state.has_outline and state.outline_text:
        current_sig = _text_sig(state.outline_text)
        if prev_outline_sig and current_sig != prev_outline_sig:
            signals.append(ChangeSignal(
                kind="outline_updated",
                evidence="作者编辑了章节大纲",
                severity=0.9,  # 最强信号——作者自己更新了意图
            ))

    return signals


def aggregate_severity(signals: List[ChangeSignal]) -> float:
    """合并多个信号的严重度（取最高，多信号略加权）。"""
    if not signals:
        return 0.0
    base = max(s.severity for s in signals)
    # 多信号叠加略加权（上限 1.0）
    if len(signals) >= 2:
        base = min(1.0, base + 0.1)
    return base


def _text_sig(text: str) -> str:
    """文本签名（取前 100 字 + 长度，用于检测变更）。"""
    return f"{len(text)}:{text[:100]}"

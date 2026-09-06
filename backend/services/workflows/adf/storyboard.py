# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
"""
镜头景别规划器（V4.3 Storyboard，集成到 ADF Phase 4）。

职责：
- 在正向流写作前，为每段分配景别（5 档）+ 运镜指令
- 解决"远景→近景切换突兀"问题（第 1 章诊断的 Q3）

设计依据：第 6 轮讨论——LLM 同时当导演+编剧没有"运镜意识"

景别 5 档（来自电影语言）：
- wide（远景）：建立世界，交代氛围，无人物特写
- full（全景）：群体描写，个体只是色块
- medium（中景）：人物互动，环境作背景
- close（近景）：动作细节，心理活动
- macro（特写）：单一细节放大，情绪密度最高

运镜 5 种（场景间过渡）：
- cut（硬切）：跳剪，靠读者脑补（快节奏）
- push_in（缓推）：从远景渐推到近景（蓄势）
- pull_out（拉远）：从近景拉到全景（收束）
- counter（反打）：视角跳切到另一对象（如主角→观察者）
- fade（淡入淡出）：时间/场景大转换

分配策略（纯算法，按段序号 + 情绪曲线）：
- 第 1 段：wide（建立世界）
- 中段：medium / close 交替
- 倒数第 2 段：close（情绪累积）
- 末段（高潮）：macro（特写爆破）
- 段间运镜：根据相邻景别差决定
"""

import logging
from typing import List, Optional, Tuple

from backend.services.workflows.adf.types import EmotionCurve

logger = logging.getLogger(__name__)


# ============================================================
# 景别常量
# ============================================================

SHOT_WIDE = "wide"        # 远景
SHOT_FULL = "full"        # 全景
SHOT_MEDIUM = "medium"    # 中景
SHOT_CLOSE = "close"      # 近景
SHOT_MACRO = "macro"      # 特写

SHOT_LABELS = {
    SHOT_WIDE: "远景",
    SHOT_FULL: "全景",
    SHOT_MEDIUM: "中景",
    SHOT_CLOSE: "近景",
    SHOT_MACRO: "特写",
}

# 景别的"距离值"（用于运镜判断）
SHOT_DISTANCE = {
    SHOT_WIDE: 1,
    SHOT_FULL: 2,
    SHOT_MEDIUM: 3,
    SHOT_CLOSE: 4,
    SHOT_MACRO: 5,
}

TRANS_CUT = "cut"
TRANS_PUSH_IN = "push_in"
TRANS_PULL_OUT = "pull_out"
TRANS_COUNTER = "counter"
TRANS_FADE = "fade"

TRANS_LABELS = {
    TRANS_CUT: "硬切",
    TRANS_PUSH_IN: "缓推",
    TRANS_PULL_OUT: "拉远",
    TRANS_COUNTER: "反打",
    TRANS_FADE: "淡入",
}


# ============================================================
# 主入口：分镜规划
# ============================================================

def plan_storyboard(
    total_segments: int,
    emotion_curve: Optional[EmotionCurve] = None,
    has_multiple_pov: bool = False,
) -> List[Tuple[str, str]]:
    """为每段分配 (shot_type, transition)。

    Args:
        total_segments: 总段数
        emotion_curve: 情绪曲线（用于判断哪段是高潮）
        has_multiple_pov: 是否有多 POV（影响反打频率）

    Returns:
        List[(shot_type, transition)]：每段的景别 + 与前段的过渡方式
        第一段的 transition 是 "fade"（开篇）
    """
    if total_segments <= 0:
        return []

    shots: List[str] = []
    transitions: List[str] = []

    for i in range(total_segments):
        progress = (i + 1) / total_segments

        # 景别分配（基于位置 + 情绪能量）
        shot = _allocate_shot(i, total_segments, progress, emotion_curve)
        shots.append(shot)

        # 运镜（基于与前一段的景别差）
        if i == 0:
            transitions.append(TRANS_FADE)  # 开篇淡入
        else:
            trans = _allocate_transition(
                shots[i - 1], shots[i],
                has_multiple_pov=has_multiple_pov,
                is_high_emotion=_is_high_emotion(emotion_curve, progress),
            )
            transitions.append(trans)

    logger.info(
        f"[Storyboard] 分镜完成：{total_segments} 段 → "
        + " → ".join(f"{SHOT_LABELS[s]}({TRANS_LABELS[t]})" for s, t in zip(shots, transitions))
    )
    return list(zip(shots, transitions))


def _allocate_shot(
    index: int,
    total: int,
    progress: float,
    emotion_curve: Optional[EmotionCurve],
) -> str:
    """分配单段景别。"""
    # 首段：远景（建立世界）
    if index == 0:
        return SHOT_WIDE

    # 末段（高潮）：特写
    if index == total - 1:
        # 如果情绪曲线高潮能量 >= 9，用 macro；否则用 close
        if emotion_curve and emotion_curve.samples:
            climax_sample = max(emotion_curve.samples, key=lambda s: s.energy)
            if climax_sample.energy >= 9:
                return SHOT_MACRO
        return SHOT_CLOSE

    # 倒数第二段：近景（情绪累积）
    if index == total - 2:
        return SHOT_CLOSE

    # 第二段：全景（引入群体）
    if index == 1:
        return SHOT_FULL

    # 中段：根据情绪曲线交替 medium/close
    cur_energy = _energy_at(emotion_curve, progress)
    if cur_energy >= 7:
        return SHOT_CLOSE
    elif cur_energy >= 5:
        return SHOT_MEDIUM
    else:
        return SHOT_MEDIUM


def _allocate_transition(
    prev_shot: str,
    cur_shot: str,
    has_multiple_pov: bool = False,
    is_high_emotion: bool = False,
) -> str:
    """分配段间运镜。"""
    prev_dist = SHOT_DISTANCE.get(prev_shot, 3)
    cur_dist = SHOT_DISTANCE.get(cur_shot, 3)
    diff = cur_dist - prev_dist

    # 景别差 >= 2 → 大转换
    if diff >= 2:
        # 推近（远景→近景）
        return TRANS_PUSH_IN
    if diff <= -2:
        # 拉远（近景→远景）
        return TRANS_PULL_OUT

    # 景别差小 → 看是否反打（多 POV 场景）
    if has_multiple_pov and diff == 0 and is_high_emotion:
        return TRANS_COUNTER

    # 同景别但高情绪 → 硬切（节奏快）
    if is_high_emotion:
        return TRANS_CUT

    # 默认硬切
    return TRANS_CUT


def _energy_at(curve: Optional[EmotionCurve], progress: float) -> int:
    """取情绪曲线在 progress 处的能量。"""
    if not curve or not curve.samples:
        return 5
    sample = curve.sample_at(progress)
    return sample.energy


def _is_high_emotion(curve: Optional[EmotionCurve], progress: float) -> bool:
    """判断 progress 处是否高情绪（能量 >= 7）。"""
    return _energy_at(curve, progress) >= 7


# ============================================================
# Prompt 注入用：景别约束文本
# ============================================================

SHOT_CONSTRAINT_TEMPLATES = {
    SHOT_WIDE: (
        "【远景】重氛围轻对话，禁用人物大段对白。描写环境、空间、光影、人群轮廓。"
        "人物只是远景中的色块，不要给具体面孔特写。"
    ),
    SHOT_FULL: (
        "【全景】群体描写，可写多个人物的位置和姿态，但每个个体只用一两笔带过。"
        "环境仍是主体。可包含简短群体对话。"
    ),
    SHOT_MEDIUM: (
        "【中景】人物互动为主，环境作背景。可写对话、动作、表情。"
        "这是叙事的主力景别，节奏自然。"
    ),
    SHOT_CLOSE: (
        "【近景】聚焦单一人物的动作细节、心理活动、微表情。"
        "对话要少而精，重在内心。环境虚化。"
    ),
    SHOT_MACRO: (
        "【特写】放大单一细节（一只手、一个眼神、一个物件）。"
        "情绪密度最高，几乎不要对话，全是感官与象征。"
    ),
}

TRANSITION_HINT_TEMPLATES = {
    TRANS_CUT: "【硬切】直接切换，不加过渡，靠读者脑补。节奏快。",
    TRANS_PUSH_IN: "【缓推】从前一段的远景/全景，逐渐推到本段的近景。开头一两句仍带前段的环境感，然后聚焦。",
    TRANS_PULL_OUT: "【拉远】从前一段的近景，拉到本段的远景/全景。开头一句可带前段人物的状态，然后扩大视野。",
    TRANS_COUNTER: "【反打】视角跳切到另一对象（如从主角切到观察者）。开头点明新视角的在场，制造张力。",
    TRANS_FADE: "【淡入】开篇，慢慢建立场景。从环境描写开始，逐渐引入人物。",
}


def get_shot_constraint(shot_type: str) -> str:
    """获取景别的 prompt 约束文本。"""
    return SHOT_CONSTRAINT_TEMPLATES.get(shot_type, SHOT_CONSTRAINT_TEMPLATES[SHOT_MEDIUM])


def get_transition_hint(transition: str) -> str:
    """获取运镜的 prompt 提示文本。"""
    return TRANSITION_HINT_TEMPLATES.get(transition, TRANSITION_HINT_TEMPLATES[TRANS_CUT])

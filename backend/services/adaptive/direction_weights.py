# Velluma - NLE-ADF 3.0 方向权重算法
# AGPL-3.0
"""
卡片舱的方向偏好引擎——纯算法，零 LLM，零 DB 写。

5 个固定叙事方向，每个有 0-1 权重（和归一化为 1.0），代表"此刻最该递哪个方向的碎片"。
权重由四种力驱动：

- 推动力：未完成的叙事任务往上推（必达未达→主线+，伏笔未埋→伏笔+）
- 读者力：高张力读者期待推对应方向（张力≥8 的"该收了"期待→类型映射方向+，封顶一票）
- 惯性力：作者刚写了什么就抑制什么（环境写多了→环境-，对话正热→关系+）
- 节拍力：沉淀段落=新节拍部分重置；久不推主线→主线+

防剧透：意图数据（必达/伏笔/弧线）只进本算法算权重，绝不直接进 LLM prompt。
LLM 只看到"主线 40%"这种抽象数字，看不到"必须发现日志"这种剧情细节。
"""
from __future__ import annotations

from typing import Dict, List

# ============================================================
# 5 个固定方向
# ============================================================

DIRECTIONS: List[str] = ["主线", "伏笔", "刻画", "环境", "关系"]

# 默认基线权重（推动力为零时的均匀分布偏向）
_BASELINE: Dict[str, float] = {
    "主线": 0.30,
    "伏笔": 0.20,
    "刻画": 0.20,
    "环境": 0.18,
    "关系": 0.12,
}

# 读者力：期待类型 → 叙事方向映射（读者在等哪类兑现，就把对应方向往上推）
# 注意纪律：只有 type/tension 数字进本算法，期待文本绝不进（防剧透，与意图数据同理）
_EXPECTATION_DIRECTION_MAP: Dict[str, str] = {
    "power_reveal": "主线",
    "growth": "主线",
    "revenge": "主线",
    "mystery": "伏笔",
    "romance": "关系",
}

# ============================================================
# 文体方向标记词（惯性力检测用）
# ============================================================

# 环境描写标记词——段落里这些词密集说明作者在铺环境
_ENV_MARKERS = (
    "风", "光", "影", "雾", "尘", "气味", "声音", "寂静", "远处", "天空",
    "海", "墙", "地", "锈", "潮", "温", "冷", "热", "灰", "暗",
)

# 动作动词——密集说明作者在写人物行为（角色刻画方向）
_ACTION_MARKERS = (
    "走", "跑", "抓", "推", "拉", "敲", "看", "听", "转身", "蹲下",
    "伸手", "攥", "摸", "踢", "挡", "握", "按", "拧",
)


# ============================================================
# 主算法
# ============================================================

def compute(
    intent: Dict,
    soft: Dict,
    recent_text: str,
    facts_text: str,
    prev_weights: Dict[str, float],
    settled_just_now: bool,
    adopted_directions: List[str] = None,
) -> Dict[str, float]:
    """算 5 方向权重。

    Args:
        intent: 世界模型层 2 意图（ChapterIntent.to_dict()），含 must_hits/foreshadows/arc
        soft: SettingsBundle.soft_constraints()，含 must_hit_events/foreshadow_ops 文本
        recent_text: 作者当前段落尾部（≤500 字）——惯性力检测输入
        facts_text: 层 1 已沉淀事实全文——推动力"已达成"判定输入
        prev_weights: 上次的权重表（节拍力用）
        settled_just_now: 本次心跳前是否刚沉淀过段落（节拍力触发重置）
        adopted_directions: 上次被作者缝合采纳的方向列表（负反馈降权）

    Returns:
        {"主线": 0.40, "伏笔": 0.25, ...}，和归一化为 1.0
    """
    adopted_directions = adopted_directions or []
    weights: Dict[str, float] = dict(_BASELINE)

    # ---- 1. 推动力：未完成的叙事任务 ----
    must_hits = _as_str_list(intent.get("must_hits", []))
    foreshadows = _as_str_list(intent.get("foreshadows", []))

    # 必达事件里还没在已写正文出现的 → 主线推动
    unmet_main = _count_unmet(must_hits, facts_text)
    weights["主线"] += min(unmet_main * 0.30, 0.60)  # 上限 +0.60

    # 伏笔操作里还没埋的 → 伏笔推动
    unmet_foreshadow = _count_unmet(foreshadows, facts_text)
    weights["伏笔"] += min(unmet_foreshadow * 0.25, 0.50)

    # 弧线存在但 must_hits 空 → 主线仍有方向感
    if intent.get("arc") and not must_hits:
        weights["主线"] += 0.10

    # ---- 1.5 读者力：高张力期待（"该收了"区间）推对应方向 ----
    # 每条张力 ≥8 的活跃期待给其映射方向 +0.15，总加成封顶 +0.30——
    # 读者视角只是方向信号里的一票，永不主导（作者主权）
    reader_boost = 0.0
    for e in soft.get("reader_expectations") or []:
        if not isinstance(e, dict):
            continue
        direction = _EXPECTATION_DIRECTION_MAP.get(e.get("type") or "")
        if direction and (e.get("tension") or 0) >= 8 and reader_boost < 0.30:
            weights[direction] += 0.15
            reader_boost += 0.15

    # ---- 2. 惯性力：作者刚写了什么就抑制什么 ----
    if recent_text:
        recent = recent_text.strip()
        # 环境描写密度（标记词命中数 / 文本长度）
        env_hits = sum(recent.count(w) for w in _ENV_MARKERS)
        env_density = env_hits / max(len(recent), 1)
        if env_density > 0.08:  # 环境词占比超 8% → 环境写够了
            weights["环境"] *= 0.3

        # 对话密度（引号/书名号密度）→ 关系推动
        dialogue_marks = recent.count('"') + recent.count('"') + recent.count('「') + recent.count('」')
        if dialogue_marks >= 2:
            weights["关系"] *= 1.6

        # 动作密度 → 刻画抑制（刚刻画过）
        action_hits = sum(recent.count(w) for w in _ACTION_MARKERS)
        action_density = action_hits / max(len(recent), 1)
        if action_density > 0.06:
            weights["刻画"] *= 0.5

    # ---- 3. 节拍力 ----
    # 刚沉淀 → 刻画/环境部分重置回基线（新段新节拍）
    if settled_just_now:
        weights["刻画"] = max(weights["刻画"], _BASELINE["刻画"])
        weights["环境"] = max(weights["环境"], _BASELINE["环境"])

    # 久不推主线（上轮主线权重低 + 已写很多）→ 主线回推
    prev_main = prev_weights.get("主线", 0)
    if prev_main < 0.25 and len(facts_text) > 600:
        weights["主线"] += 0.15

    # ---- 4. 负反馈：被采纳的方向降权 ----
    for d in adopted_directions:
        if d in weights:
            weights[d] *= 0.4

    # ---- 5. 归一化（和为 1.0）----
    return _normalize(weights)


# ============================================================
# 辅助
# ============================================================

def _as_str_list(val) -> List[str]:
    """把各种形态（list[str] / list[dict] / str）统一成 list[str]。"""
    if isinstance(val, str):
        return [s.strip() for s in val.split("；") if s.strip()] if val else []
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, str):
                if item.strip():
                    out.append(item.strip())
            elif isinstance(item, dict):
                # must_hit 可能是 {"event": "..."} 结构
                ev = item.get("event") or item.get("note") or ""
                if ev.strip():
                    out.append(ev.strip())
        return out
    return []


def _count_unmet(items: List[str], text: str) -> int:
    """统计 items 里有多少还没在 text 中出现（关键词交集判定，宽松）。

    匹配规则：把 item 拆成 2-3 字的关键词片段，只要 text 命中其中任一关键词，
    就算"已达成"（宁可漏判未达，也不误判已达——避免主线权重虚高）。
    """
    if not text:
        return len(items)
    count = 0
    for item in items:
        if _is_met(item, text):
            continue
        count += 1
    return count


def _is_met(item: str, text: str) -> bool:
    """item 是否已在 text 中达成（关键词命中即算）。"""
    item = item.strip()
    if not item:
        return True
    # 整串直接命中
    if item in text:
        return True
    # 拆成 2-3 字关键词片段（滑动窗口），任一命中即算达成
    # 取 item 中间 60% 的片段做关键词（去掉首尾噪声）
    keywords = _extract_keywords(item)
    for kw in keywords:
        if kw in text:
            return True
    return False


def _extract_keywords(text: str) -> List[str]:
    """从文本提取 2-3 字关键词片段（用于模糊匹配）。

    策略：滑动 3 字窗口，过滤掉纯标点/数字片段。
    """
    kws = []
    # 3 字滑动窗口
    for i in range(len(text) - 2):
        frag = text[i:i+3]
        # 过滤含标点/数字的片段
        if any(c in "。，、；：！？""''「」（）《》0123456789 " for c in frag):
            continue
        kws.append(frag)
    # 去重，取最多 4 个关键词（够判断）
    seen = []
    for k in kws:
        if k not in seen:
            seen.append(k)
    return seen[:4]


def _normalize(weights: Dict[str, float]) -> Dict[str, float]:
    """归一化到和为 1.0，保底防全零。"""
    total = sum(weights.values())
    if total <= 0:
        # 全零兜底：回退基线
        return dict(_BASELINE)
    return {k: round(v / total, 3) for k, v in weights.items()}

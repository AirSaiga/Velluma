# Velluma - 世界页空间换算（D4 比例尺标定）
# AGPL-3.0
"""
CRS.Simple 内部坐标 → 现实距离的纯函数换算层（docs/map-scale-spatial.md §4）。

设计约束（S1-S3）：
- 未标定（map_scale 为 None/无 refs）一切函数静默降级（返回 None / 原样）——
  距离功能缺席不影响任何既有行为（prompt 零变化）。
- 内部基准 = 步行日（浮点）；展示永远说作者的话（「约 2 天步程」）。
- 直线 × detour_factor 的**估算**，一切输出天然带「约」——诚实给数。
- 前端 engine/distance.ts 与本文件同构（改口径两侧同步 + 各配单测对拍）。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# 1 步行日的缺省现实换算（仅用于空白舆图预填建议与展示参考；作者可改）
KM_PER_DAY_FOOT = 30.0

_MODE_SPEED_DEFAULTS = {"walk": 1.0, "horse": 2.5, "boat": 2.0, "caravan": 0.7}


def _refs(scale: Optional[Dict]) -> List[Dict]:
    if not isinstance(scale, dict):
        return []
    refs = scale.get("refs") or []
    return [r for r in refs if isinstance(r, dict) and _ref_px_per_day(r) is not None]


def _ref_px_per_day(ref: Dict) -> Optional[float]:
    """单条参考线：px 长度 ÷ 步行日数 → px/天。无 days_foot 或零长度线 → None。"""
    days = ref.get("days_foot")
    try:
        days = float(days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    try:
        length = math.hypot(
            float(ref.get("bx", 0)) - float(ref.get("ax", 0)),
            float(ref.get("by", 0)) - float(ref.get("ay", 0)),
        )
    except (TypeError, ValueError):
        return None
    if length <= 0:
        return None
    return length / days


def px_per_day(scale: Optional[Dict]) -> Optional[float]:
    """标定锚：全部参考线 px/天 的均值。未标定 → None。"""
    vals = [_ref_px_per_day(r) for r in _refs(scale)]
    vals = [v for v in vals if v is not None and v > 0]
    if not vals:
        return None
    return sum(vals) / len(vals)


def distance_days(
    a: Tuple[float, float],
    b: Tuple[float, float],
    scale: Optional[Dict],
) -> Optional[float]:
    """两点内部坐标 → 步行日（含 detour_factor 绕行系数）。未标定 → None。"""
    ppd = px_per_day(scale)
    if ppd is None:
        return None
    px = math.hypot(b[0] - a[0], b[1] - a[1])
    detour = 1.2
    try:
        d = float((scale or {}).get("detour_factor") or 1.2)
        if 1.0 <= d <= 3.0:
            detour = d
    except (TypeError, ValueError):
        pass
    return (px / ppd) * detour


def format_distance(days: Optional[float], mode: str = "walk", scale: Optional[Dict] = None) -> str:
    """步行日 → 作者的话。None → 空串（调用方自行缺席）。所有输出天然带「约」。

    mode 走 horse/boat/caravan 时按标定的 modes 速率折算（缺省 2.5/2.0/0.7）。
    """
    if days is None or days < 0:
        return ""
    speed = _MODE_SPEED_DEFAULTS.get(mode, 1.0)
    if scale:
        try:
            override = float((scale.get("modes") or {}).get(mode))
            if override > 0:
                speed = override
        except (TypeError, ValueError):
            pass
    v = days / speed
    unit = "步程" if mode == "walk" else "行程"
    if v < 0.25:
        return "近在咫尺"
    if v < 1.0:
        return f"约半日{unit}"
    if v < 10.0:
        text = f"{v:.1f}".rstrip("0").rstrip(".")
        return f"约 {text} 天{unit}"
    return f"约 {int(v)} 天{unit}"


def format_distance_with_scale(
    a: Tuple[float, float],
    b: Tuple[float, float],
    scale: Optional[Dict],
    mode: str = "walk",
) -> str:
    """组合便捷：坐标 + 标定 → 作者的话（未标定 → 空串）。"""
    return format_distance(distance_days(a, b, scale), mode, scale)


def blank_atlas_suggested_scale(map_width_px: float) -> Dict:
    """空白舆图隐含地球尺度（设计稿 §2.2）：图宽 = 赤道周长 → 预填建议标定。

    横贯线（图宽）= 40075km ÷ 30km/天 ≈ 1336 步行日。
    """
    days = 40075.0 / KM_PER_DAY_FOOT
    return {
        "refs": [{
            "ax": 0.0, "ay": 0.0,
            "bx": float(map_width_px), "by": 0.0,
            "days_foot": round(days, 1),
            "label": "图宽=赤道一圈（空白舆图预填）",
        }],
        "detour_factor": 1.2,
        "modes": dict(_MODE_SPEED_DEFAULTS),
    }


def encounter_band(days: Optional[float]) -> Optional[str]:
    """相遇距离分档（D4-2）：同地 / 半日内可达 / 1-3 天 / 更远。

    返回 None = 距离不可用（未标定）或同地（调用方已有同地逻辑）。
    """
    if days is None:
        return None
    if days <= 0.05:
        return None  # 同地：沿用既有 W5-lite 逻辑
    if days < 0.5:
        return "半日内可达"
    if days <= 3.0:
        return "1-3 天路程"
    return "更远"


def build_spatial_brief(
    presence: List[Dict[str, Any]],
    scene: Optional[Dict[str, Any]],
    scale: Optional[Dict],
) -> str:
    """D4-3：生成上下文的空间常识块（≤3 行，双门槛静默降级为空串）。

    presence: [{name, x, y, ...}]（推演态实体含坐标）；scene: 场景钉/脚下
    {name, x, y}。同地省略距离；只列与场景/首位的距离。
    """
    ppd = px_per_day(scale)
    if ppd is None or not presence:
        return ""
    anchored = [(p["name"], p.get("x"), p.get("y")) for p in presence if p.get("x") is not None]
    if not anchored:
        return ""
    lines: List[str] = []
    origin = None
    if scene and scene.get("x") is not None:
        origin = (scene.get("name") or "场景地", scene["x"], scene["y"])
        lines.append(f"本章场景：{origin[0]}")
    same_place: List[str] = []
    for name, x, y in anchored:
        if origin and math.hypot(x - origin[1], y - origin[2]) < 1e-6:
            same_place.append(name)
    if same_place:
        lines.append(f"同处{origin[0] if origin else ''}：{'、'.join(same_place[:4])}")
    ref = origin or ("，".join(n for n, _, _ in anchored[:1]), anchored[0][1], anchored[0][2])
    far: List[str] = []
    for name, x, y in anchored:
        if name in same_place:
            continue
        d = distance_days((x, y), (ref[1], ref[2]), scale)
        if d is not None and d >= 0.5:
            far.append(f"{name}距此{format_distance(d)}")
    if far:
        lines.append("；".join(far[:3]))
    return "\n".join(lines[:3])

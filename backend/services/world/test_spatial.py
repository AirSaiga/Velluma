# Velluma - D4 空间换算单测
# AGPL-3.0
"""spatial.py 纯函数对拍（docs/map-scale-spatial.md §6 D4-1 出口标准）。"""

from backend.services.world.spatial import (
    px_per_day,
    distance_days,
    format_distance,
    format_distance_with_scale,
    encounter_band,
    build_spatial_brief,
    blank_atlas_suggested_scale,
)


SCALE = {
    "refs": [{"ax": 0, "ay": 0, "bx": 100, "by": 0, "days_foot": 1.0, "label": "骑马一天"}],
    "detour_factor": 1.2,
    "modes": {"walk": 1.0, "horse": 2.5},
}


def test_uncalibrated_silent_degradation():
    """S1：未标定 → 一切 None/空串（prompt 零变化的地基）。"""
    assert px_per_day(None) is None
    assert px_per_day({}) is None
    assert px_per_day({"refs": []}) is None
    assert distance_days((0, 0), (100, 0), None) is None
    assert format_distance_with_scale((0, 0), (100, 0), None) == ""
    assert build_spatial_brief([{"name": "甲", "x": 1, "y": 1}], None, None) == ""
    assert encounter_band(None) is None


def test_calibration_math():
    """100px = 1 步行日 → 200px 直线 × 1.2 绕行 = 2.4 天。"""
    assert abs(px_per_day(SCALE) - 100.0) < 1e-9
    assert abs(distance_days((0, 0), (200, 0), SCALE) - 2.4) < 1e-9


def test_multi_ref_average():
    s = {"refs": [
        {"ax": 0, "ay": 0, "bx": 100, "by": 0, "days_foot": 1.0},   # 100 px/天
        {"ax": 0, "ay": 0, "bx": 100, "by": 0, "days_foot": 2.0},   # 50 px/天
    ]}
    assert abs(px_per_day(s) - 75.0) < 1e-9


def test_format_distance_author_language():
    assert format_distance(None) == ""
    assert format_distance(0.1) == "近在咫尺"
    assert format_distance(0.6) == "约半日步程"
    assert format_distance(2.0) == "约 2 天步程"
    assert format_distance(2.0, "horse", SCALE) == "约半日行程"   # 2÷2.5=0.8 落半日档
    assert format_distance(3.0, "horse", SCALE) == "约 1.2 天行程"
    assert format_distance(25.0) == "约 25 天步程"
    assert format_distance_with_scale((0, 0), (100, 0), SCALE) == "约 1.2 天步程"


def test_encounter_band():
    assert encounter_band(None) is None
    assert encounter_band(0.01) is None      # 同地沿用 W5-lite
    assert encounter_band(0.3) == "半日内可达"
    assert encounter_band(2.0) == "1-3 天路程"
    assert encounter_band(9.0) == "更远"


def test_blank_atlas_suggestion():
    s = blank_atlas_suggested_scale(2000)
    ppd = px_per_day(s)
    assert ppd is not None
    # 图宽 2000px ≈ 1336 天 → 全图穿越约 1603 天（含 1.2 绕行）
    assert abs(distance_days((0, 0), (2000, 0), s) - 2000 / ppd * 1.2) < 1e-6
    assert 1300 < 2000 / ppd < 1400


def test_spatial_brief_lines():
    presence = [
        {"name": "甲", "x": 0, "y": 0},
        {"name": "乙", "x": 0, "y": 0},
        {"name": "丙", "x": 1000, "y": 0},
    ]
    scene = {"name": "北岸要塞", "x": 0, "y": 0}
    brief = build_spatial_brief(presence, scene, SCALE)
    assert "本章场景：北岸要塞" in brief
    assert "同处北岸要塞：甲、乙" in brief
    assert "丙距此" in brief and "天步程" in brief
    lines = [l for l in brief.split("\n") if l.strip()]
    assert len(lines) <= 3

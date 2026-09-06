# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - NLE-ADF 接缝裁剪与陈词嗅探单测
"""
2026-08-27 感知逻辑诊断轮（导师裁决）的纯函数契约锁。

背景：挂件菜单混装节拍两侧素材——「工头拍肩」=节拍事件本身、「弯腰捡书」=
节拍之后，作者连吸两枚一次 Space 就把自己的转折点写穿了。处方：切断供给
（beat/after 不进挂件 prompt）+ 陈词嗅探（菜单不带生成层库存词）——对服从度
有限的模型，两者都不设 prompt 服从率问题。

锁定：
- _prebeat_projections：stage now/approach 保留；显式 beat/after 丢弃；
  缺标/乱标时首幅宽容视为 now、其余保守丢弃；__dock__/__canon_watch__ 与
  非 dict 项跳过
- _has_camera_stock：镜头陈词（目光失焦/轮廓模糊族）命中，正常画面放行
"""
from backend.services.adaptive.components.dock_generator import (
    _has_camera_stock,
    _prebeat_projections,
)


def _proj(stage, event="画面"):
    beats = [{"event": event, "anchors": [], "emotion": "静"}]
    if stage is not None:
        beats[0]["stage"] = stage
    return {"possible_beats": beats, "confidence": 0.5, "signature": "s"}


class TestPrebeatFilter:
    def test_now_and_approach_kept_beat_after_dropped(self):
        projs = [_proj("now"), _proj("approach"), _proj("beat"), _proj("after")]
        kept = _prebeat_projections(projs)
        assert len(kept) == 2
        assert kept[0]["possible_beats"][0]["stage"] == "now"
        assert kept[1]["possible_beats"][0]["stage"] == "approach"

    def test_explicit_beat_first_not_promoted(self):
        """显式 beat 标注可信：即使排在首位也丢弃，不占「首幅宽容」位。"""
        kept = _prebeat_projections([_proj("beat", "节拍"), _proj("now", "此刻")])
        assert len(kept) == 1
        assert kept[0]["possible_beats"][0]["event"] == "此刻"

    def test_missing_stage_first_kept_rest_dropped(self):
        """缺标降级：首幅宽容视为 now，其余保守视为节拍侧丢弃（宁可薄不可抢拍）。"""
        kept = _prebeat_projections([_proj(None, "一"), _proj(None, "二"), _proj(None, "三")])
        assert len(kept) == 1
        assert kept[0]["possible_beats"][0]["event"] == "一"

    def test_markers_and_non_dict_skipped(self):
        projs = [
            {"__dock__": True, "parts": []},
            {"__canon_watch__": True},
            "not-a-dict",
            _proj("beat"),
            _proj("now"),
        ]
        kept = _prebeat_projections(projs)
        assert len(kept) == 1
        assert kept[0]["possible_beats"][0]["stage"] == "now"

    def test_empty_and_none_safe(self):
        assert _prebeat_projections([]) == []
        assert _prebeat_projections(None) == []


class TestCameraStockSniff:
    def test_stock_phrases_hit(self):
        assert _has_camera_stock("林尘目光失焦地望着远处")
        assert _has_camera_stock("黄浦江的轮廓模糊在灰尘里")
        assert _has_camera_stock("他的瞳孔微微收缩")

    def test_normal_text_passes(self):
        assert not _has_camera_stock("林尘握着扫帚的手停在半空")
        assert not _has_camera_stock("他把书往口袋深处按了按")
        assert not _has_camera_stock("工头的脚步声从砖堆后面过来")

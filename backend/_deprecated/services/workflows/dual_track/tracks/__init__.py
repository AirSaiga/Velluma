"""
双轨模块 - 轨道实现。

职责：
- 提供 Track A 和 Track B 的执行器
- 封装节拍扩写和短文生成的逻辑

子模块：
- track_a.py: 节拍扩写轨 (Track A)
- track_b.py: 短文生成轨 (Track B)

使用方式：
    from backend.services.workflows.dual_track.tracks import TrackAExecutor, TrackBExecutor

    track_a = TrackAExecutor(api_key, base_url, ...)
    track_b = TrackBExecutor(api_key, base_url, ...)
"""

from backend.services.workflows.dual_track.tracks.track_a import TrackAExecutor
from backend.services.workflows.dual_track.tracks.track_b import TrackBExecutor

__all__ = [
    "TrackAExecutor",
    "TrackBExecutor",
]

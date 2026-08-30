# -*- coding: utf-8 -*-
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - AI novel writing assistant
# Copyright (C) 2026 Velluma contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""生成空白舆图底图（frontend/src/features/world/containers/blankAtlas.ts）。

====================================================================
用途
----
世界页无底图时铺的手绘风地球世界平面。海岸线/湖泊/河流/国界取自
Natural Earth 50m 矢量数据（公共领域），等距圆柱投影到 1000×500 viewBox：

    x = (wrap(lon - CENTER_LON) + 180) / 360 * 1000
    y = (90 - lat) / 180 * 500

中央经线 CENTER_LON=40°E（视觉中心落在欧亚大陆：黑海—高加索一线居中），
切线随之走 140°W 东太平洋开阔洋面；阿拉斯加/阿留申如常规太平洋中心世界图
分列两缘（跨切线的环由 path_d 的反经线断行拆成两半，各在图缘直边收口）。

因此 2:1 的 viewBox 必须对应内部坐标里 2:1 的 bounds（WorldMap.vue 的
BLANK_ATLAS_BOUNDS），否则大陆会被非均匀拉伸变形。

数据缓存（默认 data/atlas-src/，目录已 gitignore）：
    https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson
    .../ne_50m_lakes.geojson
    .../ne_50m_rivers_lake_centerlines.geojson
    .../ne_50m_admin_0_boundary_lines_land.geojson

用法：
    python scripts/make_blank_atlas.py            # 读缓存、写出 blankAtlas.ts
    python scripts/make_blank_atlas.py --tol 0.7  # 调轮廓简化容差（svg 单位）

⚠ 输出文件是生成物：手改会被下次生成覆盖；装饰层（山脉/经纬网/
南方大陆虚影/浪花）的锚点在下方 DECOR 常量里改，重跑即可。
====================================================================
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
W, H = 1000.0, 500.0

# 中央经线：40°E 让欧亚大陆（黑海—高加索一带）坐镇画面正中；切线 140°W 过东太平洋。
CENTER_LON = 40.0


# ---- 坐标与几何 -----------------------------------------------------------

def project(lon: float, lat: float) -> tuple[float, float]:
    """等距圆柱（中央经线 CENTER_LON）：wrap(lon-c) ∈ [-180,180) → x 0..1000，lat 90..-90 → y 0..500。"""
    r = (lon - CENTER_LON + 540.0) % 360.0 - 180.0
    return (r + 180.0) / 360.0 * W, (90.0 - lat) / 180.0 * H


def simplify(points: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker（迭代栈实现，避免长海岸线递归爆栈）。"""

    def seg_dist(p, a, b) -> float:
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == dy == 0:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        best_i, best_d = lo, -1.0
        for i in range(lo + 1, hi):
            d = seg_dist(points[i], points[lo], points[hi])
            if d > best_d:
                best_i, best_d = i, d
        if best_d > tol:
            keep[best_i] = True
            stack.append((lo, best_i))
            stack.append((best_i, hi))
    return [p for p, k in zip(points, keep) if k]


def ring_metrics(pts: list[tuple[float, float]]) -> tuple[float, float, float]:
    """返回 (shoelace 有符号面积, bbox 宽, bbox 高)——按投影后坐标。"""
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s += x1 * y2 - x2 * y1
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return abs(s) / 2.0, max(xs) - min(xs), max(ys) - min(ys)


def fmt(v: float) -> str:
    """1 位小数、去尾零——路径体积第一道闸。"""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def path_d(pts: list[tuple[float, float]], close: bool) -> list[str]:
    """坐标对 → 'M x,y x,y x,y …'（M 后隐式 L）。跨 180° 的跳变断开成新子路径。"""
    segments: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    px: float | None = None
    for x, y in pts:
        if px is not None and abs(x - px) > 300:  # 反经线跳变
            segments.append(cur)
            cur = []
        cur.append((x, y))
        px = x
    if cur:
        segments.append(cur)
    out: list[str] = []
    for seg in segments:
        if len(seg) < 2:
            continue
        d = "M" + " ".join(f"{fmt(x)},{fmt(y)}" for x, y in seg)
        out.append(d + "Z" if close else d)
    return out


def iter_rings(geom: dict):
    if geom["type"] == "Polygon":
        yield from geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield from poly


def iter_lines(geom: dict):
    if geom["type"] == "LineString":
        yield geom["coordinates"]
    elif geom["type"] == "MultiLineString":
        yield from geom["coordinates"]


# ---- 数据层 ---------------------------------------------------------------

def load(name: str, data_dir: Path) -> dict:
    with open(data_dir / f"ne_50m_{name}.geojson", encoding="utf-8") as f:
        return json.load(f)


def build_land(gj: dict, tol: float) -> list[str]:
    """海岸线：全部陆地环合并成一条 path（Antarctica 摘除——南缘走手绘虚影）。"""
    subs: list[str] = []
    for ft in gj["features"]:
        for ring in iter_rings(ft["geometry"]):
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            if sum(lats) / len(lats) < -63.0:  # 南极大陆及其陆缘
                continue
            pts = [project(lo, la) for lo, la in ring]
            area, bw, bh = ring_metrics(pts)
            if bw < 2.2 and bh < 2.2 or area < 1.4:  # 不可见碎屑
                continue
            pts = simplify(pts, tol)
            subs.extend(path_d(pts, close=True))
    return subs


def build_lakes(gj: dict, tol: float) -> list[str]:
    """内陆水体轮廓（里海/五大湖/贝加尔……），只留看得见的。"""
    subs: list[str] = []
    for ft in gj["features"]:
        p = ft["properties"]
        if (p.get("scalerank") or 0) > 1:  # 小湖群留给地名层去写
            continue
        for ring in iter_rings(ft["geometry"]):
            pts = [project(lo, la) for lo, la in ring]
            area, bw, bh = ring_metrics(pts)
            if area < 1.6 or bw < 2.4:
                continue
            pts = simplify(pts, tol)
            subs.extend(path_d(pts, close=True))
    return subs


def build_rivers(gj: dict, tol: float) -> list[str]:
    """大河细线：scalerank ≤ 3 的干流（尼罗河/亚马逊/长江这一级 + 次级大河）。"""
    subs: list[str] = []
    for ft in gj["features"]:
        p = ft["properties"]
        if (p.get("scalerank") or 9) > 3 or p.get("featurecla") != "River":
            continue
        for line in iter_lines(ft["geometry"]):
            pts = [project(lo, la) for lo, la in line]
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            if math.hypot(max(xs) - min(xs), max(ys) - min(ys)) < 14:  # 短支流
                continue
            pts = simplify(pts, tol)
            subs.extend(path_d(pts, close=False))
    return subs


def build_borders(gj: dict, tol: float) -> list[str]:
    """陆上国界（点状虚线样式在 TS 侧）。"""
    subs: list[str] = []
    for ft in gj["features"]:
        for line in iter_lines(ft["geometry"]):
            pts = [project(lo, la) for lo, la in line]
            xs = [q[0] for q in pts]
            ys = [q[1] for q in pts]
            if math.hypot(max(xs) - min(xs), max(ys) - min(ys)) < 12:
                continue
            pts = simplify(pts, tol)
            subs.extend(path_d(pts, close=False))
    return subs


# ---- 装饰层（锚点按经纬度给，换投影不用重排） ------------------------------

# 山脉：(lon, lat, 尺寸)。尺寸 = 半峰底宽（svg 单位），峰高约 1.7×。
MOUNTAINS: list[tuple[float, float, float]] = [
    # 北美
    (-118.5, 37.5, 2.6), (-121.8, 45.2, 2.4),          # 内华达山脉 / 喀斯喀特
    (-114.0, 50.5, 3.0), (-107.0, 41.0, 3.2), (-106.0, 33.5, 2.8),  # 落基山
    (-79.5, 38.5, 2.0), (-81.5, 34.0, 1.9),            # 阿巴拉契亚
    (-105.0, 25.0, 2.4),                               # 马德雷山脉
    # 南美（安第斯山系一串）
    (-70.5, 8.0, 3.0), (-75.5, 3.0, 3.2), (-68.5, -14.0, 3.2),
    (-68.5, -26.0, 3.0), (-70.5, -40.0, 2.8), (-72.0, -49.5, 2.6),
    # 欧洲中东
    (-5.5, 31.5, 2.4),                                  # 阿特拉斯
    (1.2, 42.7, 2.0), (9.5, 46.3, 2.8), (24.5, 47.5, 2.2),  # 比利牛斯/阿尔卑斯/喀尔巴阡
    (33.0, 37.3, 2.2),                                  # 托罗斯山脉
    (15.0, 64.5, 2.4),                                  # 斯堪的纳维亚山脉
    (58.5, 60.5, 2.4), (59.5, 53.0, 2.0),               # 乌拉尔
    (44.5, 42.6, 2.6), (52.0, 30.5, 2.4), (52.5, 36.3, 2.2),  # 高加索/扎格罗斯/厄尔布尔士
    # 亚洲
    (78.0, 42.3, 2.6), (88.0, 49.3, 2.6), (93.0, 52.5, 2.2),   # 天山/阿尔泰/萨彦岭
    (85.0, 28.3, 3.6), (76.0, 35.8, 3.0), (70.5, 35.5, 2.4), (73.5, 38.5, 2.6),  # 喜马拉雅/喀喇昆仑/兴都库什/帕米尔
    (128.0, 65.5, 2.4), (107.5, 33.5, 2.0),                     # 上扬斯克山脉 / 秦岭
    (137.8, 36.2, 2.2),                                         # 日本阿尔卑斯
    # 非洲 / 大洋洲
    (38.5, 8.5, 2.4), (28.8, -29.5, 2.4),               # 埃塞俄比亚高原 / 龙山
    (149.8, -31.5, 2.4), (146.5, -20.5, 2.2),           # 大分水岭
    (140.5, -5.5, 2.2), (169.5, -44.0, 2.2),            # 新几内亚高地 / 南阿尔卑斯
]

# 浪花：(lon, lat)——散在大洋空处。
WAVES: list[tuple[float, float]] = [
    (-152.0, 8.0), (-38.0, -16.0), (78.0, -20.0), (-122.0, -40.0), (-48.0, 34.0),
]


def mountains_d() -> str:
    """每锚点两笔小三角（主峰 + 错位小峰），古图山脉记号。"""
    parts: list[str] = []
    for lon, lat, s in MOUNTAINS:
        x, y = project(lon, lat)
        parts.append(
            f"M{fmt(x)},{fmt(y)} l{fmt(s)},{fmt(-1.7 * s)} l{fmt(s)},{fmt(1.7 * s)}"
            f" M{fmt(x + 1.9 * s)},{fmt(y + 0.4 * s)} l{fmt(0.8 * s)},{fmt(-1.4 * s)} l{fmt(0.8 * s)},{fmt(1.4 * s)}"
        )
    return " ".join(parts)


def graticule_d() -> tuple[str, str]:
    """经纬网 30° 步（子午线锚定中央经线，±180 切线处即图缘不画）；赤道一道稍重的连续线（古图惯例）。"""
    mer_lons = sorted((CENTER_LON + 30 * k + 180.0) % 360.0 - 180.0 for k in range(-5, 6))
    mer = " ".join(f"M{fmt(project(lon, 0.0)[0])},0V{fmt(H)}" for lon in mer_lons)
    par = " ".join(
        f"M0,{fmt((90 - lat) / 180 * H)}H{fmt(W)}" for lat in (60, 30, -30, -60)
    )
    equator = f"M0,{fmt(H / 2)}H{fmt(W)}"
    return mer + " " + par, equator


def terra_australis_d() -> str:
    """未知的南方大陆：南缘一道虚影弧线（Terra Australis Incognita）。"""
    return "M60,468 C250,452 420,462 560,456 C700,450 840,460 940,454"


def waves_d() -> str:
    parts = []
    for lon, lat in WAVES:
        x, y = project(lon, lat)
        parts.append(f"M{fmt(x)},{fmt(y)} q5,-5 10,0")
    return " ".join(parts)


# ---- 组装 -----------------------------------------------------------------

HEADER = """/* Velluma - AI novel writing assistant
 * Copyright (C) 2026 Velluma contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published
 * by the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

/**
 * ⚠ 生成物——由 scripts/make_blank_atlas.py 产出，勿手改（重跑即覆盖）。
 * 空白舆图默认底图：手绘风地球世界平面（Natural Earth 50m 海岸线/湖泊/
 * 河流/国界，等距圆柱投影到 1000×500）。2:1 的 viewBox 必须搭配 2:1 的
 * BLANK_ATLAS_BOUNDS（WorldMap.vue），否则大陆纵向变形。
 */
"""

FOOTER = """
/** 空白舆图 SVG 的 viewBox（与生成脚本的 1000×500 投影面一致） */
export const BLANK_ATLAS_VIEWBOX = '0 0 1000 500'
"""


def emit(subs: list[str], per_line: int = 4) -> list[str]:
    """子路径若干条并一行，避免超长行。"""
    return [" ".join(subs[i : i + per_line]) for i in range(0, len(subs), per_line)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", default=str(ROOT / "data" / "atlas-src"))
    ap.add_argument("--out", default=str(ROOT / "frontend" / "src" / "features" / "world" / "containers" / "blankAtlas.ts"))
    ap.add_argument("--tol", type=float, default=0.42, help="海岸线简化容差（svg 单位）")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    for name in ("land", "lakes", "rivers", "borders"):
        if not (data_dir / f"ne_50m_{name}.geojson").exists():
            raise SystemExit(f"缺数据：{data_dir}/ne_50m_{name}.geojson（下载地址见脚本头注释）")

    land = emit(build_land(load("land", data_dir), args.tol))
    lakes = emit(build_lakes(load("lakes", data_dir), args.tol))
    rivers = emit(build_rivers(load("rivers", data_dir), args.tol))
    borders = emit(build_borders(load("borders", data_dir), args.tol), per_line=3)
    grat, equator = graticule_d()

    lines = [
        HEADER,
        "export const BLANK_ATLAS_INNER = `",
        "  <!-- 经纬网（30° 步淡虚线；赤道一道连续稍重） -->",
        f'  <path d="{grat}" stroke="rgba(110,85,45,.12)" stroke-width="1" fill="none" stroke-dasharray="4 6"/>',
        f'  <path d="{equator}" stroke="rgba(110,85,45,.17)" stroke-width="1" fill="none"/>',
        "  <!-- 海岸线（Natural Earth 50m，wm-ink-soft 走细毛边） -->",
        '  <g filter="url(#wm-ink-soft)" stroke="rgba(110,85,45,.5)" stroke-width="1.25" stroke-linejoin="round" fill="rgba(110,85,45,.055)">',
        *[f'    <path d="{d}"/>' for d in land],
        "  </g>",
        "  <!-- 内陆水体（里海/五大湖/贝加尔……） -->",
        '  <g filter="url(#wm-ink-soft)" stroke="rgba(110,85,45,.42)" stroke-width="0.9" fill="none">',
        *[f'    <path d="{d}"/>' for d in lakes],
        "  </g>",
        "  <!-- 大河细流（干流级） -->",
        '  <g stroke="rgba(110,85,45,.32)" stroke-width="0.85" fill="none" stroke-linecap="round">',
        *[f'    <path d="{d}"/>' for d in rivers],
        "  </g>",
        "  <!-- 山脉（古图小三角记号） -->",
        f'  <path d="{mountains_d()}" stroke="rgba(110,85,45,.4)" stroke-width="0.9" fill="none"/>',
        "  <!-- 陆上国界（古图点状虚线） -->",
        '  <g filter="url(#wm-ink-soft)" stroke="rgba(110,85,45,.4)" stroke-width="0.9" fill="none" stroke-dasharray="1.2 3" stroke-linecap="round">',
        *[f'    <path d="{d}"/>' for d in borders],
        "  </g>",
        f'  <path d="{terra_australis_d()}" stroke="rgba(110,85,45,.3)" stroke-width="1.2" fill="none" stroke-dasharray="6 5"/>',
        f'  <path d="{waves_d()}" stroke="rgba(110,85,45,.28)" stroke-width="1" fill="none"/>',
        "`",
        FOOTER,
    ]
    out = Path(args.out)
    out.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(
        f"写出 {out}（{out.stat().st_size / 1024:.0f} KB；"
        f"海岸线 {len(land)} 段 / 湖泊 {len(lakes)} 段 / 河流 {len(rivers)} 段 / 国界 {len(borders)} 段）"
    )


if __name__ == "__main__":
    main()

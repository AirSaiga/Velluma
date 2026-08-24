# -*- coding: utf-8 -*-
"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
语义匹配阈值校准脚本（任务包 D，手动小工具，不进 CI）。

目的：services/style/semantic_match.py 的 SEMANTIC_HIT_THRESHOLD = 0.78
是拍脑袋初值。本脚本用真实 embedding 模型跑一组受控语料，实测
「同义变体句」（换字逃逸：陈词的改写变体）与「无关句」（正常写作）
的相似度分离度，给出阈值建议——分离度好则阈值取两簇中点；两簇重叠
则说明该模型/该维度下语义闸分辨力不足，宁可调高阈值少误报。

语料：约 10 条种子陈词（取自 services/style/default_cliches.py）×
每条 2 句手写同义变体句 + 6 句无关句。全部向量一次批量请求。

注意：本脚本只调 embedding API、不碰向量数据库，故不受
is_embedding_configured() 的 SQLite/pgvector 方言门控影响——只看
model_config.json 的 embedding 连接是否配了 api_key。

用法：
    python scripts/calibrate_semantic_threshold.py
    python scripts/calibrate_semantic_threshold.py --threshold 0.82
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows 控制台 GBK 防御
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # pragma: no cover
    pass

from backend.core.model_config import get_embedding_connection
from backend.services.llm.embedding import cosine_similarity, get_embeddings
from backend.services.style.default_cliches import (
    ZH_CLICHE_BLOCKER,
    ZH_CLICHE_WARNING,
    ZH_HOUSE_VOICE_WARNING,
)
from backend.services.style.semantic_match import SEMANTIC_HIT_THRESHOLD


# ============================================================
# 受控语料（陈词 pattern → 2 句同义变体；无关句独立一组）
# ============================================================
# 变体句的写法刻意贴近「换字逃逸」实景：句式语义与陈词同型，但逐字不
# 含 pattern 本身（脚本会 assert 这一点，防语料自己犯规）。

VARIANTS: dict = {
    "眼底闪过一丝": ["她的眼底掠过一抹讶异。", "他目光深处闪过些许不耐。"],
    "嘴角勾起一抹": ["他嘴角扬起一丝弧度。", "她唇角勾出一点笑意。"],
    "深邃的眼眸": ["那双眼睛深不见底。", "她有着幽深的双眸。"],
    "难以言喻的": ["一种说不清楚的感觉涌了上来。", "那是种无法形容的滋味。"],
    "命运的齿轮": ["命运开始悄然转动。", "宿命的巨轮缓缓启动。"],
    "时间的长河": ["在岁月的洪流里，什么都会淡。", "时光的长流冲淡了一切。"],
    "心如刀绞": ["心口像被利刃绞着。", "他心里像被刀割一样疼。"],
    "不动声色地": ["他面无表情地继续说。", "她神色未变地收回手。"],
    "意味深长": ["这话里有话。", "他话中别有所指。"],
    "仿佛在诉说着": ["像在低声讲述什么。", "似乎正倾诉着往事。"],
}

UNRELATED: list = [
    "他把柴火劈好，码在墙角。",
    "锅里炖着萝卜牛肉，汤面浮着一层油花。",
    "船在第三天清晨靠了岸，缆绳勒得木桩咯吱作响。",
    "她数了数铜板，还差三文。",
    "雨下了整夜，屋顶漏下一线水，正好滴在门槛内侧。",
    "老周把烟袋在鞋底磕了磕，起身去关鸡笼。",
]


def _load_patterns() -> list:
    """从 default_cliches 种子里取 VARIANTS 覆盖的陈词（顺序稳定）。"""
    seeds = {
        item["pattern"]: item
        for item in ZH_CLICHE_BLOCKER + ZH_CLICHE_WARNING + ZH_HOUSE_VOICE_WARNING
    }
    patterns = []
    for pattern in VARIANTS:
        if pattern not in seeds:
            print(f"[警告] 种子库中找不到陈词「{pattern}」，请同步更新 VARIANTS 语料")
            continue
        patterns.append(pattern)
    return patterns


async def run(current_threshold: float) -> int:
    connection = get_embedding_connection()
    if not connection.get("api_key"):
        print("未配置 embedding（model_config.json 的 embedding 节缺 api_key）。")
        print("请先在设置弹窗或 model_config.json 中配置 embedding 连接后再校准。")
        return 1

    patterns = _load_patterns()
    if not patterns:
        print("没有可用种子陈词，先检查 default_cliches.py 与本脚本 VARIANTS。")
        return 1

    # 语料自检：变体句不得逐字包含 pattern（防语料自己犯规变成精确匹配）
    for pattern in patterns:
        for sentence in VARIANTS[pattern]:
            assert pattern not in sentence, f"变体句含原词面：{pattern} ∈ {sentence}"

    sentences = [s for p in patterns for s in VARIANTS[p]] + UNRELATED
    print(f"模型: {connection['model']}  维度: {connection['dimensions']}  "
          f"连接: {connection['source']} ({connection['base_url']})")
    print(f"语料: {len(patterns)} 条陈词 × 2 句变体 + {len(UNRELATED)} 句无关句\n")

    vectors = await get_embeddings(patterns + sentences, timeout=180)
    pattern_vecs = vectors[: len(patterns)]
    sentence_vecs = vectors[len(patterns):]
    if not any(pattern_vecs) or not any(sentence_vecs):
        print("[错误] embedding 请求失败（返回全空向量），检查连接后重试。")
        return 1

    # ---- 相似度矩阵（行=陈词，列=变体1/变体2/无关句最大值）----
    print("=" * 72)
    print(f"{'陈词':<10}  {'变体1':>6}  {'变体2':>6}  {'无关最大':>6}")
    print("-" * 72)
    variant_sims: list = []
    unrelated_max = -1.0
    for i, pattern in enumerate(patterns):
        if not pattern_vecs[i]:
            print(f"{pattern:<10}  （向量缺失，跳过）")
            continue
        base = i * 2  # 变体句区按 pattern 顺序两两排布
        sims = [
            cosine_similarity(pattern_vecs[i], sentence_vecs[base]),
            cosine_similarity(pattern_vecs[i], sentence_vecs[base + 1]),
        ]
        unrel = max(
            cosine_similarity(pattern_vecs[i], sv)
            for sv in sentence_vecs[len(patterns) * 2:]
        )
        variant_sims.extend(sims)
        unrelated_max = max(unrelated_max, unrel)
        print(f"{pattern:<10}  {sims[0]:>6.3f}  {sims[1]:>6.3f}  {unrel:>6.3f}")

    if not variant_sims:
        print("[错误] 全部陈词向量缺失。")
        return 1

    # ---- 分离度与阈值建议 ----
    min_variant = min(variant_sims)
    print("=" * 72)
    print(f"变体句相似度:  min={min_variant:.3f}  mean={sum(variant_sims)/len(variant_sims):.3f}  max={max(variant_sims):.3f}")
    print(f"无关句相似度:  max={unrelated_max:.3f}")
    separation = min_variant - unrelated_max
    midpoint = (min_variant + unrelated_max) / 2
    print(f"分离度（变体min − 无关max）: {separation:+.3f}")
    if separation > 0:
        print(f"阈值建议: {midpoint:.3f}（两簇中点；取 (0.78, 建议) 中较保守者防误报）")
        if SEMANTIC_HIT_THRESHOLD > min_variant:
            print(f"⚠ 当前阈值 {SEMANTIC_HIT_THRESHOLD} 高于全部变体句 → 会漏抓，建议下调")
        if current_threshold < unrelated_max:
            print(f"⚠ 当前阈值 {current_threshold} 低于无关句最大值 → 会误报，建议上调")
    else:
        print(f"⚠ 两簇重叠（分离度 {separation:+.3f}）：该模型/维度下语义闸分辨力不足，")
        print(f"  建议取明显高于无关句最大值的阈值（≥ {unrelated_max + 0.05:.2f}），宁可漏抓勿误报。")
    print(f"\n当前生效阈值: SEMANTIC_HIT_THRESHOLD = {SEMANTIC_HIT_THRESHOLD}"
          f"（backend/services/style/semantic_match.py，改后即时生效）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="语义匹配阈值校准（手动小工具）")
    parser.add_argument(
        "--threshold", type=float, default=SEMANTIC_HIT_THRESHOLD,
        help="对照阈值（默认取 semantic_match.py 当前值）",
    )
    args = parser.parse_args()
    return asyncio.run(run(args.threshold))


if __name__ == "__main__":
    sys.exit(main())

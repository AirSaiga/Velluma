# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
# Velluma - 语义闸向量 API 可用性探针（约束治理二期 C0）
"""
纯 API 语义比对（semantic_overlap 抢拍语义闸）在**当前部署形态**下是否可用
的实测探针——与 is_embedding_configured() 的存储门控无关（SQLite 默认部署
也可用，pgvector 只有写侧/检索侧才需要）。

实测三件事：
1. is_embedding_api_configured() 窄判定（只看 Key）；
2. get_embeddings_api_only() 真实调用返回向量；
3. 近义转述对 vs 无关句的余弦分离度（阈值校准的原材料——BEAT_RUSH_SHADOW_
   THRESHOLD=0.80 是占位，2026-09-02 实测转述对仅 0.695，转正前必须按真实
   卡片×节拍语料重定档）。

用法：python scripts/probe_embedding_api.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("DATABASE_URL", None)  # 探针按默认 SQLite 路径实测（PG 路径必然可用）


async def main() -> int:
    from backend.services.llm.embedding import (
        cosine_similarity,
        get_embeddings_api_only,
        is_embedding_api_configured,
    )

    print(f"is_embedding_api_configured(): {is_embedding_api_configured()}")
    if not is_embedding_api_configured():
        print("FAIL: 未配置 embedding Key——语义闸全形态空转（零变化契约）")
        return 1

    pairs = [
        ("他走进了北岸要塞", "主角进入要塞与守军对峙"),   # 近义转述对
        ("他走进了北岸要塞", "今天天气很好适合出门散步"),   # 无关对
    ]
    flat = [t for pair in pairs for t in pair]
    vecs = await get_embeddings_api_only(flat)
    if not vecs or not any(vecs):
        print("FAIL: get_embeddings_api_only 返回空（API 不可达/维度不符）")
        return 1

    print(f"向量维度: {len(vecs[0])}")
    sim_near = cosine_similarity(vecs[0], vecs[1])
    sim_far = cosine_similarity(vecs[2], vecs[3])
    print(f"近义转述对余弦: {sim_near:.3f}")
    print(f"无关句对余弦:  {sim_far:.3f}")
    if sim_near <= sim_far:
        print("FAIL: 分离度倒挂——该 embedding 模型不适合抢拍检测")
        return 1
    print("PASS: 语义闸在当前部署真实可用；分离度样本已记录（阈值校准用）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

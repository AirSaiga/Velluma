"""BS-ADF 引擎（Beat-Slot Anchor-Driven Flow）。

V3.2 ADF 的并行引擎：把 Phase 4 的自由写作替换为
"槽位卡生成 → 双轨渲染 → 降级回退"子流水线。
复用 ADF 的 Phase 1-3（spine/anchor/tier）和 Phase 5-7（audit/refine/consistency）。
"""

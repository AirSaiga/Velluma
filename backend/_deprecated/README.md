# 废弃生成引擎归档（_deprecated/）

> 剥离日期：2026-07-24
> 操作：后端引擎剥离重构 —— 保留 ADF（V3.2）+ Refinery（V4.1），废弃 V3.0 / V3.1 / V4.0 三套引擎。

本目录存放已从活跃代码中剥离、但保留以备历史查阅或恢复的废弃引擎代码。
**这些文件不参与任何 import 链，不会被后端加载或执行。** 其内部的 `from backend...`
import 路径已失效（原路径下的文件已被移走），但因无任何活跃代码引用它们，不影响运行。

---

## 废弃引擎清单

| 引擎 | 版本 | 原端点 | 原工作流主类 | 废弃原因 |
|------|------|--------|-------------|---------|
| **Detonation（引爆链）** | V3.0 | `POST /generate-v3` | `detonation/workflow.py: DetonationWorkflow` | 高潮倒推架构，被 Unified 整体复用为底层；端点早已标 deprecated |
| **Unified（统一引擎）** | V3.1 | `POST /generate` | `detonation/unified_workflow.py: UnifiedWorkflow` | 高潮倒推的"倒着写"链路；前端已切换到 ADF，仅作备选残留 |
| **DualTrack（双轨）** | V4.0 | `POST /generate-chapter` | `dual_track.py: DualTrackWorkflow` | 双轨对抗架构；前端零调用，迭代硬编码=1，含大量死代码 |

---

## 保留的活跃引擎（不在本目录）

- **ADF（V3.2）**：`POST /generate-adf` —— 当前默认引擎，正向逐段写作 + 锚点约束
  - 代码：`backend/services/workflows/adf/`、`backend/routes/chapter_generation/adf.py`
- **Refinery（V4.1）**：`POST /refinery/diagnose` + `/refinery/confirm` —— 独立精修工具
  - 代码：`backend/services/refinery/`、`backend/routes/chapter_generation/refinery.py`

---

## 本目录结构（镜像原路径）

```
_deprecated/
├── README.md                                  ← 本文件
├── repositories/
│   └── detonation_repository.py               ← DetonationChainRepository
├── routes/chapter_generation/
│   ├── detonation.py                          ← V3.0 引爆链闸门路由
│   ├── dual_track.py                          ← V4.0 双轨路由（/generate-chapter、/plan、/plan/confirm）
│   ├── unified.py                             ← V3.1 统一引擎路由
│   ├── stream_handler.py                      ← DualTrackStreamHandler（双轨 SSE 编排器）
│   ├── progress_tracker.py                    ← ProgressTracker / StreamEventBuilder
│   ├── checkpoint_manager.py                  ← CheckpointManager
│   └── test_cp34_sse_smoke.py                 ← SSE 冒烟测试
├── schemas/
│   └── detonation.py                          ← V3.0/V3.1 Pydantic 模型 + TIER_*/ZONE_* 常量
└── services/
    ├── prompts/
    │   ├── detonation_prompts.py              ← 引爆链 prompt 模板
    │   └── stitch_prompts.py                  ← 统稿 prompt 模板
    └── workflows/
        ├── detonation/                        ← V3.0/V3.1 工作流包（13 个文件）
        │   ├── workflow.py                    ← DetonationWorkflow（V3.0 主类）
        │   ├── unified_workflow.py            ← UnifiedWorkflow（V3.1 主类）
        │   ├── chain_grower.py / payload_writer.py / fuse_writer.py / assembler.py
        │   ├── graph_auditor.py / anchored_auditor.py / refiner.py
        │   ├── ledgers.py / sketch_baseline.py / types.py
        │   └── __init__.py
        ├── dual_track/                        ← V4.0 双轨包（含 tracks/、alignment/、config/）
        ├── dual_track.py                      ← DualTrackWorkflow（V4.0 主类）
        ├── dual_track_helpers.py
        ├── sketch_generator.py                ← Track B 速写生成器
        ├── adversarial_aligner.py             ← 对抗校对器（顶层活跃副本）
        ├── stitching.py                       ← stitch_chunks（双轨统稿）
        ├── drafting.py                        ← execute_draft_stage（Track A 起草）
        ├── drafting_thinking.py / drafting_utils.py / beat_utils.py  ← 起草辅助
        ├── fortress_candidate.py              ← 要塞候选评分
        ├── fail_fast.py                       ← fail-fast 重试机制
        ├── test_cp32_smoke.py                 ← CP3.2 冒烟测试
        └── test_cp44_fortress_smoke.py        ← CP4.4 冒烟测试
```

---

## 剥离时的连带处理（已完成的代码变更）

为彻底切断废弃引擎与活跃代码的耦合，剥离时做了以下处理：

1. **`tier_classifier.py` 迁移**：原 `detonation/tier_classifier.py` 被 ADF 引擎违规
   import（`adf/tier_decider.py`）。该文件完全自包含（仅依赖 `backend.models`），
   已迁至 `backend/services/workflows/adf/tier_classifier.py`，并更新 ADF 的 import 路径。
   **注意：此文件不在本目录，是 ADF 的活跃依赖。**

2. **`__init__.py` 重导出清理**：以下聚合模块已移除对废弃引擎的重导出：
   - `services/workflows/__init__.py`（保留 planning、refining）
   - `routes/chapter_generation/__init__.py`（保留 adf、refinery router）
   - `services/prompts/__init__.py`（移除 stitch_prompts 重导出）
   - `schemas/__init__.py`（移除 detonation schemas 整块重导出）
   - `repositories/__init__.py`（移除 DetonationChainRepository 重导出）

3. **ORM / 迁移清理**：
   - `models.py`：移除 `DetonationChain` ORM 类及 `__all__` 条目
   - `database.py`：移除 detonation_chains 表的 3 条 ALTER 迁移、init_db 的 import
   - **注意：数据库中的 `detonation_chains` 表未删除，存量数据保留**（只是代码不再管理它）

4. **config 层清理**：移除 `DualTrackSettings` 类及其在 `WorkflowPolicy`、
   `DerivationEngine`、`adapter`、`mapper`、`intent_driven`、`rules` 等处的全部引用。

---

## 如需恢复

若未来需要重新启用某个废弃引擎：

1. 将对应文件/目录从本处 `git mv` 移回原路径
2. 恢复各 `__init__.py` 中被移除的重导出行（参考本文件上方"剥离时的连带处理"）
3. 恢复 `models.py` 的 `DetonationChain` ORM、`database.py` 的迁移条目
4. 恢复 `config` 层的 `DualTrackSettings` 及相关引用
5. 注意 `tier_classifier.py`：若恢复 detonation 包，需决定是把它迁回 detonation/ 还是保留在 adf/

由于全程使用 `git mv`，git 历史完整保留，可通过 `git log --follow <file>` 追溯。

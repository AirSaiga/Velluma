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
| **BS-ADF（步进）** | — | `POST /generate-bsadf` + `/advance-beat` + `/stepping-run/{id}/state` + `/rerender-beat` + `/cancel-run` | `bsadf/bsadf_workflow.py: BSAdfWorkflow` | 归档 2026-08-19（roadmap P3.2）：前端 UI 已随 2026-08-17 写作台重构移除；验证过的思想已迁入 adaptive（DDE 岔路→作者声明岔路 M3、章级规划→软脉络、字数闸门→outline 双层闸、Loop 3 涌现抽取→`services/adaptive/emergent_facts.py`、残句修复→`repair_single_defect`）。本目录含引擎包 `bsadf/`（含 8 单测与 dde/）+ `routes/bsadf_route.py` + `schemas/bsadf_schema.py` |

---

## 保留的活跃引擎（不在本目录）

- **NLE-ADF 3.0（adaptive）**：`/adaptive/*` —— **当前唯一主线**（作者主导写作 + AI 柔性共生）
  - 代码：`backend/routes/chapter_generation/adaptive.py`、`backend/services/adaptive/`
- **ADF（V3.2）**：`POST /generate-adf` —— 引擎本体保留，前端无 UI 入口
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

## 2026-09-01 死代码批量归档

**判定方法**：静态可达性分析（backend.main 起 BFS import 图）+ 消费方 grep 双重验证，零运行路径方入档。**教训**：schemas/* 曾被误判（相对导入不可见），config/intent_* 曾被误搬（整目录 mv 前未核对活清单）——整目录搬移前必须逐文件核对活死清单。

- `config/`：V4.0 参数推导层（adapter/derivation/engine/mapper/rules/schemas+generation_config）。活件 intent_driven/intent_engine 已回迁 backend/config/。
- `rag/`：旧检索器全家 18 文件 + enhanced/ 子包（retriever/scoring/编排链/context_packager/伏笔追踪/explainability/workflow_integration 等）。在役三件（recall/lexical/memory_indexing）留在 backend/services/rag/。
- `services/orchestration/`：agentic.py + beat_manager.py（tier_mapper 在役留下）。
- `services/prompts/`：bsadf_prompts / chapter_card_prompts / inspiration_prompts。
- `services/`：context/engine.py、generation/chapter_card.py、utils/sanitizer.py、workflows/{planning,context_blocks,state_validator}.py（conftest.py 在役留下）。

## 2026-09-05 global_sys_prompt（创作笔记）死线归档

**背景**：前端「创作笔记」/建书「全局提示词」/向导「写作风格指南」三处写入
`books.global_sys_prompt`，adaptive 主线（settings_bundle）零消费；消费方全部位于
V3 生成链残骸。用户拍板整线退役。本批由 `git mv` 移入，`git log --follow` 可溯。

**移入文件**（镜像原路径）：
- `services/prompts/chapter_prompts.py` —— `build_chapter_prompt` 在役代码零调用点
- `services/prompts/draft_prompts.py` + `draft_prompts_legacy.py` + `draft_prompts_prose.py`
  + `draft_prompts_review.py` + `draft_prompts_subconscious.py` + `draft_prompts_utils.py`
  —— V3/V4.0 主笔链，唯二 import 方是 barrel 与彼此（`build_draft_agent_prompt` 唯一
  调用点在 draft_prompts_legacy 内部），零外部消费者
- `services/prompts/clarification_prompts.py` + `services/workflows/clarification_agent.py`
  —— 唯一入口 `/clarify-outline` 前端零调用（旧 BS-ADF/ADF 澄清步骤）
- 前端侧同步删除（只留清单）：`frontend/_deprecated/README.md` 2026-09-05 节

**在役文件的原位修改**：
- `services/prompts/review_prompts.py` 精简为仅 `build_refine_agent_prompt`
  （refining.py/章节优化在用）；删除三个死函数；`global_sys_prompt` 读点改固定基线
  「你是一个专业的小说写作助手。」（=原空值兜底，未填笔记的书 prompt 逐字节零变化）
- `services/prompts/__init__.py`：prune 归档重导出（余 build_refine_agent_prompt + format）
- `services/generation/chapter.py` / `__init__.py`：prune 死 re-export（余
  call_llm/generate_stream_response/update_character_dynamic_state/refine_draft）
- `routes/chapter_generation/__init__.py`：摘除 `/clarify-outline` 端点及专属 import
- `schemas/generation.py`：ClarifyOutline 四件套（Request/Response/ClarifyingQuestion/
  ClarificationOption）删除；`schemas/book.py`：BookBase/BookUpdate 摘除
  `global_sys_prompt`；`schemas/__init__.py` prune
- `models.py`：`books.global_sys_prompt` 列**冻结保留**（style_blacklist 先例）——
  历史数据不动，代码不再读写；存量书若有旧笔记，无任何活路径再消费
- 未动：ADF（`setting_resolver.py` 的 `getattr` 读）——引擎本体保留原则；字段无写入方
  后 ADF 读值只会是历史存量或空，行为自然退化，不改造

- `style_knobs.py`（2026-09-14 去参数化，docs/style-parameter-effectiveness-audit.md）：
  意图旋钮档位表 + render_knob_lines 退役——rhythm/dialogue 零注入+检索数学空转，
  density/warmth 与白描封杀令指令内战；`style_cards.style_knobs`/`dialogue_ratio_target`
  两列冻结只读（列保留、历史值可读），API 写入路径一律剥离。

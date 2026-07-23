# 生成体系 3.0 实施规格（Spec）

> 日期：2026-07-20
> 前置：`docs/generation-v3-design.md`（设计文档）、`docs/generation-v2.1-brainstorm.md`、`docs/human-flavor-in-fiction.md`
> 性质：**实施规格**。设计已定，本文档把"做什么 / 做成什么样 / 如何验收"落到可执行单元。

---

## 1. 目标与范围

### 1.1 目标

把 `generation-v3-design.md` 描述的 3.0 引爆链架构落地为"作者能实际试用"的完整产品迭代，取代当前效果不佳的双轨流作为可选生成引擎。

### 1.2 已确认决策（用户拍板）

| 维度 | 决策 |
|---|---|
| Phase A 前置闸门 | **跳过**，信任设计文档的两个核心假设（逆向规划消除漏洞感、爆炸先写解决平淡）；由 Slice A 的真实成稿作为事实上的 Phase A 验证 |
| 本轮范围 | **Phase 1+2+3**（后端引爆链 + 审计与回写 + 前端闸门 UI） |
| 新旧流程共处 | **并存**：3.0 走新端点 `/api/chapters/{id}/generate-v3` + 前端"生成引擎"开关，旧双轨 `/generate-chapter` 保留作 fallback |
| 前端闸门复杂度 | **完整闸门**（含树可视化编辑） |
| 实施顺序 | **横向最小纵切**：Slice A（最小纵切出第一份成稿）→ Slice B（叠加审计与回写）→ Slice C（叠加完整闸门 UI） |
| 后端架构 | **新建 `DetonationWorkflow` 与 `DualTrackWorkflow` 并列**，两个类完全隔离，代码层零交叉 |

### 1.3 与设计文档的现实校正

实施前已核查代码现状，对设计文档做以下校正（不修改原文档，仅在实施中以本 spec 为准）：

| 设计文档原文 | 代码现实 | 实施校正 |
|---|---|---|
| `workflows/reviewing.py`（review_draft + revision_plan）无调用方 | 文件不存在；真正孤儿是 `services/validation/chapter_reviewer.py` + `review_repair.py` | 3.0 有锚审计不替换任何活跃代码，与 CP3.4 双层审计（`CodeAuditPipeline`+`LLMAuditor`+`QualityReport`）并存 |
| `asyncio.Semaphore(5)` 硬编码并发 | `drafting.py` 实际是严格串行 Rolling Prefix 链 | 3.0 引线写作沿用串行（呼吸连续性本就要求串行），无并发要改 |
| `StyleCardManager` 类 | 不存在 | 职责分散在 `StyleCardRepository` + `extract_style_card()`，沿用现状 |
| PlotLedger 自动落账是改造 | 唯一活跃写入是 `activate_plot_ledgers`（仅 publishing 流闭账），**无开账路径** | 3.0 伏笔自动落账是 0→1 新功能，需新增 `create`/`plant_from_setup_node` 仓储方法 |
| 模型三槽位路由（reasoning/creative/light） | 仅 reasoning/creative 两个 profile；`light` 静默 fallback 到 creative | 3.0 现阶段用 reasoning/creative 即可；light 槽位缺口不阻塞实施 |
| CP2.4 sketch 已是 3.0 预备 | sketch 已半废弃（`dual_track.py:336-339` 守卫） | 3.0 废 sketch 是顺势收尾 |

### 1.4 复用清单（原样保留的 2.0 子系统）

实施中**只读不改**的现有资产：

- `backend/services/context/engine.py`（ContextEngine）
- `backend/services/context/loader.py`（load_full_chapter_context）
- `backend/services/workflows/fortress_candidate.py`（`generate_and_pick_dual_candidates` → **3.0 引爆点双候选直接复用**）
- `backend/services/observability/run_recorder.py`（RunRecorder）
- `backend/services/llm/client.py`（call_llm_with_usage）
- `backend/services/validation/code_auditors.py`（CodeAuditPipeline，7 个零 token Auditor）
- `backend/repositories/chapter_card_repository.py` + `style_card_repository.py`
- `backend/services/prompts/chapter_card_prompts.py`（章节卡 prompt，扩展不重写）

### 1.5 废除/降级清单（不删，保留作 fallback）

- `backend/services/workflows/adversarial_aligner.py`：旧路径保留，3.0 主路径不调用
- `backend/services/workflows/sketch_generator.py`：旧路径保留，3.0 主路径不调用
- `backend/services/workflows/stitching.py`：保留，仅作 >5000 字复杂章 fallback

---

## 2. 架构

### 2.1 后端模块拓扑

```
backend/
├── models.py                                ★ 新增 DetonationChain + StoryBeat 6 字段 + ChapterCard.payload_moment
├── database.py                              ★ MIGRATIONS 列表追加 7 条（6 StoryBeat 列 + 1 ChapterCard 列）
├── schemas/
│   ├── __init__.py                          ★ 追加 detonation schemas 导出
│   └── detonation.py                        ★ 新增：PayloadMoment / SetupNode / DetonationChain 等 Pydantic 模型
├── repositories/
│   ├── __init__.py                          ★ 追加 DetonationChainRepository 导出
│   └── detonation_repository.py             ★ 新增：DetonationChain CRUD + PlotLedger 落账辅助
├── services/
│   ├── prompts/
│   │   └── detonation_prompts.py            ★ 新增：4 个核心 prompt（候选生成/树生长/引线写作/有锚审计）
│   ├── workflows/
│   │   └── detonation/                      ★ 新增独立包
│   │       ├── __init__.py
│   │       ├── types.py                     ★ dataclass：PayloadMoment / SetupNode / DetonationChain / DetonationResult
│   │       ├── chain_grower.py              ★ 引爆链生长（逆向递归，1-2 次 reasoning）
│   │       ├── payload_writer.py            ★ 引爆点双候选写作（复用 fortress_candidate）
│   │       ├── fuse_writer.py               ★ 引线写作（距离指令 prompt）
│   │       ├── assembler.py                 ★ 轻量组装（阅读序拼接 + 接缝过渡句）
│   │       ├── graph_auditor.py             ★ Layer 0 图校验（零 token 纯算法）
│   │       ├── anchored_auditor.py          ★ Layer 1 有锚审计（Slice B）
│   │       └── workflow.py                  ★ DetonationWorkflow 主类（编排上述模块）
│   └── generation/
│       └── detonation_service.py            ★ 闸门服务：候选生成 + 树持久化 + 引爆点人审
└── routes/
    └── chapter_generation/
        ├── __init__.py                      ★ 追加 detonation_router 合并
        ├── progress_tracker.py              ★ 追加 3.0 SSE 事件构造器
        └── detonation.py                    ★ 新增：/card-v3 /detonation-chain /payload /generate-v3 等闸门端点
```

### 2.2 前端模块拓扑

```
frontend/src/
├── services/api/domain/
│   └── index.ts                             ★ 追加 detonationApi（候选/树/引爆段/SSE）
├── features/
│   ├── chapter-editor/
│   │   └── containers/ChapterEditorContainer.vue   ★ 追加"生成引擎"开关
│   └── detonation-gate/                     ★ 新增 feature（Slice A 列表式 / Slice C 树可视化）
│       ├── index.ts
│       ├── types.ts
│       ├── containers/
│       │   └── DetonationGateContainer.vue
│       └── presentation/
│           ├── PayloadCandidatePanel.vue    (Slice A)
│           ├── ChainNodeList.vue            (Slice A 列表式 → Slice C 升级为树)
│           ├── ChainTreeView.vue            (Slice C)
│           ├── PayloadReviewPanel.vue       (Slice A 双候选对照)
│           └── DetonationQualityReport.vue  (Slice A 原始 → Slice C 可视化)
└── components/
    └── GenerationEngineSwitch.vue           ★ 新增：双轨 / 引爆链切换
```

### 2.3 数据流（3.0 主路径）

```
作者在 ChapterEditor 选"引爆链"引擎
  ↓
GET /api/chapters/{id}/detonation-state       （恢复未完成链）
  ↓ 无 →
POST /api/chapters/{id}/card-v3                （章节卡 + 引爆候选，复用 preview_plan 扩展）
  ↓ 闸门 1：作者选/改引爆点
PUT /api/chapters/{id}/detonation-chain        （持久化确认的 payload + 进入 growing）
  ↓
POST /api/chapters/{id}/detonation-chain/grow  （树生长：逆向递归，1-2 次 reasoning）
  ↓ 闸门 2：作者审树（增删改节点 / 换引爆点）
PUT /api/chapters/{id}/detonation-chain        （持久化确认的树 + status=confirmed）
  ↓
POST /api/chapters/{id}/payload/write          （引爆点双候选，复用 fortress_candidate）
  ↓ 闸门 3：作者审 ~800 字（双候选对照选定 / 手改）
PUT /api/chapters/{id}/payload/text            （冻结为锚）
  ↓
POST /api/chapters/{id}/generate-v3            （SSE：引线写作 → 组装 → 图校验 → [B: 有锚审计 → 精修] → 文本流）
  ↓
作者读成稿 → 满意则发布（沿用现有 /publish，伏笔自动落账在 Slice B 接入）
```

---

## 3. 数据模型

### 3.1 新表 `detonation_chains`

| 字段 | 类型 | 说明 |
|---|---|---|
| id | UUID PK | |
| book_id | UUID FK books | |
| chapter_id | UUID FK chapters | nullable（草稿态可暂空） |
| version | Integer | 版本号（换引爆点局部重长时 +1） |
| payload | JSONB | PayloadMoment（见 §3.2） |
| nodes | JSONB | List[SetupNode]（见 §3.3） |
| reading_order | JSONB | List[str]（节点 id 序，末位是 "PAYLOAD"） |
| status | String(50) | draft → growing → confirmed → writing → done |
| confirmed_by | String(50) | user / auto |
| created_at | DateTime | |
| updated_at | DateTime | |

通过 `Base.metadata.create_all` 自动建表（无需写 MIGRATION）。

### 3.2 PayloadMoment（JSONB）

```json
{
  "id": "PAYLOAD",
  "description": "...",
  "emotional_target": "...",
  "answers_question": "...",
  "opens_question": "...",
  "must_land": true,
  "candidate_index": 0,
  "text": "...",           // Phase 3 双候选选定/人审后的成文
  "approved": false
}
```

### 3.3 SetupNode（JSONB 列表元素）

```json
{
  "id": "n1",
  "type": "plant | development | diversion | texture",
  "content": "...",
  "sets_up": ["PAYLOAD"],
  "distance_to_payload": 1,
  "assignment": "suppress | tighten | release_partial | texture",
  "question_delays": "...",
  "restraint_note": "...",
  "subtext": "...",
  "satisfied_by_existing": null,
  "planted_in_text": null,
  "future_payoff": null,
  "beat_id": null,
  "trivial": false
}
```

### 3.4 StoryBeat 扩展（6 个新列，走 MIGRATION）

`chain_node_ids JSONB` / `sets_up JSONB` / `payoff_of JSONB` / `assignment VARCHAR(50)` / `question_open TEXT` / `question_delays TEXT`

### 3.5 ChapterCard 扩展（1 个新列）

`payload_moment JSONB`（章节卡生成时同步产出的引爆点候选列表，作为"闸门 1"的输入）

---

## 4. API 契约

所有端点前缀 `/api/chapters/{chapter_id}`，挂在 `chapter_generation` 路由器下。

| 方法 | 路径 | 阶段 | 闸门 |
|---|---|---|---|
| GET | `/detonation-state` | 恢复 | - |
| POST | `/card-v3` | 章节卡+引爆候选 | → |
| POST | `/detonation-chain` | 树生长（首次） | → |
| GET | `/detonation-chain` | 读取 | - |
| PUT | `/detonation-chain` | 编辑/确认 | ✋ |
| POST | `/detonation-chain/grow` | 重新生长/局部重长 | → |
| POST | `/payload/write` | 引爆点双候选 | → |
| GET | `/payload/text` | 读取 | - |
| PUT | `/payload/text` | 选定/编辑 | ✋ |
| POST | `/generate-v3` | SSE 全流程 | → |
| GET | `/detonation-chain/report` | 落地报告 | - |

### 4.1 SSE 事件（`/generate-v3`）

沿用现有 `TEXT_CHUNK` / `COMPLETE` / `ERROR` / `HEARTBEAT`，新增：

- `DETONATION_STAGE`：阶段切换（FUSE_WRITING / ASSEMBLING / GRAPH_AUDIT / ANCHORED_AUDIT / REFINING）
- `FUSE_PROGRESS`：引线段进度（segment_index / total_segments）
- `DETONATION_METRIC`：图校验/起爆分等指标
- `DEGRADED`：降级事件（沿用）

---

## 5. Prompt 契约（核心 4 模板）

详见设计文档 §7。实施要点：

- **§7.1 引爆点候选生成**：reasoning, T=0.5，产出 3 候选；与章节卡生成**合并为 1 次调用**（章节卡 prompt 末尾追加"同时产出 payload_candidates"）
- **§7.2 铺垫树生长**：reasoning, T=0.3，两段式（自由分析 → JSON 抽取）；递归终止三条件
- **§7.3 引线写作**：creative, T=0.8，距离指令模板；payload_text 或其关键段落锚注入
- **§7.4 有锚审计**：reasoning, T=0.1，证据链 JSON（Slice B）

所有 prompt 遵守 2.0 契约：system 静态前缀保缓存、user 动态尾部、两段式输出、降级显式化。

---

## 6. Slice 划分与验收

### Slice A：最小纵切（2-3 周）

**后端**：
- 数据模型与迁移（§3）
- schemas/detonation.py
- detonation_prompts.py（§7.1/7.2/7.3 三模板）
- detonation/ 包：types / chain_grower / payload_writer / fuse_writer / assembler / graph_auditor / workflow
- routes/chapter_generation/detonation.py + progress_tracker SSE 帧
- 章节卡扩展 payload_candidates

**前端**：
- detonationApi（domain/index.ts）
- detonation-gate feature（列表式闸门：候选 radio + 节点可排序卡片 + 双候选对照 + 质量报告 JSON）
- 生成引擎开关

**验收闸门**：
- ✅ 作者能走完三闸门 → 拿到第一份 3.0 成稿
- ✅ 第一份成稿可盲读（事实上的 Phase A 验证）
- ✅ 切换回双轨引擎可正常生成（fallback 完好）

### Slice B：审计与回写（2-3 周）

**后端**：
- anchored_auditor.py（§7.4：落地验证 + 起爆验证 + 早泄检查）
- 精修接证据链（断线节点补埋 / 早泄段降燃 / 起爆不足引爆段换候选重写）
- detonation_repository.py 的 PlotLedger 自动落账（树节点 future_payoff → 开账）
- restraint_note 校验（代码关键词 + LLM 抽查）
- SSE v3 事件（DETONATION_METRIC 上浮起爆分/断线率）

**前端**：
- DetonationQualityReport 升级为指标可视化（断线/起爆分/早泄/伏笔落账率）

**验收闸门**：
- ✅ 质量指标达标（断线节点率=0、起爆分≥7、早泄段数=0、伏笔自动落账率≥90%）

### Slice C：完整闸门（2-4 周）

**前端**：
- ChainTreeView.vue（节点卡片 + 引线边，支持拖动/增删/换引爆点）
- 换引爆点局部重长（后端 `/detonation-chain/grow` 支持局部重生长）
- 完整质量报告页（指标卡片 + 断线节点定位 + 起爆分趋势）

**后端**：
- `/detonation-chain/grow` 支持 `partial_from_node_id` 参数（局部重长）
- 复杂章 fallback 接管（>5000 字自动走 stitching + 分段）

**验收闸门**：
- ✅ 作者能完整操作三闸门（含树可视化编辑）
- ✅ 换引爆点局部重长不影响其他子树

---

## 7. 风险与对策（沿用设计文档 §11，增补实施层风险）

| 风险 | 对策 |
|---|---|
| 跳过 Phase A，假设不成立 | Slice A 2-3 周即出第一份成稿做盲读；新端点 + 开关并存策略保证可回退 |
| 树生长质量不稳（递归发散/漏关键前提） | established_facts 接地终止；深度上限 6 层；代码级树校验 + 带反馈重试 ≤2 轮；作者树闸门兜底 |
| 引线压抑=无聊 | 问题流保温（每段配 question_delays）+ Phase A 重点验证此点 |
| 引爆点先写导致引线与引爆文风断层 | 同一文风卡+作者样本贯穿；引爆段关键句锚入引线 prompt；接缝工序 |
| 前端树可视化复杂度爆炸 | Slice A 先用列表式跑通主链路，Slice C 再叠可视化；若树库（vue-flow/D3）集成成本过高，降级为"缩进列表 + 连线 CSS" |
| 双轨并存导致代码重复（ContextEngine 装配等样板） | 接受少量重复换取隔离彻底；提取共享 helper 仅当重复超过 ~50 行 |

---

## 8. 实施次序（横向最小纵切）

```
Slice A（本轮）:
  A1. 数据模型 + 迁移
  A2. Pydantic schemas
  A3. Prompt 模板
  A4. detonation/ 包（核心服务）
  A5. 路由 + SSE 帧
  A6. 章节卡扩展
  A7. 前端最小闸门 + 引擎开关
  A8. 集成验证（跑通新端点）

Slice B（后续）:
  有锚审计 + 精修 + 伏笔落账 + SSE v3

Slice C（后续）:
  树可视化 + 换引爆点局部重长 + 完整质量报告页
```

本 spec 只覆盖 Slice A 的完整实施；Slice B/C 在 Slice A 验收后基于实际经验再细化。

---

## 9. 验收标准（Slice A）

实施完成的判据（逐条可验证）：

1. `backend/models.py` 存在 `DetonationChain` 类；`StoryBeat` 含 6 个新列；`ChapterCard.payload_moment` 存在
2. `backend/database.py` MIGRATIONS 列表含 7 条新迁移（6 StoryBeat + 1 ChapterCard）；`detonation_chains` 表自动建表
3. `backend/schemas/detonation.py` 存在且在 `schemas/__init__.py` 导出
4. `backend/repositories/detonation_repository.py` 存在且在 `repositories/__init__.py` 导出
5. `backend/services/prompts/detonation_prompts.py` 含 4 个 prompt 构建函数（候选/树生长/引线/有锚审计占位）
6. `backend/services/workflows/detonation/` 包含 7 个模块文件
7. `backend/routes/chapter_generation/detonation.py` 存在，11 个端点全部注册；`__init__.py` 合并了 detonation_router
8. `backend/routes/chapter_generation/progress_tracker.py` 追加了 3.0 SSE 事件构造器
9. 后端启动无 ImportError（`python backend/main.py` 能起）
10. `GET /api/health` 200
11. `POST /api/chapters/{any_chapter_id}/card-v3` 返回章节卡 + payload_candidates
12. `POST /api/chapters/{id}/detonation-chain/grow` 返回合法的树（有 nodes + reading_order，每节点可达 PAYLOAD）
13. `POST /api/chapters/{id}/payload/write` 返回双候选
14. `POST /api/chapters/{id}/generate-v3` 返回 SSE 流，含 FUSE_PROGRESS + TEXT_CHUNK + COMPLETE
15. 前端 `detonationApi` 存在；`detonation-gate` feature 含至少 4 个组件
16. 前端 `ChapterEditorContainer` 含"生成引擎"开关
17. 前端 `npm run typecheck` 通过
18. 切换回双轨引擎，`/generate-chapter` 仍正常工作（fallback 完好）

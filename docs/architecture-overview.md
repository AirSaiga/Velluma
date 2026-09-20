# Velluma 新生成架构总览（V3.2 + V4.0 + V4.1 + V4.2 + V4.3）

> ⚠️ **【历史快照 2026-07-21，2026-09-19 标注归档】**本文是 ADF 主线时代的全景图，此后格局已多次更迭：现行主线为 **NLE-ADF 3.0 自适应流**（见 AGENTS.md「引擎对照」与 `docs/agent/nle-adf.md`）；Refinery 已拔除（2026-09-12）；设定中心页已退役（2026-09-05）；`features/canon` 前端从未落地（后端 canon 服务仍在役）；V4.2 Reader Mirror / V4.3 Storyboard 仅存于本文的设计记载，从未实施。运行事实一律以 AGENTS.md 为准，本文只作设计考古。
> （后端 canon 14 端点与 reader_mirror 服务仍在 `main.py` 注册服役——查真相层现状请读 `docs/agent/world.md`。）

> **版本**：V3.2 ADF + V4.0 Canon + V4.1 Refinery + V4.2 Reader Mirror + V4.3 Storyboard
> **状态**（写作时点）：全栈搭建完成，全量验证通过
> **日期**：2026-07-21
> **本文作用**：把分散在 4 个设计文档里的模块整合为一张全景图

---

## 1. 架构全景

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 0: 作者意图层（Author Intent Layer）                   │
│  ★ 介入点 1（生成前）：章节规划确认                            │
│  - Reader Mirror 规划建议（期待张力/爽点周期）                 │
│  - Canon 摘要（private 字段）                                 │
│  - 作者对每个建议问题做决策                                    │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Layer 1: 真相层（Canon Layer，V4.0）                         │
│  - 作者脑中世界图谱（节点 + 边 + 双层 visibility）            │
│  - private 字段绝不泄露到正文                                  │
│  - 一致性引擎 + 变更连锁分析                                   │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Layer 2: 生成层（Generation Layer，V3.2 ADF + V4.3 Storyboard）│
│  - 正向流写作（N 段，每段受三方约束）                          │
│  - 镜头景别（5 档：远景/全景/中景/近景/特写）                  │
│  - 运镜指令（5 种：cut/push_in/pull_out/counter/fade）        │
│  - Canon 注入 prompt 作为强约束                                │
│  - 关键词检测 Precondition 落地                                │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: 精修层（Refinery Layer，V4.1）                      │
│  ★ 介入点 2（诊断后）：问题清单确认                            │
│  - 诊断 → 作者确认 → 局部手术 → 整体回读 → 抛光              │
│  - 多工序流水线（每工序只做一件事）                            │
│  - 流式手术事件（progress_callback）                          │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│  Layer 4: 反馈层（Feedback Layer，V4.2 + V4.3）               │
│  ★ 介入点 3（成品后）：读者反馈                                │
│  - Reader Mirror 期待账本（双层：作者声明 + 自动推断）         │
│  - 读者反馈（1 次 LLM 扮演读者，叙述性感受）                  │
│  - 张力曲线（全书节奏可视化）                                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 五个核心模块

| 模块 | 版本 | 职责 | 核心原则 |
|---|---|---|---|
| **Canon** | V4.0 | 存作者脑中真相 | private 绝不泄露 + 一致性引擎 |
| **ADF** | V3.2 | 正向流式生成正文 | 远端锚牵引 + 条件涌现 |
| **Storyboard** | V4.3 | 镜头景别分镜 | 5 档景别 + 5 种运镜 |
| **Refinery** | V4.1 | 多工序精修 | 读-诊断-局部手术-回读-抛光 |
| **Reader Mirror** | V4.2 | 读者状态镜像 | 仪表盘不是方向盘（作者主权） |

---

## 3. 三个对话式介入点

| 介入点 | 时机 | 作用 | 端点 |
|---|---|---|---|
| **介入点 1** | 生成前 | 章节规划确认（期待/爽点/Canon） | `POST /api/chapters/{id}/plan-suggestion` |
| **介入点 2** | 诊断后 | 问题清单逐条确认（避免自我合理化） | `POST /api/chapters/{id}/refinery/diagnose` + `/confirm` |
| **介入点 3** | 成品后 | 读者反馈（叙述性感受） | `POST /api/chapters/{id}/reader-feedback` |

---

## 4. 端点清单（26 个新架构端点）

### V3.2 ADF（1）
- `POST /api/chapters/{id}/generate-adf` — ADF 引擎生成（SSE）

### V4.0 Canon（14）
- `GET/POST/PUT/DELETE /api/books/{book_id}/canon/nodes[/{id}]`
- `GET/POST/PUT/DELETE /api/books/{book_id}/canon/edges[/{id}]`
- `GET /api/books/{book_id}/canon` — 整书图谱
- `GET /api/books/{book_id}/canon/nodes/{id}/neighbors`
- `GET /api/books/{book_id}/canon/hooks`
- `POST /api/books/{book_id}/canon/check` — 一致性检查
- `POST /api/books/{book_id}/canon/impact/{id}` — 连锁分析
- `POST /api/books/{book_id}/canon/extract` — 自动提取

### V4.1 Refinery（2）
- `POST /api/chapters/{id}/refinery/diagnose` — 诊断（SSE 第一阶段）
- `POST /api/chapters/{id}/refinery/confirm` — 手术+回读+抛光（SSE 第二阶段，流式）

### V4.2 Reader Mirror（7）
- `GET /api/books/{book_id}/reader-mirror`
- `GET /api/books/{book_id}/reader-mirror/plan/{chapter_number}`
- `POST/PUT/DELETE /api/books/{book_id}/reader-mirror/expectations[/{id}]`
- `POST /api/books/{book_id}/reader-mirror/tension/{chapter_number}`
- `POST /api/books/{book_id}/reader-mirror/infer/{chapter_id}`

### V4.3 介入点 1 + 3（2）
- `POST /api/chapters/{id}/plan-suggestion` — 章节规划建议
- `POST /api/chapters/{id}/reader-feedback` — 读者反馈

---

## 5. 完整工作流（用户视角）

```
1. 建模阶段（一次性，持续维护）
   ├─ 进入「脑图」tab（Canon）
   ├─ 添加 private 角色/事件/伏笔节点
   └─ 进入「设定中心」→「期待账本」（Reader Mirror）
      添加作者声明的期待

2. 章节生成（每章）
   ├─ 选 V3.2 引擎 + 定档 → 点「生成本章」
   ├─ ★ 介入点 1：章节规划确认弹窗
   │   ├─ 看 Reader Mirror 建议（张力/爽点周期）
   │   ├─ 看活跃期待
   │   ├─ 回答系统提问（释放/累积/反转）
   │   └─ 确认 → 进入生成
   ├─ ADF 正向流写作（带景别分镜）
   │   └─ 每段推 ADF_PROGRESS（含 shot_type/transition）
   ├─ ★ 介入点 2（可选）：点「启动精修」
   │   ├─ 诊断 → 问题清单
   │   ├─ 作者逐条确认（确认/否决/补充）
   │   └─ 手术+回读+抛光（流式）
   └─ ★ 介入点 3（可选）：点「获取读者反馈」
       └─ LLM 扮演读者写叙述性感受

3. 全书维护
   ├─ 章节发布后 Reader Mirror 自动推断期待变化
   ├─ Canon 自动提取候选节点（待作者确认）
   └─ 张力曲线可视化（爽点周期一目了然）
```

---

## 6. 解决的问题清单（对照今晚讨论）

| 问题 | 解决方案 | 状态 |
|---|---|---|
| Q1 钩子丢失 | Canon HOOK 节点 + 强制 Precondition 关联 | ✅ |
| Q2 设定词缺失 | Precondition.must_use_terms 关键词检测 | ✅ |
| Q3 场景切换突兀 | V4.3 Storyboard（景别 + 运镜） | ✅ |
| Q4 段间拼接错位 | V4.1 Refinery 诊断（pacing_break）+ 手术 | ✅ |
| Q5 信息泄露 | Canon private 字段 + Refinery 诊断（info_leak） | ✅ |
| Q6 节奏拖沓 | Refinery 诊断（pacing_drag）+ 手术 | ✅ |
| Q7 直陈句太多 | Refinery 诊断（tell_not_show）+ 手术 | ✅ |
| Q8 人物脸谱化 | Refinery 诊断（character_off）+ 手术（部分） | ⚠️ |
| Q9 文学性不足 | 受 LLM 上限限制，第 4 期文风指纹 | ⚠️ |
| Q10 作者未写设定 | Canon private 字段 + 介入点 1 询问 | ✅ |
| Q11 高频即兴修改 | Canon 连锁分析 + 介入点 1-3 | ✅ |
| Q12 真相在脑中 | Canon 是最高权威 + 一致性引擎 | ✅ |
| Q13 系统绑架作者 | Reader Mirror 是仪表盘不是方向盘 | ✅ |
| Q14 爽点周期 | Reader Mirror suggest_chapter_plan | ✅ |
| Q15 期待 ≠ 伏笔 | Expectation 双层账本（张力/状态） | ✅ |
| Q16 信息差 | InformationAsymmetry schema（v1 基础） | ⚠️ |

✅ 完全解决 / ⚠️ 部分解决（v1 基础，后续迭代）

---

## 7. 代码组织总览

```
backend/
├── schemas/
│   ├── adf.py                    V3.2 ADF
│   ├── canon.py                  V4.0 Canon
│   ├── refinery.py               V4.1 Refinery
│   └── reader_mirror.py          V4.2 Reader Mirror
├── services/
│   ├── workflows/adf/            V3.2 ADF + V4.3 Storyboard
│   │   ├── adf_workflow.py       主类
│   │   ├── forward_flow_writer.py 正向流写作（含景别注入）
│   │   └── storyboard.py         ★ V4.3 镜头景别
│   ├── canon/                    V4.0 Canon
│   │   ├── consistency.py        一致性引擎
│   │   ├── impact.py             连锁分析
│   │   └── extractor.py          自动提取
│   ├── refinery/                 V4.1 Refinery
│   │   ├── refinery.py           主类（流式 refine）
│   │   ├── diagnostician.py      诊断
│   │   ├── planner.py            手术规划
│   │   ├── surgeon.py            局部手术
│   │   ├── holistic_reader.py    整体回读
│   │   ├── polisher.py           抛光
│   │   └── reader_feedback.py    ★ V4.3 读者反馈
│   └── reader_mirror/            V4.2 Reader Mirror
│       └── reader_mirror.py      期待账本 + 规划建议
├── routes/
│   ├── canon.py                  V4.0 Canon REST
│   ├── reader_mirror.py          V4.2 Reader Mirror REST
│   └── chapter_generation/
│       ├── adf.py                V3.2 ADF + 介入点 1
│       └── refinery.py           V4.1 Refinery + 介入点 3

frontend/src/
├── services/api/domain/
│   ├── canon.api.ts              V4.0 Canon API
│   ├── reader-mirror.api.ts      V4.2 Reader Mirror API
│   └── index.ts                  V3.2/V4.1/V4.3 API
├── features/
│   ├── canon/                    V4.0 Canon 编辑器 + Cytoscape 可视化
│   ├── bible/containers/
│   │   └── ReaderMirrorPanel.vue V4.2 期待账本 UI
│   └── generation/
│       ├── composables/useGenerationSession.ts  全引擎统一状态
│       └── presentation/
│           ├── PlanConfirmModal.vue      ★ 介入点 1 弹窗
│           ├── RefineryIssuesPanel.vue   ★ 介入点 2 问题清单
│           └── （介入点 3 内嵌在 InspectorPanel）
└── components/TierSelector.vue   引擎选择（V3.1/V3.2）
```

---

## 8. 数据库变更

| 表 | 变更 | 版本 |
|---|---|---|
| `books` | 加 `reader_mirror` JSONB | V4.2 |
| `canon_nodes`（新建） | 节点表（17 列） | V4.0 |
| `canon_edges`（新建） | 边表（12 列，含唯一约束） | V4.0 |

所有变更通过 `Base.metadata.create_all` + MIGRATIONS 自动应用，首次启动即可用。

---

## 9. 已知简化（后续迭代方向）

1. **作者样本学习**（第 4 期）——抛光 prompt 的 author_samples 字段已预留
2. **信息差矩阵**（Q16）——schema 已定义，前端 UI 未做
3. **Canon 自动提取触发**——章节发布 hook 未接（API 已就绪）
4. **pending refinement 内存存储**——单机够用，多 worker 需 Redis
5. **角色弧线独立追踪**——当前在 Reader Mirror 的 expectation 里隐含
6. **文风指纹**——从作者修改中提取模式（第 4 期）
7. **多 POV 反打频率**——Storyboard 的 has_multiple_pov 当前固定 False

---

## 10. 验证状态

- ✅ 后端 Python 全部 import 通过
- ✅ 前端 TypeScript `vue-tsc --noEmit` 退出码 0
- ✅ 全栈 26 个新架构端点全部注册
- ✅ Planner 合并逻辑测试通过
- ✅ Reader Mirror 算法测试通过（高张力释放/卡爽点/卷末强制）
- ✅ Storyboard 分镜测试通过（远景→全景→近景×2→特写）
- ✅ 期待推断测试通过（"打脸"关键词触发释放）
- ✅ 问题构建测试通过（高张力期待/伏笔/作者意图三类问题）
- ✅ Refinery.refine 支持 progress_callback（流式手术）

---

*最后更新：2026-07-21（完整新架构搭建完毕）*

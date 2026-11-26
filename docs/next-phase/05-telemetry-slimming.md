# 协作埋点瘦身（拆除分析层，保留机制层）设计稿

> 状态：**已施工（2026-09-18，M1-M3 全落，验收绿：后端 1562 / 前端 381 + tsc 净；
> M4 专用计数随 01-04 各功能施工带入）**。叙事见 `docs/incidents/nle-adf.md`
> 「协作埋点瘦身」；词表现状见 `backend/routes/chapter_generation/adaptive/events.py` 模块头。
> 方向拍板：2026-09-18 会话（作者判定埋点「本质无效、拖累项目、暂不考虑外放」，
> 裁决删除；经代码核实后范围收敛为**瘦身**——删分析层、留机制层）。
> 性质：拆除/减负工程，不是新建。
> 一句话：埋点的价值是从多人产品继承的，单人项目里它饿死在「门卫」岗位上；
> 但同一根水管上接着三个还在干活的机制零件——**拔管会误伤，瘦身才对**。

---

## 0. 裁决依据（讨论定形）

1. **单人项目（n=1）+ 不外放**：埋点的统计价值前提是「人多稀释噪声」；36 条协作事件、
   1 条文风事件的现实下，任何「率」都无意义，且永远不会有意义；
2. **门卫岗饿死**：路线图上一批「视数据再议」的功能（M4 自动岔路、影子检转正等）
   以埋点数据为启动条件——条件永远达不到，功能等于被判无期徒刑；
3. **拖累是真实的**：15 处前端接线、DOM 事件桥、insights「协作」面板、聚合端点、
   「新功能必须配埋点」与 COLLAB_KIND_LABELS 上屏映射两条纪律——全是维护面。

**但代码核实发现**：`data/collab_events.jsonl` 有三个**运行时机制**消费方
（非分析用途），整根删除会使其失明。因此最终范围 = **删分析层，留机制层**。

## 1. 保留清单（机制零件与观测，勿动）

| 保留项 | 消费方 | 说明 |
|---|---|---|
| 事件总线：`POST /adaptive/event` + `collab_events.jsonl` 写路径 | —— | `backend/routes/chapter_generation/adaptive/events.py`；保留写侧与轮转纪律 |
| `hint_dismiss` 事件 | `services/adaptive/quiet_learning.py:188-221` | 30 天窗口同类收起 ≥3 次 → 静音；删了提醒永远学不会闭嘴 |
| `ghost_adopt` / `ghost_discard` 事件 | `services/style/sample_prior.py`（文风样本采纳率先验 ±20%）、`routes/style/feedback.py:420` | 文风「选择」平面的活零件 |
| 意图纠正类事件 | `services/adaptive/intent_inference.py:303` | 「不对」纠正手势的学习源（具体事件种类施工时核对） |
| `constraint_events.jsonl` | 约束登记册信用分 | 后端自动写、零维护、**不可补采**——影子检若哪天转正，它是唯一依据 |
| `generation_runs` / `trace_*.jsonl` | 用量台账、质量排查 | **观测，从来不算埋点**，原样不动 |

前端接线点从 15 处收缩到 4-5 处（仅保留上述机制消费的事件种类）。

## 2. 拆除清单（分析层）

1. **insights 数据页「协作」面板**：四采纳率卡 + 逐章分布（P1 §2.3 产物，commit e9d69a3）；
2. **`GET /adaptive/events/summary`** 聚合端点；
3. **纯分析用途的事件种类**及其前端接线（胶囊扩写计数、quick_note_commit 等
   只喂面板的事件；`velluma:collab-event` DOM 事件桥随接线收缩评估去留）；
4. **两条纪律废除**：「新功能必须配埋点」；「埋点枚举键上屏须过 COLLAB_KIND_LABELS 映射」；
5. 相关测试同步删（summary 端点/面板测试；机制类测试 test_quiet_learning /
   test_intent_hardening / test_style_paradigm 中的埋点路径**保留**）。

**施工第一步是清点**：`collab_events.jsonl` 现有事件种类全列清单，按「有无机制消费方」
二分，清单评审确认后再动手（防止误删机制食粮）。

## 3. 原则修订（文档义务）

「度量驱动缓行」原则修订为（施工时落进 `docs/ai-writing-philosophy.md` §8 并同步路线图）：

> **埋点不当门卫，只当刽子手、镜子与机制零件。** 启动决策靠推理与体感（单人项目里
> 最便宜的信号）；保留/移除决策留给数据（两周零交互即可读，不需要样本量）。

配套纪律：**门卫没有了，刽子手必须有名有姓**——每个新功能在设计文档里写明
「什么数据会让我杀掉它」（本夹 01-04 四份设计稿已带「度量与去留」节，照此执行）。

## 4. 对四份设计稿的度量节修订

01-04 各稿的「度量与去留」原挂在协作埋点总线上，现统一改为：

- 每个功能只带**一个专用极简计数**（如开章卡：显示次数/展开次数；问书：问题类型分布），
  写入各自的小台账或 `data/` 下独立 jsonl，**不接事件总线、不做面板**；
- 需要看数时：副驾「调试」分区出原始计数行，或直接看文件；
- 杀伐阈值仍在设计稿里写明，到点人工读数裁决。

## 5. 分期建议

| 期 | 内容 | 验收 |
|---|---|---|
| M1 | 事件种类清点 → 二分清单评审 | 清单列出每个 kind 的消费方，作者确认 |
| M2 | 拆面板 + 聚合端点 + 纯分析接线收缩（15→4-5 处） | 机制三零件行为不变（静音/先验/意图纠正对拍测试全绿）；vue-tsc 净 |
| M3 | 文档修订：AGENTS.md 埋点节、哲学文档 §8 补充条款、路线图 P0-3/§2.3/§5 标注本条为准 | 三处文档同步 |
| M4 | （随各功能施工带入）01-04 专用计数落地 | 各功能上线即带计数 |

## 6. 风险与注意

- **勿误伤机制**：M2 的接线收缩必须对照 M1 清单逐个核对；quiet_learning 有
  `use_cache=False` 即时生效路径，删错事件种类会让静音集合静默失效（该功能的事故
  前科就是「静默全灭数月不可见」——拆完必须人工触发一次 hint_dismiss 验证静音仍工作）；
- 「暂不考虑外放」留有余地：事件总线保留意味着将来若改主意，重新装备分析层的
  成本可控（总线在、写侧在，只缺面板）；
- 路线图上以埋点数据门为触发条件的缓行件（§5 表、M4 自动岔路、影子检转正门槛）
  随门卫废除而**失去触发机制**——不自动等于取消，后续按推理逐项重新分诊（在路线图
  上标注「数据门已废，改推理分诊」）。

---

### 附：代码锚点（写作时核实，行号会漂移）

- 事件总线写侧：`backend/routes/chapter_generation/adaptive/events.py:54-111`
- 机制消费方：`backend/services/adaptive/quiet_learning.py:178-221`、
  `services/style/sample_prior.py:47-68`、`services/adaptive/intent_inference.py:303`、
  `routes/style/feedback.py:420-431`
- 约束台账：`backend/services/constraints/events.py`（照抄 collab 模式，5MB 轮转）
- 测试引用：`test_quiet_learning.py:203`、`test_intent_hardening.py:414`、
  `test_style_paradigm.py:141-177`
- 前端面板：`frontend/src/features/insights/containers/InsightsView.vue`（协作分区）

### 附：M1 事件种类清点（2026-09-18 施工时核实，二分清单）

**保留（机制消费，5 种，前端发射点 3 文件 5 处）**：

| kind | 发射点 | 消费方 |
|---|---|---|
| `hint_dismiss` | WorkspaceView（感知带收起） | quiet_learning 30 天窗同类 ≥3 静音 |
| `ghost_adopt`（detail.text 必带） | useGhostDraft（Enter 落地） | sample_prior 先验 + feedback 幽灵收编池 |
| `ghost_discard` | useGhostDraft（Esc/退格） | sample_prior 先验 |
| `intent_correct` | useChapterSpine（「不对」手势） | intent_inference 纠正史教材 |
| `ghost_discard_reason` | useGhostDraft（蒸发理由 chips） | 暂无后端消费——失败分类学传感器采集（nle-adf 档案在册的未来机制，保留采集） |

**拆除（纯分析，19 种，前端发射点 8 文件 ~19 处 + insights 协作面板 + summary 端点）**：
`cards_delivered` / `dock_delivered` / `ghost_request` / `settle` / `card_burst` /
`ignition` / `ignition_dismiss` / `capsule_create` / `capsule_expand` / `finish` /
`branch_resolved` / `quick_note` / `sentence_fix` / `context_card` / `slice_mode` /
`batch_accept` / `spine_suggest` / `spine_suggest_adopt` / `spine_suggest_discard` /
`spine_intent_set` / `spine_anchor_add` / `spine_anchor_drop` / `spine_anchor_remove`
——只喂 summary 端点/面板或零消费；连带拆除 cards/dock 亮出去重签名变量、
batchAccept 埋点归账（BatchAcceptOutcome.chapterId 字段）、两个 QuickEventNote
的 commit/undo 发射。后端 `DELETE /books/{id}/adaptive/collab-events` 清空端点
**保留**（机制数据历史重置口，test_collab_clear 锁定）。

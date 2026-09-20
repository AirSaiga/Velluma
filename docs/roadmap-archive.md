# Velluma 演进路线图 · 已完结期次归档（§1–§5、§9–§20）

> **归档说明（2026-09-19 拆分）**：`docs/iteration-roadmap.md` 是演进唯一权威（append-only 编年体，每期一节）。
> 为控制主文件体积，已完结期次的长叙事抽到本文件，**节号不变**；主文件保留 §0 排序原则、§6–§8 三张横向表（决策点/分期总表/风险登记）与 §21 起近期期次。
> 本文件冻结——只增不改；新增期次一律进主文件。文中所引 `docs/` 路径为各期写作时点路径（2026-09-19 报告归档批后部分文件已移 `docs/reports/`，文件名不变）。

---

## 1. P0 观测打底（协作度量优先）

**定位**：无设计风险的纯接入期，为协作调优提供仪表。预估 1–2 周。

| # | 任务 | 说明 |
|---|------|------|
| P0-1 | 提交在途批次 | ✅ 2026-08-18：5 个逻辑提交（C1 融合+空白舆图 / embedding 解耦+设置弹窗 / 文风 PATCH+500 修复 / SQLite 备好零接线 / 启动脚本路径修正）；顺手修复记忆中三处单参 repo.update() 必 500 与表数断言 30→31。 |
| P0-2 | **adaptive 观测落库** | ✅ 2026-08-18：新增 `services/adaptive/observing.py`（chapter 级常驻 RunRecorder + per-chapter 锁 drain/restore 原子冲账 + `trace_adaptive_{chapter_id}.jsonl` 单文件追加）；五端点 bind trace + 事件 + 冲账（stitch 在 SSE finally）；六组件 record_result（intent/future/dock/critique/event_scout/settle 涌现抽取——补全 memory_ingestion 预留未接线的 recorder 参数）。 |
| P0-3 | **协作交互埋点** | ✅ 2026-08-18 落地；**05 瘦身 2026-09-18 改造**（`docs/next-phase/05-telemetry-slimming.md`，本行为历史记录、现状以该稿为准）：分析层（`GET /events/summary` + insights 协作面板 + 纯分析事件接线）已拆；事件总线保留承载机制四件（hint_dismiss 静音 / ghost_adopt·ghost_discard 文风先验+收编池 / intent_correct 意图纠正教材）+ ghost_discard_reason 传感器。 |
| P0-4 | 双轴状态机补洞 | ✅ 2026-08-18：三枚举全部**接线**（顶栏「走向已备好」文案此前是死代码）——ghostStitching 由 ghostActive 单点 watch 驱动；settling 在 settleCurrent 首尾置位回落；suggesting=心跳带回挂件/走向卡时。Ctrl+Enter 在幽灵在屏时的沉淀行为保持不变（gate 显式覆盖 ghostStitching）。 |
| P0-5 | `/adaptive/model` 处置 | ✅ 2026-08-18：副驾「章节」tab 尾部「世界模型（调试）」折叠按钮，展开拉快照渲染摘要视图（意图/最近事实/走向/沉淀字数）。 |

**出口标准**：✅ 已达成（2026-08-18）——token 成本看 `generation_runs` 表（run_id=
`adaptive_{chapter_id}`，stage 按组件拆账）+ `logs/trace_adaptive_{chapter_id}.jsonl`
（llm/client 自动埋点含 prompt/usage/延迟）。（05 瘦身注：协作采纳率出口随
events/summary 端点退役——采纳率语义现存于文风 sample_prior 先验，不再做面板。）

---

## 2. P1 写作台人机协作深化 ✅（2026-08-19 全部完成）

### 2.1 感知层补全 ✅（漂移卡经核验已在 S4+ 批次全链落地——fingerprint.compute_style_drift_hint→心跳 canon_hints→PerceptionBand violet 卡渲染，本轮验证各环节齐备；柔性通道原则贯穿后续各件）

- **文风漂移感知卡接线**：后端心跳已产 `kind=style_drift` 提示（S4+），前端
  PerceptionBand 有占位（violet 色标「S4 补全」）未渲染——接上。
- 感知带行对齐与提示密度打磨（避免协作信息过载——协作的前提是「柔性可忽略」不被
  打扰感破坏）。

### 2.2 审校闭环：finish 修复型护栏 ✅（bbbea94：repair_single_defect + /adaptive/fix-sentence 作者裁决式 + 审校 tab 修复按钮，每轮审计上限 5 处）

- 审校 tab 审计报告每条残句给「定点修复」按钮：1×creative + REASONING_DISABLED +
  max_tokens=1600 + 上限 5 处（沿用 BS-ADF Phase 7.5 参数，`sentence_integrity.py`
  为共享层现成代码）；
- 修复产出 diff 交作者裁决后落正文——「作者裁决即闸门」，不引入自动改稿；
- 一致性手术是否同批接入，视 P0 观测到的审计命中率再定。

### 2.3 走向卡质量环 ✅（6694dc4：insights 第四面板「协作」——四采纳率卡+逐章分布；**05 瘦身 2026-09-18 已拆**）

- 基于 P0-3 埋点，在数据页（insights）出「协作采纳率」区：走向卡采纳率、胶囊扩写
  采纳率、各模式 stitch 使用分布；
- 这是「相遇→走向卡桥」（§3.2）上线后的验证仪表，也是 D3 复议的唯一依据。
- （05 瘦身注：本节产物已退役——单人项目里任何「率」都无意义且永远不会有意义；
  面板与 summary 端点拆除记录见 `docs/next-phase/05-telemetry-slimming.md`，insights
  现仅存成本/质量/用量三面板。）

### 2.4 章级谋篇 ✅（M1 747244e / M2 6efb889 / M3 0f2937d；M4 DDE 自动岔路——05 瘦身后数据门已废，改推理分诊）

> ✅ D2 已拍板（2026-08-18）：可行，**核心约束「度」**——谋篇的前置心智成本必须
> 趋近于零，不得损害写作效率与心流。设计稿：`docs/chapter-planning-spine.md`
> （chapters.spine JSONB / 复合谋篇卡 / 走向卡挂锚点 / 纯算法进度判定 / M1-M4 分期，
> DDE 自动岔路列 M4 数据门）。

**问题**：段落级共生已成熟，「本章要去哪」没有伴生参照；走向卡只是逐刻柔性推测。

**形态设想**（设计稿起点，非定稿）：

1. **章首谋篇时刻**：进新章/空章点火时出现轻量谋篇卡——作者亲笔写本章意图与关键
   锚点，或采纳 AI 建议（输入：世界状态切片 + 前情回响 + 上一章走向 + 开放伏笔，
   1×creative）。产出「软脉络」：作者可改可删可无视的锚点组。
2. **走向卡挂脉络**：心跳走向卡关联脉络节点（「服务于锚点 2」），不再孤立。
3. **进度感知**：感知带提示「写到哪了 / 还剩哪些锚点未兑现 / 意图是否漂移」（纯算法，
   复用方向权重设施）。
4. **DDE 真岔路判断融入**：全章 1×creative 判断剧情级分岔（取材
   `workflows/bsadf/dde/decision_card_generator.py`），有则走向卡升级为**硬提示**
   （视觉权重区别于柔性建议），选定走向写入脉络。
5. **细纲胶囊升级**：胶囊可挂脉络锚点（「这段速记服务于锚点 N」），扩写时锚点上下文
   注入 prompt。

**设计红线**：脉络是给作者看的参照物，不是给渲染器看的槽位；一切产出柔性可忽略，
不打开谋篇卡也能照常写作；零弹窗原则延续。

**取材清单**（迁完随引擎归档）：`dde/`（岔路判断 + slot_mutator 思想）、
`slot_builder.py` enrich 双幻觉闸门、`outline_self_check.py` 大纲自检思路。

**出口标准**：作者能从空章走到完稿，全程有一个可见、可改、可无视的章级规划伴生体；
不打开它时写作体验与现状逐字节一致。

---

## 3. P2 世界页完善 ✅（2026-08-19 全部完成）

### 3.1 C2 真相层挂接 ✅（fb0d8e0 + 04662a7：ref 列/hook 并入/migrate-canon/prompt 换源+往返契约单测/EntityDetailDrawer 读者认知分区/挂接治理三处级联清理）

- canon_nodes 加 ref_type/ref_id 挂世界对象——根治**名字漂移使泄密检测静默失效**
  （角色改名 → canon label 脱钩 → `check_canon_compliance` 漏检）；
- hook 并入 plot_ledgers（加 canon_text/public_text/reveal_plan 列）；
- `/world/migrate-canon` 迁移端点（label 匹配 + 作者确认制）；
- `build_canon_context_for_prompt` 换源 + 往返单测锁三段格式契约；
- 移除 CanonSection 裸建实体入口。详设见 `canon-world-fusion.md` §4/§7。

### 3.2 W5 桥接件：相遇→走向卡桥 ✅（30621fc：encounters 注入推测+from_encounter 闸+🗺徽标+encounter_card_burst_rate 度量）

原缓行理由是「等切片数据密度验证」。方向拍板后改策略为**带度量上线，由数据决定
留存与调优**（P0-3 埋点先行，§2.3 仪表验证）：

- 切片条「相遇」数据（同地同时在场，纯计算零 LLM，W5 lite 已产）接入走向卡/方向
  权重：走向卡可出现「地图来源」建议（「甲与乙同在北岸要塞——要安排相遇吗」）；
- 验证指标：走向卡里地图来源建议的采纳率（与整体采纳率对比）。

### 3.3 C3 真相能力激活 ✅（9f3359e：连锁分析/查片段接 UI+提取候选入待确认池（accept 分流建真相节点）+时间轴揭示朱点+心跳揭示临近提醒）

- 一致性检查 / 连锁分析接真相详情抽屉 UI（后端 API 就绪休眠中）；
- canon 提取候选并入「待确认」收件箱（与 W4 候选事件同一物理池语义）；
- 揭示章投影到时间轴刻度 + 揭示临近提醒（写作中接近揭示章时感知带提示）。

### 3.4 世界页收尾与打磨 ✅（a0a3431：旧表冻结声明 8 处+切章红点修复+读者视角相遇口径定夺）

- M4 旧表收尾：audit/publish/inspiration/chapter_optimization 四路由换源 world 或
  显式声明冻结；
- 写作桥 §12 遗留观察小修（章节切换误亮红点、读者视角相遇块口径、名单外提示）；
- 期待弧线带维持暂缓（触发条件见 §5）。

### 3.5 比例尺标定与空间简报 ✅（380df52：D4-1 标定+换算双端对拍+角标；D4-2 切片距离行/邻近对；D4-3 spatial_brief 进四模式 prompt 零变化契约）

> ✅ D4 已拍板（2026-08-18）：投入，设计委托 Agent 完成。设计稿：
> `docs/reports/map-scale-spatial.md`（books.map_scale / 三步拉线标定 / 步行日内部基准 /
> 前后端同构换算 / D4-1..3 分期，spatial_brief 为 D4-3）。

- 解封 W5 缓行①；标定交互 ≤3 步（拉线→选档→完成），未标定书静默降级；
- D4-3 的 spatial_brief 进 settings_bundle 遵守零变化契约（无标定书 prompt
  逐字节不变）。

---

## 4. P3 基建与架构债轨（功能期间隙插入）

| # | 任务 | 说明 |
|---|------|------|
| P3-1 | **SQLite 切换日** ✅（f745ee5：默认 data/velluma.db，DATABASE_URL 显式给出走 PG；canon 兼容层四查询接通；端到端建库验证） | 按 `backend/db_sqlite/__init__.py` 清单执行：aiosqlite 入 requirements、`main.py` init_db 分支（默认 SQLite，`DATABASE_URL` 显式给出仍走 PG）、canon_repository 接 compat_queries、启动脚本与打包数据目录、存量迁移入口（`scripts/migrate_pg_to_sqlite.py`，新装默认 SQLite/存量首启引导迁移）。C2 已在 §3.1 先行，schema 收敛约束自然满足。 |
| P3-2 | **BS-ADF 整体归档** ✅（dc7af61+50099af：emergent_facts 迁出→引擎/路由/schema 归档 _deprecated；前端 -1168 行；原「顺带拆 composable」升格为独立后续任务 T1，见 §9） | §2.4 取材完成后：引擎移入 `backend/_deprecated/`；前端删 `useGenerationSession.ts` 约 2000 行休眠步进逻辑 + `bsadfApi` + Track A/B 类型；顺带把 adaptive 逻辑从 3371 行单文件拆为独立 composable。 |

---

## 5. P4 数据驱动缓行件（触发条件制，不预排期；**05 瘦身 2026-09-18：数据门已废，改推理分诊**——下表触发条件原挂协作埋点总线，总线已缩至机制四件；各缓行件后续按推理与体感逐项重新分诊，不自动等于取消）

| 候选项 | 出处 | 激活触发条件（原口径，历史记录） |
|---|---|---|
| 世界页全图读者滤镜（纯作者视角工具；**读者分享版地图已随「不社区化」拍板移除**） | world-writing-bridge W5 缓行③ | P0 埋点显示切片条读者视角档使用率高 |
| 切片条升级 editor-host 常驻列 | world-writing-bridge §10.1 | P0 埋点显示切片条使用率证明常驻价值 |
| 期待（ReaderMirror）弧线带 | world-unified-settings M3 注 | 伏笔弧线带使用数据验证价值后单独设计 |
| 信息差矩阵 UI / 角色弧独立追踪 | architecture-overview §9 | 用户反馈驱动 |
| 作者级跨书文风卡 / 预设署名风格 | style-module §10 | 文风埋点数据再议 |
| E4 复核 / 心跳漂移重度化 | style-module §8 | 维持不做，除非漂移提醒采纳率高且误报率低 |

---

## 9. 后续任务（独立排期，不属于任何已完成期次）

| # | 任务 | 说明 |
|---|------|------|
| T1 | **useGenerationSession adaptive 逻辑拆分** | P3-2 设计时标「顺带」的 composable 拆分，实施时评估风险大于收益（写作主线路径集中于此文件），升格为独立任务：把 adaptive 键位状态机/车道管理拆出独立 composable，主文件只留会话编排。前置：一次全量 GUI 回归。验收：vue-tsc 净 + 全部既有测试过 + 写作台键位行为逐项不变。 |

---

## 10. 收尾记录（2026-08-19 归档）

P0-P3 + D4 全量完成并经真机首验。上线后两起事故当场修复：
1. **存量数据未随切换迁移**（206efc7）：切换日只换默认引擎，旧 PG 数据需显式跑 `scripts/migrate_pg_to_sqlite.py`；脚本同批增补「源 PG 结构补齐」——源库未跑过启动迁移时（ORM 新列缺失）先过一遍 MIGRATIONS 清单再搬（只加列不动行）。实测 3 书 20 章 1266 行全过。
2. **SQLite 方言 UUID 字符串不容忍**（53b2828）：repo 惯约 str 传参在 PG+asyncpg 被驱动容忍，SQLite 下 `value.hex` 崩 → world 查询全 500。修在 `db_sqlite/type_compat` 的类型级容忍（str 先解析为 UUID），一处覆盖所有调用点，PG 路径零变化。

后续：真实写作使用数据（协作面板/埋点）驱动 P4 缓行件与 M4 数据门评估；T1（useGenerationSession 拆分）独立排期（§9）。归档时工作区干净、157 后端测试 + 21 前端测试全绿。

---

## 11. P5 地基加固期（2026-08-20 立项，✅ 施工完成 2026-08-21）

**定位**：「作者录入设定 → AI 放大设定」地基不变，修系统侧契约违约点 + 录入回报可见
+ 架构内提生成效果。设计哲学与全部实施细节见 **`docs/reports/foundation-hardening.md`**
（唯一执行载体，含 §11 施工记录），此处仅登记排期骨架。

| 批次 | 内容 | 状态 |
|---|---|---|
| 批次 1 | B2 AI 所见预览（全局观测依赖，先做）→ A4 叙事时间来源可见 → A2 在场提权 → A5a 候选去重 → B3 用量可见 | ✅ 2026-08-21 |
| 批次 2 | A1 私有语义统一（信任级）→ A5b/c/d 回流闭环（批量裁决/积压提醒/沉淀直达） | ✅ 2026-08-21 |
| 批次 3 | A3a 截断常量收敛（57 常量入 budget.py，零行为变化）→ A3b 预算动态分配（机制落地，默认恒等不触发；调参留实测期） | ✅ 2026-08-21 |
| 批次 4 | C1 上屏前快检染色 → C2 样本场景匹配 → C3 分模式差异化注入；B4 真流式按 D8 未启动 | ✅ C1-C3 2026-08-21 |
| 收尾批次 | finish 报告 memory_indexed 层级错位修复 / boundary-pacing 测试措辞对齐（后端首次全绿）/ 五处注释与死代码债 | ✅ 2026-08-21 |

中期立项登记：C4 world_bridge 换源（A3b 后）、SQLite 向量补强、draft/planner/agentic
休眠链归档评估。观察项：ghost_guard 一次性 flake（25+ 次复跑未复现）。
排序标尺：**作者录了但系统没忠实使用 = 违约，按严重程度排队修**；不做任何
「补偿无设定场景」的能力（2026-08-20 拍板的产品立场）。
出口标准余项：实测期验证（A1 泄底 / C2 / A3b 调参 / B4 决策）与 GUI 对拍，
待真实写作使用回收。

---

## 12. 战略定稿与实测修复期（2026-08-25 立项，✅ 施工完成 2026-08-26，实测期开放中）

**定位**：架构层大讨论（调研 + trace/DB/遥测三源实证）后的战略定稿与首轮施工。
设计哲学与全部细节见 **`docs/reports/auto-read-quiet-learning.md`**（唯一执行载体，
含战略六问+第七问定稿、生成质量三机制诊断、事故台账），此处仅登记骨架。

| 批次 | 内容 | 状态 |
|---|---|---|
| 战略定稿 | 六问拍板（严肃作者/大局镜子/铁律不动/更懂这本书/带得走/只自写）+ 第七问「系统自己去读」破喂养死循环；实测双轨（读《弦上灰》写《最终武装》） | ✅ 2026-08-25 |
| WP1 学着闭嘴 | 被拒学习双通道（收件箱类型级 + 感知带提醒级）、静音派生不落库、宽恕锚点 assist_mutes、幽灵蒸发理由条 | ✅ fb8e3c7 |
| WP2 自动阅读 | 预算闸 read_budget（哈希幂等/间隔/每日上限）+ auto-read/read-entities 端点 + 切章发枪 + 全书通读两阶段向导 | ✅ 4d992c6 |
| WP3 视野配比 | 续写窗 200→800/500→1200（P1-3 数据门达成）+ 大纲就近化（outline_nearby 共享）+ 句界净截 | ✅ 4d992c6 |
| WP4 剂量与预算 | 点火剂量闸（防冲章实证事故）+ spine-suggest 2400+空输出重试 | ✅ 4d992c6 |
| 语义修复 | 思考关闭从「不表态」改显式关闭（MiMo 默认开实证） | ✅ 862132d |
| 首秀实测四修 | 冷启动自锁 / 层叠穿帮 / 跨章重复+默认日期 / 连点事故双闸+清库 | ✅ 28c8e73 cdfb740 61bdd01 b4e38b8 |
| 审计二修+文档同步 | 通读阶段 B 静默空跑（ts_key 分立）/unknown 厂商关闭态；五处文档滞后 | ✅ c017837 a3b7441 |
| 感知链五连修 | 出场卡形状修复/dock_muted 闭嘴到端/场景锚定/缝合契约反转（复读剥离）/文流第一 | ✅ ec4974d a2088e8 7d266d2 501b982 1c16243 |

出口标准（实测数据回收后验收，见执行文档 §5-6）：收件箱采纳率、蒸发理由分布、
静音准确性、模型 A/B 归因（**卡 DeepSeek Key 失效**——A/B 乙侧与 mimo 禁令
不服从两悬案的钥匙）、自动阅读日花费带、感知带出场卡真实触发验证。
基线：后端 624 / 前端 93 全绿（2026-08-26 二次归档时）。


---

## 13. 世界内核期（2026-08-28 立项，B0-B9 ✅ 2026-08-28 施工完成——执行计划唯一载体 `docs/reports/world-kernel-construction-plan.md`；B8 stitch 门与金标准标注待真实使用签发）

**定位**：四域存在论（truth/intent/belief/presentation）内核 + WCA 分层认知——
设计唯一权威 `docs/world-kernel-foundation.md`（地基）与 `docs/world-cognition-architecture.md`（四层）。
动因：方向权重引擎尸检（18 次恒常量输出，先验力学无观测无回路）+ 用户定调
「地基优先、不模仿业界、创新超越」。知识检索平面 v3.1（2026-08-27 施工，
`docs/knowledge-retrieval-plane.md`）是本期的注入车道底座。

| 批次 | 内容 | 状态 |
|---|---|---|
| B0 | 清账提交 + context_manifest 观测 + 注入未消费率脚本 + 金标准评测工具 | ✅ 68f6f21 |
| B1 | Event v2（time_precision/supersedes/认知事件家族/时序边）+ Fold API 唯一入口 | ✅ b13bf7f |
| B2 | Intent 统一存储（伏笔/期待/揭示迁入；spine/大纲因作者主权保留原状）+ 双读迁移 | ✅ cd08985 |
| B3 | belief 域折叠（四值 clearance）+ 泄密检测命题化（视角配给随数据激活） | ✅ c88481b |
| B4 | Depiction 呈现关系 + 回填气闸端点 + reader 折叠 + 负空间差集（阶段 C 前端 UI 待接） | ✅ 4eb3619 |
| B5 | provenance 信封 + 现实校验挂 finish | ✅ dc4a4df |
| B6 | 温层计划层温卡 + 提及逐出前缀 + 章内冻结缓存（prefix byte-equal 测试锁） | ✅ e6cd2e7 |
| B7 | 热层显著性（影子常开）+ 方向权重引擎删除（信号转世）+ dock 具名提示单车道 | ✅ 3921bbc |
| B8 | 冷层 digest（节级键控+事实节纯代码+ops 编译器+预算分池；**门控关闭中**——stitch 双门未签发） | ✅ 56a86ac |
| B9 | 认知浮现三时机 + books.cognition_surfacing 总开关（可见性悖论防线） | ✅ 本批 |

不变量验收（11 条，见地基文档 §4）与每批回退路径随批登记。

---

## 14. deai 期（2026-08-31 迁入立项——去AI味小模型子项目 + 宿主接口预留）

**定位**：卡片舱（幽灵草稿）上屏前的「小模型抛光」。`deai/` 自 `D:\deai` 整体迁入
（v1 已收官：百炼 SFT Qwen3-4B+LoRA，15 条 holdout 六闸 14/15=93% 基线；模型侧契约
唯一权威 `deai/docs/contract.md`，归档报告 `deai/docs/archive.md`）。宿主集成唯一
权威 `docs/deai-integration.md`。

| 项 | 内容 | 状态 |
|---|---|---|
| 迁移 | deai/ 44 文件入库（.gitignore 对 deai/data、deai/logs 反排除 + 脚本 SPDX 补头）+ 迁移后四自检全绿 | ✅ 本批 |
| 配置 | model_config.json `deai` 节（enabled/api_key/model/base_url；未配置=零调用、逐字节零变化） | ✅ 本批 |
| 后端 | `backend/services/deai/`：`polish_fragment` 公共入口 + 契约§6 事实闸保底回退原文 + `gates.py` 运行时闸门移植副本（权威在 deai/scripts/validate_pairs.py）+ 17 单测对拍 | ✅ 本批 |
| 挂点 | stitch-ghost 呈现平面（字数闸后、ghost_guard 快检前）；≤100 字契约窗内短稿生效、长稿自动跳过；GHOST_DONE `deai` 增量字段；trace/style_events `deai_polish` 遥测 | ✅ 本批 |
| 设置 | 设置弹窗「实验：去 AI 味小模型」折叠分区 + `POST /api/system/deai/test` 试一试（表单实时值；事实闸保底回退不算失败） | ✅ 本批 |
| 训练对收集 | 写作台浮窗「记改前/记改后」两步配对 → `data/deai_pairs.jsonl` → `ingest_behavior_pairs.py` 去重+六闸 → `behavior_sft.jsonl`（数据飞轮手动起点，导师评价轮采纳：bad=主模型原样产出、good=作者亲手版） | ✅ 本批 |
| v2 扩量 | 叙事类语料收集（deai/data/inbox/ 收集箱，v1 训练语料无小说文本）→ 六闸管线 → 重训重部署 → 仅需换配置里的部署名；句级分片长稿覆盖 / GHOST_DONE `deai` 字段前端消费（抛光 chip）待评估 | ⏸ 搁置（等真实使用回收） |

## 15. 地点内部构造期（2026-09-01，`docs/reports/location-interior.md` 唯一权威）

| 项 | 内容 | 状态 |
|---|---|---|
| v1+二期 | `world_locations.parent_id` 树零迁移（上图权=parent_id IS NULL 铁律）/ LocationDetailDrawer 二级面板面包屑下钻 / 树删 BFS 父前子后+子树快照撤销 / 幂等闸改同父同名 / 速记与事件表单房间级全路径消歧 | ✅ 3271bd0 |
| 场景作用域 | `scene_scope_ids` 钉房间祖先算在场；场景身份块带地点档案（无 intro 零变化）；`scene.path` 全路径 | ✅ 3271bd0 |
| 父地点闸 | update_location 补父存在+同书+非自身+非子孙防环（与 create 同口径，553f4f7） | ✅ 553f4f7 |

## 16. 约束治理期（2026-09-02 一期施工，`docs/constraint-governance.md` 唯一权威）

执法可靠性序=供给切断>输出代码闸>确定性改写>prompt 偏置>事后审计；把「约束」从 prompt 文案升格为注册管理的代码资产。

| 项 | 内容 | 状态 |
|---|---|---|
| 注册表+台账 | `services/constraints/registry.py` 约束登记册（id/layers/enforcement/status=shadow\|live\|report-only\|retired）+ `events.py`（data/constraint_events.jsonl，信用分数据不可补采） | ✅ 一期 |
| prompt 编译器 | `prompt_sections.py` 剂量治理分节编译（dock 首租户：节拍子句挂 has_outline_nearby、自检清单已删、强措辞 15+→≤4） | ✅ 一期 |
| ghost 第五检 | out_of_scene shadow 出生（warning 带 local_only 不进 GHOST_DONE，白名单=称呼表同一产物透传）；回归语料库 `validation/regression_corpus/` 准入即测试；promote 门槛=语料全对+≥20 次真实命中 FP<10% | ✅ shadow |
| 输入侧 | `scene_visibility.py`（称呼表过滤迁此+after_text 泄漏手术——仅出现于胶囊后文的名字不进称呼表，挂账残留见 constraint-governance §8）；B6 数据缺口=event_parser 三级匹配+`lexical_presence.py` 词法兜底（presence_source=lexical）+切片条「据正文推断」badge+`scripts/backfill_event_participants.py` 回填 | ✅ 一期 |
| persona 漂移 | `persona_drift.py`（B5 report-only：叙述段第一人称密度超阈值落台账） | ✅ report-only |
| 明确不做 | constrained decoding / 实时 judge 拦截 / 多轮重试（dock 靠过采样 4-6 枚代替） | — |

另：2026-09-01 死代码批量归档 38 件（314e414——rag 旧检索器全家/V4.0 config 参数推导层等迁 `backend/_deprecated/`，无行为变化，不设期）。

## 17. 真相与意图质感期（2026-09-03 三连施工，已提交 b8209f5/d7337d8/2a040fd/e51adcc/defcf49 + 时间轴 3fc79be 09-02）

真相层 UX 人话化重修（因果图谱+连锁分析退役——建边零入口实证；详情两问重排「读者现在知道吗/打算怎么抖出来」，设计稿 docs/design/truth-ux/）/字段级真相分层（档案字段三态 chip + 派生感知五消费线，零变化契约锁定）/时间轴 UX 两轮（内容贴合自动视野/三档刻度/浮点年日精度/拖拽平移）/意图感知入舱（三级源链 spine>大纲>AI 猜 +「不对」纠正手势 + 后续线 A-E：stitch 意图兜底/意图画像/章首接力棒/双 shadow 检）/续写质感治理（双轨 motion·texture 契约 + beat_rush live+rewrite + 质感密度测量与 finish 样本候选）。

## 18. 大纲板与运维收口期（2026-09-04～09-06，已提交）

大纲板重写为故事线俯视板（d1bafd5：章号轴伏笔弧线/真相朱点/张力折线 + 章卡规划列就地编辑）/09-04 审计修复两批 + 死代码清理（2cc4bb7/2e2b441：B5 现实校验复活/幽灵跨章双防线等 21 项）/世界侧栏直达创建入口（f40f1bc）/启动脚本单窗口监控台 + 网页监控台 + 后台 python 监督者（556aa6b）/设定中心页整体退役 + global_sys_prompt 死线归档（d75abef）/SPDX 协议头 100% 规范化（ecbeb94）。

另：2026-09-07 起前端 UX 重构多期（地基 Esc 栈/浮层钳位 + 世界页图标栏三组 + 写作台 08 期「桌上一张纸」，设计稿 `docs/design/ux-redesign/`）与 dock 红队三批（在场制/对白分镜组/FIM 中插桥接/临时通行证）原在未提交工作区——已随 2026-09-13～16 提交收录，行为记录见 §19/§20 与 AGENTS.md。

## 19. 写后检查收敛与深水区加固期（2026-09-11～09-13，已提交）

架构优化双轮七项（a66ffd3：backend/models 35 表按域拆 8 子模块 + adaptive 路由拆 8 子模块 + style 路由拆 6 子模块 + 四对双实现收敛 + FK 排雷；成本核算 `services/llm/pricing.py` 价目纯函数随批入库）/启停脚本防误杀加固（de035eb：OwnedPort 端口登记+状态 JSON 新鲜度闸+taskkill 树杀三护）/模型配置预设快速切换（28664b3：整套存档一键切回+自动存档安全网）/**写后检查收敛（d1a5b38：Refinery 与 /critique_chapter 整体拔除——未过目整章覆写/noHistory 不可撤销/跨章覆写三连风险；手术原语迁 `services/text_surgery/`、读者反馈收编 `/adaptive/reader-feedback`，唯一权威 `docs/reports/post-writing-checks-audit.md`；AI 视角面板 09 期重设计同批——保字排版/三段分组/折叠头行仪表盘）**/事件可编辑标题（21c640c：`world_events.title` 列 + `eventDisplayName` 回退链）/时间轴视觉升级（9179868：信标针脚/金墨直方图/燕尾书签/黄铜菱形游标/快捷视界胶囊）/应用图标单源（8b0db19：`frontend/electron/app-icon.png`）/深水区红队四件（cb5ee8f 别名归一补口+微镜头旁路 deai/P2、594bc28 dock 输入减肥 DOCK_PIPELINE_VERSION→v2.2、456ccc0 RAG 检索分流去敏——V/B 抹在场实体名 A 流保原文、a165f8e 跨书文风黄金池冷启动兜底）/桥接后文锚扩窗 300 字+六目标边界修复（6607adb，DOCK_PIPELINE_VERSION→v2.3）/卡片舱与文风链路调研报告归档（ea4cfa3）。

## 20. 文风去参数化、叙事四弹与主题焕新期（2026-09-14～09-16，已提交）

叙事四弹（b89f804 世界页时间轴 60 帧性能重塑 / a5f102c 文风去参数化——旋钮滑块退役+亲笔样本真实装填通道，`docs/reports/style-parameter-effectiveness-audit.md` / 0050eed 场次流转第三弹——光标派生取景 `active_scene` 纯函数+四线接流，`docs/reports/scene-transit-feasibility.md` / edce677 第四弹——打算与大纲 UI 单轨合流叙事引力流面板 + `/adaptive/active-beats`，`docs/reports/spine-outline-merge-feasibility.md`）/主题系统五主题×明暗+chrome 视觉现代化+设置拆三入口与 Electron CSP 防闪收口（9cab473，设计稿 `docs/design/theme-system/`）/AI 视角简报化（e8cd82c：战局态势卡+空块静音+preview 光标真切片，`docs/reports/ai-view-briefing-feasibility.md` + 使用说明 `docs/ai-view-panel-guide.md`）/Tab 重算失败可见化（5606689：本地端点连接快速失败不重试+旧卡年龄+舱内朱色报错行）/模型槽显式化（4666ca9：全链 model_type 归位+Ollama reasoning_effort=none 思考关闭实测修复，含槽位全景报告 `docs/reports/model-slot-coverage-report.md`）/数据库卫生批（dc74486：事件 id 引用格式归一+fold 出场即活语义+幂等检测脚本 `scripts/check_db_hygiene.py`）/书架视觉改版 v2+novel-wizard 向导整体退役（81d53c0：新建唯一入口=快速创建，一句话打算直落第 1 章 spine）/全量测试补全批（ec0fe8e：改码→测试映射纪律文档 `docs/testing-guide.md`）。

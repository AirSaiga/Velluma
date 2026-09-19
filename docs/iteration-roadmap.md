# Velluma 后续迭代路线图（P0–P5）

> 状态：**方向与定位已拍板（2026-08-18）**——优先「世界页完善 × 写作台人机交互协作」；
> 产品定位「**真实可用的玩具**」（自用验证优先，可作开源产品但不社区化）；
> SQLite 切换日与 BS-ADF 归档降为基建/架构债轨，在功能期间隙插入。
> 本文档是生成与交互侧演进的唯一权威载体。
> 前置：世界层 M1-M6+ ✅ · 写作桥 W1-W5lite ✅ · Canon 融合 C1 ✅ · 文风 S1-S5 ✅ ·
> BS-ADF 已整体归档 `_deprecated/`（P3-2 ✅）
> 关联：`docs/canon-world-fusion.md` §7（C2/C3 详设）· `docs/world-writing-bridge.md`
> §6（W5 缓行件）· `docs/style-module-redesign.md` §8（E4 维持不做）·
> **`docs/foundation-hardening.md`（P5 地基加固期执行文档，2026-08-20 立项）**

---

## 0. 背景与排序逻辑

### 0.1 方向与定位拍板（2026-08-18）

产品方向确定为两条主线：

- **线 A · 写作台人机交互协作**：心跳感知/走向卡/细纲胶囊/审校等协作交互的深化与补全；
- **线 B · 世界页完善**：真相层挂接（C2/C3）、W5 桥接件、旧表收尾。

两条线是**同一个飞轮的两侧**：世界页生产设定数据，写作台消费它做协作，W 桥接件
是连接件。因此排期不按线隔离，而按「度量 → 协作交互 → 世界数据喂协作」的依赖序
交织。原路线图（2026-08-18 首版）的「生成能力回补」在本方向下重新定位：P2a/P2b
不是「让 AI 更能写」，而是**协作交互设计**——尤其章级谋篇，是人与 AI 在章级尺度
上的共谋形态，而非渲染管线回归。

**定位四问确认**（同日，战略层拍板）：

- **项目定位 = 真实可用的玩具**。自用验证优先（开发者本人即长篇作者与深度用户）；
  可作开源产品，但**不社区化**（不做账号/分享/多人协作功能）。设计验收标准由此
  定为双轴：**有趣（可玩性/手感/美学）× 真实可用（一致性守护/人味守护）**。罗盘、
  空白舆图、衬线题签这类「玩具感」元素不是装饰，是产品本质的一部分；世界页与
  协作交互的打磨同时按效率与把玩感两个维度验收。终极验收标准：作者本人下一次
  真实写作的体感。
- **画像收窄成立，D3 定案**：不服务「AI 代笔成书」需求。依据：模型短期无法解决
  「不说人话」，完全代笔破坏作者心流，写作体感不如作者主导。推论：文风体系与人味
  防线（指纹/负面清单/洗涤/human-flavor 研究）的战略地位再升一级——**AI 帮忙，
  人味由作者守护**。
- **验证方式 = 自用验证**。P0 埋点的用途收窄为**自我可见性**（协作质量与 token
  成本的个人镜子），不做增长分析、不设跨用户指标。
- **冷启动延后并改写定义**：新书启动本就要求作者想清楚设定并亲手录入，AI 即时
  生成的初始设定是无效信息——冷启动不由「AI 生成内容」承担，而由**世界页的录入
  乐趣与顺滑**承担（新书第一小时 = 玩世界）。路线图不设冷启动主线；建书向导/导入/
  逆向提取维持现状；世界页完善的验收标准因此增加一条：**空态体验与录入顺滑度就是
  产品的第一小时**。

### 0.2 三个决定优先级的事实

1. **协作体验无仪表**。adaptive 各组件调 `call_llm_with_usage` 后 usage 全部丢弃；
   走向卡/细纲胶囊/切片条/情境浮卡**无任何采纳度量**。没有这些数据，协作交互的每次
   调优都是盲调，W5 缓行件「视数据再议」永远无数据可议。
2. **世界页数据尚未充分喂到协作现场**。相遇提示、疆域控制方、真相层秘密等数据已在
   世界页可维护，但到走向卡/感知带的桥还是 lite 态或未建（W5 缓行件）。
3. **章级尺度是协作的最大空白**。段落级共生（心跳/幽灵续写/胶囊）已成熟，「本章要
   去哪」没有任何伴生参照物——这是协作线最大的一件，且必须先出设计稿。

### 0.3 排序原则

```
P0 度量先行 → P1 协作交互深化 → P2 世界页数据喂协作 → P3 基建/架构债（间隙插入）→ P4 数据驱动激活
```

- P1 与 P2 不按线隔离，按依赖交织：世界页侧的桥接件（相遇→走向卡）直接服务 P1 的
  走向卡质量环；
- schema 变更（C2）排在 SQLite 切换日之前——MIGRATIONS 双库共享单一事实源，一次
  收敛，切换日只搬最终形态；
- 缓行件不用计划替代数据：凡「视数据再议」的项，一律等 P0 度量落地后按触发条件激活。

### 0.4 非目标（全程有效）

- E4 段落级指标制导维持不做（S4+ 复核结论：无数据支撑，走向卡已是柔性机制）。
- 多时间线 / 平行世界；实时推送同步（版本号轮询够用）。
- 不回到「按拍渲染」老路——章级谋篇的任何形态都不得把规划物变成渲染槽位。
- **整章代笔不做**（D3 定案，依据见 §0.1）。
- 不做社区化功能：账号体系/分享/多人协作/读者分享版地图（定位拍板推论）。
- 写作页内不做任何空间编辑；文风/笔记/应用设置不进世界页。

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
> `docs/map-scale-spatial.md`（books.map_scale / 三步拉线标定 / 步行日内部基准 /
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

## 6. 决策点

| # | 决策 | 状态 |
|---|------|------|
| D1 | C2 与 SQLite 切换日先后 | ✅ **已解**（方向拍板自然排序：C2 在 §3.1，切换日在 §4.1，schema 一次收敛） |
| D2 | 章级谋篇（§2.4）设计稿先行 | ✅ **已拍板**（2026-08-18）：可行，核心约束「度」（前置成本趋零、不损心流）；设计稿 `docs/chapter-planning-spine.md` |
| D3 | 是否保留整章代笔入口 | ✅ **定案不做**（2026-08-18）：模型短期无法解决「不说人话」，完全代笔破坏作者心流，体感不如作者主导 |
| D4 | 比例尺标定是否投入 | ✅ **已拍板**（2026-08-18）：投入，设计委托 Agent 完成；设计稿 `docs/map-scale-spatial.md` |
| D5 | 「私有」语义 = AI 知晓但绝不能直接写出（对齐 canon `[private]`），不从上下文删除 | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |
| D6 | 叙事时间默认值问题首版零行为变化：来源可见 + 录入侧警示（chapter_ref 方案已排除——该列全库无写入点） | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |
| D7 | 上下文预算管理器分两期：A3a 纯重构零行为变化 → A3b 动态分配单独实测 | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |
| D8 | stitch-ghost 真流式条件排期：批次 1-2 后实测首字延迟再定 | ✅ **已拍板**（2026-08-20，foundation-hardening §1） |

---

## 7. 分期总表

| 期 | 内容 | 性质 | 状态 |
|---|---|---|---|
| P0 | 在途批次提交 + adaptive 观测落库 + 协作交互埋点 + 状态机/model 端点补洞 | 纯接入 | ✅ 2026-08-18 完成（vue-tsc 净 + bsadf 118 单测全过 + 冒烟验证） |
| P1 | 写作台协作深化：感知层补全 / 审校修复闭环 / 走向卡质量环 / 章级谋篇 M1-M3 | 交互主线 | ✅ 2026-08-19 完成 |
| P2 | 世界页完善：C2 真相挂接 / 相遇→走向卡桥 / C3 激活 / M4 收尾 / D4 比例尺 | 数据主线 | ✅ 2026-08-19 完成 |
| P3 | SQLite 切换日 + BS-ADF 归档 | 基建/架构债 | ✅ 2026-08-19 完成 |
| P4 | 缓行件激活 | 数据驱动（§5 触发条件） | ⏸ 等 P0 数据 |
| P5 | 地基加固期：契约修复（私有语义/在场提权/叙事时间可见/回流闭环）+ 录入回报可见（AI 所见预览/用量）+ 预算管理器 + 生成效果调优 | 加固/体验/效果 | ✅ 施工完成 2026-08-21（`e44dd59`，后端 365/0 首次全绿、前端 85；实测期事项与 B4 待真实使用验证） |

---

## 8. 风险登记

- **useGenerationSession.ts（2426 行，步进逻辑已删）**：仍是 adaptive 主逻辑的最大
  单文件——拆分为独立任务 T1（§9），拆分前改动需谨慎；新交互件优先落在
  useAdaptiveAssist / useChapterSpine 等独立 composable。
- **协作信息过载**：P1 感知层与走向卡升级的共同风险是打扰作者心流——所有新提示
  一律走「柔性可忽略」通道（感知带/挂件，不弹窗、不抢焦点），上线后凭 P0-3 无视率
  数据回调密度。
- **SQLite 切换演练**：迁移脚本虽有行数对照 + FK 校验，切换日前仍需真实大书库演练
  一轮（SystemCliche 种子翻倍前科需回归验证）。
- **观测接入性能**：heartbeat 是高频端点（防抖 3s），RunRecorder 落库必须异步不阻塞
  响应（adf.py 已有先例）。
- **双库并存期测试盲区**：切换日后 PG 路径保留，CI 目前只跑 py_compile——canon
  兼容层两个方言各需冒烟验证手段。

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
+ 架构内提生成效果。设计哲学与全部实施细节见 **`docs/foundation-hardening.md`**
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
设计哲学与全部细节见 **`docs/auto-read-quiet-learning.md`**（唯一执行载体，
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

## 13. 世界内核期（2026-08-28 立项，B0-B9 ✅ 2026-08-28 施工完成——执行计划唯一载体 `docs/world-kernel-construction-plan.md`；B8 stitch 门与金标准标注待真实使用签发）

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

## 15. 地点内部构造期（2026-09-01，`docs/location-interior.md` 唯一权威）

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

架构优化双轮七项（a66ffd3：backend/models 35 表按域拆 8 子模块 + adaptive 路由拆 8 子模块 + style 路由拆 6 子模块 + 四对双实现收敛 + FK 排雷；成本核算 `services/llm/pricing.py` 价目纯函数随批入库）/启停脚本防误杀加固（de035eb：OwnedPort 端口登记+状态 JSON 新鲜度闸+taskkill 树杀三护）/模型配置预设快速切换（28664b3：整套存档一键切回+自动存档安全网）/**写后检查收敛（d1a5b38：Refinery 与 /critique_chapter 整体拔除——未过目整章覆写/noHistory 不可撤销/跨章覆写三连风险；手术原语迁 `services/text_surgery/`、读者反馈收编 `/adaptive/reader-feedback`，唯一权威 `docs/post-writing-checks-audit.md`；AI 视角面板 09 期重设计同批——保字排版/三段分组/折叠头行仪表盘）**/事件可编辑标题（21c640c：`world_events.title` 列 + `eventDisplayName` 回退链）/时间轴视觉升级（9179868：信标针脚/金墨直方图/燕尾书签/黄铜菱形游标/快捷视界胶囊）/应用图标单源（8b0db19：`frontend/electron/app-icon.png`）/深水区红队四件（cb5ee8f 别名归一补口+微镜头旁路 deai/P2、594bc28 dock 输入减肥 DOCK_PIPELINE_VERSION→v2.2、456ccc0 RAG 检索分流去敏——V/B 抹在场实体名 A 流保原文、a165f8e 跨书文风黄金池冷启动兜底）/桥接后文锚扩窗 300 字+六目标边界修复（6607adb，DOCK_PIPELINE_VERSION→v2.3）/卡片舱与文风链路调研报告归档（ea4cfa3）。

## 20. 文风去参数化、叙事四弹与主题焕新期（2026-09-14～09-16，已提交）

叙事四弹（b89f804 世界页时间轴 60 帧性能重塑 / a5f102c 文风去参数化——旋钮滑块退役+亲笔样本真实装填通道，`docs/style-parameter-effectiveness-audit.md` / 0050eed 场次流转第三弹——光标派生取景 `active_scene` 纯函数+四线接流，`docs/scene-transit-feasibility.md` / edce677 第四弹——打算与大纲 UI 单轨合流叙事引力流面板 + `/adaptive/active-beats`，`docs/spine-outline-merge-feasibility.md`）/主题系统五主题×明暗+chrome 视觉现代化+设置拆三入口与 Electron CSP 防闪收口（9cab473，设计稿 `docs/design/theme-system/`）/AI 视角简报化（e8cd82c：战局态势卡+空块静音+preview 光标真切片，`docs/ai-view-briefing-feasibility.md` + 使用说明 `docs/ai-view-panel-guide.md`）/Tab 重算失败可见化（5606689：本地端点快速失败+旧卡年龄+舱内朱色报错行）/模型槽显式化（4666ca9：全链 model_type 归位+Ollama reasoning_effort=none 思考关闭实测修复，`docs/model-slot-coverage-report.md`）/数据库卫生批（dc74486：事件 id 引用格式归一+fold 出场即活语义+幂等检测脚本 `scripts/check_db_hygiene.py`）/书架视觉改版 v2+novel-wizard 向导整体退役（81d53c0：新建唯一入口=快速创建，一句话打算直落第 1 章 spine）/全量测试补全批（ec0fe8e：改码→测试映射纪律文档 `docs/testing-guide.md`）。

## 21. 候选回流链路修缮期（2026-09-18，设计稿 `docs/next-phase/02-candidate-reflow-repairs.md`，未提交批内）

修缮非新建（链路本体幂等/去重/批量采纳不动）：候选补出处（抽取 prompt 要求 evidence 逐字摘录 + event_scout 落池「去空白子串」校验，编造出处剥除不上屏、候选降级无出处档；前端收件箱悬停/批量模态引文/世界页卡片三面展示）/ 撤销单事务化（`POST /world/candidates/{id}/undo-accept` 删转正产物+回 pending 一个 commit；accept 记录产物 id 入 draft）/ 拒绝史进防重（30 天窗/200 条归一化判重，auto_reject 假拒绝不计，suppressed_rejected 计数）/ 键盘裁决（↑↓/→·Enter/←·Delete，`inboxKeyboard.ts` 纯函数三宿主）/ 回场补读（进章也发枪 auto-read，哈希幂等闸兜底零成本重进）/ read-entities 失败不写幂等锚（`EmergentFacts.failed` 区分失败与无涌现）+ 顺修 `adaptive/schemas.py` 缺 `Any` 导入致 read-entities 响应必炸的预存在隐患 / 用量停机冲账（lifespan+atexit 双路 `flush_all_adaptive_records`）。叙事见 `docs/incidents/world.md`，契约见 `docs/agent/world.md` ④ 与 `docs/agent/nle-adf.md`。测试基线：后端 1531→1562、前端 370→381。

## 22. 协作埋点瘦身期（2026-09-18，设计稿 `docs/next-phase/05-telemetry-slimming.md`，未提交批内）

拆分析层留机制层：`GET /adaptive/events/summary` 聚合端点与 insights「协作」面板（四采纳率卡/逐章分布/COLLAB_KIND_LABELS/清空埋点按钮）退役——面板只剩成本/质量/用量三 tab（B3 用量两卡是 generation_runs 观测面，原样保留）；纯分析事件接线 19 种全拆（前端发射点收缩到机制 3 文件 5 处：hint_dismiss/ghost_adopt/ghost_discard/intent_correct + 传感器 ghost_discard_reason）；事件总线与写侧保留（机制四件的水管），`DELETE collab-events` 端点保留为机制数据重置口。原则修订落 `docs/ai-writing-philosophy.md` §8（埋点不当门卫只当刽子手；两纪律废除：新功能必须配埋点 / COLLAB_KIND_LABELS 上屏映射）；§5 缓行表与 §2.3/§2.4 数据门标注「已废改推理分诊」。M1 全量清点清单在 05 稿附录。机制对拍（quiet_learning 66 项/intent_hardening/style_paradigm sample_prior 5 项）全绿；基线 1562+381+tsc 净不变。

## 23. 开章卡与读者清单期（2026-09-18，设计稿 `docs/next-phase/01-opening-card-and-reader-ledger.md`，未提交批内）

两面镜子零 LLM：**开章卡**（M1——`GET /adaptive/opening-card`：空章「打算」页顶部四行：该揭（含逾期深度）/别说破（scope 徽标全书·在场两档）/线头（真实总数+最久）/此刻；三规则宪法=真实总数+口径徽标·点一下就地展开·空集零像素；设置弹窗「写作台」开关；专用计数 touch 端点写独立 jsonl——05 瘦身口径首发）/ **读者清单**（M2——finish 响应 `reader_ledger`：本章新知道/已经知道/还不知道按计划章分桶+未排期，报告末尾「读者此刻」栏）。数据底座 `services/world/reader_ledger.py` 复用 read_merge_reveals（扩文本三件）+ build_scene_slice（在场口径无平行实现）。测试 +6（test_reader_ledger.py：分类/空 None/文本携带/卡片行/空书/路由防御），基线 1568+381+tsc 净。M3 调参（超载阈值 6/排序键）待真实使用数据。

## 24. 问书期（2026-09-18，设计稿 `docs/next-phase/04-ask-the-book.md`，未提交批内）

行间手势速查：`??` 触发（AskNoteNode 手势族）→ `POST /adaptive/ask-book`——六类纯代码直答零 LLM（`services/world/ask_book.py`：线头/该揭/距离 spatial/上次出场/谁知道 belief 四值/哪章写过 jieba）→ M2 意图解析笼（LLM 只翻译+名单硬闸）→ M3 材料内合成（出处 id 校验，编造拒收）→「没查到」是一等功能。答案幽灵式浅字只读 Esc 蒸发不进正文；出处点验=章就地切/世界页深链。问题原文落 data/ask_book_metrics.jsonl（M4 分布回看）。测试 +17（test_ask_book.py：分类/六类哨兵防 LLM/硬闸/合成校验/路由/度量），基线 1585+381+tsc 净。

## 25. 幽灵改稿自动捕获与三键期（2026-09-18，设计稿 `docs/next-phase/03-ghost-edit-capture.md`，未提交批内）

deai 数据飞轮收集端零操作化 + 幽灵交互防呆：**书签位置映射**（`useGhostPairTracker`：采纳瞬间暂存 AI 原样+首尾 position 纯内存，随事务映射塌缩守原地；保存时对比并更新同幽灵只留最新版，切章定稿聚合提示+按批撤销；干净采纳跳过/塌缩=完全否决/≤100 字窗外不收）+ **三键阶梯**（Tab 采纳·Enter 暂留零承诺·Esc 丢弃+60s 找回窗；流式只打断不采纳+GHOST_DONE 400ms 缓冲窗；一期一个暂留位，暂留终局丢弃喂学习）+ **视觉**（mint 点线边界+转正段未审虚线 GhostTrack 装饰碰过即消）。pairs 后端 source 三源白名单（manual_mark/auto_ghost/capsule）。测试 +17 前端（ghostPairTracker），基线 1585+398+tsc 净。M4 度量（粮食速率/干净采纳率/暂留转化率/自动对六闸通过率）待真实写作数据。

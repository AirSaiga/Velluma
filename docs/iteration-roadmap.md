# Velluma 后续迭代路线图（P0–P4）

> 状态：计划稿（2026-08-18 归档）。生成侧演进的唯一权威载体——此前记录在 AGENTS.md
> 「弃置策略」节的迁移候选清单由本文档接管并展开。
> 前置：世界层 M1-M6+ ✅ · 写作桥 W1-W5lite ✅ · Canon 融合 C1 ✅ · 文风 S1-S5 ✅ ·
> BS-ADF 弃置中（前端 UI 已删，引擎暂留作迁移源）
> 关联：`docs/canon-world-fusion.md` §7（C2/C3 详设）· `docs/world-writing-bridge.md`
> §6（W5 缓行件）· `docs/style-module-redesign.md` §8（E4 维持不做）

---

## 0. 背景与排序逻辑

### 0.1 三个决定优先级的事实

1. **adaptive 已是唯一主线，却是唯一没有观测的引擎**。adf / bsadf / refinery 均为
   RunRecorder + trace_event 全套接入；唯独 adaptive 各组件（intent_inference /
   dock_generator / future_projection / post_process / event_scout）调
   `call_llm_with_usage` 后 **usage 全部丢弃**，orchestrator 只有软预算规划
   （单章心跳 creative ≤3000 tokens）从未被实测验证。后果：用户 API 花费无账可查；
   走向卡采纳率无从统计；W5 缓行件、E4 复核、切片条升级等**所有「视数据再议」的
   决策全部卡在缺数据上**。度量是后续一切决策的前提。
2. **SQLite 化是发行门槛，不是功能**。要求桌面用户装 PostgreSQL 没有分发可行性。
   `backend/db_sqlite/` 已备好约九成（引擎层/方言编译/列迁移复用/canon 兼容查询/
   7 项回归测试）+ `scripts/migrate_pg_to_sqlite.py` 搬迁脚本（PG 只读、行数对照、
   FK 校验），刻意零接线等待「切换日」。拖得越久，后续 schema 变更（C2 加列）叠加
   双库维护窗口的风险越大。
3. **章级规划层是生成能力的最大空白**。adaptive 把段落级共生做得很好（心跳 / 幽灵
   续写 / 细纲胶囊），但 BS-ADF 验证过价值的章级规划层（脉络轨/锚点/定档/槽位卡）
   在 adaptive **完全没有对应物**。它不能照搬槽位卡，需要从「作者主导」哲学重新设计
   形态——是全计划唯一需要先出独立设计文档的项。

### 0.2 排序原则

```
度量先行（P0）→ 发行门槛（P1）→ 能力回补（P2）→ 架构债清理（P3）→ 数据驱动激活（P4）
```

- 低风险纯接入工作排前，设计重件排后；
- schema 变更尽量在 SQLite 切换日前收敛（MIGRATIONS 双库共享单一事实源）；
- 缓行件不用计划替代数据——P0 落地后才有激活依据。

### 0.3 非目标（全程有效）

- E4 段落级指标制导维持不做（S4+ 复核结论：无数据支撑，走向卡已是柔性机制）。
- 多时间线 / 平行世界；实时推送同步（版本号轮询够用）。
- 不回到「按拍渲染」老路——P2b 的任何形态都不得把规划物变成渲染槽位。
- 整章代笔入口是否开放是哲学决策，不在本计划默认范围内（见 §6 D3）。
- 写作页内不做任何空间编辑；文风/笔记/应用设置不进世界页。

---

## 1. P0 在途落地 + 观测打底

**定位**：无设计风险的纯接入期，为后续所有数据决策打底。预估 1–2 周。

| # | 任务 | 说明 |
|---|------|------|
| P0-1 | 提交在途批次 | embedding 厂商无关化（DashScope SDK → OpenAI 兼容协议 + follow_llm + 连通性探测）、AppSettingsModal 全局设置弹窗、文风样本 PATCH（scene_type/content + 重向量化宁缺勿旧）。SQLite 部分按既定策略保持「备好不接」。 |
| P0-2 | **adaptive 观测落库** | 五端点接入 RunRecorder + trace_event（adf.py / bsadf.py 有现成范式）：heartbeat 按组件拆账（意图反推/未来推测/挂件生发/Canon 感知各记一笔）；stitch-ghost 记 mode + 目标/实际字数；settle/finish 记沉淀组件与审计调用。GenerationRun 落库。 |
| P0-3 | 双轴状态机补洞 | `ghostStitching` / `settling` / `suggesting` 三枚举从未被赋值（2026-08-18 调研发现）——要么接线（缝合期置 authorLane=ghostStitching 等），要么从枚举删除。现状是死代码且误导读者。 |
| P0-4 | `/adaptive/model` 处置 | 端点已上线但前端无调用方——给调试入口（如副驾「章节」tab 的世界模型快照折叠区）或删除端点，二选一，不留悬置。 |

**出口标准**：在 adaptive 模式写完一章后，能凭 `generation_runs` 表 + `logs/trace_*.jsonl`
回答「这章 AI 辅助各组件分别花了多少 token / 多少次调用 / 心跳软预算是否超标」。

---

## 2. P1 SQLite 切换日

**定位**：发行质量里程碑。零外部依赖单机桌面应用的最后一公里。

切换日清单（来自 `backend/db_sqlite/__init__.py` 自述，逐条执行）：

1. `requirements.txt`（两份）加 `aiosqlite`；
2. `main.py` 的 `init_db` 走分支：默认 SQLite（`data/` 下文件库），`DATABASE_URL`
   显式给出时仍走 PG（专业级/开发路径保留）；
3. `canon_repository` 4 处 PG 专有 JSONB 查询按 `dialect_name` 分派到
   `compat_queries` 的 SQLite 等价构件；
4. 启动脚本（windows/macos 三模式）与 electron-builder 打包配置的数据目录约定；
5. 存量迁移入口：`scripts/migrate_pg_to_sqlite.py`（PG 侧只读、拓扑序搬迁、行数
   对照 + `PRAGMA foreign_key_check`，embedding 列默认丢弃置 NULL——向量记忆本就是
   专业级可选项）。建议产品形态：**新装默认 SQLite；存量 PG 用户首次启动提示并
   引导跑迁移脚本**。

**先后约束**：C2（canon_nodes 加 ref_type/ref_id，见 §4）若确定要做，**宜排在切换日
之前**——MIGRATIONS 列表是 PG/SQLite 双库共享的单一事实源，先在 PG 侧完成 schema
收敛，切换日搬过去的就是最终形态，避免迁移脚本要为旧结构书再跑一轮列迁移。

**出口标准**：无 PostgreSQL 的全新机器安装后建书 → 写作 → 完稿 → 重启，数据完好；
存量测试书迁移后抽查 world_events / author_samples / canon_nodes / memory_chunks
行数与内容一致。

---

## 3. P2 生成能力回补

### 3.1 P2a finish 修复型护栏（快赢，可随时插入）

adaptive 完稿审计目前**只诊断不治疗**；BS-ADF Phase 7.5 的残句定点修复
（`services/workflows/sentence_integrity.py`，共享层，扫描已被 post_process 复用）
是现成验证过的能力。

- 审校 tab 审计报告的每条残句给「定点修复」按钮：1×creative + REASONING_DISABLED +
  max_tokens=1600 + 上限 5 处（沿用 Phase 7.5 参数）；
- 修复产出 diff 交作者裁决后落正文——符合「作者裁决即闸门」哲学，不引入自动改稿；
- 一致性手术（consistency surgery）视 P0 观测到的审计命中率再决定是否同批接入。

### 3.2 P2b 章级规划层（唯一需要先出设计文档的大件）

**问题**：BS-ADF 验证过价值的章级规划（脉络轨/锚点/定档）在 adaptive 无对应物；
走向卡只是逐刻柔性推测，没有「本章要去哪」的伴生参照。

**形态设想**（设计文档的起点，非定稿）：

1. **章首谋篇时刻**：进新章（或空章点火时）出现轻量谋篇卡——作者亲笔写本章意图 /
   关键锚点，或采纳 AI 建议（输入：世界状态切片 + 前情回响 + 上一章走向 + 开放伏笔；
   1×creative）。产出是「软脉络」：一组作者可改可删可无视的锚点。
2. **走向卡挂脉络**：心跳产出的走向卡关联到脉络节点（「服务于锚点 2」），不再孤立。
3. **进度感知**：心跳感知带提示「写到哪了 / 还剩哪些锚点未兑现 / 本章意图是否漂移」
   （纯算法，复用方向权重设施）。
4. **DDE 真岔路判断融入**：全章 1×creative 判断是否存在剧情级分岔（取材
   `workflows/bsadf/dde/decision_card_generator.py`），有则走向卡升级为**硬提示**
   （区别于日常柔性建议的视觉权重），作者选走向后写入脉络。
5. **细纲胶囊升级**：胶囊可挂在脉络锚点上（「这段速记服务于锚点 N」），扩写时锚点
   上下文注入 prompt。

**设计红线**：

- 脉络是**给作者看的参照物，不是给渲染器看的槽位**——绝不按脉络自动渲染整章；
- 一切产出柔性可忽略，作者不打开谋篇卡也能照常写作（辅助层一律可关）；
- 零弹窗原则延续（NLE 传统）。

**取材清单**（迁完随引擎归档）：`dde/`（岔路判断 + slot_mutator 纯函数思想）、
`slot_builder.py` 的 enrich 双幻觉闸门、`outline_self_check.py` 的大纲 3-pass 自检
思路（用于谋篇卡的建议质量自检）。

**出口标准**：作者在 adaptive 模式能从空章走到完稿，全程有一个可见、可改、可无视的
章级规划伴生体；不打开它时写作体验与现状逐字节一致。

---

## 4. P3 数据收敛与架构债清理

| # | 任务 | 说明 |
|---|------|------|
| P3-1 | **C2 Canon×世界挂接**（宜在 P1 前，见 §2 约束） | canon_nodes 加 ref_type/ref_id 挂世界对象——根治**名字漂移使泄密检测静默失效**（角色改名 → canon label 脱钩 → `check_canon_compliance` 子串匹配漏检，长篇连载的真实质量伤害）；hook 并入 plot_ledgers（加 canon_text/public_text/reveal_plan 列）；`/world/migrate-canon` 迁移端点（label 匹配 + 作者确认制）；`build_canon_context_for_prompt` 换源 + 往返单测锁三段格式契约；移除 CanonSection 裸建实体入口。详设见 `canon-world-fusion.md` §4/§7。 |
| P3-2 | **BS-ADF 整体归档** | P2 取材完成后：引擎移入 `backend/_deprecated/`（路由摘除）；前端删除 `useGenerationSession.ts` 约 2000 行休眠步进逻辑 + `bsadfApi` + Track A/B 类型残留。**顺带**把 adaptive 相关逻辑从 3371 行单文件拆成独立 composable——该文件是当前前端最大维护风险。 |
| P3-3 | M4 旧表收尾 | audit / publish / inspiration / chapter_optimization 四路由仍读旧 characters/assets 表——逐路由换源 world 或显式声明冻结，给「旧表彻底冻结」画句号。 |

---

## 5. P4 数据驱动缓行件（触发条件制，不预排期）

P0 观测落地前，以下项**一律不启动**——各前置文档已记录缓行理由，本表只补触发条件：

| 候选项 | 出处 | 激活触发条件 |
|---|---|---|
| 相遇 → 走向卡 / 方向权重桥 | world-writing-bridge W5 缓行② | 走向卡整体采纳率达到可判别基线（≥30%）且切片条使用率高 |
| 世界页全图读者滤镜 / 读者分享版地图 | W5 缓行③ / §4.7 | 切片条读者视角档使用率证明需求 |
| spatial_brief 空间简报 | W5 缓行① | 比例尺标定交互设计有人认领（前置依赖） |
| C3（一致性检查/连锁分析接 UI、提取候选入收件箱、揭示临近提醒） | canon-world-fusion §7 | C2 落地后 canon 节点密度上来、泄密检测有真实命中样本 |
| 期待（ReaderMirror）弧线带 | world-unified-settings M3 注 | 伏笔弧线带使用数据验证价值后单独设计 |
| 信息差矩阵 UI / 角色弧独立追踪 | architecture-overview §9 | 用户反馈驱动 |
| 作者级跨书文风卡 / 预设署名风格 | style-module §10 | 开放问题，视文风埋点数据再议 |
| 心跳漂移提醒的重度化 / E4 复核 | style-module §8 | 维持不做，除非埋点显示漂移提醒采纳率高且误报率低 |

---

## 6. 决策点（待拍板）

| # | 决策 | 选项与建议 |
|---|------|-----------|
| D1 | **C2 与 SQLite 切换日的先后** | 建议 C2 先行（schema 一次收敛，迁移只搬最终形态）；若更想尽快发版，可先切换、C2 走 SQLite 侧 MIGRATIONS（机制支持，代价是 PG 老用户迁移脚本需多跑一轮列迁移）。 |
| D2 | **P2b 设计文档先行** | 建议产出一份 canon-world-fusion.md 级别的设计稿再动工——其形态直接决定 DDE 迁移方式与「软脉络」的数据模型（新表 or 复用 plot_ledgers or 纯会话态）。 |
| D3 | **是否保留任何「整章代笔」入口** | 当前哲学是纯作者主导，细纲胶囊是唯一 AI 扩写出口。P2b 的脉络 + outline 模式天然可扩展出「整章按脉络连续扩写」。建议等 P0 有观测数据后看细纲胶囊使用率再定。 |

---

## 7. 分期总表

| 期 | 内容 | 性质 | 状态 |
|---|---|---|---|
| P0 | 在途批次提交 + adaptive 观测落库 + 状态机补洞 + model 端点处置 | 纯接入，无设计风险 | 📋 待启动 |
| P1 | SQLite 切换日（新装默认 SQLite / 存量引导迁移） | 基建，清单已备 | 📋 待启动（受 D1 约束） |
| P2a | finish 残句定点修复按钮 | 快赢，可随时插入 | 📋 待启动 |
| P2b | 章级规划层（软脉络 + 走向卡挂载 + DDE 融入 + 胶囊升级） | 设计先行（D2） | 📋 待设计稿 |
| P3 | C2 Canon 挂接 + BS-ADF 归档 + M4 旧表收尾 | 架构债清理 | 📋 待启动 |
| P4 | 缓行件激活 | 数据驱动（§5 触发条件） | ⏸ 等 P0 数据 |

---

## 8. 风险登记

- **useGenerationSession.ts（3371 行）**：休眠步进逻辑与在役 adaptive 逻辑同居一个
  文件，任何误改都可能伤及主线。P3-2 拆分前，改动此文件需格外谨慎。
- **SQLite 切换演练**：迁移脚本虽已带行数对照 + FK 校验，切换日前仍需用真实大书
  库演练至少一轮（脚本自述「首次演练曾踩过种子翻倍」——SystemCliche 种子化已在
  搬迁路径跳过，但值得回归验证）。
- **观测接入的性能**：heartbeat 是高频端点（防抖 3s），RunRecorder 落库必须异步
  不阻塞响应（adf.py 已有先例可抄）。
- **双库并存期的测试盲区**：切换日后 PG 路径保留（DATABASE_URL 显式给出时），
  CI 目前只跑 py_compile——两个方言的关键查询（canon 兼容层）需各有冒烟验证手段。

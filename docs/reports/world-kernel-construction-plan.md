> **归档说明（2026-09-19）**：世界内核期执行计划（2026-08-28，B0-B9 全部完成）；现行契约见 `docs/agent/world.md`，设计地基 `docs/world-kernel-foundation.md`。

# 世界内核施工计划（B0-B9）

> 2026-08-28 · 状态：B0-B9 全部施工完成（707 绿，逐批独立提交）；开放项：金标准标注（作者）、B8 stitch 双门签发、DeepSeek 双模型对照（B4 前端阶段 C 已于同日补齐：useReadBook/ReadBookModal/WorldView 三阶段接线+5 项 vitest+vue-tsc 净） · 上游设计：`docs/world-kernel-foundation.md`（内核地基）、`docs/world-cognition-architecture.md`（WCA 四层）、`docs/knowledge-retrieval-plane.md`（v3.1 注入车道，已施工）。
> 总原则：**每批次交付物 = 代码 + 测试 + 文档同步 + 独立提交**；全量回归绿是提交前置；每批次有验收数据门与回退路径；按用户指令本期不做 token 消耗实测优化（结构性缓存纪律保留，命中 token 度量暂缓）。

---

## 0. 总览与依赖图

```
B0 清账与观测（1-2天 + 一周数据窗）
 ├──> B1 内核 schema + Fold API（2-3天）──> B2 Intent 统一（2-3天，风险最高）
 │        │                                  │
 │        ├──> B3 belief 域（2天）<───────────┤（B2 供 Intent 查询面）
 │        └──> B4 Depiction 呈现层（2-3天 + 异步回填）
 ├──> B5 provenance 信封 + 现实校验（1-2天，与 B1-B4 穿插）
 │
 ├──> B6 温层场景卡 + 前缀纪律（1-2天，前置 B1）
 ├──> B7 热层显著性 + 方向权重拆解（2天 + 影子一周，前置 B6）
 └──> B8 冷层 digest（3-4天，双门：B0 manifest 数据 + 双模型对照）
          └──> B9 认知浮现三时机（2天，前置 B3/B4 数据积累）
```

关键路径：**B0 数据窗 → B1 → B2 → B6 → B7**；B8 独立等双门；B3/B4 可与 B2 后半并行。

| 批次 | 主题 | 规模 | 验收门 | 回退 |
|---|---|---|---|---|
| B0 | 清账+观测+金标准 | 1-2 天+一周数据 | manifest 攒满一周 | 纯增量，无回退需求 |
| B1 | Event v2 + Fold API | 2-3 天 | 不变量 2/3/4 测试绿 | fold 是包装层可退直调 |
| B2 | Intent 统一存储 | 2-3 天 | 往返单测逐字段等价 | 双读期旧表恒为事实源备份 |
| B3 | belief 域+视角配给 | 2 天 | 不变量 7 + 模态封闭 | 命题走回书级 secrets 块 |
| B4 | Depiction+回填 | 2-3 天+异步 | 不变量 9/11 | 呈现层空转不伤内核 |
| B5 | 信封+现实校验 | 1-2 天 | 不变量 5/10 | 校验只标记不删除 |
| B6 | 温层+前缀纪律 | 1-2 天 | prefix byte-equal+方差下降 | 逐出逻辑可关回 v3.1 行为 |
| B7 | 热层+权重拆解 | 2 天+影子一周 | 影子重叠率+dock A/B 不降 | 力学模型留 git 历史 |
| B8 | 冷层 digest | 3-4 天 | 采纳率/canon 合规提升 | 回退 v3.1 全注入（kill 线） |
| B9 | 认知浮现三时机 | 2 天 | UI 纪律检查表 | 浮现开关可全关 |

---

## 1. B0：清账与观测打底（先于一切新工件）

**动因**：方向权重的死因是「先建引擎后建观测」。本批让后续每个架构决策都有数据签发。

- **B0.1 提交存量**（需作者确认划分）：工作区两批未提交——①08-27 感知批次（同步钳制/接缝裁剪/场景锚定，已审计无高危）②知识平面 v3.1 一期（671 绿）。建议分两个提交。
- **B0.2 context_manifest 观测**：stitch 路由的 `kg_selected` trace 升级为 manifest（每块 key/车道/字符/条目键/prefix 哈希）；心跳组件同源。配套 `scripts/analyze_context_manifest.py`：**注入未消费率**（注入实体 × 生成/采纳文本提及重叠）、canon 跟随率、分车道采纳率。
- **B0.3 金标准评测集 v0**：弦上灰取 ~20 断点 + 苏醒 3 断点，作者标注「应选条目」（先 10 个起步，每断点约 2 分钟）；`scripts/eval_selector_recall.py` 算 recall/precision。门槛沿用设计：场景锚定相关条目 recall ≥95%。
- **B0.4 路线图挂期**：iteration-roadmap.md 增「世界内核期」条目（本计划入册）。

**数据门**：manifest 攒满一周真实写作 → 签发 B8 第一道许可。

## 2. B1：内核 schema 与 Fold API（K1+K5）

- **Event v2**（models.py + MIGRATIONS + db_sqlite/schema.py 同源）：`world_events` +`time_precision`(exact/interval/unknown) +`supersedes`（修订链，永不物理删改）；新表 `world_event_edges`(kind=before/after，时序边)；事件类型家族扩展 `told/discover/misbelieve/witness`（认知事件是真事件，同表合法；payload 契约写入模块头）。
- **Fold API**：新模块 `services/world/fold.py`——`fold(book_id, t, perspective_set, domains[truth|belief|intent|reader], tx_head=None)` 唯一入口；内部归一 compute_world_state + 各域（belief/intent/reader 分别由 B3/B2/B4 接入，本批先立骨架与 truth 域收口）。消费方收口：world_bridge/settings_bundle/scene_slice/知识平面。
- **前端同构**：`features/world/engine/` 折叠扩展 domains 参数；双端共用 seed 用例库做 fuzz 对拍。
- **测试**：不变量 2（折叠纯度 fuzz）、3（模态封闭 property test——actual-only 折叠永不含 intent/private）、4（fold 调用无默认值，签名级检查）。

## 3. B2：Intent 统一存储（K2，全程风险最高，配双读）

- **新表 `world_intents`**：kind(beat/foreshadow/expectation/reveal/promise) / scope / target(三态) / window(t 或章区间) / 生命周期枚举 / setup_event_id / realized_by / serves_anchor / provenance。
- **映射**：伏笔→foreshadow；期待→expectation；canon 揭示计划→reveal；大纲节拍→beat；spine 锚点→promise；岔路→beat 候选。
- **迁移**：`scripts/migrate_to_intents.py` 幂等复制（plot_ledgers / chapters.spine 锚点 / 大纲节拍 / canon reveal_plan / books.reader_mirror）。
- **双读过渡**：IntentRepository 读合并（新表优先/旧表兜底）；消费方切换清单：get_open_hooks 与 [hook] 装配（loader.py）、心跳 canon_hints、outline_nearby、spine 进度判定、期待账本。前端零改动（API 适配吸收）。
- **测试**：往返单测（迁移后旧表读 == 新表读逐字段等价）+ test_context_contract 式契约锁扩展。
- **回退**：双读期间任何时点切回旧表读；旧表在全部消费方切走并稳定一章前不冻结。

## 4. B3：belief 域与视角配给（K3）

- **belief 折叠**：曝光级推导（participants + told/discover/witness/misbelieve 折叠出 per-entity 信息状态）+ 命题注册表（canon_nodes 原位）clearance 查询；四值可答（knows/believes_false/unaware/unknown）。
- **场景级视角配给**：secrets 通道升级——perspective_set=在场者；**无人知晓的 private 命题不进上下文**，需暗示时以轨迹形态（hook 行）进。这是 B 的供给侧升级，也是泄密防护从「守卫」到「配给」的落点。
- **ghost_guard 精确化**：泄密检测从正则升级为命题 id 比对。
- **UI 纪律**：认知模型默认不可见（可见性悖论红线），本批不新增任何前端。

## 5. B4：Depiction 呈现层（K4）

- **新表 `world_depictions`**：subject(event|proposition) / chapter / mode(shown/told/hinted/symbolized) / status(confirmed|candidate) / source。
- **气闸升格**：world_event_candidates kind 扩展 depiction/epistemic/supersession 提案——AI 提案、作者裁决的宪法不变。
- **通读向导阶段 C**：ReadBookModal/useReadBook 扩展「呈现关系回填」（前端改动集中于此）；回填异步进行，未回填=unknown（诚实降级）。
- **reader 折叠 + 负空间差集 v0**：`dramatic_capital(book_id, t)` 内部查询——世界真相 − 读者认知 − 已排期揭示；先供 finish 报告与 canon_watch 消费，不做 UI。

## 6. B5：provenance 信封与现实校验（K6，穿插交付）

- **信封**：{source_keys, fold_version, compiler_version, params_hash}——kg_selected 升级 + 温/冷层预留；每交付一个派生物即纳入信封纪律。
- **现实校验**：`services/world/reality_check.py`——抽样派生论断回查 fold（死者/位置/关系活跃等纯代码可验项），finish 挂一次；失败→派生物标记失效 + trace，不静默。

## 7. B6：温层场景卡 + 前缀纪律（WCA Phase 1，前置 B1）

- **温层**：knowledge_plane 增温卡渲染（复用 build_scene_slice，**禁止平行实现**）+ 计划层固定节（spine 意图+锚点+大纲就近一拍——「第四层」落地）；章内冻结（缓存键=章+t+场景钉+spine 版本；刷新点：切章/settle/场景钉变更）。
- **提及逐出前缀**：v3.1 修正——提及命中移到后缀（热层雏形），实体块冻结为进章版本。
- **测试**：prefix byte-equal 对拍（同章连续两次装配，前缀逐字节相等——扩展零变化测试族）。
- **门**：章内稳定验证 + manifest 装配方差下降。

## 8. B7：热层显著性与方向权重拆解（WCA Phase 2）

- **`services/adaptive/salience.py`**：三族信号（文本流/世界/行为）× 段距指数衰减（提及 τ≈3 段、开放环 ∞）+ 六槽配额（≤3 top 显著、≥1 被冷落的重要、≥1 在场沉默者、1 系统事件）；纯代码，参数个位数。
- **影子先行**：算而不注一周，trace 记录热集 vs 实际选中集重叠率。
- **方向权重葬礼**：direction_weights.py 力学模型删除；信号转世（期待张力→世界信号、未兑现伏笔计数→「被冷落」槽、采纳反馈→行为乘子）；dock prompt 权重块替换为热层具名实体提示行；「高权重方向至少占一枚」配额废除。
- **A/B**：热层只开 dock 一条车道；τ 参数此刻才允许调。

## 9. B8：冷层 digest（WCA Phase 3，双门后开工）

- **开工许可**：①B0 manifest「注入未消费率」显示冷知识利用率不足；②双模型对照（同 manifest，mimo vs DeepSeek 各跑一周）证明瓶颈在供给而非模型——**需 DeepSeek key 到位**。
- **结构**：`world_digest_sections`（section_key/text 有界/source_refs/frozen/derived）；事实节纯代码（fold 渲染），综合节 LLM 只输出结构化 ops（ADD/UPDATE/DELETE/NOOP）；预算独立分池（与 auto-read 隔离）。
- **消费顺序**：先 finish/audit（非交互、错了不脏画布）→ 验证 N 章 → 进 stitch（世界观大块整体注入此时降级为 digest 节+按需检索）。
- **Kill criterion**（开工时即存在）：上线 N 章采纳率/canon 合规无可测提升 → 回退 v3.1 全注入，digest 维护停用，沉没成本限于维护调用。

## 10. B9：认知浮现三时机（呈现层，前置 B3/B4 数据）

- 三时机且仅三时机：**泄密疑点**（视角配给证据链）、**反讽机会**（belief 差集——读者知而角色不知）、**负空间清单**（「此刻可揭示的戏剧资本」）。
- UI 纪律检查表进 AGENTS.md；浮现总开关可全关（可见性悖论防线）。

---

## 11. 横切纪律与风险清单

- **每批交付**：代码+测试+文档同步（AGENTS 对应段落+设计文档施工状态标记）+独立提交；`pytest --ignore=backend/_deprecated` 全绿为前置，涉前端跑 vitest。
- **风险**：B2 双读迁移（回退路径已备，往返单测锁）；单模型混杂（假设一——B0.2 的 manifest 让双模型对照随时可开，key 到位即跑）；作者标注负担（金标准 10 断点起步）；可见性悖论（B9 开关）；工作区堆积（B0.1 先清）。
- **明确不在本期**：token 命中实测（用户指令暂缓）、约束编译器（C）、心智镜像呈现（F）、learned significance、反事实分支、概率浮点。

## 12. 需要作者参与/决策的事项

1. **B0.1**：未提交两批的提交划分确认；
2. **B0.3**：金标准标注（先 10-20 断点，每断点约 2 分钟）；
3. **假设一证伪**：DeepSeek key 更换时机（B8 第二道门的前提）；
4. **B4**：通读阶段 C 回填安排在写作空闲期；
5. **B7**：方向权重退役前过目影子数据一周。

里程碑口径：内核 B1-B5 约 9-12 个工作日；WCA B6-B8 约 6-8 天 + 两处一周数据窗；B9 2 天。总计约 4-5 周日历时间（含数据窗与作者参与点）。

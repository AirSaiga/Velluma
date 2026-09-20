> **归档说明（2026-09-19）**：真相层融合设计（C1-C3，已随 2026-08-17/19 各批实施）；现行契约见 `docs/agent/world.md`。

# Canon × 世界页融合设计（信息层并入活舆图）

> 状态：已实施——C1 ✅ 2026-08-17、C2/C3 ✅ 2026-08-19（分期表见 §7，落地差异在各期注记）
> 范围：`frontend/src/features/canon/` → `frontend/src/features/world/` + `backend/routes/canon.py`
> + `backend/services/canon/` + `services/context/settings_bundle.py`
> 前置：`docs/reports/world-unified-settings.md`（M1-M6+ 已全部落地）——其 §8 承诺的
> "CanonNode 与世界实体合并评估，另行设计"即本文档。

---

## 0. 背景与目标

**背景**：世界页统一设定工程（M1-M6+）已把角色/势力/资产/地点/关系/伏笔/期待/世界观
全部收进活舆图，`WorldEntity` 成为实体底座唯一（P2）。但 Canon（作者脑中世界）仍是
平行的图谱体系：独立入口（AppRail「脑图」）、独立页面（CanonView 三 tab）、独立数据
（canon_nodes / canon_edges）、独立 API（/canon）。同一批角色、地点、伏笔被**双重建模**。

**目标**

1. 世界页成为 Canon 的唯一编辑入口（UI 承载融合），AppRail「脑图」与 CanonView 退役
   ——复刻 M5 伏笔先例。
2. 消除双重建模：Canon 的实体类节点（character/place/object）与 hook 节点不再独立存在，
   收敛为挂在世界对象上的**信息面**（真相 vs 读者认知 + 揭示计划）。
3. 生成链路供给不断：`build_canon_context_for_prompt` 的输出格式**冻结不动**，
   只换数据源；泄密检测 / Canon 感知带 / CanonHighlight 零感知。

**非目标**

- 不改 `[private]/[public]/[hook]` 三段 prompt 输出格式（`hard_constraints` 按字符串
  标记切片解析，与之强耦合——格式是冻结契约，见 §6）。
- 不动世界观（worldview 条目集）、期待账本（ReaderMirror）、文风/笔记。
- 不把"读者认知"塞进事件溯源推演（P3 只管客观事态；读者认知是叙事规划数据，
  存信息面/伏笔账本，不入 `computeWorldState`）。
- 不做多时间线/平行世界（沿用既有非目标）。

---

## 1. 概念定位：事态层 × 信息层（两层模型）

融合的立论基础是两个正交维度，而非两块重叠功能：

```
┌─────────────────────────────────────────────────────┐
│ 信息层（Canon，本设计并入）                              │
│   作者真相 canon_text ─ ─ ─ 读者认知 public_text       │
│   差集 = 秘密；揭示计划 = 差集的收敛时刻                  │
│   回答：读者该知道什么 / 什么绝不能写出来                  │
├─────────────────────────────────────────────────────┤
│ 事态层（世界页，已有）                                   │
│   事件溯源 → computeWorldState(t)                     │
│   谁在哪 / 生死 / 疆域 / 关系，随游标推演                │
│   回答：世界里发生了什么 / 现在是什么状态                  │
└─────────────────────────────────────────────────────┘
```

- **事态层**是上帝视角的客观状态机：不关心读者。
- **信息层**是叙事视角的知识边界：不改变世界状态，只标记"真相—读者所见"的差集与
  收敛计划（reveal_plan / expected_reveal_chapter）。
- 同一个对象（角色"兰星"）两层各有facet：事态层有位置/生死/档案；信息层有
  真实身世（private）/ 读者目前认知（public）/ 计划第 45 章揭示。
- **融合 = 给世界页的对象挂信息面**，而不是保留一个平行图谱再维护一遍同一批实体。

---

## 2. 现状盘点与重叠矩阵

### 2.1 Canon 现状（调研结论）

- 数据：`canon_nodes`（5 类节点 + canon_text/public_text 双层 + visibility 三态 +
  reveal_plan）+ `canon_edges`（6 类叙事因果边）。
- UI：`CanonView.vue` 三 tab（图谱/节点列表/悬空伏笔）+ Cytoscape 图谱 + 节点/边编辑弹窗。
- 入口：AppRail「脑图」`/canon/:bookId`；写作台 InspectorPanel「前往 Canon 脑图」跳转。
- 消费链：`build_canon_context_for_prompt`（consistency.py）→ 三段文本 →
  `settings_bundle.canon_context` → adaptive 四模式 prompt / refinery / adf；
  `hard_constraints()` 解析出 `canon_private_labels` / `canon_public_facts` →
  `check_canon_compliance` 泄密检测（finish 审计 + canon_watch 心跳感知带）。
- 休眠能力：一致性检查 / 连锁分析 / 自动提取三 API 后端就绪，CanonView 无入口。
- **伏笔双源**：canon HOOK 节点喂 `[hook]` 段；plot_ledgers 喂章节卡 `foreshadow_ops`
  （`settings_bundle.py:549`）+ RAG 词法评分加分 + 世界页伏笔抽屉/弧线带。两处维护、
  语义重叠、无关联。

### 2.2 重叠矩阵与处置

| Canon 侧 | World 侧 | 重叠 | 处置 |
|---|---|---|---|
| character/object 节点 | world_entities | **完全重复建模** | C2：节点退役，信息面挂实体 |
| place 节点 | world_locations | **完全重复建模** | C2：同上 |
| hook 节点 | plot_ledgers（M5 起世界页唯一编辑源） | **语义重叠 + 双源喂 prompt** | C2：并入伏笔账本 |
| event 节点（叙事单元） | world_events（状态变更） | 概念不同：叙事因果 vs 状态突变 | 保留为自由叙事节点 |
| canon_edges（causes/before/hints/setups/callbacks/echoes） | world_relations（人物关系） | 概念不同：叙事结构 vs 人际态度 | 保留，图谱模态可视化 |
| visibility | WorldEntity.visibility（M2 已吸收，注释明言"从 Canon 吸收"） | 部分重叠；canon 多 partial + 双层文本 | C2：统一进信息面 |
| canon_text / public_text 双层 | 无 | **Canon 独有核心价值** | 信息面的本体 |
| reveal_plan / expected_reveal_chapter | 无 | Canon 独有 | 信息面保留 |
| 一致性检查 / 连锁分析 / 提取 | 无 | Canon 独有服务 | 保留，输入源切换（C3 激活 UI） |
| CanonGraph 图谱 | 脑图透镜已退役（单一画布哲学） | — | 降格为模态（因果图谱查看器） |

### 2.3 双重建模的真实危害（不只是不整洁）

**名字漂移使泄密检测静默失效**：作者在世界页给角色改名 → canon 节点 label 不跟随 →
`canon_private_labels` 与实体真名脱钩 → `check_canon_compliance` 子串匹配漏检。
RAG 实体匹配 / POV 名闸门用的是 world 侧名字，canon 侧是另一套 label，两套账本天然
漂移。这是 C2 必须做的核心理由。

---

## 3. 设计原则

| # | 原则 | 含义 |
|---|------|------|
| K1 | 信息面挂对象，不建平行图谱 | canon 数据的生命周期跟随它描述的世界对象（实体/地点/伏笔），label/ref 单源 |
| K2 | 三分法归类 | 有埋设-回收结构的 → 伏笔账本；持续性秘密 → 实体信息面；纯叙事因果单元 → 自由节点 |
| K3 | prompt 输出格式冻结 | `[private]/[public]/[hook]` 三段 + hard_constraints 解析格式不变，只换装配来源 |
| K4 | 迁移作者确认制 | label 匹配自动迁移 + 逐条确认（migrate-legacy 先例），可撤销，不静默改库 |
| K5 | 图谱是查看器不是编辑画布 | 活舆图单一画布哲学不变；因果图谱降格为模态透镜 |

---

## 4. 目标数据模型（C2 终态）

### 4.1 canon_nodes 改造为「信息面 overlay」

```
canon_nodes 增列：
  ref_type  VARCHAR   -- 'entity' | 'location' | 'ledger' | NULL
  ref_id    UUID      -- 挂接对象 id；NULL = 自由叙事节点
  唯一约束 (book_id, ref_type, ref_id)

规则：
- ref 节点：label/type 由世界对象推演（entity→character/faction/asset、
  location→place、ledger→hook），不再独立维护（根治 §2.3 漂移）；
  原列保留为迁移期快照，读取时 ref 在则覆盖。
- 自由节点：type=event（叙事单元：祖孙相认、真相揭穿——不进 computeWorldState）。
- 信息面字段不变：canon_text / public_text / visibility / reveal_plan /
  expected_reveal_chapter / tags / confidence / source。
- 挂接对象删除 → overlay 级联删除（ON DELETE CASCADE），canon_edges
  端点悬空时整条边清理（迁移脚本 + 外键约束）。
```

### 4.2 HOOK 节点并入 plot_ledgers

伏笔条目**天然就是信息层对象**：埋设 = 建立"表象—真相"差集，回收 = 差集收敛。
canon hook 的字段有明确去处：

| canon hook 字段 | 去处 |
|---|---|
| canon_text / public_text | plot_ledgers 加列 `canon_text` / `public_text`（可空，默认空 = 无双层需求） |
| status（open/resolved/…） | 已有 resolved_in_chapter_id / world_time_resolved 语义覆盖 |
| strength / bury_style / payoff_style | metadata JSONB（非检索字段，不值得加列） |
| reveal_plan / expected_reveal_chapter | plot_ledgers 加列 `reveal_plan`（揭示计划文本）；预期章已有回收锚，不重复建 |
| `[hook]` prompt 段 | 装配源切到 plot_ledgers（open 状态取前 8），输出格式不变（K3） |

**三分法判定**（K2，迁移与新建共用）：

- 「针脚歪斜暗示身世」（有埋设-回收弧）→ **伏笔账本** + 可选 canon_text 真相面；
- 「兰星与老人是失散祖孙」（持续性秘密，无回收结构，可长期不揭）→ **实体信息面**（可两实体各挂一条，边连两节点）；
- 「第 45 章祖孙相认导致老人倒戈」（叙事因果链）→ **自由 event 节点 + canon_edges**。

### 4.3 canon_edges 不动

六类边（causes/before/hints/setups/callbacks/echoes）连接信息层节点（overlay +
自由节点），与 world_relations（人物关系、地图连线）语义分立、各归其位。

### 4.4 API 变更

| 端点 | 变更 |
|------|------|
| `/canon/nodes` CRUD | 增 ref_type/ref_id 参数；创建实体类 canon 条目的正路改为「从世界对象挂接」（C2 起 CanonSection 不再提供裸建实体类节点入口） |
| `/world/migrate-canon`（**新增**） | label 匹配 world 实体/地点/伏笔 → 生成迁移预览（逐条 ✓/✗/改名映射）→ 确认落库；幂等 |
| `/canon/extract`、`/canon/check`、`/canon/impact` | 输入源适配 overlay，签名不变 |

ORM/MIGRATIONS 同步：canon_nodes 加列 + 唯一约束；plot_ledgers 加 canon_text /
public_text / reveal_plan。

---

## 5. 交互设计

> **UX 设计稿**：`docs/design/canon-fusion/`（index 总览 + 三场景稿，沿用 M6 活舆图视觉
> 令牌）。核心交互概念：**表里两面**（表=读者所见/里=作者真相，三态=秘密/半露/公开）、
> **朱点贯穿**（图标栏·舆图名签·账本行·详情面板同一视觉签名）、**句子优先录入**
> （「＋ 记一条真相」写下句子即「里」全文，主语按实体名/别名自动挂接）、
> **图谱降格为透镜**（因果图谱模态只看不编）。术语表里化：canon_text→里、
> public_text→表、private→秘密、partial→半露。
>
> **评审拍板（2026-08-17）**：命名定「真相」；表里三态 chips 直切（不用「表非空推导
> 半露」的隐式规则）；账本角标显**总条数**（与伏笔/期待格一致，秘密数退居抽屉头
> 次级信息）；因果图谱**保留为只读查看器**（只看不编、无常驻入口，不预设退役）。
> 详见设计稿 index §6。

### 5.1 C1：「真相」抽屉（世界页右缘图标栏账本族第四格）

- `SidePanelKey` 加 `'canon'`（WorldView.vue）；图标栏插 `ar-btn`（同心圆 ◉ 图标），角标 = 总条数；抽屉内容委托新组件 `presentation/CanonSection.vue`
  （参考 ForeshadowSection 先例）。
- 抽屉结构：
  - 过滤 chips：**表里三态**（秘密/半露/公开）——主轴不是类型；
  - 列表卡：label + 类型色点 + visibility 徽标 + canon_text 首行摘要
    （private 橙点强调）；点击 → `CanonTruthDetailDrawer`（表里两面就地编辑，
    失焦即存，替代旧 NodeEditModal 弹窗——按 UX 稿 A-2 落地）；
  - 底部：`＋ 记一条真相`（句子优先：一句话即「里」全文，Enter 建条开详情；C1 过渡期
    默认建「叙事」自由节点，主语自动挂接是 C2 能力）+ `查看因果图谱` 按钮开图谱模态；
  - 编辑落库后广播 `velluma:world-refresh`（与伏笔/期待/世界观同契约）。
- 深链：`?panel=canon`（consumeRouteQuery 的 PANEL 集合扩展）。

### 5.2 图谱模态（K5：查看器不是画布）

- 旧 `CanonGraph.vue` 降格迁入 `world/presentation/CausalityGraphModal.vue`（ModalShell 壳），
  Cytoscape 依赖已有；**只看不编**：点节点出信息条（类型/表里/真相摘要/一度邻居 +「打开
  真相条目」跳转编辑），点边看边注（类型/强度/备注）；过滤 chips 全部/只看秘密/只看伏笔。
- 入口：真相抽屉底部按钮；真相详情「关联」区（C2 后实体信息面「因果邻居」亦可跳入聚焦）。

### 5.3 C2：实体详情抽屉的「读者认知」分区

EntityDetailDrawer 加第四分区（档案字段 / 编年史 / 快捷事态之后）：

- 空态："此人尚未入正史"+ `[设为秘密]` `[公开设定]` 两个起始按钮 → 创建 overlay；
- 有 overlay：visibility 切换（M2 卡角徽标迁入本区）+ canon_text / public_text /
  reveal_plan 三行就地编辑（v-autogrow）+ 揭示章号；
- 分区常驻显示但折叠态默认（一眼够，深度可展开——V4.0 双层 UI 原则）。

### 5.4 入口退役（C1 完成时）

- AppRail「脑图」项删除；路由 `/canon/:bookId` 改 redirect → `/world/:bookId?panel=canon`
  （旧深链不断）。
- InspectorPanel `handleEditCanon`（及其转传 RefineryIssuesPanel 的 `@edit-canon`）
  改跳 world 深链；文案「前往 Canon 脑图」→「在世界页查看正史」。

---

## 6. 生成链路契约（冻结声明）

**消费点全景**（改动波及面 = 只允许换源，不允许换格式）：

```
build_canon_context_for_prompt (services/canon/consistency.py)
  ├─ 段1 [private]：作者真相 ≤10 → C2 起来源 = 实体 overlay + 伏笔 canon_text
  ├─ 段2 [public]：已建立事实 ≤10 → 同上
  └─ 段3 [hook]：活跃伏笔 ≤8   → C2 起来源 = plot_ledgers(open)
        ↓ 输出（格式冻结）
settings_bundle.canon_context ──→ adaptive 四模式 / refinery / adf prompt
hard_constraints()
  ├─ _extract_canon_private_labels（正则切 `- 标签：` 行）
  └─ _extract_canon_public_facts
        ↓
canon_checks.check_canon_compliance → finish 审计报告「⚠️ Canon 泄露」
canon_watch（心跳感知）→ PerceptionBand「Canon 感知」带 + __canon_watch__ 缓存
CanonHighlight（编辑器高亮词表 WorkspaceView canonMarkTerms）
```

- **护栏**：C2 落地时补一条往返单测——`build_canon_context_for_prompt` 输出喂
  `hard_constraints` 解析，锁格式（防改源时顺手改了段标记）。
- canon_watch / CanonHighlight 的词表来源在 C2 后自动获得世界侧真名（漂移根治），
  无需改动。

---

## 7. 迁移分期（每期独立可发布）

| 期 | 内容 | 价值验证点 |
|----|------|-----------|
| C1 ✅ 2026-08-17 | 世界页第四格「真相」抽屉（`CanonSection.vue`：表里三态过滤 chips + 行卡 + **句子优先录入**——一句话即「里」全文，Enter 建条开详情，C1 过渡期默认建「叙事」自由节点）；真相详情抽屉（`CanonTruthDetailDrawer.vue`：表/里两面就地编辑失焦即存，「里」朱晕 + 密印 + 泄密警示，揭示计划/章号、标签、钩子字段保留，删除带确认）；因果图谱模态（`CausalityGraphModal.vue`：旧 CanonGraph 降格迁入——只读透镜，全部/只看秘密/只看伏笔过滤，点节点出信息条跳真相详情，点边看边注）；`useCanon` 迁 `world/composables`（ensureLoaded 幂等 + CRUD 后广播 world-refresh；术语表里化：private→秘密/partial→半露/hook→钩子）；`?panel=canon` 深链；AppRail「脑图」项删除、`/canon/:bookId` redirect 世界页、InspectorPanel 跳转改深链（「在世界页查看真相」）；`features/canon/` 整目录删除。**后端零改动**，canon.py/canonApi 复用。 | 世界页真相抽屉打开率 / 旧入口残余访问 |
| C2 ✅ 2026-08-19（数据收敛：信息面 overlay + 伏笔统一） | canon_nodes 加 ref_type/ref_id + 唯一约束；实体类节点退役（EntityDetailDrawer「读者认知」分区为唯一创建口）；HOOK 并入 plot_ledgers（加 canon_text/public_text/reveal_plan 列，strength/bury_style 进 metadata）；`/world/migrate-canon` 一键迁移（label 匹配 + 作者逐条确认，幂等可撤销）；`build_canon_context_for_prompt` 换源（格式冻结 + 往返单测）；实体类裸建入口从 CanonSection 移除。**落地差异**（hb0d8e0 + 04662a7）：唯一性走**应用层幂等护栏**（create 时同世界对象既有 overlay 直接返回）而非 DB 约束——无单一外键因三目标，清理同样在应用层（世界对象删除→overlay 级联清理 entity/location/ledger 三处）；label/type 读取时由世界对象推演（根治名字漂移→泄密漏检）；迁移端点预览/确认两相 + decisions 逐条覆盖建议（合并守卫：账本非空字段不回填）；往返契约单测 `services/canon/test_context_contract.py` 锁三段格式。 | 迁移完成书的泄密检测命中率 / 世界页实体改名后 canon 词表是否跟随 |
| C3 ✅ 2026-08-19（能力激活） | 一致性检查 / 连锁分析接进抽屉 UI（现休眠 API）；canon 提取候选并入世界页「待确认」收件箱（正史徽标，与 event_scout 候选同池）；揭示章投影到时间轴章节锚刻度（reveal_plan 可视化）；EntityDetailDrawer「因果邻居」跳图谱聚焦。**落地情况**（9f3359e）：①连锁分析（`/canon/impact`）+「查片段」（贴正文对照真相账本查泄露/矛盾）进真相详情抽屉；②`POST /canon/extract-to-inbox`（最新有正文章节→候选入池 source=canon_extract，同 label pending 幂等跳过；红线：绝不直接进 Canon）+ accept 分流建 tentative 真相节点（前端待确认行正史徽标）；③时间轴章节锚刻度朱点 + canon_watch 心跳 reveal-due（expected_reveal_chapter 距本章 ≤2 章，纯算法）。「因果邻居」跳图谱聚焦未随批落地（图谱模态已只读降格承接总览）。 | 一致性提醒是否被采纳 |

依赖顺序：C1 独立；C2 依赖 C1（编辑入口先就位再动数据）；C3 各项相互独立可拆。

---

## 8. 风险与对策

| 风险 | 对策 |
|------|------|
| C2 迁移 label 匹配错配（同名实体/别名） | 作者确认制预览（K4）；匹配含 aliases；不匹配项保留为自由节点不强行挂接 |
| hard_constraints 字符串解析被无意破坏 | 格式冻结（K3）+ 往返单测锁契约 |
| canon_edges 端点悬空（挂接对象被删） | overlay CASCADE 删；边清理进迁移脚本；图谱渲染对悬空边容错跳过 |
| C1→C2 间储期：用户仍可裸建实体类节点 | C1 保全现状（诚实迁移不降级）；C2 移除入口 + 迁移收编存量 |
| 伏笔账本字段膨胀（canon 面挤占） | 双层文本可空、默认折叠，无 canon 需求的伏笔形态不变（存量大数） |
| 图谱模态大图性能 | 沿用既有过滤 + Cytoscape 局部展开；>200 节点按类型/势力过滤（world-unified-settings §7 同款对策） |

---

## 9. 与现有系统的边界确认

- **世界观（worldview 条目集）**：不动。与信息层互补（世界观=世界的规则背景，
  canon=具体对象的真相边界），融合不合并。
- **期待账本（ReaderMirror）**：不动。期待是"读者情绪侧"推断账本，canon 是
  "作者真相侧"规划账本；两者经伏笔/揭示计划天然衔接，无需建表关联。
- **canon_checks / canon_watch / CanonHighlight**：C1 零感知；C2 仅数据源切换。
- **world_relations**：不动（人际关系，与叙事因果边分立）。
- **文风 / 笔记 / 应用设置**：沿用既有非目标，不进世界页。

---

## 附：2026-09-03 UX 人话化重修（设计稿 `docs/design/truth-ux/`）

表面重修，非架构变更——本文档的数据与分期设计全部保持有效。要点：

- **因果图谱模态退役**：C1 拍板「保留为只读查看器」的隐含假设是边会由提取流程产生；
  该假设被证伪（前端 `createEdge` 零调用方、候选转正只建节点不建边、后端无自动推边），
  图谱永远只能渲染孤立圆点。组件删除、cytoscape 依赖同卸；**后端边表、边 CRUD 路由
  与 `/impact` 保留**，存量数据零风险，未来若有自动推边能力可复活。
- **连锁分析随图谱退役**（沿边扩散，边恒为零则恒答「没有波及」）。
- **真相详情抽屉两问重排**：「读者现在知道吗？」（三态 + 表/里两卡，表/里退居角标）
  /「打算怎么抖出来？」（怎么揭 + 第几章揭，填章号即显示「写到第 N−2 章写作台会提醒你」
  ——把 canon_watch ≤2 章提醒规则显性化）。
- **「钩子」字段区退役**：与伏笔账本重复（C2 既定方向落地）；存量 hook 条目在详情
  显示迁移指引行，走既有「旧条目挂接到世界对象」面板并入伏笔账本。
- **已挂接条目类型只读**：类型随挂接对象推演，自由叙事条目保留可改。
- **文案对照全表与待拍板记录**见 `docs/design/truth-ux/index.html` §05/§07。

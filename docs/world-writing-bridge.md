# 世界沙盘 → 写作现场桥接设计（World Writing Bridge）

> 状态：设计稿（2026-08-16 已对照代码逐项验证，修正见 §11 验证附录；剩余拍板见 §10）
> 范围：`frontend/src/features/workspace/`（写作页）+ `frontend/src/features/world/`（沙盘）+ `backend/routes/world.py` + `backend/services/context/` + adaptive 沉淀链路
> 前置文档：`docs/world-unified-settings.md`（事件溯源底座、单一画布收敛、生成侧桥接）
> 一句话：**沙盘一寸不动，把它的价值半径延伸到笔尖旁边。**

---

## 0. 目标与非目标

**目标**

1. 写作时世界的价值**送货上门**：作者不切页就能看到「此刻此地」的世界切片（谁在场/在哪/生死/头顶悬着什么伏笔）。
2. 写作中世界的录入**顺手完成**：一句话速记、写后确认回流，录入成本从「填表单」降到「三秒动作」。
3. 写作产出的世界事实**流回沙盘**：正文里写出的移动/生死/新地点以候选形态进收件箱，作者确认即入账——世界随写作生长。
4. **作者看到的 = AI 看到的**：写作页切片、沙盘回放、生成上下文三处消费同一份数据契约。

**非目标**

- 写作页**不做任何空间编辑**（拖 marker / 圈疆域 / 摆底图 / 档案编辑）——那是沙盘的活，一律深链跳转。
- 本期不改生成侧 prompt 消费格式（`settings_bundle` 结构不动；W5 距离层只加不替换）。
- 不做实时推送式同步（版本号轮询足够，设定数据秒级滞后无伤害）。
- 不做多时间线/平行世界；期待账本弧线带仍按前置文档暂缓。
- Canon / 旧表冻结节奏不受本期影响。

---

## 1. 设计原则（不可妥协项）

| # | 原则 | 含义 |
|---|------|------|
| P1 | 沙盘唯一 | 空间语义编辑只在世界页发生；写作页出现画布 = 设计失败 |
| P2 | 切片即契约 | 写作页切片条 / 世界页游标回放 / 生成上下文，三处同源：同一时刻解析、同一条推演链、同一份输出 |
| P3 | 三秒动作 | 写作页所有世界交互必须三秒内完成（看一眼 / 点一下 / 写一句话），做不到的就该深链回沙盘 |
| P4 | 写入两条路 | 事实入账只有：①作者直接录入（速记也须预填确认）②作者确认的 AI 候选。第三条例外不存在，AI 永不静默入账 |
| P5 | 撤销安全感 | 写作页轻录入全部可撤，且撤销有可见反馈（toast 写明撤了什么），不盲撤 |
| P6 | 保鲜不打扰 | 双页并存靠版本号被动同步：静默刷新 + 红点提示，永不弹窗打断心流 |

---

## 2. 总体架构：一个沙盘，两个现场

```
                 ┌──────────────── 事件账本（唯一事实源）────────────────┐
                 │   world_events（append-only） + 候选暂存（隔离）        │
                 └──────▲───────────────────────────┬───────────────────┘
                        │ 写入两条路                  │ 推演（同源 fold）
        ┌───────────────┴───────────┐               ▼
        │ ① 作者录入                 │        切片服务（章节→时刻→切片）
        │   沙盘全手势 / 写作页速记    │               │
        │ ② AI 候选 → 作者确认转正    │     ┌─────────┼──────────┐
        └───────────────────────────┘     ▼         ▼          ▼
                                     世界页回放  写作页切片条  生成上下文
                                     （游标）   （本章时刻）  （bundle）
```

**分工矩阵**

| 动作 | 世界页（沙盘） | 写作页（现场） |
|------|---------------|---------------|
| 看此刻谁在哪 | 游标回放（全局宏观） | **切片条（本章时刻）** |
| 查某人/某地底细 | 详情抽屉 | **情境浮卡** |
| 录一条事件 | 全部手势（拖拽/圈绘/表单/批量） | **速记框（一句话）** |
| 确认 AI 回流 | 收件箱全貌（跨章） | **章末轻确认** |
| 改本章叙事时刻 | 时间轴右键 | **切片条顶部**（双入口） |
| 空间编辑（摆位/疆域/底图/档案） | **唯一主场** | 永不做，深链跳转 |

---

## 3. 交互层设计（写作页四层，按侵入性从轻到重）

### 3.1 第 1 层：常驻切片条（被动价值，零操作）

写作页右侧 Inspector 区内新增「此刻此地」分区（**落地即替换现有 SceneSettingsPanel**——同位置升级避免两个在场列表打架；其「未用世界页」迁移引导空态由切片条继承）：

```
┌─────────────────────────┐
│ 此刻此地 · 第5年3月 〔改〕  │  ← 本章叙事时刻，可改（双入口之一）
│ 在场                     │
│  ● 林尘  北岸要塞·在途2日  │
│  ● 白霆  王都·驻留        │
│  ○ 流光  已死亡（灰显）     │
│ 脚下                     │
│  北岸要塞 · 统合局控制区    │
│ 头顶的线                  │
│  ◇ 伏笔「红月的秘密」悬空15章 │
│  ◇ 期待「身世揭示」张力8     │
├─────────────────────────┤
│ ◉ 本章带来 3 处世界变化 →   │  ← 回流收件箱徽标（见 3.3）
└─────────────────────────┘
```

规则：每块截断（在场 ≤6、伏笔/期待各 ≤2，超出「更多 »」跳沙盘）；折叠状态记忆（照 useUiPrefs 现成模式加一个字段）；**永远不需要点击**。

> ⚠ 验证修正：Inspector 并非常驻右栏，而是**默认收起的 hover 覆盖抽屉**（`rightDrawerOpen` 默认 false，WorkspaceView:941-947）——「设定 tab 内升级」与「常驻零点击」互斥，形态拍板见 §10.1。

「脚下」场景地点的判定顺序：本章叙事时刻区间内最新 move/事件地点 → 在场主角位置 → 无则整块隐藏（不造数据）。

### 3.2 第 2 层：情境浮卡（主动查询，三秒动作）

触发：选中正文人名/地名，或点击 @/# 提及。两种卡：

- **角色卡**：此刻在哪 · 生死 · 一句话档案 · 最近三条编年史（时间倒序）· 距当前场景（W5 距离层就位后显示）
- **地点卡**：所属区域 · 控制方 · 此地最近三条事件 · 距上一场景（W5）

卡底固定两动作：**「在世界页打开」**（深链，飞到该对象 + 游标停本章时刻）｜**「记一笔」**（唤起速记框）。

> 接线（已验证）：选区侧可白拿现成设施——RichTextEditor 的选区浮层管线（600ms 防抖 + coordsAtPos 定位 + 外点关闭，:383-454）与 `entity-focus-change` 事件已贯通至 WorkspaceView；提及点击则是全新接线（charMention/assetMention 现无 NodeView、无任何点击处理），W2 用 `editorProps.handleClick` 命中 mention 节点实现，成本最小。

### 3.3 第 3 层：轻录入三件

1. **速记框**（快捷键 / 浮卡「记一笔」唤起）：一行自然语言——「林尘带红月连夜离开王都」→ 后端解析 → **预填轻表单**（类型/参与者/地点/时刻=本章锚）→ 作者过目确认入账。解析失败降级为空草稿表单，绝不直写库。
2. **回流收件箱**：完稿/沉淀后角落出现「本章带来 N 处世界变化」，点开逐条 ✓/✗（例：「林尘 抵达 北岸要塞 · 第5年3月」）。✓ 即转正入账，切片条即刻刷新。
3. **本章时刻标记**：切片条顶部时刻直接可改——叙事锚决定切片内容，是写作页与世界之间最重要的螺丝，必须触手可及。

### 3.4 第 4 层：跳链协议（重操作的唯一出口）

- 去程：`/world/:bookId?entity=<id>&time=<t>&from=chapter&chapter=<id>`——沙盘飞到该对象、游标停在该时刻；
- 返程：世界页页头出现「← 返回本章」（仅 `from=chapter` 时显示），回到写作页时切片条已自动刷新；
- 兼容既有 `?entity=` 深链（WorldRedirectCard）；`time/from/chapter` 均为全新消费逻辑（WorldView `consumeRouteQuery` 现只处理 `entity`），但 `useWorld.setCurrentTime` 已导出，去程跳时刻一行即通；返程必须显式带 chapterId（workspace 路由 `/workspace/:bookId/:chapterId?`），否则落回 store 记住的当前章。

### 3.5 手势与入口总表（写作页新增）

| 数据/动作 | 入口 | 类型 | 落地方式 |
|-----------|------|------|----------|
| 看切片 | 常驻 | 被动 | 零操作 |
| 查底细 | 选中文本 / 点提及 | 免模式 | 浮卡 |
| 记事件 | 快捷键 / 浮卡 | 模式化（单表单，Esc 退出） | 解析预填 → 确认入账 |
| 确认回流 | 角落徽标 | 免模式 | ✓/✗ |
| 改本章时刻 | 切片条顶部 | 免模式 | 直接落，可改 |
| 空间编辑 | 「在世界页打开」 | 跳链 | 沙盘中进行 |

---

## 4. 数据契约与后端逻辑

### 4.1 切片服务（本期核心新端点）

`GET /api/books/{book_id}/world/scene-slice?chapter_id=`

```jsonc
{
  "t": 1887,                    // 解析出的叙事时刻
  "t_source": "chapter_anchor", // chapter_anchor | prev_anchor | max_event | zero
  "presence": [ { "entity_id": "…", "name": "林尘", "alive": true,
                  "location_name": "北岸要塞", "label": "在途（进度 40%）",
                  "importance": 8, "visibility": "public",
                  "presence_source": null } ],  // "lexical"=位置从事件 note 词法推断（见下）
  "scene": { "location_id": "…", "name": "北岸要塞", "controlling_faction": "统合局" }, // 控制方可空，见下
  "foreshadows": [ { "ledger_key": "…", "content": "红月的秘密", "chapters_open": 15 } ],
  "expectations": [ { "type": "mystery", "description": "身世揭示", "tension": 8 } ],
  "version": { "events": 42, "updated_at": "…" }
}
```

- 时刻解析复用 `resolve_narrative_time` 四级降级（W1 已扩为 `NarrativeTime(t, source)` 并同步调用方）；状态复用 `compute_world_state`——**与生成桥接同源是硬约束**（P2）。
- **在场推导的词法兜底（2026-09-02 约束治理一期，`services/world/lexical_presence.py`）**：结构化参与者链接缺失的实体，若名字出现在事件 note 正文中则补进在场、标 `presence_source=lexical`（前端渲染「据正文推断」badge，兼作补录事件参与者的建议通道；情境浮卡的角色状态行同带该字段）；增强内建在 `compute_world_state` 仓库实现——切片条/浮卡/生成桥接同一口径；死者不复活、歧义不填、不回写事实源；存量可用 `scripts/backfill_event_participants.py` 回填。
- **伏笔关联规则（验证后重写）**：PlotLedger **没有**实体/地点关联字段，硬交集不可算。降级为——基线取全书开放伏笔（`get_open_hooks` 现成；status 取值 open/closed/dropped），在场实体名/别名子串命中的提权排前（复用 recall `_world_echoes` 的匹配手法），本章新埋（`chapter_id` = 当前章）必进；`chapters_open = 当前章号 − created_at_chapter`（⚠ 该列存的是**章节号 Integer**，非章节 id）。
- `controlling_faction` 判定：地点有坐标 → 对 territory_states 各 polygon 做点包含（射线法自写，仓库无 shapely 无现成工具）；无坐标（迁移来的地点恒为空）或多命中 → 该子块隐藏，不造数据。
- 期待块对齐 `reader_mirror` 实际结构：`raw["expectations"]` 过滤 `status ∈ (setup, accumulating)`，字段为 `type/description/current_tension`（与 settings_bundle `_reader_expectations_view` 同源，原稿的 `content` 字段名有误）。
- 单端点聚合返回，写作页**不重复**世界页的 8 连请求模式。
- 世界无实体 / 章节无锚时各块优雅缺席（返回空数组 + t_source 标明降级级别），前端按块隐藏。

### 4.2 保鲜：版本号 + 三时机比对

- `version` 随切片返回：events 计数 + events/entities/locations/relations 四表聚合 `max(updated_at)`（四表均有时间戳列，已验证）；计数兜底「删除不 bump updated_at」的盲区；
- **adaptive 心跳响应附带 `world_version`**——接线点已验证：heartbeat 路由签名里的 `db` 参数现成闲置，聚合查询在路由层做即可，不动 orchestrator；
- ⚠ 心跳受三重门控（assistEnabled 关闭即停 / 非 composing 不发 / 幽灵在屏不发），纯手写与阅读态**没有心跳**——「窗口重新聚焦重取」因此是硬性兜底而非可选优化。比对时机：进入章节 / 心跳响应携带版本 / 窗口重新聚焦；版本变化 → 静默重取切片 + 红点「世界有更新」；
- 叙事锚变更（无论改自时间轴右键还是切片条）→ 两个现场即时跟随。

### 4.3 速记解析端点

`POST /api/books/{book_id}/world/parse-event` `{ chapter_id, text }` →

```jsonc
{ "draft": { "event_type": "move", "time_start": 1887,
             "participant_ids": ["…"], "location_id": "…", "note": "…" },
  "confidence": "high" }
```

- 小预算 + REASONING_DISABLED；输出对齐 `eventTemplates` 结构；实体/地点按名与别名模糊命中，命不中留空让作者手选；
- **契约红线：此端点只产草稿，绝不写库**；入账走既有事件创建（支持指定 id，undo/redo 幂等体系不变）；
- 解析失败/低置信 → 返回空草稿，前端降级为普通轻表单。
- **关联式录入扩容（2026-09-05 P1，未提交批内）**：`chapter_id` 可空——世界页速记入口缺省书级此刻（最大章锚→事件最远处→0）；响应新增 `new_entities`/`new_locations`（速记里名单外的名字草拟：`{name, kind?, evidence}`，`evidence` 为速记原文逐字子串且过后端硬闸校验）与既有实体 `aliases`（速记口述原词自动回填，供 RAG 检索/名单匹配共用）——仍只产草稿，作者过目才建档，红线不变。

### 4.4 候选事件：隔离暂存，转正才入账

新表 `world_event_candidates`：

```
id, book_id, chapter_id
draft      JSONB   -- 结构化事件草稿（同 parse-event 输出形状）
source     settle | finish
status     pending | accepted | rejected
created_at
```

- **与事件账本物理隔离**：候选不参与推演、不进正常图层、不影响 version 主计数——账本零污染风险；
- 确认 = 创建真事件（正常分配回放序号）+ status→accepted；丢弃 = status→rejected（保留痕迹供回溯，不进任何视图）；
- **保质期**：超过三章未处置的候选在前端排序沉底，不删除、不骚扰；
- 建表（已验证）：加进 `models.py` 即由 `create_all` 建表（database.py 的显式导入列表是文档性惯例非闸门，W4 落地时顺手补上 WorldRelation 的既有遗漏）；列写法照 WorldRelation（UUID 主键 / CASCADE / 时间戳）+ 照 PlotLedger 加 status CheckConstraint（pending/accepted/rejected），`(book_id, status)` 建索引；
- 世界页侧栏加「待确认」分区（跨章全貌），写作页收件箱只管本章——两处操作同一状态机。

### 4.5 抽取扩展（回流的生产端）

- settle / finish 的沉淀链路在现有实体抽取之外，增**候选事件抽取**（move/birth/death/battle/found 等结构化类型），时刻一律锚 `resolve_narrative_time(本章)`；
- 结构（验证后定案，原待拍板 3 关闭）：做**独立 adaptive 组件**（`services/adaptive/components/` 新文件，契约 `run(chapter_id, db, snapshot, budget, **kw)`，orchestrator 注册；prompt 进 `services/prompts/`），不与 settle 的实体抽取合并 prompt——现有先例 `extract_emergent_facts`（bsadf/memory_ingestion.py:61-96）已示范「LLM 解析不落库、落库独立步」的分层，候选抽取复刻该哲学（REASONING_DISABLED + 小 max_tokens + `parse_json_safe` 容错 + 失败返空）；
- 沿用既有哲学：冲突检测照跑；抽取不到 = 没有候选，宁缺勿滥。

### 4.6 撤回语义（跨页一致）

- 速记入账 / 候选确认 → 撤销胶囊 5 秒内可撤（撤销 = 删除该事件 + 候选回 pending），文案写明撤的是什么（P5）。⚠ 验证修正：现有 useToast 无动作按钮能力——撤销 UI 仿 `AutoCutHint` 自管胶囊模式（WorkspaceView 已有先例），不动通用 Toast 组件；
- 世界页既有 undo 栈体系不动；写作页轻录入不进该栈，用 toast 撤销即够（动作粒度小、即时）。

### 4.7 读者视角（W5）

切片与世界页加 `visibility` 过滤档：纯计算时过滤，不存第二份数据。用途：作者自检揭示节奏（防泄底），远期可演进为读者分享版地图。

---

## 5. 生成侧影响（本期刻意克制）

- `settings_bundle` 结构与消费格式**不变**——world 优先桥接已接通，切片服务与其共用时刻解析与推演即保证 P2；
- W5 距离层成熟后再议 `spatial_brief` 上下文块（新增块，不替换任何现有块，先观察再收口）；
- 候选事件→走向卡/方向权重的桥接（相遇提醒）列入 W5，与前置文档 §5 遗留方向合并设计。

---

## 6. 分期落地（每期独立可发布）

| 期 | 内容 | 价值验证点 |
|----|------|-----------|
| **W1 切片上桌** ✅ 2026-08-16 | scene-slice 端点（`services/world/scene_slice.py`）+ 写作页切片条 `WorldSceneSlice.vue`（在场/脚下/头顶的线/时刻可改 + 清除锚）+ useWorldSlice 三时机保鲜（章节切换 / velluma:world-version 心跳事件 / 窗口聚焦）+ HeartbeatResponse.world_version（路由层闲置 db 计算）；`resolve_narrative_time` 扩为 `NarrativeTime(t, source)` 并同步 3 处调用方；SceneSettingsPanel 已删除。**形态落 §10.1 推荐 (a)**：Inspector「设定」tab 内替换（2026-08-17 写作台重构后，副驾收敛为此刻/章节/审校三 tab，切片条迁至「此刻」tab） | 切片条 7 日展开率；作者是否主动扫视 |
| **W2 查询闭环** ✅ 2026-08-16 | 情境浮卡 `WorldContextCard.vue`（角色卡：状态/编年史 ≤t 防剧透；地点卡：控制方/此地事件）+ `GET /world/context-card`（名字/别名/实体 id 解析，404 静默缺席）+ 提及点击接线（RichTextEditor `handleClick` 命中 charMention/assetMention，此前无 NodeView 无点击处理的证伪项落地）+ 选区浮卡（1-12 字经 `entity-focus-change` 载荷扩展贯通）+ 深链去程（`?entity/&loc/&time/&from=chapter&chapter=`）+ 世界页「返回本章」+ 切片条在场行点击跳转。「记一笔」入口留给 W3 | 浮卡打开频率；跳链往返完成率 |
| **W3 速记入账** ✅ 2026-08-16 | `POST /world/parse-event`（`services/world/event_parser.py`，解析/落库分离红线）+ 速记框 `QuickEventNote.vue`（Alt+N 捕获阶段注册，Alt+O 同款门控；浮卡「记一笔」经 velluma:quick-note 预填实体名）→ 预填轻表单（类型/参与者 chips/地点/时刻历法预览/备注）→ 入账走既有 createEvent → 自管撤销胶囊 6s（Toast 无动作按钮的验证修正落地）；速查表补 Alt+N 条目 | 事件录入中速记占比；解析草稿采纳率 |
| **W4 候选回流** ✅ 2026-08-16 | 新表 `world_event_candidates`（models + create_all；database.py 显式导入列表顺手补 WorldRelation 遗漏）+ 独立组件 `services/world/event_scout.py`（orchestrator 注册，settle 带段落/finish 整章各触发一次，幂等去重，REASONING_DISABLED）+ prompt `prompts/world_event_prompts.py` + 四端点（list/accept/reject/reopen；accept 按类型补 payload 保证推演回放正确）+ 写作页收件箱（切片条「本章变化」✓/✗ + 撤销胶囊=删事件+reopen）+ 世界页侧栏「待确认」跨章分区 + settle/finish 经 velluma:world-refresh 静默刷新 | 回流确认率（✓占✓+✗）；新书 7 日首事件率（核心激活指标） |
| **W5 切片加厚** ◐ 2026-08-16（lite 落地，重件缓行） | ✅ 本章场景钉（`chapters.scene_location_id` + MIGRATIONS + 切片「脚下」钉住/取消，钉定优先于推演）；✅ 读者视角滤镜（切片条开关，隐藏 private 实体与作者层伏笔，UiPrefs 记忆）；✅ 同地相遇提示（切片 encounters：t 时刻同地点存活角色组，纯计算零 LLM）。⏸ 缓行项及理由：比例尺校准与距离/旅程常识→spatial_brief（需要标定交互与单位设计，且无标定时无法诚实给数）；相遇→走向卡/方向权重桥（等切片数据密度验证后与 §5 遗留方向合并设计）；世界页全图读者滤镜（先验证切片条档位的使用率再扩） | 续写空间硬伤抽检下降；走向卡里地图来源建议的采纳率 |

排序逻辑（产品死穴是「录入先于价值」）：**先让价值可见（W1-W2）→ 再让录入变懒（W3-W4）→ 最后让启发生长（W5）**。

> **W4 后续演进（本表登记 2026-08-16 之后，行为已多轮升级）**：
> ① **P5 地基加固（2026-08-21，`e44dd59`，详见 `foundation-hardening.md` A5b）**——收件箱**批量裁决**（「全部采纳」→ 逐条预览可剔除 → 6s 复合撤销 = 删产物 + reopen，前端 `features/world/composables/batchAccept.ts` + `BatchAcceptModal.vue`）；settle 候选**三重去重**（prompt 排除近 15 条已入账 + 归一化双向子串预筛 + pending 池幂等）；积压 >5 心跳 `kind=world_inbox` 感知带提示 + settle 完成 toast 直达收件箱。
> ② **战略定稿期（2026-08-25/26，详见 `auto-read-quiet-learning.md`）**——自动阅读 / 全书通读的候选入池（新 source）；候选判重升**全书级**归一化子串 + 转正前账本判重闸（命中标 `auto_reject=duplicate`）；accept 服务端实体/地点创建按（书 + 归一化名 + 类型）**幂等**（治连点重复建事故）；候选联表补 `chapter_number`（无叙事锚显示「第 N 章」不伪造默认日期）。
> ③ 收件箱随切片条位于副驾「此刻」tab（2026-08-17 写作台重构迁入切片条所在 tab，2026-08-22 副驾四 tab 化后沿用，组件仍为 `WorldSceneSlice`）；世界页「待确认」图标栏改为**常驻**（空箱也可开抽屉发起通读，2026-08-25 `28c8e73` 修冷启动自锁）。

---

## 7. 风险与对策

| 风险 | 对策 |
|------|------|
| 双页数据漂移（沙盘改了，写作页旧了） | P2 同源切片 + 版本号三时机比对；叙事锚变更双向即时跟随 |
| LLM 速记解析错误入账污染账本 | 红线：只产草稿，作者确认才入账；低置信降级表单；toast 可撤 |
| 候选回流噪音轰炸 | 账本物理隔离 + 三章沉底 + 按章聚合 + 上限截断 |
| 切片条信息过载 | 每块硬性截断 + 折叠记忆 + 缺数据按块隐藏（不显示空壳） |
| 写作页性能（心跳已密） | version 比对搭心跳便车零新增请求；切片仅版本变化时重取 |
| 两个在场列表并存割裂 | W1 落地即替换 SceneSettingsPanel，不留旧面板 |
| 作者不信任「AI 看到了什么」 | 远期可在切片条加「AI 视角」预览档（复用同一切片），本期靠 P2 同源承诺 |

---

## 8. 与现有系统的边界确认

- **世界页本体**：手势体系、undo 栈、底图编辑、时间轴全部不动；新增仅「待确认」分区、「返回本章」页头、深链参数。
- **SceneSettingsPanel**：W1 起被切片条替换（同位置升级）。
- **entity-mention（@/#）**：建议/创建逻辑不动；浮卡作为其点按后的新展示层。
- **生成上下文**：bundle 不变；scene-slice 与其共享时刻解析与推演纯函数，不复制逻辑。
- **Canon / 期待账本 / 旧表**：均不在本期范围；伏笔数据仍读写 PlotLedger 共享表。
- **BS-ADF 弃置节奏**：不受影响；候选事件思想（作者裁决闸门）与 adaptive 路线一致。

---

## 9. 衡量指标（怎么知道改对了）

1. **激活**：新书 7 日内产生第一条事件的比例（W4 后应显著上升——回流把录入成本打掉了）；
2. **在场**：切片条 7 日展开率、浮卡日均打开次数（价值兑现是否发生）；
3. **来源**：事件入账中「速记 + 回流确认」占比 vs 传统表单占比（录入是否真的变懒了）；
4. **留存**：世界数据密度高的书，章节产出稳定性与续写采纳率是否更高（终极问题：世界到底帮没帮到写作本身）。

---

## 10. 待拍板事项

1. ~~切片条形态~~ **已定案（W1 实施取 (a)）**：落 Inspector「设定」tab 替换 SceneSettingsPanel 已上线；2026-08-17 写作台重构后副驾收敛为三 tab，切片条现位于「此刻」tab（下述「tab 复位为规划」的取舍记录基于旧七 tab 结构，仅存档）。是否升级 (b) editor-host 常驻列仍待真实使用数据。
2. ~~本章场景钉~~ **已定案**：随 W5-lite 落地（`chapters.scene_location_id`，钉定优先于推演）。
3. ~~候选抽取的 LLM 调用安排~~ **已定案（验证后）**：独立组件 + 独立小调用，复刻 `extract_emergent_facts` 的解析/落库分离——见 §4.5。

---

## 11. 验证附录（2026-08-16 对照代码逐项核对；行号为当时快照——此后 useGenerationSession 已减至 2426 行、SceneSettingsPanel 所在 tab 结构已重构为三 tab、bsadf/memory_ingestion 已迁 `backend/_deprecated/bsadf/`，本节仅作实施过程记录）

**证实的关键假设**

- 四张 world 表（events/entities/locations/relations）均有 created_at/updated_at，version 聚合可算（models.py:1306-1307 等）；但 repo 无现成 count 聚合，需新写一条（照 `next_sequence_num` 的 `func.max` 写法）。
- heartbeat 路由的 `db` 参数现成闲置（adaptive.py:130），world_version 在路由层计算零侵入；HeartbeatResponse 定义在 adaptive.py:91-102，加字段无障碍。
- settle/finish 无 response_model（返回 dict），追加字段无 schema 障碍。
- territory_states.polygon 为 `[[x,y],...]` 点数组（world_repository.py:335-347；schemas/world.py:214-217）——控制方判定原料齐备，仅缺 PIP 函数。
- reader_mirror 期待结构：`expectations[].{type,description,status,current_tension}`（schemas/reader_mirror.py:59-86）；settings_bundle `_reader_expectations_view`（:174-197）的过滤排序姿势可直接复用。
- 新表加进 models.py 即由 create_all 建表（走 Base.metadata；database.py:723-729 显式导入列表是文档性惯例非闸门）。
- parse-event 有同构先例 `extract_emergent_facts`（bsadf/memory_ingestion.py:61-96）：解析不落库、落库独立步、REASONING_DISABLED + parse_json_safe 容错、失败返空。
- 前端：SceneSettingsPanel 全仓唯一消费方是 InspectorPanel「设定」tab（InspectorPanel.vue:609）；心跳为 HTTP POST（adaptive.api.ts:115-131），响应处理在 useAdaptiveAssist.ts:133-168；RichTextEditor 选区浮层管线（:383-454，防抖/定位/关层全套）与 `entity-focus-change` 事件贯通至 WorkspaceView；`useWorld.setCurrentTime` 已导出（useWorld.ts:597-599）；折叠记忆照 useUiPrefs 加字段三行接入；快捷键照 Alt+O 的捕获阶段注册模式（useGenerationSession.ts:3027/:3254）；收件箱状态挂 useAdaptiveAssist 的 settle/finish 成功块（:256-266/:426-429）。

**证伪 / 修正项（均已回写上文各节）**

- PlotLedger 无实体/地点关联字段，「伏笔 ∩ 在场」硬交集不可算 → 降级为提权排序；`created_at_chapter` 存章节号 Integer 而非章节 id（§4.1）。
- Inspector 为默认收起的 hover 覆盖抽屉 →「tab 内升级」与「常驻零点击」互斥（§3.1 / §10.1）。
- 心跳三重门控（assistEnabled / composing / ghost 在屏）→ 聚焦重取升为硬性兜底（§4.2）。
- charMention/assetMention 无 NodeView、无点击处理 →「点击提及」是全新接线而非复用（§3.2）。
- useToast 无动作按钮能力 → 撤销 UI 改自管胶囊（§4.6）。
- 深链 `time/from/chapter` 在 WorldView `consumeRouteQuery`（:416-419）零实现，返程须显式带 chapterId（§3.4）。
- 仓库无 point-in-polygon 工具（无 shapely），且迁移地点坐标恒空 → controlling_faction 需自写射线法 + 无坐标即隐藏（§4.1）。

**顺带发现（不属本期，记录备查）**

- `plot_ledger_repository.py:87` 引用不存在的 status 值 `"addressed"`（死代码分支）。
- database.py 显式导入列表漏 WorldRelation（表照建，纯文档性遗漏，建新表时顺手补）。

---

## 12. 测试与修复归档（2026-08-16，任务收官记录）

**GUI 测试轮**（依据 `docs/world-writing-bridge-test.md`，真实键盘/鼠标黑盒）：执行 54 项 + 复跑 13 项受阻用例，发现缺陷 5 项（含 2 项存量）——全部修复并经 GUI 复测通过。

| # | 缺陷 | 根因 | 修复 |
|---|------|------|------|
| 1 | 场景钉点击无反馈 + 章节列表 500 | 响应模型 `scene_location_id` 声明 `Optional[str]`，ORM 返回 UUID → 序列化失败 | `schemas/chapter.py` 改 `Optional[UUID]`（两处） |
| 2 | 浮卡两个动作按钮全部失效 | 点击卡内任意处塌缩编辑器选区 → cursor 事件关卡 → 按钮点击与卸载竞态 | 双修：卡片根节点 `@pointerdown.prevent`（选区菜单同款惯用法）+ WorkspaceView cursor 事件不再关闭浮卡 |
| 3（存量） | 中文正文 @/# 提及永不触发 | tiptap suggestion 默认 `allowedPrefixes=[' ']`，要求触发符前是空格/行首；中文无词间空格 | `entityMention.ts` 两处 `allowedPrefixes: null` |
| 4 | MiMo 小预算调用空输出（速记解析/候选抽取必走降级） | `api.xiaomimimo.com` 未被 reasoning 适配层识别，OpenRouter 协议被 MiMo 静默忽略，隐藏思考烧光预算（实测 reasoning_tokens 1499/1500） | `reasoning_adapter.py` 新增 MIMO provider（`thinking.type` 协议，实测禁思考后 reasoning_tokens=0），附单测 |
| 5（存量） | 完稿审计 `/adaptive/finish` 一直 500 | `orchestrator.on_finish` 缺 `WorldModelRepository` 局部导入 → NameError（on_settle 有、on_finish 漏） | 补导入 |

**修复后的实测表现**：速记 2 秒解析出预填草稿；沉淀 4 秒出真实候选（同段重沉淀去重有效）；对峙类无事实段落 0 候选（宁缺勿滥）；完稿 3 秒出审计报告且整章抽取追加候选；打字中心跳 4 秒内同步世界变更。

**成本注记**（MiMo v2.5 国内价 输入 ¥1/M·输出 ¥2/M）：中度使用一章（3500 字）约 150K 输入 + 20K 输出 ≈ **¥0.1~0.2**；禁思考修复前每笔小预算调用暗烧 0.8~1.5K 输出 token，成本约 ×3~5。

**遗留观察**（低优先级，产品定夺）：章节切换会点亮「世界有更新」红点（来源徽标计入内容签名）；读者视角同时隐藏「相遇」块（文档未明确口径）；T3.5 名单外提示依赖模型是否输出名单外名字，UI 分支未在真机复现。

# 写作台「此刻」面板底层实现调研报告

> 调研日期：2026-09-16。调研方式：三个子智能体分头摸底（前端 UI 层 / 后端场景切片 / 候选收件箱链路），本文为主 agent 汇总提炼。所有行号以当前工作区为准，会漂移。

「此刻」面板是写作台右侧助手面板（InspectorPanel）的默认工作分区之一，承载两件事：**「此刻此地」世界场景切片条**（作者写到哪，世界此刻长什么样）与**候选回流收件箱**（AI 从正文里读出的世界变化，等作者批示）。它是「世界设定层 → 写作现场」双向桥（docs/world-writing-bridge.md）在写作台的主要落点。

---

## 1. 面板定位与挂载结构

**入口**：`InspectorPanel.vue`（frontend/src/features/workspace/containers/）五分区 `now/planning/chapter/review/debug` 中的 `now`（tabs 定义 InspectorPanel.vue:79-85，AssistRail 栏图标消费同一份定义，零映射漂移）。切章默认分区：空章落「打算」、有正文落「此刻」；wordCount 由 0 转正且用户未手动切过时补切，手动切过即尊重（InspectorPanel.vue:87-110）。

**结构**：「此刻」= 单组件 `WorldSceneSlice.vue`（workspace/presentation/），内部七个分区（模板注释 :538-825）：

1. 现场取景器（微观层，active_scene 派生）
2. 本章大盘（宏观层：宏观据点行 + 故事时刻行）
3. 出场名册（双轨融合）
4. 相遇
5. 距离（proximities/nearest_anchor，map_scale 标定才出现）
6. 伏笔与期待（「头顶的线」）
7. 候选收件箱 + 静音清单

**完稿→收件箱的引导**：finish 报告带 `candidates_pending > 0` 时检查分区出「去处理」按钮（InspectorPanel.vue:847-854），经 `velluma:open-inbox` 事件 + `inboxAutoOpen` 旗标切回「此刻」并展开收件箱——旗标专治「事件发出瞬间监听器未挂」的 v-if 卸载时序坑（batchAccept.ts:29）。

---

## 2. 场景切片：前端链路

### 2.1 useWorldSlice 模块级单例

`frontend/src/features/world/composables/useWorldSlice.ts`——模块级单例 ref（slice/candidates/loading/updated/scoutSkipped，:33-38）。单例动机：切片数据跨组件存活，副驾不在「此刻」tab 时事件不丢（:43-44）。

**保鲜三时机**（头注释 :15-26）：

| 时机 | 机制 | 位置 |
|---|---|---|
| ① 章节切换 | `watch(props.chapterId, immediate)` → `load()` | WorldSceneSlice.vue:57-63 |
| ② 心跳 world_version | 心跳响应搭便车带版本 → `velluma:world-version` → 比对 events+updated_at 变化才静默重取 | useAdaptiveAssist.ts:594-598 → useWorldSlice.ts:94-102 |
| ③ 窗口聚焦 | `window focus` → silent reload | useWorldSlice.ts:148-150 |

③ 是硬性兜底：心跳三重门控下纯手写/阅读态无心跳（:18 注释）。竞态守卫 `currentKey` 比对，请求期间切章丢弃过期响应（:79-80）。

**红点机制**：不用版本号而用内容签名（t/t_source/presence 拼串/scene.location_id/伏笔 ledger_key/期待 description，:53-62），避免「版本变但内容等价」误亮；仅同章内比较，点击 `acknowledgeUpdate()` 清除。

### 2.2 渲染层的双线融合

- **现场取景器**（WorldSceneSlice.vue:83-133）：优先 activeScene 派生（prose/pin/event 三源），prose 源显示「正文推导 · <线索>」微标；派生场景 ≠ 本章钉时出「钉定」链接钮 → `worldApi.setScenePin`（一键把正文推导固化为作者主权钉）。activeScene 由心跳响应经 `velluma:active-scene` 事件带来，含章号守卫防串章。
- **出场名册双轨**：`castFused` = 事件推演在景者（场景作用域子树闭包）∪ 正文活跃者（activeScene.cast）∪ 未建档高频人名（guests「临时通行证」）；`chapterRoster` 再并上 `slice.chapter_actors` 全章正文轨，同名去重、死亡/重要度排序（:141-216）。
- **脚下·宏观据点行**：`scene.path`（内部构造全路径「父·子」）+ `controlling_faction` 控制区标签 + `pinned` 已钉定标。
- **头顶的线**：`foreshadows`（悬空 N 章）与 `expectations`（张力 N）各截 2-3 条；读者视角滤镜下伏笔段整段隐藏（伏笔=作者层）。
- **「据正文推断」badge**：`presence_source === 'lexical'` 朱色微标——提示作者补正式事件，而非把词法推断当事实。

### 2.3 深链与「主动/被动分界」

`goWorld()` 组 query：`time=slice.t` + `from=chapter` + `chapter=chapterId` + 可选 `entity`/`fs`/`panel`（WorldSceneSlice.vue:491-504），世界页 `consumeRouteQuery()` 解析并出「返回本章」返程（WorldView.vue:928-986）。**写作台只做三类轻动作：改叙事锚、钉场景、裁决候选；一切重编辑深链世界页**（WorldSceneSlice.vue:31-33 注释「被动呈现为主；空间编辑永远在世界页」）。

---

## 3. 场景切片：后端链路

### 3.1 端点与响应

`GET /api/books/{book_id}/world/scene-slice?chapter_id=`（routes/world.py:394-411）——**参数只有 chapter_id，没有 cursor/时间**：时间走叙事锚四级降级，光标派生取景框不在本端点（走心跳通道）。委托 `build_scene_slice(db, book_id, chapter)`（services/world/scene_slice.py:175-424）。

响应 `SceneSliceResponse`（schemas/world.py:336-358）：`t` / `t_source`（chapter_anchor|prev_anchor|max_event|zero）/ `t_source_note` / `t_source_chapter` / `presence[]` / `scene` / `chapter_actors[]` / `encounters[]` / `foreshadows[]` / `expectations[]` / `version` / `world_empty` / 条件字段 `proximities`/`nearest_anchor`/`spatial_brief`（未标定 map_scale 整段缺席，向后兼容）。

### 3.2 build_scene_slice 主流程

1. **world_empty 守卫**：无实体 → t=0/zero 空切片，前端显示迁移引导（:186-198）。
2. **t 解析**：`resolve_narrative_time`（world_bridge.py:58-102）四级降级——本章锚 → 前序最近锚（带章号）→ 事件最大时刻（带摘要 note）→ 0。
3. **状态推演**：`compute_world_state_from_events(events, locations, t, relations)`（world_repository.py:281-413）纯函数 fold，前后端同构；统一做词法兜底增强。
4. **各行计算**：
   - **在场**：character_states 只取 character，排序 `(not alive, -importance)`，上限 40（:276）；结构化 location_id 留给前端做取景/章范围子树过滤（**双层分立**：后端上限只防极端长书全量倾泻，取景过滤交前端）。
   - **相遇**（W5-lite，:263-274）：t 时刻同地点存活角色两两成组 ≥2 人，人数降序前 3——「戏剧机会线索」。
   - **脚下 scene**（:279-296）：显式钉（pinned=True）→ 最新带 location_id 的事件 → 在场角色位置（alive 优先、重要度降序）→ 整块隐藏。`controlling_faction` 要求地点有坐标且对疆域 polygon **唯一命中**（射线法），否则 None 不造数据。
   - **伏笔**：PlotLedger open；在场名/别名命中 content 或 hook 属本章 → boost 排前；`chapters_open = 当前章号 − created_at_chapter`；上限 4。
   - **期待**：reader_mirror JSONB 中 status∈setup/accumulating，张力降序前 3。
   - **chapter_actors**（方向 B，:43-92）：整章纯文本 `extract_active_actors` + `detect_guest_names`；md5 内存缓存——「切片保鲜三时机反复调用只付一次 md5 的钱」。解决**「零事件不等于零戏份」**（:392-393）。

### 3.3 active_scene.py 光标派生取景框

`resolve_active_scene(pre_cursor_text, locations, base_loc_id)`（services/world/active_scene.py:199-258）——**无状态纯函数**（设计不变量：删改/回滚/FIM 分叉天然正确，不做漂移状态机）。

机制要点：

- **转场动词表** = LOCATION_JUMP_VERBS 11 词（原为幽灵稿穿越闸守门员，此处赋予导航职责）+ 室内扩充 5 词（推门/跨进/拐进/摸进/闪进），动词与地名间允许 ≤2 字填充。
- **三闸合法化**（主循环 :225-256，从最右命中向左）：① 动词紧邻地名；② **命中句须已完结**（地名后到文本尾有句末标点——作者正在写的半截短语不引发切换，无状态滞回防抖）；③ **闪回豁免**（句含 FLASHBACK_WORDS 或「N年前」正则则跳过继续向左）。
- **微观姿态层**（_scan_posture :167-194）：名册死板性补丁——作者只建宏观据点（村子）而正文写「推开门」时，从正文逆扫三组动势词（indoor_living/workshop/street）补微观姿态，叠加在宏观钉上。
- **降级链**：地名命中 → 姿态+宏观钉 → 本章显式钉（derived=False）→ 空。目标不在名册命中失败保持原景——**「专名约束是天然防漂闸」**。
- **pre_cursor_window 尾部锚定协议**（:299-330）：心跳 recent_text（光标段前 500 字，dock 语义不能动）取尾 80 字在章纯文本 rfind，锚点前 ≤2000 字即光标前窗；锚找不到（改写中/异步未落库）→ 章尾窗。
- **消费点**：orchestrator 心跳（orchestrator.py:224-292）——派生景 loc_id 进 `presence_fingerprint`（换景 = dock 整舱重算失效键），active_scene 附 cast/guests 随心跳响应回前端切片条微标；dock_generator 与 stitch_context 同源消费。

### 3.4 词法兜底（presence_source=lexical）

`enrich_state_with_lexical_presence`（services/world/lexical_presence.py:37-133）：折叠核心只认 birth/move 定位，事件 participant_ids 全空时在在场恒空——从事件 note 词法补在场标。纪律：**死者永不复活 / 同名歧义不填 / 不回写 participant_ids（append-only 纯洁）**；命中标 `label="据正文推断"` + `presence_source="lexical"`，即前端 badge 的唯一来源。缺口经 on_event 回调记 event-participant-gap 台账。

### 3.5 配套

- **map_scale 空间块**：proximities（异地存活角色对 ≤3 天步程前 3）/ nearest_anchor / spatial_brief（≤3 行进生成侧 settings_bundle）；未标定静默降级、一切距离天然带「约」。
- **state-for-chapter 端点**（world.py:373-391）：同时间解析、原始 fold 快照——与 scene-slice 是「同时间解析、两种视图」。

---

## 4. 候选回流收件箱：后端链路

### 4.1 生产端 event_scout

`services/world/event_scout.py`（注意：在 services/world/ 而非 adaptive/ 下）。契约 `run(chapter_id, db, snapshot, budget, source=, text=)`，注册为 orchestrator 组件（orchestrator.py:770,777）。两个触发点：

| 触发 | 输入 | 预算/超时 | 失败语义 |
|---|---|---|---|
| settle（Ctrl+Enter 沉淀） | 段落正文，source="settle" | budget 1500 | 只记组件错误，不阻塞沉淀 |
| finish（完稿审计） | 整章 content_text，source="finish" | budget 2500 + wait_for 90s | 不影响完稿报告 |

正文 <20 字不跑 LLM；LLM 走 creative 槽 temperature=0.1 + REASONING_DISABLED；prompt 截 4000 字，注入「只抽确定性事实」原则与近 15 条已入账事件排除块。产出经 `normalize_draft` 归一（11 类事件白名单外落 custom；参与者名三级匹配：精确→双向子串≥2 字→jieba token 边界）。

第三条生产链：**自动阅读**（world_read.py）——`POST /adaptive/auto-read`（切章发枪，过 read_budget 三层闸：内容哈希幂等/同章 300s/每书每日 30 次）复用同一个 `event_scout.run(source="auto_read")`；`POST /adaptive/read-entities`（通读阶段 A 认人）只产草稿不落库，作者勾选后才走既有创建端点（服务端幂等：书+归一化名+类型）。「喂养从『作者要做的事』变成『作者要批的事』」（world_read.py:31-35）。

### 4.2 三重去重 + 转正判重闸

1. **prompt 排除块**：t 之前最近 15 条已入账事件注入「勿重复提取，同义换措辞也算重复」（_recent_events_block）。
2. **归一化双向子串预筛**：`_is_ledger_duplicate`——去空白+中西文标点后 `a in b or b in a`；任一侧 <4 字放行（**宁漏勿误**）。
3. **pending 池幂等（全书级）**：同批/跨章原样重复 seen 集合拦，换措辞重复走同一把归一化子串尺——同一事件在不同章重复抽取是通读常态。
4. **转正前账本判重闸**（accept 路由内）：全书账本最近 200 条 note 跑同一判据，命中→不建事件、候选标 rejected + `auto_reject="duplicate"` 留痕、响应 `duplicated: true`——「重复转正闸不是作者的失败」（前端把它从 failed 拆出）。

判据函数只此一处、禁止平行实现（event_scout.py:89-91）。

### 4.3 候选池模型与四端点

`world_event_candidates` 表（models/world.py:388-424）——docstring 即物理隔离红线：**候选不参与推演、不进正常图层、不影响 version 主计数（账本零污染风险）**。状态机 pending/accepted/rejected（CheckConstraint），复合索引 (book_id, status)。

路由（routes/world.py）：

- `GET /candidates?status=&chapter_id=`——写作页收件箱带 chapter_id 只管本章，世界页待确认抽屉不带看全书；联表补 chapter_number（无叙事锚书显示「第 N 章」不伪造默认日期）。
- `POST /candidates/{id}/accept`——分流：`source="canon_extract"` → 建 tentative 真相节点；否则过重复闸后 `_event_fields_from_draft` 按类型补 payload（move→character_ids+to_location_id 等，保证推演回放正确）建事件。**accept 不建实体**（实体由名单闸保证已在库）。
- `POST /reject`——仅标 rejected 留痕不删行（供 quiet_learning 学习）。
- `POST /reopen`——回 pending，配合 `DELETE /events/{id}` 实现撤销。

**批量裁决无专用端点**：前端 batchAccept.ts 串行逐条走既有 accept（防后端竞态、单条失败不阻断），6 秒 toast 复合撤销 = 逐条「删产物（事件/canon 节点）+ reopen」；撤销闭包捕获本批 outcomes 防连开两批互撤。

### 4.4 quiet_learning「学着闭嘴」

`services/adaptive/quiet_learning.py` 唯一权威。核心立场：**静音集合从行为派生不落库**（杜绝静音态与行为漂移），`books.assist_mutes` 只存宽恕时间戳。

- **静音键**：`wevt:<event_type>` 与 `hint:<kind>`（白名单 appearance/callback/style_drift/world_inbox；leak/contradiction 安全类**永不静音**——「作者主权不包括让我看不见穿帮」）。
- **阈值纪律**：裁决样本 ≥3 且 ✗ ≥3 且 ✓==0 才静音（**一次肯定胜过三次否定**，宁错放勿错杀）；hint 收起 ≥3（30 天窗，轻动作适用时间窗；✗ 是重裁决不适用）。
- **防失真**：`auto_reject` 假拒绝不计入学习（「系统判重不是作者态度」）。
- **消费双闸**：event_scout 生成侧（prompt 排除块 + 落池过滤）+ 心跳感知带过滤；加载失败按无静音继续（学习链路故障绝不阻塞生产）。
- **可见可恢复**：`GET/POST /assist-mutes(/forgive)`，前端收件箱空态渲染静音 chip + 「恢复」按钮——覆盖「收件箱为什么空了」的困惑场景。

### 4.5 心跳侧积压提示

pending > 5（`WORLD_INBOX_HINT_THRESHOLD`，heartbeat.py:479）产 `kind=world_inbox` 卡并入 canon_hints 走感知带——「提示不拦截：只提示永不阻断写作动作」（P5 §9 红线）；计数缓存 TTL 10s 砍掉约 2/3 查询；settle/finish 落新候选主动失效缓存。

---

## 5. 设计思路提炼

从代码注释、docstring 与机制形状中提炼出的十条设计原则（按重要性排序）：

1. **切片即契约，三处同源**（scene_slice.py:7-9）：写作页切片条 / 世界页游标回放 / 生成上下文（settings_bundle）共用同一份时间解析与事件推演——**「作者看到的在场 = AI 看到的在场」**。这是整个面板存在的第一理由：切片不是独立功能，而是生成链路的可视化调试窗。

2. **块级缺席原则，绝不造数据**（scene_slice.py:11-12）：每块缺原料返回空集合，前端按块隐藏。疆域控制方要求唯一命中否则 None、条件字段缺席即省略键——宁可面板少一行，不可多一行编的。

3. **双轨在场：事件推演轨 + 正文活跃轨**：世界事件只认显式事件，「正文里端水端饭说了四段话的明姐被物理抹杀」（active_scene.py:81-84）——词表/jieba 纯代码 0 LLM 补镜头前名单；零事件不等于零戏份。词法兜底同样有「宁可缺席不可复活」的纪律。

4. **解析/落库分离 + 物理隔离双红线**：AI 只产草稿（event_scout/parse-event/auto-read 三路同），落 pending 候选池（与事件账本平台级隔离：不参与推演/不进图层/不影响 version），作者 ✓ 才转正。「喂养从『作者要做的事』变成『作者要批的事』」。

5. **无状态纯函数优于漂移状态机**（active_scene.py:11-18）：光标派生取景框每次重算，删改/回滚/FIM 分叉天然正确；防抖用「命中句须已完结 + 停顿档节流 + 无跨请求状态」三层无状态方案，而非滞回状态机。

6. **保鲜不打扰**（docs/world-writing-bridge.md:38）：版本号被动同步（心跳搭便车，非轮询）+ 内容签名红点 + 静默重取，**永不弹窗打断心流**。窗口聚焦是硬性兜底（纯手写态无心跳）。

7. **学着闭嘴：派生不落库 + 阈值纪律**：静音从行为派生（裁决史 + 埋点史），宽恕时间戳一笔勾销旧账；「一次肯定胜过三次否定」；安全类永不静音；系统判重不算作者态度。

8. **失败不阻塞主链**：scout 失败不影响沉淀/审计；quiet learning 故障静默降级空集；finish 整章抽取 90s wait_for 上限防响应无限挂起。

9. **双层分立：后端防倾泻，前端做取景**：后端只设极端上限（presence 40/相遇 3/伏笔 4），取景/章范围过滤交前端子树闭包——切片响应保持结构化（location_id 而非只给名字），过滤语义归展示层。

10. **主动/被动分界**：写作台是呈现层，只做三类轻动作（改叙事锚/钉场景/裁决候选）；一切重编辑深链世界页（带时刻与往返参数）。

---

## 6. 事件总线一览（前端解耦）

「各自监听各自改状态」（batchAccept.ts:21-25），抽屉/tab/收件箱分属三个组件，靠 window 自定义事件避免层层 props：

| 事件 | 发送方 | 接收方与动作 |
|---|---|---|
| `velluma:world-version` | 心跳响应带版本（useAdaptiveAssist.ts:594） | useWorldSlice 比对后静默重取 |
| `velluma:world-refresh` | settle/finish/速记/批量/canon 转正等 7 处 | 切片+收件箱重取、世界页候选+期待重取 |
| `velluma:quick-note` | 情境浮卡「记一笔」/收件箱「＋ 登场/补记」 | QuickEventNote 速记浮卡打开（可带预填词） |
| `velluma:active-scene` | 心跳响应带 active_scene | 切片条取景器微标（章号守卫） |
| `velluma:open-inbox` | settle toast / 检查报告「去处理」 | InspectorPanel 切「此刻」+ 收件箱展开 |
| `velluma:scout-skipped` | settle/finish 后 | 收件箱空态显示跳过原因 |

---

## 7. 已知张力与挂账

1. **fold 唯一入口纪律的字面违反**：fold.py:7-9 声明场景切片应经 `fold()`，但 scene_slice.py:208 直调 `compute_world_state_from_events`（显式传 relations）。两者都做词法增强、输出等价，但若后续在 fold 层加 tx_head/belief 语义，切片需同步跟进——当前是注释层面的纪律张力，非行为分歧。

2. **chapter_actors 的 md5 缓存是进程内内存缓存**（scene_slice.py:38-40，容量 64 超限整体清空）：多进程部署（多 uvicorn worker）下缓存各自为政；当前单进程 SQLite 路径无影响。

3. **收件箱批量裁决是前端串行循环**：N 条候选 = N 次 HTTP 往返 + 每条内部过 200 条账本判重查询。章均候选量小（个位数）时无感，全书通读后大批裁决时延迟线性增长；后端语义层面暂无批量端点。

4. **quiet_learning 的 hint 通道扫 jsonl 埋点文件**（collab_events.jsonl，30s 缓存）：文件无限增长后扫描成本上升；当前个人单机场景可接受。

5. **active_scene 的转场动词表是封闭词表**：室内转场已扩充过一轮（推门/跨进等 5 词），新写法（如「下楼」「上岸」）不在表内即回退本章钉——有微观姿态层兜底，但词表维护是持续的追赶工作。

---

## 附：关键文件索引

**前端**
- `frontend/src/features/workspace/containers/InspectorPanel.vue` — 面板壳与分区逻辑
- `frontend/src/features/workspace/presentation/WorldSceneSlice.vue` — 「此刻」唯一组件（切片条+收件箱+静音清单）
- `frontend/src/features/world/composables/useWorldSlice.ts` — 单例 store（保鲜三时机/版本比对/内容签名红点）
- `frontend/src/features/world/composables/batchAccept.ts` — 批量裁决与复合撤销
- `frontend/src/features/world/presentation/BatchAcceptModal.vue` — 批量裁决模态（写作页/世界页双宿主共用）
- `frontend/src/features/world/engine/narrativeTimeSource.ts` — 时刻来源人话文案
- `frontend/src/services/api/domain/world.api.ts` — 端点与类型（SceneSlice :152-175）

**后端**
- `backend/routes/world.py` — scene-slice :394-411 / candidates :501-628 / state-for-chapter :373-391
- `backend/services/world/scene_slice.py` — build_scene_slice :175-424
- `backend/services/world/active_scene.py` — resolve_active_scene :199-258 / pre_cursor_window :299-330
- `backend/services/world/event_scout.py` — 候选生产端（settle/finish/auto_read 三 source）
- `backend/services/world/event_parser.py` — normalize_draft / 参与者三级匹配
- `backend/services/world/lexical_presence.py` — 词法兜底（presence_source=lexical 唯一来源）
- `backend/services/adaptive/quiet_learning.py` — 静音派生与阈值纪律
- `backend/services/adaptive/read_budget.py` — 自动阅读三层预算闸
- `backend/services/context/world_bridge.py` — resolve_narrative_time 四级降级 :58-102
- `backend/repositories/world_repository.py` — compute_world_state_from_events :281-413 / 候选 repo :505-553
- `backend/routes/chapter_generation/adaptive/heartbeat.py` — world_inbox 积压提示 :474-530
- `backend/routes/chapter_generation/adaptive/world_read.py` — auto-read / read-entities

**设计文档**
- `docs/world-writing-bridge.md` — 写作桥 W1-W5 唯一权威
- `docs/scene-transit-feasibility.md` — 光标派生取景框设计
- `docs/foundation-hardening.md` — P5 叙事时间来源可见/在场提权
- `docs/auto-read-quiet-learning.md` — 系统自动读 + 学着闭嘴战略

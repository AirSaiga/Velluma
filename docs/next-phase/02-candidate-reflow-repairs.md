# 候选回流链路修缮（设计稿）

> 状态：**已施工（2026-09-18，M1-M4 四期全落，验收绿：后端 1562 / 前端 381 + tsc 净）**。
> 施工叙事见 `docs/incidents/world.md`「候选回流链路修缮」；契约沉淀见 `docs/agent/world.md` 写作桥④ 与 `docs/agent/nle-adf.md`。
> 性质：**修缮，不是新建**——不重设计链路，只把已存在的链路修到「敢用、好用」。
> 一句话定义问题：系统懂这本书的唯一途径是「读正文 → 提候选 → 作者勾选入账」，
> **作者点「勾」的那一下决定了此后全部辅助的质量**。本设计的目标：让那一下
> **既有把握（信任面），又不费劲（省力面）**。

---

## 0. 讨论中确立与撤销的部分

**确立**：链路本体健壮、设计自洽（2026-09-18 全链体检结论）——幂等（内容哈希）、
三道去重闸、批量采纳 6 秒可撤销、失败保留重试资格，这些不动。
「来源单极化」（候选几乎全部来自 auto_read，settle/finish 为零）是**设计的必然结果**：
自动阅读在切章时已读整章，手动链路再抽会被去重闸合法拦下——不是死链，不修。

**撤销**（讨论中提出后被证据否掉，留档防复读）：
- ~~「批阅无节奏导致系统静默变钝」的预防性担心~~——零使用的真实原因是作者一直在测
  其他功能，非节奏缺陷；降级为「以后留意的假设」，不为此设计任何东西。
- ~~回场欢迎页/仪式化设计~~——依据不足，撤销。回场只保留一个轻量用途（见 §3-M4 补读）。

## 1. 体检发现的问题与修法（按优先级）

### P1 候选补出处（信任面，最优先）

**问题**：候选项只有「类型 + 概括（≤30 字）+ 章号」，无原文片段、无置信度、无抽取理由
（`backend/services/world/event_parser.py:205-233` normalize_draft）。作者要凭一句话做
「该不该进世界账本」的重裁决，判错即污染后续全部推演。
**对比**：Alt+N 速记解析（`parse_event_text`）反而带 confidence/evidence 硬闸——
轻场景配了厚证据，重场景配了薄证据。

**修法**：event_scout 抽取时要求 LLM 同时给出**出处原句**（evidence span，正文逐字片段，
非改写），存入候选 payload；前端候选卡默认显示概括，展开/悬停见原句。
裁决从「信不信 AI 的概括」变为「看一眼原句就知道有没有这事」。
纪律：原句必须能在正文中逐字找到（后端校验子串，找不到即丢弃该条或降级标注），
防止模型编造出处（出处铁律同挂件 note 后端拼装原则）。

### P2 两处健壮性修补（信任面）

**P2a 用量记账重启丢失**：实测 2026-09-10 auto_read 成功产出 2 条候选但
`generation_runs` 无记录。recorder 内存累积 + 失败塞回（`backend/services/adaptive/observing.py:56-82`），
进程重启即丢缓冲——「防丢账」承诺在重启场景不成立。
**修法**：缩短 drain 周期或关停时 flush（atexit/优雅停机钩子），使 insights 的
「AI 用量」不再系统性漏记。

**P2b 撤销链非事务**：批量撤销 = 逐条「删事件 + 候选 reopen」两个独立请求
（`frontend/src/features/world/composables/batchAccept.ts:147-164`），链断留下
「事件已删、候选仍 accepted」孤儿态；reopen 端点不校验事件存在
（`backend/routes/world.py:617-628`）。
**修法**：撤销改单事务端点（服务端一步完成删事件+reopen），或加启动时对账
（accepted 候选无对应事件 → 自动 reopen 并提示）。

### P3 拒绝史进防重（信任面）

**问题**：去重素材只含账本事件 + pending 池（`event_scout.py:200,216`），rejected 候选
不参与判重——作者 ✗ 掉的事件换措辞/跨章会再次进箱；唯一收敛是类型级静音
（同类型 ≥3 裁决且全 ✗，`quiet_learning.py:57-58,107-119`）。
**修法**：归一化判重素材加入**近期 rejected 池**（带窗口，如 30 天/近 200 条，防止
永久误挡同名不同事）；命中 rejected 判重时不再入箱、静默落台账。

### P4 键盘裁决（省力面）

**问题**：单条 ✓/✗ 全靠鼠标，无任何键盘绑定（WorldSceneSlice、BatchAcceptModal 均无
keydown）；长期使用下「每章几条候选」与操作成本不匹配。
**修法**：收件箱获焦后 ↑/↓ 移动、←/→（或 Enter/Delete）裁决、批量确认快捷键；
目标：几十条候选一分钟内批完。鼠标路径保持不变。

### P5 消化去手动化（省力面，「沉淀」重新定位）

**背景**：沉淀（Ctrl+Enter，写作中让 AI 消化刚写的段落）零使用——它的活儿已被
心跳（轻量持续感知）+ 自动阅读（切章整章读）瓜分，且「记得按家务键」本身反人性。
**作者裁决过**：不做常驻按钮（按钮治「找不到」，治不了「为什么按」）。
**修法**：
- **回场补读**：进章时校验 `chapters.auto_read_state` 哈希——内容从未读或已变，
  静默补读（复用 auto_read 全链路，预算闸不变）。覆盖「应用关闭前未切章导致
  整章未读」的盲区；
- Ctrl+Enter 保留为高级用户手动覆盖键，不再作为唯一入口，不新增常驻按钮；
- 不设「重大转折提醒消化」的主动打扰（易烦，明确不做）。

### P6 小修（顺手）

- `event_scout.py:207-210` 单条候选 normalize 失败 bare except 静默丢弃 → 计数落台账
  （让作者知道「AI 提过但坏了 N 条」）；
- `world_read.py:151-159` read-entities「LLM 失败」与「无涌现」不可区分且照写幂等锚
  → 失败不写锚，保留重试资格（与 auto_read 事件阶段同纪律）。

## 2. 明确不做

- 不重设计链路、不动 auto_read 预算闸/幂等（体检确认扎实）；
- 不做回场欢迎屏/仪式页（§0 已撤）；
- 不改批量采纳的串行语义（单条 accept 已原子，`world.py:597-600`；只修撤销对账）；
- settle/finish 的候选生产路径保留原样（在役无害，被 auto_read 挤压是设计必然）。

## 3. 分期建议

| 期 | 内容 | 验收 |
|---|---|---|
| M1 | P1 候选补出处（抽取 schema + evidence 子串校验 + 前端候选卡原句展示） | 新候选带原句；编造出处被校验拦下；旧候选兼容（无 evidence 不报错） |
| M2 | P2a 用量记账 + P2b 撤销对账 + P3 拒绝史防重 + P6 小修 | 重启不丢账；撤销无孤儿态；rejected 换皮不再入箱；后端测试全绿 |
| M3 | P4 键盘裁决 | 全键盘批完一箱候选；vue-tsc 净 |
| M4 | P5 回场补读（进章哈希校验静默补读） | 关应用前未切章的书，重进后候选自动补齐；预算闸行为不变 |

## 4. 度量与回看

- M1 后看「候选 ✓ 率」变化：出处让裁决有把握，预期误采纳下降、拒绝更果断
  （基线：当前 42 ✓ / 0 ✗ 的橡皮图章分布应被打破）；
- P3 上线后台账计数「重复投递拦截次数」，验证拒绝史防重的实际命中；
- 修缮全部落地后，「批阅节奏/静默变钝」假设留待真实使用数据再评估（§0）。

---

### 附：代码锚点（2026-09-18 体检时核实，行号会漂移）

- 自动阅读入口：`backend/routes/chapter_generation/adaptive/world_read.py:38-87`；预算/幂等 `backend/services/adaptive/read_budget.py`
- 事件侦察与三道去重：`backend/services/world/event_scout.py:189-222`；候选规格化 `backend/services/world/event_parser.py:205-233`
- 采纳/转正判重/reopen：`backend/routes/world.py:550-628`；批量与撤销 `frontend/src/features/world/composables/batchAccept.ts:111-164`
- 用量记账：`backend/services/adaptive/observing.py:56-82`
- 静音派生与宽恕：`backend/services/adaptive/quiet_learning.py:256-326`
- 收件箱 UI：`frontend/src/features/workspace/presentation/WorldSceneSlice.vue:766-820`；世界页抽屉 `frontend/src/features/world/containers/WorldView.vue:1333-1368`
- settle/finish 生产路径：`backend/services/adaptive/orchestrator.py:655-674, 713-742`

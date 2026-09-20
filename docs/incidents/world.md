# 世界设定层施工日志

> 时效性施工/事故叙事自 AGENTS.md 拆出，稳定契约见 `docs/agent/world.md`（本文是其唯一追溯处，只收「怎么发现的/哪批干的」，结论与判据已留档案）。

### 真相层 C1 融合（2026-08-17）

- 信息层（作者真相 vs 读者认知）并入活舆图，UX 稿 `docs/design/canon-fusion/`；过渡期句子录入建「叙事」自由节点。

### 时间轴交互两轮 UX 优化（2026-09-02）

- 时间轴交互整体重做工分两轮落地：自动视野贴合内容时刻集（取代创世 0 年起铺满）、Ctrl/Cmd+滚轮精确到日、轨道拖拽/游标柄拖拽手势分工、浮点年持久化（整数年语义与旧版逐日等价、存量零迁移）。交互契约见档案「时间轴」节。
- 浮点年窗口的动机：旧方案世界页状态存 localStorage，启动脚本端口扫描换 origin 即漂移，实机表现为重启后视野重置回第 1 年——故一律按书持久化进 `books.timeline_view`，旧 `velluma:tl-*` 键仅作一次性迁移来源。

### 世界速记关联式录入扩容（2026-09-05，P1 批次）

- `POST /world/parse-event` 支持 `chapter_id` 可空：世界页速记入口缺省书级此刻（最大章锚→事件最远处→0）；响应新增 `new_entities`/`new_locations` 草拟名单与既有实体 `aliases` 口述原词自动回填。「只产草稿，作者过目才建档」红线内的扩容。

### 设定中心整体退役（2026-09-05，M4/M5 之后）

- 「创作笔记」（写 `books.global_sys_prompt`）因页面承诺的「全局提示词」在 adaptive 主线零存在而整线退役：`features/bible/`、`components/NotesPanel.vue` 删除，AppRail「设定」项移除，`/bible/:bookId` 重定向世界页，后端 V3 生成链 prompt 模块+`/clarify-outline`+ClarifyOutline schema 同批归档，`books.global_sys_prompt` 列冻结只读。

### 真相层 UX 人话化重修（2026-09-03）

- 设计稿 `docs/design/truth-ux/`：详情抽屉按「读者现在知道吗？/打算怎么抖出来？」两问重排，表/里退居角标。
- 同日实测修正：句子录入原本自动弹出详情抽屉——「记一句话跳出一屏字段」，改为行落账顶闪朱+toast 闭环；问二/标签收「补充」折叠区、有值自动展开。

### 因果图谱与连锁分析退役（2026-09-03）

- 建边零入口实证（前端 createEdge 零调用方/候选转正只建节点/后端无自动推边）→ 边恒为零、图谱永远一屏孤立圆点；连锁分析沿边扩散恒答「没有」，一并退役。`CausalityGraphModal` 组件删除、cytoscape 依赖同卸。保留项（后端边表/CRUD 与 `/impact` 路由、`useCanon` 边契约）见档案。

### 字段级真相分层（2026-09-03）

- 同日实测把 intro 补入可分层字段——动机：作者最常把「读者知大概/不知具体数据」的混合内容写在「一句话」里。契约与五条消费线见档案。

### 写作桥第三弹——光标派生取景框（2026-09-14）

- 动机：光标中插写作时旧口径把光标后已写内容整个当「作者当前段落」（实测：插入点在送别、卡片全接着文末饭桌场景生发），取景需从「本章钉」细化到「正文推导的当前场景」。设计唯一权威 `docs/reports/scene-transit-feasibility.md`，判据与接流四线见档案「写作桥⑧」。

### 数据库卫生批（2026-09-14）

- 审计实锤五类历史遗留污染生成链，修复语义见档案「数据库卫生批」；发现经过：
  - ① 事件 id 引用格式分裂：早期写入路径把 hex32 无连字符存进 events/candidates 的 JSONB 引用列，读侧全用带连字符 str(UUID) 匹配 → 推演状态静默挂不上实体。《弦上灰》42 条事件全数失配，词法兜底产生的带 dash 条目歪打正着掩盖了问题。
  - ② fold 严格 born 语义会把整书批量导入（无 birth 事件）的世界的全部出场角色判死；①归一后会显形为「已死亡」连环劣化，故「出场即活」修正与①同批。
  - ③ RAG 陈旧记忆：28 块 memory_chunks 全部与当前正文对不上（22 块旧引擎摘要层积《我！魔法之巅》+2 块重写前正文《最终武装》+4 块带 HTML 标签且重复《弦上灰》），清后按当前正文重建 12 块。
  - ④《弦上灰》三条 `-2` 同内容伏笔复本（开放伏笔素材块双份注入）。
  - ⑤《我！魔法之巅》ch1.summary 为旧版正文摘要（专有名词现正文零命中），previous_summary 接力棒会把假「上一章结尾」注入 ch2。
- 修后《弦上灰》推演 6/6 命中 bridge（修前 4/9 且含格式假象）。备份在 `data/backups/velluma.pre-hygiene-*.db`。

### 设置拆三入口（2026-09-15）

- 原设置面板拆为 AppRail 底部三钮：「外观」`AppearancePanel.vue`、「API」`ApiSettingsModal.vue`、「设置」瘦身弹窗 `AppSettingsModal.vue`（仅通知偏好），`useAppSettings` 单例三路开关。旧七面板删除清单见档案「编辑入口收敛」节。

### 事件 title 可编辑显示名（2026-09-13）

- `world_events.title` 支持编辑显示名；前端 `eventDisplayName` 唯一回退链 title→事件类型模板 label。

### 快捷视界胶囊+视觉升级（2026-09-13，9179868）

- 时间轴头部新增快捷视界组（以游标为中心的跨度预设，含「全局=回自动视野」档），点击走 `setTimelineRange` 立即落盘；同批视觉件：信标针脚/金墨直方图/燕尾书签/黄铜菱形游标。

### 隐式图谱投影器原型实装（2026-09-16，未提交批内）

- 按 `docs/reports/implicit-graph-projection-feasibility.md` 调研结论实装 `services/world/implicit_graph.py` 三件；当前消费方暂无（纯原型），P1 接 knowledge_plane event_card 通道/前缀签名并入事件哈希待拍板。契约与对拍见档案。

### 候选回流链路修缮（2026-09-18，设计稿 docs/next-phase/02-candidate-reflow-repairs.md，未提交批内）

- 动机：系统懂这本书的唯一途径是「读正文→提候选→作者勾选入账」，作者点勾那一下决定此后全部辅助质量——修缮让那一下既有把握（出处原句可对）又不费劲（键盘批阅/回场补读）。设计稿定性为「修缮非新建」，链路本体（幂等/去重闸/批量采纳）不动。
- M1 候选补出处：旧候选只有「类型+概括+章号」，作者凭 AI 一句话做重裁决（对比：Alt+N 速记反而带 evidence 硬闸——轻场景厚证据、重场景薄证据的倒挂）。修法=抽取 prompt 要求逐字摘录 evidence + event_scout 落池前 `verify_evidence`（去空白子串；标点不同即判改写）。取舍：出处过不了校验**剥出处保留候选**（降级回无出处档）而非整条丢弃——宁降级不丢事件，编造原句绝不递给作者。
- P2b 撤销链非事务：旧撤销=「删事件」+「reopen」两条独立请求，链断留「事件已删候选仍 accepted」孤儿态。修法选单事务端点（`/undo-accept`）而非启动对账——防在源头优于事后扫。施工坑：canon 分支 `str(node.id)` 在 flush 前读得 None（列 default 到 INSERT 才赋值），先 `await db.flush()` 再记 draft。
- P3 拒绝史防重：✗ 掉的事件换措辞/跨章曾会再进箱（唯一收敛是类型级静音）。窗口取 30 天/200 条防永久误挡同名不同事；`auto_reject=duplicate` 系统假拒绝不计（账本判重本就会拦）。
- P6 两小修 + 一枚顺带实锤：给 world_read 补测试时发现 `adaptive/schemas.py` 缺 `Any` 导入（`from __future__ import annotations` 惰性求值把错误掩盖到首次实例化）——**read-entities 端点响应此前从未成功过**（工作照跑、候选照抽，FastAPI 序列化必炸）。补一行导入修复。
- M3 键盘裁决 / M4 回场补读：`inboxKeyboard.ts` 纯函数三宿主接线（收件箱/待确认抽屉/批量模态）；WorkspaceView 进章也发枪 auto-read，哈希幂等闸兜底「已读未变零成本」。
- 测试：新增 `test_emergent_facts.py`(6)/`test_observing_shutdown.py`(3)/`test_world_read.py`(3)/inboxKeyboard(11) + event_scout 扩 13 项 + accept_dedup 扩 6 项。既有测试假件坑：`test_event_scout_dedup` 的 fake 实体缺 `id` 属性——旧测试的去重用例实际静默走 normalize 异常路径（bare except 吞掉），P6 计数化后立刻显形，补 `id` 修复归位被测路径。

# 打算与大纲底层合流与统一引力线可行性分析报告

> 2026-09-14 · 系统架构重构调研第一期 · 纯只读调研（零代码改动）
> 议题：`chapters.spine.intent`（打算：一句话方向）与 `chapters.outline_text`（大纲：多行节拍）是否应当底层合流为「单轨叙事引力流（Single Narrative Vector）」。
> 行号以 2026-09-14 工作区为准（函数名为准，行号会漂移）；所有关键结论附代码/文档/提交证据。

---

## 0. 结论摘要（TL;DR）

1. **「两份饲料撕裂生成链」的前提在生成层不成立**。截至当前代码，spine 与 outline 已经**双向互通**：spine 意图+锚点进 stitch 五模式（system 侧温卡，2026-08-28 e6cd2e7 起）也进 dock（spine_line）；大纲就近节拍进 dock（nearby_block）也进 stitch（user 侧意图块）与未来推测。真正分离的不是「谁喂谁」，而是**同一方向信息在 prompt 里的两个剂量位**：system 位=全章方向软约束（温卡，章内冻结），user 位=下一步目的地（就近一两拍，每次现算）。
2. **分裂根因是有意的分层设计 + 一次实证事故**，不是未打通。2026-08-18 设计稿明文红线「不与章节大纲合并/互转」（chapter-planning-spine.md:45）；2026-08-25 两起「弧线级材料导致冲章/跳高潮」事故（stitch_context.py:159-165、test_dock_nearby.py:4-9）确立了 user 位只收就近节拍的剂量纪律。
3. **作者感受到的认知负荷是真的，但病灶在 UI 层**（侧栏「打算」分区并排两个输入框），不在数据层。两条合流路径评估：**路径 A（废 spine.intent，大纲首拍兼方向舵）不建议**——七处断裂面、违背设计红线、解决的是生成层不存在的问题；**路径 B（打算升维即时节拍）条件可行**但背负意图双身份语义债。证据自动浮现出**路径 C（UI 合流、数据层与 prompt 剂量位不动）为首选**，成本最低、断裂面为零。
4. 无论选哪条路径，**三处缓存/签名依赖**（dock 文本签名、前缀冻结签名 spine_hash、spine_hot 节流豁免锚）是必须逐点续接的硬约束，漏任何一处表现为「改了方向舱不换向」/「冻结前缀继续供旧卡」两类静默事故（§3.3）。
5. 附带勘误：本报告调研发现并修正了昨日《侧栏编辑项生效链路报告》的一处错误论断——spine 意图并非「不进 stitch」，它走温卡（docs/assist-panel-editables-flow.md 已加修正注）。

---

## 1. 历史分裂根因考古

### 1.1 时间线（git + 文档双证）

| 日期 | 提交/文档 | 事件 |
|---|---|---|
| 2026-08-18 | docs/chapter-planning-spine.md（D2 拍板） | spine 立项。**非目标红线第 3 条**：「不与章节大纲合并/互转（大纲是自由散文燃料，谋篇是其上的结构化薄层）」（:45） |
| 2026-08-25 | 4d992c6（视野配比实测修复） | stitch 意图兜底从「大纲前 200 字粗暴截断」改为**就近一两拍**——旧兜底把整章剧情地图喂给轻量续写，「模型直奔终点（冲章），且截断落在半截词（真实 trace 实证）」（stitch_context.py:159-165 注释原文）。同批 dock 就近铁律：事故=「意图（血噬的觉醒）+ 养料…天然指向章末，挂件一步跳到高潮场面」（test_dock_nearby.py:4-9 事故语料 docstring） |
| 2026-08-28 | e6cd2e7（B6 温层+前缀纪律） | **spine 意图+锚点经知识平面温卡注入全部 stitch 模式的 system 侧**——「本章打算（作者定的方向，软约束）」，章内冻结进前缀（knowledge_plane.py:407-431） |
| 2026-09-03 | d7337d8（意图入舱+后续线 A-E） | stitch user 侧意图块加层2 兜底（仅 inferred/baton）；注释明示 spine 不走 user 侧的原因是**去重**：「它已经由知识平面温卡（warm_card）注入 system 侧，user 侧不重复注入」（stitch_context.py:175-176） |

### 1.2 三份「分裂是有意的」明文证据

1. **设计红线**（chapter-planning-spine.md）：
   - :45 非目标：「不与章节大纲合并/互转（大纲是自由散文燃料，谋篇是其上的结构化薄层，见 §2.3）」；
   - §2.3 分工表：大纲回答「本章情节怎么展开」/心跳点火的 LLM 燃料/心智成本中；谋篇回答「本章**要去哪**、哪几步不能少」/走向卡挂载、进度感知/心智成本趋近于零；
   - D-5 锚点上限 5 的存在本身就是防「谋篇膨胀成第二份大纲」（:59，422 劝阻文案同义）；
   - §8 风险登记「概念混淆」对策：「大纲写情节，谋篇写方向；谋篇区永远在上（方向先于情节）」（:258-259）。
2. **canon 迁移时的再确认**（backend/repositories/intent_repository.py:253-255）：把伏笔/真相/期待迁入 canon 节点时明确写了不迁清单及理由——「chapters.outline_text 大纲节拍（自由文本，作者逐拍编辑的事实源…）；chapters.spine 锚点（spine 已是章级意图存储…）」。即：分立在 2026-09 前后的两次独立评审中都被当作**正确边界**复述过。
3. **就近化注释**（stitch_context.py:159-165 / test_dock_nearby.py:4-9）：user 位为什么不吃全量大纲/弧线——冲章与跳高潮的双实证（详 §1.4）。

### 1.3 现状反转：生成层已是「一源两位」，不是「两源撕裂」

对「stitch 对 spine.intent 视而不见」这一命题的核查结论：**在 2026-08-28 之后不成立**。

- spine → stitch：`_render_warm_card`（knowledge_plane.py:407-431）读 `chapter.spine`，渲染「# 本章打算（作者定的方向，软约束）\n本章打算：{意图}\n非写不可的情节：{非 dropped 锚点}」，经 `render_system_blocks` 注入序**第 2 位**（「warm」，adaptive_prompts.py:346，场景身份之后、实体之前）；五个 stitch builder（continue :554/burst :759/outline :881/open/outline-expand）全部接受 `warm_card` 形参并透传（:386/:610/:798/:929 等传参点）。
- spine → dock：`_spine_intent` 直读（dock_generator.py:404-413）→ spine_line「# 本章意图（方向参考）」（adaptive_prompts.py:1632）。
- outline → dock：nearby_block「作者大纲·就近节拍（几步之外的目的地…）」（adaptive_prompts.py:1639-1643）+ `has_nearby` 分节编译的 toward_beat 槽位子句（:1692-1705）。
- outline → stitch：`_nearby_intent_from_outline`（stitch_context.py:158-166）→ user 侧意图块「几步之后的目的地」（adaptive_prompts.py:617-636）。
- outline → 未来推测：nearby_block「推测画面必须是通往它路上的合理一步」（adaptive_prompts.py:1286-1293）。

**「视而不见」的注释真义**：stitch_context.py:199 `if intent.source not in ("inferred", "baton")` 只作用于 **user 侧意图块的层2 兜底档**；:175-176 注释写明排除 author 源的理由是「已由温卡注入 system 侧，user 侧不重复注入」——**剂量去重，不是供给缺口**。

### 1.4 深层顾虑的回答：不是「意图太粗」，是「意图是弧线级」

当初不让 spine 意图占据 stitch user 位（目的地槽）的顾虑，实证链非常清晰：

- 08-25 stitch 事故：旧兜底=大纲前 200 字（≈整章弧线）→「模型直奔终点（冲章）」（stitch_context.py:161-163）；
- 08-25 dock 事故：意图「血噬的觉醒」（典型弧线级一句话，与 spine.intent 同构）+ 养料 →「挂件一步跳到高潮场面——作者明明还在写开场名言」（test_dock_nearby.py:5-9）。

即：**弧线级文本放在「接下来写什么」的槽位会诱导模型跳拍**。修复不是删弧线信息，而是**剂量学位移**——弧线降为 system 侧软约束（「方向参考」「软约束」措辞，温卡），user 位只留「接下来一两拍」。这是今天两字段并存于全部 prompt 的真实架构原因。spine（08-18 立项）与 outline_nearby 共享判据（08-25 提取为共享模块 outline_nearby.py:1-14 模块头）确实是两批施工，但「stitch 不吃 spine」**不是遗漏而是 08-25/08-28 两次治理后的稳态**。

---

## 2. outline_nearby 的真实吞吐能力

### 2.1 算法解剖（三层，全纯函数零 LLM）

**第一层：片段提取**（text_match.py:40-57 `sliding_fragments`）——把条目拆 3 字滑窗片段；**含标点/数字/空白的片段整片弃用**（FRAGMENT_INVALID_CHARS :31-33，全角标点+阿拉伯数字+空白）；保序去重；只取前 **6** 片（:55-56——条目是短语/大纲行，全量取片只会添噪）。

**第二层：命中率**（text_match.py:60-80 `fragment_hit_rate`）——命中片段数÷可判片段数，0-1。

**第三层：判据入口**（text_match.py:83-115 `matches`）——整串捷径（`item in text` 逐字出现过直接判中，:110-111）+ 命中率 ≥ threshold（带 1e-9 容差，:115，治 2/3 浮点）+ `no_fragments` 兜底语义开关。

**大纲行消费参数**（outline_nearby.py）：
- `outline_line_written`：threshold **2/3**（6 片须中 4）、size=3、max_fragments=6、`no_fragments=True`（无可判片段的**结构性短行按已写跳过**，:50-60）；
- `outline_line_is_meta`：整行被引号包裹 / 含《》/ strip 后 <6 字 → 不是剧情行（:31-47，2026-09-03 卷首致辞事故产物，与意图反推的 arc 提取**共用同一判据**——intent_inference.py:349-367）;
- `outline_nearby`：行 ≥8 字、非 meta、跳过已写行、取接下来 1-2 拍、**每拍截断 ≤60 字**（OUTLINE_NEARBY_LINE_MAX :25，take=2，:63-87）。

### 2.2 抗噪能力的两面

- **误判已写（跳拍，重噪声）的防线**：2/3 阈值即「6 片须 4 片逐字散落」——通用三字组（「他没有」「不多时」）单发命中不再足以判已写（text_match.py:5-18 模块头正是为治这个：旧「任一/过半命中」曾致「未写的大纲行被判已写→就近节拍跳到更远的拍子」）；测试实证：test_dock_nearby.py:39-50——开场名言已写、致辞行过滤、首拍=工头打断、**远方节拍（袭击/机甲侵入）不进供给**。
- **误判未写（重复喂，轻噪声）的残留**：判据是逐字片段，作者改写（「修好」→「修好了」仍中，「修复」不中）不命中 → 同一拍继续喂。设计上接受（text_match 模块头：宁重勿跳；重复喂方向无害，跳拍破坏就近铁律）。test_dock_nearby.py:53-58 实证推进：原句写入后下一拍顶上。

### 2.3 单行微大纲推演：「修好发电机，回家吃饭」

该句 10 字（≥8 入选、非 meta）→ `outline_nearby` 返回该行 → 三个消费面全部正常工作（dock has_nearby→toward_beat 子句、stitch intent_source=outline、推测 nearby_block）。**能跑，且消耗行为合理**：

- 全串可判片段：「修好发/好发电/发电机/回家吃/家吃饭」5 片（含逗号的片段被弃——逗号天然切成两个语义半拍）；2/3×5≈3.33 → 需 4 片；
- 作者写完「修好发电机」段（3 片全中）仍差 1 片 → **不判已写，继续喂**——很合理：饭还没吃；
- 写到「回家吃饭」→ 5/5 或整串捷径 → 判已写 → `outline_nearby` 返回**空表**。

**单行大纲的固有代价：耗尽即引力场清零**。空表之后：dock 丢 toward_beat 槽（分节编译里该子句整节缺席，挂件降级 landing/ambient/echo）、stitch 意图块整块缺席（转层2 inferred 兜底，若置信达标）、推测丢场景锚。要到作者写下一条（或写满 100 字让反推接管）才恢复。这正是「节拍是消耗品、方向是常量」的架构差异在极端输入下的显影——**单轨合流若以大纲为轨，作者只写一句话时系统在写完这句话后失去全部作者方向供给**。

### 2.4 dock 侧与 stitch 侧消费差异对照

| 维度 | dock（卡舱） | stitch（续写 user 位） | 未来推测（走向卡） |
|---|---|---|---|
| 数据形态 | 列表 `[:2]` 逐行 | `"\n".join(beats)` 连接文本 | 列表 `[:2]` |
| 字数截断 | 行 ≤60 字（outline_nearby 源头截） | 同源同行截断；`build_continue_prompt` 直插**无二次截断**（adaptive_prompts.py:635） | 行 ≤60 字 |
| 措辞框定 | 「几步之外的目的地——碎片只给通往它的**第一步**，不是节拍本身的画面」（:1641） | 「目的地…现在不写它本身——它的场面、事件与对白都留给几步之后，此刻只写通往它路上的画面」（:633-636） | 「通往它路上的**合理一步**，人物此刻在哪/在做什么以此为准，不得与节拍的场景矛盾」（:1289-1291） |
| 联动结构 | `has_nearby` 分节编译 toward_beat 槽位子句（:1692-1705，约束治理编译器） | `intent_source` 分档措辞（outline/request=作者材料框 / inferred=「AI 猜的」框 / baton=承接框，:617-634） | serves_anchor 写入闸（:1258-1270） |
| 切断条件 | `is_bridge`（FIM 中插）切断整块（dock_generator.py 桥接段） | 仅 stitch/continue 吃兜底链；burst/outline/open 各有方向载体不喂（stitch_context.py:249-252） | `_prebeat_projections` 把 beat/after 挡在 dock 取材池（接缝裁剪） |
| 输出侧闸 | beat_overlap（≥4 字重叠丢件，约束登记册） | ghost-guard beat_rush（live，字面比对 `outline_beats` 列表） | — |

**同源保证**：stitch 侧 2026-09-03 特意拆出列表形态 `_nearby_beats_from_outline`——「抢拍代码闸需要节拍原文列表做字面比对，意图块消费 join 后的文本形态——两者同源，同一份计算（防两处各自判定漂移出两个『就近』）」（stitch_context.py:147-151）。任何合流方案都必须维持这处单一计算源。

---

## 3. 跨模块连锁影响（Blast Radius Audit）

### 3.1 `spine.intent` 全消费清单（若废弃该字段，以下全部受影响）

**后端（12 处）**：

| # | 位置 | 消费形态 |
|---|---|---|
| 1 | routes/adaptive/spine.py:64-88,128-148 | PATCH 归一（60 字截断/source 归一/全空归 null） |
| 2 | routes/adaptive/spine.py:151-219 | spine-suggest（1×creative，不落库；上一章 pending 锚点顺延 :159-176） |
| 3 | routes/adaptive/heartbeat.py:71 + schemas.py:28 | HeartbeatRequest.spine_intent（前端上行字段） |
| 4 | routes/adaptive/heartbeat.py:263-378 | 锚点进度判定（hit 写库+防并发合并）——锚点不动则不受影响 |
| 5 | services/adaptive/orchestrator.py:180-185 | spine_updated 变化信号（severity 0.6） |
| 6 | orchestrator.py:316-326 | `spine_hot` 节流豁免（intent 非空+spine_updated → 免 30s 反推节流；注释描述的失败形态=「纠正被无视」） |
| 7 | orchestrator.py:375-377 | **dock 文本签名直接哈希 spine_intent**（`_text_sig(f"{recent_text}|{spine_intent}|wc{word_count}")`） |
| 8 | components/dock_generator.py:404-413,528 | `_spine_intent` 直读 → prompt spine_line |
| 9 | components/intent_inference.py:66,74-85 | **from_spine 短路**（author/0.9/0 LLM） |
| 10 | components/intent_inference.py:228-264 | 意图画像轨迹（前几章 spine intent 的跨章 few-shot） |
| 11 | context/knowledge_plane.py:407-431 | **温卡**（system 位注入五模式） |
| 12 | context/knowledge_plane.py:688-702 | **前缀冻结缓存签名第 5 元 spine_hash**（改 spine 必失效前缀——正确行为，合流后此键必须换成新载体） |

**前端（8 文件）**：useChapterSpine.ts（单例+2s 防抖+correctIntent）、SpinePanel.vue（意图框+岔路编辑器）、InspectorPanel.vue（意图反推行+「不对」手势 :434-459）、WorkspaceView.vue（章首复合谋篇卡+心跳注入 getOutline/spine）、useAdaptiveAssist.ts（心跳 spine_intent 上行 :425；near_branches 硬提示卡 :513-524）、BeatCardDock.vue（⚑ 锚点签 :68-72）、OutlineNoteChip.vue（胶囊挂锚）、InsightsView.vue（协作面板消费 spine 埋点）。

### 3.2 `outline_text` 全消费清单（路径 A 的真实爆炸半径）

**关键事实：大纲不是侧栏私有字段，它是独立页面（大纲板）的数据主干。**

| 面 | 位置 | 消费形态 |
|---|---|---|
| bundle 总线 | settings_bundle.py:311 | `bundle.outline_text`（一切下游的总入口） |
| 心跳变化检测 | change_detector.py:145-146 + orchestrator.py:171-175 | outline 签名对比→强变化信号（可触发反推重算） |
| 意图层2转化 | intent_inference.py:86-97,349-367 | from_outline（author/0.85）+ 卷首致辞过滤 |
| 就近节拍 | outline_nearby.py（唯一计算源） | dock/projection/stitch 三消费面（§2.4） |
| open 模式召回 | stitch_context.py:259 | 无正文时 recall query = outline 前 200 字（STITCH_INTENT_OUTLINE_MAX_CHARS，budget.py:372） |
| **章级向量记忆** | context/loader.py:253-268,371-373 | **outline 全文 embedding 进记忆检索**（大纲是 RAG 数据源，不只是 prompt 素材） |
| 章节优化 | chapter_optimization.py:129,179 | refine 上下文（大纲前 200 字） |
| 完稿审阅 | review_prompts.py:121 | 编辑意见的对照参考 |
| canon 抽取 | canon/extractor.py:343 | 提取候选 canon_text 参考（截 200） |
| **大纲板整页** | OutlineView.vue:87,106,120 | 故事线俯视板章卡**就地编辑**——一个完整页面的存在依赖 |
| 小说向导 | LibraryView.vue:197-208 | 建书向导第 1 章大纲落 outline_text |
| 编辑器容器 | ChapterEditorContainer.vue:74 + useChapterEditorContainer.ts:169-171 | 选区改写 current-context / meta 更新 |
| 遗产引擎 | adf_workflow/beat_patcher/climax_designer/segment_writer + nle_prompts | ADF（引擎本体保留） |

### 3.3 三处缓存/签名依赖的续接分析（合流的硬约束）

1. **dock 文本签名**（orchestrator.py:375-377）：`cur_text_sig = _text_sig(recent_text + "|" + spine_intent + "|wc" + word_count)`——意图纠正瞬间段落没变也 bust 缓存（注释 :368-369「纠正即换向」）。合流后若意图载体变更，此键必须换成新载体文本；**漏改症状=改了方向 Tab 出旧方向零件**。另 projection 签名并入 `intent_version`（:394——反推重算/纠正后旧推测过期）。
2. **前缀冻结缓存签名**（knowledge_plane.py:626-712）：键含 `spine_hash`（spine 整体 JSON 哈希，:692-702）等 9 元，**不含正文**（作者打字不作废前缀——B6 前缀纪律）；刷新点注释明列「spine 变更」（:629）。⚠ **outline_text 不在此签名中**——因为大纲走 user 侧每次现算，不进冻结前缀。合流若把意图迁进大纲侧，前缀签名必须同步考虑（温卡若改为读大纲首拍，签名需加 outline 相关键——否则「改大纲首拍，温卡供旧方向」静默事故）。2026-08-28 审计修复（:630-632）已经历过一次同类事故（同数量内容级世界编辑不换签名→旧档案供到切章），前科在案。
3. **spine_hot 节流豁免锚**（orchestrator.py:321-326）：豁免条件是 `state.spine_intent 非空 + spine_updated 信号`。若纠正手势改落大纲：change_detector 的 outline 签名变化（:145-146）也产信号，但**不在豁免名单**——30s 节流窗口内纠正会被吞，恰好复现注释里描述的「纠正被无视」事故形态。
4. **intent_version 递增**（world_model.py:175，`set_intent` 内 `intent_version += 1`）：source 无关——只要合流后的意图写入仍走 `set_intent`（from_outline 已如此），版本机制与 dock proj 签名的联动**原样保留**，无结构性改动。

---

## 4. 合流架构推演：路径 A vs 路径 B（+证据浮现的路径 C）

### 4.1 路径 A：大纲包容打算（废 `spine.intent`，大纲首个待兑现节拍兼任方向舵）

**代码修改量**（估算，非实施清单）：后端 ~7 文件——spine.py（归一器删 intent 分支）、intent_inference.py（删 from_spine 短路，:74-85；trajectory 数据源改大纲首行，:228-264）、dock_generator.py（删 `_spine_intent`/spine_line 或换料为 nearby 首拍——但 nearby_block 已存在，**同一拍将双份进 dock prompt**，必须再去重）、knowledge_plane.py（温卡删意图行，锚点行保留）、orchestrator.py（spine_sig 检测/spine_hot 豁免重锚到 outline 信号）、heartbeat schemas（删上行字段）；前端 ~4 文件（SpinePanel/useChapterSpine/InspectorPanel 纠正手势/WorkspaceView）；测试至少 test_intent_hardening + heartbeatSeam + dock 相关 3 处。**且大纲侧 14 个消费面（§3.2）全部承受语义变化外溢**（大纲板/向导/loader embedding/refine/审阅看到的「大纲」从此兼任方向舵）。

**破坏性断裂面（七处）**：

1. **方向语义无处安放**：「本章主要写甲发现假信」可凑合转节拍，但「过渡章，放缓节奏」「这章写完两人关系降到冰点」这类**纯方向/纯节奏**意图不是节拍——大纲首拍兼任方向舵会把它们逼成伪节拍或让作者放弃表达。
2. **单行大纲耗尽**（§2.3 实证推演）：作者只写一句话时，写完即引力场清零——这正是合流想解决的「单轨」最常见用法（只写一句）恰恰是路径 A 最脆弱的输入。
3. **纠正手势语义变粗**：「不对」当前=覆写一句话（correctIntent，useChapterSpine.ts:175-182，60 字、source=author、埋点带旧猜测原文）；改落大纲=编辑既有多行文本（改哪行？插到哪？）——手势从「覆写一个字段」退化成「文本编辑操作」。
4. **节流豁免失锚**（§3.3-3）：纠正落大纲不豁免 30s 反推节流 → 「纠正被无视」回归。
5. **0.9→0.85 信度档损失 + from_spine 的 0 LLM 即时性依赖 from_outline 保持**（两者同为短路，此项可平）；但 trajectory 意图画像（学作者写意图的粒度口吻）数据源从 ≤60 字意图句粗化为大纲首行。
6. **违背两次评审确认过的设计红线**（§1.2——08-18 立项红线 + 09 月 canon 迁移再确认）。
7. **dock 双份节拍**：spine_line 换料为首拍后与 nearby_block 首行重复，prompt 内同拍两现，需引入新的去重逻辑。

**作者打字顺手度**：少一个输入框，但写「方向」的心理成本从 D-1 的「一句话趋近于零」升为「写进大纲」（大纲定位=心智成本中、值得认真写）——净体验大概率变差。

**判定：不建议。** 它治疗的是生成层不存在的病（生成层已双向互通），制造的是语义层真实的病（方向表达降维 + 七断裂面 + 14 消费面外溢）。

### 4.2 路径 B：打算升维为即时节拍（保留极简一句话，stitch 直接吃）

两个子形态，差别巨大：

**B1（简单版：把 spine.intent 文本直接塞进 stitch user 位，优先级高于就近节拍）**——弧线文本进「目的地」槽，**08-25 冲章事故的剂量条件原样复现**（事故里的「意图（血噬的觉醒）」正是弧线级一句话；test_dock_nearby.py:5-9）。且与温卡去重纪律冲突（同文本 system+user 双现）。除非配套全套措辞降权，否则等于撤销两次治理的成果。**不建议。**

**B2（完整版：intent 获得「当前正在写的一拍」语义 + hit 消耗）**：

- 语义变更：`spine.intent` 从「章方向」重定义为「手动第一拍」——像锚点一样可判定兑现、兑现即消耗（清空或由作者续写下一句）。
- 技术可行性高，因为**全部基础设施已存在**：
  - hit 判定：heartbeat 的 text_match + growth 窗 + 就近窗口机制（heartbeat.py:250-378）可直接复用于 intent 文本；
  - stitch 兜底链插层：`assemble_stitch_context` 在就近节拍之前加一档「spine 未消耗意图」（框定措辞需新写为「作者正在写这一拍」而非「目的地」）；与温卡去重需同步调整（意图行从温卡迁 user 位，锚点行留 system 位）；
  - dock：spine_line 措辞从「方向参考」改「当前一拍」；签名已含 spine_intent（改文本/清空即失效重算，天然支持消耗换料）；
  - 前缀签名 spine_hash 同理天然续接（intent 变更即失效前缀）；
  - 前端：SpinePanel 意图框加消耗态视觉（锚点 chip 的 hit 基建可参照）。
- **断裂面（三处语义债）**：
  1. **意图双身份**：「方向型」意图（「放缓节奏」）永不 hit → 永驻 user 位 = 慢性弧线剂量（B1 的温和版病灶长期化）。需要逃生门设计（如方向型不进 user 位只留温卡——但这又要求系统判别「这算不算一拍」，判别本身无可靠纯算法）。
  2. 与锚点体系部分重叠：作者心智里「当前一拍」（intent）与「非写不可的情节」（anchors[0]）界限天然模糊——同一句「修好发电机」写意图还是建锚点，两条 UI 通路语义趋同后反而更需要解释。
  3. 60 字意图句 vs 8-60 字节拍行的格式张力（意图常含目的连接词「…然后…」，节拍判定片段化后消耗点难解释）。
- 修改量：中等（后端 4 文件+前端 2 文件+测试），缓存层**零结构性改动**（§3.3 四处全部天然续接）。
- 顺手度：最优——一句话+自动推进+大纲当背景图。

**判定：条件可行**——条件是把「intent 重定义为节拍」当作显式产品决策（含方向型输入的归宿），而不是当作技术打通的副产品。

### 4.3 路径 C（证据自动浮现）：UI 合流、数据层与剂量位不动

§1.3 的现状反转直接推出：作者的真实痛点（「必须维护两个同质化字段」）位于 **UI 呈现层**——InspectorPanel 打算分区里 SpinePanel 意图框与大纲卡上下并排（InspectorPanel.vue:494-549），文案自己都在解释分工（「打算=一句话方向，这里=剧情细节备忘」，:548——需要用文案解释的分工就是认知负荷本身）。

路径 C：把两个输入框合成**一个「叙事引力流」编辑面**（例：首行高亮=当前一拍/方向，下方=后续节拍流），提交时仍分别落 `spine.intent` 与 `outline_text`——生成层三 prompt 位（system 方向软约束 / user 就近目的地 / dock 槽位）的剂量分工是 08-25 事故换来的资产，原样保留。

- 修改量：纯前端 2-3 文件（SpinePanel+InspectorPanel 打算分区重组）；后端零改动；缓存零触碰。
- 断裂面：零（数据契约不变，旧章数据零迁移）。
- 顺手度：与 B2 相当（一个编辑面），且不预支语义债。
- 判定：**首选**——用最低成本先验证「认知负荷」假设本身。

### 4.4 三维度对比总表

| 维度 | 路径 A（大纲包容打算） | 路径 B2（打算升维节拍） | 路径 C（UI 合流） |
|---|---|---|---|
| 代码修改量 | 后端 ~7 文件+前端 ~4+测试 3+，外溢 14 个大纲消费面 | 后端 ~4+前端 ~2+测试 | 前端 2-3 文件 |
| 破坏性断裂面 | 七处（方向降维/单行耗尽/手势变粗/节流失锚/红线违背/dock 双份/画像粗化） | 三处语义债（双身份/锚点重叠/格式张力），缓存零结构性改动 | 零 |
| 作者打字顺手度 | 变差（方向表达升成本） | 最优（一句+自动推进） | 与 B2 相当 |
| 缓存/签名续接 | 3 处需逐点重锚（dock 签名/前缀签名/节流豁免） | 4 处全部天然续接 | 零触碰 |
| 解决的真实问题 | 生成层无此病可治 | user 位方向供给（若确证存在） | UI 认知重复（实证所在层） |

---

## 5. 风险登记与建议

1. **建议顺序：C 先行 → 埋点验证 → 视数据决定是否 B2；A 不做。**
2. **埋点缺口**：当前无法量化「作者是否真的双重维护」——collab_events 有 spine 意图/锚点事件（events.py:43），但 **outline 编辑走 store.updateChapter 无埋点**。任何合流决策前应先补 outline_edit 埋点，用真实重复率（同章 spine_intent_set 与 outline 编辑的时序相关性）验证痛点规模，而非凭感受重构。
3. **缓存续接三原则**（任何动 spine 载体的方案必须逐点核对）：①dock 文本签名键（orchestrator.py:375-377）；②前缀冻结签名 spine_hash（knowledge_plane.py:688-702）；③spine_hot 节流豁免锚（orchestrator.py:321-326）。三处均有明文注释记载事故形态，漏一处=静默失效。
4. **就近节拍单一计算源**红线：`_nearby_beats_from_outline`（stitch_context.py:145-155）与 dock/projection 共用 outline_nearby——合流方案若新增「意图节拍化」路径，必须复用同一模块，禁止另写滑窗（text_match.py:5-18 的历史教训）。
5. **本报告附带勘误**：docs/assist-panel-editables-flow.md 初版「spine 意图不直接进续写」论断有误（漏温卡通路），已于该文档 §1.3/§6-5 就地修正并指向本报告 §1.3。

---

## 附录：证据索引

- 设计与历史：chapter-planning-spine.md:45/§2.3/:59/:258-259 · intent_repository.py:253-255 · 提交 4d992c6（2026-08-25）/e6cd2e7（2026-08-28）/d7337d8（2026-09-03）
- spine→生成：knowledge_plane.py:407-431（温卡）+ adaptive_prompts.py:346（warm 位）+ 五 builder warm_card 形参/传参（:386/:554/:610/:759/:798/:881/:929）· dock_generator.py:404-413,528 · adaptive_prompts.py:1632（spine_line）
- 就近节拍：outline_nearby.py:31-47,50-60,63-87 · text_match.py:31-33,40-57,60-80,83-115 · stitch_context.py:145-166,239-252 · adaptive_prompts.py:617-636,1286-1293,1639-1643,1692-1705 · test_dock_nearby.py:4-9,39-58
- 层2 意图：intent_inference.py:66,74-97,148-152,179-199,202-225,228-264,273-289,349-367 · world_model.py:175（intent_version）· stitch_context.py:169-206
- 缓存/签名：orchestrator.py:171-185,227-238,316-326,368-377,391-408 · knowledge_plane.py:626-712（前缀签名）
- 纠正手势：useChapterSpine.ts:153-182 · InspectorPanel.vue:434-459 · collab intent_correct 回喂 intent_inference.py:307-346
- 大纲消费面：settings_bundle.py:311 · change_detector.py:145-146 · loader.py:253-268,371-373 · chapter_optimization.py:129,179 · review_prompts.py:121 · canon/extractor.py:343 · stitch_context.py:259 · OutlineView.vue:87,106,120 · LibraryView.vue:197-208

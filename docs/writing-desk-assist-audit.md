# 写作台「AI 辅助写作」面审计报告

> 2026-09-12 · 只读全量代码考察（三路并行扫描 + 使用数据分析 + 关键发现人工复核）· 范围：写作台全部 AI 辅助触点（前端交互层 / 状态机层 / 后端 adaptive 链路）· 本报告只诊断不施工。

---

## 0. 一页结论

**「乱」是真的，但乱源不是功能数量，而是三层失控：命名失控、门控失控、遗留失控。** 具体说：

1. **体量与使用完全倒挂**：作者可见的 AI 触点约 30 个、快捷键 17 组、专有名词约 25 个、后端 14 个端点——而全部历史真实交互只有 33 条埋点，其中作者主动动作 8 次（Space 续写 4 次、采纳 1 次）；**九类功能（连写/细纲胶囊/世界速记/点火卡/沉淀/完稿体检/残句修复/切片视角/锚点编辑）从未被真实使用过一次**。所有交互数据都来自开发验证会话。
2. **同一个东西最多有 7 个名字**（卡片舱=SparkDock=灵感悬浮舱=卡舱=挂件=零件=镜头=拼画面），「收件箱」「润色」「检查」「打算」各有 3-4 个互不相干的含义——作者视角的概念地图是碎的。
3. **「AI 辅助总开关」管不住一半的 AI 功能**：关掉它之后，选区 AI 润色/改写、清脂、找灵感、AI 审阅、完稿体检、世界速记、@/# 提及照样能用——开关的实际语义是「管 Space 续写和卡舱」，但 UI 承诺的是「AI 辅助」。
4. **状态机三层叠加且互不同步**：authorLane/aiLane 双轴 + legacy stage 单轴（15 个枚举值里 10 个零赋值死状态仍在参与拦截判断）+ assistEnabled/adaptiveMode 两层布尔——「AI 正在写」这一事实被劈在两条轴上还会互相矛盾（幽灵上屏期间 aiLane 显示 dormant）。
5. **死代码与半死机制成片**：`SPARK_DOCK_AUTO_POPUP=false` 一个常量连坐杀死三处机制但留下 sticky 残留语义；约 20 个死导出/死链/死分支散在核心文件里。另发现 **2 个真 bug**（settle 后端并发守卫恒真——finish 侧同型已修 settle 侧漏修；settling 态无超时可卡死心跳）。

**乱里不乱的部分也要说清**：五档续写模式各自的真实机制差异（检索锚/字数闸/门控）是写作场景逼出来的有意设计；Tab 唯一入口、自动弹舱退役、停顿绿点退役、感知常驻都是明确拍板过的产品决策——**本报告不把这些列为乱源**。乱的是它们周围长出来的残留物。

---

## 1. 使用现状：先看数据

### 1.1 协作埋点（data/collab_events.jsonl，33 条全量）

| 事件 | 次数 | 性质 |
|---|---|---|
| dock_delivered / cards_delivered | 9 / 7 | 被动投递（心跳带回） |
| ghost_discard | 6 | 主动（多为测试中丢弃） |
| batch_accept | 5 | 主动（08-25 通读向导测试，同一秒连发 5 章） |
| ghost_request | **4** | **主动**：continue×1（08-29）+ stitch×3（09-10 微镜头验证会话） |
| context_card（情境浮卡） | 2 | 主动 |
| spine_suggest / spine_suggest_adopt | 1 / 1 | 主动 |
| ghost_adopt | **1** | 主动——**历史唯一一次采纳 AI 续写** |

**埋点词表内零发生**（events.py:33-44）：`card_burst`（Ctrl+Space 连写）、`capsule_create/capsule_expand`（细纲胶囊）、`quick_note`（世界速记）、`ignition`（点火卡）、`settle`（沉淀）、`finish`（完稿体检）、`sentence_fix`（残句修复）、`slice_mode`（切片视角）、`spine_intent_set/spine_anchor_*`（打算是手填的，无埋点）。

### 1.2 LLM 用量（generation_runs）与心跳（trace）

- adaptive 系 LLM 调用共 **33 次**：自动阅读 13、卡舱生发 9、走向推测 7、canon 感知 2、意图反推 1、**stitch 续写仅 1 次落账**（stitch_start 在 trace 里 54 次，其中 **50 次集中在开发测试章** `07136b7a`，日期分布（09-09×14、08-29×6……）与开发验证会话完全重合）。
- 心跳 398 次 / trace LLM 353 次 / salience 影子 345 次——后台机器一直在转，作者没在用。
- 2026-08-15 以来 51 个提交动了 generation/workspace 目录——复杂度增速远高于使用验证速度。

**结论：所谓「乱」的另一半真相是——这是一套尚未被真实写作使用过、但已经按最终形态长全了的系统。** 多数功能的「该不该存在」目前无法用数据裁决（这也是 AGENTS 挂账的 A3b「待真实写作回收」项）。

---

## 2. 全景：作者面对的是什么

### 2.1 触点地图（约 30 个，五类）

**写作动作类（作者按键发起，产出文字）**：Space 续写（顺写/缝合自动分支）、Ctrl+Space 连写、细纲胶囊扩写（Alt+O / `[[`）、点火卡写开头、选区 AI 润色/改写（润色/描写/扩写/压缩/换语气五子模式）、深度清脂（Alt+Shift+↓）、清脂（Alt+↓）。

**感知反馈类（自动出现，只读）**：卡片舱（Tab）、感知带（纸左圆点轨+覆态卡）、canon 词高亮、思考指示器（光标绿点）、AI 状态短句（页头 meta 行八种文案）、幽灵三条浮层（疑点/返修/洗层）。

**世界回流类（AI 读你的文字，产出待确认项）**：沉淀（Ctrl+Enter）、候选收件箱（此刻页）、切章自动阅读、心跳感知常驻、情境浮卡、世界速记（Alt+N）、@/# 提及。

**检查审校类（写完之后）**：完稿体检（报告含残句修复/AI 味变体/情节完成度/秘密穿帮/编辑意见/质感样本/收件箱积压八块）、Refinery 润色（诊断→确认→手术→回读→抛光五段）、读者反馈、AI 编辑审阅（⋯ 菜单）、找灵感。

**观测调参类**：AI 视角面板（健康横幅 + AI 此刻读到的十四块保字排版预览 + AI 眼中的世界）。

### 2.2 交互入口（快捷键 17 组，四处监听器分布）

window 捕获层（useGenerationSession:790-1034）管创作键：Space / Ctrl+Space / Tab / Esc / Enter / Ctrl+Enter / 1-4 / ↑↓ / Alt+O / Alt+↓ / Alt+Shift+↓；WorkspaceView 管面板键：Ctrl+\ / Ctrl+1~5；组件层：Alt+N（速记）/ Ctrl+F（查找）/ 各浮层自己的 Esc。

**快捷键速查表（ShortcutsCheatsheet）与代码的漂移**：漏 Alt+O、漏 `[[`、漏卡舱内 ↑↓、「Esc 逐层退出」漏了走向卡舱这层、「1-4 快速选择」把两个不同的卡舱（数字键语义完全不同：卡片舱=直接开写单镜头，走向舱=选向即写）混在一条描述里、「Space 接着写」没说空段/未激活时不触发、自注释还写着已退役的「顶栏?按钮」。

---

## 3. 状态机解剖：四层东西在同时管「AI 是否在工作」

| 层 | 位置 | 语义 | 问题 |
|---|---|---|---|
| `assistEnabled` | useAssistEnabled.ts:23（localStorage 持久） | 总开关 | **管不住一半 AI 功能**（见 §6-E） |
| `adaptiveMode` | useGenerationSession.ts:233 | 本章是否进过 adaptive | 与 assistEnabled 关联松散：关 assist 会连坐 exitAdaptive，重开不会自动回 |
| `authorLane`（4 态） | :229 | 作者侧：idle→composing→ghostStitching→settling | settling **无超时**；心跳只认 composing |
| `aiLane`（6 态） | :231 | AI 侧：dormant→perceiving/suggesting/assisting/digesting/analyzing | 与 authorLane **不同步**：幽灵上屏期间（authorLane=ghostStitching）aiLane 已回 dormant；suggesting 判据是卡片舱可见、文案却说「走向卡备好了」 |
| `stage`（legacy 15 态） | :117-132 | 旧单轴，只剩 idle/auditing/refining/error/done 5 个活值 | **10 个枚举零赋值**却仍参与 inAuthoringContext/gate 拦截判断（beat_authoring 等死分支）；文件头注释还在宣称完整的旧状态机 |
| `stitching` / `authoringEnabled` | :277/:274 | 旧布尔 | **恒 false**，三处守卫恒通过，纯遗留 |

**一个概念三处复用**：「perceiving」同时是 aiLane 状态（顶栏「AI 正在看你写的」）、thinkingPhase（光标绿点）、注释术语——三条代码路径独立驱动，互不校准。

**幽灵生命周期**（9 类入口写它）：begin/append/materialize/commit/evaporate/reap/三条数据灌入/authorLane 联动/展示消费——设计是完备的，但 `ghostEndReason` 的 commit/other 分流唯一消费者包在恒 false 的 `SPARK_DOCK_AUTO_POPUP` 里，**分流已死**；缝合时仍执行的 `setSparkSticky()` 承诺的「落定回弹」也已死，sticky 只剩「打字不隐藏」副作用且滞留 true 到下一次 Esc。

---

## 4. 五档续写模式：机制差异是真实的，命名是失控的

后端五模式（stitch/continue/burst/outline/open）真实差异表（考察核实，详见附录 A）：检索锚不同（光标前文 800 字 / 胶囊双端 500+300 / 大纲整章）、目标字数差一个量级（50 / 200 / 400 / 700）、字数闸形态不同（微镜头免压缩 / 两级压缩 / 保尾双闸 / 点火剂量闸）、门控不同（复读剥离/白描封杀令/主体锁/texture 双轨只开 stitch+continue；beat_rush 闸素材 burst 豁免——「本职就是写节拍」）。

**这些差异本身是合理设计**。失控的是命名：同一族动作在 UI 上叫「顺写/拼画面/连写/细纲/写开头」（AI 视角预览），在键位描述里叫「接着写/缝合/多段连写/落笔扩写/写个开头」，在代码注释里叫 continue/stitch/burst/outline/open——**两套中文词对不齐**，且「拼画面」这个词只在 AI 视角预览出现，作者在别处永远遇不到它。

---

## 5. 「乱」的实证清单（分六型，全部 file:line 复核）

### A. 命名失控（一物多名 / 一名多物 / 黑话上屏）

| # | 事实 | 证据 |
|---|---|---|
| A1 | **SparkDock 一物七名**：灵感悬浮舱（SparkDock.vue:3）/卡片舱/卡舱（WorkspaceView.vue:9）/挂件（useSparkDock.ts:9）/零件（useGenerationSession.ts:293）/镜头（UI hint）/拼画面（ContextPreviewSection.vue:46，与 stitch 模式对应） | 代码注释+UI 文案各说各话 |
| A2 | **两个「卡舱」**：卡片舱（SparkDock，句级镜头，Tab 唤起，行间推挤布局）vs 走向卡舱（BeatCardDock，段落走向，Ctrl+Space 唤起，仍是 fixed 浮层布局）——同名不同物、同布局范式不统一、数据却同源于心跳链路（setBeatCards，useAdaptiveAssist.ts:518） | useBeatDock.ts 全文件 |
| A3 | **「收件箱」一名三义**：世界候选收件箱（此刻页）/文风收件箱（「这不像我」投递目标）/检查报告里的收件箱积压块；感知带 world_inbox 提醒也叫收件箱 | InspectorPanel.vue:766、RichTextEditor.vue:220、PerceptionBand.vue:65 |
| A4 | **「润色」一名四义**：Refinery 全流程/选区浮窗「AI 润色」子模式/aiStateLabel「润色中…」（=refining 态）/Refinery 内部「定稿润色」阶段；幽灵的禁忌词替换又叫「洗层」 | InspectorPanel.vue:817-862、RichTextEditor.vue:1197、WorkspaceView.vue:669 |
| A5 | **「检查」一名四义**：分区名/「完稿体检」按钮/报告块（检查报告、编辑意见、检查结论——后两者与体检是不同后端来源）/「正在检查全文…」（实为 Refinery 诊断态） | WorkspaceView.vue:670、InspectorPanel 多处 |
| A6 | **「打算」一名四义**：面板分区名/谋篇体系（spine）/点火卡意图输入/检查报告「打算」附注块 | SpinePanel.vue:105、InspectorPanel.vue:734 |
| A7 | **「黄金片段」按钮与产物名漂移**：按钮叫黄金片段，toast 说「已存进文风样本库」 | RichTextEditor.vue:177,184,1160 |
| A8 | **菜单与弹窗名不一致**：「找找灵感」vs 弹窗「找灵感」 | ChapterEditorView.vue:164、InspirationModal.vue:102 |
| A9 | 黑话直接上屏：蒸发/锁死/洗层/清脂/沉淀/完稿体检/落笔扩写/锚点/岔路/建档——部分有解释部分没有 | 各组件 |

### B. 入口与反馈乱（静默失败 / 吞键 / 门槛缝隙）

| # | 事实 | 证据 |
|---|---|---|
| B1 | **空章按 Tab 完全无反馈**：激活需 ≥4 字（WorkspaceView.vue:724），激活静默失败后 summonParts 照发、心跳被 authorLane 守卫静默拦下（useAdaptiveAssist.ts:335）——作者不知道为什么没反应 | 三层静默叠加 |
| B2 | **1~3 字缝隙**：点火卡要求正文全空、激活要求 ≥4 字——打了 1~3 字时两者都不覆盖（无点火卡、无 adaptive） | WorkspaceView.vue:288-296 vs :724 |
| B3 | **Space 空文档静默**：requestContinue 空 fragment 静默 return 无任何反馈 | useAdaptiveAssist.ts:712 |
| B4 | **Ctrl+Enter 吞键**：不满足沉淀条件时仍 preventDefault 且无动作（如 assist 关但幽灵在屏） | useGenerationSession.ts:969-971 |
| B5 | **走向舱非 composing 数字键吞动作**：按键关舱且不出稿无提示 | useGenerationSession.ts:903-913 |
| B6 | **burst 鼠标路径无门控**：点击走向卡直接 requestBurst，不查 adaptiveComposing/assistEnabled（键盘路径查）——同一动作两路径守卫不对称 | WorkspaceView.vue:196-204 vs :909-911 |
| B7 | **细纲 `[[` 无门**：Alt+O 有 assistEnabled+聚焦+无幽灵三重门，`[[` 输入规则无任何门 | OutlineNoteNode.ts:173-188 |
| B8 | **走向舱打字即关**未在 UI 提示（提示只说「按数字键选 · Esc 关闭」） | useBeatDock.ts:44-46 |

### C. 状态机乱（死状态 / 不同步 / 残留语义）

| # | 事实 | 证据 |
|---|---|---|
| C1 | stage 10 个枚举零赋值仍参与拦截判断；文件头注释宣称完整旧状态机 | useGenerationSession.ts:117-132,861-867 |
| C2 | `stitching`/`authoringEnabled` 恒 false 三处守卫恒通过 | :277,:274 |
| C3 | aiLane 与 authorLane 不同步（幽灵在屏 aiLane=dormant） | useAdaptiveAssist.ts:681 |
| C4 | suggesting 判据（卡片舱可见）与文案（走向卡备好了）错位 | :570 + WorkspaceView.vue:661 |
| C5 | ghostEndReason 分流死 / sticky 回弹承诺死（详见 §3） | useSparkDock.ts:117,184-191 |
| C6 | 「perceiving」三处复用互不校准 | §3 |
| C7 | error ref 双用途冲突（清脂失败写同一 error 且 3s 自清，与「存活到 stage 离开」注释矛盾） | useGenerationSession.ts:781-782 |
| C8 | 疑点 kind 双轨：canon_leak「秘密穿帮」与 secret_leak「秘密外泄」并存（07 期改名残留） | useGhostDraft.ts:63-64 |
| C9 | 面板默认分区 5 处写 activeTab（推导/补切/切章复位×2/三个 watch 抢切） | InspectorPanel.vue:96-132 |

### D. 死代码与半死机制

死导出/死链清单（约 20 项）：`chapterTargetWords`、`ghostDirty`、`ghostSource`（死 import）、`insertMarkedText`、`useGhostDraft()`/`useBeatDock()` 包装、`isTerminal/cancel/reset/retry`、`engine/finalStats`、`dynamicBeats`（恒空仍上行 segment_count）、`verdictLabel`、`chapterEditorRef`、`anchorPov`、`refresh-characters` 事件链、`metaCollapsed` 四层穿透、`.char-list` 遗留 CSS、`_partsForContext/_contextKey/_recentText500`（只服务死秒弹分支）、`commitGhostFragment` 的整套 NLE-ADF 2.0 残留空转（fragmentSnapshots/beatBaseStack 等 6 组）、InspectorPanel fallback 双实例隐患（props 断供会双挂 window 键位监听）。

### E. 门控不一致（assistEnabled 的真实边界）

关掉「AI 辅助总开关」后**仍可用**的 AI 功能：选区「AI 润色/改写」、黄金片段、这不像我、记改前/记改后、Alt+↓/Alt+Shift+↓ 清脂（**不查 assistEnabled**）、⋯ 菜单的找灵感/AI 审阅/全文格式整理、检查面板全部按钮（完稿体检按钮的 disabled 文案写的是 composing 门槛）、@/# 提及、Alt+N 世界速记、Ctrl+F。而编辑器 placeholder 在 assist 关闭时仍显示「Space 让 AI 接着写」。**总开关的真实语义=「管 Space 续写+卡舱+心跳感知」，与其名字承诺差距巨大。**

### F. 后端不对称与真 bug（人工复核确认）

| # | 事实 | 严重度 |
|---|---|---|
| F1 | **settle 的 sediment 并发守卫恒真**：`"sediment" not in self._active_tasks`（orchestrator.py:576）——sediment 走同步直调从不进 _active_tasks；**finish 侧同型 bug 已修**（_finish_in_flight，:626-633 注释自认），settle 侧漏修。当前被前端 authorLane=settling 挡住，属遮蔽中的真缺陷 | 中 |
| F2 | **settling 无超时**：settleCurrent 的 HTTP 请求若悬挂，authorLane 卡 settling → 心跳守卫全停（useAdaptiveAssist.ts:748-790,335） | 低概率真实 |
| F3 | 返修环后处理不含 burst/open 的字数截断（_postprocess_repair_draft 只处理 stitch/continue/outline 三档，gates:340-365）——返修稿可能超字数上屏 | 低 |
| F4 | burst/outline 的意图块仍是旧措辞「章节意图（方向参考，非强制）」，未接 intent_source 分档——层 2 兜底虽只对 stitch/continue 开，但大纲节拍兜底对 burst/outline 同样命中，同样存在「节拍被当场面写」的原始病灶（prompts:761,892） | 低 |
| F5 | 切除豁免 docstring 与代码不符（写 stitch/continue/burst，代码含 open，gates:384 vs :417） | 文档 |
| F6 | preview 的 selected_keys 被 schema 静默丢弃；前端未类型化 unselected | 死数据 |
| F7 | rolling 窗 cap 双写（stitch.py 与 preview.py 各一份同式，2026-09-04 曾因此漂移过一次） | 维护面 |
| F8 | 写作台版 QuickEventNote 的 Esc 不 preventDefault——**世界页同组件已修过的「一次 Esc 两层同关」bug，写作台版未同步**（workspace/presentation/QuickEventNote.vue:199-201 vs world/presentation/:87-94） | 中 |

---

## 6. 收敛方向（分层建议，供拍板，未施工）

### 第一层：零风险清理（不动任何产品语义，纯除残）

1. 删死代码：stage 死枚举及其拦截分支、stitching/authoringEnabled、§D 清单全部、遗留 CSS、死事件链；
2. 补修两个真 bug：settle 并发守卫对齐 finish 侧；写作台 QuickEventNote 的 Esc 对齐世界页版；
3. 注释对齐现实（useSparkDock/useBeatDock/session 文件头/useGenerationSession 状态机注释）；
4. 快捷键速查表按 §2.2 重写（补 Alt+O/`[[`/↑↓、区分两个卡舱、写明 Space 真实门槛）。

### 第二层：命名统一（一次拍板，全局改词）

建立「作者词汇表」，每概念唯一名（建议）：**卡片舱**（SparkDock 一族全部归这个词，废 挂件/零件/灵感悬浮舱/拼画面）、**走向卡**（BeatCardDock 改叫「走向卡面板」避免「卡舱」混淆）、**续写**（Space 一族，缝合/顺写是它内部的自动分支不上屏）、**收件箱**加定语（世界收件箱/文风收件箱）、**润色**归 Refinery 独占（选区功能改叫「改写这段」）、**完稿体检**与「检查报告」统一、「打算」保留在面板分区+谋篇两处（可接受）。

### 第三层：产品决策（需要用户拍板，本报告不预设答案）

1. **总开关的边界**：assistEnabled 到底管什么？建议二选一——(a) 名字改为「续写辅助开关」如实反映现状；(b) 扩权为真总开关（关=全部 AI 入口禁用）。现状是最差的状态：承诺大、实际管得少。
2. **两个卡舱是否合并入口**：Tab（句级镜头）与 Ctrl+Space（段落走向）语义相邻、布局范式已分裂（行间推挤 vs fixed 浮层）——合并成一个舱两栏，还是保持两键但统一布局范式。
3. **五档模式在 AI 视角预览的呈现**：五个胶囊是否降为「跟随最近一次实际动作自动选档+可手动切换」（上一轮讨论过）。
4. **零使用功能的去留**：连写/细纲/点火/完稿体检/速记九类零使用——不急着砍（数据都是开发会话，真实写作未开始），但可以设一个「真实写作 N 章后复盘」的检查点。

---

## 附录 A：五模式机制差异速查（后端考察核实）

| 维度 | stitch 拼画面 | continue 顺写 | burst 连写 | outline 细纲 | open 写开头 |
|---|---|---|---|---|---|
| 入口 | Space（有吸附） | Space（无吸附） | Ctrl+Space | 胶囊扩写 | 点火卡 |
| target | 50（微镜头免压缩） | 200 | 700 | 速记解析 100-800 缺省 400 | 700 |
| rolling 窗 | 800 | 800 | 1200 | 1200 | 不消费 |
| 检索锚 | 光标前文+零件 | 光标前文 | 光标前文 | 胶囊前 500 后 300 | 大纲前 200 字 |
| 意图兜底 | 请求→节拍→层2 | 同左 | 请求→节拍 | 节拍+锚点行 | 节拍（剂量闸） |
| 复读剥离/白描令/主体锁/texture 双轨 | ✅ | 除复读剥离 ✅ | ❌ | ❌ | ❌ |
| 字数闸 | 微镜头单级 | 两级压缩 | 两级 | 保尾双闸 | 两级+点火剂量闸 |
| 样本 k | 2 | 2 | 3 | 2 | 2 |

## 附录 B：方法与可信度

三路并行只读考察（前端状态机/前端 UI 层/后端链路，行号为 2026-09-12 工作区实况）+ 使用数据三方核对（collab_events 33 条全量、generation_runs 按阶段聚合、trace 1303 事件按章/按日分布）+ F1/F2 及全部「bug 级」定性发现经人工复核源码确认。命名/文案类发现逐条有 file:line；「有意设计」与「失控复杂度」已区分标注（Tab 唯一入口、自动弹舱退役、停顿绿点退役、感知常驻、五模式机制差异均属前者，不列入乱源）。

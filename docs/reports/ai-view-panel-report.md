> **归档说明（2026-09-19）**：面板全景调研（2026-09-14），是简报化施工的输入；§12 所列三处漂移在 09-15 施工后已修，引用前需复核。

# 「AI 视角」侧栏调研报告

> 调研对象：写作台右缘「AI 视角」面板（截图所示：AI 此刻读到的 + 分组折叠块 + 模式五档 + AI 眼中的世界）。
> 调研日：2026-09-14。行号锚点以当日 HEAD 为准。设计权威：`docs/design/ux-redesign/09-ai-view-redesign.md`（09 期重设计）；出身文档：`docs/reports/foundation-hardening.md` §2.1（P5 B2「AI 所见预览」）。

## 0. 三句话结论

1. 这不是普通侧栏，是 **stitch-ghost 上下文装配的只读镜像**：后端 `GET /adaptive/context-preview` 与真实续写共用同一个装配函数 `assemble_stitch_context` + 同一个渲染函数 `render_system_blocks`（同源红线写死在代码里，禁止平行实现），作者在面板里看到的每一块，就是 AI 续写时 system prompt 里注入的每一个字，且**全程零 LLM 调用**。
2. UI 上 14 个块按真实注入序切成三段（事实与设定 / 约束与记忆 / 文风与笔感），每块默认折叠只留「头行仪表盘」（标题/字数/来源/预算占用条），展开是**保字排版**（`contextBlockFormat.ts` 解析，字不增不删，另有「原文」等宽逐字核对逃生舱）。
3. 本次调研发现三处**非功能性但真实的漂移/缺口**：前端 `ContextPreviewBlock.key` 类型联合停留在 P5 时代（7 键 vs 实际 14 键）；后端产出的 `selected_keys` 字段被 response schema 静默丢弃；知识平面「未选清单」（`unselected`）已下发但前端从未消费——预览的审计闭环只建成了一半。详见 §12。

---

## 1. 定位与演化史

「AI 视角」是写作台助手面板（`InspectorPanel`）的第五分区（内部 key=`debug`，历史名「调试」），回答的问题只有一个：**AI 接下来写的时候，到底读到了什么**。

演化三阶段：

| 阶段 | 时间 | 内容 |
|---|---|---|
| P5 B2 出生 | 2026-08-21 前后（`docs/reports/foundation-hardening.md`） | 从 stitch 路由抽出共享装配器 `stitch_context.py`，预览与注入同源；初版 7 块平铺 |
| 知识平面 v3.1 | 2026-08-27 | 块从 7 个扩到 14 个（场景身份/温卡/实体/世界观/关系/禁词五块由 `knowledge_plane.py` 预渲染），预算器上线（A3b） |
| 09 期重设计 | 2026-09-12（提交 `b6f064c`） | 「去大按钮、块默认折叠、保字排版、注入序三段分组、空块补录引导」——即截图形态 |
| 第三弹接流 | 2026-09-14（提交 `44fb841`） | 场景身份块支持光标派生取景（`active_scene`），预览随装配自动获得 |

## 2. 界面解剖（截图逐项 → 代码）

### 2.1 宿主结构：右缘栏 + 浮出面板

```
WorkspaceView.vue
├── AssistRail.vue          44px 右缘图标栏（AI 辅助总开关✨/打算/此刻/本章/检查/AI 视角🔍/？）
└── InspectorPanel.vue      浮出面板 min(380px, 44vw)，单分区壳（一次只渲染一个分区）
    └── debug 分区 = 本报告对象
```

- 栏与面板同构世界页「栏—面板」心智：点击开、再点同区收、一次一格（`WorkspaceView.vue:506` `onRailSelectTab`）。
- 快捷键：**Ctrl+5** 直达 AI 视角（`WorkspaceView.vue:560-584`，`PANEL_TAB_ORDER` 第 5 位）；**Ctrl+\** 三态 pin（关→开并钉 / 开未钉→钉 / 已钉→收并解钉）；面板开着时 Ctrl+1~5 由 `InspectorPanel` 自身监听切区，两路汇于同一 `activeTab` 状态（无双源）。
- 关闭路径：Esc（未钉时收；焦点在 input/textarea/面板内编辑区不收——`WorkspaceView.vue:528-534`）、外点收（未钉时，点在面板/栏/模态之外，`WorkspaceView.vue:547-555`）、面板头 ×。
- pin 态持久化：`uiPrefs.rightDrawerOpen`（localStorage，经 `useUiPrefs`；语义=「钉住」，钉住态跨会话恢复即开着，`WorkspaceView.vue:474-475`）。
- 截图右上角两个小图标：**图钉**（pin，非「设置」滑杆）+ **×**（收起）——`InspectorPanel.vue:543-553` 面板头。

### 2.2 debug 分区纵向三件套

`InspectorPanel.vue:894-959`：

1. **组件健康横幅**（条件渲染，有错才出现）：「N 个辅助功能最近出错」，点开见明细（组件名/相对时间/错误详情），成功即清自动消失。数据源是 `useAdaptiveAssist.ts:45` 的模块级单例 `componentErrors`——心跳响应持续回填，`/adaptive/model` 也会带回同一份（per-orchestrator 内存态，进程重启归零）。组件名→人话映射 7 个（方向猜测/走向推测/卡舱供件/世界感知/设定整理/完稿体检/世界发现，`InspectorPanel.vue:259-267`）。
2. **「AI 此刻读到的」主件**（`ContextPreviewSection.vue`，纯展示组件，数据获取在容器）——下文 §3-§9 全是它。
3. **「AI 眼中的世界」折叠卡**（面板底部）：点开拉 `GET /adaptive/model` 世界模型快照，前端拼结构化摘要四行——方向（来源人话化：inferred=「AI 猜的」/author=「你写的」/outline=「大纲」/baton=「上一章接力」）、事实 N 条（最近 5 条各截 50 字；`fact_count` 只计活事实——画布即事实源纪律）、走向 3 条（滤掉 dock/canon_watch 内部投影）、已整理字数（`InspectorPanel.vue:333-359`）。

### 2.3 主件内部（截图从上到下）

| 截图元素 | 代码 | 说明 |
|---|---|---|
| 标题「AI 此刻读到的」+ 副句「AI 续写时读到的，就是下面这些字。空着的块 = 这次用不上。」 | `ContextPreviewSection.vue:182-183` | 承诺即契约：所见=所注入 |
| 「**2,031** 字」汇总 | `sum-total`（:105） | `total_chars` = 14 块 chars 之和 |
| 「原文」圆钮 | `sum-raw`（:190-201） | 全部块正文切等宽逐字直出，信任逃生舱（不持久化） |
| ↻ 刷新钮 | `sum-refresh`（:196-201） | 按当前正文与设定重新装配（loading 时图标旋转） |
| 「第2177年5月19日 · 来自本章固定 · 设定来自世界页」 | `sum-line2`（:204-208） | 叙事时间四级来源（本章锚/上一章锚/最新事件/空世界）+ world 桥接是否生效——作者一眼知道设定数据走的是世界页还是旧章表 |
| 模式五档：顺写/拼画面/连写/细纲/写开头 | `MODES`（:44-50） | continue/stitch/burst/outline/open，各带 title 提示检索锚差异；点击切档即重拉 |
| 三段小标题：事实与设定 / 约束与记忆 / 文风与笔感 | `SEGMENT_TITLES` | 沿真实注入序切段，**不重排** |
| 块卡头行：▸ 标题 · 「N 字 · 来源」 | `blk-head`（:260-263） | 头行即仪表盘；来源徽标人话化见 §4 |
| 头行下 2px 预算占用条 | `blk-meter`（:265-270） | 超支变红 + 「预算超支，N 条 → M 条」红字 |
| 块正文（展开后） | `blk-body`（:271-300） | grid 0fr→1fr 展开动画，无嵌套滚动（滚动交给面板整体） |
| 空块单行虚线「还没录」+ 补录引导 | `blk-empty`（:253-257） | 见 §9 |
| 底部「AI 眼中的世界」 | §2.2 第 3 件 | |

**截图与代码的一致性核验**：截图《弦上灰》书 `world_sourced=true`（设定来自世界页）→ 有知识平面实体块 → `proper_nouns`（实体称呼）块被去重缺席；spine 未写 → `warm`（本章打算）块缺席。截图 12 个可见块与代码推导完全吻合（§4 全表 14 块）。

### 2.4 数据获取生命周期（容器侧，`InspectorPanel.vue:280-322`）

- **进区自动装配一次**：`activeTab` 变为 `debug` 且无数据时自动拉（拉过即不再自动拉，之后靠手动刷新——预览是快照不是直播，这是有意的：装配有成本，且正文每秒都在变）。
- **切章复位**：`selectedChapterId` 变 → 预览数据/错误/世界模型全清；仍在本分区则自动重拉一次。
- **模式切换**：已有数据/已出错才重拉（首拉未完成时点击只改档不重复发）。
- 重读体验：旧列表半透明冻结 + 顶部扫描条（`isReloading`），布局零跳动（:114-116、:243-247）；首次加载是三段骨架屏（:225-234）；失败是错误条 + 重试（:236-239）。
- 折叠态与「原文」开关都是**组件内状态，不持久化**——切章/新数据到达即复位（默认只展开「场景身份」块：恒居注入序首位且短，让保字排版第一眼可见，:70-83）。

---

## 3. 数据链路与「同源红线」

```
ContextPreviewSection（纯展示）
  ↑ props
InspectorPanel.loadContextPreview()                    [InspectorPanel.vue:287-299]
  ↑
adaptiveApi.contextPreview(chapterId, mode)            [adaptive.api.ts:334-339]
  = GET /api/chapters/{id}/adaptive/context-preview?mode=…（缺省 continue）
  ↑
routes/chapter_generation/adaptive/preview.py:43-90    ★ 路由层只做三件事：
  ① mode 白名单校验（422）
  ② rolling_prefix 构造：落库 HTML → 剥纯文本 → 句界净截（mode-aware cap：
     stitch/continue=800 / burst·outline=1200 / open=0 即空串）
  ③ 调共享装配器 → 显式构造 response model
  ↑
assemble_stitch_context()                              [stitch_context.py:219-361]
  —— 与 stitch-ghost 路由（stitch.py:143）共用同一函数
  ↑
ctx.system_blocks_with_usage()                         [stitch_context.py:127-143]
  = adaptive_prompts.render_system_blocks_with_usage   ★ 注入序唯一权威
  ↑
build_context_preview(ctx, mode)                       [stitch_context.py:433-467]
  —— (key, content) 列表 → JSON 块（title/source/chars/budget_chars/trimmed）
```

**三条防漂移设计**（这是本面板最值钱的工程约束）：

1. **装配同源**：预览路由与 stitch 路由共用 `assemble_stitch_context`——不存在第二份装配逻辑（`stitch_context.py` 模块头「防漂移红线」；预览只是 `fragment=""` 的特殊调用）。
2. **渲染同源**：块文本由 `render_system_blocks_with_usage` 产出，与五个 stitch builder 拼 system prompt 用的**同一个函数、同一份参数**（`StitchContext._kg_kwargs` 保证 kg 块参数同源同参，`stitch_context.py:102-104`）。
3. **预算同源**：占用条数据来自 `allocate` 的 usages（A3b）——预览即调参界面，被裁事件与真实注入同源（`budget.py:529-542`）。

装配器内部七步（`stitch_context.py:243-361`）：① `load_chapter_settings_bundle`（章级绑定+Canon+世界观+world 桥接全套）→ ② 意图解析（请求自带 > 大纲就近节拍 > 层 2 inferred/baton 兜底，仅 stitch/continue）→ ③ 前情召回 `recall_memories`（query=正文尾 150 字+碎片；open 模式=大纲前 200 字；V/B 流抹在场实体名去敏）→ ④ 文风执行层（画像渲染 + 样本检索 k≤2/burst 3，对话场景加成）→ ⑤ 光标派生取景 `resolve_active_scene`（rolling+fragment 逆扫转场动词，失败静默 None）→ ⑥ 知识平面 `build_knowledge_view`（条目化→选择→渲染，前缀章内冻结缓存）→ ⑦ 称呼表按可见文本过滤 `scene_visible_proper_nouns`。

---

## 4. 十四块清单（截图块的完整身世）

注入序 = 返回序 = 面板显示序（`adaptive_prompts.py:344-369`）。三段映射在 `contextBlockFormat.ts:32-47`。

| # | key | 标题 | 段 | 数据源（最终出处） | 来源徽标（前端人话化后） | 配额 | 硬度 |
|---|---|---|---|---|---|---|---|
| 1 | scene | 场景身份 | 事实 | `knowledge_plane` 场景身份块：场景钉+叙事时刻+地点档案；第三弹起可光标派生（预览恒按章节尾派生，见 §11） | 场景钉 + 时间锚 | — | KG 硬层 |
| 2 | warm | 本章打算 | 事实 | spine 意图+锚点温卡（章内冻结，B6 前缀纪律） | 打算 tab（章内不变） | — | KG 硬层 |
| 3 | entities | 在场与相关 | 事实 | 知识平面实体条目：world 桥接实体（含档案全文+〔此刻〕状态）或旧章级绑定 | 世界页 · 实体档案 / 章节旧表（未接世界页） | — | KG 硬层 |
| (3b) | proper_nouns | 实体称呼 | 事实 | `scene_visible_proper_nouns`：在场∪死亡∪本章提及∪可见文本点名；**有实体块时被去重缺席**（名字已含于实体条目） | 世界页 · 实体 / 章节旧表 | 420 | 硬块 |
| 4 | canon | Canon 图谱 | 事实 | `build_canon_context_for_prompt` 三段（[private]/[public]/[hook]）；含字段级真相分层的虚拟条目 | 真相账本（含私有）/真相层 | 5480 | 硬块 |
| 5 | secrets | 私有设定 | 事实 | `bundle.character_secrets`（A1 私有通道：visibility=private 实体档案，上限 8 条×150 字） | 世界实体 · 私有设定 | 1400 | 硬块 |
| 6 | worldview | 世界观 | 事实 | `books.worldview_settings` 条目完整注入 | 世界页 · 世界观 | — | KG 硬层 |
| 7 | relations | 人物关系 | 事实 | `world_relations` t 时刻活跃关系 | 世界页 · 关系（t 时刻活跃） | — | KG 硬层 |
| 8 | negative | 禁词约束 | 约束 | `prohibitions` 四源合并（负面清单+黑名单+系统陈词+反 AI 词表），user 尾部重钉「不用X——改用Y」 | 文风页负面清单 + 系统陈词 | — | KG 硬层 |
| 9 | echoes | 前情回响 | 约束 | `recall_memories` 向量召回（k=3，各≤160 字） | 记忆召回 | 545 | 软块（最先裁） |
| 10 | spatial | 空间常识 | 约束 | `spatial_brief`（books.map_scale 比例尺换算，≤300 字） | 世界比例尺 | 325 | 软块 |
| 11 | style_positive | 文风画像 | 文风 | `render_style_positive`（文风卡画像 ≤10 行；2026-09-14 去参数化后 14→10 行、块配额 2020→1460） | 文风卡 | 1460 | 软块（成段最后裁） |
| 12 | author_samples | 笔迹示范 | 文风 | `retrieve_author_samples_with_meta`（k≤2/burst 3，各≤1200 字；对话场景同型加成；drift_anchor 收藏加成） | 文风样本库（· 优先对话段） | 2500（burst 3750） | 软块 |
| 13 | anti_pseudo_sensory | 白描封杀令 | 文风 | 常量文案 `_ANTI_PSEUDO_SENSORY_BLOCK`（**仅 stitch/continue 两档注入**，其余模式空串） | — | — | — |

设计理由（`adaptive_prompts.py:308-322` docstring）：**事实层全前于文风层**——中档模型对 prompt 中部遗忘，连续性事实必须占据 primacy 位（`docs/knowledge-retrieval-plane.md` §6）。

**预算器**（`budget.py:413-500`）：

- 每模式总预算 = Σ七块配额 12650（burst +1250 吸收 k=3 样本加量）；默认路径 allocate 是**恒等操作**（初值=各块 worst-case 总和，注入逐字节不变，`test_budget_allocate` 零变化锁）。
- 裁剪序（软块从尾往前收缩）：echoes → author_samples → spatial → style_positive；硬块（canon/secrets/proper_nouns）永不裁，宁可总注入超支。
- 知识平面五块+温卡+白描令**不进 allocate**（硬层无预算裁剪），唯一体量约束是 `KG_BUDGET_CHARS=16000` 逃逸阀——按 养料→软 顺序**丢整条不腰斩**，丢弃记录进 `unselected`（见 §12-F2：该记录前端未消费）。
- 面板预算条只对 `budget_chars>0` 的块显示；占用 >90% 变红（`contextBudget.ts:19-24`）。

---

## 5. 模式五档的真实差异（预览切档到底换什么）

| 档 | key | rolling 窗（预览侧） | 召回 query | 样本 k | 白描令 | 总预算 |
|---|---|---|---|---|---|---|
| 顺写 | continue | 800 | 正文尾 150 字 | 2 | ✔ | 12650 |
| 拼画面 | stitch | 800 | 正文尾 150 字+碎片（预览碎片恒空） | 2 | ✔ | 12650 |
| 连写 | burst | 1200 | 同上 | **3** | ✘ | 13900 |
| 细纲 | outline | 1200 | 同上 | 2 | ✘ | 12650 |
| 写开头 | open | **0（空串）** | **大纲前 200 字** | 2 | ✘ | 12650 |

（预览 rolling cap 的 mode-aware 补齐是 2026-09-04 修复：此前预览对所有模式统一 1200，而 stitch/continue 真实注入只有 800——称呼表过滤/场景判定两端口径不一致，预览可能显示真实注入里被过滤掉的名字，`preview.py:59-62` 注释在案。）

其余模式差异在任务指令（五个 builder），不在知识块——**知识供给任务平权**（知识平面公理二：任何生成调用不再有「轻档少知道」的合法路径）。

## 6. 保字排版解析器（「看到的字 = AI 读到的字」的 UI 保障）

`contextBlockFormat.ts`（09 期 §5 落地，19 项对拍 `__tests__/contextBlockFormat.test.ts`）：

- **红线**：块 content 是后端 `render_system_blocks` 的字面 prompt 文本，解析成排版节点树时**除结构标记外（行首 #/##、"- "、场景行 ｜、缩进、换行）任何字符不增不删不改写**；内联标记（【…】〔…〕）只做样式包裹。
- 行级保守：只认确定形态（heading/item/profile/note/kv/sample），不确定落 plain（衬线原样渲染）；「原文」开关是逐字核对的逃生舱。
- 保字不变式进测试契约：`flattenNodes` + `normalizeForInvariant`（摊平归一后与原文本逐字符等价，`contextBlockFormat.ts:197-213`）。
- 语义着色档：〔在场〕=绿、【已死亡】=红、【此刻·t=N】=中性灰；散文行用衬线字体（块正文是作者录入的中文叙述文，等宽是给代码与坐标的——09 期 §5.3 字体裁决，`ContextPreviewSection.vue:710-712`）。
- 节点类型设计贴合各块真实形态：档案体缩进行（左竖线衬线）、「【示范 N】」样本编号行、「注：」尾注、【此刻·切记】recency 钉（前缀并入 k 显示）。

## 7. 空块引导（「什么值得录」的回报可见）

空块不是空白，是单行虚线 +「还没录」+ 一句话补录指引（`EMPTY_HINTS`，`ContextPreviewSection.vue:60-68`），覆盖 7 个作者可补录的块：文风画像（文风页填画像）、笔迹示范（**「质量杠杆最大的注入」**）、实体称呼（世界页建角色或正文 @ 提及）、Canon（世界页真相账本）、私有设定（实体设私有）、前情回响（写过的章节自动进记忆）、空间常识（世界页设定比例尺）。设计意图：空块=「这次用不上」的诚实显示 + 告诉作者去哪补、补了有什么回报。

## 8. 健康横幅与世界模型卡

- **健康横幅**是「AI 视角」的责任面之一：辅助层 7 个后台组件（意图反推/未来推测/挂件生发/Canon 感知/沉淀/后处理/世界发现）的最近失败，从心跳响应持续回填到模块级单例（`useAdaptiveAssist.ts:39-52`），有错才渲染、恢复自动消失、只记最近一次。
- **世界模型卡**（「AI 眼中的世界」）与「AI 此刻读到的」是两个互补视角：后者是**本次注入的静态切片**（system prompt 镜像），前者是**世界模型运行态**（层 2 意图从哪来/活事实几条/走向推测）——意图来源标签直译「AI 猜的 / 你写的 / 大纲 / 上一章接力」，与意图三级源链（spine 打算 > 大纲转化 > LLM 反推）的人话化一一对应。

## 9. 预览与真实注入的已知差异（设计内近似，非 bug，但要心里有数）

预览路由是「无编辑器态」的特殊调用（`preview.py:50-53`）：

| 输入 | 真实 stitch | 预览 | 后果 |
|---|---|---|---|
| rolling_prefix | 前端从**编辑器光标位置**取窗（paraStart-200/500；桥接态取光标前 500 字 `_anchorRecentText`，`useAdaptiveAssist.ts:732/817/868`） | **落库正文尾**（剥 HTML 句界净截） | ① 光标在中插位（FIM 桥接）时，预览的滚动窗/场景判定/称呼表可见集 ≠ 真实注入；② **第三弹后**：`active_scene` 由 rolling+fragment 派生，预览恒按「章节尾」取景——作者光标停在中段已转场的场景时，预览的场景身份块与真实注入可能不同 |
| fragment | 作者原句碎片 / 胶囊速记 | 空串 | 拼画面档预览的召回 query 少碎片项 |
| chapter_intent | 请求可携带 | 不携带 | 预览的意图走大纲就近/层 2 兜底链——若作者刚在别处传了意图，预览意图块可能不同 |
| after_text | outline 模式透传胶囊后文 | 空串 | 仅影响称呼表泄漏手术路径，预览不受染 |
| drift_anchor | 心跳漂移提醒在态时 True | False | 漂移时真实注入的样本检索有收藏加成，预览无 |

这些差异的共同点：**装配函数同源，输入快照不同**。预览的语义是「按当前落库正文的章节尾视角装配一次」，不是「复现你下一次 Space 的确切注入」。

## 10. 发现的问题与观察

**F1（契约漂移，低危）**：前端 `ContextPreviewBlock.key` 类型联合仅 7 键（style_positive|author_samples|proper_nouns|canon|secrets|echoes|spatial），注释还写着「注入序」——这是 P5 时代的七块口径；实际后端返回 14 键（`adaptive.api.ts:231-244` vs `stitch_context.py:369-386`）。无运行时影响（响应是 JSON，接口只做标注；消费点 `segmentOfKey(key: string)` 收 string），但会误导后来者以为块集合只有 7 个。建议顺手把联合类型补齐并删掉过时注释。

**F2（半建成的审计面，中低危）**：知识平面为预览准备了「已选/未选（原因）」两栏审计数据——`build_context_preview` 返回 `unselected[:60]` 与 `selected_keys[:60]`（`stitch_context.py:463-466`），但：
- `selected_keys` 未在 `ContextPreviewResponse` schema 声明（`schemas.py:116-124` 只有 `unselected`）→ **FastAPI response_model 过滤，该字段永远到不了前端**（死产出）；
- `unselected` 到了前端但 `ContextPreview` 接口未声明、UI 未消费（后端注释自称「前端未消费前为向后兼容增量字段」）。
- 后果：`KG_BUDGET_CHARS=16000` 逃逸阀**丢整条**时（厚书安全网），丢弃事件只进 trace，作者在预览里看不到——「完备性从暗箱变成可审计」的设计承诺（v3.1 §5 纠正回路②）目前只兑现了一半。接线成本不高：unselected 结构已含 key/title/reason，可挂在块卡下方或面板底部。

**F3（观察项）**：模式五档中「写开头（open）」预览的 rolling_prefix 恒为空串 → `active_scene` 恒 None → 场景身份块恒按本章钉/无场景。这是 open 模式「无正文」语义的正确行为，但作者切到 open 档会看到场景身份块与顺写档不同，无任何解释——可在档位 title 或空场景块上补一句（现状可接受）。

**观察**：`EMPTY_HINTS` 里 `proper_nouns` 的引导（「世界页建好角色…」）在 world_sourced 书里几乎永不出现（实体块存在时称呼块被去重缺席）——文案无害，仅指出其可达面窄。

## 11. 测试底座（调研日实测全绿）

- 后端：`test_stitch_context.py` + `test_c3_mode_differential.py` 共 **55 passed**（装配/预览载荷/模式差异对拍）；另有 `test_budget_allocate.py`（预算恒等零变化锁）、`test_knowledge_plane.py`、`test_private_channel.py` 守各段。
- 前端：`contextBlockFormat.test.ts` + `contextBudget.test.ts` 共 **19 passed**（保字不变式 + 占用条换算）。

## 12. 文件地图

| 层 | 文件 | 角色 |
|---|---|---|
| 栏 | `frontend/src/features/workspace/presentation/AssistRail.vue` | 44px 图标栏（AI 视角=🔍 第 5 档，Ctrl+5） |
| 面板壳 | `frontend/src/features/workspace/containers/InspectorPanel.vue` | 单分区壳 + debug 分区编排（数据获取/切章复位/健康横幅/世界模型卡） |
| 主件 | `frontend/src/features/workspace/presentation/ContextPreviewSection.vue` | 「AI 此刻读到的」纯展示（汇总/模式/三段/块卡/预算条/空块） |
| 解析器 | `frontend/src/features/workspace/presentation/contextBlockFormat.ts` | 保字排版 + 段分组 + 来源人话化 |
| 预算条 | `frontend/src/features/workspace/presentation/contextBudget.ts` | 占用比/吃紧纯函数 |
| API | `frontend/src/services/api/domain/adaptive.api.ts:229-255, 330-339` | 类型契约 + contextPreview |
| 路由 | `backend/routes/chapter_generation/adaptive/preview.py` | mode 校验 + rolling 构造 + 响应模型 |
| 装配 | `backend/services/context/stitch_context.py` | 共享装配器 + 预览载荷（`build_context_preview`） |
| 注入序 | `backend/services/prompts/adaptive_prompts.py:292-369` | `render_system_blocks(_with_usage)` 唯一权威 |
| 知识平面 | `backend/services/context/knowledge_plane.py` | 五块预渲染 + 前缀冻结 + 审计面 |
| 预算器 | `backend/services/context/budget.py` | 块配额/模式总预算/裁剪序/allocate |
| 健康源 | `frontend/src/features/generation/composables/useAdaptiveAssist.ts:39-52` | componentErrors 模块单例 |
| 模型端点 | `backend/routes/chapter_generation/adaptive/settle_finish.py:263-275` | GET /adaptive/model + last_component_errors |

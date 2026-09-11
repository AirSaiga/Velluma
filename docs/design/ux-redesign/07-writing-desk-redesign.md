# 第 7 期：写作台重设计 —— 纸面常裸，三器随召（UX 重构 · 设计规格 · 唯一施工权威）

> 前置：第 0 期 `00-foundation.md`（token / z 层表 / 浮层规范继续消费，不另立）。
> 基线：**HEAD（2026-08-22 定稿版写作台）**。第 4/5/6 期的施工已整体回退，本文从 HEAD 出发重新设计；04/05/06 三稿的条款处置见 §10（逐条裁定：继承 / 废弃 / 已烧禁做）。
> 用户原话（本期边界的唯一来源）：「被改得乱七八糟的，太怪了，各种组件的布局位置很不自然，交互也是乱糟糟的，作者点进去都不知道应该看哪，还有这些乱七八糟的文字都是什么，完全不知道怎么使用。」
> 范围：`features/workspace/containers/WorkspaceView.vue`、`features/workspace/containers/InspectorPanel.vue`、`features/workspace/presentation/PerceptionBand.vue`、`features/workspace/presentation/ChapterBadges.vue`、`features/workspace/presentation/WorldSceneSlice.vue`、`features/workspace/presentation/QuickEventNote.vue`、`features/workspace/presentation/WorldContextCard.vue`、`features/workspace/presentation/ContextPreviewSection.vue`、`features/generation/presentation/`（SparkDock / BeatCardDock / IgnitionCard / GhostWarningsBar / GhostWashChip / GhostRepairedChip / ShortcutsCheatsheet + 新增 CursorLayer）、`features/generation/composables/useAdaptiveAssist.ts` 与 `useGhostDraft.ts`（仅上屏字符串）、`features/chapter-editor/`（presentation/ChapterEditorView.vue / PublishModal.vue / CritiqueModal.vue、containers/ChapterEditorContainer.vue / useChapterEditorContainer.ts / useChapterPublisher.ts）、`components/ChapterEditor.vue`、`components/RichTextEditor.vue`、`components/InspirationModal.vue`、`style.css`（恢复段局部修订）。
>
> **冻结红线（本文任何条款不得触碰）**：四槽位语义与排序；Space/Ctrl+Space/Tab/Esc/Alt+N/Alt+O/Ctrl+Enter 七键契约；心跳三计时器 / 感知常驻 detach 语义 / 章节纪元守卫；幽灵草稿机制（含 reapGhostIfDead、蒸发理由 toast）；细纲胶囊机制；dock 零件缓存签名输入；TipTap mark 类名（canon-mark/ghost-draft/outline-note 家族）；SSE 帧与 GHOST_* 字段；`computeCursorDockPos()` 公式本体（消费侧叠加钳位，函数一字不动）；感知锚定算法本体（`.canon-mark` 视口 Y 查询 / `stackAnchoredTops` / RESERVED_FLOOR / rAF 节流）；静音学习链（dismiss-hint 载荷不变）；`--editor-max-width: 880px`；placeFloating / useFloatingLayer / useEscStack / ModalShell 接口签名；后端零改动。

---

## 0. 翻车诊断：04/05/06 各自成立，叠加为什么变成信息墙

三期施工回退前的翻车现场（用户截图）与 HEAD 基线对照后，根因是四个机制性错误，**本期每条设计都必须能回答「不犯哪一条」**：

### 0.1 常驻面膨胀：每期为「发现性」各加一条 chrome，第一眼落点被稀释

- HEAD 首屏常驻面：binder / 顶栏 / 纸列 / 底栏 /（写中才出现的）感知带 = 4~5 处。
- 04 加状态丸+把手，05 加书脊+图标栏+批注轨，06 加工作条+章首时空戳行+章首打算行。三期叠加后首屏 **11 处** 同时说话的界面元素。每一处在当期稿里都「有理」，但发现性是有总量的——样样都想被看见 = 什么都看不见。「作者点进去都不知道应该看哪」的直接物证。

### 0.2 用文字解释代替形态自解释

每个新容器配一句副标题（「写之前想一想：…」「这些都按世界页的事件推算。想改？…」），06 期甚至为「消灭重复副标题」又做了一轮结构重构。三期合计净增 20+ 句解释性文案。「这些乱七八糟的文字都是什么」——解释对象是「为什么有这个面板」，而这句话需要存在本身，就是形态失败的证据。**本期纪律反转：宁可功能晚一点被发现，也不在第一屏写说明书。**

### 0.3 新手势取代旧手势，而不是减少手势

hover 300ms peek、章首折叠行展开、批注轨圆点点击弹卡、铃铛徽章、召唤带段落落点——每个单看都成立，叠加后作者要学的交互模型数量翻倍。「交互也是乱糟糟的」的物证。**本期只使用 HEAD 已有的手势族（hover 瞥看 / 点击 / Esc / 既有快捷键），零新手势。**

### 0.4 默认态错误：该藏的先亮了

面板在报告到达时 peek、章首两行常驻、空章同时存在「打算行」与「点火卡」两个意图输入——作者打开第一章，先看到的是 UI 不是纸。**本期默认态收敛：除纸面与 binder 外，一切默认关闭；唯一的主动推送保持 HEAD 现状（完稿报告滑出一次、沉淀 toast），一个不多。**

### 0.5 结论：本期方法论

在 HEAD 上只做 **减法与归位**，不发明新形态。凡与 HEAD 不同之处，§8 逐条给出理由；凡 04/05/06 引入的形态，除 §10 列为「继承」的少数几件外，全部不回搬。

---

## 1. 设计总则（验收时逐条对照）

1. **第一眼落点唯一**：任何视口、任何章节状态下，首屏视觉重心 = 纸列。其余元素满足其一才可存在：① 是纸面的一部分；② 静默到近乎隐形（edge/角落/图标级）；③ 作者召唤才来。
2. **AI 三件套各有唯一的家，家的位置 = 使用时机**：
   - **写的帮手在光标旁**——卡舱（SparkDock）、走向卡舱（BeatCardDock）、幽灵三条。写中才出现，出现在眼睛已经在的地方。
   - **看的提醒在纸左缘**——感知提醒。平时是守着行高的圆点，看一眼才是卡。
   - **干的活在右抽屉**——打算/此刻/本章/检查 + AI 视角。默认关，一招唤出（把手/Ctrl+\/顶栏钮），用完即走。
3. **文字纪律**：本期施工后界面文字总量 **< HEAD**（净删除，见 §7 预算表）。解释性长句零新增；hint 一句话、title 说后果；品牌词按 AGENTS.md 口径保留（幽灵草稿/蒸发/走向卡/卡舱/挂件/细纲胶囊/沉淀/此刻此地/黄金片段/这不像我/清脂），黑话清零（副驾/Canon/锚定/钉住/入账/快检/在屏/上屏/规避/逆向提取/动态状态/章级特例/继承/叙事时刻/引擎观测/为您/相似度数字/地点穿越，逐一见 §6 表）。
4. **安静知情**：不新增任何自动弹出/自动展开/peek。HEAD 已有的两个主动推送（完稿报告抽屉滑出一次、沉淀 toast「去确认」）原样保留，除此之外零主动。
5. **纸面几何恒定**：纸列宽度与位置在写作全程（含辅助激活、提醒到达、卡舱弹出）**不发生任何位移**——这是「坐下就写」的物理保证，也是感知带改覆态的核心收益（§2.4）。

---

## 2. 逐区域设计（现状 → 目标）

### 2.0 总览图

```
HEAD（现状）：
[AppRail 56] [binder ~229] [感知带 260（打字后出现，纸列被挤跳）] [880 纸列] [8px 隐形条 → 380 抽屉]
             顶栏（断片词+3 个无字图标） / 底栏（字数+保存，与页头保存态重复）

本期（目标）：
[AppRail 56] [binder ~229 不变] [880 纸列（恒定居中）] [右缘把手 → 380 抽屉 不变]
纸左缘：28px 提醒轨（覆于页边，不占宽；圆点守行高；hover/点击/键盘 → 232px 覆态读卡）
光标旁：卡舱 / 走向卡舱 / 幽灵三条（写中才出现的唯一浮动层）
顶栏：状态短句丸 + [✨ AI 辅助●] + [?] + [助手] —— 全部有名字或悬停即有名
底栏：删除（字数/保存并入页头 meta 行）
```

### 2.1 binder 章节导航（左栏）——结构不动，两处降噪

| | 现状（HEAD） | 目标 | 理由 |
|---|---|---|---|
| 形态 | splitpanes 常驻栏，min 14%/max 32% | **不变** | 章节列表是常规形态（Word 导航窗格同构），不是翻车成分；05/06 的拆除已被用户否决 |
| 徽标 | tier / 生成中 / 已生成 / 已发布 / 草稿 + 死 props | **退役「生成中」「已生成」**（`ChapterBadges.vue:50-52,59-61`）；保留 tier（存量老书数据）/已发布/草稿；删死 props `climaxScore`/`auditIssueCount`（:20-23）连模板段（:83-95）与样式（:154-166） | 「已生成」= content_text 存在即亮，写过的章全顶着它，零信息量；「生成中」是旧引擎字段，adaptive 时代不产生 |
| 底三钮 | 新建章节 / 导入 .md / 分析 | 「分析」→「**提取设定**」；title「从当前章正文里认出角色/地点/伏笔等」→「从这一章的正文里认出角色、地点、伏笔，收进世界页」 | 「分析」二字无自解释，title 是黑话（逆向提取） |

### 2.2 顶栏（nle-topbar）——断片词变短句，无字图标变带字开关

位置/高度/打字淡出语义（`--dim` + hover/focus-within 召回）**不变**。样式类 `state-pill` / `assist-toggle` 已在 style.css:477-537（04 期遗留段，双主题正确），**直接消费，零新 CSS**。

| 位 | 现状（HEAD） | 目标 |
|---|---|---|
| 左 | `nleStateLabel` 断片词 12px 灰字（感知中/续写中/沉淀中…，WorkspaceView.vue:486-503） | **状态丸**：6px 呼吸点 + 一句完整短句（文案见 §6 表 A1/A2）；无状态整丸缺席；error 态朱色（`state-pill--error`）。Space 按下瞬间 `aiLane='assisting'` 即亮「正在往下写…」——补上 2-7s LLM 等待期的「我听见了」反馈 |
| 右 1 | AI 辅助：13px 纯图标（:892-899） | **带字 pill**：`[✨] AI 辅助 [●]`——开=薄荷点 `#34d399`、关=`--text-faint` 点；active 字色 `--accent-500`；title 见 §6 表 A3/A4。「Space 为什么不是空格」从此有可见归属 |
| 右 2 | 快捷键 ? 纯图标 | 不变（title「快捷键一览」自解释足够） |
| 右 3 | 抽屉 panel-right 纯图标，title「副驾面板（Ctrl+\ 固定）」 | 图标不变；title→「**写作助手（Ctrl+\ 固定）**」 |

### 2.3 页头与底栏合并——消灭「上下两条横栏夹纸」

- **删除** `.status-bar` 整块（WorkspaceView.vue:984-990）与其样式（WorkspaceView scoped :1466-1489 + style.css 恢复段 :763-769）。
- **页头 meta 行**（ChapterEditorView.vue:122-125）新构：
  `[第N章] [已发布] · [N 字] · [保存态] ……… [⋯]`
  - 字数：`{{ wordCount }} 字`，`--text-xs` + `--text-muted` + tabular-nums。数据链：WorkspaceView 既有 `wordCount` computed（:761）→ `components/ChapterEditor.vue` 加 `wordCount?: number` prop → `ChapterEditorContainer.vue` 透传 → ChapterEditorView 渲染。**不新建数据源。**
  - 保存态沿用 `page-head__save`（「保存中…/已保存 HH:MM」），**error 态文案升级为底栏原句「保存失败（已存本地草稿）」且加 `color: var(--danger)`**——底栏删除后红字语义与「已存本地草稿」信息必须有人继承；且页头不打字淡出，顺带修复「底栏淡出把保存失败藏起来」事故。
- 打字淡出范围：底栏删后只剩顶栏淡出；页头 meta 行常显（现状语义，此处为声明）。
- 页头 ⋯ 菜单四项文案见 §6 表 B（获取灵感→找找灵感；编辑审阅→AI 编辑审阅；智能格式整理→整理全文格式）。
- 发布中浮层文案见 §6 表 B8（「动态状态」黑话清零）。

### 2.4 感知带 → 纸左缘提醒轨（本期最大结构变化，取代 260px 常驻列）

**现状问题（实锤）**：`.perception-band` 260px in-flow（PerceptionBand.vue:217-226），且只在 `adaptiveActive`（打字 ≥4 字）后挂载——**作者开始写字的瞬间，纸列被挤跳 260px**，恰是最不该动纸面的时刻；260px 常驻面承载的通常是 0-3 张小卡，面积严重超配；带内硬编码浅粉彩在深色下瞎眼（:429-476）。

**目标形态：提醒轨 + 覆态读卡**（PerceptionBand.vue 内部重写，**props/emits 零变化**：`suggestions` / `spineProgress` / `dismiss-hint`；锚定管线复用 §2.4.4）：

#### 2.4.1 提醒轨（默认态，28px）

- absolute 覆于 `.editor-host` 左缘（left:0 / top:0 / bottom:0 / width:28px），`z-index: var(--z-page-chrome)`（40），**不占布局宽**——纸列从此零位移。无底色、无边框（轨道本体透明，圆点自带可读性）。
- **圆点守行高**：每条 `suggestions` 一枚 8px 圆点，纵向位置 = 该条锚定 Y（`stackAnchoredTops` 输出按点半径 clamp 进 `[8, 轨高-8]`，且只渲染锚点在当前视口内的条）；kind 五色（§2.4.5 token 化色族）；**安全类（leak/contradiction）10px 朱点 `--danger`**——安全提权语义从折叠徽章继承到轨。
- 锚点滚出视口的条与找不到锚的条（orphan/leak 兜底区内容）→ 轨底「+N」小计数（`--text-xs` muted，N=未上轨条数）。
- **打算小旗**：`spineProgress` 存在时轨顶一枚 ⚑（`--accent-500`），仅此而已——进度详情在覆态读。
- 空态（无 suggestions 无 spineProgress）：轨渲染但零内容零交互（`aria-hidden`），视觉隐形。**删「写到相关角色/伏笔时，这里会浮现提醒」引导句的常驻位**——它只在覆态空态里出现（见下）。
- 圆点是 button（tab 序可达，Enter/空格同点击）。

#### 2.4.2 覆态（读卡态，232px）

- 打开（任一）：① hover 轨 120ms 驻留（pointerenter 起计时，移出取消——防划过误开）；② 轨 `:focus-within`（键盘 Tab 到圆点）；③ 点击轨体/圆点（点击=钉住，再点解除）。
- 形态：absolute left:0 全高 232px，纯色底 `var(--bg-secondary)` + 右缘投影（复用 `.inspector-drawer` 的 box-shadow 值，方向镜像），`translateX(-8px)+opacity 0 → 0/1` 过渡 0.18s（reduced-motion 毯式瞬切）。**覆于纸列之上不推挤**——与右抽屉 hover 瞥看同族语义（边缘 peek 临时遮纸，读完即走）。
- 内容 = HEAD 带内容全量平移：**打算进度行**（:134-155 原样，意图+旗标+可点折叠清单）→ 锚定卡（按 Y 对齐，避让顶部进度行实高）→ 底部兜底区「其他提醒 +N 更多」（:188-212 原样逻辑）。卡结构逐行保留（图标+label+kind tag+×+detail）。
- **header「Canon 感知」删除**（英文+机制词+等宽大写，调试腔；卡自有 kind tag，头是冗余）。空态时覆态顶部显示一行「写到相关角色 / 伏笔时，这里会浮现提醒」（`--text-sm` muted）。
- 关闭：mouseleave（且内无焦点、未钉住）/ Esc（**入 Esc 栈**，关闭后焦点回编辑器）/ 钉住态外点（pointerdown 在轨与覆态之外即收）。三态管理收进 PerceptionBand 内部一个 `bandOpen` ref + `pinnedByClick` 标志，**不向 WorkspaceView 新增 prop**。
- 覆态根 `wheel` 事件转发编辑器滚动容器（一行监听）——悬停读卡时滚轮不被截获。
- dismiss ×：24px 命中（`padding: 4px 6px`），卡 `:hover`/`:focus-within` 双触发显形（03 期 §4.1 规则的落地处）；安全类不出 ×（白名单 `MUTEABLE_KINDS` 不变）。

#### 2.4.3 不再保留的形态

- hover 整条展开成常驻宽带的旧模型（带本即栏）随栏体删除；**band-force 不存在**（卡舱已迁光标层，「有零件时带自己回来」的对象不存在）。
- SparkDock 的带内 #dock 槽删除（§2.5）；`topReservePx` 测量对象改挂**打算进度行** wrapper（同一 RO 公式 `el.offsetTop + el.offsetHeight + 6`；无 spine 时 reserve=0）——锚定卡顶部避让从「舱体实高 0~230px 浮动」变为「进度行实高 0 或 ~40-120px」。

#### 2.4.4 锚定机制适配（红线专项）

- 算法本体零改动（`.canon-mark` 视口 Y 查询 / `stackAnchoredTops` / RESERVED_FLOOR / rAF 节流 / 滚动与文档变化监听，函数级 diff 为零）。
- `bandEl` ref 改指覆态根元素：覆态与旧带体同为 editor-host 顶缘全高，`viewportY - bandRect.top` 相对 Y 语义逐像素不变。
- 轨档圆点消费同一 `anchors` 输出（clamp 进轨），覆态卡消费同一 `anchors` 输出（原样）——一份锚定，两种渲染。

#### 2.4.5 深色修复（token 化，零新增 token）

03 期 §4.2 的派生方案落地（该期未施工的项）：带/卡全部硬编码色 → token 或 color-mix 派生。卡五族：`border: color-mix(in srgb, KIND 35%, transparent)`、`background: color-mix(in srgb, KIND 8%, var(--bg-canvas))`、文字/tag = KIND 本体。映射：character→`--info` 族；hook→`--warn` 族；leak/contradiction→`--danger` 族；style→`--accent-500` 族；inbox→`--ok` 族。轨圆点同色族。其余散件：带体边 `var(--border-color)`、空态字 `var(--text-muted)`、卡底 `var(--bg-canvas)`、兜底区渐变由 `var(--bg-secondary)` color-mix 同构。薄荷品牌色字面值按 00 期 §2.5 先例保留。

### 2.5 卡舱与幽灵三条 → 光标层（归位，非发明）

**现状问题**：SparkDock 在感知带顶部流式区块——写中作者眼睛在光标，卡在 260px 外的栏顶；幽灵三条（疑点/返修/洗层）同病（提示与幽灵正文隔一个栏宽）。SparkDock.vue 文件头自述原始设计即「光标停顿 4s → 在光标下方 8px 淡入」；`useSparkDock.ts` 至今仍在算 `sparkDockPos` 并挂 `followEditorLayout`（:157-183 活着的冗余）。**本期是启用既有齿轮的归位，不是新形态。**

#### 2.5.1 新组件 `features/generation/presentation/CursorLayer.vue`

WorkspaceView 模板中 `#dock` slot 块（:939-952）整体移入本组件；挂载条件沿用 `adaptiveActive`（WorkspaceView 层 `v-if` 不变）。Teleport body / fixed / `z-index: var(--z-dock)`（50）。两个槽位：

**槽位 A · SparkDock**（可见性状态机零改动：sticky/stash/restore/打字隐藏/自动弹舱守卫/`v-if="visible && !ghostActive"` 全继承）：
- 锚 = `computeCursorDockPos()` 输出换算 `{ x: p.left, y: p.top - 8 }`（契约 +8 还给 gap，与 BeatCardDock 消费模式同款）→ `useFloatingLayer({ gap:8, margin:8, prefer:'below', flip:true, align:'start' })`；宽 `min(360px, 80vw)`（碎片卡紧凑，比 BeatCardDock 420 窄一档）；底缘不足上翻、右缘夹紧、maxHeight 内滚；翻转时加 `--flipped` 类，入场 translateY 方向取反。
- 滚动/resize 跟随 = `followEditorLayout` 既有，零新增。
- 尺寸：开后实测根元素；首帧兜底 `{ width: 360, height: 300 }`。

**槽位 B · 幽灵三条**（疑点条 → 返修条 → 洗层条，纵叠 gap 4px）：
- 三条数据全部在 GHOST_DONE 帧到达（流式毕、光标静于幽灵尾）——**挂载即一次性取 `computeCursorDockPos()` 作锚**，同款 placeFloating 参数；挂 `followEditorLayout` 防滚动漂移。流式进行中三条不存在，天然无抖动面。
- 互斥天然成立：`ghostActive` 时 SparkDock 自隐（既有），幽灵蒸发/采纳 → 三条随 `ghostActive=false` 卸载。
- Esc 语义不变（幽灵蒸发在编辑器 keymap；三条无独立 Esc）。

#### 2.5.2 SparkDock 组件内微调（自解释一行，净文案不增）

- **舱顶加标题行**：仅 `sparkDockVisible && !attachedParts.length` 时显示一行 `--text-xs` muted「卡住了？点一个画面接着写」——作者必须知道这盒子弹出来是干嘛的。
- **删底部 tips 行**（:111-113「选中后 Space：以这枚画面为引接着写约百字 · Esc 收起」）——信息并入标题行，底部不再占高。
- 吸附态 hint（:126）→「Space 照着选中的画面写 · Esc 清空选择」。
- 两级层级 chip / 数字键 / 「多写几段 ▸」/ 槽位符号副行——**逐像素保留**。
- 根样式：由带内 `width:100%` 改 `width: min(360px, 80vw)`（宿主管 fixed 定位，卡片自身视觉不变）。

#### 2.5.3 BeatCardDock 不动

03 期设计的 placeFloating 消费若已在代码中则保持，若未施工也**不在本期补**——走向卡舱一切现状冻结（仅 §6 表 D 三处文案）。

### 2.6 右抽屉（写作助手）——结构不动，可发现性与文字密度双修

| | 现状（HEAD） | 目标 |
|---|---|---|
| 发现入口 | 8px 右缘渐变条，静息 opacity 0.4（style.css:772-788） | **12px 命中宽 + 常驻把手**：把手 24×48px pill 贴右缘垂直居中，左圆角，底 `var(--bg-secondary)` + 左边框 `var(--border-color)`，内含 chevron（关=‹ 开=›，随 `drawer-edge--active` 翻转）；静息 opacity 0.5，hover 升 1；title「写作助手（Ctrl+\ 固定）」。8→12 加宽纯命中面（渐变色标是绝对定位 4px 衰减，视觉零变化） |
| 抽屉本体 | 380px/44vw overlay（hover 瞥看）/ pin 推挤、Ctrl+\、报告到达滑出一次 | **全部不变** |
| 四 tab | 打算/此刻/本章/检查 + 副标题行（TAB_SUBTITLES 四句，InspectorPanel.vue:80-86,479） | **tab 架构不变；副标题行整行删除**——每个 tab 内容自带功能头（SpinePanel「打算 写之前记两句…」、WorldSceneSlice「此刻此地」、检查三区 label），副标题与内容第一屏同义重复（06 期「一头一句」诊断成立，此处保守落地：只删重复头，不动结构） |
| 底部 | 「AI 视角」降级入口（Ctrl+5） | 不变；title 去「引擎观测」→「AI 续写时实际读到的内容（Ctrl+5）」 |
| 内部文案 | 见 §6 表 G-M | 黑话清零（章级特例/继承/审计残留/相似度数字/缝合/点火模式名/锚定/钉住/入账等），**内容组件结构与流程零改动** |

### 2.7 空态与点火卡——第一印象的仅有两处文案手术

- **无选中章空态**（WorkspaceView.vue:974-982）：「选择一个章节开始写作」→ 衬线大标题「**选一章，开始写**」（`--text-2xl` + `--font-heading`）；副行→「左边选一章，或者新建一章」；新建钮不变。
- **点火卡**（IgnitionCard.vue）：形态/位置/显隐门控**全部不变**。文案两处（§6 表 E）：意图 placeholder→「这一章主要讲什么？一句话就行，空着也行」；无大纲 hint「先在副驾『打算』页写两句大纲…」→「先在右侧『打算』页写两句大纲，AI 就能帮你开个头」（副驾词退役）。
- ChapterEditorView :189 的「选择一个章节或新建章节开始编辑」是不可达分支（WorkspaceView 已用 v-if 把无章态拦在空态卡），**标死代码不动**。

### 2.8 其余各面（全部只动文案，结构零改动）

- 检查 tab 全流程（完稿体检/报告/残句修复/润色/读者反馈/手术历史/检查结论）：表 J/K。
- AI 视角 tab（AI 此刻所见/世界模型快照/组件健康）：表 L。
- 此刻 tab（WorldSceneSlice）：表 M（muted 说明尾巴缩短 + 钉住/入账词替换，结构零改动）。
- 选区浮窗与选区改写：表 O（placeholder 问句式 + 两条 toast）。
- 发布/审阅/灵感/格式整理：表 P。
- Alt+N 速记与情境浮卡：表 Q。
- 幽灵三条与拒稿逃生舱 toast：表 F。
- 快捷键速查弹层：表 R。
- 其余 toast：表 S。

---

## 3. 组件级施工落点（文件清单）

| # | 文件 | 动作 |
|---|---|---|
| 1 | `features/workspace/containers/WorkspaceView.vue` | 顶栏三件套改造（状态丸/带字开关/title）；删底栏 footer 与 scoped 样式；`wordCount` 下传；drawer-edge 把手；`#dock` slot 块（:939-952）移除改挂 `<CursorLayer>`；PerceptionBand 挂载条件与 props 不变；空态文案；表 A/S 文案 |
| 2 | `features/workspace/presentation/PerceptionBand.vue` | 内部重写为提醒轨+覆态（§2.4）；props/emits/锚定算法消费零变化；卡色 token 化 |
| 3 | `features/generation/presentation/CursorLayer.vue` | **新增**（§2.5.1；约 120 行：两个 useFloatingLayer + followEditorLayout + 三条纵叠） |
| 4 | `features/generation/presentation/SparkDock.vue` | 标题行/删 tips/hint 文案/根宽 |
| 5 | `features/generation/presentation/GhostWarningsBar.vue`、`GhostWashChip.vue`、`GhostRepairedChip.vue` | 表 F 文案 |
| 6 | `features/generation/presentation/BeatCardDock.vue` | 表 D 三处文案 |
| 7 | `features/generation/presentation/IgnitionCard.vue` | 表 E 两处文案 |
| 8 | `features/generation/presentation/ShortcutsCheatsheet.vue` | 表 R（键位描述人话化，键位本身零变化） |
| 9 | `features/workspace/containers/InspectorPanel.vue` | 删 TAB_SUBTITLES 与 `.tab-subtitle` 模板/样式；表 G-M 文案；**tab 架构/内容/默认切换逻辑零改动** |
| 10 | `features/workspace/presentation/ChapterBadges.vue` | 退役两徽标+删死 props（§2.1） |
| 11 | `features/chapter-editor/presentation/ChapterEditorView.vue` | 页头 meta 行加字数+保存失败红；菜单文案；发布浮层文案；placeholder |
| 12 | `components/ChapterEditor.vue`、`features/chapter-editor/containers/ChapterEditorContainer.vue` | `wordCount?: number` prop 透传（各加 3 行） |
| 13 | `components/RichTextEditor.vue` | 表 O 文案 |
| 14 | `features/chapter-editor/containers/useChapterEditorContainer.ts`、`useChapterPublisher.ts` | 表 O/P toast 与弹窗文案 |
| 15 | `features/chapter-editor/presentation/PublishModal.vue`、`CritiqueModal.vue`、`components/InspirationModal.vue` | 表 P 文案 |
| 16 | `features/workspace/presentation/WorldSceneSlice.vue`、`QuickEventNote.vue`、`WorldContextCard.vue`、`ContextPreviewSection.vue` | 表 M/Q/L 文案 |
| 17 | `features/generation/composables/useAdaptiveAssist.ts`、`useGhostDraft.ts` | 表 F/S toast 与 kind 词表（**仅字符串字面量**） |
| 18 | `style.css` | 删恢复段 `.status-bar`/`.status-bar--dim`（:763-769）；`.drawer-edge` 加宽 8→12 + 新增 `.drawer-edge__handle` 段；`.nle-topbar__state`（:759-761）随状态丸退役删除；`.inspector-drawer` 与过渡段保留 |

**零新增 token、零新 z 值、零新依赖。** 新增表面全部消费既有 token（§5）。

---

## 4. 交互细则（每个新/改件的触发 · 消失 · 键盘）

| 对象 | 出现 | 消失 | 键盘 |
|---|---|---|---|
| 状态丸 | aiLane/stage 有态即现（Space 按下即亮「正在往下写…」） | 态空即隐 | 纯态标，无交互 |
| AI 辅助带字开关 | 常驻顶栏 | — | Tab 可达，Enter/空格切换；toast 文案不变 |
| 提醒轨圆点 | 心跳 `suggestions` 到达即现（淡入 0.15s）；守锚定行高 | 该条 hint 消失即隐 | button，Tab 可达 |
| 提醒覆态 | hover 轨 120ms / focus-within / 点击轨体（钉住） | mouseleave 且无焦点未钉住 / Esc（入栈）/ 钉住态外点 | Esc 关且焦点回编辑器；卡内 × Tab 可达 |
| SparkDock（光标层） | 停顿 4s 段尾 / Tab（现状触发链零改动） | 打字即隐（非 sticky）/ Esc / 幽灵在屏互斥（现状零改动） | ↑↓ 浏览、1~4 吸附、Esc（现状零改动） |
| 幽灵三条（光标层） | GHOST_DONE 有命中即现于幽灵尾下 | 幽灵采纳/蒸发即隐 | 无独立键位（随幽灵） |
| 抽屉把手 | 常驻右缘 | — | 抽屉本体 Ctrl+\ 不变；把手 button Tab 可达（Enter=pin 切换，同点击） |
| 页头 ⋯ 菜单 | 纸面 hover/focus-within 浮现（现状） | 外点/ Esc 现状 | 现状不变 |
| 快捷键速查 | 顶栏 ? | Esc/外点（现状） | 现状不变 |

**零新增手势族**：全部交互都能映射到 HEAD 已有族（hover 瞥看 / 点击 / Esc / 既有键位）。

---

## 5. 几何、自适应与双主题

### 5.1 几何锚（验收 I-06 引用；纸列恒定 = 本条核心）

| 视口 | 编辑器窗格 | 纸列 | 文字量度 | 备注 |
|---|---|---|---|---|
| 1200px（Electron 最小窗宽） | 1200−56−229(binder 20%) ≈ 915 | ~875（px-5 内） | ~779px ≈ 48 字/行 | 感知轨覆态不占宽，**开写零跳动** |
| 1093px（1366@125% DPI） | ≈ 808 | ~768 | ~672px ≈ 42 字/行 | 对比 HEAD 同视口（带开时 ~519 ≈ 32 字）**+29%** |
| 1280px | ≈ 995 | 880 触顶 | 768px 满额 | — |
| 1200px + 抽屉 pin | ≈ 535 | ~495 | ~400px ≈ 25 字/行 | 作者自选 pin，允许变窄不错乱（同 HEAD 语义） |

- 提醒轨 28px 覆于页边：1093 视口下纸面文字起始于 x≈68（px-5 20 + px-12 48），轨宽 28 < 68——**常态零遮字**。覆态 232px 读卡时临时遮纸（与右抽屉 hover 瞥看同族，peek 语义）。
- `--editor-max-width: 880px` 冻结；editor-type-large 实验开关零交集。
- 覆态卡 Y 锚定在任意档位语义不变（算法不感知形态）。

### 5.2 双主题

- 零新增 token；卡五族 color-mix 派生自动双主题正确（§2.4.5）；状态丸/带字开关复用 style.css 既有双主题段；把手/覆态投影复用 `.inspector-drawer` 既有值（深色下该值已成立）。
- 深色专项巡查点：提醒轨圆点五色可辨、覆态卡无瞎眼粉彩、把手在 `--bg-primary` 深底上可见（边框 `--border-color` 深色侧 `#3a3530` 达标）。

### 5.3 z-index 消费表（不立新值）

| 表面 | 层 | 论证 |
|---|---|---|
| 提醒轨 / 覆态 | `--z-page-chrome`（40） | 页内浮动工具带；低于卡舱/浮层，遮内容让弹层 |
| CursorLayer（SparkDock + 幽灵三条） | `--z-dock`（50） | 卡舱带内值，与 BeatCardDock 同层兄弟 |
| 抽屉把手（随 .drawer-edge） | 80（恢复段既有字面值） | 不动 |
| 抽屉 | 85（恢复段既有字面值） | 不动 |

---

## 6. 文案逐条定稿（每条上屏文字的唯一权威）

> 纪律：品牌词保留（AGENTS.md 口径）；黑话清零只替换不加长；标「保留」的行施工时 grep 零 diff。file:line 以 HEAD 为准。

### 表 A · 顶栏与状态（WorkspaceView.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| A1 | :489-494 | 感知中 / 走向已备好 / 续写中 / 沉淀中 / 通读中 | **AI 正在看你写的 / 走向卡备好了 · Ctrl+Space / 正在往下写… / 正在整理新设定… / 正在通读全章…** |
| A2 | :498-500 | 精修中 / 审校中 / 生成失败 | **润色中… / 正在检查全文… / 生成失败**（保留） |
| A3 | :895 | AI 辅助已开启（点击关闭：Space 恢复普通空格，停顿感知/卡片舱停用） | **AI 辅助开着——Space 会叫 AI 接着写，停顿会浮出卡舱；点击关闭** |
| A4 | :895（关态分支） | AI 辅助已关闭（纯手写模式，点击开启） | **AI 辅助已关——Space 是普通空格；点击开启** |
| A5 | :901 | 快捷键一览 | 保留 |
| A6 | :910 | 副驾面板（Ctrl+\ 固定） | **写作助手（Ctrl+\ 固定）** |
| A7 | :1021 | 副驾抽屉（Ctrl+\ 固定） | **写作助手（Ctrl+\ 固定）** |
| A8 | :984-990 | 底栏「N 字 / 保存中… / 已保存 / 保存失败（已存本地草稿）」 | DOM 删除，文案迁页头（§2.3；失败句原文继承） |
| A9 | :273-276 | AI 辅助已开启 / 已关闭：可安静手写，Space 恢复普通空格（toast） | 保留 |

### 表 B · 页头与章节菜单（ChapterEditorView.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| B1 | :123 | 第N章 label | 保留（旁加 `N 字` · 保存态，§2.3） |
| B2 | :130 | 章节动作 | 保留 |
| B3 | :139,:143 | 发布本章/撤回发布 · 获取灵感 | 保留 · **找找灵感** |
| B4 | :147 | 编辑审阅 | **AI 编辑审阅** |
| B5 | :152 | 智能格式整理 / 格式整理中… | **整理全文格式 / 正在整理格式…** |
| B6 | :162 | 未命名章节 | 保留 |
| B7 | :177 | 从这里开始写——Space 续写 · Alt+O 细纲 · Alt+N 记世界 | **从这里开始写——Space 让 AI 接着写 · Alt+O 插细纲 · Alt+N 记一笔** |
| B8 | :111-116 | 发布中... / 正在更新章节状态及角色动态... | **正在发布… / 正在更新角色近况…** |

### 表 C · 提醒轨与覆态（PerceptionBand.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| C1 | :132 | Canon 感知 | **删除**（覆态无 header） |
| C2 | :57-76 | kind 标签：角色/伏笔/泄露/矛盾/文风/收件箱；fallback「Canon」 | 角色/伏笔/**泄密**/矛盾/文风/收件箱；fallback→**设定** |
| C3 | :179 | 收起此类提醒（同类多次收起后将少提，可在收件箱恢复） | **收起这类提醒（多收几次就不再提，可在写作助手里恢复）** |
| C4 | :159-161 | 写到相关角色 / 伏笔时，这里会浮现提醒 | 保留（改在覆态空态一处出现） |
| C5 | :189 | 其他提醒 | 保留 |

### 表 D · 卡舱（SparkDock.vue / BeatCardDock.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| D1 | SparkDock 新增舱顶 | — | **卡住了？点一个画面接着写**（仅无吸附时；同时删 :111-113 tips 行） |
| D2 | SparkDock :126 | Space 以画面为引接着写 · Esc 清空 | **Space 照着选中的画面写 · Esc 清空选择** |
| D3 | SparkDock :107 | 多写几段 ▸（title 选一个走向，AI 连写几段 Ctrl+Space） | 保留 |
| D4 | BeatCardDock :46,:58,:70,:84-85 | 接下来几段往哪写？/ 岔路 title / 这条建议帮你写到：X / 自由发挥 | 保留 |
| D5 | BeatCardDock :64 | 来自地图相遇机会——世界页同地角色的戏剧线索 | **来自世界页地图：同在一处的角色，可能撞出戏** |
| D6 | BeatCardDock :75 | 焦点：A、B | **涉及：A、B** |
| D7 | BeatCardDock :89 | N 以内数字键选择 · Esc 关闭 | **按数字键选 · Esc 关闭** |

### 表 E · 点火卡（IgnitionCard.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| E1 | :36 | 本章还是白纸 | 保留 |
| E2 | :42 | 一句话：这一章主要讲什么？（可空） | **这一章主要讲什么？一句话就行，空着也行** |
| E3 | :52-53,:59-65 | 收下建议/不用 · ⚡ 写个开头 / 我自己写 | 保留 |
| E4 | :69 | 生成的是幽灵草稿：Enter 采纳 · Esc 蒸发 · 采纳后随时可改 | 保留 |
| E5 | :70 | 先在副驾「打算」页写两句大纲，就能让 AI 帮你开个头 | **先在右侧「打算」页写两句大纲，AI 就能帮你开个头** |
| E6 | :77 | ✨ AI 帮我出出主意 / 建议生成中… | 保留 |

### 表 F · 幽灵三条与拒稿（GhostWarningsBar / GhostWashChip / GhostRepairedChip / useGhostDraft / useAdaptiveAssist）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| F1 | WarningsBar :50 | 快检疑点：…（只提示不拦截，Enter 照常采纳） | **自动检查发现的疑点（只提醒，Enter 照常采纳）** |
| F2 | WarningsBar :52 | N 处疑点 | 保留 |
| F3 | WarningsBar :67 | Enter 采纳 · Esc 蒸发——疑点仅供参照，不拦截任何操作 | **Enter 采纳 · Esc 蒸发——疑点只是提醒，不拦你** |
| F4 | useGhostDraft :53-62 | 死者开口/疑似泄底/私有设定外泄/禁忌词/人物不在场/地点穿越/自动修正暂停 | 死者开口/**秘密穿帮**/**秘密外泄**/禁忌词/人物不在场/**地点跳变**/自动修正暂停（一词表三处消费，自动联动。「穿越」是网文类型词，误读风险实测成立） |
| F5 | WashChip :34 | 生成后自动规避了你的禁忌词（只改 AI 的提案，Enter 采纳后才进正文） | **AI 写的时候避开了你的禁忌词（只改 AI 的稿子，Enter 采纳才进正文）** |
| F6 | WashChip :38 | 已规避 N 处禁忌词 | **已换掉 N 处禁忌词** |
| F7 | WashChip :49,:56 | （无替代词，仅提示）/ 只改 AI 的提案不碰你的正文 · Enter 采纳 / Esc 蒸发照常 | **（没有合适的替代词，只标出来）/ 只改 AI 的稿子，不碰你的正文 · Enter 采纳 / Esc 蒸发照常** |
| F8 | WashChip :52-54 | 用原稿（保留这些词）+ title | 钮保留；title→**恢复 AI 原来的稿子，这些词以后只提醒不替换** |
| F9 | RepairedChip :28 | title 检出的设定硬伤已自动修正（改写修复/删去违规句） | **AI 稿子里的设定错误已自动改掉（改写修复/删掉问题句）：…** |
| F10 | useGhostDraft :96 | 已采纳，含 N 处疑点：…（可忽略，仅供参照） | **已采纳，含 N 处疑点：…（只是提醒，可不管）** |
| F11 | useGhostDraft :410 | 幽灵已蒸发——点个原因，帮我学会少写这种 | 保留 |
| F12 | useAdaptiveAssist :111-124 | 这次没能写出合格的续写（检出设定硬伤，自动修正未通过）+ 钮「仍以疑点提示上屏」 | **这次没写出合格的续写——有设定错误，自动修正也没修好** + 钮「**还是贴出来（带疑点标记）**」 |
| F13 | useAdaptiveAssist :750 | 已有幽灵草稿在屏，先 Enter 定稿或 Esc 蒸发再扩写 | **已有一段 AI 草稿——先 Enter 采纳或 Esc 蒸发，再扩写** |

### 表 G · 写作助手框架（InspectorPanel.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| G1 | :69-75 | tab：打算/此刻/本章/检查 + AI 视角底钮 | 保留 |
| G2 | :80-86,:479 | 四行副标题 + debug 条「AI 续写时实际读到的内容（引擎观测）」 | **副标题四行整体删除**；底钮 title→**AI 续写时实际读到的内容（Ctrl+5）** |
| G3 | :471 | tab title 带 Ctrl+N | 保留 |

### 表 H · 打算 tab（InspectorPanel :513-549 + SpinePanel.vue）

**零改动**（2026-09-03 人话化成果区：打算/非写不可的情节/划掉/可以怎么发展/帮我想想这章怎么走/「AI 目前的猜测」「不对」纠正手势——全部保留）。唯一一处：InspectorPanel :518 title「…卡片舱与续写随即按你的方向来」→「**…卡舱和续写马上按你的方向来**」（口语化，品牌词保留）。

### 表 I · 本章 tab（InspectorPanel.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| I1 | :575 | 章级特例 | **本章专属** |
| I2 | :576 | 继承书级文风 | **跟随全书文风** |
| I3 | :582 | 恢复继承（title 删除本章特例，恢复继承书级文风） | **改回全书文风**（title 删掉本章专属，改回跟随全书文风） |
| I4 | :587 | 编辑本章文风特例 / 为本章设文风特例 | **编辑本章专属文风 / 给本章单独定个文风** |
| I5 | :589 | 回忆章换个腔调？章级特例只影响这一章的生成，其余章节仍用书级文风。 | **回忆章想换个腔调？本章专属只管这一章，其他章节不受影响。** |
| I6 | :596-598 | 在世界页查看真相 + 表/里 hint | 保留 |
| I7 | :148-155 | 需要精修/未审校/修改后通过/需要再修 | **需要润色/未检查/通过（修改后）/需要再修** |

### 表 J · 检查 tab：完稿体检与报告（InspectorPanel.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| J1 | :617 | title 触发全章检查 / 在章节内写满 4 字激活 AI 辅助后可用 | **让 AI 通读全章，出一份检查报告 / 在本章写满 4 个字后可用** |
| J2 | :621-623 | 通读中…/完稿体检 + hint | 保留 |
| J3 | :631-654 | 没写完的句子（N）/修复/采纳/放弃/未能修复 | 保留 |
| J4 | :659 | 疑似 AI 味变体（N） | **疑似 AI 味的句子（N）** |
| J5 | :667 | ≈「…」（相似度 0.83） · 可改为：… | **≈「…」 · 可改为：…**（删相似度数字） |
| J6 | :674-756 | 收入收件箱/关键情节/打算/⚠️ 秘密穿帮/编辑意见/前情记忆/收件箱区/新出现的角色·事物/⚠️ 设定冲突/已有：/正文： | 保留 |

### 表 K · 检查 tab：润色与反馈

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| K1 | :782 | 启动润色（检查 + 修改） | **开始润色：先检查，再修改** |
| K2 | 润色记录/再次润色/读者反馈区/RefineryProgress/RefineryIssuesPanel 全件 | — | 保留 |

### 表 L · AI 视角 tab（ContextPreviewSection.vue + InspectorPanel :220-308,:886-896）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| L1 | CtxPrev :80 | AI 此刻所见（预览） | **AI 此刻读到的（预览）** |
| L2 | CtxPrev :32-38 | 顺写/缝合/连写/细纲/点火 | 顺写/**拼画面**/连写/细纲/**写开头** |
| L3 | CtxPrev :40-45 | 本章锚定/前序章锚定/事件最大时刻/空世界 | **本章固定/上一章固定**/最新事件/空世界 |
| L4 | CtxPrev :51 | 世界页建实体（或在正文 @ 提及），防缝合时称呼漂移 | **世界页建好角色（或在正文 @ 提及），AI 写作时称呼不乱叫** |
| L5 | Inspector :220-228 | 方向猜测/走向推测/挂件生发/世界感知/沉淀整理/完稿体检/世界发现 | 方向猜测/走向推测/**卡舱供件**/世界感知/**设定整理**/完稿体检/世界发现 |
| L6 | Inspector :302-308 | 「方向：inferred · …」「字数（沉淀）」 | source 映射中文：**inferred→AI 猜的 / author→你写的 / outline→大纲 / baton→上一章接力 / none→无**；「字数（沉淀）」→**已整理字数** |
| L7 | Inspector :886,:893 | 健康 hint / AI 眼中的世界 | 保留 |

### 表 M · 此刻 tab（WorldSceneSlice.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| M1 | :386 | title 本章就固定在此刻——以后录新事件不会再拉动它（与世界页时间轴右键同一功能） | **本章就固定在这个时间——以后记新事件不会再拉动它** |
| M2 | :445 | 📌 已定（title 已钉住，不随事件推算变动） | 徽标保留；title→**已固定，不随新事件变动** |
| M3 | :455 | 取消钉住（title 取消钉住，回到按事件推算） | **取消固定**（title 取消固定，回到按事件自动算） |
| M4 | :400,:439,:479,:501 | 在场/脚下/相遇/伏笔与期待 的 muted 说明尾巴 | 缩短为：**谁在哪、谁还活着 / 本章故事发生的地点 / 同在一处的角色，可能撞出戏 / 悬着的线，点击看详情**（保留的四句即这四条；信息不变字数减半） |
| M5 | :558,:609-610 | title 采纳入账（进入世界推算）/ 已入账：X + 撤销 | **采纳，记入世界 / 已记入世界：X + 撤销** |
| M6 | :595 | 这些都按世界页的事件推算。想改？去世界页记一笔（写作时按 Alt+N 也行），或拖世界页的时间轴。 | **都按世界页的事件推算——想改就去世界页记一笔（或按 Alt+N）。** |
| M7 | 其余全部 | 此刻此地/少了谁？补一句/据正文推断/已按你的拒绝少提/恢复 | 保留 |

### 表 O · 选区浮窗与选区改写（RichTextEditor.vue + useChapterEditorContainer.ts）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| O1 | RTE :1013 | AI 润色/改写 | 保留 |
| O2 | RTE :995 | title 将选中片段加入黄金片段（同时汇入文风样本库） | **把这段存进你的文风样本库，AI 以后会学它的写法**（钮名「黄金片段」保留） |
| O3 | RTE :1028 | 这不像我 | 保留 |
| O4 | RTE :1017 | title 教去AI味小模型：先记下这段原文（改前），…成一对训练样本 | **帮 AI 学你的改法：先记下这段原文，亲手改完后选中它再点这里** |
| O5 | RTE :371-373 等 | 润色方向：优化语气、描写和句式（Enter 执行）等 placeholder | 问句式：**想怎么润色？如：更紧凑 / 更温柔（Enter 执行）；想往哪扩？如：补细节、情绪和动作；想怎么压？如：留信息、提节奏；想细写什么？如：看到的、听到的、摸到的**；换语气行保留现句（已合格） |
| O6 | RTE :1073 | 目标语气：如 冷峻/诙谐/抒情 | 保留 |
| O7 | RTE :1107 | 优化生成中... | **AI 改写中…** |
| O8 | RTE :1141-1160 | 替换原文/保留原文/已替换 · 撤销 | 保留 |
| O9 | RTE :177,:184 | 已汇入文风样本库 / 汇入文风样本库失败 | **已存进文风样本库 / 保存失败：** |
| O10 | RTE :249 | 已存第 N 对训练样本（改前 X 字 → 改后 Y 字） | **已存第 N 对「改前→改后」样本（X 字 → Y 字）** |
| O11 | container :240-247 | 优化生成完成，请确认 / 优化未返回有效结果 / 优化失败： | **改好了，请在正文里确认 / AI 没给出可用的改写，换个说法再试 / 改写失败：** |
| O12 | container :212 | 请先配置 API Key | **请先在设置里配置 API Key** |

### 表 P · 发布/审阅/灵感/格式整理

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| P1 | useChapterPublisher :53 | 请先在设置中配置 API Key 以启用角色动态状态更新功能 | **请先在设置里配置 API Key——发布后 AI 才能更新角色近况** |
| P2 | useChapterPublisher :57-59 | 确定要发布本章吗？发布后将会自动更新涉及角色的动态状态。+ warning 同义重复 | message→**确定发布本章吗？发布后 AI 会通读本章，更新涉及角色的近况。**；warning 删（与 message 重复） |
| P3 | PublishModal :65,:90 | 新提取的角色信息 / 共提取 N 个角色，其中新角色 M 个 | **从本章认出的角色 / 本章共认出 N 个角色，其中新角色 M 个** |
| P4 | CritiqueModal :38,:83 | 编辑审阅 / 暂无审阅结果 | **AI 编辑审阅 / 没有审阅结果** |
| P5 | InspirationModal | 点子启发 / 为您的剧情提供灵感火花 / 作者意图引导 (可选) / 正在思考灵感... / 应用到大纲 / 暂无灵感数据 / 重新生成 | **找灵感 / 给这章出几个点子 / 你想要什么方向？（可空）/ 正在想点子… / 收进大纲 / 还没想到点子 / 再想几个** |
| P6 | container :179 | 章节内容太少，无法审阅 | **本章内容太少——先多写一点，再请编辑看** |
| P7 | container :276,:288,:297-300 | 以使用智能格式整理功能 / 文档含未落笔的细纲胶囊… / 确认弹窗 | **…才能整理格式 / 文里有还没扩写的细纲胶囊——先扩写或删掉，再整理格式 / 整理全文格式** |

### 表 Q · 速记与情境浮卡（QuickEventNote.vue / WorldContextCard.vue）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| Q1 | QuickEventNote :230 | 一句话记下刚发生的剧情事实，AI 解析成事件草稿，你过目后入账。 | **一句话记下刚发生的剧情事实，AI 整理成事件草稿，你过目后才记入世界。** |
| Q2 | QuickEventNote :242 | 解析/解析中… | **整理/整理中…** |
| Q3 | WorldContextCard :144 | 尚无叙事时刻之前的事件记录 | **这个时间之前，还没有事情被记下** |
| Q4 | 其余（记一笔 · 世界速记/编年史/此地事件/在世界页打开 →） | — | 保留 |

### 表 R · 快捷键速查（ShortcutsCheatsheet.vue :13-44）

| 键 | 现状 | 新文案 |
|---|---|---|
| Space | 接着写：有灵感零件就拼上写，没有就顺着写 | **接着写：有卡舱画面就照着写，没有就顺着写** |
| Enter | 采纳幽灵草稿为正文 | **采纳幽灵草稿（变成你的正文）** |
| Esc | 逐层退出：蒸发幽灵稿 → 收起卡舱 → 取消吸附 | 保留 |
| Tab | 唤起灵感卡片舱 | **弹出卡舱（接着写的画面）** |
| Ctrl+Enter | 沉淀当前段（把新设定记下来） | **沉淀：把这段里的新设定记进世界** |
| Ctrl+Space | 打开走向卡（选一条接着写） | 保留 |
| Alt+N | 世界速记：一句话记事件，过目入账 | **世界速记：一句话记下剧情事实** |
| 1-4 | 卡舱开启时：捡起挂件 / 选走向卡 | **卡舱开启时：快速选择** |
| Ctrl+Z | 撤销（打字/清脂/格式整理均可反悔） | 保留（清脂为品牌词） |
| Ctrl+Shift+Z / Alt+↓ / Alt+Shift+↓ | — | 保留 |
| Ctrl+\ | 固定 / 收起副驾面板 | **固定 / 收起写作助手** |
| Ctrl+1~4 | 切换副驾 tab：打算 / 此刻 / 本章 / 检查 | **切换写作助手：打算 / 此刻 / 本章 / 检查** |
| Ctrl+5 | AI 视角（副驾底部入口：AI 实际读到的内容） | **AI 视角（写作助手底部入口）** |

组名「写作与 AI 辅助 / 修订 / 界面」保留。

### 表 S · 其余 toast 与空态（WorkspaceView / useAdaptiveAssist）

| # | file:line | 现状 | 新文案 |
|---|---|---|---|
| S1 | WorkspaceView :176 | 已恢复原稿，这些词此后降为提醒（不再自动替换） | **已恢复 AI 原稿，这些词以后只提醒不替换** |
| S2 | WorkspaceView :751,:757 | 已生成并写入章节 / 精修完成 | **已写入本章 / 润色完成** |
| S3 | useAdaptiveAssist :636 | 沉淀失败：… | **整理新设定失败：…** |
| S4 | useAdaptiveAssist :838 | 完稿审计失败：… | **完稿体检失败：…** |
| S5 | useAdaptiveAssist :847 | AI 辅助已关闭，细纲扩写不可用（顶栏 ✨ 开关可开启） | **AI 辅助已关闭，细纲扩写不可用（右上角 ✨ 可开启）** |
| S6 | WorkspaceView :974-982 | 选择一个章节开始写作 / 从左侧选择章节，或新建一个章节。 | **选一章，开始写 / 左边选一章，或者新建一章** |

### 文字总量预算表（纪律 3 的验收依据）

| 变化 | 条数 |
|---|---|
| 删除：底栏 4 态文案位 / 感知带 header / 感知带常驻引导句位移覆态 / 副标题 4 句 / SparkDock tips 行 / P2 warning 重复句 / J5 相似度数字 | **−10 处** |
| 新增：状态丸（替代原断片词，等量）/ SparkDock 舱顶标题行（替代 tips 行，等量）/ 把手 title | **+3 处（两处为替代）** |
| 替换：其余全部 old→new 等长或更短 | ≈70 处 |
| **净结论：首屏文字簇 −3（底栏、带 header、带引导句），全局文字总量 < HEAD** | |

---

## 7. 行为变化清单（唯一依据，清单外变化=事故；每条附理由——用户拍板项的依据）

| # | 变化 | 理由（必须能回答「不犯 0.x 哪一条」） | 风险 |
|---|---|---|---|
| B-01 | 感知带 260px in-flow → 28px 提醒轨 + 232px 覆态（§2.4） | 治 0.1（常驻面 −1）+ 纸列开写跳动（总纲 5） | **中**（形态变化；内容与锚定算法零改动是安全绳） |
| B-02 | 提醒轨圆点守行高 + 安全类朱点 + 轨顶 ⚑ + 轨底 +N | 0.1 下保留「哪一行有提醒」的位置信息 | 中（随 B-01） |
| B-03 | SparkDock 带内流式 → 光标层浮舱（§2.5） | 治 0.4 之外的「眼睛在光标、卡在栏顶」；归位原始设计（组件头注释与 sparkDockPos 既有齿轮） | **中高**（本期最高风险项；状态机/触发/内容零改动 + §9 回归清单兜底） |
| B-04 | 幽灵三条带内 → 光标层幽灵尾下（GHOST_DONE 一次性锚） | 提示贴着它描述的对象 | 中（无流式抖动面） |
| B-05 | 底栏删除；字数/保存态上移页头（失败红字+「已存本地草稿」继承） | 治 0.1（横栏 −1）+ 修「打字淡出藏保存失败」 | 低 |
| B-06 | 顶栏断片词 → 状态短句丸；AI 辅助带字化；抽屉钮 title 人话 | 治 0.2（机制词看不懂）+ 入口隐身 | 低 |
| B-07 | 右缘 8px 隐形条 → 12px 命中 + 常驻把手 | 抽屉可发现性（HEAD 唯一发现入口是 8px 渐变条） | 低 |
| B-08 | 抽屉副标题四行删除 | 治 0.2（与内容第一屏同义重复） | 低 |
| B-09 | 感知带卡色 token 化（深色修复）+ header「Canon 感知」删 | 深色瞎眼实锤 + 英文残留违反口径 | 低 |
| B-10 | ChapterBadges 退役「已生成/生成中」+ 删死 props | 零信息量徽标是列表噪音 | 低（存量 tier 徽标仍在） |
| B-11 | 「分析」→「提取设定」 | 二字无自解释 | 低 |
| B-12 | 空态 hero 文案（选一章，开始写） | 第一印象语气 | 低 |
| B-13 | 全量文案替换（§6 表 A-S） | 治 0.2；黑话清零 | 低（纯字符串） |
| B-14 | topReserve 测量对象：dock 槽 → 打算进度行 | 舱迁走的连带（测量机制不变） | 低 |

**清单条数：14。中高 1 项（B-03），中 3 项（B-01/B-02/B-04），其余低。**

---

## 8. 不动清单（冻结红线 + 本期豁免重申）

- 七键契约（Space/Ctrl+Space/Tab/Esc/Alt+N/Alt+O/Ctrl+Enter）与键位状态机；Esc 逐层语义（幽灵蒸发在编辑器 keymap，优先于一切栈内浮层）。
- 心跳三计时器 / 感知常驻 detach 语义 / 章节纪元守卫；静音学习链（dismiss-hint 载荷与 MUTEABLE_KINDS 白名单）。
- 幽灵草稿机制（含 reapGhostIfDead、蒸发理由 toast）；细纲胶囊机制；SSE 帧与 GHOST_* 字段；wash/repaired 增量字段。
- `computeCursorDockPos()` 公式本体；dock 零件缓存签名输入；四槽位语义与排序；`_finalize_parts` 规整。
- 感知锚定算法本体（仅 bandEl 指向与 topReserve 测量对象适配，§2.4.4）。
- SparkDock 可见性状态机（sticky/stash/restore/打字隐藏/自动弹舱守卫/dock_muted 消费）与两级层级 chip 内容。
- BeatCardDock 全部（触发/定位/互斥/内容，仅表 D 三处文案）。
- splitpanes 与 sizes 持久化；binder 结构（列表/多选/底三钮/徽标体系除 B-10）。
- 抽屉 380px/44vw、hover 瞥看/pin 推挤双态、Ctrl+\、报告到达滑出一次、收件箱 toast 直达（OPEN_INBOX_EVENT 链）。
- InspectorPanel 四 tab 架构与各分区内容构成、默认 tab 切换逻辑（空章→打算/有正文→此刻/用户切过即尊重）、Ctrl+1~5 处理器所在层级。
- 点火卡显隐门控（showIgnition 全条件）与位置；空章冷启动链路。
- TipTap mark 类名；stripGhostDraftHtml 消费链；canon 词表注入链。
- `--editor-max-width: 880px` 与排版三 token、editor-type-large 实验开关。
- placeFloating/useFloatingLayer/useEscStack/ModalShell 接口签名；后端零改动。
- 世界页/大纲页/文风页/AppRail——全部不在本期范围。
- 各 tab 内容组件内部逻辑（SpinePanel/WorldSceneSlice/检查三组/AI 视角三件）——纯文案层改动，结构与流程零改动。

---

## 9. 验收清单

> G = grep/脚本；M = 目检；I = 交互手测。I 类 = 渲染/静态（I-01~I-10）；II 类 = 交互（II-01~II-16）。证据本地留存不入库。

### I 类（渲染/静态）

- **I-01【G】** 黑话清零：`grep -rn "副驾\|Canon 感知\|逆向提取\|章级特例\|继承书级\|锚定\|钉住\|入账\|快检\|在屏\|上屏\|规避\|动态状态\|汇入文风\|为您\|地点穿越\|疑似泄底\|私有设定外泄\|完稿审计\|精修中\|审校中\|相似度" frontend/src/features/workspace/ frontend/src/features/generation/ frontend/src/features/chapter-editor/ frontend/src/components/RichTextEditor.vue frontend/src/components/InspirationModal.vue`——模板/title/placeholder/toast 字符串零命中（注释与 `__tests__` 白名单；ContextPreviewSection 的「锚定」仅 L3 两处在替换范围）。
- **I-02【G】** `grep -n "status-bar\|nle-topbar__state" frontend/src/features/workspace/containers/WorkspaceView.vue frontend/src/style.css` 零命中；页头 meta 行含 `N 字` 与保存态。
- **I-03【G】** 冻结 diff 零：`computeCursorDockPos` 函数体；`stackAnchoredTops` 函数体；canon-mark/ghost-draft/outline-note 类名串；七键 keymap 段；SSE 消费字段名；`dismiss-hint` 载荷。
- **I-04【G】** 新/改样式段无新增 token、无新 z 值（只允许 40/50/80/85 既有值）、无裸 hex（薄荷 #34d399 品牌字面值与复用 .inspector-drawer 投影值豁免）、无新裸 font-size。
- **I-05【G/M】** 文字预算：§6 预算表成立——首屏文字簇较 HEAD −3；副标题四行不存在；SparkDock tips 行不存在。
- **I-06【M】** 几何锚四视口实测（§5.1 表）：1200 / 1093(DPI) / 1280 / 1200+抽屉 pin——纸列宽度与文字量度达标；**打字激活辅助层瞬间纸列零位移**（HEAD 对比组会跳 260px，本期必须不动）。
- **I-07【M】** 深色主题全写作台巡查：提醒轨圆点五色可辨、覆态卡无粉彩瞎眼、状态丸/带字开关/把手/光标层两舱可读。
- **I-08【M】** 浅色对照：纸列 parchment 层级不被覆态/把手糊边；提醒轨常态近乎隐形。
- **I-09【G】** `grep -n "TAB_SUBTITLES\|tab-subtitle\|band-header\|band-dock-slot\|spark-dock__tips" frontend/src/` 零命中（注释豁免）。
- **I-10【M】** `--editor-max-width` 恒 880px（DevTools computed）；editor-type-large 切换正常。

### II 类（交互）

- **II-01【I】** 第一眼落点验收（设计意图）：空章进写作台——首屏只有 binder/纸列/点火卡三簇；无世界数据书同样成立。请非技术用户视角走查：第一眼看的是纸。
- **II-02【I】** 提醒轨全周期：打字 ≥4 字轨出现（纸不动）→ 心跳出提醒 → 圆点守行高（滚动跟随）→ hover 120ms 覆态读卡 → 移出即收 → 点击钉住 → 外点/Esc 收 → 安全类朱点无 ×、普通类 × 24px 命中且多收几次后少提（静音链回归）。
- **II-03【I】** 键盘路径：Tab 序到圆点 → focus-within 覆态开 → Tab 进卡内 × → Esc 关覆态且焦点回编辑器。
- **II-04【I】** SparkDock 光标层：停顿 4s 段尾弹舱在光标下 8px 左对齐文本块；近视口底上翻；近右缘夹紧；Tab 召唤/数字键吸附/点击吸附/打字隐藏/sticky 连续吸附/Esc 收舱/滚动跟随——与 HEAD 逐一同。
- **II-05【I】** 互斥与收割：SparkDock×BeatCardDock 互斥；幽灵在屏两舱皆隐；幽灵 Esc 蒸发/Enter 采纳/退格收割（reapGhostIfDead）回归。
- **II-06【I】** 幽灵三条：造 dead_speak+cliche 命中 → GHOST_DONE 后三条在幽灵尾下方纵叠（疑点→返修→洗层），不遮幽灵正文；「用原稿」学习回流；拒稿逃生舱「还是贴出来（带疑点标记）」回归（materializeRejectedGhost）。
- **II-07【I】** 抽屉：把手常态可见（50%）；hover 右缘 12px 滑出；Ctrl+\ pin 推挤；报告到达滑出一次（手动关过不反复）；四 tab 内容/默认切换逻辑回归；无副标题行。
- **II-08【I】** 顶栏：Space 按下即亮「正在往下写…」（2-7s 等待期全程在）；停顿心跳后「AI 正在看你写的」；Ctrl+Enter「正在整理新设定…」；完稿体检「正在通读全章…」；无态整丸缺席；error 朱色；AI 辅助关→Space 普通空格+toast；打字淡出+hover 召回。
- **II-09【I】** 保存链路：打字→页头「保存中…」→「已保存 HH:MM」；断网→「保存失败（已存本地草稿）」红字在页头**且不随打字淡出**；字数随写随变（tabular-nums 不跳宽）。
- **II-10【I】** 点火卡：空章+有大纲→卡现；意图失焦即存；⚡ 写个开头/我自己写/✨ 出主意三路径回归；无大纲 hint=「先在右侧『打算』页…」；纯手写模式不弹。
- **II-11【I】** 极端态·空章（有世界数据）：提醒轨隐形（无内容）；点火卡在；抽屉默认关。
- **II-12【I】** 极端态·长章（5000+ 字、提醒 >10 条）：轨点分布守行高、轨底 +N 正确；覆态兜底区折叠 +N 更多展开；锚定卡下推避让不叠；滚动 rAF 跟随无飘。
- **II-13【I】** 极端态·无世界数据书：此刻 tab 空态原文；提醒轨零内容；写作主链路（Space/Tab/Ctrl+Enter/体检）零报错。
- **II-14【I】** 七键契约全回归：Space（有/无零件）/Ctrl+Space/Tab/Esc 逐层/Alt+N/Alt+O/Ctrl+Enter 逐一；细纲胶囊扩写全流程。
- **II-15【I】** 写作闭环动线（设计意图验收）：空章 → 点火卡写一句（或我自己写）→ 写中提醒轨守行 → 停顿卡舱光标旁弹出 → Space/Tab 用卡 → 幽灵三条贴幽灵尾 → Ctrl+Enter 沉淀 → toast 去确认 → 抽屉此刻收件箱裁决 → 完稿体检 → 抽屉滑出报告 → 残句修复/润色/读者反馈。全程无死路、无遮挡、无双重入口。
- **II-16【I】** reduced-motion：覆态/光标层/抽屉/菜单全部瞬切；1200px 最窄窗与 1093 DPI 下 II-02/04/07 复跑无布局塌陷。

---

## 10. 与 04/05/06 期的条款处置（取代关系唯一权威）

**04 期**（文案人话化 + chrome 微调）——**大部分继承，两处修正**：

| 04 期条款 | 处置 |
|---|---|
| §4 文案替换表 24 张 | **继承收敛版**（§6 表 A-S）：品牌词（卡舱/挂件/清脂/沉淀/蒸发/收编）按 AGENTS.md 口径保留不替换；黑话清零项全部继承 |
| §2.1 删底栏上移页头 | 继承（§2.3） |
| §2.2 状态丸 | 继承（§2.2），样式复用 style.css 既有段 |
| §2.3 AI 辅助带字开关 | 继承（§2.2） |
| §2.4 抽屉把手 | 继承（§2.6） |
| §2.5 感知带折叠态徽章化 | **废弃**（感知带形态整体重构为提醒轨，徽章无载体；安全提权语义由朱点继承） |
| §3.1 点火卡扉页化（440px/动效） | **废弃**（形态不动治 0.1；仅文案两处继承） |
| §3.2 ChapterBadges 精简 | 继承（§2.1） |
| §3.3 分析→提取设定 / §3.4 空态 hero / §3.5 发布浮层 | 继承 |

**05 期**（书脊/批注层/光标层/图标栏+面板制）——**结构条款全部废弃，两件成果继承**：

| 05 期条款 | 处置 |
|---|---|
| §1 书脊 + 目录抽屉（splitpanes 退役） | **废弃**（治 0.1/0.3；binder 常驻是常规形态非翻车成分） |
| §2 感知带去栏体化（244 批注区） | **废弃壳，继承核**：圆点守行高（§2.4 取代 36px 折叠条）、卡色 token 化（03/05 同方案） |
| §4 SparkDock 与幽灵三条迁光标层 | **继承**（§2.5——三期中唯一经得住「归位」检验的结构变化；原始设计即光标位，有既有齿轮实证） |
| §5 图标栏 + 面板制 + 本章解散 | **废弃**（治 0.1/0.3/0.4；四 tab 抽屉保留） |

**06 期**（工作条/章首三区/单面板长卷）——**全部废弃，仅两条诊断继承**：

| 06 期条款 | 处置 |
|---|---|
| §3.1 工作条 / §3.2 章首时空戳+打算卡 / §3.5 长卷五段面板 / 书脊图标栏删除（05 的再推翻） | **全部废弃**（翻车现场主体；章首两行稀释第一眼落点、长卷面板默认摊开、双重意图输入） |
| §1.4-3「副标题重复是结构病」+ §3.6「一头一句」纪律 | **继承为保守形态**：只删重复副标题（§2.6），不为它再造结构 |
| 功能调研方法（时机×频率×内容量） | 继承为本文 §2 各表「理由」列的写法 |

---

## 11. 考虑过并否决（防施工走样）

1. ** binder 也收成抽屉/书脊——否决。** 05/06 已烧；章节列表常驻是桌面写作软件常规形态（Word/Scrivener 导航窗格），用户肌肉记忆在此。本期发现性预算只花在真正隐身的两件（提醒轨自解释、抽屉把手）。
2. **提醒覆态改常驻细栏（如 120px 常驻迷你卡）——否决。** 任何形式的常驻都会再犯 0.1；提醒的真实密度（0-3 条小卡）不配常驻面积。覆态 peek 与右抽屉 hover 同族，手势零新增。
3. **SparkDock 留在原处只修可见性——否决。** 带体已解构则无家；栏顶位置与视线的距离是原生病（05 期 §4.1 论证成立且与组件原始设计一致）。
4. **BeatCardDock 顺手接 placeFloating 钳位——否决。** 03 期规划未施工则非翻车成分；本期风险预算集中给 B-03，走向卡舱零触碰控面。
5. **给提醒轨加「新提醒到达时自动展开一次」——否决。** 违反安静知情（总纲 4）；圆点出现+守行高已是足量信号，安全类朱点自带提权。
6. **点火卡扉页化（04 §3.1）回搬——否决。** 空章首屏已是「纸+一卡」的干净形态，翻车不在此；形态改动一律从简。
7. **AI 视角从抽屉底钮再降级（收进设置）——否决。** 功能零删除约束 + 现位置已是降级位，不动。

## 需用户拍板

**无硬性拍板项。** 一处实测关注（非拍板）：B-03 卡舱移到光标旁后，停顿自动弹舱的视觉存在感的会比带内强——这正是设计意图（卡住了就在看的地方给零件），若实测嫌打扰，回退预案 = 自动弹舱守卫加严（如仅 Tab 召唤不自动弹），一行条件改动，已在 II-04 配实测项。

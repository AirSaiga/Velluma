# 第 8 期：写作台完全重构 —— 桌上一张纸（UX 重构 · 设计规格 · 唯一施工权威）

> 前置：第 0 期 `00-foundation.md`（token / z 层表 / 浮层规范继续消费，不另立）；第 7 期 `07-writing-desk-redesign.md`（文案表 A-S 与光标层 CursorLayer 两项成果继承，其余条款由本文取代）。
> 基线：**07 期施工完成态（工作区未提交）**。本文是写作台的完全重构稿——骨架全部重审，无一默认保留。
> 用户原话（本期边界的唯一来源）：「完全完全完全地重构」；前两轮裁决证据见 §1。
> 范围：`features/workspace/containers/WorkspaceView.vue`、`features/workspace/containers/InspectorPanel.vue`、`features/workspace/presentation/`（PerceptionBand / ChapterBadges / 新增 ChapterSpine / ChapterTocDrawer / TocPage / AssistRail / ChapterTocList）、`features/chapter-editor/presentation/ChapterEditorView.vue`、`components/ChapterEditor.vue`、`features/chapter-editor/containers/ChapterEditorContainer.vue`、`features/generation/presentation/`（IgnitionCard / ShortcutsCheatsheet 两件；CursorLayer / SparkDock / BeatCardDock / 幽灵三条零改动）、`components/RichTextEditor.vue`、`style.css`。
> 不在范围：世界页/大纲页/文风页/数据页/AppRail/一切后端。

---

## 1. 诊断：为什么骨架本身必须动

### 1.1 两轮裁决的证据链

- **04/05/06 期（回退）**：「被改得乱七八糟的……各种组件的布局位置很不自然……作者点进去都不知道应该看哪，还有这些乱七八糟的文字都是什么。」三期叠加后首屏 11 处同时说话的界面元素——**加法是死路**。
- **07 期（被判隐形）**：「和最原本的界面有什么区别啊？侧栏一点不变的啊？」骨架不动的纯减法，视觉上等于没做——**不动骨架的减法是另一条死路**。

两条死路夹出唯一活路：**减常驻面，且把减下来的每件东西换一个符合直觉的新家**。新家不能发明形态（04/05/06 死因），只能搬用产品里已经被用户接受的形态——世界页 M6「右缘图标栏 + 浮出抽屉」自 2026-08-28 上线至今零投诉，是唯一经实机验证的「栏—面板」语言，本稿全屋复用。

### 1.2 HEAD 骨架的五个结构性原罪（07 期未触碰，故 07 被判无效）

1. **常驻面税制**。binder 章节列表占编辑器左侧 20-32% 常驻宽，服务的却是「切章」这个一场写作发生个位数次、每次两秒的任务。它是首屏上文字行数最多、对比最高的一块面——**第一眼落点被章节列表抢走，纸面沦为屏幕上「剩下的那块空间」**。07 保留它，等于保留了第一眼杀手。
2. **框架先于内容**。AppRail（56）→ binder（~229）→ 顶栏 → 页面头 → 纸面：作者的目光要穿过四层家具才到自己的字。写作软件的先验参照物（Word/Scrivener）确实都有导航窗格——但它们的内容区占比与视觉权重远高于此；本作的 binder 在 1200px 最小窗宽下与纸面几乎等宽（229 vs ~875 含页边），量级失衡。
3. **AI 辅助散居四处，没有统一心智地图**。状态在顶栏、提醒在左轨、卡舱在光标、干活在四 tab 抽屉——四个家各自有理（07 逐件论证过），但系统层面「AI 到底住哪」没有答案，于是每个家都要配解释文字，文字墙由此而生。「这些乱七八糟的文字都是什么」的病根是**居所分散**，不是措辞。
4. **发现性押注在隐形边缘与记忆键位上**。右抽屉的唯一发现入口曾是 8px 渐变条（07 加了把手，仍是补丁不是形态）；目录、助手、快捷键全靠用户「已经知道」。新用户不可达。
5. **纸不是纸**。`.paper` 用静态 `bg-parchment-50`（ChapterEditorView.vue:102）、RichTextEditor 根同样静态 `bg-parchment-50`（RichTextEditor.vue:945）——深色主题下纸面恒白而 `--text-primary` 是暖白 `#ede8df`，**白字白纸，HEAD 预存 P0 不可读**。点火卡以浮卡姿态压在空纸中央（IgnitionCard.vue:83-97 absolute 居中），纸面连空着的时候都不是主角。

### 1.3 结论

骨架五件（AppRail / binder / 纸列 / 顶栏 / 右抽屉）中：AppRail 是全局导航非写作台私物（动它 = 破坏全 app 一致性，保留）；**binder 与顶栏两件删除，以新形态转世**；纸列升格为唯一常驻主角；右抽屉改形为世界页同款图标栏。下文全部设计都从「第一眼只能是纸」反推。

---

## 2. 总纲与设计原则

**统一愿景（一句话）**：写作台是一张书桌——**纸在中央，目录收进左缘的书签里，助手收进右缘的抽屉栏里**。写的时候，屏幕上只剩纸和光标；需要帮手时，东西都在它该在的那条边缘上，一伸手就到，一收就回。

**心智地图（作者只需记三句话）**：
- **左边是书**——章节、目录、返回书架，全在左缘书签后面。
- **右边是 AI**——开关、打算、此刻、本章、检查、AI 视角、快捷键，全在右缘栏后面。
- **中间是我**——纸面上的东西只有两种：我写的，和 AI 递到我手边的（光标旁的卡舱、页边的批注点）。

**设计原则（验收逐条对照）**：

1. **第一眼落点唯一且恒为纸**。任何视口、任何章节状态，首屏视觉重心 = 纸列。无选中章时纸面本体就是目录页——连「选哪章」这个前置任务也在纸上完成，不在另一块 chrome 上。
2. **零常驻宽**。纸列几何全程恒定：目录抽屉、助手面板、批注覆态全部 overlay，不推不挤（唯一例外 = 作者主动 pin 助手面板，语义继承 HEAD）。常驻物只剩两条 40-44px 缘签，静默到近乎隐形。
3. **同物同形，全 app 一套「栏—面板」语言**。助手栏逐像素同构世界页 atlas-rail 心智：图标栏常驻右缘、点击开、一次一格、Esc/外点收。作者在世界页学会的手势在写作台原样生效——新手势零新增。
4. **时机即位置**。写前（目录页 / 打算面板）、写中（光标层卡舱 / 纸边批注）、写后（检查面板 / 报告）各有其时，不时不现。主动推送维持 HEAD 仅有的两件：完稿报告滑出一次、沉淀 toast 直达——一个不多。
5. **纸是 token 驱动的真纸**。新增 `--paper-bg` 双主题 token（唯一新 token），浅色是暖白纸、深色是灯下纸；深色白字不可读 P0 随此根治。
6. **文字预算继承 07**：解释性长句零新增；07 文案表 A-S 全量继承（§6 注明载体重定位的少数条目）；品牌词口径按 AGENTS.md 不动。

---

## 3. 布局总图（三态）

### 态 A · 无选中章 = 目录页（进写作台的第一眼）

```
┌──────────────────────────────────────────────────────────────────────┐
│ A │                                                                  │
│ p │            ┌────────────── 纸 880px ──────────────┐              │
│ p │            │                                      │              │
│ R │            │           长 夜 将 明                 │              │
│ a │            │           ── 目 录 ──                │         ┌──┐ │
│ i │            │                                      │         │✨│ │
│ l │            │   1   雨夜来客                       │         ├──┤ │
│   │            │   2   车站              ·已发布      │         │打│ │
│ 5 │            │   3   未命名章节          ·草稿      │         │今│ │
│ 6 │            │                                      │         │本│ │
│ p │            │   ＋ 新起一章                        │         │检│ │
│ x │            │                                      │         ├──┤ │
│   │            │   ────────────────────               │         │AI│ │
│   │            │   从 .md 文件批量导入章节             │         │？│ │
│   │            │                                      │         └──┘ │
│   │            └──────────────────────────────────────┘         右缘  │
│   │                             纸面即界面                       助手栏│
└──────────────────────────────────────────────────────────────────────┘
 首屏说话的面 = 一张纸（书名+目录）。右缘栏静默。左缘书签缺席（你已在目录上）。
```

### 态 B · 写字中（干净态，90% 时间的样子）

```
┌──────────────────────────────────────────────────────────────────────┐
│ A │ 左│┌──────────────── 纸 880px 恒定居中 ────────────────┐         │
│ p │缘││ 第3章 · 1,234 字 · 已保存 14:02                ⋯ │         │
│ p │书││                                                  │         │
│ R │签││ 章节标题（衬线大字，写在纸面上）                   │    ┌──┐ │
│ a │  ││                                                  │    │✨│ │
│ i │第││ 正文正文正文正文正文正文正文正文正文正文正文正文    │    ├──┤ │
│ l │3 ││ 正文正文正文正文正文正文正文正文正文正文正文正文    │    │打│ │
│ 5 │章││ 正文正文正文正文正文正文正文▏                     │    │今│ │
│ 6 │  ││ 正文正文正文正文正文正文正文正文正文正文正文正文    │    │本│ │
│ p │  ││                                                  │    │检│ │
│ x │  ││                                                  │    ├──┤ │
│   │  ││                                                  │    │AI│ │
│   │  │└──────────────────────────────────────────────────┘    │？│ │
│   │  │  点击 = 目录抽屉                              右缘助手栏└──┘ │
└──────────────────────────────────────────────────────────────────────┘
 打字中：左右缘签淡出至 35%（hover 即复原），页面头 meta 行不淡（保存态不藏）。
```

### 态 C · 辅助激活（停顿卡舱 + 页边批注 + 助手面板同屏极限）

```
┌────────────────────────────────────────────────────────────────────────┐
│ A │左│┌──────────── 纸（零位移） ────────────┐ ┌─── 助手面板 380 ───┐ │
│ p │缘││ 第3章 · 1,247字 · 保存中… ·●AI正在看你│ │ 此刻          固定 ×│ │
│ p │书││                                      │ ├────────────────────┤ │
│ R │签││ 正文正文正文正文正文正文正文正文正文   │ │ 在场：…             │ │
│ a │  ││·正文正文正文正文正文正文正文正文正文   │ │ 脚下：…             │ │
│ i │  ││ 正文正文正文正文▏                     │ │ 头顶的线：…         │ │
│ l │  ││ ┌─ 卡舱（光标下 8px）────────┐        │ │ 收件箱 · 2 条待确认  │ │
│   │  ││ │ ▸ 接着写：他伸手去够门把    │        │ │                    │ │
│   │  ││ │ ⚑ 通往「夜访」：…          │        │ │                    │ │
│   │  ││ └───────────────────────────┘        │ │                    │ │
│   │  │└·─────────────────────────────────────┘ └────────────────────┘ │
│   │  │ ↑页边批注点（守行高；hover→覆态读卡向右开）   点击右缘图标开/Esc 收 │
└────────────────────────────────────────────────────────────────────────┘
 三处 AI 同时在场时：卡舱在光标（写）、批注在页边（看）、面板在右缘（干）——各就各位，纸不动。
```

---

## 4. 分区详设

### 4.1 纸列（唯一常驻主角）

- 几何：`--editor-max-width: 880px` 值不动；水平居中于书桌区（AppRail 以右全部宽度）；纵向 pt-5 / pb-5（顶栏删除后顶部留白补齐，视觉重心归中）。
- **纸面 token 化（P0 根治）**：
  - 新 token（双主题成对，本期唯一新 token）：
    - `:root { --paper-bg: #fefdfb; }`（= 现 parchment-50/--bg-canvas 值，浅色逐像素零变化）
    - `:root.dark { --paper-bg: #26231e; }`（比桌面 `--bg-primary #1a1815` 亮一档的「灯下纸」；与 `--text-primary #ede8df` 对比 ≈11:1，placeholder `--text-muted #8a8275` ≈4.6:1 达 AA）
  - `.paper`（ChapterEditorView.vue:102）：删静态 `bg-parchment-50`，改 `background: var(--paper-bg)` + 新增 `border: 1px solid var(--border-color)`（深色下阴影不可见，边框给纸的轮廓；浅色下边框与既有阴影叠加无感）。既有 box-shadow 字面值保留（深色下自然隐形，无害）。
  - RichTextEditor.vue:945 根节点删 `bg-parchment-50`（改透明，纸提供底色）；945-1130 区间其余 `bg-parchment-*` 为浮窗内部 chip 底色，浅色语义保留，深色由各 chip 既有 token 类兜底——**本期不动**（浮窗深色已有 dark: 变体的不动；无 dark 变体的列验收 I-07 巡查项）。
  - 发布中浮层（ChapterEditorView.vue:105）`bg-parchment-50/80` → `color-mix(in srgb, var(--paper-bg) 82%, transparent)`。
- 页面头 meta 行（07 期 §2.3 成果继承）升格为**纸上唯一状态行**：
  `第N章 · 已发布 · N 字 · 已保存 HH:MM · ● AI 正在看你写的` … `⋯`
  - 末位新增 AI 状态件：`aiStateLabel` / `aiStateError` 两 prop 自 WorkspaceView 经 ChapterEditor → ChapterEditorContainer → ChapterEditorView 下传（wordCount 既有链路同款，三层各加 ≤4 行）。文案 = 07 表 A1/A2 原文；形态 = 6px 呼吸点 + `--text-xs` muted；error 态 `--danger`；空态整件缺席。容器 `aria-live="polite"`。
  - meta 行**永不参与打字淡出**（保存失败红字语义继承 07 修复）。
- 页面头 ⋯ 菜单、衬线大标题、placeholder（07 表 B）全部原样。

### 4.2 左缘书签（ChapterSpine，章节系统的写中入口）

- 形态：absolute 贴书桌区左缘、垂直居中，宽 40px、高 fit-content（min 120px），`background: var(--bg-elevated)` + 1px `var(--border-color)`（左缘无框），圆角 `0 var(--radius-lg) var(--radius-lg) 0`，z `--z-page-chrome`（40）。
- 内容（自上而下）：`book-open` 图标（目录语义；避开助手栏已用的 document，防图标撞车）+ 竖排当前章标识（`writing-mode: vertical-rl`，`第3章 · 标题`，`--text-xs` muted，超过 10 字截断）。整签一个 button，`title="章节列表"`。图标名已核对 Icon.vue 注册表：book-open 既有；列表类图标（queue-list/bars-3）未注册，禁新造 SVG。
- 显隐：**仅在有选中章时存在**（无选中章时纸面就是目录，书签缺席）；打字淡出族成员（态 B 注）。
- 交互：点击 → 开目录抽屉（4.3）；键盘 Tab 可达，Enter/空格同点击。无 hover 展开（防划过误开，点击制与右栏同律）。

### 4.3 目录抽屉（ChapterTocDrawer，binder 的转世）

- 形态：absolute 贴书桌区左缘全高，宽 320px，`var(--bg-secondary)` + 右边框 + 右向投影（复用 `.inspector-drawer` 投影值方向镜像），滑入 `translateX(-24px)+opacity → 0/1` 0.22s（reduced-motion 瞬切），z `--z-drawer`（85）。**overlay 不推纸**。
- 内容 = binder 全量功能平移（零功能删除）：头部（返回书架钮 + 书名 + 多选钮）→ 多选全选栏 → 章节行列表（行 = 序号 + 标题 + ChapterBadges + hover 删除钮，逐行结构照抄现 binder 行）→ 多选批量栏 → 底部三钮（新建章节 / 导入 .md / 提取设定——disabled 逻辑照抄：提取设定需有选中章）。
- 关闭路径：选中任一章（=完成使命即收）/ Esc（入 useEscStack）/ 外点（pointerdown 落在抽屉与书签之外）/ 再点书签。
- **无 pin 模式**（切章是秒级任务，pin 无场景；少一个状态）。
- 章节行渲染抽共享组件 `ChapterTocList.vue`（props：chapters / selectedId / selectMode / checkedIds；emits：select / toggle-check / delete），目录抽屉与目录页（4.4）共用一份行结构——杜绝双份漂移。

### 4.4 目录页（TocPage，无选中章时的纸面本体）

- 取代现 `.empty-editor` 空态块（WorkspaceView.vue:970-978 删除）。**纸面几何与章页完全同构**（880 居中、同 pt/pb）——翻页不换桌子。
- 纸上内容（全部衬线、居中轴）：
  - 书名大标题（`--text-3xl` + `--font-heading`）+ 其下一行 `--text-sm` muted「目录」；
  - 章节条目区（`ChapterTocList` 的 page 变体：行高放宽至 2.4rem、序号 tabular-nums、标题左对齐、徽标同行；行数超纸面则纸内滚动）；
  - 末行「＋ 新起一章」（虚线边框行，点击 = createChapter 既有函数）；
  - 纸底一行 `--text-xs` faint：「从 .md 文件批量导入章节」（text button，开既有 MarkdownImportModal）。
- 零章节书：条目区显示一行「这本书还没有章节」+ 主钮「新起第一章」。
- 多选删除在目录页不提供（管理动作归目录抽屉；纸面保持读感）。
- 点火卡不出现在目录页（它属于空章页，4.6）。

### 4.5 右缘助手栏（AssistRail，AI 辅助的唯一的家）

- 形态：absolute 贴书桌区右缘、垂直居中，宽 44px，`var(--bg-elevated)` + 边框（右缘无框）+ 圆角 `var(--radius-lg) 0 0 var(--radius-lg)`，z 40。**逐像素同构世界页 atlas-rail 心智**（但全部消费 token，不抄世界页的硬编码 rgba——世界页是历史遗留，新件必须 token 干净）。
- 栏位序（自上而下，固定）：
  1. `✨` AI 辅助总开关（带 6px 状态点：开=`#34d399` 薄荷品牌值 / 关=`--text-faint`；active 态图标 `--accent-500`；title 继承 07 表 A3/A4 原文）
  2. 分隔线
  3. `💡` 打算（Ctrl+1）· `🗺` 此刻（Ctrl+2）· `📄` 本章（Ctrl+3）· `✅` 检查（Ctrl+4）——图标沿用现 InspectorPanel tab 图标名（light-bulb/map/document/check-circle），零图标映射变化；实际渲染走 Icon 组件同名
  4. 分隔线
  5. `🔍` AI 视角（Ctrl+5）
  6. `？` 快捷键一览（栏底）
- 徽章：检查图标带 6px `--danger` 圆点 = 完稿报告到达且尚未看过（面板在报告到达后在「检查」开过一次即灭，WorkspaceView 持一个 ref）。无其他计数徽章（收件箱计数无现成数据链，本期不做）。
- 交互：点击图标 → 开对应面板（4.6）；再点同图标 / Esc / 外点 → 收；点击 ✨/？ 不开面板（各自直行动作）。Tab 序可达。打字淡出族成员。
- hover 瞥看**退役**（见 §9-4 与拍板项 P-2）。

### 4.6 助手面板（InspectorPanel 的去 tab 化改造）

- 形态：复用 `.inspector-drawer` 全部样式与过渡（fixed 右缘 380px / max 44vw / z 85），**overlay 不推纸**；pin 态推挤继承 HEAD 语义（`.workspace-view--drawer-pinned` padding-right 既有实现不动）。
- **内部 tab 栏与底部「AI 视角」钮删除**——栏在 4.5，面板壳只渲染当前分区。新增面板头行：分区名（打算/此刻/本章/检查/AI 视角，`--text-md` 600）+ 右侧 pin 图标钮（Icon 名 `pin`，**05 期已注册、注册注释即「面板/目录固定钮」**，零新增 SVG；title「固定面板（Ctrl+\）」，pin 态 `--accent-500` 高亮）+ × 关闭钮（Icon `x-mark`，24px 命中）。
- 分区内容组件**零改动**：SpinePanel / WorldSceneSlice / 本章统计与真相入口 / 检查三组 / ContextPreviewSection+世界模型快照——原样挂载，只换壳。
- 状态归属上移 WorkspaceView：`assistPanelOpen`、`assistPinned`（持久化沿用 uiPrefs.rightDrawerOpen 键，语义不变）、`activeTab` 以 `v-model:active-tab` 与 InspectorPanel 双向同步。**InspectorPanel 内默认 tab 逻辑（空章→打算/有正文→此刻/用户切过即尊重）与其 Ctrl+1~5 的 window 监听原样保留**——只加一行：切 tab 时 `emit('activate', key)`，WorkspaceView 收到即开面板。栏点击 = WorkspaceView 写 activeTab + 开面板。两条路汇于同一状态，无双源。
- 主动推送继承：完稿报告到达 → 面板以「检查」滑出一次（手动关过不反复，`_drawerAutoOpened` 逻辑平移）；沉淀 toast「去确认」→ OPEN_INBOX_EVENT → 以「此刻」滑出（既有链路平移）。
- Esc 细则：面板开在 window 层注册 useEscStack；**事件目标位于 input/textarea/[contenteditable] 内时不收**（SpinePanel 内联编辑自带 Esc 语义，防一按两收）。幽灵蒸发在编辑器 keymap，焦点在编辑器时 Esc 永远先蒸幽灵——既有语义不动。
- Ctrl+\ 语义映射：面板关 → 开并 pin；开未 pin → pin；已 pin → 收并解 pin。

### 4.7 页边批注（PerceptionBand 第三次落位：纸的左页边）

- **几何迁移**：07 期提醒轨挂在 `.editor-host` 左缘（视口感知）；本期迁到**纸列左页边**——挂载点不变（WorkspaceView 内），根容器改绝对定位覆于纸列：`left:50%; transform:translateX(-50%); width:var(--editor-max-width); max-width:100%; height:100%`，圆点落在容器 `left:14px`（纸的 px-12=48px 页边内，贴近它所注的那一行，如印本书的句读批点）。
- 根容器 `pointer-events:none`，圆点与覆态 `pointer-events:auto`——不拦截正文选区与点击。
- 覆态读卡**向右开**（覆于正文上，宽 232px，peek 语义同 07）；打开/关闭三态（hover 120ms / focus-within / 点击钉住）与 Esc 入栈全部继承 07 §2.4.2。
- **冻结继承清单**：锚定算法（`.canon-mark` 视口 Y 查询 / `stackAnchoredTops` / rAF 节流 / bandEl 指向根元素）函数体零 diff——本次只改横向几何，纵向语义天然不变；卡五族 color-mix 色族、安全类朱点提权、× 静音链（MUTEABLE_KINDS / dismiss-hint 载荷）、轨底 +N、轨顶 ⚑、覆态内容结构（打算进度行 → 锚定卡 → 兜底区）逐行继承。
- props/emits 零变化（`suggestions` / `spineProgress` / `dismiss-hint`）。

### 4.8 光标层与点火卡

- **CursorLayer / SparkDock / BeatCardDock / 幽灵三条 / ThinkingIndicator：零改动**（07 §2.5 成果是「归位正确」的少数结构件，用户两轮裁决均未指向它）。挂载点随 WorkspaceView 模板迁移原样平移。
- **点火卡入纸**（IgnitionCard 形态改造）：
  - ChapterEditorView 在 page-head 与 RichTextEditor 之间加 `<slot name="page-top" />`；WorkspaceView 把 `<IgnitionCard v-if="showIgnition">` 移入该 slot（显隐门控 `showIgnition` 全部条件零改动）。
  - IgnitionCard 根样式由 absolute 居中浮卡（:83-97）改**纸内页首块**：去 absolute/translate/浮卡阴影/边框/底色；宽度与正文列对齐；标题「本章还是白纸」改衬线 `--text-lg`；输入区与按钮行结构零改动。
  - 文案全继承 07 表 E。
  - 效果：空章的纸面 = 页面头 + 一句衬线问句 + 两个选择（⚡ 写个开头 / 我自己写）——**纸自己在问**，不是一张浮卡压在纸上。

### 4.9 打字沉浸 2.0

- 顶栏删除后，淡出对象 = 左缘书签 + 右缘助手栏两件：`isTyping` 时两者 opacity → 0.35（transition 0.3s），`:hover`/`:focus-within` 立即复原。实现：`.workspace-view--typing` 挂根，CSS 两条。
- 纸面、页面头 meta 行、批注点、光标层**全部不淡**（内容与其近侍不受打扰）。

### 4.10 行为变化总表（清单外变化 = 事故）

| # | 变化 | 治 §1.2 哪条 | 风险 |
|---|---|---|---|
| R-01 | binder splitpane 删除 → 目录页 + 左缘书签 + 目录抽屉 | 原罪 1/2 | **高**（本期最大骨架赌注；安全绳 = 功能零删除 + ChapterTocList 共用） |
| R-02 | 顶栏删除；状态丸 → 页面头 meta 行末位；AI 开关/快捷键 → 助手栏顶/底 | 原罪 2/3 | 中（发现性由栏位顺序与 title 继承兜底） |
| R-03 | 右抽屉 hover 瞥看 → 点击制图标栏 + 浮出面板（世界页同构） | 原罪 3/4 | 中（拍板项 P-2） |
| R-04 | InspectorPanel 去 tab 栏 → 单分区面板壳 + 面板头 | 原罪 3 | 低（内容零改动） |
| R-05 | 提醒轨 → 纸左页边批注（横向几何迁移） | 原罪 2（提醒贴近它注的行） | 低（算法/内容/交互全继承） |
| R-06 | 点火卡浮卡 → 纸内页首块 | 原罪 5 | 低（门控零改动） |
| R-07 | 纸面 `--paper-bg` token 化 + 静态 parchment 类清除 | 原罪 5（深色 P0） | 低 |
| R-08 | 打字淡出对象：顶栏 → 两条缘签 | 随 R-02 | 低 |
| R-09 | Ctrl+\ 语义映射面板开/pin/收；hover  drawerHover 状态删除 | 随 R-03 | 低 |
| R-10 | splitSizes 持久化停止读写（旧键留尸不迁移） | 随 R-01 | 低 |

---

## 5. 施工落点文件清单（主 agent 照单施工）

| # | 文件 | 动作 |
|---|---|---|
| 1 | `frontend/src/features/workspace/containers/WorkspaceView.vue` | **大手术**。删：Splitpanes/Pane import 与模板、`.binder` 全家模板与 scoped 样式（:781-876 模板 / :1084-1380 样式）、`.nle-topbar` 块（:883-918）与 `.nle-topbar__btn` 样式（:1464-1488）、`.empty-editor` 块（:970-978）、`.drawer-edge` 块（:1007-1020）、`onResize`/`splitSizes`（:396-414）、`drawerHover`（R-03）。增：`<ChapterSpine>` + `<ChapterTocDrawer>` + `<AssistRail>` + `<TocPage>` 挂载；`assistPanelOpen/assistPinned/activeTab` 状态与 Ctrl+\ 改造（`_drawerKeyHandler` 重写为开/pin/收三态）；`reportDot` ref；`aiStateLabel` computed 由 nleStateLabel 改名平移（:483-500 逻辑零改动）并下传；IgnitionCard 改经 slot 传入 ChapterEditor（见 #6/#7）；`workspace-view--typing` 根类；InspectorPanel 换 `v-model:active-tab` + `@activate` 监听。保留平移：drawerPinned 持久化（键名 uiPrefs.rightDrawerOpen 不变）、`_drawerAutoOpened`（改以「检查」开面板）、`_onOpenInboxDrawer`（改以「此刻」开面板）、isTyping 计时器、CursorLayer/PerceptionBand/BeatCardDock/ThinkingIndicator/WorldContextCard/QuickEventNote/ShortcutsCheatsheet 挂载、多选删除与导入/提取模态状态（移交 ChapterTocDrawer 经 props/emit 或保留容器持有——容器持有，抽屉纯受控） |
| 2 | `frontend/src/features/workspace/presentation/ChapterSpine.vue` | **新增**（§4.2，~70 行；props：chapterLabel；emit：open） |
| 3 | `frontend/src/features/workspace/presentation/ChapterTocDrawer.vue` | **新增**（§4.3，~200 行壳；行渲染消费 #4；受控组件：visible/active 状态全在容器） |
| 4 | `frontend/src/features/workspace/presentation/ChapterTocList.vue` | **新增**共享行组件（§4.3；props：chapters/selectedChapterId/selectMode/checkedIds/variant:'page'\|'drawer'；emits：select/toggleCheck/delete/toggleSelectAll；ChapterBadges 复用零改动） |
| 5 | `frontend/src/features/workspace/presentation/TocPage.vue` | **新增**（§4.4，~130 行；props：bookTitle/chapters/loading；emits：select/create/import） |
| 6 | `frontend/src/features/workspace/presentation/AssistRail.vue` | **新增**（§4.5，~110 行；props：assistEnabled/activeTab/reportUnread；emits：toggleAssist/selectTab/openCheatsheet） |
| 7 | `frontend/src/features/workspace/containers/InspectorPanel.vue` | 删 tab 栏模板（:460-480 一带）与底部 AI 视角钮（:897-902）及其样式；`activeTab` 改 `v-model:active-tab` prop；`handleKeydown`（:112-134）切 tab 处加 `emit('activate', key)`；加面板头行（分区名+固定钮+×，emit：pin/close）；**各分区内容组件与默认 tab 逻辑零改动** |
| 8 | `frontend/src/features/workspace/presentation/PerceptionBand.vue` | §4.7 几何迁移（根定位改为纸列对齐容器 + 圆点 left:14px + 覆态右开 + pointer-events 分层）；算法/卡结构/交互/色族零 diff |
| 9 | `frontend/src/features/chapter-editor/presentation/ChapterEditorView.vue` | `.paper` 去静态类（:102）+ 发布浮层 token 化（:105）；meta 行加 AI 状态件（:124-129 区间，新 props `aiStateLabel?: string` / `aiStateError?: boolean`）；加 `<slot name="page-top" />`（:167 后） |
| 10 | `frontend/src/components/ChapterEditor.vue`、`frontend/src/features/chapter-editor/containers/ChapterEditorContainer.vue` | `aiStateLabel/aiStateError` 透传（各 ≤4 行，wordCount 先例）；ChapterEditorContainer 模板把 IgnitionCard 槽位内容自 WorkspaceView 链路透传（或直接由 WorkspaceView 经 ChapterEditor 的具名 slot 透传——取既有多层 slot 透传惯例，施工时按 ChapterEditor 现有 slot 结构二选一，设计约束 = IgnitionCard 的最终渲染位在 page-top slot 内） |
| 11 | `frontend/src/features/generation/presentation/IgnitionCard.vue` | 根样式 in-flow 化（:83-97 重写；去浮卡 chrome，标题衬线化）；模板/事件/门控零改动 |
| 12 | `frontend/src/components/RichTextEditor.vue` | :945 根删 `bg-parchment-50` |
| 13 | `frontend/src/style.css` | 增 `--paper-bg` 双主题（:root 与 :root.dark 各一行）；增 `.desk-spine`/`.toc-drawer`/`.assist-rail`/`.toc-page` 样式段（消费 token；z 只允许 40/85）；删 `.drawer-edge`/`.drawer-edge__handle` 段（:764-820）；`.inspector-drawer` 段保留原样（助手面板消费） |
| 14 | `frontend/src/features/generation/presentation/ShortcutsCheatsheet.vue` | 两条键位描述更新（§6 表 N11） |
| 15 | `frontend/src/composables/useUiPrefs.ts` | 只读检查：rightDrawerOpen 键保留复用；splitSizes 停止读写（WorkspaceView 侧删除即可，本文件零改动） |

**预算：新增 token 1 个（--paper-bg）；新 z 值 0；新依赖 0；新组件 5 件（全 presentation 受控件）；净删除模板行数 ≫ 净新增。**

---

## 6. 文案表

**07 期 §6 表 A-S 全量继承**（其文案逐条仍为唯一权威）。以下仅列载体重定位与新增面：

### 表 N · 本期新增/重定位

| # | 位置 | 文案 | 来源 |
|---|---|---|---|
| N1 | 目录页书名行 | `{书名}` + 副行「目录」 | 新增 |
| N2 | 目录页末行 | ＋ 新起一章 | 新增 |
| N3 | 目录页零章态 | 这本书还没有章节 · 钮「新起第一章」 | 新增 |
| N4 | 目录页纸底 | 从 .md 文件批量导入章节 | 新增（07 A 表「导入 .md」语义） |
| N5 | 书脊签 title | 章节列表 | 新增 |
| N6 | 目录抽屉底部三钮 | 新建章节 / 导入 .md / 提取设定 | 继承现 binder（07 已改「提取设定」） |
| N7 | 助手栏 title 群 | ✨=07 表 A3/A4 原文；打算（Ctrl+1）/ 此刻（Ctrl+2）/ 本章（Ctrl+3）/ 检查（Ctrl+4）/ AI 视角（Ctrl+5）/ 快捷键一览 | 继承 07 A3/A4/A5 + InspectorPanel 既有 tab 名 |
| N8 | 面板头 pin 钮 | 图标钮（Icon `pin`）· title「固定面板（Ctrl+\）」；pin 态高亮 + title「取消固定」 | 新增（「钉住」是 07 禁用词，title 用「固定」） |
| N9 | meta 行 AI 状态件 | AI 正在看你写的 / 走向卡备好了 · Ctrl+Space / 正在往下写… / 正在整理新设定… / 正在通读全章… / 润色中… / 正在检查全文… / 生成失败 | 07 表 A1/A2 原文，载体顶栏丸 → meta 行 |
| N10 | 07 表 S6（选一章，开始写 / 左边选一章，或者新建一章） | **退役**（空态被目录页取代，N1-N4 接替） | — |
| N11 | 速查表两条 | Ctrl+\：「固定 / 收起助手面板」；Ctrl+1~4：「打开助手面板：打算 / 此刻 / 本章 / 检查」（其余行 07 表 R 原样） | 07 表 R 局部修订 |
| N12 | 点火卡页内版 | 本章还是白纸 / 这一章主要讲什么？… / 收下建议 / 不用 / ⚡ 写个开头 / 我自己写 / 生成的是幽灵草稿… / 先在右侧「打算」页… | 07 表 E 全量原文（「右侧」二字在栏式布局下依然成立） |
| N13 | 页边批注 | 全部 | 07 表 C 全量原文（覆态空态引导句/dismiss title/kind 标签，一字不动） |
| N14 | 幽灵三条/卡舱/选区/发布/速记/检查 | 全部 | 07 表 D/F/O/P/Q/J/K/L/M/S 原样 |

**文字预算**：首屏文字簇——目录页 = 书名 + 目录行 + 2 行入口（纸面本体，不算 chrome）；章页 = meta 一行 + 标题 + 正文（+ 空章点火块）。chrome 文字总量较 07 态净减（顶栏三件套、抽屉把手 title、空态三行全部消失；新增仅缘签两处 title 与面板头一行）。

---

## 7. 验收清单

> G = grep/脚本；M = 目检；I = 交互手测。证据本地留存不入库。四视口 = 1280 / 1200（Electron 最小）/ 1093（1366@125% DPI）/ 1280+面板 pin。

### I 类（渲染/静态）

- **I-01【G】** 黑话清零沿用 07 I-01 词表，追加 `副驾` 在 `features/workspace/` 零命中（注释与 `__tests__` 白名单）。
- **I-02【G】** `grep -n "Splitpanes\|splitpanes\|nle-topbar\|drawer-edge\|status-bar\|empty-editor\|binder-pane\|\.binder\b" frontend/src/features/workspace/containers/WorkspaceView.vue frontend/src/style.css` 零命中（style.css 注释豁免）；新组件类名一律 `desk-spine/toc-*/assist-rail`，禁复用 `binder-*`。
- **I-03【G】** 冻结 diff 零：`computeCursorDockPos` 函数体；`stackAnchoredTops` 与 `usePerceptionAlignment` 函数体；canon-mark/ghost-draft/outline-note 类名串；七键 keymap 段；SSE GHOST_* 消费字段；`dismiss-hint` 载荷；dock 四槽位排序与 `_finalize_parts`；心跳三计时器常量；`reapGhostIfDead` 与蒸发理由 toast；`stripGhostDraftHtml` 消费链。
- **I-04【G】** token 纪律：新/改样式段新增 token 仅 `--paper-bg`；z 值只允许消费 40/50/60/85/120 既有档；无新裸 hex（薄荷 #34d399 品牌值与 .inspector-drawer 投影复用豁免）；无新裸 font-size。
- **I-05【M】** 四视口几何：纸列 880 居中；开目录抽屉 / 开助手面板 / 开批注覆态 / 卡舱弹出全程**纸列零位移**（pin 唯一例外，推挤一次到位）；1093 下缘签与纸列不重叠（两侧沟 ≈78px > 签宽 44px）。
- **I-06【M】** 深色巡查（P0 验收主项）：纸面 `--paper-bg` 生效，正文/标题/placeholder/meta 行全可读；目录页/书脊签/目录抽屉/助手栏/助手面板/批注覆态/点火块/发布浮层/选区浮窗逐面巡；批注点五色可辨。
- **I-07【M】** 浅色对照：纸面与 07 态逐像素一致；缘签静息近乎隐形；目录抽屉/面板投影不糊纸边。
- **I-08【M】** `--editor-max-width` computed 恒 880px；editor-type-large 实验开关切换正常。
- **I-09【G/M】** 文字预算：§6 表 N 之外无上屏新文案；面板头一行 + 缘签 title 为全部新增；07 表 A-S 中退役项仅 N10 一条。

### II 类（交互）

- **II-01【I】** 第一眼验收（设计意图）：进写作台 → 目录页，非技术视角走查「第一眼看的是纸上目录」；点章 → 第一眼是纸面正文/空章问句。
- **II-02【I】** 章节动线：书签点击开目录抽屉 → 选章即收且章节正确切换；外点/Esc/再点书签三路径收；多选删除/全选/新建/导入/提取设定全回归；目录页「＋ 新起一章」与「从 .md 导入」可达。
- **II-03【I】** 助手栏：点击图标开对应面板；再点同图标收；Esc 收（且焦点在 SpinePanel 输入框内按 Esc 只退出内联编辑、不收面板）；外点收；面板间切换单格互斥。
- **II-04【I】** 键位：Ctrl+1~4 开对应面板、Ctrl+5 AI 视角（面板关时按键 = 开 + 定位）；Ctrl+\ 三态（关→开并 pin / 开→pin / pin→收）；pin 推挤一次到位无抖动。
- **II-05【I】** 主动推送回归：完稿报告到达 → 检查面板滑出一次（手动关过不反复）+ 检查图标朱点，看过即灭；沉淀 toast「去确认」→ 此刻面板滑出且收件箱就位。
- **II-06【I】** 七键契约全回归：Space（有/无零件）/Ctrl+Space/Tab/Esc 逐层（幽灵 > 卡舱 > 覆态 > 面板，逐层剥皮顺序实测）/Alt+N/Alt+O/Ctrl+Enter；细纲胶囊扩写全流程。
- **II-07【I】** 写作闭环动线：目录页选章 → 空章点火块写一句（或我自己写）→ 写中批注点守行 → 停顿卡舱光标旁 → Space/Tab 用卡 → 幽灵三条贴幽灵尾 → Ctrl+Enter 沉淀 → toast 直达 → 此刻面板裁决 → 完稿体检 → 检查面板报告 → 残句修复/润色/读者反馈。全程无死路、无遮挡、无双重入口。
- **II-08【I】** 页边批注全周期：心跳出提醒 → 点守行高随滚动 → hover 120ms 覆态右开 → 移出收 → 点击钉住 → Esc 收且焦点回编辑器；安全类朱点无 ×；普通类 × 多收几次少提（静音链回归）；轨底 +N 与 ⚑ 打算行正确。
- **II-09【I】** 光标层回归（07 II-04/05/06 原项）：停顿弹舱位置/翻转/夹紧/数字键/sticky/互斥/幽灵三条/退格收割 reapGhostIfDead。
- **II-10【I】** 打字沉浸：打字 1.2s 内两缘签淡至 35%、hover 即复原；meta 行不淡；断网下「保存失败（已存本地草稿）」红字全程可见。
- **II-11【I】** 极端态：零章节书（目录页零态）/ 无世界数据书（主链路零报错）/ 5000+ 字长章且提醒 >10（批注点分布、+N、覆态兜底折叠）/ 1200px 最窄窗与 1093 DPI 复跑 II-02/03/08 无塌陷。
- **II-12【I】** 深色全写作闭环（II-07 复跑）+ reduced-motion 全表面瞬切。
- **II-13【I】** AI 辅助关：栏顶 ✨ 关态点灰、Space 普通空格、toast 原文（07 A9）；目录/面板等其余功能不受影响。

---

## 8. 冻结红线（本期任何条款不得触碰）

1. **后端零改动**。
2. **七键契约**：Space 续写 / Ctrl+Space 走向卡 / Tab 召唤卡舱 / Esc 逐层收 / Alt+N 世界速记 / Alt+O 细纲胶囊 / Ctrl+Enter 沉淀——键位、语义、状态机零改动。
3. **幽灵草稿机制**：Esc 蒸发 / Enter 采纳 / 退格收割 `reapGhostIfDead` / 蒸发理由 toast / GHOST_DONE 三条消费。
4. **心跳感知**：3s 活跃防抖 / 4s 停顿计时器；感知常驻 detach 语义；章节纪元守卫。
5. **细纲胶囊机制**（含存盘剥除链 `stripGhostDraftHtml`）。
6. **dock 四槽位语义与排序**（landing/toward_beat/echo/ambient）与 `_finalize_parts` 规整。
7. **SSE 帧与 GHOST_* 字段**（含 wash/repaired/deai 增量字段）。
8. **TipTap mark 类名**：canon-mark / ghost-draft / outline-note 家族。
9. 自冻结（07 继承）：`computeCursorDockPos()` 公式本体；感知锚定算法本体（`usePerceptionAlignment` / `stackAnchoredTops`，bandEl 指向适配除外）；静音学习链 dismiss-hint 载荷与 MUTEABLE_KINDS；SparkDock 可见性状态机；dock 零件缓存签名输入；`--editor-max-width: 880px` token 值；placeFloating / useFloatingLayer / useEscStack / ModalShell 接口签名；零新依赖。
10. **双主题一等公民**：任何新表面浅色深色同步交付，深色不是事后巡查项而是设计输入。
11. InspectorPanel 五分区内容组件（SpinePanel/WorldSceneSlice/本章/检查/AI 视角）内部逻辑与文案——本期只换壳。
12. AppRail 全局栏——非写作台私物，不动。

---

## 9. 考虑过并否决（防施工走样）

1. **binder 常驻保留、只做视觉瘦身（07 路线加强版）——否决。** 07 已实证：binder 不动 = 用户判定「没做」；且常驻列表就是第一眼杀手（§1.2-1）。瘦身治不了「占着最好位置放最低频信息」的结构病。
2. **章节改顶部横排 tab 栏——否决。** 长篇小说 50+ 章横排不可扩展（滚动 tab 栏是更差的形态）；顶部横条属于 04/05/06 翻车的「上下夹纸」家族。
3. **进写作台自动打开最近章节、取消目录页——否决。** 替作者做决定违反「作者主权」基调；且目录页是「看得见的重构」的签名面与章节系统的天然教学场（作者在目录页亲眼看到章节列表住在纸上，写中发现左缘书签时不需解释）。
4. **右抽屉 hover 瞥看保留——否决。** 鼠标停靠右缘误开是既有恼点；世界页点击制已被接受，全 app 统一为点击制（拍板项 P-2）。
5. **书脊签与助手栏合并到同一侧——否决。** 左书右 AI 的分工就是心智地图本体（§2 三句话）；同侧混居破坏对称，且右侧栏会遮住批注覆态的右开空间。
6. **目录抽屉加 pin 模式——否决。** 切章是秒级任务，pin 无使用场景；每多一个持久态就多一倍边界 bug。
7. **页边批注改纸的右页边——否决。** 右缘已是助手栏领地；左侧页边是中文书批点/句读的传统位置，且圆点在行首左侧天然先于阅读顺序被看到。
8. **点火卡保留浮卡、只改视觉——否决。** 浮卡压纸 = 纸面不是主角（§1.2-5）；空章页首块让「纸自己在问」，同时回答第一眼落点。
9. **纸面加书眉/页码/装饰线——否决。** 装饰性 chrome 违反文字与元素预算；纸面的表情由排版（衬线标题+页边）承担，不靠花边。
10. **顶栏保留只放状态丸——否决。** 一条横栏为一颗丸服务是面积超配；状态上纸（meta 行）比悬在框上更贴近它描述的对象。
11. **--editor-max-width 借重构改宽——否决。** 880 是排版三 token 与 editor-type-large 实验的既有契约，本期无证据支持变动；重构的「看得见」由格局承担，不靠改字号栏宽。

---

## 10. 需用户拍板（硬拍板项 2 条）

- **P-1 · 章节列表去常驻化（全稿最大骨架赌注）**：binder 左栏彻底取消 → 无选中章时纸面 = 目录页；写中切章 = 点左缘书签 → 目录抽屉（选章即收）。**代价**：写中切章从「侧栏常驻点行」变为「点签 → 点行」两步；05 期书脊曾被烧过一次（但那次是加 chrome 不减 binder，这次是 binder 本体的净减法转世）。**若否决**：回退方案 = binder 保留但收成 48px 数字轨（只显示章序号竖列，点击章号直接切，hover 出抽屉）——此方案第一眼改善减半，不推荐。
- **P-2 · 右缘改点击制**：hover 瞥看退役 → 图标点击开 / Esc·外点收（与世界页一致）；Ctrl+\ pin 保留。**代价**：改掉「悬停即看」的既有肌肉记忆。**若否决**：栏图标加 hover 300ms 预览（单击开、悬停预），但世界页与写作台手势从此不一致。

其余均为自决项（顶栏删除与状态上纸 / 点火卡入纸 / 批注点进纸页边 / 目录页签名面），由 §7 验收清单兜底。

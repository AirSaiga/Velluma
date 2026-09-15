# 06 · Chrome 语言整体重做设计稿（「纸上的仪器」）

> 2026-09-15 调研定稿。触发：用户实机反馈「完全看不到有什么明显改变」（P3 黑盒实测证实：默认暖纸浅色写作台上 P0-P2 的可感知变化趋近于零）。
> 输入：P0-P2 施工事实（token/elev/chroma/Toast/SegmentedPill/抽屉 v2）+ P3 十格实测结论 + 05 文档方向二（「仪器」降级项）。
> 本文档 = 只出稿不施工。所有红线沿用 05 §7.7/§8/§9 铁律并新增本章声明。

---

## 0. 现状定性（P3 实测的一手结论）

| 面 | 现状 | 实测观感 |
|---|---|---|
| 浅档写作台（默认视图） | 纸面冻结是对的，但 chrome 也没拿出新东西：AppRail 变化=灰实底→淡 tint pill；按钮/输入框/chip 全是 P0 之前的旧皮肤 | **肉眼无差**——用户反馈属实 |
| 外观抽屉 v2 | 半切预览卡/对勾 chip/SegmentedPill/缩略卡 | **一眼可见的大变化**——证明团队做得出「明显感」，缺口在排期不在能力 |
| 暗档五主题 | 五级阶梯+chroma 影+内高光 | 显著，但用户默认停在浅档 |
| 模态/Toast | blur/elev-3/语义条 | 显著，但出现频率低 |
| 遗留债（本稿顺手登记） | `color: white` 字面量 27 处（P2 只清了 `#fff`）；chrome 裸 px 字号 37 处；`.cs-type` 徽标对比 ≈2:1 | N1 一并收编 |

**结论**：克制路线在浅档付出了「无感」的代价。本稿把「仪器感」全面引入 chrome——**密度更高、字排更精密、层次更明确**——同时纸面与豁免面一寸不让。

---

## 1. 设计原则

**一句话纲领：纸上的仪器——chrome 是置于纸侧的精密仪器架，纸面永远安静。**

1. **纸面神圣**：chrome 的一切装饰/密度/动效不得越过纸列边界；编辑器、正文、古地图、书封、ghost-draft 零触碰（永久红线，任何期次不得提案改动）。
2. **密度即质感**：chrome 控件从「宽松留白」转向「紧凑有格」——控件行高阶 28/32/36、菜单项高 28、chip 高 24；留白从「气氛」改为「对齐」。
3. **层次三件套**：浅档层次只允许来自 ①线阶（--line-faint/--line/--line-strong）②表面阶梯（sunken 凹槽 / float 浮起）③hairline 高光与主题影——**禁止新增大块实底色块**（签名色/语义色实底按钮除外，那是信号不是层次）。
4. **仪器字排**：chrome UI 以 12/13px 为主档、tracking 0.02-0.06em 分档、数字一律 tabular-nums；字重只有 400/500/600 三档分工（400 正文/500 标签与按钮/600 强调与选中）。不引 webfont（01 §0-6 裁决不改）。
5. **动效为功能**：交互反馈 ≤240ms（dur-1/2）、浮层出入 dur-2/3；spring 只驱 ≤12px 位移；motion-low 一键归零（既有毯式规则不动）。

**仪器感 ↔ 文房感分工表**：

| 维度 | chrome（向仪器靠拢） | 纸面（向文房坚守） |
|---|---|---|
| 密度 | 高：28-36px 行高阶、4px 基栅对齐 | 不变：880 纸列、1.8-2.0 行高 |
| 层次 | sunken 凹槽+hairline+elev | 纸边/纸影/纸纹（既有语言） |
| 字排 | 12/13px、tabular-nums、eyebrow | 衬线标题、正文排版 token |
| 阴影 | 主题 chroma 影（P1 已立） | --shadow-paper 恒纸感 |
| 抽屉 | **保留纸叠影**（文房锚点，见评审点 2） | — |

---

## 2. Token 增量设计（在 P0-P2 架构上扩，不另起炉灶）

所有新 token 只在 `:root` 声明一次，浅/深行为由底层 token 自动解析；新增值全部走 color-mix 或直接 alias，**零新硬编码透明度**。

### 2.1 控件几何（新段，插在 P0 几何 token 后）

```css
/* ---- Chrome 控件几何（06 §2.1：仪器密度阶；任何控件取其一） ---- */
--control-h-sm: 1.75rem;   /* 28 chip/小钮 */
--control-h-md: 2rem;      /* 32 按钮/输入/分段 默认档 */
--control-h-lg: 2.25rem;   /* 36 模态主钮/工具行 */
--control-px: 0.625rem;    /* 10px 横向内衬（按钮/输入统一） */
--menu-item-h: 1.75rem;    /* 28 菜单项 */
--chrome-gap: 0.25rem;     /* 控件组内间距（取代散写 6/8px） */
```

### 2.2 字排与图标（新段）

```css
/* ---- Chrome 字排/图标阶（06 §2.2） ---- */
--tracking-label: 0.02em;    /* 按钮/标签 */
--tracking-eyebrow: 0.06em;  /* 分区眉标/小写大写化标签（letter-spacing） */
--icon-sm: 0.875rem;         /* 14 紧凑图标（chip 内/菜单） */
--icon-md: 1rem;             /* 16 chrome 默认图标 */
```

- chrome UI 字号**不新设字阶**：消费现有 --text-xs(12)/--text-sm(13)/--text-base(14)；37 处裸 px 在 N1 全部归位到这三档。
- 数字对齐：`.num-serif` 升格改名 `.tnum`（utility：font-variant-numeric: tabular-nums + 继承字体），推广面见 §5.3。

### 2.3 表面/线阶/状态增量（浅档主战场）

```css
/* ---- 浅档 chrome 层次（06 §2.3；深色档自动成立） ---- */
--well-bg: var(--surface-sunken);                                 /* 凹槽底：输入框/分段轨道 */
--well-inset: inset 0 1px 0 color-mix(in srgb, var(--text-primary) 6%, transparent);
                                                                  /* 凹槽内 hairline（浅档凹槽感的来源） */
--field-bg: var(--bg-canvas);                                     /* 输入框面（浅档取 canvas：凹槽由 border+well-inset 表达） */
--hover-line: color-mix(in srgb, var(--text-primary) 12%, transparent);
                                                                  /* hover 态描边加深档（替代底色块hover） */
--shadow-menu: var(--shadow-md);                                  /* 菜单/popover 统一 elev-2 档 */
```

行为说明（浅→深）：
- `--well-inset` 在浅档提供「仪器凹槽」的顶缘暗线；深档 text-primary 6% 变亮 hairline，同样成立，**一条规则两档通用**。
- `--hover-line`：浅档 hover 从「底色块」改为「描边+微底」（Linear 式），消除大面积色块闪烁；深档因底色深，hover 底保留 --state-hover，描边叠加。
- 抽屉壳**不换影**：inspector/toc 抽屉保留纸叠影（paper-edge 错位边）——这是全产品仅存的文房 chrome 锚点（评审点 2）。

### 2.4 现有 token 不动清单

surface 五档/line 三档/state 三档（hover=别名、active 8%、selected 15%）/elev 四档/motion 十二枚/dur 终值——**全部冻结**，本稿只消费不修改（selected 15% 是 P2 刚调的可见性下限，不回退 12%）。

---

## 3. 控件族规范（核心章节·照此可施工）

统一约定：色态全部 token；圆角按钮/输入/菜单项取 `--radius-sm(6px)`、卡片取 `--radius-md(8px)`、浮层壳取 `--radius-md`；disabled=opacity 0.5 + cursor default（不动配色）；focus 沿用全局 `:focus-visible` 环（02 既有）；动效交互态一律 `var(--dur-1) var(--ease-out)`（hover/active），语义态切换 `var(--dur-2)`。

### 3.1 按钮

| 规格 | primary | ghost（默认钮） | danger |
|---|---|---|---|
| 结构 | label（≤14px 字）± icon-sm；h-md（模态主钮可 h-lg） | 同左 | 同左 |
| 尺寸 | h-md 32 / px 10 / 字号 --text-sm / 字重 500 / tracking-label | 同左 | 同左 |
| radius | --radius-sm | 同左 | 同左 |
| default | bg `--accent-500`、文字 `var(--bg-canvas)`（C6 范式）、border 1px `--accent-500` | bg transparent、文字 `--text-secondary`、border 1px `--line` | bg transparent、文字 `--danger`、border 1px `--line` |
| hover | bg `--accent-600`、box-shadow `var(--glow-accent)` | 文字→`--text-primary`、border→`--hover-line`、bg `--state-hover` | 文字/边框→`--danger`100%、bg `color-mix(in srgb, var(--danger) 8%, transparent)` |
| active | transform scale(.98) + `--state-active` 底叠加 | bg `--state-active` | bg `color-mix(in srgb, var(--danger) 14%, transparent)` |
| selected | 不适用（按钮无选中） | 同左 | 同左 |
| disabled | opacity .5 | 同左 | 同左 |
| 动效 | all var(--dur-1) var(--ease-out)；hover 阴影 dur-2 | 同左 | 同左 |

施工面：现散写 `.btn--primary/.btn/.preset-btn/.pm-done/...` 全族（>20 文件）在 N1 收编为 **两个工具类 `.btn-primary-instrument` / `.btn-ghost`**（style.css chrome 层），组件 class 逐步换挂；hover 态里残留的 `color: white` 27 处随收编一并 C6 化（→`var(--bg-canvas)`）。

### 3.2 chip（过滤/标签/状态）

| 项 | 规格 |
|---|---|
| 结构 | label 12px ± 前置 dot(6px，语义色) / × 图标-sm |
| 尺寸 | h-sm 28（当前 24-26 不统一，归 28 一档）；px 10；radius pill |
| default | bg `--surface-raised`、border 1px `--line`、文字 `--text-secondary` |
| hover | border `--hover-line`、文字 `--text-primary`、bg `--state-hover` |
| active（选中过滤） | bg `--state-selected`、border `color-mix(in srgb, var(--accent-500) 35%, transparent)`、文字 `--accent-500`、字重 600 |
| active+hover | bg `color-mix(in srgb, var(--accent-500) 20%, transparent)` |
| disabled | opacity .5 |
| 动效 | color/border/background dur-1 |

施工面：`.cs-chip/.fs-chip/.spine-chip/.spark-dock__chip/.qen-chip` 等（现状：bg-secondary+border-color+无 hover 描边档）统一换 `.chip` 工具类 + 修饰类。

### 3.3 输入框 / textarea

| 项 | 规格 |
|---|---|
| 结构 | label(eyebrow 12px/500/muted，上置 4px 间距) + field；hint 行 12px faint |
| 尺寸 | input h-md 32 / px 10 / 字号 --text-sm；textarea 最小高 4 行，同 padding |
| default | bg `--field-bg`、border 1px `--line`、box-shadow `var(--well-inset)`（凹槽）、文字 `--text-primary`、radius-sm |
| hover | border `--hover-line` |
| focus | border `--accent-500` + `var(--ring-soft)`；**凹槽 inset 保留**（仪器聚焦=凹槽+光环） |
| filled（有值） | 不变（不另设色） |
| error | border `--danger` + `color-mix(in srgb, var(--danger) 8%, transparent)` 底；hint 改 `--danger` |
| disabled | opacity .5 |
| 动效 | border/box-shadow dur-1 |

施工面：`input/textarea/select` 的散写皮肤（ApiSettingsModal `.field-input` 7px10px/13px/bg-primary、qen 系列、WorldviewPanel `.item-title-input` 等 >15 处）统一 `.field` 工具类；**select 同规范**（原生 select 保功能只换肤）。

### 3.4 分段控件（SegmentedPill 演进，不重写）

P1 已立范式即本稿标准，N1 只补三点：① 高归 `--control-h-md`（轨道 padding 3px 不变）；② 加 `size` 无关的**键盘导航**（←→ 切换，roving tabindex——可访问性补齐）；③ 推广面：文风页意图区/数据页粒度切换等散写 tab-btn 全部换挂。色态不动（轨道 sunken/thumb float+elev-1/选中 600）。

### 3.5 菜单 / 右键菜单 / 动作菜单

| 项 | 规格 |
|---|---|
| 结构 | 浮层壳（elev-2 + radius-md + padding 4px）+ item(h-28 px 8 radius-sm) + 分隔线（1px `--line-faint` margin 4px 0）+ 尾部 kbd hint（12px faint，右对齐，ml auto） |
| item default | 文字 --text-sm 400 `--text-primary`；图标 icon-sm muted |
| item hover | bg `--state-hover`；图标→`--text-primary` |
| item danger | 文字 `--danger`，hover bg `color-mix(in srgb, var(--danger) 8%, transparent)` |
| item disabled | opacity .45 |
| 选中 check 位 | item 前置 16px 占位，选中 `--accent-500` ✓（svg，bg-canvas 不适用——细线图标用 accent 实色） |
| 动效 | 壳入场：opacity 0→1 + translateY(-4px→0) dur-2 ease-out（--ease-out）；item hover dur-1 |

施工面：`action-menu`（ChapterEditorView 376 行现状 7px10px）、mention-popup、edd-fieldmenu（已 elev-2，补 item 归一）、`.qen-*` 下拉。世界页右键菜单在 N2 随浮层族。

### 3.6 tab / 分区头（eyebrow 体系）

| 项 | 规格 |
|---|---|
| chrome 分区头 | eyebrow：12px / 600 / `--tracking-eyebrow` / `--text-muted` / 全大写化（CSS `text-transform: uppercase` 由内容决定，中文不生效即保持原字）+ 下接 hairline（`--line-faint`）；**替代**现 12px/600/muted 无分隔的 `.ap-section-title` 散写 |
| 页级分区头 | ❦+衬线（04 期 §B1 语言）**保留不动**——文房仪式感只留在页级 |
| tab（同页切换，如文风页「你的字/笔迹指纹」、数据页面板 tab） | h-32 / item px 12 / 选中=文字 `--text-primary` 600 + 2px `--accent-500` 下划条（`--line-strong` 基线之上）；未选 `--text-secondary`；hover 文字主色 |
| 动效 | 下划条滑动 transform dur-2 ease-out |

施工面：`.ap-section-title` 全量（AppearancePanel/设置弹窗）、`.panel-tab`（InsightsView 739）、StyleView 分区头。

### 3.7 卡片（card-std 族）

| 项 | 规格 |
|---|---|
| card-std | padding 12px（现 16，收紧一档）/ radius-lg→**--radius-md** / elev-1 不变 / hover（可点卡）叠 `.card-hover`（现有） |
| card-compact | 不动（无影紧凑档保留） |
| paper-card | **冻结**（纸面语义卡，文房语言） |
| 新增 `.card-well` | 凹槽卡：bg `--well-bg` + `var(--well-inset)` + 无 border，用于「嵌入仪表格」（指纹指标格/用量格） |
| 动效 | hover 抬升 2px + elev-2（现有 card-hover 改造：去 translateY，改 shadow 档提升——位移 hover 在仪器语言里过于活泼，**评审点 4**） |

### 3.8 抽屉 / 面板壳

| 壳 | 现状 → 目标 |
|---|---|
| inspector/toc 抽屉 | **保留纸叠影**（paper-edge 错位+shadow-lg）+ 头改 eyebrow 分区规范 + 头部底 hairline；N3 密度化 |
| 世界页详情抽屉（atlas-drawer 内） | 豁免面外缘不动；**内部** DrawerShell 头/搜索栏/计数 chip 走本稿控件族（N3） |
| 助手面板（assistant-panel） | 同 inspector 规范 |
| AppearancePanel | 已是 v2 范式：N1 把 `.ap-section-title` 换 eyebrow、按钮/控件皮肤换挂 |

### 3.9 AppRail

| 项 | 现状 → 目标 |
|---|---|
| 宽 | 56px **冻结**（IA 不动） |
| item | 高 44→**40**（padding 8px 4px→6px 4px）；icon 20→**18**（--icon-md 16 太小，rail 取 18 特例）；label 12px(--text-xs) 500 |
| default | 文字/图标 `--text-muted` |
| hover | bg `--state-hover`、文字 `--text-primary` |
| active | bg `--state-selected`、文字+图标 `--accent-500`、radius-md（现值）+ 左缘 2px accent tick（现 ::before 条保留） |
| 底部工具簇 | 与导航项同规范；分隔线 hairline |
| 动效 | 现 dur-2 保留；active 态切换时 pill 背景 dur-2 |

---

## 4. 分区改造要点（现在 → 目标 → 文件）

| 分区 | 现在 | 改成 | 主要文件 |
|---|---|---|---|
| AppRail | 20px 图标/52px 项高/灰实底 hover | §3.9 仪器密度 | `features/app/containers/AppRail.vue` |
| 写作台页头 | meta 行+衬线标题+⋯菜单（菜单项 7px10px 散写） | ⋯菜单接 §3.5；页头 meta 行 12px+tnum；⋯钮 hover 接 chip 规范 | `ChapterEditorView.vue`、`page-head` 样式段 |
| 助手栏/右缘栏 | 44px 图标栏 elev 面 | 图标 16px（--icon-md）、hover 描边化、激活点保留 mint | `AssistRail`（WorkspaceView 内） |
| 副驾抽屉/目录抽屉 | 纸叠影（保留）+ 头部分区散写 | 头改 eyebrow+hairline、内部控件族换挂、N3 密度 | `InspectorPanel.vue`、`ChapterTocDrawer.vue`、`.assistant-panel` 段（style.css） |
| 世界页 chrome | 图标栏/抽屉/表单散写皮肤 | 控件族换挂；**画布与古地图零触碰** | `DrawerShell.vue`、各 DetailDrawer、QuickCapturePanel、世界页表单族 |
| 书架 | 书封卡（豁免面）+新建卡 | 书封冻结；卡壳外 chrome（新建表单/按钮/输入）换挂 | `LibraryView.vue`（非书封部分） |
| 文风页 | 两栏仪表盘、分区头散写 | eyebrow 化、样本卡→card-std 新档、tab 接 §3.6 | `StyleView.vue` + presentation 组件 |
| 数据页 | 面板 tab 散写、用量格平色 | tab 接 §3.6、指标格→`.card-well`、数字 tnum | `InsightsView.vue`、PriceSettingsModal |
| 大纲板 | 章卡/规划列散写 | 章卡→card-std、控件换挂 | `OutlineView.vue`、`ChapterCard.vue`、StorylineAxis |
| 模态族 | ModalShell 已 v2（elev-3+blur10） | 内部按钮/输入/分段换挂；footer 顶 hairline | `ModalShell.vue` + 各模态表单 |
| 全局散写 | 27 处 `color: white`、37 处裸 px 字号 | N1 全量收编 | 全仓（codemod+手工复核） |

---

## 5. 字排与密度

### 5.1 字体栈

- chrome UI：**保持现有 --font-body**（Inter/苹方栈）——不引 webfont（01 §0-6 裁决）。「仪器感」靠字阶/字重/tracking/数字对齐，不靠换字体。
- 页级衬线标题/签名色：冻结。

### 5.2 字号阶（chrome 消费面归位表）

| 用途 | 现状散写 | 归位 |
|---|---|---|
| 按钮/输入/tab/菜单项 | 12/13px 混 | --text-sm 13 |
| chip/kbd hint/计数 | 11-12px | --text-xs 12 |
| eyebrow 分区眉标 | 12px 600 | --text-xs 600 + tracking-eyebrow |
| 正文/卡标题 | 13-14px | --text-sm/--text-base |
| 大数字展示 | 现有 num-serif | `.tnum`（升 utility，见 2.2） |

37 处裸 px 在 N1 用 codemod 归位（11px→--text-xs、12/13/14px→对应档），对拍测试补一项「chrome 无 <12px」。

### 5.3 数字对齐推广面

`.tnum` 挂：页头字数统计、章卡字数、文风指纹全部指标、数据页用量/价格、世界页计数 chip、Timeline 刻度（豁免面内Timeline 刻度是地图内容，**不动**）、Toast/胶囊计数。衬线大数字展示（指纹 hero 数）保留 heading 衬线 + tnum。

### 5.4 密度基准（现在的留白 vs 目标）

| 控件 | 现状 | 目标 |
|---|---|---|
| 按钮高 | 28-34 散写 | 32 一档（28 chip 档/36 模态档） |
| 输入高 | 30-36 散写（7px10px padding） | 32 = h-md + px10 |
| 菜单项 | 7px10px padding（≈30 实际行高不稳） | h-28 定高 |
| 卡 padding | 16 | 12（card-std） |
| 分区头间距 | 8px 下间距无分隔 | 8px + hairline + 12px 内容间距 |
| AppRail 项 | ≈52px | 40px |

---

## 6. 分期

| 期 | 内容 | 视觉幅度 | 风险 | 为什么排这里 |
|---|---|---|---|---|
| **N1 仪器底座**（必须一眼可见） | 控件族全量（§3.1-3.4 按钮/chip/输入/分段 + §3.6 eyebrow 分区头 + AppRail 密度）+ `color:white`/裸 px codemod | **高** | 中（控件多但模式统一，全走 4 个新工具类） | 用户已等了一轮无感批次；浅档 chrome 换脸是「一眼后现代」的最大单一杠杆 |
| N2 浮层族 | §3.5 菜单规范全量（action-menu/mention/fieldmenu/右键）、card-std 新档+`.card-well`、模态内部换挂、hover 抬升改影档（评审点 4） | 中 | 中低 | 浮层频率次于控件，但菜单是高频触面 |
| N3 分区深化 | 写作台/世界页/文风页/数据页/大纲板/抽屉内部密度+换挂收尾、`.tnum` 推广面、AppRail/助手栏微调 | 中低 | 低 | 精修面；风险最小放最后 |

**每期真机核验点**（截图对比 + 计算样式）：
- N1：浅档写作台「按钮+输入+chip+分区头」同屏截图 vs 本稿 §3 规格逐项对；`getComputedStyle` 抽 5 个控件的高度=32/28、border-color=var(--line) 解析值、hover 描边出现；`color:white` 残留=0；typecheck+vitest 绿。
- N2：⋯菜单/右键/mention 浮层截图（壳 radius-md+elev-2+item h-28）；卡片新 padding 对比；模态 footer hairline。
- N3：五主题×明暗十格全量截图走查（沿用 P3 矩阵法）；`.tnum` 元素 font-variant-numeric 计算值抽查；motion-low 双态各过一遍。

---

## 7. 明确不做

1. 纸面/编辑器零装饰（--paper-bg/--editor-*/.ProseMirror/.ghost-draft/纸列网格——永久红线）。
2. 豁免面四族零触碰（古地图画布/书封六色板/签名恒定色/预览卡 hex 集中前的散置值）。
3. 不做玻璃拟态面板/animated gradient mesh/视差（05 §5-2）；blur 只许在遮罩层与既有 dock/Toast 范式内。
4. 不引 webfont；不动 IA 与布局网格（56px rail/880px 纸列/抽屉宽全冻结）。
5. 签名色恒定不动；新透明度只走 color-mix；index.html↔useAppearance 对拍契约不碰；不 commit（沿用批次惯例）。
6. motion-low 一键归零能力不退化（任何新动效必须吃 token 时长才能被毯式规则压住）。

---

## 8. 验收标准（每期）

**N1**
- 截图：浅档写作台含「primary 钮+ghost 钮+chip+输入框+分段+一个分区头」的单屏对比图，与本稿 §3 规格逐项一致。
- 计算样式抽查 ≥8 点：控件高 32/28、border `--line` 解析、hover 描边 `--hover-line`、focus `ring-soft`、active scale、selected `--state-selected` 15%、eyebrow letter-spacing 0.06em、AppRail 项高 40。
- 债清零：`color: white`=0（豁免面外）、chrome 裸 px 字号=0。
- `npm run typecheck` 0 错；`npm test` 全绿（对拍测试增「chrome 无 <12px」一项）。

**N2**
- 菜单三实例截图（⋯/右键/mention）壳与 item 规格一致；浮层出入动效 dur-2 ease-out 录屏或连拍。
- card-std padding 12/radius-md 计算值；`.card-well` 凹槽 inset 存在。

**N3**
- 十格矩阵全量截图（P3 方法复用）；`.tnum` 抽查 6 处；motion-low 开/关各一轮五主题无破版。
- 全量回归：34 项 extensions 对拍 + contextBlockFormat + heartbeatSeam + timelineLayout 绿。

---

## 9. 用户评审点（需拍板的美学抉择）

1. **按钮角半径**：A. `--radius-sm(6px)`（Linear/Raycast 式锐利，推荐——与 hairline 语言最搭）｜B. `--radius-md(8px)`（现卡半径，更柔）。影响：全部按钮/输入/菜单项。
2. **抽屉语言**：A. **保留纸叠影**（文房锚点，推荐——chrome 全仪器后需要一处「书」的记忆点，且抽屉是低频大件）｜B. 换仪器浮层影（elev-2+chroma，与菜单统一但失去文房唯一 chrome 锚）。影响：inspector/toc/助手面板三壳。
3. **分区头体系**：A. chrome 分区全面 eyebrow 化（uppercase+tracking+hairline，推荐），❦ 衬线只留页级｜B. 维持现 12px/600 小标不加 hairline（更静但层次不足）。影响：全站分区头观感。
4. **可点卡 hover**：A. 去 translateY 抬升，改「阴影档提升+描边加深」（仪器式克制，推荐）｜B. 保留 2px 上浮（活泼但与本稿语言冲突）。影响：全部 card-hover。
5. **输入框形态**：A. flat+hairline+focus 环（最克制）｜B. sunken 凹槽+well-inset+focus 环（推荐——「仪器」的第一触觉，且不引 blur/玻璃）。影响：全部输入/下拉/分段轨道。

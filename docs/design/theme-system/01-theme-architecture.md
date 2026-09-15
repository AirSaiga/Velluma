# 主题系统架构设计稿（01 · 总纲）

> 输入：`00-visual-inventory.md`（四路盘点）。本文是所有开放问题的**拍板文档**与 token 施工图纸。
> 读者：施工 agent。纪律沿用 style.css:42-45——只允许消费 token；几何 token（字阶/间距/圆角/z 表）主题无关，本设计不动。

---

## 0. 裁决总表（盘点遗留开放问题，逐一拍板，无「待定」）

| # | 问题 | 裁决 | 一句话理由 |
|---|---|---|---|
| 1 | 多主题组织模型 | **主题 id 挂 `data-theme`，明暗继续挂 `.dark` class 的二维正交模型；`:root`/`:root.dark` 现状块 = 暖纸主题，逐字节不动** | 暖纸零回归；新主题=纯增量覆写块；Tailwind `darkMode:'class'` 零改动 |
| 2 | 每主题自带明暗还是明暗正交 | **正交**：五主题 × 浅/深 = 10 个覆写块，明暗由 mode（跟随系统/浅/深）独立控制 | 「明暗」与「性格」是两个意图，用户要的是夜里也能用二次元 |
| 3 | 两种紫（伏笔 #a855f7 vs accent #7c6aad） | **都保留，各司其职**：伏笔紫升格恒定签名色 `--foreshadow`；accent 是界面交互色随主题变 | 一艳一灰色距足够，语义本来不同（叙事线索 vs 界面交互）；合并会让时间轴伏笔弧失去辨识度 |
| 4 | 岔路朱 #c2725a 是否并入朱砂 | **并入**：朱砂收敛为两档 `--cinnabar`（印泥/文字级 #a63e2a）+ `--cinnabar-bright`（点状/高亮级 #c25a4a），岔路朱并入 bright 档 | 作者肉眼分不出三种朱的语义差别；深/亮两档是明度变体不是两种色——深色保文字对比、亮色保时间轴小点在鎏金旁可读 |
| 5 | 世界页古地图 | **豁免：「古地图永远是古地图」**，浅/深/任何主题下恒定羊皮纸；另立最小 `--atlas-*` token 集仅作未来挂点，本期不做逐行替换 | 古地图是产品招牌与「世界即古籍」隐喻本体，375 行 token 化成本极高、换肤收益为负；深色下保持亮图=「灯下看地图」，由无意幸运**正式追认为设计决定** |
| 6 | webfont 引不引 | **不引入任何打包字体**。字体性格差异改走「系统字体栈按主题重排」——`--font-heading`/`--font-body` 升格为可覆写 token | CJK 子集化后仍 2-5MB，Electron 打包与首载成本不值；Windows 必中 STSong/SimSun/雅黑/圆体系，栈重排零成本拿到 80% 性格差 |
| 7 | 自定义背景存哪 | **设备本地 localStorage**（`velluma:appearance:v1`），不进 books 表 | 防闪烁要求 index.html 内联脚本**同步**读取——localStorage 是唯一同步可读存储；外观重设成本 10 秒，可接受换 origin 漂移（时间轴视野是工作现场才值得入库，外观不是） |
| 8 | 背景按书还是全局 | **全局（设备级）**，本期不做按书主题 | 主题是「作者的写作环境」不是「书的装帧」；书封才是书的装帧（六色板豁免不变） |
| 9 | Tailwind 静态 palette | **config 映射 CSS 变量**（ink/parchment/accent 三族常用档 → var(--*)），`primary` 天蓝板验证零引用后删除；emerald/rose/amber/blue 外来语义类随各域重构清剿（见 02） | 87 行类名不用逐行改、值随主题；双轨并一轨 |
| 10 | 薄荷 AI 色 | **升格为跨主题恒定签名色 `--mint` 族**，不随主题变（只分浅/深档） | 「薄荷=AI 在场」是 Velluma 事实品牌，换主题不换品牌 |
| 11 | 数据页 verdict 第二套语义色 | **废除**，统一吃 `--ok/--warn/--danger` | 同一页两种绿是 bug 不是风格 |
| 12 | 阴影 token | **新增四件套 `--shadow-sm/md/lg/paper`**，每主题浅深给值；不强制替换存量 118 处，新组件必用、重灾区重构时顺手换 | 阴影语言按主题有性格差（极简硬、柔和软、二次元带粉调） |

---

## 1. 主题机制架构

### 1.1 选择器结构（style.css 落法）

```
:root                      /* = 暖纸 paper 浅色档（现状块，逐字节不动） */
:root.dark                 /* = 暖纸 paper 深色档（现状块，逐字节不动） */

/* 新增：签名恒定色段（§3），浅档挂 :root、深档挂 :root.dark，各新主题不覆写 */

/* 新增：四个主题 × 两档 = 8 个覆写块，每块只覆写颜色/阴影/字体栈 token */
[data-theme='minimal']            { ... }
[data-theme='minimal'].dark       { ... }
[data-theme='soft']               { ... }
[data-theme='soft'].dark          { ... }
[data-theme='pro']                { ... }
[data-theme='pro'].dark           { ... }
[data-theme='anime']              { ... }
[data-theme='anime'].dark         { ... }
```

- `data-theme='paper'` 时不存在对应覆写块——`:root` 就是 paper，**旧 localStorage 值、旧用户、未迁移路径全部零回归**。
- 几何 token 八档字阶/行高/间距/圆角/z 表/`--editor-*` 全部留在 `:root`，任何主题块不得覆写（二次元想要大圆角也不行——靠色彩与字重表达性格）。
- 每主题块覆写清单（缺一不可，缺了就是半成品皮肤）：
  背景七枚 `--bg-primary/secondary/tertiary/canvas/panel/paper-bg/bg-elevated`、
  文字四枚 `--text-primary/secondary/muted/faint`、
  边框/hover `--border-color/--hover-bg`、
  滚动条 `--scrollbar-thumb/--scrollbar-thumb-hover`、
  accent 三枚 `--accent-400/500/600`（`--accent`/`--focus-ring` 是 var 别名自动跟随，不用覆写）、
  语义八件 `--ok/--ok-bg/--warn/--warn-bg/--danger/--danger-bg/--info/--info-bg`、
  阴影四件 `--shadow-sm/md/lg/paper`、
  字体两枚 `--font-heading/--font-body`（允许与默认相同则省略）。

### 1.2 useAppearance（取代 useTheme 成为唯一挂装点）

新建 `frontend/src/composables/useAppearance.ts`，useTheme.ts 删除（全仓 grep `useTheme` 引用点迁移——盘点确认只有 AppShell 初始化处在用）。

```ts
// 状态模型
type ThemeId = 'paper' | 'minimal' | 'soft' | 'pro' | 'anime'
type Mode = 'system' | 'light' | 'dark'
type BgSpec =
  | { kind: 'theme' }                                  // 跟随主题 --bg-primary（默认）
  | { kind: 'color'; color: string; veil?: number }    // 自选纯色
  | { kind: 'image'; dataUrl: string; veil: number }   // 本地图片 + 遮罩 0~0.8
  | { kind: 'texture'; texture: 'grain' | 'weave'; veil?: number } // 内置纸纹
interface Appearance { theme: ThemeId; mode: Mode; bg: BgSpec; motionLow: boolean }
```

- 持久化：localStorage `velluma:appearance:v1`（JSON）。**迁移**：旧键 `velluma_theme='dark'` → `{theme:'paper', mode:'dark'}`，读取后写新键删旧键；`velluma:editor-typography` 键保持不变（排版档位继续独立）。
- `apply()` 做的事（顺序敏感，全部同步完成）：
  1. `documentElement.dataset.theme = theme`（paper 也显式写，语义明确）；
  2. 解析 mode：`system` 走 `matchMedia('(prefers-color-scheme: dark)')`，挂/摘 `.dark` class；mode 变化监听仅 system 档注册；
  3. 背景：`document.body.style` 上写 `--user-bg-image`/`--user-bg-color`/`--user-bg-veil` 三个自定义属性（不写 background 本体，背景合成在 style.css 里，见 §5.3）；
  4. `motionLow` → `documentElement.classList.toggle('motion-low')`。
- 与 AppShell 的关系：AppShell onMounted 调 `initAppearance()`；首帧由 index.html 内联脚本负责（§1.3），onMounted 只是二次对齐。

### 1.3 index.html 内联防闪烁脚本（照 main.ts:8-12 先例，前移进 head）

在 `<div id="app">` 之前、`<script type="module">` 之前插一段纯同步内联脚本（无依赖、try/catch 包裹、失败静默=paper 浅档）：

```
读 velluma:appearance:v1 → data-theme + .dark（system 档现场 matchMedia）+ body 背景自定义属性
兼容：无新键时读旧 velluma_theme
```

要点：这段脚本是**唯一防 FOUC 闸**（main.ts 执行时 CSS 已加载、首帧已排）。改 `velluma:appearance:v1` 的 schema 时必须同步改这段脚本——脚本与 useAppearance 共用一份「解析函数文字」，施工时在 index.html 注释里写明「逻辑与 useAppearance.ts parse() 对拍，改一边必须改另一边」。

### 1.4 背景合成层（style.css 新增段）

```
body { background: var(--bg-primary); }  /* 现状保留，主题底色恒在 */

/* 自定义背景层：body::before 全屏固定层，z-index -1 垫在所有内容下 */
body::before {
  content: ''; position: fixed; inset: 0; z-index: -1;
  background: var(--user-bg-color, none);
  background-image: var(--user-bg-image, none);
  background-size: cover; background-position: center;
}
/* 遮罩层：body::after 同结构，background: rgba 由 --user-bg-veil 驱动
   veil 默认值浅档 rgba(255,255,255,.55)/深档 rgba(0,0,0,.55)，滑杆覆盖 */
```

**纸面红线**：自定义背景只换「桌面层」（--bg-primary 所见区域：纸列之外、AppRail 底、世界页铬件底）。`--paper-bg` 永远吃主题值——背景换图时纸面不变，正文对比度不可被作者自己玩坏。

---

## 2. Velluma 签名（全主题恒定，跨主题不换的品牌件）

以下 token 只在 `:root` / `:root.dark` 各定义一次，四个新主题块**不得覆写**。它们与「纸面承载纪律、880 纸列、竖排书脊、章节仪式排印」共同构成跨主题成立的「小说感」。

| token | 浅档值 | 深档值 | 语义 |
|---|---|---|---|
| `--mint` | `#34d399` | 同左 | AI 在场/幽灵品牌色（呼吸点/脉冲环/assist 点亮） |
| `--mint-ink` | `#047857` | `#6ee7b7` | 薄荷文字级（chip 文字/计数） |
| `--mint-bg` | `#ecfdf5` | `rgba(20,46,38,.55)` | 薄荷面（chip 底/已修正 tag） |
| `--mint-line` | `#6ee7b7` | `rgba(110,231,183,.35)` | 薄荷线（chip 描边） |
| `--mint-soft` | `rgba(16,185,129,.15)` | 同左 | 幽灵草稿底色（ghost-draft--mint 现值平移） |
| `--cinnabar` | `#a63e2a` | `#c8553c` | 朱批/真相/印章·文字级（深档提亮保对比） |
| `--cinnabar-bright` | `#c25a4a` | `#e0684f` | 朱点/时间轴小点/岔路（岔路朱 #c2725a 并入此档） |
| `--foreshadow` | `#a855f7` | `#c084fc` | 伏笔弧/伏笔点（亮紫罗兰，与 accent 区分） |
| `--gold` | `#b08d3e` | 同左 | 鎏金：此刻/编年游标（世界页恒定） |
| `--gold-deep` | `#8a6d2f` | 同左 | 黄铜渐变深端 |
| `--gold-pale` | `#e6c87e` | 同左 | 黄铜渐变浅端 |
| `--gold-star` | `#c9a227` | 同左 | 核心角色金环星芒 |
| `--truth-secret` | `var(--cinnabar)` | `var(--cinnabar)` | 三态真相·秘密 |
| `--truth-partial` | `#7c5faf` | `#a98fd4` | 三态真相·半露 |
| `--truth-open` | `#5f7d5a` | `#86a383` | 三态真相·公开 |

世界页古地图豁免锚定集（§7 裁决，本期只定义不替换）：

| token | 值（浅深恒定） | 对应现值 |
|---|---|---|
| `--atlas-paper` | `#e7d7b6` | 羊皮画布底 |
| `--atlas-paper-2` | `#ecdfc3` | 羊皮高光层 |
| `--atlas-ink` | `#6e552d` | 暖墨线描（rgba(110,85,45) 实色化，alpha 由消费处自调） |
| `--atlas-river` | `#3f6f8f` | 在途青墨 |
| `--atlas-float` | `#ece4d3` | 暖纸浮层族实色化（alpha 消费处自调） |

---

## 3. 五主题完整 token 对照表（全部精确 hex，浅/深双套）

> 暖纸 paper = 现状 `:root`/`:root.dark` 值，此表只为对照完整列出；施工时 paper 不落任何覆写块。

### 3.1 暖纸 paper（默认 · 现状冻结）

| token | 浅 | 深 |
|---|---|---|
| --bg-primary | #f7f4ed | #1a1815 |
| --bg-secondary | #faf8f4 | #211f1b |
| --bg-tertiary | #f0ece3 | #2c2923 |
| --bg-canvas | #fefdfb | #1e1c18 |
| --paper-bg | #fefdfb | #26231e |
| --bg-panel | #f0ece3 | #2c2923 |
| --bg-elevated | #fefdfb | #2c2923 |
| --text-primary | #2c2c2c | #ede8df |
| --text-secondary | #6b6560 | #bfb8ab |
| --text-muted | #756c5e | #8a8275 |
| --text-faint | #a89e90 | #6b6459 |
| --border-color | #e0dbd3 | #3a3530 |
| --hover-bg | #eee9df | #33302a |
| --scrollbar-thumb / hover | #c8c0b4 / #a89e90 | #4a4540 / #5c5650 |
| --accent-400/500/600 | #9685c2 / #7c6aad / #6d5dab | #8b6de8 / #a78bfa / #c4b5fd |
| --ok / --ok-bg | #047857 / #d1fae5 | #34d399 / #0f2b22 |
| --warn / --warn-bg | #b45309 / #fef3c7 | #fbbf24 / #33270e |
| --danger / --danger-bg | #b91c1c / #fee2e2 | #f87171 / #3a1a1a |
| --info / --info-bg | #1d4ed8 / #dbeafe | #93c5fd / #15243d |
| --shadow-sm | 0 1px 2px rgba(18,38,63,.05) | 0 1px 2px rgba(0,0,0,.5) |
| --shadow-md | 0 4px 12px rgba(18,38,63,.08) | 0 4px 12px rgba(0,0,0,.55) |
| --shadow-lg | 0 12px 32px rgba(18,38,63,.12) | 0 12px 32px rgba(0,0,0,.6) |
| --shadow-paper | 0 8px 20px rgba(18,38,63,.06) | 0 8px 20px rgba(0,0,0,.5) |
| 字体 | 现状（衬线标题/Inter body） | 同左 |

### 3.2 极简 minimal（高对比黑白灰 · 一点冷钢蓝 · 标题换无衬线）

| token | 浅 | 深 |
|---|---|---|
| --bg-primary | #f4f4f2 | #0e0e0e |
| --bg-secondary | #fafafa | #151515 |
| --bg-tertiary | #eaeae7 | #1f1f1f |
| --bg-canvas | #ffffff | #121212 |
| --paper-bg | #ffffff | #191919 |
| --bg-panel | #eaeae7 | #1f1f1f |
| --bg-elevated | #ffffff | #202020 |
| --text-primary | #161616 | #ececec |
| --text-secondary | #4f4f4f | #b3b3b3 |
| --text-muted | #6d6d6d | #8c8c8c |
| --text-faint | #a6a6a6 | #565656 |
| --border-color | #e0e0dd | #2b2b2b |
| --hover-bg | #ececea | #242424 |
| --scrollbar-thumb / hover | #c6c6c3 / #9e9e9b | #3a3a3a / #4e4e4e |
| --accent-400/500/600 | #6f90f2 / #3b62d8 / #2e4db0 | #7aa0f5 / #94b4f8 / #b6ccfb |
| --ok / --ok-bg | #0b7a4b / #e2f2e9 | #5cc98e / #12291d |
| --warn / --warn-bg | #96620a / #f8eed7 | #e0b054 / #2e2410 |
| --danger / --danger-bg | #c02c2c / #fae7e7 | #e57373 / #331414 |
| --info / --info-bg | #2e4db0 / #e6ecfb | #94b4f8 / #18223d |
| --shadow-sm | 0 1px 2px rgba(0,0,0,.06) | 0 1px 2px rgba(0,0,0,.5) |
| --shadow-md | 0 4px 12px rgba(0,0,0,.08) | 0 4px 12px rgba(0,0,0,.55) |
| --shadow-lg | 0 12px 32px rgba(0,0,0,.12) | 0 12px 32px rgba(0,0,0,.6) |
| --shadow-paper | 0 4px 14px rgba(0,0,0,.05) | 0 4px 14px rgba(0,0,0,.5) |
| --font-heading | 'Inter','PingFang SC','Microsoft YaHei','Segoe UI',sans-serif | 同左 |
| --font-body | 同默认 | 同左 |

性格注：纸面纯白的「校样稿」。accent 只出现在交互焦点，全站其余一律灰阶；标题换黑体感（无衬线）是极简与暖纸最醒目的一眼差。

### 3.3 柔和 soft（低饱和奶油 · 雾玫瑰 accent · 阴影大而软）

| token | 浅 | 深 |
|---|---|---|
| --bg-primary | #f5f0e8 | #221d19 |
| --bg-secondary | #faf6ef | #29241f |
| --bg-tertiary | #efe7da | #322c26 |
| --bg-canvas | #fdfaf4 | #252019 |
| --paper-bg | #fdfaf4 | #2d2822 |
| --bg-panel | #efe7da | #322c26 |
| --bg-elevated | #fdfaf4 | #332d26 |
| --text-primary | #4b423b | #ece2d6 |
| --text-secondary | #7d7166 | #c3b6a6 |
| --text-muted | #8d8172 | #9b8f80 |
| --text-faint | #b3a898 | #6e6455 |
| --border-color | #e6dccd | #3e372f |
| --hover-bg | #f0e8db | #37312a |
| --scrollbar-thumb / hover | #d3c7b4 / #b5a891 | #4a423a / #5d5348 |
| --accent-400/500/600 | #cfa0ab / #b77e8d / #a36778 | #d3a4b1 / #d9a7b0 / #e5bec5 |
| --ok / --ok-bg | #5d8a6a / #e3ede2 | #8fb896 / #25301f |
| --warn / --warn-bg | #b08a4a / #f5ecd9 | #d3ac6c / #35290f |
| --danger / --danger-bg | #b65b5b / #f5e4e4 | #d98b8b / #382020 |
| --info / --info-bg | #7d93ad / #e6ecf1 | #9db4c9 / #232e38 |
| --shadow-sm | 0 1px 3px rgba(120,100,80,.08) | 0 1px 3px rgba(0,0,0,.45) |
| --shadow-md | 0 6px 18px rgba(120,100,80,.10) | 0 6px 18px rgba(0,0,0,.5) |
| --shadow-lg | 0 16px 40px rgba(120,100,80,.14) | 0 16px 40px rgba(0,0,0,.55) |
| --shadow-paper | 0 6px 16px rgba(120,100,80,.07) | 0 6px 16px rgba(0,0,0,.45) |
| 字体 | 同默认（衬线标题） | 同左 |

性格注：奶油纸+热可可。文字不是黑是可可棕；语义色全部降饱和（雾绿/杏/柔红/雾霾蓝）；阴影带暖棕调、更大更软。与暖纸的区别：暖纸是「书店新书的米白」，柔和是「羊绒毯上的奶茶」。

### 3.4 专业 pro（冷灰蓝工作台 · 钢蓝 accent · 阴影冷调）

| token | 浅 | 深 |
|---|---|---|
| --bg-primary | #eef1f5 | #10151b |
| --bg-secondary | #f5f7fa | #151b22 |
| --bg-tertiary | #e4e9ef | #1c242d |
| --bg-canvas | #fbfcfe | #12181f |
| --paper-bg | #ffffff | #1a222b |
| --bg-panel | #e4e9ef | #1c242d |
| --bg-elevated | #ffffff | #1d252e |
| --text-primary | #20262e | #e3e9ef |
| --text-secondary | #525c68 | #b0bac5 |
| --text-muted | #66707c | #8792a0 |
| --text-faint | #9aa3ad | #5c6672 |
| --border-color | #d6dde4 | #2a343f |
| --hover-bg | #e6ebf1 | #232d38 |
| --scrollbar-thumb / hover | #bcc5cf / #9aa5b2 | #39444f / #4b5764 |
| --accent-400/500/600 | #5d8fd1 / #2f6db3 / #265a98 | #6fa3dc / #82b3e5 / #a4c8ec |
| --ok / --ok-bg | #177a52 / #def0e7 | #5cb98d / #14271f |
| --warn / --warn-bg | #a06a08 / #f9efd6 | #d9a94f / #2d2410 |
| --danger / --danger-bg | #bb3232 / #f9e4e4 | #e07b7b / #341919 |
| --info / --info-bg | #2f6db3 / #e2ecf7 | #82b3e5 / #182738 |
| --shadow-sm | 0 1px 2px rgba(30,50,70,.06) | 0 1px 2px rgba(0,0,0,.5) |
| --shadow-md | 0 4px 14px rgba(30,50,70,.09) | 0 4px 14px rgba(0,0,0,.55) |
| --shadow-lg | 0 12px 32px rgba(30,50,70,.13) | 0 12px 32px rgba(0,0,0,.6) |
| --shadow-paper | 0 6px 18px rgba(30,50,70,.07) | 0 6px 18px rgba(0,0,0,.5) |
| 字体 | 同默认（衬线标题——出版社审校感） | 同左 |

性格注：编辑部日光灯/夜班审校台。纸面纯白、桌面冷灰、accent 钢蓝——信息密度高的页面（数据/文风）在这个主题下最「称手」。与极简的区别：极简是黑白摄影，专业是冷灰蓝工作台（边框与底都带蓝调）。

### 3.5 二次元 anime（亮色高饱和可爱系 · 樱饼浅档/霓虹夜空深档 · 标题圆体系）

| token | 浅 | 深 |
|---|---|---|
| --bg-primary | #fff2f6 | #17101f |
| --bg-secondary | #fff8fa | #1d1526 |
| --bg-tertiary | #fbe6ee | #251b30 |
| --bg-canvas | #fffcfd | #191221 |
| --paper-bg | #fffdfd | #221a2c |
| --bg-panel | #fbe6ee | #251b30 |
| --bg-elevated | #ffffff | #261c31 |
| --text-primary | #43304e | #f3eafd |
| --text-secondary | #7d6586 | #cbb8dd |
| --text-muted | #8d7595 | #a08bb3 |
| --text-faint | #bba8c0 | #6e5c80 |
| --border-color | #f2d7e3 | #372847 |
| --hover-bg | #fbe9f1 | #2c2139 |
| --scrollbar-thumb / hover | #ecc3d4 / #d9a3bb | #46355c / #5a4674 |
| --accent-400/500/600 | #f77bab / #ef5390 / #d63d7c | #ff8fbb / #ffa5c8 / #ffc2d9 |
| --ok / --ok-bg | #1fae7d / #d9f5ea | #4fd6a4 / #142b24 |
| --warn / --warn-bg | #d98a12 / #fdf0d7 | #f0b95a / #33260e |
| --danger / --danger-bg | #e84a6f / #fde3ea | #ff7d9c / #3a1824 |
| --info / --info-bg | #5b8def / #e3ecfd | #8ab0ff / #1b2540 |
| --shadow-sm | 0 1px 3px rgba(200,80,130,.10) | 0 1px 3px rgba(0,0,0,.5) |
| --shadow-md | 0 4px 14px rgba(200,80,130,.12) | 0 4px 14px rgba(0,0,0,.55) |
| --shadow-lg | 0 14px 36px rgba(200,80,130,.16) | 0 14px 36px rgba(0,0,0,.6) |
| --shadow-paper | 0 6px 18px rgba(200,80,130,.10) | 0 6px 18px rgba(0,0,0,.5) |
| --font-heading | 'Yuanti SC','YouYuan','PingFang SC','Microsoft YaHei',sans-serif | 同左 |
| --font-body | 同默认 | 同左 |

性格注：浅档=樱饼（白里透粉、深葡萄文字不是黑）；深档=霓虹夜空紫。圆体标题栈（Yuanti/YouYuan 系统必中其一，不中退雅黑圆感）是二次元的第一眼性格。阴影带粉调。**朱砂/薄荷/鎏金签名色在本主题依然恒定**——可爱的是界面，笔还是那支笔。

---

## 4. 小说化视觉语言体系（第一诉求的正面回答）

### 4.1 字体策略（裁决：零 webfont，栈重排 + 字重/字距/行高承担性格）

- **标题** `--font-heading`：按主题给栈（见 §3 各表字体行）。衬线承担「书」感（paper/soft/pro），黑体承担「校样」感（minimal），圆体承担「轻小说」感（anime）。
- **正文 UI** `--font-body`：全主题统一 Inter/苹方栈（界面可读性不玩花样）。
- **正文文稿** `--editor-font-family`：全主题恒定宋体系，**不随主题变**——作者写的是纸上的字，纸感恒定。想改走「编辑器排版」设置，不进主题系统。
- **数字展示**：裁决——统计大数字（文风指纹/数据页用量）统一用 `--font-heading` 衬线（insights 现状孤立决定升格为全站约定：「页码感」），极简主题自然落黑体数字，同样成立。
- `--font-serif`/`--font-mono` 真 bug 修复：`:root` 新增
  `--font-serif: var(--font-heading);`（8 处 CanonSection/CanonTruthDetailDrawer 引用立即生效，随主题换栈）
  `--font-mono: ui-monospace,'Cascadia Mono',Consolas,'Courier New',monospace;`

### 4.2 纸面质感（可开关的 --paper-*）

- `--shadow-paper`（§3 每主题给值）统一替换三处现值 `0 8px 20px rgba(18,38,63,.06)` 与 ModalShell 投影。
- 纸纹（可选项，默认关）：`:root` 定义 `--paper-texture: none;`，「外观」区开「纸纹」后置为一个 4KB 内 SVG feTurbulence data-URI（`url("data:image/svg+xml,...")`，浅档 opacity .03/深档 .05 叠在 .paper 面）。实现位置：`.toc-page`、写作台纸列、`.paper` 工具的 `background-image: var(--paper-texture)`。开关走 appearance.bg.texture 或独立布尔——裁决：**纸纹归为背景种类之一**（§5 kind='texture'），不做第二个开关。

### 4.3 朱批与仪式感排印（全主题恒定规范，不落 token 的直接写进规范）

- 朱批体系：朱砂两档 token（§2）承担——未读朱点、安全类朱点+光环、矛盾段左缘 3px 朱条、闪朱 cs-fresh、时间轴揭示朱点、岔路标记。
- 仪式感排印规约（写进 02 的共享层施工项，数值全站统一）：
  页头章节号 letter-spacing 0.08em；「目录」级 0.3em；题材眉标 0.22em；
  章节分隔符统一用 `❦`（现各页零散使用 *, ——, ·，收编为一种）；
  竖排书脊 desk-spine 保留不动。
- 动效密度：「外观」区新增「降低动效」开关 → `motion-low` class → 复用 style.css 既有 prefers-reduced-motion 毯式规则体（同一套 CSS 写两个选择器），罗盘摆动/金芒旋转/呼吸微光全灭。零新增动画代码。

### 4.4 各主题下「小说感」的成立方式（设计自检）

| 主题 | 小说感载体 |
|---|---|
| 暖纸 | 现状全量（纸+衬线+朱砂+古地图） |
| 极简 | 校样稿：纯白纸面+黑体标题+朱砂批注在高对比灰阶里更跳，「编辑红笔」感 |
| 柔和 | 奶油书页+雾玫瑰，睡前读物感；朱砂在奶油底上偏暖更融 |
| 专业 | 出版社审校台：冷灰桌面衬白纸，衬线标题+朱砂=红笔审校意象 |
| 二次元 | 轻小说文库本：圆体标题+樱饼底+亮粉 accent；薄荷 AI 与朱砂在粉紫底上依然可读（签名色恒定价值在此兑现） |

---

## 5. 自定义背景机制

- **种类**：跟随主题（默认）/ 自选纯色 / 本地图片 / 内置纸纹（grain 细纹、weave 织纹两款 SVG 内置）。
- **作用层**：只换桌面层（§1.4 body::before），纸面/古地图/书封不动。
- **图片约束**：文件选择后前端压缩（canvas 缩到最长边 1920、JPEG q0.8），dataURL 存 localStorage；压缩后 >1.5MB 拒绝并 toast 提示。遮罩滑杆 0~80%，默认 55%（深档自动反色遮罩，§1.4）。
- **存储理由复述**：同步可读性（防闪）> 跨设备一致性；外观重设 10 秒成本，换 origin 漂移可接受。
- **与纸面关系**：背景是「桌面」，纸是「稿纸」——稿纸永远干净（--paper-bg 主题值），这是可读性红线，不提供「纸面也换图」的选项。

---

## 6. 「外观」设置区（AppSettingsModal）

- **位置**：常显 section，插在「实验：编辑器排版」折叠区**之后**、misc-grid（:790）**之前**；排版折叠区删除、内容迁入本区。
- **布局**（720px 单列卡内）：
  1. **主题**——五张预览小卡横排网格（每张 128×88：主题桌面色为底、纸面色块居中、三行示意线=标题行（accent 色 8px 高）/正文行（text-secondary 6px）/薄荷+朱砂两点；卡下主题名+一行性格词：「暖纸·默认」「极简·校样」「柔和·奶油」「专业·审校」「二次元·樱」）。选中态=accent 2px 描边+朱点角标。
  2. **明暗**——三档 radio：跟随系统 / 浅色 / 深色（即时生效，不走保存按钮）。
  3. **背景**——四选一分段控件（主题默认/纯色/图片/纸纹）+ 条件展开：纯色=色板 input[type=color]；图片=选文件按钮+遮罩滑杆+「清除」；纸纹=细纹/织纹两枚缩略块。
  4. **编辑器排版**——原 radio 两项原样迁入。
  5. **降低动效**——checkbox 一枚。
- 预览小卡用纯 CSS 色块实现（值直接读本稿 §3 表，写死在设置组件里=预览合理豁免，不进文档 HTML）。

---

## 7. 世界页古地图裁决细则

- **豁免范围**：WorldMap/WorldTimeline/WorldView 三容器的羊皮画布、鎏金、暖墨、烛光暗角、毛边滤镜、印章、燕尾书签、罗盘、blankAtlas（生成物 9 处内联色，不改生成脚本）——全部保持现状值，浅/深/任何主题恒定。
- **追认设计决定**（写进组件头部注释）：深色模式下地图保持亮羊皮=「灯下看地图」；书封六色板同理（已有注释豁免）。
- **最小 token 集** `--atlas-*`（§2 表）：本期只在 `:root` 定义，不替换存量 hex——为未来「地图皮肤」留挂点，避免本期 375 行高风险替换。
- **不豁免的部分**（进 02 施工单）：世界页的抽屉族/浮层/表单（DrawerShell 已正规军；LocationDetailDrawer 灰系旧兜底、EntityDetailDrawer 三态 chip、ReaderMirrorBoard slate 残留）随主题；engine 三张 JS 色表（EVENT_TYPE_COLOR/RELATION_TYPES/NODE·EDGE_TYPE_COLORS）是「地图内容色」——裁决：**事件/关系/节点色是地图画布内容，跟随古地图豁免恒定**；ZHU_COLOR 改读 --cinnabar 常量对齐。

---

## 8. Tailwind 双轨裁决（config 一次性映射）

```js
// tailwind.config.js theme.extend.colors 改造
ink:   { 50:'var(--bg-canvas)', 100:'var(--bg-tertiary)', 200:'var(--border-color)',
         300:'var(--scrollbar-thumb)', 400:'var(--text-faint)', 500:'var(--text-muted)',
         600:'var(--text-secondary)', 700:'var(--text-secondary)', 800:'var(--text-primary)',
         900:'var(--text-primary)' }
parchment: { 50:'var(--paper-bg)', 100:'var(--bg-secondary)', 200:'var(--bg-primary)',
         300:'var(--bg-tertiary)', 400:'var(--hover-bg)', 500:'var(--border-color)' }
         // 600-900 删除，grep 验证零引用（盘点未见高档位使用）
accent: { 400:'var(--accent-400)', 500:'var(--accent-500)', 600:'var(--accent-600)' }
         // 50-300/700-900 删除，grep 验证
primary: 整族删除（grep 验证零引用，盘点标记「疑似遗留」）
```

施工注意：var 值颜色下 Tailwind 的 `/opacity` 修饰符（如 `bg-accent-500/50`）不生效——先 grep `\b(bg|text|border)-(ink|parchment|accent)-\d+/` 找出透明度修饰用法，有则该处迁入组件 style 用 color-mix。emerald/rose/amber/blue/slate/indigo/violet 外来语义类不在 config 映射范围，随 02 各域逐文件清剿。

---

## 9. 盘点 §7 八项 bug 的消化路径

| # | bug | 消化 |
|---|---|---|
| 1 | --accent-500-rgb 未定义 | P1：5 处引用（ChapterTocDrawer:201/ChapterTocList:95/MarkdownImportModal:311/ExtractionPreviewPanel×5）改 `color-mix(in srgb, var(--accent-500) N%, transparent)`，不新增 -rgb token |
| 2 | --font-serif/--font-mono 未定义 | P0：:root 补定义（§4.1） |
| 3 | 无切换开关+FOUC | P0：本稿 §1.2/§1.3/§6 |
| 4 | z-index 表外 ≥8 处 | P1/P2：归表映射见 02 §6 表 |
| 5 | 9-11px 裸字号 | P2：统一提到 --text-xs(12px)，视觉微涨接受 |
| 6 | 朱砂双值/verdict 第二套/LocationDetailDrawer 灰系 | P1/P2：--cinnabar 两档；--ok/--warn/--danger；02 §3 |
| 7 | outline-note 薄荷 fallback | P1：清 fallback（accent 已有定义，fallback 恒死代码） |
| 8 | RichTextEditor diff 色写进文档 mark | P2：JS 层改写 class（diff-add/diff-del），样式走 stylesheet 消费新 token `--diff-add-bg:rgba(16,185,129,.18)` / `--diff-del-bg:rgba(220,60,60,.16)`（浅深档 :root 定义）；存量文档内联 style 无害残留，不清洗 |

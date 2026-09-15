# 组件视觉语言层（04 · 第二轮主题施工设计稿）

> 输入：用户对第一轮的批评——「只改了主题系统，组件/布局/交互都没改」。第一轮（01/02/03）是 token 管道，默认暖纸下观感几乎不变；本轮是**看得见的「小说化」皮肤重构**。
> 读者：施工 agent。每项含「现状 → 设计 → 施工位（文件/类）→ 验收」，末尾为施工顺序。
> 红线（沿用 03 批注总红线，本轮追加）：
> ① `--editor-max-width: 880px` 纸列几何不动；② 幽灵 mark class/节点/语义不动（`.ghost-draft` 的 `border-radius:2px`/`padding:0` 是行内网格敏感件，圆角归一**绕开**）；③ 书封六色板不动（hover 微抬是几何动效，允许）；④ 古地图三容器画布装饰色一行不动（含其内部暖棕/青墨调阴影——C 批清剿先判归属再动手）；⑤ 一切新视觉消费 token，五主题×明暗自动成立，**禁止只给暖纸画装饰**；⑥ 有对拍单测的模块（extensions 34 项 / contextBlockFormat 保字 / ghostReap / heartbeatSeam）每批全绿。

---

## A. 纸感升级（第一轮欠账）

### A1. 纸纹接线：--paper-texture 从定义到消费

**现状**
- `style.css:168` `:root { --paper-texture: none; }` 定义后**全仓零消费**。
- `useAppearance.apply()` 的 texture 分支只写 `--user-bg-image`（桌面层 body::before 消费），纸面颗粒没有通道。
- `index.html:11` 内联防闪脚本**刻意豁免 texture**（「颗粒晚一帧不可感知」）——此豁免保持，纸纹通道不需要进防闪脚本。
- 桌面 TEXTURES 的 grain 是 0.55 不透明度的 feTurbulence 彩噪，靠 55% 白纱压淡——**直接叠纸面会脏**，纸面需要独立淡剂量变体。

**设计**
1. useAppearance 新增第二张纹理表 `PAPER_TEXTURES`（纸面淡剂量；灰度化+低不透明，深档纸上靠噪声里的亮微粒显形，**单档两用不分明暗**）：

```ts
/** 纸面淡剂量纸纹（灰度化 feColorMatrix + 低不透明；浅纸显暗粒、深纸显亮粒，单档两用） */
const PAPER_TEXTURES: Record<BgTexture, string> = {
  grain:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)' opacity='0.16'/%3E%3C/svg%3E\")",
  weave:
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cdefs%3E%3Cpattern id='w' width='12' height='12' patternUnits='userSpaceOnUse'%3E%3Cpath d='M0 6 Q3 3 6 6 T12 6' fill='none' stroke='%23808080' stroke-opacity='0.14' stroke-width='1'/%3E%3Cpath d='M0 12 Q3 9 6 12 T12 12' fill='none' stroke='%23808080' stroke-opacity='0.09' stroke-width='1'/%3E%3C/pattern%3E%3C/defs%3E%3Crect width='120' height='120' fill='url(%23w)'/%3E%3C/svg%3E\")",
}
```

2. `applyAppearance()` texture 分支增写一行：`s.setProperty('--paper-texture', PAPER_TEXTURES[ap.bg.texture])`；其余三个分支（theme/color/image）增 `s.removeProperty('--paper-texture')`（回落 `:root` 的 `none`）。`index.html` 豁免注释扩一行：「--paper-texture 同此豁免」。
3. CSS 消费点（**⚠ 施工陷阱：`background: var(--paper-bg)` 简写会把 background-image 重置为 none，必须先拆简写**）：

```css
/* style.css 新增「纸面质感」段（A1/A2 共用工具类） */
.paper-face {
  background-color: var(--paper-bg);
  background-image: var(--paper-texture); /* 缺省 none 零成本；选「纸纹」背景时纸面同步得纹 */
  border: 1px solid var(--paper-edge);    /* A2 */
  box-shadow: var(--shadow-paper);
}
```

消费点清单（3 处）：
| # | 位置 | 改法 |
|---|---|---|
| 1 | `style.css` `.toc-page`（:1163） | `background: var(--paper-bg)` → `background-color` + `background-image: var(--paper-texture)` 两行；border 色换 `--paper-edge` |
| 2 | `ChapterEditorView.vue` `.paper`（:233 写作台纸列） | 同上拆简写 + `--paper-edge`；类上 `shadow-[var(--shadow-paper)]` 保持 |
| 3 | 新 `.paper-card`（D2 纸面卡档） | 直接 `@apply` 语义等价于 `.paper-face` 规格（见 D2） |

**施工位**：`frontend/src/composables/useAppearance.ts`（PAPER_TEXTURES + apply 两分支）、`frontend/index.html`（注释一行）、`frontend/src/style.css`（.paper-face 段 + .toc-page 拆写）、`frontend/src/features/chapter-editor/presentation/ChapterEditorView.vue`（.paper 拆写）。

**验收**
- 设置→外观→背景选「纸纹·细纹」：写作台纸列与目录页纸面出现细微灰粒（约 5% 感知度，不脏字）；切回「主题默认」纸面回净。
- 深色模式：纸面微粒可见但不刺眼（亮粒显形）；五主题逐一过一遍无主题破版。
- typecheck 绿；未选纸纹时 `getComputedStyle` 的 `background-image: none`（零成本验证）。

---

### A2. 纸张物理感：纸缘描边 / hover 微抬 / 多层纸叠影

**现状**
- 纸列/目录页描边与全站卡片共用 `--border-color`（#e0dbd3 极淡），纸的「裁切边缘」无存在感；投影已 token 化（--shadow-paper）。
- `.card-hover`（style.css:473）定义为 -1px+--shadow-md，**全仓零消费**（死工具类，可就地升格零回归）。
- 抽屉/助手面板（`.inspector-drawer`/`.toc-drawer`/世界页 DrawerShell）只有一道 --shadow-lg，「从一叠纸里抽出一页」的层次未表达。

**设计**
1. **新 token `--paper-edge`**（纸缘色=border-color 向 text-faint 走 40%，比边框深半档；10 块值如下，配方注释留在 style.css）：

| 主题 | 浅 | 深 |
|---|---|---|
| paper（:root / :root.dark） | `#cac3b8` | `#4e4840` |
| minimal | `#c9c9c7` | `#3c3c3c` |
| soft | `#d2c7b8` | `#51493e` |
| pro | `#bec6ce` | `#3e4853` |
| anime | `#dcc4d5` | `#4d3d5e` |

消费点：`.paper-face` 边框（A1 已含）、写作台 `.paper`、`.toc-page`、D2 `.paper-card`、A2-3 叠影条。

2. **卡 hover 微抬统一**：`.card-hover` 就地升格（-1px→-2px，transition 0.18s ease）：

```css
.card-hover { transition: transform 0.18s ease, box-shadow 0.18s ease; }
.card-hover:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
```

挂点名单（可点卡才挂，静态纸面卡/抽屉/面板不挂）：书架书卡（LibraryView .book-card 壳，书封色板不动）、文风样本卡（StyleSampleSection）、世界实体卡（EntityCard）、大纲章卡（ChapterCard）。

3. **多层纸叠影（sheet-stack）**：抽屉=从纸堆抽出的一页，画布侧边缘露出 3px「下层纸」撞色边。用 box-shadow 硬偏移实现（不用 ::before——`.toc-drawer` 等壳 `overflow:hidden` 会裁掉外探伪元素，投影不受裁剪）：

```css
/* style.css 新增（A2-3）：右缘抽出（面板在画布右，下层纸露左缘）/ 左缘抽出镜像 */
.inspector-drawer { box-shadow: -4px 0 0 -1px var(--paper-edge), var(--shadow-lg); }
.toc-drawer       { box-shadow:  4px 0 0 -1px var(--paper-edge), var(--shadow-lg); }
```

世界页 `DrawerShell .ds` 同 `.inspector-drawer` 规格（其既有定向影 `12px 0 36px rgba(0,0,0,.45)` 被组合影取代）。

**施工位**：`style.css`（--paper-edge ×10 块、.card-hover 升格、.inspector-drawer/.toc-drawer 投影替换）、`DrawerShell.vue`（.ds 投影）、四个卡片组件（挂 .card-hover）。

**验收**
- 默认暖纸下：纸列/目录页边缘出现可辨的「纸裁边」；打开助手面板，面板左缘见 2-3px 下层纸错边；目录抽屉右缘镜像。
- 书卡/样本卡 hover 抬 2px 带影；motion-low 下抬升被毯式灭（既有规则覆盖）。
- 五主题×明暗：纸缘色在每块都可辨但不抢（比边框深半档的灰），极简主题下是「校样灰边」。

---

### A3. 章节仪式感：章页页头与目录页排印

**现状**
- `ChapterEditorView` 页头：章号 `.page-head__chapter` 11px（字阶外裸值）/0.08em/600/muted；标题 1.75rem 衬线 700；标题与正文之间**无任何分隔饰**。
- `TocPage`：书名 3xl 衬线 0.04em + 「目录」副行 sm/0.3em/muted，扉页感已有但未点睛；章条目号 `.ch-num` 非衬线。
- 01 §4.3 裁决的 letter-spacing 体系（章号 0.08em/目录级 0.3em/题材眉标 0.22em）只落了一半。

**设计**
1. **章号眉标化**：`.page-head__chapter` 字号 0.6875rem → `var(--text-xs)`（12px，归字阶顺带）、letter-spacing 0.08em → **0.22em**（题材眉标档）、font-weight 600→500。视觉：小而疏的灰眉标，把「第N章」从标签升格为书页眉。
2. **章饰（❦ 主落地位）**：标题下、页首块槽之前插一行饰——**左 ❦ + 右延 hairline**（左对齐随标题，不做对称双线；编辑器画布安静优先，符色用纯装饰档）：

```html
<!-- ChapterEditorView.vue：.page-head__title 之后 -->
<div class="page-head__ornament" aria-hidden="true">❦</div>
```
```css
.page-head__ornament {
  display: flex; align-items: center; gap: var(--space-3);
  margin-top: var(--space-3);
  font-size: 12px; line-height: 1;
  color: var(--text-faint); /* 纯装饰档：不承载信息，不上朱砂 */
}
.page-head__ornament::after { content: ''; flex: 1; height: 1px; background: var(--border-color); }
```

3. **目录页扉页升级**：
   - `.toc-page__title` letter-spacing 0.04em→0.06em；
   - `.toc-page__sub` 改 `❦ 目录 ❦`（对称符=扉页成立，符色 --text-faint，文字色保持 muted）；
   - 章条目页码感：`ChapterTocList.vue` 增加 `.toc-list--page .ch-num { font-family: var(--font-heading); color: var(--text-faint); }`（仅 page 变体，抽屉变体不动）。

**施工位**：`ChapterEditorView.vue`（章号样式 + ornament 行）、`TocPage.vue`（sub 文案与样式）、`ChapterTocList.vue`（page 变体 .ch-num 覆写）。

**验收**
- 章页：眉标疏朗、标题衬线、其下 ❦+细线一道——默认暖纸下与施工前对比「一眼像书页」；标题 input 的 hover/focus 下划线行为不变。
- 目录页：书名+「❦ 目录 ❦」+衬线章号，扉页感成立。
- ❦ 是文本节点不是图片，五主题自动着色；motion-low 无影响（无动效）。

---

## B. 全站装饰语言（本轮新增）

### B1. 分区标题体系升级（拍板：❦ 前缀 + 短钉线）

**现状**：`.sec-head`/`.sec-title`/`sec-hint` 全局工具类（style.css:929），9 文件 27 处消费（文风 5 区 + 世界抽屉族 4 + 其余）——**改工具类一处，27 处零改动自动生效**。

**候选与拍板**
- 主方案：标题前 ❦ 小节符（--text-faint）+ 标题后 1.5rem 短钉线（--border-color）。
- 备选：朱砂首字下沉——否决：::first-letter 对 CJK 排版节奏破坏大、首字下沉是拉丁传统、且朱砂进场会让 27 处分区标题满地朱（违反 B3 克制纪律）。
- **拍板主方案**，符色 --text-faint 不上朱砂（装饰档纪律同 A3）。

```css
/* style.css 工具类原位升级（27 处消费零改动） */
.sec-title {
  display: flex; align-items: center; gap: var(--space-2);
  font-family: var(--font-heading); font-size: var(--text-lg);
  font-weight: 600; color: var(--text-primary);
}
.sec-title::before { content: '❦'; font-size: 0.72em; font-weight: 400; color: var(--text-faint); }
.sec-title::after  { content: ''; width: 1.5rem; height: 1px; background: var(--border-color); }
```

注意：`.sec-head` 常有 `.sec-hint`/`.sec-sub` 兄弟，钉线固定 1.5rem **不延伸行尾**（延伸会挤压副行、且各消费点副行有无不一）。局部覆写点（如 StyleSampleSection 的 `border-bottom:none` 变体）不受影响——::before/::after 是纯增量。

**施工位**：`style.css`（.sec-title 三条声明）。
**验收**：文风页五分区标题统一点符+钉线；世界页四抽屉分区同貌；五主题下符色融入不跳；hint 副行布局零位移（baseline 对齐改为 center 后行高不变式——肉眼核）。

---

### B2. ❦ 分隔符统一落地（克制清单）

**现状**：03 批注将 ❦ 挂起——「现存 */——/· 几乎都在正文语义文本与 placeholder 里，纯装饰位未成规模」。该判断对**语义文本**继续有效，本轮给 ❦ 划**纯装饰位清单**，重启但克制：

| # | 落地位 | 来源 |
|---|---|---|
| 1 | 章页章饰（左 ❦+细线） | A3-2（主落地位） |
| 2 | 目录页「❦ 目录 ❦」副行 | A3-3 |
| 3 | 分区标题 ::before 前缀 | B1 |
| 4 | 空状态主句上方饰符 | D3 |

**明确不碰**：正文语义文本内的 `*`/`——`/`·`（03 判断原样保留）；placeholder；SparkDock 槽位符号 ▸⚑◆○（功能符号不是装饰）；世界页古地图全域（豁免）；文档正文渲染（HTML 导入章节内的分隔行）。

**验收**：全仓 ❦ 只出现在上述 4 类位置（grep `❦` 核对）；正文/placeholder 零改动。

---

### B3. 朱批点缀克制清单（≤8 处，含既有）

朱砂语义=「作者的笔在界面上留的批注」。满地朱=廉价，本轮只新增 2 处，总清单冻结如下：

| # | 位置 | 态 |
|---|---|---|
| 1 | 真相层「里」卡朱晕+密印 | 既有，不动 |
| 2 | 时间轴揭示朱点 | 既有，不动 |
| 3 | 主题预览卡选中朱点角标 | 既有，不动 |
| 4 | 大纲板真相朱点/伏笔弧（StorylineAxis/ChapterCard） | 既有，不动 |
| 5 | SpinePanel 岔路声明标记 | 既有，不动 |
| 6 | **完稿报告未读点**：`.assist-rail__badge` background `var(--danger)` → `var(--cinnabar-bright)` | 新增。「有新批注」不是错误；danger 回收给真错误 |
| 7 | **待确认计数**：世界页待确认抽屉 `.ds-count` 与写作台切片条收件箱计数 → `color: var(--cinnabar)` + `background: color-mix(in srgb, var(--cinnabar) 10%, transparent)`（加修饰类 `.ds-count--pending`，DrawerShell 通用壳不默认朱砂） | 新增。「等你裁决的数」=朱批语义 |
| 8 | CanonSection 句子录入落账闪朱（cs-fresh） | 既有，不动 |

**明确不进朱砂**：分区标题符、章饰、空态饰符（全走 --text-faint 装饰档）、按钮 hover、链接、focus ring、硬禁 chip（danger 语义）、章节状态点（mint/灰）。

**施工位**：`style.css`（.assist-rail__badge）、`DrawerShell.vue`（.ds-count--pending 修饰类）、待确认抽屉与 WorldSceneSlice 收件箱计数的挂类点。
**验收**：五主题下朱砂出现点位=清单 8 处；报告到达时右缘检查图标点呈朱砂亮档而非警报红。

---

### B4. 衬线数字约定（页码感）

**现状**：InsightsView `.summary-num`/`.usage-num` 已衬线（01 期孤立先例）；文风指纹 `.metric-value`（1.25rem/600）非衬线；页头字数 12px 小字非衬线。

**约定**：**≥16px 展示的统计大数字**统一 `font-family: var(--font-heading)` + `font-variant-numeric: tabular-nums`（衬线等宽数字，防跳动）；≤13px 的 chip/徽标小计数**不强制**（衬线小数字辨识度差，明确排除页头字数/柱顶计数/书卡元信息）。

新增全局工具类：
```css
.num-serif { font-family: var(--font-heading); font-variant-numeric: tabular-nums; }
```

消费点名单：
| # | 位置 | 改法 |
|---|---|---|
| 1 | InsightsView `.summary-num` | 补 `tabular-nums`（衬线已有） |
| 2 | StyleFingerprintSection `.metric-value`（指纹指标网格） | 挂两句（类上加属性） |
| 3 | InspectorPanel「本章」字数大数值 | 挂 `.num-serif` |
| 4 | ChapterTocList page 变体 `.ch-num` | A3-3 已含 |
| 5 | 大纲章卡字数（ChapterCard） | 挂 `.num-serif`（若 ≥16px；小字则不动，施工核实） |

**验收**：文风指纹格与数据页大数字呈衬线等宽；12px 小计数全场无衬线（grep 核 `.num-serif` 未挂小件）。

---

## C. 阴影与卡片语言清剿（第一轮欠账）

**现状**：硬编码 box-shadow **98 处**（已排除豁免容器/既有 token/语义 inset）；圆角裸值 470+ 处（7px×28 / 6px×47 / 10px×17 / 0.1875rem×14 / 0.3rem×6……）。

### C1. 阴影批量映射

先补两枚 token（:root 一次，color-mix 以 token 为输入即主题自适应，无需按主题给值）：
```css
--ring-soft: 0 0 0 3px color-mix(in srgb, var(--accent-500) 12%, transparent); /* 焦点柔环 */
--glow-accent: 0 4px 12px color-mix(in srgb, var(--accent-500) 25%, transparent); /* accent 辉光（btn-primary:hover 同款） */
```

映射总表（按现值归并，施工按此 grep 替换）：

| 现值（代表） | 计数 | 映射 |
|---|---|---|
| `0 12px 32px rgba(0,0,0,.18)` | 7 | `var(--shadow-lg)` |
| `0 6px 18px rgba(0,0,0,.25)` / `0 12px 32px rgba(0,0,0,.22)` / `0 16px 44px rgba(0,0,0,.16)` / `0 10px 40px…` | 9 | `var(--shadow-lg)` |
| `0 8px 24px…` / `0 10px 24px/26px/32px…`（黑调） | 6 | 模态/抽屉=`--shadow-lg`；浮卡=`--shadow-md`（按所在层判） |
| `0 4px 12px/14px/16px…`（黑调） | ~6 | `var(--shadow-md)` |
| `0 1px 2-5px…` / `0 2px 8px…` | ~8 | `var(--shadow-sm)` |
| `0 0 0 3px rgba(124,106,173,.1/.12)` | 10 | `var(--ring-soft)` |
| `0 4px 12px rgba(124,106,173,.25)` | 4 | `var(--glow-accent)` |
| 暖棕调 `rgba(96,72,36,*)` `rgba(60,48,30,*)` `rgba(60,44,22,*)` `rgba(120,100,70,*)` | ~15 | **先判归属**：古地图三容器画布内=豁免不动；容器外（QuickCapturePanel/RelationInlineForm/BulkImportDialog 等）→ `--shadow-md/lg` |
| `12px 0 36px rgba(0,0,0,.45)`（DrawerShell 定向影） | 1 | A2-3 组合影取代 |
| `0 0 0 7px rgba(63,111,143,.28)` 等光环/脉冲件 | 余量 | 豁免容器内不动；容器外用 `color-mix(in srgb, var(--info) 28%, transparent)` 改写 |
| `inset 3px 0 0 var(--danger)` / `inset 0 0 0 1px var(--border-color)` | 保留 | 语义边，非投影，不动 |

重点文件序（先重灾后长尾）：`PanelContainer.vue` → `WorldView/WorldMap/WorldTimeline`（**只动容器外件**）→ `InspectorPanel.vue` → `SparkDock/BeatCardDock.vue` → `ModalShell/AppSettingsModal/InspirationModal/MarkdownImportModal` → `EditorFindBar/QuickEventNote(两枚)/WorldContextCard/PerceptionBand/WorldSceneSlice` → `StyleSampleSection/LibraryView` → 世界页 presentation 长尾（EntityCard/EventSpineList/Canon 两件/InlineCreate/BulkImportDialog/ForeshadowDetailDrawer/QuickCapturePanel/RelationInlineForm/LocationDetailDrawer/EntityDetailDrawer）。

### C2. 圆角归一

映射表（同 C1 批顺手做，同文件同改）：

| 裸值 | 归一 |
|---|---|
| 2px | **保留**（行内网格敏感件：.ghost-draft/.editor-find-match——红线，勿动） |
| 3px / 0.1875rem / 4px | `var(--radius-xs)` |
| 5px / 6px / 0.3rem / 0.35rem / 7px | `var(--radius-sm)` |
| 8px | `var(--radius-md)` |
| 10px / 0.625rem / 12px / 14px / 0.6rem | `var(--radius-lg)` |
| 0.25rem / 0.375rem / 0.5rem 字面值 | 换同名 token 引用 |
| 999px / 9999px / 50% | 保留（pill/圆） |
| 模态壳 | 恒 `var(--radius-xl)`（现状已归一，核漏） |

**验收**
- `grep -rn "box-shadow" frontend/src --include="*.vue"` 非 token 命中 98 → **≤25**（余量=豁免容器内+语义 inset+光环脉冲类，逐条可点名）。
- 圆角：grep `border-radius: (5|6|7|10|12|14)px` 命中清零；.ghost-draft/.editor-find-match 两处 2px 原样（对拍 extensions 34 项绿）。
- 肉眼：InspectorPanel/抽屉族/模态在五主题下投影性格随主题（极简硬、柔和大软、二次元粉调）。

---

## D. 布局节奏微调（皮肤级，不翻骨架）

### D1. 页面头统一规格

**现状**：四页 `.page-title` 已归一（heading/--text-2xl/0.08em/600；书架 --text-3xl 例外=产品门面，保留）；padding P4 已归一。副行与动作区各写各。

**规格（确认+补齐，不重排）**：
- 标题行：flex / align-items baseline / gap `var(--space-3)`；动作区 `margin-left:auto` 与标题 baseline 对齐。
- 副行（一句话说明，有才加）：`--text-sm` / `--text-secondary` / `var(--lh-normal)` / margin-top `var(--space-1)`。
- **页标题不加 ❦**（页级保持素——仪式在章页/目录页/分区三级，防装饰通胀）。

**施工位**：四页页头核对（LibraryView/OutlineView/InsightsView/StyleView），只动偏差处。
**验收**：四页标题字阶/字距/动作区基线一致；书架 3xl 例外保留。

### D2. 卡片三档规格（留白节奏）

**现状**：卡片 padding 各写各（0.5/0.625/0.875/1rem 混），圆角见 C2。

**三档全局工具类（style.css 新增）**：
```css
/* 紧凑卡：列表条目/指标格 */
.card-compact { padding: var(--space-2) var(--space-3); border-radius: var(--radius-md);
  background: var(--bg-secondary); border: 1px solid var(--border-color); }
/* 标准卡：样本卡/实体卡/章卡（可点卡叠 .card-hover） */
.card-std { padding: var(--space-4); border-radius: var(--radius-lg);
  background: var(--bg-canvas); border: 1px solid var(--border-color); box-shadow: var(--shadow-sm); }
/* 纸面卡：文书语义卡（真相表/里、完稿报告、指纹大卡）——A1/A2 纸面规格直通 */
.paper-card { padding: var(--space-5) var(--space-6); border-radius: var(--radius-lg);
  background-color: var(--paper-bg); background-image: var(--paper-texture);
  border: 1px solid var(--paper-edge); box-shadow: var(--shadow-paper); }
```

挂点名单：StyleSampleSection 样本卡→`.card-std`+`.card-hover`；InsightsView summary 格→`.card-compact`；EntityCard→`.card-std`+`.card-hover`；ChapterCard→`.card-std`；CanonTruthDetailDrawer 表/里两卡→`.paper-card`（里卡朱晕/密印叠加不动）。

**验收**：三档卡在同页（文风页）节奏一眼可辨；纸面卡选了纸纹背景时得纹（A1 通道验证第二落点）。

### D3. 空状态统一规格

**现状**：LibraryView `.empty-state`（48px 灰 icon+h2 1.25rem+p+按钮）；StyleView ramp-hero（38rem 定制三幕，已成熟）；TocPage 空章态（衬线句+primary）；ChapterEditorView「选择一个章节」（小 svg 图标+一句灰字）。四家四种排印。

**规格（全局 `.empty-state` 升格）**：
```css
.empty-state { display:flex; flex-direction:column; align-items:center; justify-content:center;
  padding: var(--space-12) var(--space-8); text-align:center; gap: var(--space-3); color: var(--text-secondary); }
.empty-state::before { content:'❦'; font-size:16px; color: var(--text-faint); } /* 饰符取代 48px 灰 icon */
.empty-state__title { font-family: var(--font-heading); font-size: var(--text-xl); font-weight:500; color: var(--text-primary); }
.empty-state__sub { font-size: var(--text-sm); max-width: 26rem; line-height: var(--lh-normal); }
.empty-state__action { margin-top: var(--space-2); } /* 主行动=btn-primary */
```

消费点：LibraryView 空书架（icon 删、h2→`.empty-state__title`）、OutlineView 空书态、TocPage 空章态、ChapterEditorView 未选章态（svg icon 删）。**StyleView ramp-hero 保留定制**（三幕设计已是独立语言，只核对标题 3xl 衬线）。

**验收**：四处空态=「❦ + 衬线主句 + 灰副句 + 主行动」同构；无 48px 灰图标残留；五主题下饰符色融入。

---

## E. 动效点缀（拍板：两项都不做）

1. **主题切换全局过渡（body 0.25s transition）——不做**。理由：① `* { transition }` 与 motion-low/prefers-reduced-motion 毯式规则直接冲突，白名单补丁成本高；② 写作台同屏挂 ProseMirror 大文档+Leaflet 地图，全属性过渡期 token 换色会触发大面积 repaint 拉扯；③ 主题切换是低频动作，瞬时切换=「换了个房间」语义干脆，过渡反而让五主题走查的对比判断失真。
2. **列表卡片入场 stagger——不做**。理由：书架/样本/实体列表是工具场景，>20 项时 stagger 是纯等待成本；Electron 低功耗下掉帧显廉价。
3. **本轮动效唯一变化**=既有微交互 token 化归一（`.card-hover` 升格 2px/A2、btn-primary 辉光换 `--glow-accent`/C1）——感知得到、性能零新增。

**验收**：motion-low 开关下全站无新增动画漏网（grep 本轮新增 CSS 无 `@keyframes`）。

---

## 施工顺序（每批可独立验证、独立提交）

| 批 | 内容 | 验证 |
|---|---|---|
| **批 1 · token 与工具类** | style.css：`--paper-edge`×10 块 + `--ring-soft`/`--glow-accent` + `.paper-face`/`.num-serif`/`.card-*` 三档/`.empty-state` 升格 + `.sec-title` 装饰升级 + `.card-hover` 升格 | typecheck 绿；文风页（sec-head 密集页）五主题×明暗走查：分区标题点符+钉线、无布局位移 |
| **批 2 · 纸感接线（A1/A2 核心）** | useAppearance PAPER_TEXTURES+apply 两分支；index.html 注释；.toc-page/.paper 拆 background 简写接 `--paper-texture`+`--paper-edge`；.inspector-drawer/.toc-drawer/.ds 叠影组合 | 选纸纹→纸面得纹/切回回净；助手面板左缘下层纸错边；目录抽屉镜像；深色与五主题过版 |
| **批 3 · 章仪式与目录（A3）** | ChapterEditorView 章号眉标+ornament 行；TocPage 书名/❦副行；ChapterTocList page 变体 .ch-num 衬线 | 章页与施工前截屏对比「一眼像书页」；目录扉页感；标题 input 交互零回归 |
| **批 4 · 阴影圆角清剿（C）** | 映射表按重点文件序批量替换；暖棕调先判豁免归属；圆角映射同批 | 阴影非 token 命中 ≤25；圆角裸值清零；.ghost-draft 2px 原样；extensions 34 项+ghostReap+heartbeatSeam 全绿 |
| **批 5 · 点缀收口（B3/B4/D2/D3）** | assist-rail badge 朱砂化；.ds-count--pending 两处；.num-serif 消费点；卡片三档挂点+.card-hover 挂点；空状态四处归一 | 朱砂点位=8 处清单；大数字衬线化小计数豁免；空态四处同构；motion-low 无新增动画 |

**批次间依赖**：批 1 是批 2-5 的 token/工具类前置；批 2 与批 3 互不依赖可并行；批 4 与批 3/5 文件面错开（C 批清剿文件若与批 5 挂点同文件，先 4 后 5）。**每批固定验收**：typecheck 绿 + 309 前端测试全绿 + 五主题×明暗抽一页肉眼 + 红线六条。

---

## 施工实况批注（2026-09-15 当日，批 1-5 全部落定）

**验收总态**：typecheck 零错 · 309 测试全绿 · 构建过 · 阴影非 token 命中 98→3（余量=书封材质豁免×2+地图 pulse-pick 豁免×1，逐条可点名）· 圆角裸值 382 处归一（余 2 处多值圆角：直方图柱顶 `3px 3px 0 0` 与 atlas-rail `12px 0 0 12px`，多值不在单值映射表，容忍）· ❦ 点位=4 类不溢出。

**逐批落点**：
- 批 1 ✅ --paper-edge ×10 块、--ring-soft/--glow-accent、.paper-face/.num-serif/.card-compact/.card-std/.paper-card/.empty-state 全套工具类、.sec-title ❦+短钉线（27 处消费零改动生效）、.card-hover 升格 -2px/0.18s。
- 批 2 ✅ useAppearance PAPER_TEXTURES 淡剂量表+--paper-texture 通道（theme/color/image 分支 removeProperty 回落）；.toc-page 与写作台 .paper 拆 background 简写接纹+纸缘；.inspector-drawer/.toc-drawer/.atlas-drawer/三个详情抽屉/PerceptionBand 覆态卡全部换纸叠影组合（`±4px 0 0 -1px var(--paper-edge)` 硬偏移）。
- 批 3 ✅ 章号眉标化（12px/500/0.22em）、❦+hairline 章饰行、目录扉页（书名 0.06em+「❦ 目录 ❦」）、page 变体章号衬线页码感。
- 批 4 ✅ 阴影按映射表清剿（ring-soft ×14/glow ×4/三档影 ×42/暖棕归 lg-md/朱砂晕 color-mix 化/EntityCard 选中环 text-primary 派生）；圆角 64 文件 382 处归并；radius var() 兜底 4 处剥离。
- 批 5 ✅ assist-rail 朱点 danger→cinnabar-bright、DrawerShell countPending 修饰类+待确认抽屉挂点、WorldSceneSlice 收件箱计数朱砂化（顺带修掉 #fff 字面色）、衬线等宽数字三处（指纹指标/本章字数/数据汇总）、真相表/里两卡升纸面卡规格、样本卡 hover 微抬、EntityCard 微抬对齐 -2px、空态四处归一（Library/Outline/编辑器未选章去 48px 灰 icon/TocPage 加饰符）。

**与设计稿的偏差（3 项）**：
1. **summary-card 未换 .card-compact 类**：现有规格（bg-canvas+radius-md+0.875rem padding）已属紧凑卡语义带宽内，换类会引起无收益的尺寸抖动——挂起。
2. **ChapterCard 未挂 hover 微抬**：它是「就地展开编辑」卡不是跳转卡，行内编辑时抬升会晃——设计挂点名单含它，施工裁定不挂（同款理由适用抽屉内静态卡）。
3. **CSS content 转义踩坑**：`'\2766'` 经 JSON→bash→Python 双层剥变成 `'¾6'`——改用 ❦ 字面字符（文件均 UTF-8，模板侧本就用字面）；顺手修复 TocPage 插入错位导致的孤儿 CSS 块（构建曾红，已复绿）。

**留待真机**：选「纸纹」背景后纸列/目录页/真相两卡的颗粒观感（5% 感知度目标）；❦+钉线在文风页五分区的密度观感；抽屉纸叠边在深色下的可辨度。

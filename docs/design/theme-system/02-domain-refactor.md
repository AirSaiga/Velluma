# 逐域重构方案（02 · 硬编码清剿与视觉归一施工单）

> 配套 01-theme-architecture.md。本文回答「哪个文件哪些值换成哪个 token」。
> 红线复述：编辑器 880px 列宽 / 幽灵 mark 语义（ghost-draft mark 的 class 名与节点结构）/ 书封内容色豁免 / 古地图画布豁免 / Leaflet 地图结构——一律不碰。

---

## 0. 全局替换映射总表（颜色族 → token）

| 现值族 | 出现处 | 替换为 |
|---|---|---|
| 薄荷族 `#34d399`/`#6ee7b7`/`#047857`/`#ecfdf5`/`#d1fae5`/`rgba(110,231,183,*)`/`rgba(20,46,38,*)`/`#059669`/`#065f46`/`#a7f3d0`/`#10b981` | GhostRepairedChip、GhostWashChip、SparkDock、state-pill、assist-toggle、ThinkingIndicator、ChapterBadges、ImportProgressTracker（emerald-600） | `--mint`/`--mint-ink`/`--mint-bg`/`--mint-line`（01 §2）；幽灵底色用 `--mint-soft` |
| 琥珀报告族 `#b45309`/`#fef3c7`/`#d97706`/`#f59e0b`/`#fcd34d`/`rgba(251,191,36,*)`/`rgba(251,146,60,*)` | InspectorPanel、GhostWarningsBar、ChapterBadges、style.css ghost-draft--amber、editor-find-match、entity-mention--asset、FileDropZone | 语义=警示 → `--warn`/`--warn-bg`；透明度底色用 `color-mix(in srgb, var(--warn) 15%, transparent)` |
| 朱砂三值 `#a63e2a`/`#c25a4a`/`#c2725a` | CanonSection、CanonTruthDetailDrawer、useCanon ZHU_COLOR、StorylineAxis、ChapterCard、SpinePanel、BeatCardDock（岔路）、WorldTimeline 朱点 | 文字/印章级 → `--cinnabar`；点状/岔路 → `--cinnabar-bright` |
| 真相三态 `#7c5faf`/`#5f7d5a` | EntityDetailDrawer chip、CanonSection 点 | `--truth-partial`/`--truth-open`（秘密档已=--cinnabar） |
| 伏笔紫 `#a855f7`/`rgba(168,85,247,*)`/`rgba(126,87,194,*)`（章节紫并入） | ArcBand、WorldTimeline 伏笔弧/章节片 | `--foreshadow` |
| 红绿结论 `#dc2626`/`#16a34a`/`rgba(220,38,38,*)` | InspectorPanel、InsightsView verdict、StyleFingerprintSection（#10b981/#ef4444 健康带/出界点）、Toast | `--danger`/`--ok`（bg 用对应 --*-bg） |
| indigo/red/violet 外来 tag 三套 | GhostWarningsBar | 按语义：警示→--warn 族、错误→--danger 族、信息→--info 族 |
| 蓝 mention `#93c5fd`/`rgba(96,165,250,.14)`、黄 mention `#fcd34d`/`rgba(251,191,36,.12)` | style.css entity-mention | 新 token `--mention-char:#1d4ed8`(浅)`/#93c5fd`(深)、`--mention-char-bg:color-mix(in srgb,var(--info) 14%,transparent)`；资产侧用 --warn 同构 |
| 冷紫 fallback `var(--accent-500-rgb,124,58,237)`、`var(--accent,#6366f1)` | ChapterTocDrawer/List、MarkdownImportModal、ExtractionPreviewPanel、InspectorPanel | `color-mix(in srgb, var(--accent-500) N%, transparent)` / 直接 `var(--accent-500)`，fallback 全删 |
| 灰系旧兜底 `#333`/`#999`/`#ddd`/`#6b7280`/`#f3f4f6`/`#475569` | LocationDetailDrawer、ReadBookModal、GhostWashChip is-kept、ReaderMirrorBoard | `--text-primary`/`--text-muted`/`--border-color`/`--bg-tertiary` 按角色对位 |
| 深色段硬编码 `rgba(30,32,37,.92)` 族 | SparkDock、BeatCardDock 深色段 | `--bg-elevated` + alpha 消费处自调 |
| 独立错误红 `#b0483c`（ExtractionModal）、#ffcccc/#ccffcc（diff） | extraction、RichTextEditor | `--danger` / `--diff-add-bg`·`--diff-del-bg` |

JS 色表裁决（01 §7 已拍）：`eventTemplates.ts` EVENT_TYPE_COLOR、`relationTypes.ts` 边色、`useCanon.ts` NODE/EDGE 色 = 古地图内容色**豁免恒定**，唯一改动 `ZHU_COLOR` 常量值改注释指向 `--cinnabar`（值不变 #a63e2a，浅深档差异由 CSS 消费侧承担，JS 恒取浅档值——地图画布恒亮，自洽）。

---

## 1. 写作台线（workspace / chapter-editor / generation）

### 1.1 幽灵三件套（改造收益最大的一批）

- **GhostRepairedChip**（~15 处薄荷）：全部换 `--mint-*` 四件。深色侧 `rgba(20,46,38,.55)`→`--mint-bg` 深档值；`:root.dark` 覆写段删除（token 自带双档）。
- **GhostWashChip**（~13 处）：同上；`is-kept` 的 `#f3f4f6/#6b7280` → `var(--bg-tertiary)`/`var(--text-muted)`；`.ghost-wash__span` `#065f46`→`--mint-ink`。
- **GhostWarningsBar**（~17 处琥珀+三套外来 tag）：琥珀族→`--warn`/`--warn-bg`；indigo/red/violet tag 按语义归 --info/--danger/--warn；**mark 的 class 名与 decoration 结构不动**（幽灵 mark 语义红线）。
- style.css 本体：`.ghost-draft--mint` 两值→`--mint-soft`+`box-shadow` 用 `color-mix(in srgb, var(--mint) 12%, transparent)`；`.ghost-draft--amber` → `color-mix(in srgb, var(--warn) 15%, transparent)` 同构；`.state-pill`/`.assist-toggle` 的 `#34d399`→`--mint`；`::selection` 的 `rgba(124,106,173,.25)`→`color-mix(in srgb, var(--accent-500) 25%, transparent)`；`.btn-primary:hover` 阴影同法；`.card-hover` 阴影→`--shadow-md`；`.editor-find-match` 两档琥珀→新 token `--find-match:color-mix(in srgb, var(--warn) 22%, transparent)` / `--find-match-active:color-mix(in srgb, var(--warn) 42%, transparent)`（:root 定义，主题自动跟随——color-mix 以 token 为输入即主题安全）；outline-note 三处薄荷 fallback 删除（:369/:425/:451）；`.inspector-drawer`/`.toc-drawer` 投影 `rgba(0,0,0,.45)`→`--shadow-lg` 语义化（值并入 token 消费）。

### 1.2 InspectorPanel（~22 处 + 裸字号 40 处）

- amber 报告族→--warn 族；红绿结论→--danger/--ok；`var(--accent,#6366f1)`→`var(--accent-500)`。
- 裸字号 40 处逐档归 --text-xs/sm/base/md/lg；9-11px 一律提到 --text-xs（ChapterBadges 9px 同批处理）。
- 不改面板骨架/分区结构（08/09 期布局红线）。

### 1.3 SparkDock / BeatCardDock / ThinkingIndicator

- SparkDock ~16 处：薄荷族→--mint 族；深色段 `rgba(30,32,37,.92)`→`color-mix(in srgb, var(--bg-elevated) 92%, transparent)`。
- BeatCardDock ~12 处：岔路朱 #c2725a→`--cinnabar-bright`；深色段同上；10/10.5/11px 字号提 12px。
- ThinkingIndicator：薄荷脉冲点→`--mint`；z 89→`--z-pop`。
- InlineDockHost/CursorLayer/PerceptionBand 已是正规军，只把 color-mix 输入从字面色换 token（如有残留）。

### 1.4 ChapterTocDrawer / ChapterTocList

- `--accent-500-rgb` bug 两处→color-mix；其余已是 token。

### 1.5 RichTextEditor（17 行 palette 类 + JS diff 色）

- 选区工具条 emerald/rose/amber 类→语义 token（ emerald=收样本→--mint 族？不——「黄金片段」是正向动作，用 accent；「这不像我」=负面→--danger 族；「AI 润色」=accent）。裁决：工具条按钮全部中性化（--text-secondary/--hover-bg），只保留图标语义色：💛 用 --gold（恒定签名，呼应「金」）、⚠ 用 --warn。
- diff 色：extensions 里写 mark style 的 `#ccffcc/#ffcccc`→ class `.diff-add`/`.diff-del`，style.css 新增两枚 token 消费（01 §9-8）。**不动 mark 的其他属性与导出契约**（stripGhostDraftHtml 白名单加 class 放行——施工时查 strip 实现确认 class 不被剥）。
- Tailwind palette 类清除后，config 映射（01 §8）兜底剩余 ink/parchment/accent 类。

### 1.6 PublishModal / ShortcutsCheatsheet / ConfirmDialog / InspirationModal

- 四件全部**收编 ModalShell**（壳：Teleport+焦点陷阱+Esc 栈+token 投影）。
- PublishModal：green/blue 冷色板→发布成功主按钮 accent、次要 --text-secondary。
- ShortcutsCheatsheet：gray+dark: 补丁→全 token（--bg-elevated/--text-*/--border-color），dark: 行全删。
- ConfirmDialog：parchment 静态类+dark:gray→token；danger 确认钮→--danger。
- InspirationModal：四类 chip amber/rose/emerald/blue-100→四类映射 --warn-bg/--danger-bg/--mint-bg/--info-bg（文字配 --warn/--danger/--mint-ink/--info），dark 适配自动获得。

---

## 2. 世界页线（豁免之外的清剿单）

- **三容器装饰体系豁免**（WorldMap/WorldTimeline/WorldView 的羊皮/鎏金/暖墨/印章/罗盘/书签/针脚/暗角/滤镜）——本期一行不动。组件头部注释追认「灯下古地图」设计决定。
- **LocationDetailDrawer**（54 处灰系，最旧一层）：全量换 token——#333→--text-primary、#999→--text-muted、#ddd→--border-color、底--bg-secondary/elevated、hover--hover-bg；灰系旧兜底双写（`var(--x,#999)`）fallback 全删。
- **EntityDetailDrawer**：三态 chip #7c5faf/#a63e2a/#5f7d5a→--truth-partial/--cinnabar/--truth-open；衬线 font-family 字面栈→`var(--font-heading)`。
- **CanonTruthDetailDrawer / CanonSection**：朱砂 30 处→--cinnabar/--cinnabar-bright；`var(--font-serif)` 8 处在 01 P0 补定义后自动生效，本批只删多余 fallback。
- **ReaderMirrorBoard**：slate #475569→--text-secondary。
- **ReadBookModal**：收编 ModalShell + 14 处灰纸双写→token。
- **WorldTimeline/WorldView 的字面 serif 栈 5 处**→`var(--font-heading)`（豁免的是颜色不是字体栈——字体栈换 token 后，极简主题下地图题字仍衬线？裁决：**古地图字体栈也恒定衬线**（地图是古籍），这 5 处改 `--font-heading` 会随主题变——与豁免冲突。改法：新增恒定 token `--font-atlas:'Noto Serif SC','Source Han Serif SC',STSong,SimSun,serif`，5 处字面值→var(--font-atlas)。）
- **blankAtlas.ts / 罗盘 / ArcBand JS 色点**：豁免恒定，不改生成脚本。
- WorldContextCard z 90→`--z-pop`；QuickEventNote z 95/96→`--z-modal`（它是 Teleport 模态草稿）。

---

## 3. 书架 / 大纲 / 文风 / 数据线

- **LibraryView**：书封六色板+几何母题+材质渐变=豁免（内容色）；真问题=封面 icon-btn 纸白系 5 处→`color-mix(in srgb, var(--paper-bg) 88%, transparent)` + --text-secondary。页面标题 1.5rem 保留 --text-3xl（门面 hero 例外，01 §6 之外的全站规则见 §5）。
- **OutlineView**：容器 0 裸值保持；StorylineAxis 朱点 #c25a4a→--cinnabar-bright、ChapterCard chip #a63e2a→--cinnabar。
- **StyleView + 10 组件**：唯二 SVG 裸值（ReconciliationSection:241 健康带 #10b981→`var(--ok)`、:253 出界点 #ef4444→`var(--danger)`）；StyleFingerprintSection 渐变已是 token 范本，不动。
- **InsightsView**：verdict 第二套 #16a34a/#d97706/rgba(220,38,38)→--ok/--warn/--danger；衬线大数字保留并升格为约定（01 §4.1）。
- **usageChart.ts**：纯几何零色，不动。

---

## 4. 导入 / 抽取线（Tailwind 散兵整编）

- **MarkdownImportModal / ExtractionModal**：收编 ModalShell；step-dot 与勾选卡的 `--accent-500-rgb` bug→color-mix；ExtractionModal 独立红 #b0483c→--danger。
- **ExtractionPreviewPanel**：5 处 --accent-500-rgb→color-mix；勾选卡选中态统一 accent 描边+`color-mix(in srgb,var(--accent-500) 8%, transparent)` 底。
- **ImportProgressTracker**：emerald-600 成体系→--mint 族（进度=AI 干活中，语义正合）。
- **FileDropZone / ImportPreviewTable**：amber/red 裸值→--warn/--danger 族。
- **Import-markdown 与 extraction 的 Tailwind palette 类**：全部替换为 token 后，这两域回到「只允许消费 token」纪律内。

---

## 5. 共享层归一

- **ModalShell 收编清单**：MarkdownImportModal、ExtractionModal、InspirationModal、ConfirmDialog、ShortcutsCheatsheet、PublishModal、QuickEventNote、ReadBookModal。ModalShell 自身 2 裸值（遮罩/投影）→ `--shadow-lg` + 遮罩 token `--overlay-bg:rgba(20,16,10,.38)`（浅）/`rgba(0,0,0,.55)`（深），:root 定义。
- **Toast**：success 现走 accent 保留；error/warning/info 的 rose/amber/blue 静态→--danger/--warn/--info 族。
- **z-index 归表**：QuickEventNote 95/96→--z-modal、BeatCardDock 90→--z-dock 带内 55、ThinkingIndicator 89→--z-pop 带内 65、WorldContextCard 90→--z-pop 65、Tailwind z-50→--z-dock、z-[110]→--z-modal；其余 grep `z-index:\s*\d` 复核。
- **页面标题/padding 归一**：页面标题统一 `font: var(--font-heading) var(--text-2xl)` + letter-spacing 0.08em（书架 hero 例外 --text-3xl）；页 padding 统一 `--space-8 var(--space-10)`（垂直/水平），大纲/数据两页的 1.5/2 套改为同一值。
- **章节分隔符**：全站统一 `❦`（现 *, ——, · 混用处收编）。
- **AppShell**：路由过渡不动；`useTheme`→`useAppearance` 切换（01 §1.2）。

---

## 6. 对拍与既有测试的保护

- `contextBlockFormat.test.ts` 保字不变式：AI 视角块正文渲染**零改动**（本工程不碰 ContextPreviewSection 的文本管道）。
- `extensions/__tests__`（chineseTypography/editorFind/foreignStyles 34 项）：find-match 的 class 名 `.editor-find-match`/`--active` 不变，只改色值来源。
- `ghostReap.test.ts`/heartbeatSeam：幽灵 mark class 名与节点结构不变。
- 视觉回归肉眼检查点：幽灵三态（mint/amber/repaired）、朱点闪朱、时间轴游标鎏金、地图印章、书封六色、目录抽屉选中态——每批施工后按 03 的验收清单走查。

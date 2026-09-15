# 前端视觉现状全量盘点（主题化重设计输入）

> 2026-09-15 四路并行只读扫描汇总（写作台线 / 世界页线 / 书架·文风·数据线 / 共享层+横切审计）。
> 用途：作为「小说化视觉 + 多主题系统」再设计的唯一事实输入。行号为当日实况，会漂移。

---

## 0. 一句话结论

Velluma 前端 = **同一暖纸宇宙里的三套子语言 + 一群旧世代散兵**：写作台暖纸系（token 化正规军）、世界页古地图羊皮纸系（自成一体、装饰色全绕过 token）、文风页现代仪表盘系（最年轻最守纪律）；外加 import/extraction 手写 modal、幽灵三件套、InspectorPanel 等硬编码重灾区。全仓约 **530 行硬编码 hex + 393 行 rgba + 87 行 Tailwind 静态色板类**，主题机制只有浅/深两档且**应用内无切换开关、无防闪烁**。

---

## 1. 主题机制现状（扩展点与阻碍）

### 1.1 现状机制
- `useTheme.ts`：模块级 `ref('light')`；`setTheme` = documentElement 挂/摘 `dark` class + localStorage `velluma_theme`；`initTheme` 无存储时跟随 `prefers-color-scheme`。
- **全库没有任何 UI 调 setTheme——应用内不存在明暗切换开关**，深色只能随系统。
- `index.html` 无预置主题脚本（主题 class 在 AppShell onMounted 才挂）→ 深色用户首帧白闪。对比：`main.ts:8-12` 已有 editor-typography 启动补 class 防闪先例。
- token 层：`style.css` `:root` 定义全部 token；`:root.dark`（:130-173）只覆写颜色类 token，几何 token（字阶/间距/圆角/z 表）主题无关。
- Tailwind `darkMode: 'class'`；`tailwind.config.js` 扩展了 **ink（暖灰）/ parchment（纸）/ accent（靛紫）/ primary（天蓝，疑似遗留）** 四套**静态 hex** 色板——用这些类的组件不跟随 CSS 变量轨。

### 1.2 「class + localStorage + token 覆写」完整先例
「实验：编辑器排版」开关（AppSettingsModal.vue:312-327, 768-787）：localStorage `velluma:editor-typography` + `documentElement.classList.toggle('editor-type-large')` + style.css:124-127 只覆写两枚 token。即时生效、不走「保存设置」按钮。**主题系统可照抄此链路。**

### 1.3 设置持久化键清单（velluma 系）
`velluma_theme`、`velluma_ui_prefs_v1`、`velluma_api_config`、`velluma_current_book_id`、`velluma:prefs:notify`、`velluma:editor-typography`、`velluma_ai_intent_mode`、`velluma:assist:enabled` 等。

### 1.4 扩展多主题（极简/柔和/专业/二次元…）+ 自定义背景的有利条件
1. useTheme 是唯一挂 class 的单点，扩为「主题 id 挂 data-theme + style.css 新增 token 覆写块」即可；几何 token 不用动。
2. 核心壳（AppShell/AppRail/PanelContainer/ModalShell/DrawerShell）与大部分页面 100% 消费 var(--*)，换 token 值即全局换肤。
3. color-mix 仅 35 处且几乎全以 token 为输入，自动随主题。
4. 图标体系 100% 主题安全：Icon.vue 自建 65 个内联 SVG path 字典，全部 `stroke="currentColor"`、零内联色（全库唯一 fill 硬编码=WorldView 指北针 1 处）。
5. 自定义背景有现成分层挂点：`--bg-primary`（桌面）/`--bg-canvas`（画布）/`--paper-bg`（纸面）三层；纸面视图统一吃 `--paper-bg`。

### 1.5 阻碍清单（需在设计中裁决）
1. **世界页+generation 两域约 375 行 hex + 183 行 rgba 的羊皮纸质感写死**（WorldMap 地图底纹 5 层渐变、WorldTimeline 鎏金系、罗盘/印章/燕尾书签）——是视觉主体，多主题下不会自动适配，需专项 token 化或明确豁免（如「古地图永远是古地图」）。
2. Tailwind 静态 palette + 87 行 palette 类 + 2 文件 dark: 补丁，与变量轨并存双轨（见 §4）。
3. box-shadow 118 处无 shadow token，新主题改阴影语言工作量集中。
4. 语义状态色八件套（--ok/--warn/--danger/--info ×前景背景）每个新主题需各配一套值。
5. `blankAtlas.ts` 是生成物（scripts/make_blank_atlas.py 产出 SVG 字符串，9 处内联色）——参数化需改生成脚本。
6. 深色现状：`:root.dark` 反色后世界页画布/时间轴带/暖纸浮层**保持亮色不变**（现状即「灯下古地图」，可能是无意幸运）——要不要为古地图配 dark token 需拍板。
7. 书封六色板 + 封面材质渐变（LibraryView）是**注释声明的设计决定**（封面=内容非 UI 表皮，双主题同面孔）——主题化应豁免。

---

## 2. 视觉语言版图（三套子语言 + 散兵）

| 子语言 | 载体 | 特征 | token 纪律 |
|---|---|---|---|
| **暖纸写作台系** | workspace/chapter-editor/generation + 全局壳 | 暖纸底 #f7f4ed、靛紫 accent #7c6aad、衬线标题、纸面唯一承载面 | 正规军：EditorFindBar/TocPage/WorkspaceView/AssistRail 零硬编码 |
| **古地图羊皮纸系** | world 三容器 + 抽屉族 | 羊皮画布 #e7d7b6 五层做旧、暖墨 rgba(110,85,45)、鎏金 #b08d3e、黄铜渐变、朱砂 #a63e2a、烛光暗角、毛边墨迹 SVG 滤镜、印章/燕尾书签/信标针脚 | 自成一体，装饰色全绕过 token（WorldMap 132 处、WorldTimeline 88、WorldView 58） |
| **现代仪表盘系** | style 文风页（S5 最新） | 固定 header+sticky 状态条+anchor 导航+96rem 容器+双栏 duo+hairline 分区+container query | **全仓最好**：10 个 presentation 组件 8 个零硬编码 |
| **旧世代散兵** | import-markdown/extraction 手写 modal、ConfirmDialog、InspirationModal、ShortcutsCheatsheet、PublishModal、RichTextEditor 选区工具条 | Tailwind 静态色板类 + dark: 手工补丁；未走 ModalShell | 差：emerald/rose/amber/blue 原生类与暖纸系冲突 |

页面间不统一点：页面标题字号三档（书架 1.5rem / 大纲·数据 1.25rem / 文风 --text-xl）、页 padding 两套（2.5/2.75 vs 1.5/2）。

---

## 3. 全局 token 地基（style.css 958 行）

- 背景：--bg-primary/secondary/tertiary/canvas/panel + --paper-bg + --bg-elevated（浅暖纸 / 深灯下纸两套）。
- 文字：--text-primary/secondary/muted + --text-faint（纯装饰档）。
- accent：--accent-400/500/600（浅 #9685c2/#7c6aad/#6d5dab、深 #8b6de8/#a78bfa/#c4b5fd）+ --focus-ring。
- 语义八件套：--ok/--warn/--danger/--info × 前景/背景成对（浅深各一套）。
- 字阶八档 --text-xs~3xl（12px 底线）+ 行高三档 + 间距 4px 基栅 + 圆角六档 + z 表十档。
- 排版：--editor-max-width 880px（冻结）+ --editor-font-family（宋体族）/size/line-height + `.editor-type-large` 宽排档。
- 字体：--font-body（Inter/苹方系）、--font-heading（Noto Serif SC/思源宋/STSong/SimSun 衬线）。**零 webfont 加载，全靠系统字体**（Windows 实际命中 STSong/SimSun）。
- 纪律声明（style.css:42-45）：「新组件只允许消费 token；新增裸色值/裸字号=打回」——执行不均匀。
- style.css 自身残留：ghost-draft 薄荷/琥珀（:331-338）、find-match 琥珀、mention 蓝/黄、state-pill 薄荷 #34d399（:468-478，I-04 品牌豁免）、outline-note 段薄荷 fallback `var(--accent-500, #10b981)`（:369/425/451，**换主题前旧值未清**）、::selection rgba(124,106,173,.25)。

---

## 4. 横切面审计总表（frontend/src，排除测试）

| 维度 | 数量 | Top 文件 |
|---|---|---|
| 硬编码 hex | **530 行** | WorldMap 64、LocationDetailDrawer 42、WorldTimeline 28、InspectorPanel 27、GhostWarningsBar 22 |
| rgba/rgb | **393 行** | WorldMap 69、WorldTimeline 60、WorldView 44、LibraryView 26、SparkDock 12 |
| Tailwind 带色号类 | **87 行**（标准 palette+ink/parchment 49 行/7 文件；accent-* 20 行；white/black 18 行） | RichTextEditor 17、InspirationModal 11、ConfirmDialog 9 |
| gradient | **19 处** | LibraryView 4（封面材质）、WorldMap 6（羊皮底纹）、WorldTimeline 5（鎏金系）、StyleFingerprintSection 1（**token 化范本**） |
| box-shadow | **118 行**（无 shadow token） | WorldMap 21、WorldTimeline 14、WorldView 9 |
| color-mix | 35 处（31 处以 token 为输入=主题安全） | 集中在 style 页与 workspace |
| dark: 前缀 | 12 行/19 处/仅 2 文件（ConfirmDialog 7、ShortcutsCheatsheet 5） | 静态 palette+dark:gray 手工补丁双轨典型 |
| font-family 硬编码 | 字面 serif 栈 5 处（WorldTimeline:1219/WorldView:1772/WorldMap:2421,2916/EntityDetailDrawer:628） | — |
| z-index 层表外 | ≥8 处（30/89/90/95/96 + Tailwind z-50/z-[110]） | QuickEventNote 95/96、BeatCardDock 90、ThinkingIndicator 89、WorldContextCard 90 |
| 低于 12px 字号 | 大量（9/9.5/10/10.5/11px） | BeatCardDock 10/10.5/11、ChapterBadges 9px、GhostRepairedChip 9px |

**未定义 token 引用（真 bug）**：
- `var(--accent-500-rgb, 124,58,237)` —— `--accent-500-rgb` 全仓从未定义，fallback 是冷紫 #7c3aed ≠ 暖靛紫 #7c6aad，**实际渲染偏色**：ChapterTocDrawer:201、ChapterTocList:95、MarkdownImportModal:311、ExtractionPreviewPanel:343/345/357/410/411。
- `var(--font-serif, …)` 8 处（CanonSection:471/489、CanonTruthDetailDrawer:426/564/651/662/677/690）——未定义恒走 fallback。
- `var(--font-mono, monospace)`（ContextPreviewSection:701）——未定义。

---

## 5. 分域详情

### 5.1 写作台线（workspace/chapter-editor/generation）
- **正规军**（零或近零硬编码）：WorkspaceView、EditorFindBar（最纯正模板）、TocPage、AssistRail/ChapterSpine（样式全在全局段）、IgnitionCard、CursorLayer、InlineDockHost、PerceptionBand（**color-mix+局部变量 --k 派生法=全仓最佳实践**）、ContextPreviewSection（色彩层）、WorldSceneSlice（大部分）、style.css 08 期全局段。
- **重灾区**：
  - InspectorPanel（~22 处）：amber 报告族 #b45309/#fef3c7/#d97706/#f59e0b×12、红绿结论 #dc2626/#16a34a、出题 fallback `var(--accent, #6366f1)`（--accent 明明有定义）；裸字号约 40 处。
  - 幽灵三件套：GhostWarningsBar（~17 处琥珀+indigo/red/violet 三套外来 tag 色）、GhostRepairedChip（~15 处薄荷族）、GhostWashChip（~13 处薄荷族）——语义上正是 --warn/--ok 却零引用，**改造收益最大的一批**。
  - SparkDock（~16 处薄荷/深色段 rgba(30,32,37,.92)）、BeatCardDock（~12 处：岔路朱 #c2725a + 深色段硬编码）、ThinkingIndicator、ChapterTocDrawer/List（--accent-500-rgb bug）。
  - PublishModal（100% Tailwind：green/blue 冷色板）、ShortcutsCheatsheet（95% Tailwind gray+dark: 双轨）、RichTextEditor 选区工具条（emerald/rose/amber 色板类 + JS 层 diff 色 #ffcccc/#ccffcc 写进文档 mark）。
- 布局资产：纸列骨架（--drawer-pinned 推挤/880 冻结列宽）、inspector-drawer 380px、toc-drawer 320px 覆盖式。

### 5.2 世界页线（world）
- **三容器即审美核心**：
  - WorldView（2517 行）：书名水印题字（衬线 38px/0.22em 字距）、手绘罗盘 SVG（compass-sway 5.6s CSS 摆动）、胶囊工具条/右缘图标栏（暖纸 rgba(236,228,211,.92) 族）、金徽标 #b08d3e。
  - WorldMap（2932 行，**全仓最重 132 处**）：羊皮纸画布 #e7d7b6 + 5 层 CSS gradient 做旧 + 烛光暗角 multiply；地点三类环色 #7c6aad/#10b981/#60a5fa；在途青墨 #3f6f8f；核心角色金环 #c9a227 星芒旋转 14s；事件涟漪/行军虚线流动/存活呼吸全部 CSS keyframes；**事件印章**（不规则 border-radius+rotate(8deg)+印泥内阴影）；毛边滤镜 #wm-ink/#wm-ink-soft（SVG feDisplacementMap）。
  - WorldTimeline（1990 行，88 处）：**鎏金体系**（游标 #b08d3e 双层金晕、黄铜渐变 135deg #e6c87e→#8a6d2f、金墨微波柱、播放态金）；**燕尾书签** clip-path+drop-shadow；**信标针脚**虚线；章节紫 rgba(126,87,194)；伏笔紫 #a855f7；朱点揭示 #c25a4a；纪年翻页 rotateX+blur。
- 抽屉族：DrawerShell（最干净全 token）、EntityDetailDrawer（名字衬线+三态 chip #7c5faf/#a63e2a/#5f7d5a）、**LocationDetailDrawer（54 处灰系旧兜底 #333/#999/#ddd，最旧一层）**、CanonTruthDetailDrawer（朱砂贯穿 30 处、360px）、CanonSection（朱点视觉签名 .cs-mark+cs-fresh 闪朱 2.6s+衬线 var(--font-serif)——未定义 bug）、ReadBookModal（14 处旧灰纸双写兜底）、ReaderMirrorBoard（slate 残留 #475569）。
- engine 三张色表（JS 内联色，被 inline style 消费）：EVENT_TYPE_COLOR 11 色（eventTemplates.ts:114-125）、RELATION_TYPES 8 边色（relationTypes.ts:13-20）、NODE/EDGE_TYPE_COLORS 11 色 + ZHU_COLOR='#a63e2a'（useCanon.ts:184-217，**唯一被提取成常量的品牌色**）。
- blankAtlas.ts（生成物）：经纬网/海岸线/国界全内联 SVG attr 色 9 处。
- 内联色占比 ~9%（blankAtlas/罗盘/ArcBand/JS 色点/色表 ≈45-50 处），其余 90% 是 CSS 类内硬编码可批量 token 化；动效全 CSS 实现主题化友好。

### 5.3 书架/大纲/文风/数据/导入/抽取线
- **LibraryView**（~36 处但 ~28 处是声明豁免的书封内容色）：书封六色板 #34506b/#7a3e3e/#52466b/#3f5747/#75563a/#514c46 + 六种几何母题（arcs 同心弧/stripes 斜纹/dots 点阵/ridge 山脊/moon 圆月/grid 格栅），书名 hash 独立取色取母题，3:4 开本，径向柔光+经纬细纹+内衬描边+底部渐晕，衬线书名三档自适应字号，题材眉标 0.22em 字距——**全站辨识度核心**。真问题=封面 icon-btn 纸白系 5 处。
- **OutlineView**：唯一 0 裸值页面容器；StorylineAxis SVG 全 token 化唯二硬编码=朱点 #c25a4a（注释明示与 WorldTimeline 同值）；ChapterCard 朱砂 chip #a63e2a——**朱砂双值 #a63e2a/#c25a4a 待归一**。
- **StyleView + 10 组件**：三段式骨架（固定 header/anchor 胶囊导航/96rem 容器查询滚动列）+双栏 duo 5fr/7fr+hairline；8/10 组件零硬编码；唯二 SVG 裸值=健康带 #10b981/出界点 #ef4444（ReconciliationSection:241/253）；零状态 hero「贴一段你写过的字」衬线 1.875rem=全站最大衬线字；inbox-excerpt 样本摘录排衬线=「正文感」暗示。
- **InsightsView**：verdict 第二套绿/琥珀/红（#16a34a/#d97706/rgba(220,38,38)）与 token --ok/--warn/--danger 并存=「同一页两种绿」；衬线当数字展示字体（accent 紫衬线大数字）是孤立决定；usageChart.ts 纯几何零色，架构干净。
- **import-markdown/extraction**：手写 modal 不走 ModalShell；MarkdownImportModal step-dot / ExtractionPreviewPanel 勾选卡踩 --accent-500-rgb bug；ExtractionModal 独立错误红 #b0483c（三色系外）；ImportProgressTracker emerald-600 成体系；FileDropZone/ImportPreviewTable amber/red 裸值。

### 5.4 共享层
- AppShell：flex 行 = AppRail 3.5rem + router-view；路由过渡 fade 0.15s/0.1s（离开视图 absolute 防卡死）。
- AppRail：全 token，active=accent 文字+左缘 2px 指示条。
- ModalShell（Teleport+焦点陷阱+Esc 栈，全 token，仅遮罩/投影 2 裸值）、PanelContainer/PanelEmpty（良好）。
- ConfirmDialog（旧式 Tailwind+parchment 静态+dark:gray 补丁）、Toast（success 走 accent，error/warning/info 用 rose/amber/blue 静态）、InspirationModal（四类 chip amber/rose/emerald/blue-100 无 dark 适配）——三个待整编件。
- AppSettingsModal：720px 单列滚动卡，双模型卡 → 折叠区×3（向量记忆/deai/编辑器排版）→ misc-grid 两列 → footer。**「外观」分区自然落点**=「实验：编辑器排版」升级为常显区（主题+排版+背景聚拢），插在 deai 折叠区后、misc-grid 前；实现照 editor-typography 先例（即时生效+localStorage 设备键）。

---

## 6. 已品牌化、待升格全局 token 的色彩语义

| 语义 | 现值 | 分布 | 备注 |
|---|---|---|---|
| **薄荷 = AI 在场/幽灵** | #34d399 族 | ghost-draft 呼吸微光、state-pill、ThinkingIndicator、SparkDock、assist 点亮、GhostRepaired/WashChip | 事实品牌色，有 I-04 豁免先例，应升格 token |
| **朱砂 = 真相/朱批** | **#a63e2a 与 #c25a4a 双值** + #c2725a（岔路朱） | CanonSection/ZHU_COLOR/CanonTruthDetailDrawer/ChapterCard/StorylineAxis/WorldTimeline 朱点/SpinePanel/BeatCardDock | 应收敛为一枚 --cinnabar（岔路朱是否同源待裁决） |
| **鎏金/黄铜 = 此刻/编年** | #b08d3e/#8a6d2f/#e6c87e/#c9a227 | WorldTimeline 游标/播放/金墨柱、WorldView 金徽标、地图金环、ArcBand 回收金光 | 世界页专属语义，可升格 |
| **伏笔紫** | #a855f7 族 | ArcBand/WorldTimeline 伏笔弧 | **与全局 accent #7c6aad 是两种紫**，需裁决 |
| **暖墨 = 古地图线描** | rgba(110,85,45)/rgba(107,90,68) 族 | 经纬网/海岸线/浮层边框/水印/罗盘 | 世界页专属 |
| **羊皮纸底** | #e7d7b6 + #ecdfc3/#e5d4b0/#dcc8a0 | 地图画布 | 世界页专属 |
| **暖纸浮层族** | rgba(249,242,226)/rgba(236,228,211)/rgba(244,238,225) | 世界页浮层 20+ 次 | 世界页专属 |
| 三态真相色 | 半露 #7c5faf / 公开 #5f7d5a / 秘密 #a63e2a | 真相 chip/点 | 应随朱砂一并 token 化 |

---

## 7. 现有 bug 级视觉问题（重设计顺手修）

1. `--accent-500-rgb` 未定义 → 4+ 文件选中态恒渲染冷紫 violet-600（§4）。
2. `--font-serif`/`--font-mono` 未定义恒走 fallback（§4）。
3. 应用内无明暗切换开关；index.html 无 FOUC 防护。
4. z-index 层表外值 ≥8 处。
5. 9-11px 裸字号违反 12px 底线（BeatCardDock/ChapterBadges/GhostRepairedChip 等）。
6. 朱砂双值（#a63e2a/#c25a4a）；数据页 verdict 第二套语义色；LocationDetailDrawer 灰系旧兜底。
7. style.css outline-note 残留薄荷 fallback（换 accent 前旧值）。
8. RichTextEditor JS 层 diff 色 #ffcccc/#ccffcc 写进文档 mark（持久化污染）。

---

## 8. 「小说感」资产清单（重设计可放大复用）

1. **纸的三层**：--paper-bg 纸面唯一承载面纪律 + 纸张投影 0 8px 20px rgba(18,38,63,.06)（三处复用）+ 880px 冻结纸列。
2. **衬线体系**：--font-heading 用于书名/页面标题/hero/章题/统计大数字/AI 块散文行/叙事流意图行；编辑器宋体族+行高 2.0；样本摘录衬线=「正文感」。
3. **竖排**：desk-spine `writing-mode: vertical-rl` 左缘书签（最有「书」意象的一件）。
4. **朱点/朱批**：未读朱点、安全类朱点+光环、矛盾段左缘 3px 朱条、真相朱点、闪朱 cs-fresh。
5. **薄荷 = AI 在场**：呼吸微光/脉冲环/呼吸点。
6. **仪式感排印**：「目录」letter-spacing 0.3em、题材眉标 0.22em、页头章节号 0.08em、纪年翻页。
7. **书封几何母题系统**（六色×六母题 hash 派生）。
8. **虚线 = 未定/邀请**：幽灵书位/grow-teaser/btn-ghost/outline-note/悬空伏笔弧，跨页一致。
9. **古地图装饰**：羊皮做旧/烛光暗角/毛边滤镜/印章/燕尾书签/信标针脚/黄铜游标/罗盘。
10. **符号批注体系**：⚑ 锚点/⚡ 岔路/⊘○▸◆ 槽位/🪶 收编池。

---

## 9. 字体现状

零 webfont：--font-body（Inter/苹方/微软雅黑栈）、--font-heading（Noto Serif SC/思源宋/STSong/SimSun）、--editor-font-family（Songti/STSong/SimSun/Noto Serif…）。Windows 实际命中 STSong/SimSun。多主题若要不同字体性格（如二次元圆润、极简无衬线），需决策是否引入本地打包字体（Electron 离线可用性）。

---

## 10. 布局骨架速查（供重设计对照）

- AppShell = AppRail 3.5rem + 主区；路由 fade 过渡。
- 写作台 = 纸列 880px 居中 + 左缘书签/目录抽屉 320px + 右缘助手栏 44px/面板 380px（pinned 推挤 padding-right）+ 底部无栏。
- 世界页 = 全屏地图 + 底部时间轴带 64px 轨 + 右缘图标栏/抽屉 340px + 悬浮胶囊条。
- 书架 = 整页滚动 215px auto-fill 网格；大纲 = 60rem 章卡列；文风 = 96rem 容器查询双栏；数据 = 整页滚动+panel-tabs。
- 模态：ModalShell（新世代）vs 手写 overlay（import/extraction/Inspiration/QuickEventNote/世界页 ReadBook 等）。

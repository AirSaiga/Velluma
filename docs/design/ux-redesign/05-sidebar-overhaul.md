# 第 5 期：写作台侧栏形态重构（UX 重构 · 设计规格）

> 前置：第 0 期 `00-foundation.md`（token/层表/浮层规范继续消费，不另立）、第 3 期 `03-writing-desk.md`、第 4 期 `04-writing-desk-revamp.md`（其文案成果与状态丸/把手措辞全部继承；本期推翻其结构性条款处均显式标注「取代 xx 期 §x」）。
> 用户原话（本期边界的来源）：「这个侧边栏感觉也没变化呀，改动得幅度太小了，**我允许你完全重构的**。」
> 范围：`frontend/src/features/workspace/containers/WorkspaceView.vue`（布局重构主战场）、`containers/InspectorPanel.vue`（面板化改造）、`presentation/PerceptionBand.vue`（批注层重写）、`features/generation/presentation/SparkDock.vue`（迁光标层）、`features/generation/presentation/GhostWarningsBar.vue / GhostWashChip.vue / GhostRepairedChip.vue`（随幽灵迁移）、`features/workspace/composables/usePerceptionAlignment.ts`（适配，算法不动）、`composables/useUiPrefs.ts`（新键）、`style.css`（.nle-topbar / .drawer-edge / .inspector-drawer 段重写）。
>
> **仍然冻结的红线（复述任务边界，本文任何条款不得触碰）**：`computeCursorDockPos()` 公式（useSparkDock.ts:141-155）与 880px 正文列的关系；感知锚定算法本体（`.canon-mark` 视口 Y 查询 / `stackAnchoredTops` 碰撞避让 / RESERVED_FLOOR——topReserve 的**测量对象**按 §3.4 适配，测量机制不变）；TipTap mark 类名；七键契约（Space/Ctrl+Space/Tab/Esc/Alt+N/Alt+O/Ctrl+Enter）；心跳/幽灵草稿/细纲胶囊机制；SSE 帧与 GHOST_* 字段；dock 零件缓存签名输入；四槽位语义与排序；placeFloating / Esc 栈 / ModalShell（00 期 §4，只消费不改签名）。

---

## 0. 本期定位：从「四条竖带」到「一张纸，两只手」

### 0.1 为什么第 4 期「看起来没变」（诊断，设计依据）

04 期在「骨架不动」边界内施工，写作台的几何现实因此原样保留——**纸列被四条竖带夹着**：

```
施工前（=施工后）1093px 视口实测链：
[AppRail 56] [binder 章节列表 ~207] [感知带 260/折叠 36] [880 纸列] [抽屉 380 覆盖/推挤]
             └──── 左两条相邻灰底带，视觉上连成「一个大侧栏」 ────┘
```

- **binder 是低频工具常驻 20% 宽度**：切章是秒级动作，章节列表却永久占据屏幕五分之一（WorkspaceView.vue:792-887）。
- **感知带与 binder 相邻**，两者都是灰底条纹（`--bg-secondary` 系），作者眼里它们是「同一个侧边栏」——04 期把带内徽标改成数字徽章、header 改「提醒」，都发生在这条带的**内部**，隔着一层玻璃改动，自然无感。
- **右抽屉默认隐身**（12px 触发条 + 把手，style.css:553-589），其内容（此刻/收件箱）在写中最需要时不可见；四 tab 条又把 380px 切成四个要记忆的格子。
- 结论：04 期的边界把改动限制在「皮肤与语言」，而用户要的是**形态**。本期形态级重构的每一刀都砍在「竖带」本身。

### 0.2 总概念

**纸面是唯一永久居民。** 其余一切按「作者要不要一直看到它」分三层形态：

| 层 | 形态 | 装什么 |
|---|---|---|
| **栏（rail）** | 常驻、≤44px、纯图标+徽章、无文字 | 左：书脊（章节导航入口）；右：助手图标栏（三面板+AI 视角入口） |
| **抽屉（sheet）** | 召唤式浮出（点击/hover 延迟/Esc/外点收） | 左：章节目录；右：打算/此刻/检查/AI 视角四面板的展开态 |
| **批注（margin notes）** | 无栏体浮卡，锚定正文行，永远在屏 | 感知提醒卡 + 打算进度便签（原感知带内容，去栏体化） |

```
本期施工后：
[AppRail 56] [书脊 44] [批注层 244(窄档=24 批注轨)] [880 纸列] [图标栏 44]
              └ 点击滑出目录 288(overlay)            └ 点击滑出面板 400(overlay/pin 推挤)
```

写前规划→写中感知→写后检查的动线因此显性化：**打算/此刻/检查三个图标按动线时序排在右栏，写中感知批注守在纸边，章节导航收成一根书脊**。

### 0.3 与 03/04 期的关系

03 期是「边栏收敛」保守期、04 期是「骨架不动」皮肤期；本期是用户授权后的结构期。04 期全部文案成果（§4 替换表 24 张）、状态丸、AI 辅助带字开关、点火卡扉页、空态 hero、把手措辞——**逐字保留**；04 期 §8 否决 1（SparkDock 不挪光标）**经用户授权推翻**，理由见 §4.1。

---

## 1. 左栏重构：书脊 + 目录抽屉（取代常驻 binder）

### 1.1 重构前后对照

| | 前（现状） | 后（本期） |
|---|---|---|
| 形态 | 常驻 20% 灰底栏（min 14%/max 32% 可拖），与感知带连成一条大侧栏 | 44px「书脊」常驻 + 点击滑出 288px 目录抽屉（overlay） |
| 章节切换 | 列表常驻，单击行 | 相邻章：书脊 ‹ › 一键翻页（更快）；任意章：章号→抽屉→单击（多一步，低频） |
| 动作入口 | 底部三钮（新建/导入/提取设定）常驻 | 新建在书脊底部 ＋；导入/提取收进目录抽屉底区 |
| 多选删除 | 栏顶切换多选模式 | 目录抽屉内同功能迁移，零删减 |
| 布局 | splitpanes 两窗格 + sizes 持久化 | **splitpanes 退役**，工作区根改 flex 行 |

### 1.2 书脊（`.book-spine`，44px 常驻列）

工作区根布局改为 flex 行：`[.book-spine 44px][.editor-pane flex:1][.assistant-rail 44px]`，外覆 `.workspace-view`（isolation 已有页面根约定不变）。

自上而下（全部 icon 钮，命中 ≥36×36，图标 15px）：

1. **返回书架**（arrow-left，title「返回书架」）；
2. 弹性间隔；
3. **上一章 ‹**（chevron-up，title「上一章」；无上一章时禁用态 40%）；
4. **章号钮**（纵向两行：大行 `12` tabular-nums `--text-md` 半粗，小行 `/34` `--text-xs` muted；title「章节目录（第 12 章，共 34 章）」；**点击 = 开/关目录抽屉**；抽屉开时钮呈 active 底色）；
5. **下一章 ›**（chevron-down）；
6. 弹性间隔；
7. **＋ 新建章节**（plus，title「新建章节」）。

样式：底 `var(--bg-secondary)`、右缘 1px `var(--border-color)`；与 AppRail（56px，`--bg-tertiary` 系）色阶区分开，两条栏不糊成一条。未选章时章号大行显示「—」仍可点开目录。

上一章/下一章按 `sortedChapters` 序切换（store 既有顺序），点击即 `store.selectChapter`——切章全链路（auto-read 发枪/草稿恢复/幽灵中止）零改动继承。

### 1.3 目录抽屉（`.chapter-dir`，overlay 288px）

- **位置与层**：fixed，left=56+44=100px（贴书脊右缘），top/bottom 0，宽 288px，z `var(--z-drawer)`（85）；底 `var(--bg-secondary)`，右缘投影复用原 `.inspector-drawer` 的 `box-shadow` 值（方向镜像）。
- **内容 = 原 binder 全量迁移，零功能删减**：书头衔行（书名 + 多选切换钮）→ 多选全选栏（selectMode 时）→ 章节列表（行=序号+题名+ChapterBadges+删除钮，样式全继承）→ 底区三钮（新建章节/导入 .md/提取设定）。`.ch-delete` 的 24px/reveal-on-hover/45% 规则原样。
- **关闭路径（四条，任一）**：再点书脊章号钮；Esc（**入 Esc 栈**，00 期 §4.2）；点击抽屉外（外点关闭，遮罩免设——监听 pointerdown 判定在抽屉与书脊外即收）；**选中一章后自动收**（意图已达成；多选模式下选章不收）。
- **pin 成常驻列**：抽屉头右侧一枚 pin 钮——钉住后转为 in-flow 240px 列（书脊右侧、编辑器左侧），供「章节列表常开」的作者；状态持久化 `uiPrefs.chapterDirPinned`（新键，布尔，缺省 false）。pin 态下点书脊章号=收起该列。in-flow 过渡 `width .22s ease`（与右面板同速）。
- **空目录**（零章节）：列表区位显示一行 hint「还没有章节——点下方新建」（`--text-sm` muted）。
- **splitpanes 退役连带**：`splitSizes` 偏好键**停止消费、冻结只读**（loadUiPrefs 容错读取不受影响；存量用户拖拽过的宽度作废，属有意变化，入 B-01）。`onResize` 容错处理器随 splitpanes 一并删除。

---

## 2. 中栏左缘重构：页边批注层（感知带去栏体化）

### 2.1 重构前后对照

| | 前（现状） | 后（本期） |
|---|---|---|
| 形态 | 260px 常驻列：底色+border 条纹，与 binder 视觉连体 | **无栏体**：无底色无边框，批注卡浮于纸左缘 244px 预留区，卡右缘 leader tick（12px 细线）指向正文行 |
| 窄视口 | 36px 折叠条，hover/focus/band-force 三触发展开（覆态 260px） | **批注轨**：24px 细轨，圆点守在各自锚定行高，点击弹卡（popover） |
| 带内固定区 | header「提醒」+spine 进度行+SparkDock 舱（topReserve 避让源） | 顶部只剩**打算便签**一张卡；SparkDock 迁光标层（§4），topReserve 测量对象随之改（§3.4） |
| 兜底区 | 底部渐变浮区「其他提醒」 | 同位保留，去渐变底改 hairline 分隔 |
| 折叠指示 | 数字徽章（04 期 §2.5） | 退役——批注轨圆点本身即指示（且守行高，信息量更大） |

### 2.2 几何（容器查询两档 + 继承一档；取代 03 期 §2.2 三档判据）

`.editor-host`（deskhost 容器，WorkspaceView.vue:1420-1430）继续挂 `container-type`；**判档重定**：

| deskhost 宽 | 行为 |
|---|---|
| ≥ 64rem（1024px） | **批注展开档**：editor-host `padding-left: 244px`（批注区入布局，纸列在余宽内居中），批注层 absolute 占左区（left:0 / width:244px / 全高） |
| 48–64rem | **批注轨档**：无预留区（padding-left:0），批注层塌为 24px 细轨 absolute 覆于左缘，圆点守行高（§2.4） |
| < 48rem | 批注轨 20px；**叠加** 03 期 §2.2-C padding 让位原样继承（ProseMirror/page-head 水平 padding 3rem→1.5rem，该 @container 块不动） |

**几何锚（验收 S2-06 引用）**：

- 1093px 视口（1366@125%）：editor-pane = 1093 − 56(AppRail) − 44(书脊) − 44(图标栏) = 949px ≈ 59.3rem → **批注轨档**；纸列全宽 949，文本列 ≈ 853px（px-12 内边距内）≈ 53 字/行——对比现状同视口 698px（44 字/行），**纸面 +22%**；
- 1280px 视口：pane = 1136px ≈ 71rem → **展开档**；纸列 = 1136 − 244 = 892 → editor-main 触 60rem 上限，文本列 768px 满额（现状同视口 623px，**+23%**）；
- 1600px+：展开档，纸列 880 居中，批注区 244 居左，右侧自然留白；
- 双 pin 极端（目录 240 + 面板 400 同开 @1093）：pane 剩 ~265px，允许纸列变窄（作者自选全开的极端态，不布局错乱即可，不为此优化）。

⚠ 实现注意：现状 03 期按「dockhost ≥56rem 常展」设计在 1093 落入折叠档；本期 64rem 门槛使 1280 起即展开——1093 落批注轨档是**有意的**（圆点守行高保位置信息，点击弹卡保内容可达，纸面宽度优先）。

### 2.3 展开档：批注卡规格

- 卡宽 232px（244 区 − 12 tick 位）；结构=现状 hint-card（图标+label+kind tag+×+detail 行）**逐行保留**，仅容器重构：
  - 去栏体：层本身无 background/border；卡底 `var(--bg-elevated)`（浮层语义），边框 `1px var(--border-color)`，投影 `0 2px 10px rgba(0,0,0,.08)`（浅色）/ 深色侧 `0 4px 14px rgba(0,0,0,.35)`；
  - **leader tick**：卡 `::after` 伪元素——卡右缘向右伸 12px、高 1px、`var(--border-color)`，垂直居卡首行——视觉指向锚定行（装饰，纯 CSS）；
  - kind 五族色（03 期 §4.2 token 派生方案）原样继承；
  - × dismiss：24px 命中/hover+focus-within 显形（03 §4.1）原样。
- **打算便签**（原 spine 进度行，PerceptionBand.vue:147-168）：重排为批注层顶部第一张卡（static 流内，top 8px）——意图行+旗标+可点折叠清单全部保留，卡片化（同批注卡底/边/影）。无 spine 时缺席。
- **兜底区**：层底部（bottom:0 / max-height 55% / overflow-y auto），hairline 顶部分隔 +「其他提醒」小字（去等宽大写——04 期 §2.5 已定常规体，此处对齐），折叠逻辑（COLLAPSE_AT=4 / +N 更多）不动。
- **空态**「写到相关角色 / 伏笔时，这里会浮现提醒」保留，改排在层顶部（便签位）。
- 层根 `pointer-events:none`，卡与便签 `pointer-events:auto`（沿用现状锚定层模式）。

### 2.4 批注轨档：圆点守位 + 点击弹卡（取代 03 期 §2.3 折叠条三触发 + 04 期 §2.5 徽章）

- **轨**：24px 宽（<48rem 时 20px）、全高、absolute left:0，z `var(--z-dock)`（50），无底色（dots 自带可读性；轨本体透明避免再造条纹）。
- **圆点**：每条 suggestion 一枚，8px 圆（安全类 leak/contradiction 10px + `var(--danger)`——04 期安全提权语义继承），kind 五色同卡片族；**纵向位置 = 该条锚定 Y**（stackAnchoredTops 输出按点半径 clamp 进轨内）——「哪一行有提醒」在折叠态仍然可读，这是比 36px 条数字徽章更优的折叠语义。找不到锚定的（orphan）圆点沉轨底 hairline 下方成组。
- **点击圆点 → 弹卡**：该条 hint 的完整卡片以 popover 弹出——`placeFloating`（点锚=圆点 rect 中心，`prefer:'below'`、`flip:true`、`align:'start'`、`gap:6`、`margin:8`），fixed 层 z `var(--z-pop)`（60）；卡片复用展开档同一渲染（施工时抽 `<HintCard>` 子组件，两处共用）。关闭：Esc（入栈）/外点/点另一圆点（替换）。
- **hover 展开手势退役**：03 期「hover 整条→260px 覆态展开」删除（窄档下不再有悬停展开的宽带；要读卡=点圆点，意图更明确）。`band-force`（dockActive 强制展开）同步退役——dock 迁光标层后「有零件时带自己回来」的对象不复存在（§4）。
- 轨上交互只有点击，无 hover 态内容，键盘可达：圆点是 button（tab 序可达，Enter 弹卡）。

### 2.5 PerceptionBand 组件重构纪律

- 文件保留（`presentation/PerceptionBand.vue`），内部重写；根类 `.perception-band` → `.note-layer`（旧类名样式段全删）。
- props：`suggestions` / `spineProgress` 不变；**`bandForce` prop 删除**（WorkspaceView 的 `bandDockActive` computed 一并删）。
- emits：`dismiss-hint` 不变（学着闭嘴链路零触碰；安全类白名单逻辑原样）。
- `kindMeta` / `cardHeight` / `located` / `floating` 计算全部保留复用。

---

## 3. 锚定机制适配方案（红线条款要求的专项说明）

**算法本体零改动**：`usePerceptionAlignment.ts` 的 `.canon-mark` 视口 Y 查询、`stackAnchoredTops` 下推避让、`RESERVED_FLOOR=40`、rAF 节流、滚动/文档变化监听——**函数级 diff 为零**。

适配只在「传参对象」三处：

### 3.1 bandEl 换指向
`bandEl` ref 从旧带体元素改指 `.note-layer` 根元素。层的 `getBoundingClientRect().top` 与旧带体同为 editor-host 顶缘（全高 absolute），`viewportY - bandRect.top` 的相对 Y 语义逐像素不变。

### 3.2 topReserve 测量对象迁移（SparkDock 迁走的连带）
现状：topReserve = dock slot 实高（ResizeObserver 测 `.band-dock-slot`，PerceptionBand.vue:79-97），避让「舱体盖卡」。
新态：批注层顶部固定物只剩**打算便签**一张卡——RO 改挂便签卡 wrapper，测法同一公式（`el.offsetTop + el.offsetHeight + 6`）；便签缺席时 reserve=0。测量机制（RO+nextTick 补测）逐行复用，只换 ref 目标。**SparkDock 舱体占 ~230px 顶部的避让场景整体消失**（舱迁光标层），展开档批注卡可用高度净增。

### 3.3 批注轨档的 anchors 消费
轨档下 anchors 照算（算法不感知档位）；圆点 top = anchors 值 clamp 到 `[8, 轨高-8]`；`stackAnchoredTops` 照常防叠（点半径当卡高参与下推）。档位切换（窗口 resize 跨 64rem）时层宽变化但 Y 语义不变，RO/resize 监听走既有重算路径。

### 3.4 行为变化声明
上述适配导致的有意变化：①顶部避让区从「舱体实高（0~230px 浮动）」变为「便签卡实高（0 或 ~40-120px）」——锚定卡整体上移更贴顶；②窄档从「隐藏整条带」变为「圆点守位」——折叠态信息量增加。均入行为变化清单（B-04/B-05/B-08）。

---

## 4. 光标层：SparkDock 与幽灵三条迁移（推翻 04 期 §8 否决 1）

### 4.1 为什么现在迁（设计论证）

04 期 §8 否决「SparkDock 挪光标」的两条理由本期重新过秤：①「topReserve/stash/sticky 全挂在带内上」——带体已解构（§2），「带内」这个家不复存在，dock 必须搬；不搬则批注层顶部永久挂一块 230px 固定区，topReserve 复杂度续命，且写中时作者眼睛在光标、卡在左栏顶——「少扭一次头」在形态重构期是主收益不是边角料；②「挪位=推翻 03 期重做」——本期授权正是重做。技术可行性已被 BeatCardDock 实证：`computeCursorDockPos`（**冻结，公式一字不动**）输出作 placeFloating 锚输入的消费模式（03 期 §3.2）原样套用；且 `useSparkDock` 模块**至今仍在算 `sparkDockPos` 并挂 `followEditorLayout`**（useSparkDock.ts:157-183——带内化后这对位逻辑是活着的冗余），迁回 fixed 浮层是**启用既有齿轮**而非新造。

**概念收益**：光标层从此是「写作动作层」唯一载体——提示卡（自动弹）、走向卡舱（Ctrl+Space）、幽灵三条（GHOST_DONE 后）都出现在光标旁；批注层只管「环境感知」。两层概念纯净：一个帮你写，一个帮你看。

### 4.2 SparkDock 迁移规格

- **容器**：Teleport 到 body，fixed，z `var(--z-dock)`（50）；宽 `min(360px, 80vw)`（碎片卡紧凑，比 BeatCardDock 的 420 窄一档）。
- **定位**：锚 = `computeCursorDockPos()` 输出换算 `{ x: p.left, y: p.top - 8 }`（把契约的 +8 还给 placeFloating gap，与 BeatCardDock :43 同款换算）→ `useFloatingLayer({ gap:8, margin:8, prefer:'below', flip:true, align:'start' })`；底缘不足上翻、右缘夹紧、maxHeight 内滚——03 期 §3.2 全套语义平移。
- **滚动/resize 跟随**：`followEditorLayout` 既有（:176-184），零新增。
- **内容零改动**：舱顶标题行「卡住了？点一个画面接着写」（04 §2.5）、两级层级 chip（主行画面/副行出处）、数字键 1~4、吸附意图栏、「多写几段 ▸」——逐像素保留；仅根容器从流内块改 fixed 浮层，宽度自适应内容到 360 上限。
- **状态机零改动**：sticky/stash/restore/打字隐藏/自动弹舱守卫/`_canShow` 门（useSparkDock.ts:70-135, 187-199, 243-261）全部不动——它们是可见性逻辑，与坐标无关。`v-if="visible && !ghostActive"`（SparkDock.vue:77）保留，光标层与幽灵天然互斥。
- **触发逻辑零改动**：停顿 4s 段尾心跳注入零件 + `showSparkDock()`（已内部调 `_positionDockAtCursor`——本来就是光标定位）；Tab 召唤路径不变。

### 4.3 幽灵三条（疑点条/洗层条/返修条）迁移规格

现状：三条 chip 挂在感知带 #dock 槽（WorkspaceView.vue:962-975），数据随 GHOST_DONE 灌入，而幽灵正文在光标处——提示与对象隔着一个栏宽。

- **新位**：光标层第二容器 `.ghost-chips`（Teleport body / fixed / z `var(--z-dock)`），三条按 疑点→返修→洗层 纵叠，gap 4px。
- **定位时机**：三条的数据全部在 **GHOST_DONE 帧**到达（SSE 流式打字完成后）——此时流式结束、光标静止于幽灵尾，**挂载即一次性取 `computeCursorDockPos()` 作锚**，`useFloatingLayer` 同款参数（below 优先/flip/clamp）；无跟随移动目标问题（流式进行中三条不存在，天然无抖动）。挂载后挂 `followEditorLayout` 防滚动漂移（复用现成工具）。
- **互斥天然成立**：`ghostActive` 时 SparkDock 自身隐藏（既有），幽灵蒸发/采纳 → 三条随 `ghostActive=false` 卸载——光标层任意时刻只有一主一辅。
- **内容零改动**：三条组件的文案/按钮（「用原稿」可逆学习、「还是贴出来」逃生舱）逐字保留（04 期表 F 成果）。
- **Esc 语义不变**：Esc 蒸发幽灵是编辑器 keymap（session 键位状态机），三条无独立 Esc——幽灵没，条即没。

### 4.4 回归清单（验收 S2-09/S2-10/S2-11 逐条过）

| # | 场景 | 预期 |
|---|---|---|
| C1 | 停顿 4s 段尾弹舱 | 舱在光标下 8px、左对齐文本块起（契约语义）；近视口底上翻；近右缘夹紧 |
| C2 | Tab 召唤 / 数字键 1~4 吸附 / 点击吸附 | 与现状一致 |
| C3 | 非 sticky 打字即隐藏；sticky 缝合后打字不收舱、连续吸附 | 与现状一致 |
| C4 | stash→幽灵→restore 回弹（Esc 收舱退 sticky） | 时序零变化（状态机未动） |
| C5 | 开舱滚动编辑器 / resize | 舱跟随（followEditorLayout 既有） |
| C6 | SparkDock 与 BeatCardDock 互斥（showBeatDock 先 hideSparkDock）；幽灵在屏时两舱皆隐 | 不变 |
| C7 | 03 期 §3.3 R1-R10（BeatCardDock 钳位十条） | 全重跑，零回归 |
| C8 | GHOST_DONE 后三条出现在幽灵尾下方，不遮幽灵正文；「用原稿」学习回流回归 | 新位生效 |
| C9 | 拒稿逃生舱（materializeRejectedGhost）后三条位置 | 同上 |
| C10 | 自动弹舱守卫（响应落地时作者须未动笔） | 不变（守卫在 assist 层，与坐标无关） |

---

## 5. 右栏重构：图标栏 + 面板（取代触发条 + 四 tab 抽屉；本期主对象）

### 5.1 重构前后对照

| | 前（现状） | 后（本期） |
|---|---|---|
| 发现入口 | 12px 右缘渐变条 + 24×48 把手（04 §2.4），静息 40% 透明 | **44px 常驻图标栏**：三主图标 + 底部 AI 视角，永远可见（世界页右缘图标栏同构） |
| 开合 | hover 整条=瞥看（overlay）；Ctrl+\=pin（padding-right 推挤） | **hover 图标 300ms=peek**（overlay 不推挤）；**点击图标=pin**（in-flow 列推挤）；Ctrl+\ 语义不变 |
| 内容组织 | 380px 抽屉内四 tab 条 + 副标题行 + 底部 AI 视角钮 | **面板制**：图标栏即「tab」，面板头=名称+副标题+pin/×；tab 条与 drawer-foot 退役 |
| tab 架构 | 打算/此刻/本章/检查（2026-08-22 重排冻结至今） | **三面板 + AI 视角**：打算/此刻/检查；**「本章」解散**（§5.4） |
| 宽度 | 380px / 44vw 冻结 | **400px / 44vw**（报告区呼吸；不分档——03 期 §6.4 推挤晃动论证仍成立） |
| 状态可见 | 无（抽屉关着什么都不知道） | **图标徽章**：此刻=收件箱点、检查=报告未读点、打算=建议待收点 |

### 5.2 图标栏（`.assistant-rail`，44px 常驻）

- 工作区根 flex 行最右列（in-flow，无 z 需求）；底 `var(--bg-secondary)`、左缘 1px `var(--border-color)`。
- 自上而下：打算（light-bulb）/ 此刻（map）/ 检查（check-circle）→ 弹性间隔 → 底部 AI 视角（magnifying-glass）。图标本名复用 Icon.vue 既有名。钮 36×36 命中、图标 15px；当前打开面板对应图标 active 底色（`--hover-bg` + `--accent-500` 字色）。
- **徽章**（8px 圆点，图标右上 2px 偏移；数据源全部既有，零新 API）：
  - 此刻：`session.adaptiveSuggestions` 含 `world_inbox` hint 时亮 `var(--ok)` 点（后端 >5 条才发该 hint——阈值语义继承）；开此刻面板即灭；
  - 检查：`finishReport` 到达且未开过检查面板时亮 `var(--accent-500)` 点；开面板即灭；
  - 打算：`chapterSpine.spineSuggestions` 非空（AI 帮你想的待收）时亮 `var(--accent-500)` 点；收下/不用后灭。
- **交互**：
  - `pointerenter` 起 300ms 未移出 → **peek**（面板以 overlay 滑出，fixed right:44px——贴栏左缘，z `var(--z-drawer)`，不推挤纸列）；移出图标且不在面板内 → 收（与旧 mouseleave 语义同族）；300ms 防抖免滑过误弹；
  - **点击 = pin**：面板转 in-flow 列（工作区根 flex 在图标栏左侧插入 400px 列，纸列被推挤——推挤由布局承担，删 `.workspace-view--drawer-pinned` 的 padding-right 机制）；再点同一图标 = 关闭；
  - **Ctrl+\**（契约不动）：关着 → pin 开上次面板（缺省按章节状态：空章=打算/有正文=此刻——现行默认 tab 逻辑上移复用）；peek 中 → 转 pin；pinned → 关闭。`rightDrawerOpen` uiPrefs 键语义平移为「面板 pin 态」（存量用户 pin 偏好无损继承）。
- `.drawer-edge` 12px 触发条与把手**删除**（style.css:553-589 段移除；`--z-edge` token 保留备将来用）——把手的历史使命（可发现性）由常驻栏彻底完成。旧「鼠标甩到右缘」肌肉记忆平滑继承：右缘现在就是图标栏，hover 即 peek。
- title：「打算（Ctrl+1）」「此刻（Ctrl+2）」「检查（Ctrl+3）」「AI 视角（Ctrl+4）」。

### 5.3 面板（`.assistant-panel`，400px / max-width 44vw）

- **peek 态**：fixed，right:44px，top/bottom 0，z `var(--z-drawer)`（85），底 `var(--bg-secondary)`，左缘投影复用原 `.inspector-drawer` 值。**pin 态**：同内容转 in-flow 列（`transition: width .22s ease`）。两态共用一个组件实例，只换定位壳——内容滚动/状态不因态切换重置。
- **面板头**（替代 tab 条 + 副标题行 + drawer-foot 三处）：左=面板名（`--text-lg` 半粗）+ 副标题（04 期表 G2 四条 + debug 条文案**逐字平移**，`--text-sm` muted）；右=pin 钮（peek 态显示，title「固定面板（Ctrl+\）」）+ × 关钮（24px 命中，title「收起」）。
- **内容区**：InspectorPanel 现有四 tab 内容组件**逐个原样嵌入**（SpinePanel/WorldSceneSlice/检查三组/AI 视角三件——零内容改动证明见验收 S2-15/S2-23）；`.tab-content` 的 16px padding 与滚动条样式平移。
- **InspectorPanel 改造纪律**：从「自管 activeTab 的抽屉」改为「受控面板内容宿主」——收 `panel` prop（'planning'|'now'|'review'|'debug'），删 tab-bar/tab-subtitle/drawer-foot 模板段与其样式；开态/pin 态/快捷键处理上移到 WorkspaceView（Ctrl+1~4 处理器**必须**上移——现状处理器在 InspectorPanel 内，抽屉关着即卸载，Ctrl+1~4 关态无效；上移后关着也能开，属行为改进，入 B-15）。各 tab 的 watch（报告/沉淀/诊断到达切 review——改为「到达 → 检查图标亮徽章 + peek 一次」，不再强切正在看的面板，§5.5）与 inboxAutoOpen 旗标消费模式保留。

### 5.4 「本章」tab 解散（内容迁移表，零丢弃）

| 现内容（InspectorPanel.vue:562-607） | 去向 | 理由 |
|---|---|---|
| 字数统计卡（:569-574） | **删** | 04 期 B-01 已把字数上移页头 meta 行常驻——重复信息 |
| 本章文风卡（特例徽标/改回全书/编辑跳转，:577-597） | **打算面板底部**（原组件段平移，标题「本章文风」保留） | 写前定调语义：打算=写什么，腔调=怎么写，同属写前配置 |
| 真相账本跳转卡（:600-606） | **此刻面板底部**（原组件段平移） | 真相=世界域内容，此刻=世界切片，同域相聚 |
| 04 期表 I 全部文案（本章专属/跟随全书文风等） | 随卡平移，**逐字保留** | 合格区不动纪律 |

动线收益：三主面板恰好是「写前（打算+腔调）→ 写中（此刻+世界）→ 写后（检查）」——tab 数从 4 减到 3+1，图标栏噪音下降。

### 5.5 自动滑出语义平移

- **完稿报告到达**（WorkspaceView.vue:461-469 现行 watch）：改为 检查图标亮徽章 + 检查面板 **peek 一次**（作者手动关过则不反复弹——`_drawerAutoOpened` 单次旗标语义平移）。**不再**在作者正看别的面板时强切内容（现行 activeTab='review' 强切，在面板制下等于整个抽屉换内容，侵扰感更强——改为徽章提示是降噪，入 B-16）。
- **收件箱直达**（toast「去确认」→ OPEN_INBOX_EVENT）：peek 开此刻面板（关着时）+ WorldSceneSlice 收件箱展开——`inboxAutoOpen` 旗标 + 挂载消费模式原样（面板关闭时 InspectorPanel 卸载的既有约束与补位逻辑不变）。

---

## 6. 顶栏与空态微调（继承面）

- `.nle-topbar` 删**抽屉钮**（:928-935——图标栏常驻后它是第三入口，冗余）；状态丸/AI 辅助带字开关/快捷键钮/打字淡出（04 期 §2.2/§2.3、03 期 §5.1）原样。`max-width: 880px` 居中不动。
- 快捷键速查（ShortcutsCheatsheet）：`Ctrl+1~4` 行文案改「切换助手面板：打算 / 此刻 / 检查 / AI 视角」，`Ctrl+5` 行删，`Ctrl+\` 行保留（04 表 R 其余行零 diff）。
- 空态（无选中章）：hero 不变；书脊章号「—」可点开目录（§1.2）即「左边选一章」的落点。

---

## 7. 双主题与 token 消费

**零新增 token。** 本期全部新表面消费既有 token：

| 表面 | 消费 |
|---|---|
| 书脊/图标栏 | `--bg-secondary` + `--border-color` + `--hover-bg` + `--text-muted/secondary` |
| 目录抽屉/面板 | `--bg-secondary` + `--border-color`；投影 rgba(0,0,0,.45) 字面值（复用原 `.inspector-drawer`，双主题均成立的既有先例） |
| 批注卡 | `--bg-elevated` + `--border-color` + kind 五族 color-mix（03 §4.2 派生式原样） |
| 徽章圆点 | `--ok` / `--accent-500` / `--danger`（安全类提权色） |
| 批注轨圆点 | kind 五色族（同卡片族） |

深色侧唯一新投影值（批注卡 `0 4px 14px rgba(0,0,0,.35)`）按 `:root.dark` 覆盖写法入组件 scoped，不立 token（一次性投影值，00 期 §2 白名单精神）。全部过渡动效受 00 期 §5.2 毯式规则瞬切。

---

## 8. 解冻条款清单（取代关系唯一权威）

| # | 旧条款 | 处置 |
|---|---|---|
| U1 | 00 期 §6.1「`.inspector-drawer` 宽 380px/44vw 冻结」 | 解冻 → 400px/44vw 面板（§5.3） |
| U2 | 00 期 §6.1「`.perception-band` 宽 260px 冻结」 | 解冻 → 批注层 244 区/24 轨两档（§2.2） |
| U3 | 03 期 §2.2 边栏收敛三档判据（56/48rem） | 取代 → 64/48rem 两档+继承档（§2.2） |
| U4 | 03 期 §2.3 折叠条三触发（hover/focus-within/band-force） | 取代 → 批注轨圆点+点击弹卡（§2.4） |
| U5 | 04 期 §2.5 折叠态数字徽章 | 取代 → 圆点守位（§2.4） |
| U6 | 03 期 §2.4 + 04 期 §2.4 右缘触发条 12px 与常驻把手 | 取代 → 44px 图标栏（§5.2） |
| U7 | 03 期 §6.1 + 04 期 §6「InspectorPanel 四 tab 架构/内容构成/默认切换冻结」 | 解冻 → 面板制 + 本章解散（§5.3/§5.4） |
| U8 | 03 期 §9「splitpanes 与 sizes 持久化不动」 | 解冻 → splitpanes 退役（§1.3） |
| U9 | 04 期 §8 否决 1「SparkDock 不挪光标」 | 推翻 → 迁光标层（§4） |
| U10 | 04 期 §2.3 顶栏抽屉钮 | 删（§6） |
| U11 | 03 期 §6.4「抽屉宽度不分档」 | **维持**（论证仍成立，宽仅 380→400 微调，非分档） |

---

## 9. 行为变化清单（唯一依据，清单外变化=事故）

| # | 变化 | 理由 | 风险 |
|---|---|---|---|
| B-01 | binder 常驻栏 → 书脊 44px + 目录抽屉；splitpanes 退役、splitSizes 停止消费 | §1；四条竖带减一 | **中**（布局结构变化；目录可 pin 回补常开需求） |
| B-02 | 书脊 ‹ › 翻章钮（上一章/下一章一键） | §1.2；相邻章切换提速 | 低 |
| B-03 | 目录抽屉：章号点击开、Esc/外点/选章后收、可 pin 240px 常驻（uiPrefs 新键） | §1.3 | 低 |
| B-04 | 感知带栏体（260px 条纹）→ 页边批注层（244 预留区、浮卡、leader tick、去底色边框） | §2；第二条竖带消失 | **中**（锚定 Y 语义不变，视觉形态全新） |
| B-05 | 窄档折叠从「36px hover 展开条」→「批注轨圆点守位」；hover 展开手势与 band-force 退役 | §2.4/§3.4 | **中高**（旧手势没了；替代=点圆点弹卡，信息量不小于旧展开） |
| B-06 | 批注轨圆点点击弹卡（placeFloating popover，Esc 入栈，键盘可达） | §2.4 | 中（新交互） |
| B-07 | SparkDock 带内 → 光标层（computeCursorDockPos 消费 + placeFloating 钳位；宽 min(360,80vw)） | §4；推翻 04 §8 否决 1 | **高**（本期最高风险项；回归清单 §4.4 C1-C10 兜底；状态机/触发/内容零改动是安全绳） |
| B-08 | topReserve 测量对象：dock slot → 打算便签卡（RO 机制不变）；锚定卡顶部避让区缩小 | §3.2 | 低 |
| B-09 | 幽灵三条（疑点/返修/洗层）带内 → 光标层幽灵尾下方 | §4.3 | 中（GHOST_DONE 后一次性定位，无流式抖动面） |
| B-10 | 右缘触发条+把手 → 44px 常驻图标栏 | §5.2 | 中 |
| B-11 | 抽屉四 tab 条+副标题行+drawer-foot → 面板制（面板头=名称+副标题+pin/×） | §5.3 | 低 |
| B-12 | 「本章」tab 解散：字数删（页头已有）、本章文风→打算底、真相跳转→此刻底 | §5.4 | 中（信息搬家非删除；迁移表零丢弃） |
| B-13 | 抽屉 380/44vw → 400/44vw；pinned 从 padding-right 推挤改 in-flow 列 | §5.3 | 低 |
| B-14 | hover 瞥看：整条边缘 hover → 图标 hover 300ms peek；点击=pin；Ctrl+\ 不变 | §5.2 | 低 |
| B-15 | Ctrl+1~5 → Ctrl+1~4（AI 视角 5→4；处理器上移 WorkspaceView，关着也能开） | §5.3 | 低 |
| B-16 | 完稿报告/沉淀/诊断到达：强切 tab → 检查图标徽章 + peek 一次 | §5.5 | 低（降噪改进） |
| B-17 | 顶栏删抽屉钮；速查表 Ctrl+1~4/Ctrl+5 行更新 | §6 | 低 |

**清单条数：17。高风险 1 项（B-07），中高 1 项（B-05）。**

---

## 10. 不动清单（冻结红线 + 本期豁免重申）

- `computeCursorDockPos()` 公式（useSparkDock.ts:141-155）——两个消费侧（SparkDock/ghost-chips）按 §4 换算叠加钳位，函数一字不动；
- 感知锚定算法本体（`.canon-mark` 查询/`stackAnchoredTops`/RESERVED_FLOOR/rAF 节流）——仅 bandEl 指向与 reserve 测量对象适配（§3）；
- `--editor-max-width: 880px` 与排版三 token、03 期 §7 实验开关；
- TipTap mark 类名（canon-mark/ghost-draft/outline-note 家族）；stripGhostDraftHtml 消费链；
- 七键契约（Space/Ctrl+Space/Tab/Esc/Alt+N/Alt+O/Ctrl+Enter）与其键位状态机；Esc 逐层语义（幽灵蒸发在编辑器 keymap，优先于一切栈内浮层）；
- 心跳三计时器/感知常驻 detach 语义/章节纪元守卫；幽灵草稿机制（含 reapGhostIfDead、蒸发理由 toast）；细纲胶囊机制；
- SSE 帧与 GHOST_* 字段、dock 零件缓存签名输入、四槽位语义与排序、后端零改动；
- SparkDock 可见性状态机（sticky/stash/restore/打字隐藏/自动弹舱守卫/_canShow 门）与**内容**（标题行/两级 chip/数字键/意图栏/burst 入口）；
- BeatCardDock 全部（03 期 §3.3 R1-R10 继承，本期只重跑不改）；
- 静音白名单消费与 dismiss 埋点（dismiss-hint 载荷不变）；
- 04 期全部文案成果（§4 替换表）与 §1.5 合格区——本期零字符串改动，例外仅三处：速查表 Ctrl+1~4/Ctrl+5 两行（§6）、顶栏删钮的 title 随之消失；
- 各面板**内容组件**（SpinePanel/WorldSceneSlice/检查三组/AI 视角三件/本章文风卡/真相跳转卡）的内部结构与文案——它们是「搬家」，不是重写；
- placeFloating/useFloatingLayer/useEscStack/ModalShell 接口签名（00 期 §4）；
- WorldContextCard/QuickEventNote/ThinkingIndicator/IgnitionCard 与页面头 meta 行（04 期 B-01 成果）。

---

## 11. 验收清单

> G = grep/脚本；M = 目检；I = 交互手测。证据本地留存不入库。编号 S2-xx。

- **S2-01【G】** `grep -rn "Splitpanes\|splitpanes" frontend/src/features/workspace/` 零命中；`splitSizes` 仅剩 uiPrefs 读取兼容，无布局消费方。
- **S2-02【G】** `grep -rn "drawer-edge\|perception-band\|band-force\|band-dots\|band-badge\|hint-floating\|tab-bar\|tab-subtitle\|drawer-foot" frontend/src/features/workspace/ frontend/src/style.css` 旧形态类名清零（`.inspector-drawer` 若改名则新旧均不残留孤儿样式段）。
- **S2-03【G】** 冻结 diff 零：`computeCursorDockPos` 函数体；`stackAnchoredTops` 函数体；canon-mark/ghost-draft/outline-note 类名串；七键 keymap 段；SSE 消费字段名。
- **S2-04【G】** 本期新/改样式段（书脊/目录/批注层/批注轨/图标栏/面板/光标层）无新增 token、无裸 hex（薄荷 #34d399 系品牌字面值与投影 rgba 黑按既有先例豁免）、无新裸 font-size 值。
- **S2-05【M】** 双主题巡查：书脊/目录/批注卡/批注轨/图标栏/面板/光标层 dock 与幽灵三条，深浅各一遍——无瞎眼色、无隐形字、徽章圆点两色可辨。
- **S2-06【M】** 几何锚三视口（§2.2）：1093px→批注轨档+文本列 ≥850px；1280px→展开档+文本列 768px 满额+批注卡全显；1600px→纸列居中批注居左。DevTools device toolbar 实测。
- **S2-07【I】** 锚定回归：正文含 @角色/伏笔词 → 批注卡 Y 对齐该行（相邻卡按下推避让不叠）；滚动编辑器 rAF 跟随；打字/删词后重算；label 不在正文 → 落底部「其他提醒」。
- **S2-08【I】** 批注轨档（1093 或拖窄窗）：圆点 Y=各条锚定行高；安全类（泄密/矛盾）朱色大点；点击弹卡不溢出视口（底部行 flip）；Esc 关一层；Tab 键可达圆点、Enter 弹卡。
- **S2-09【I】** SparkDock 光标层 §4.4 C1-C5：停顿弹舱位置/Tab 召唤/数字键吸附/打字隐藏/sticky 连续吸附/Esc 收舱/滚动跟随。
- **S2-10【I】** §4.4 C6-C7：SparkDock 与 BeatCardDock 互斥；03 期 R1-R10 十条全重跑。
- **S2-11【I】** §4.4 C8-C10：造 dead_speak+cliche 命中 → GHOST_DONE 后三条在幽灵尾下方；「用原稿」学习回流；拒稿逃生舱「还是贴出来」回归。
- **S2-12【I】** 图标栏：hover 图标 300ms peek（滑过不误弹）；移出收；点击 pin（纸列被推挤 400px）；再点同一图标关；Ctrl+\ 三态（关→pin 上次/peek→pin/pinned→关）。
- **S2-13【I】** 徽章三源：收件箱积压（>5 条书）→此刻图标 ok 点；完稿报告到达→检查图标点+peek 一次；spine 建议到达→打算图标点；开对应面板即灭。
- **S2-14【I】** Ctrl+1~4：面板关着按键能开（pin 态）；开着按键切换；映射 1 打算/2 此刻/3 检查/4 AI 视角；速查表文案同步。
- **S2-15【I】** 本章解散迁移：打算面板底见本章文风卡（特例徽标/改回全书/跳文风页深链三路径回归）；此刻面板底见真相跳转（跳世界页 ?panel=canon）；字数只在页头。
- **S2-16【I】** 书脊：返回书架；‹ › 翻章（首/末章禁用态）；章号开目录（再点关）；＋新建。
- **S2-17【I】** 目录抽屉：Esc/外点/选章后收；多选删除全流程（含 Shift 范围选）；导入 .md/提取设定入口回归；pin 成 240px 常驻列且重启保持。
- **S2-18【I】** 冻结红线全回归：七键逐一；幽灵上屏/Esc 蒸发/退格收割；细纲胶囊扩写；Alt+N 速记；切页 detach 感知常驻。
- **S2-19【I】** 写作闭环动线实测（设计意图验收）：空章 → 书脊开目录选章 → 打算面板写打算（或点火卡写开头）→ 写中批注卡随写浮现 → Space/Tab 光标层用卡 → Ctrl+Enter 沉淀 → toast 去确认 peek 此刻收件箱 → 完稿体检 → 检查图标亮、peek 报告 → 残句修复/润色全流程。全程无死路、无遮挡。
- **S2-20【M/I】** 双 pin 极端（目录+面板同开 @1093）：纸列变窄但无布局错乱、无横向滚动条。
- **S2-21【I】** reduced-motion：目录/面板/批注 popover/光标层全部瞬切。
- **S2-22【I】** 收件箱直达：沉淀 toast「去确认」→ 此刻面板 peek + 收件箱展开（关着能开）；批量裁决/撤销回归。
- **S2-23【I】** 面板内容零改动证明：检查面板完稿体检→报告→残句修复→润色→读者反馈全流程与施工前逐步一致（组件搬家非重写）。
- **S2-24【M】** `--editor-max-width` 恒 880px、editor-type-large 实验开关切换正常（DevTools computed 验证）；顶栏淡出/状态丸/AI 辅助开关回归。

**清单条数：24。**

---

## 12. 考虑过并否决的方案（防施工走样）

1. **批注卡并入右侧助手（单栏化到极致）——否决。** 右栏是「显式召唤」语义（默认藏着），批注是「环境感知」语义（永远在屏才有价值）；合并=感知断。且锚定卡的价值恰在「贴着正文行」，搬到 444px 外的右栏等于解锚。
2. **SparkDock 留在批注层顶部——否决。** 带体解构后它没了家；在批注层顶续命=topReserve 复杂度永存+写中视线在光标而卡在栏顶。光标层与 BeatCardDock 同位同引擎是更干净的终态（§4.1）。
3. **章节目录做成顶栏下拉——否决。** 章节列表是纵向长列表（含多选/徽标/删除），侧出抽屉与世界页抽屉、本期的助手面板同构；下拉面板遮纸且高度管理尴尬。
4. **图标栏 hover 零延迟即 peek——否决。** 滑过误弹是旧触发条已犯过的病（静息 40% 透明就是为了不惹眼而打的补丁）；300ms 是「手指停住」的最小可靠信号。
5. **书脊并入 AppRail——否决。** AppRail=app 级导航（书架/世界/文风/设置），书脊=本书内导航（章）；两级混排会把「世界页/文风页」与「第 12 章」压进同一栏，心智分层塌掉。
6. **面板宽度随内容分档（打算窄/检查宽）——维持 03 期 §6.4 否决。** pin 态推挤联动会让纸列随切面板伸缩晃动；宽版阅读诉求的正解仍是报告模态化，不在本期。

## 需用户拍板

**无。** 本期全部条款落在用户「完全重构」授权的解冻范围内（三栏内部结构与形态）；两处高风险/中高风险（B-07 SparkDock 迁光标、B-05 hover 展开手势退役）已在行为清单标注并各配回归条目（§4.4、S2-08/S2-09），请施工后重点实测这两条的手感。

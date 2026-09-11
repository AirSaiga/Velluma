# 第 0 期：统一地基（UX 重构 · 设计规格）

> 适用范围：全库三页（写作台 / 世界页 / 文风页）共享的底层设施。施工第一步。
> 设计权威：本文档 + `01-style-page.md`。施工方照图施工；遇文档未覆盖的情形，回问设计，不自行再创造。
> 审计溯源：本文每个条目对应审计实锤（file:line），文末验收清单可逐条机器/人工检查。

---

## 0. 总则与设计原则

靶子（用户原话「使用起来不太方便」的三条定性）：
1. **找不到入口** → 本期以「hover-only 控件显形规则」（§4.4）+ 后续页面期解决；
2. **看不清/太密** → 本期字阶（§2.1）+ 对比度（§2.4）+ 语义色板（§2.5）解决根因；
3. **反馈怪** → 本期 z-index 层表（§3）+ 浮层规范（§4）+ 全局基础样式（§5）解决根因。

原则：
- **P1 双主题成对**：任何新增/修改的颜色 token 必须在 `:root` 与 `:root.dark` 同时给值。缺一对 = 打回。
- **P2 零视觉突变**：除「行为变化清单」（§6.3）逐项列出的之外，地基施工前后像素级无感。字阶/对比度修复是**有意的**视觉变化，也在 §6.3 逐项声明。
- **P3 引擎零触碰**：不改任何 prompt、SSE 帧字段、API 契约、TipTap mark 类名、引擎跟随器几何输入（§6.1 冻结清单）。
- **P4 token 先行**：新组件/新样式只允许消费 token；新增裸色值/裸字号 = 打回（白名单：第三方库内部、一次性遮罩 rgba 黑）。

---

## 1. 现状普查（设计依据，勿跳过）

### 1.1 字阶失序
全库 `font-size` 声明 **776 处**，去重后 **30+ 个不同值**。低于 12px 的约 250 处：

| 值 | 处数 | 等价 |
|---|---|---|
| 11px | 84 | |
| 0.6875rem | 92 | 11px |
| 0.75rem | 111 | 12px |
| 12px | 101 | |
| 0.625rem | 64 | 10px |
| 10px | 43 | |
| 9px / 0.5625rem | 17 | |
| 10.5px / 11.5px / 12.5px / 0.68rem / 0.7rem / 0.72rem / 0.78rem / 0.8rem | 各 5-15 | 碎片值 |

混用 px 与 rem 两套计量、同一语义（badge/hint）在不同组件取 9/10/10.5/11px 四个值。这是「看不清」的第一根因。

### 1.2 对比度失守（实测）
以 `--bg-primary #f7f4ed`（相对亮度 L=0.906）为底，按 WCAG 相对亮度公式实测：

| token | 值（浅色） | 对比度 | WCAG AA（正文 4.5 / 大字 3.0） |
|---|---|---|---|
| --text-primary | #2c2c2c | 12.7 | AAA ✅ |
| --text-secondary | #6b6560 | 4.9 | AA ✅ |
| --text-muted | #a89e90 | **2.4** | ❌ 大字档也不达 |

`--text-muted` 是全库辅助文字的默认色，2.4:1 是「看不清」的第二根因。深色侧 muted #8a8275 on #1a1815 = 4.7 ✅，无需动。

### 1.3 语义色缺失
`--accent` / `--ok` / `--danger` 从未定义但被引用（InspectorPanel.vue:1519 `btn-finish` 因 `var(--accent, #6366f1)` 兜底恒为题外靛蓝）；`--bg-elevated` 未定义（style.css:296 `.outline-note-pop` 兜底 `#1c1e24` 是**深色**——浅色主题下细纲浮层拿到深色底）；29+ 处硬编码浅底色（#fef3c7/#fee2e2/#dbeafe/#d1fae5…）在深色主题下亮瞎。

### 1.4 z-index 名存实亡
style.css:384-392 声明了分层表，但实测：世界页野生 640~1200（44 处），模态反向违例 z-50（6 处被抽屉 85 盖），z-200（2 处盖 toast 120）。

### 1.5 其余实锤
悬浮层无视口夹紧（4 处）、Esc 焦点依赖与多层同关、prefers-reduced-motion 仅 2 处豁免、无全局 :focus-visible、Toast 无堆叠上限（useToast.ts:30-33 裸 push）、路由过渡 mode="out-in" 卡死（AppShell.vue:75-79）。

---

## 2. Design Token 层

全部写入 `frontend/src/style.css` 的 `:root` / `:root.dark`。**计量统一 rem**（px 仅允许用于 1-2px 边框/hairline 与第三方库对齐场景）。

### 2.1 字阶体系（Type Scale）

根字号不动（浏览器 16px，html 不覆写）。定义八档语义字阶：

| token | 值 | px | 用途（角色纪律，§2.1.2） |
|---|---|---|---|
| `--text-xs` | 0.75rem | 12 | **最低可读档**。徽标/chip/计数/时间戳/坐标轴标签/大写 overline |
| `--text-sm` | 0.8125rem | 13 | 辅助句：hint、meta 副行、表次级信息、副标题说明 |
| `--text-base` | 0.875rem | 14 | **UI 正文默认**：按钮/输入框/菜单/列表主行/表单标签 |
| `--text-md` | 0.9375rem | 15 | 面板/抽屉正文（长句阅读） |
| `--text-lg` | 1rem | 16 | 强调正文、卡标题、分区标题 |
| `--text-xl` | 1.125rem | 18 | 页面/模态标题（配 --font-heading） |
| `--text-2xl` | 1.25rem | 20 | 页面大标题 |
| `--text-3xl` | 1.5rem | 24 | hero/零状态坡道主标题 |

行高 token：`--lh-tight: 1.35`（≥16px 标题）、`--lh-normal: 1.6`（正文/辅助句）、`--lh-compact: 1.45`（12-13px 的 meta 行）。
**规则**：12-13px 文本行高不得低于 1.45（CJK 字形拥挤是「太密」观感的另一半）。

#### 2.1.1 迁移映射表（codemod 依据）

| 旧值 | → 新值 | 条件 |
|---|---|---|
| 9px / 0.5625rem | `--text-xs` | 无条件（9px 全灭） |
| 10px / 0.625rem / 10.5px | `--text-xs` | 无条件 |
| 11px / 0.6875rem / 0.68rem / 0.7rem / 11.5px | `--text-xs` | 若承载的是句子（hint/meta 句）→ `--text-sm` |
| 12px / 0.75rem / 0.72rem / 12.5px | `--text-xs` | 若是按钮/菜单/输入/列表主行 → `--text-base`；辅助句 → `--text-sm` |
| 13px / 0.8125rem / 0.78rem / 0.8rem | `--text-sm` | 按钮/输入/菜单主行 → `--text-base` |
| 14px / 0.875rem | `--text-base` | — |
| 15px / 0.9375rem | `--text-md` | — |
| 16px / 1rem（UI 文本） | `--text-lg` | 编辑器正文不适用（见 §6.1） |
| 17-18px / 1.125rem | `--text-xl` | — |
| 20px / 1.25rem | `--text-2xl` | — |

**角色判据（二选一规则，消除施工歧义）**：
- 装饰性/计数/徽标/时间戳/轴标签/overline → 恒 `--text-xs`（不管旧值多大）；
- 承载完整句子的辅助信息（hint、副行、说明段）→ 至少 `--text-sm`；
- 可交互控件的文字（按钮/菜单项/输入/tab）→ 恒 `--text-base`；
- 抽屉/面板内成段正文 → `--text-md`。

#### 2.1.2 为什么最低档定 12px 而非 11px
桌面 CJK 在 100% DPI 下 11px 笔画粘连（实测 1366@125% 视口等效 1093px，11px 汉字约 8.8 物理像素高）。12px 是 Windows 桌面中文可读性底线；10px 以下只配做纯装饰，而库里 10px 大量用于「副行出处」「时间戳」这类**必须读**的文本——这是功能性失守不是审美问题。

### 2.2 间距尺度

4px 基栅，token 化（新增；施工只约束**新/改**的组件，存量间距本轮不强迁）：

`--space-1: 0.25rem`（4）`--space-2: 0.5rem`（8）`--space-3: 0.75rem`（12）`--space-4: 1rem`（16）`--space-5: 1.25rem`（20）`--space-6: 1.5rem`（24）`--space-8: 2rem`（32）`--space-10: 2.5rem`（40）`--space-12: 3rem`（48）

使用纪律：组件内部 gap/padding 用 1-4；分区之间用 6-8；页面级用 10-12。半档（2px/6px/10px）禁止新引入。

### 2.3 圆角尺度

| token | 值 | 用途 |
|---|---|---|
| `--radius-xs` | 0.25rem (4) | badge/chip/小标签 |
| `--radius-sm` | 0.375rem (6) | 输入框、小按钮 |
| `--radius-md` | 0.5rem (8) | 卡片、菜单项 |
| `--radius-lg` | 0.75rem (12) | 面板、抽屉卡 |
| `--radius-xl` | 1rem (16) | **模态统一**（ModalShell 现 14px → 16px；ConfirmDialog rounded-2xl=16px 已合） |
| `--radius-pill` | 999px | 胶囊/锚点导航 |

### 2.4 对比度规范（目标 WCAG AA）

硬性门槛（施工验收用，附录 A 给验证脚本）：
- 正文/辅助文字 ≥ 4.5:1；大字（≥18px 或 14px 粗体）≥ 3:1；
- 可交互控件的边框/图标 ≥ 3:1（对相邻底色）；
- 禁用态文字豁免，但禁用态不得以「看清内容」为前提（即禁用控件的信息必须可从别处获得）。

**token 调整（唯一一组存量值改动）**：

| token | 浅色旧值 | 浅色新值 | 实测 | 深色旧值 | 深色新值 | 实测 |
|---|---|---|---|---|---|---|
| `--text-muted` | #a89e90 (2.4 ❌) | **#756c5e** | 4.7 ✅ | #8a8275 (4.7 ✅) | 不变 | — |
| `--text-faint`（新增） | — | #a89e90（继承旧 muted） | 2.4 | — | #6b6459 | 3.0 |

**`--text-faint` 使用纪律**：仅用于纯装饰（水印、分隔点、空态插画、不可读的预览纹理）。**任何承载信息的文字禁用 faint**。旧 muted 的全部用法默认随 token 变深而自动修复；施工时 grep 检查旧 muted 用法中是否有「故意要很淡」的装饰场景，改指 faint（预计 ≤5 处，逐个过）。

### 2.5 语义色板（消灭硬编码浅色 + 补未定义 token）

新增状态色八件套（前景/背景成对），**双主题同时给值**：

| token | 浅色 | 深色 | 用途 |
|---|---|---|---|
| `--ok` / `--ok-bg` | #047857 / #d1fae5 | #34d399 / #0f2b22 | 成功、已保存、健康带、收编 |
| `--warn` / `--warn-bg` | #b45309 / #fef3c7 | #fbbf24 / #33270e | 警告、未保存、降级、提醒档 |
| `--danger` / `--danger-bg` | #b91c1c / #fee2e2 | #f87171 / #3a1a1a | 错误、删除、硬禁、泄密 |
| `--info` / `--info-bg` | #1d4ed8 / #dbeafe | #93c5fd / #15243d | 信息、保存中、场景徽标 |

实测对比度（fg 于自身 -bg 上）：浅色四组 4.5~5.5 ✅；深色四组 ≥6.5 ✅（附录 A 脚本复算，不得以目测放行）。

补未定义 token：
- `--accent: var(--accent-500)`（别名，消灭 `var(--accent, …)` 兜底出题外色）；
- `--bg-elevated`：浅色 `#fefdfb`、深色 `#2c2923`（浮层/弹出卡底色；消灭 outline-note-pop 浅色主题拿深色底的 bug）；
- `--focus-ring: var(--accent-500)`（§5.1 焦点环消费）；
- 幽灵草稿薄荷/琥珀两色保留字面 rgba（品牌隐喻色，不进状态色板，§6.1 冻结）。

**硬编码浅色迁移映射**（29+ 处的统一规则，逐文件清单在 01 期与后续页面期展开）：

| 硬编码 | → token |
|---|---|
| #047857 / #d1fae5 / #065f46 / #a7f3d0 系 | `--ok` / `--ok-bg` |
| #b45309 / #fef3c7 / #92400e / #fde68a 系 | `--warn` / `--warn-bg` |
| #b91c1c / #fee2e2 / #dc2626 / #fecaca 系 | `--danger` / `--danger-bg` |
| #1d4ed8 / #dbeafe / #2563eb / #bfdbfe 系 | `--info` / `--info-bg` |
| #6b7280 / #f3f4f6 系（中性徽章） | `--text-secondary` / `--bg-tertiary` |
| #d1d5db（收藏未选中） | `--text-faint` |
| #f59e0b（收藏选中） | `--warn`（深浅两侧均有良好对比） |
| #94a3b8 / #64748b / #f1f5f9 系（感知带等冷灰） | `--text-muted` / `--text-secondary` / `--bg-tertiary`（顺手归品牌暖灰） |

hover 加深写法统一 `color-mix(in srgb, var(--ok) 85%, black)` 式（不新增裸色）。

---

## 3. z-index 层表（常量强制）

### 3.1 规范层表

在 `:root` 定义（z-index 支持 var()，深浅主题同值——只定义在 `:root`）：

```css
:root {
  --z-content: 0;      /* 文档流内容（含编辑器） */
  --z-sticky: 10;      /* 页内 sticky（状态条/表头/顶栏） */
  --z-page-chrome: 40; /* 页面级浮动工具（世界页胶囊条/图标栏/页内菜单 40-49） */
  --z-dock: 50;        /* Spark/Beat Dock 卡舱（50-59） */
  --z-pop: 60;         /* 光标跟随浮层：mention/细纲浮层/情境浮卡/切片弹层（60-69） */
  --z-edge: 80;        /* 副驾抽屉触发条 */
  --z-drawer: 85;      /* 副驾抽屉 + 页内飞出抽屉（同层兄弟 85-89 带内排序） */
  --z-overlay: 100;    /* 页面级阻断遮罩（非对话框，如书架页全屏态） */
  --z-modal: 110;      /* 模态/确认/速查（嵌套逃生 111-115，需注释理由） */
  --z-toast: 120;      /* Toast 永远最上——操作结果不可被遮挡 */
}
```

铁律：
- 新浮层只允许取表内值；带内微调（如同层兄弟抽屉 85/86）允许，跨带取值 = 打回。
- **Teleport 到 body 的全局浮层必须用本表**；页面内部 z 值若 ≤39 且页面根已隔离（§3.3），可保留原值不强迁。
- style.css:384-392 的旧注释分层表删除，以此节为准（注释指向本节）。

### 3.2 野生值迁移映射（逐项）

| 现状（file:line → 值） | → 新值 | 说明 |
|---|---|---|
| BeatCardDock.vue:99 → 90 | `var(--z-dock)` 50 | ⚠ 行为变化：抽屉(85)现盖 dock，见 §6.3-B1 |
| ThinkingIndicator.vue:55 → 89 | 45 | 仍在 page-chrome 带、低于 dock（原「略低于 dock」语义保留） |
| mention-popup（style.css:481）→ 95 | `var(--z-pop)` 60 | |
| outline-note-pop（style.css:292）→ 90 | `var(--z-pop)` 60 | |
| WorldContextCard.vue:158 → 90 | `var(--z-pop)` 60 | |
| WorldSceneSlice.vue:1150 → 96 | `var(--z-pop)` 60 | |
| QuickEventNote.vue:594/849/899 → 95/96/96 | `var(--z-pop)` 60 / 60 / 61 | 96→61 者为同族最上 |
| LibraryView.vue:655 → 100 | `var(--z-overlay)` 100 | 值不变，改指 token |
| StyleExtractModal.vue:81 / StyleScanModal.vue:126 / CritiqueModal.vue:33 / PublishModal.vue:30 / InspirationModal.vue:96 / CharacterManagerPanel.vue:391,498 → 50 | `var(--z-modal)` 110 | ⚠ 修复：此前被抽屉(85)整盖（§6.3-B2） |
| ExtractionModal.vue:216 / MarkdownImportModal.vue:253 → 200 | `var(--z-modal)` 110 | ⚠ 修复：此前盖 toast（§6.3-B3） |
| WorldTimeline.vue 内 800×4 / 1367:50 | 见 §3.3 | 页面隔离后无害，值保留 |
| WorldView.vue 640/660/750/760/745/740、WorldMap.vue 460-860、标定卡 1200 | 见 §3.3 | 同上 |
| ChapterEditorView.vue:271 → 30、IgnitionCard.vue:88 → 10、StyleStatusStrip.vue:55 → 5、ImportPreviewTable → 1、PerceptionBand 2-3 | 保留 | 页内 ≤39，隔离后不逃逸；StyleStatusStrip 5 → `var(--z-sticky)` 10（语义归位） |
| Toast z-[120] | `var(--z-toast)` 120 | 值不变，Tailwind 任意值改写 scoped CSS |

### 3.3 页面隔离机制（世界页野生值的根治方案）

**问题**：世界页 44 处野生 z 值（640-1200）逃逸出页面，盖住模态与 toast。
**方案**：不靠逐值重排（Leaflet pane 体系内部 500-860 是库约定，重排脆弱），改用**层叠上下文隔离**：

```css
/* 世界页根容器（WorldView.vue 根类）加一行 */
.world-view { isolation: isolate; }
```

`isolation: isolate` 使页面根成为独立层叠上下文：子树内任何 z-index 只在上下文内部竞争；页面根本身在全局上下文中是 z-auto（=0 带），因此 toast(120)/modal(110) **必然**盖过页内一切——无论页内写 800 还是 1200。

- 施工：WorldView/WorldMap 根加 `isolation: isolate`；Leaflet 内部值（WorldMap 460-860）与世界页 chrome 值（640-1200）**全部保留不动**。
- ⚠ 验证点（隔离会破坏页内 teleport 预期）：世界页内 `Teleport to="body"` 的浮层（情境浮卡/速记确认胶囊）不受影响（teleport 后挂在 body，不在隔离上下文内）；**但页内非 teleport 的弹层若此前依赖高 z 盖过副驾抽屉，隔离后会被抽屉(85)盖住**——逐个检查 WorldTimeline 的 wt-ctx/wt-fs/wt-arc 弹层（800）是否 teleport：若是 teleport 到 body，需把值归位 `var(--z-pop)` 60；若在页内 DOM，隔离后自然低于抽屉，符合新秩序，保留。
- 同法适用于任何未来页面：页面根默认 `isolation: isolate`（写入组件脚手架约定）。

### 3.4 为什么保留 0-10 / 50-60 / 80 / 85 / 110 / 120 主带不动
写作台引擎跟随器（dock 避让、抽屉触发条 hover 区、感知带与抽屉的相对遮挡）是按现行值调优的（AGENTS.md「感知常驻」交互契约）。层表规范化只收编**违例值与野生值**，不动已在工作的秩序——「可慢不可错」。

---

## 4. 浮层规范

### 4.1 统一视口夹紧工具（接口设计）

**两个文件**（分层纪律：纯函数进 shared，DOM/监听进 composables）：

**A. 纯几何：`frontend/src/shared/utils/floatGeometry.ts`**（零 DOM 依赖，可在 vitest 对拍；测试落 `shared/utils/__tests__/floatGeometry.test.ts`）

```ts
export interface FloatAnchorRect { top: number; left: number; bottom: number; right: number }
export interface FloatPoint { x: number; y: number }   // 光标/点击点锚

export interface FloatPlacement {
  width: number          // 浮层实际宽（未知时传上限）
  height: number         // 浮层实际高（未知时传上限）
  gap?: number           // 与锚的间距，默认 8
  margin?: number        // 视口安全边距，默认 8
  prefer?: 'below' | 'above'   // 首选方向，默认 below
  flip?: boolean         // 底部不足时翻到锚上方，默认 true
  align?: 'start' | 'center' | 'end'  // 水平对齐锚的哪条边，默认 start
}

export interface FloatResult {
  top: number
  left: number
  flipped: boolean       // 是否发生了翻转（供箭头朝向/动画起点用）
  maxHeight: number | null  // 垂直空间仍不足时给出的可用高度（浮层须应用为 max-height）
}

export function placeFloating(
  anchor: FloatAnchorRect | FloatPoint,
  opts: FloatPlacement,
  viewport: { width: number; height: number },   // 注入而非读 window，保证可测
): FloatResult
```

算法（确定序，施工方照此实现）：
1. `left`：按 align 取锚 left / 中心 / right-width，然后 `clamp(margin, viewport.width - width - margin)`。
2. `top`：prefer=below → `anchor.bottom + gap`；若 `top + height > viewport.height - margin` 且 flip → 翻转到 `anchor.top - gap - height`，`flipped=true`。
3. 翻转后仍越界（锚居中视口/浮层过高）→ `top = clamp(margin, viewport.height - margin - height)`，且 `maxHeight = viewport.height - 2*margin`。
4. 点锚（mention/dock/情境卡）按零宽高矩形处理。

**为什么不用 floating-ui**：需求只有「锚下优先 + 翻转 + 双边 clamp」一个算法，200 行以内纯函数可测；引第三方库多一个升级面，且库默认行为（shift/shiftPadding 中间态）与本设计「确定序」不一致。正面样板 WorldContextCard.vue:59-63 的手写 clamp 已验证交互正确，本设计是其通用化 + 补翻转。

**B. 响应式包装：`frontend/src/composables/useFloatingLayer.ts`**

```ts
export function useFloatingLayer(options: {
  anchor: () => FloatAnchorRect | FloatPoint | null   // 每次重算时取锚
  size: { width: number; height: number } | Ref<{ width: number; height: number }>
  placement?: Omit<FloatPlacement, 'width' | 'height'>
  open: Ref<boolean>          // 开时挂监听，关时摘
}): { pos: Ref<{ top: number; left: number; flipped: boolean }>; maxHeight: Ref<number | null>; recalc: () => void }
```

行为契约：open=true 时挂 `window resize` + `scroll`（capture:true，捕编辑器容器滚动）监听重算；open=false 摘净。浮层本体 `position: fixed`，消费 `pos`/`maxHeight`。

**推广规则（哪些层必须接）**：所有 fixed 定位、锚定于页面元素的浮层——mention 弹窗（entityMention.ts，修右缘夹紧）、细纲浮层、情境浮卡（迁用统一函数替换手写 clamp）、切片弹层、时间轴弹层（wt-ctx/wt-fs/wt-arc，修无钳位）、RichTextEditor 选区浮窗（修 300px 写死夹紧——实际宽约 700px，**宽度改为实测 `el.offsetWidth` 后再夹紧**，容器 overflow-hidden 场景下浮层改为 Teleport 到 body 的 fixed 定位以彻底脱离裁剪）。
**例外**：Spark/Beat Dock 本期不接（§6.1 冻结写作台几何，dock 底缘下溢修复排在第 3 期写作台批次，届时接口现成）。

### 4.2 Esc 分层关闭栈

**问题**：Esc 依赖「焦点恰在层内」（4 个世界抽屉等）；叠层时一次 Esc 同关多层（useFocusTrap.ts:18 stopPropagation 拦不住同节点第二监听）；QuickEventNote window capture 抢跑。

**设计：`frontend/src/composables/useEscStack.ts`——全局唯一 Esc 栈**：

```ts
interface EscLayer { id: symbol; close: () => void; label?: string }
export function useEscStack(): {
  push: (close: () => void, label?: string) => symbol   // 返回 id；重复 push 由调用方防（open watch 内幂等）
  remove: (id: symbol) => void                          // 幂等
  isTop: (id: symbol) => boolean
  depth: Ref<number>                                    // 调试用
}
```

实现纪律（施工方照此）：
- 模块级单例栈 + **window 上唯一一个 keydown capture 监听**（模块首次 push 时挂，栈空即摘）。
- 监听逻辑：`if (e.key !== 'Escape' || stack.empty) return; e.preventDefault(); stack.top.close();` ——**一次 Esc 只关栈顶一层**。
- `useFocusTrap.ts` 的 Esc 分支首行加 `if (e.defaultPrevented) return;`（capture 顺序 window→document，栈监听先跑并 preventDefault，trap 自然让位；trap 的 Tab 捕获/焦点还原职责不变）。
- **迁移规则**：全库所有 `Escape` 的 window/document 级监听改为「打开时 push、关闭时 remove」；组件内元素级 Esc（input 内清空等，非浮层关闭）保留不动。世界页 4 个详情抽屉、时间轴右键菜单、关系表单、QuickEventNote 全部入栈（QuickEventNote 删 window capture 抢跑监听）。
- 入栈顺序=打开顺序；开多层时栈序即视觉层序（后开者在顶），天然正确。

### 4.3 ModalShell 推广规则

ModalShell（现 `features/world/presentation/ModalShell.vue`）**晋升为全局共享**：移动至 `frontend/src/components/ModalShell.vue`，圆角 14px → `var(--radius-xl)`，其余结构不动（Teleport/modal 过渡/遮罩/useFocusTrap/收起条全保留），**加一行 escStack 注册**（useFocusTrap 的 onEscape 保留作栈外兜底——栈不可用场景零回归）。

推广判定树：
- 模态 = 标题 + 正文 + （可选）底栏按钮 → **必须用 ModalShell**。首批迁移：StyleExtractModal、StyleScanModal（第 1 期执行）；CritiqueModal、PublishModal、InspirationModal（后续页面期）。
- 复杂向导/多区布局（ExtractionModal、MarkdownImportModal、AppSettingsModal）允许自绘壳，但**必须**：Teleport body、`z-index: var(--z-modal)`、useFocusTrap、escStack 注册、遮罩点击=Esc 语义（有未保存改动时改弹确认）。
- 模态之上再开确认（如删除确认从模态内触发）→ ConfirmDialog 已是 110 带内后开者；两个模态同开的场景设计上禁止（先关后开）。

### 4.4 hover-only 隐形控件规则（修「找不到入口」）

规则（CSS 模式化，全库统一）：
1. 任何 `:hover` 显形的控件，必须同时在**父容器 `:focus-within`** 时显形（键盘可达性的最低线）；
2. 显形用 `opacity`（保 tab 序），**禁止 `display:none`/`visibility:hidden`** 切换（会把控件从 tab 序里抹掉）；
3. 破坏性操作（删除/废弃）不允许纯 hover 显形——常态 45% 透明度可见，hover/focus 升 100%；
4. 显形控件点击目标 ≥ 24×24px（视觉图标可小，hit area 用 padding/伪元素补足）。

统一片段（写入 style.css 工具类，类名 `.reveal-on-hover` 供迁移套用）：

```css
.reveal-on-hover { opacity: 0; transition: opacity 0.15s ease; }
.reveal-parent:hover .reveal-on-hover,
.reveal-parent:focus-within .reveal-on-hover { opacity: 1; }
.reveal-on-hover:focus-visible { opacity: 1; }
.reveal-on-hover--danger { opacity: 0.45; }   /* 破坏性操作常态低显 */
.reveal-parent:hover .reveal-on-hover--danger,
.reveal-parent:focus-within .reveal-on-hover--danger { opacity: 1; }
```

首批迁移（第 1 期之外的页面期执行，本期只立规则与工具类）：章节删除钮（WorkspaceView.vue:1295-1314）、书卡操作钮（LibraryView.vue:616-622）、感知带 dismiss（PerceptionBand.vue:405-423，13px → 24px hit area）、角色卡删除（CharacterManagerPanel.vue:285,360）。

---

## 5. 全局基础样式

### 5.1 :focus-visible 基础样式（新增，写入 style.css）

```css
:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 2px;
  border-radius: var(--radius-xs);
}
:focus:not(:focus-visible) { outline: none; }
```

纪律：组件**禁止**再写 `:focus { outline: none }` 裸重置（现存 ~30 处 `outline: none`/`focus:outline-none` 逐步清除，本期先清写作台与文风页路径上的）；组件自定义焦点样式只允许改 offset/圆角，颜色恒走 `--focus-ring`。

### 5.2 prefers-reduced-motion 策略（新增，写入 style.css 末尾）

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
  html { scroll-behavior: auto; }
}
```

**豁免与降级清单**（毯式规则灭装饰后，功能性动效以「弱化替代」回归，逐个写在各自组件内）：

| 动效 | 降级方案 |
|---|---|
| 幽灵呼吸 ghost-draft-breathe 2.6s（style.css:217） | 静态 `filter: brightness(1.12)`（保留可见性语义，去循环） |
| ThinkingIndicator pulse/ring/breathe | 静态圆点 + 文字保留（进度语义由文字承担） |
| 各 spin 加载器（7 处） | 改 2s 透明度脉冲（`@keyframes reduce-pulse { 50% { opacity: .4 } }`，统一写入 style.css，类名 `.spin-reduced` 由毯式规则后声明覆盖——施工用补丁类，不改组件结构） |
| 罗盘/空白卡（已豁免 2 处） | 保留现状 |
| 世界页 wm-breathe/wm-star-spin 等装饰 | 毯式规则自然灭，无需补丁 |
| 模态/抽屉/Toast 进出场 | 0.01ms 瞬切（毯式规则生效） |

**为什么用毯式 !important 而非逐组件 @media**：库里无限动画 6+ 处且无统一命名，逐个豁免必然漏网；毯式灭一切 + 白名单补丁的顺序保证「漏网=静态」的安全失败方向（宁可不动，不可乱动）。
另：JS 侧 `scrollIntoView({ behavior: 'smooth' })` 不受 CSS 毯式管辖——`shared/utils/` 加 `prefersReducedMotion(): boolean`（matchMedia 查询），调用点 behavior 三元切换（首批：StyleView.scrollToSection）。**【审计外新增】**

### 5.3 Toast 堆叠上限与去重（useToast.ts 改造）

- **上限 3 条**：push 前若已有 3 条，逐出最旧的可逐出者（优先逐出 info/success；三条全是 error 时逐出最旧 error——上限是绝对的）。逐出需清其定时器 → 施工时把裸 `setTimeout` 改为 Map<id, timer> 持有句柄。
- **去重【审计外新增】**：同 message+type 在 1500ms 内重复 push → 不新增，重置既有条计时器（治连点产生的双 Toast，如收编双击场景）。
- 时序/时长/action(s) 契约不变（撤销胶囊、理由条不受影响）。

### 5.4 路由过渡兜底守卫（AppShell.vue）

**根因**：`mode="out-in"` 的进入端依赖离开端 after-leave 回调，回调被 HMR/异步组件挂起吞掉时进入端永不触发 → 整页 opacity:0。

**方案（确定性拆除依赖链）**：去掉 `mode="out-in"`，改默认并行模式；离开视图绝对定位退出布局流：

```css
.app-main { position: relative; }
.fade-leave-active { position: absolute; inset: 0; width: 100%; }
```

并行淡入淡出无等待链，不存在卡死路径；15ms 级交叉淡化在桌面上观感与 out-in 等价。enter/leave 时长不变（0.15s/0.1s），reduced-motion 下由 §5.2 毯式规则瞬切。
验收：连续快速切换路由 20 次（含 HMR 后），无 opacity 残留（DevTools 检查 `#app` 内无遗留 leave 节点）。

---

## 6. 几何/样式契约影响清单（写作台引擎跟随器）

### 6.1 冻结清单（本期一行不动，施工触碰=打回）

| 契约 | 位置 | 为什么 |
|---|---|---|
| `--editor-max-width: 880px` | style.css:37 | 正文列宽=引擎断点/落点计算的视觉前提 |
| `.inspector-drawer` 宽 380px / max-width 44vw | style.css:419-420 | 副驾四 tab 内容按此宽排版 |
| `.perception-band` 宽 260px | PerceptionBand.vue:218 | 感知带卡片密度调优前提 |
| `computeCursorDockPos`：top=cursor.bottom+8、left=max(16, blockStart.left) | useSparkDock.ts:141-155 | dock 吸附契约；底缘下溢修复排第 3 期 |
| `.ghost-draft` / `.ghost-draft--mint|--amber` 类名与 mark 结构 | style.css:213-234 | TipTap 扩展 + stripGhostDraftHtml 消费类名 |
| `.outline-note` / `.outline-note--collapsed` / `.entity-mention--*` 类名 | style.css:241-287/462-476 | 同上（会话级存盘剥除契约） |
| GHOST_DONE / SSE 帧字段、dock 零件缓存签名输入 | — | 后端契约，前端零触碰 |
| dock 四槽位排序、两级层级行结构 | SparkDock.vue | 交互模型冻结（硬约束 2） |

### 6.2 样式双源归一（RichTextEditor vs style.css，零视觉变化方案）

现状：style.css:447-453 全局 `.rich-text-editor .ProseMirror`（LXGW 优先/18px/1.8）被 RichTextEditor.vue:1163-1170 scoped `:deep(.ProseMirror)`（Songti 优先/1rem=16px/2.0）压死（scoped 样式后注入胜出）。**用户实际看到的是 16px/2.0/Songti 系**。

决策：**以现实为准**——归一到 token，值取当前实际渲染值（单用户写作应用，正文渲染是最高敏感度区域，不为「历史意图」制造视觉突变）：

```css
:root {
  --editor-font-family: 'Songti SC', 'STSong', 'Noto Serif SC', 'Source Han Serif SC', Georgia, serif;
  --editor-font-size: 1rem;      /* 16px */
  --editor-line-height: 2.0;
}
```

施工：RichTextEditor scoped 块删 font-family/font-size/line-height 三行（保留 height/outline/color）；style.css 全局块改为消费三个 token。渲染结果逐像素不变。
备注：style.css 注释中的「18px/1.8/霞鹜文楷优先」是未生效的历史意图；若未来要切，改三个 token 一行完成（决策权留给用户实测后拍板，不在本期）。
**【已实现（03 期 §7 落地）】**：实验开关形态=设置弹窗「实验：编辑器排版（宽排）」radio 对 + localStorage `velluma:editor-typography`（设备本地）+ `documentElement.editor-type-large` class（main.ts 启动读键防闪烁）；宽排档只覆写 `--editor-font-size: 18px / --editor-line-height: 1.8` 两枚 token，`--editor-max-width: 880px` 冻结不动；回退=选「标准」即摘 class 零残留。

### 6.3 行为变化清单（本期全部有意的行为/视觉变化，除此之外零变化）

| # | 变化 | 理由 | 风险 |
|---|---|---|---|
| B1 | dock 90→50：副驾抽屉(85)现在会盖住 dock | 抽屉是作者显式动作，dock 是自动弹出；显式盖自动 | 低：dock 在编辑列、抽屉在右缘，同屏重叠仅当光标贴右缘 |
| B2 | 六个模态 50→110：不再被抽屉盖 | 修复（模态被抽屉整盖是 bug） | 无 |
| B3 | Extraction/MarkdownImport 200→110：toast 现在盖它们 | 修复（操作结果不可被遮挡铁律） | 无 |
| B4 | 世界页 isolation 隔离：模态/toast 必然盖页内浮层 | 修复野生值逃逸 | 中：§3.3 验证点逐个过 |
| B5 | --text-muted 变深（2.4→4.7） | 修复「看不清」根因 | 低：全库辅助文字变深是有意变化 |
| B6 | 字阶收敛（10/11px→12px 等） | 修复「看不清」根因 | 中：密集面板高度 +≤8%，逐页目检 |
| B7 | InspectorPanel btn-finish 由题外靛蓝 #6366f1 变品牌靛紫 --accent-500 | 修复未定义 token 兜底 | 低：颜色变化是有意修复 |
| B8 | 路由过渡 out-in 拆除 | 修复卡死 | 低：观感等价 |
| B9 | 模态圆角 14→16px | 统一 | 无 |
| B10 | outline-note-pop 浅色主题底色深→--bg-elevated 浅 | 修复 bug | 无 |

---

## 7. 第 0 期验收清单

施工方完成后逐条核验（G=可 grep/脚本，M=目检，I=交互手测）：

- [ ] **F-01（G）**：`grep -rhoP "font-size:\s*\K[0-9.]+(px|rem)" src` 结果中无 <12px 值（0.75rem/12px 以下；白名单：注释、`__tests__`、第三方覆盖）。
- [ ] **F-02（G）**：`grep -rn "z-index" src` 无 50-120 带外裸值；无 z≥200；`z-\[` 任意值清零；世界页值保留但其根有 `isolation: isolate`。
- [ ] **F-03（G）**：`grep -rn "#fef3c7\|#fee2e2\|#dbeafe\|#d1fae5\|#f3f4f6\|#94a3b8" src` 清零（status 四系+冷灰系）。
- [ ] **F-04（G）**：`grep -rn "var(--accent[,)]\|var(--ok[,)]\|var(--danger[,)]" src` 全部解析到已定义 token（style.css 有定义行）。
- [ ] **F-05（I）**：深/浅主题各过一遍三页，无亮底深字/深底浅字穿帮；焦点环在 Tab 走查时全程可见。
- [ ] **F-06（I）**：Esc 测试：开模态+抽屉+右键菜单叠三层，连按三次 Esc = 逐层各关一次；焦点不在层内时 Esc 同样生效。
- [ ] **F-07（I）**：mention 弹窗在行尾触发不右溢；选区浮窗在最右列选中时全部按钮可达。
- [ ] **F-08（I）**：连发 5 条 toast，屏上 ≤3 条；1.5s 内同文 toast 不翻倍。
- [ ] **F-09（I）**：快速切路由 20 次无白屏；DevTools 无残留 leave 节点。
- [ ] **F-10（I）**：系统开「减少动态效果」后，幽灵草稿不呼吸、加载器变脉冲、罗盘不摆。
- [ ] **F-11（M）**：§6.1 冻结清单 diff 为零；写作台 Space/Tab/Ctrl+Space/Alt+N/Alt+O/Ctrl+Enter 全流程回归通过。
- [ ] **F-12（G）**：附录 A 对比度脚本跑过，四组状态色 + 三级文字色双主题全部 ≥ 门槛。

## 附录 A：对比度验证脚本（施工落 `scripts/verify_contrast.py`，跑一次即弃或留 CI 皆可）

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def lum(hexc):
    hexc = hexc.lstrip('#')
    r, g, b = (int(hexc[i:i+2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
def ratio(fg, bg):
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)
# 断言表：双主题全部 fg-on-bg 与 fg-on-ownbg 组合，门槛 4.5（正文）/3.0（faint 装饰）
```

---

## 接口预留（给第 1/2/3 期）

- 第 1 期（文风页）消费：§2 全部 token、§3 层表（两个模态归位）、§4.3 ModalShell 迁移、§4.4 hover 规则、§5 全部。
- 第 2 期（世界页）消费：§3.3 隔离验证点、§4.1 时间轴弹层接入、§4.2 四抽屉入栈、§4.4 角色卡删除。容器/query 模式复用第 1 期先例。
- 第 3 期（写作台）消费：§4.1 dock 底缘翻转接入（computeCursorDockPos 输出接 placeFloating）、§4.4 感知带 dismiss、§6.2 编辑器 token 切换实验。冻结清单（§6.1）在第 3 期设计评审时逐项解锁。

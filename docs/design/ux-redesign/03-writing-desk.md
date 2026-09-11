# 第 3 期：写作台（NLE-ADF 3.0 主界面 · UX 重构设计规格）

> 前置：第 0 期 `00-foundation.md`（§6.1 写作台几何契约冻结清单是本文的上位法）、第 1 期 `01-style-page.md`（container query / tier-btn 紧凑档先例）。
> 范围：`frontend/src/features/workspace/`（WorkspaceView.vue / InspectorPanel.vue / presentation/PerceptionBand.vue）、`features/generation/`（composables/useSparkDock.ts / useBeatDock.ts、presentation/SparkDock.vue / BeatCardDock.vue）、`features/chapter-editor/presentation/ChapterEditorView.vue`、`components/RichTextEditor.vue`、`style.css`（.nle-topbar / .drawer-edge / .inspector-drawer 段）、`components/AppSettingsModal.vue`（实验开关一处）。
> **冻结红线（复述 README，本文任何条款不得触碰）**：四槽位语义、Space/Ctrl+Space/Tab/Esc/Alt+N/Alt+O/Ctrl+Enter 快捷键契约、心跳/幽灵草稿/细纲胶囊机制、dock 零件缓存签名输入、TipTap mark 类名（canon-mark/ghost-draft/outline-note 家族）、感知管线。**边栏收敛只动几何与显隐，不动触发逻辑与感知管线。**

---

## 1. 目标

1. 边栏收敛：左感知带（260px）+ 右副驾抽屉（380px）+ 右缘触发条三件套对小视口（DPI 缩放 1093px CSS 视口）侵蚀正文列——互斥/让位策略落地；
2. BeatCardDock 底缘下溢治理：placeFloating 钳位**叠加**在冻结契约输出之上（契约本身一字不动）；
3. 感知带 dismiss 13px hover-only、nle-topbar 22px 钮、选区浮窗 ~20px 钮 → 目标尺寸归档；
4. InspectorPanel 四 tab 信息密度复查结论落地（字阶/间距归档）；
5. 00 期 §6.2 预留的编辑器排版一行开关 → 实验形态落地；
6. 感知带冷灰硬编码色 → token（深色修复）。

---

## 2. 边栏收敛（核心条款）

### 2.1 现状实锤

- 左：`.perception-band` 260px 常展 in-flow（PerceptionBand.vue:217-226，`order:-1`），与纸列抢宽；
- 右：`.inspector-drawer` 380px/44vw（style.css:505-519，z var(--z-drawer)），hover 瞥看（overlay 不推挤）/ 钉住（padding-right 推挤，WorkspaceView.vue:1059-1061）双态，Ctrl+\\ 切换；
- 右缘触发条 `.drawer-edge` 8px（style.css:486-502）；
- 三件套并开时（1093px 视口实测链）：1093 − 56(AppRail) = 1037 工作区 → 编辑器窗格 ≈ 830px → 830 − 260(感知带) − 380(钉住抽屉) ≈ 190px 正文列可用——纸列被压成窄条，是「看不清太密」的第一来源。

### 2.2 收敛策略（唯一指定做法）：感知带折叠条 + 容器查询两档

**不动右抽屉**（hover/pin 双态已是正确模型，00 期 §6.1 冻结其宽度），收敛落在感知带：

**A. 容器挂载**：`.editor-host`（WorkspaceView.vue:1396-1403，flex row、position:relative）挂容器：

```css
.editor-host { container-type: inline-size; container-name: deskhost; }
```

容器宽度 = 编辑器窗格实宽（减去 binder、不含右抽屉 overlay——overlay 不占布局宽；钉住时 padding-right 在 editor-main 上，editor-host 宽度不变，判定稳定）。

**B. 档位规则**：

| deskhost 宽度 | 行为 |
|---|---|
| ≥ 56rem（896px） | 现状：感知带 260px 常展 in-flow |
| 48rem – 56rem | 感知带折叠为 **36px 左缘条**（absolute 覆于纸列左缘，不占布局宽），交互见 §2.3 |
| < 48rem | 折叠条同上；**叠加**水平 padding 让位：page-head 与 ProseMirror 水平内边距 3rem → 1.5rem（`var(--space-6)`） |

**C. padding 让位实现**：RichTextEditor.vue:470 内容类含 `px-12`（3rem）。施工时用更高优先级覆写（不改该行字符串——mark 类与结构冻结，只追加样式）：

```css
@container deskhost (max-width: 48rem) {
  .editor-host .rich-text-editor .ProseMirror { padding-left: var(--space-6); padding-right: var(--space-6); }
  .editor-host .page-head { padding-left: var(--space-6); padding-right: var(--space-6); }
}
```

（page-head 实际选择器以 ChapterEditorView 现状为准，等效即可。）

**D. 几何验证锚**（验收 D-02 引用）：

- 1093px 视口（1366@125%）：deskhost ≈ 830px ≈ 51.9rem → 折叠档生效；纸列可用 830 − 36 = 794px，文字量度 min(794−96, 672 上限) = **672px ≈ 42 字/行**（现状同视口约 474px ≈ 29 字/行）；
- 1280px 视口：deskhost ≈ 1017px ≈ 63.6rem → 常展档，零变化；
- 分屏/小窗 < 768px 窗格：折叠 + padding 让位，文字量度优先。

### 2.3 折叠条交互规格

- **形态**：36px 宽、全高、absolute 左缘、`z-index: var(--z-dock)`（50——压内容、让弹层）、`overflow: hidden`；内含：提示种类圆点（最多 4 枚，kind 色）+ 溢出计数「+N」+ 打算小旗 ⚑（有 spine 打算时）——纯态标，无按钮；
- **展开触发（三条，任一满足）**：
  1. `:hover` 悬停折叠条；
  2. `:focus-within`（键盘 Tab 进入带内 dismiss 钮）；
  3. Vue 强制类 `band-force`——当 `dockActive` 为真时由 WorkspaceView 计算并下发：`dockActive = sparkDockVisible || attachedParts.length > 0 || ghostActive`（useSparkDock / useGhostDraft 既有导出，WorkspaceView 层算好以 prop/class 绑定传入，**感知带内部不新增状态机**）；
- **展开形态**：带体 260px 宽 absolute 覆于纸列之上（**不推挤**纸列——覆态语义与右抽屉 hover 瞥看同族），纯色底 `var(--bg-secondary)` + 右缘投影（复用 `.inspector-drawer` 既有 box-shadow 值，不立新 token）；
- **收起**：三触发全消即收（hover 离开 + 无焦点 + dockActive 转假）；纯 CSS `:hover`/`:focus-within` 承担前两路，`band-force` 类增删承担第三路——过渡 `width .18s ease + opacity`，reduced-motion 全局兜底已有；
- **内容保全**：折叠只是 `width: 36px; overflow: hidden`，带内 DOM 全量保留——锚定卡垂直对齐（usePerceptionAlignment）只依赖 Y 坐标，宽度切换安全；topReserve 测量走既有「文档变化重算」路径，折叠切换不改头部内容高度，零新逻辑；
- **显隐语义**：折叠态作者「感知」不中断（心跳照跑、零件照算——感知常驻契约），只是视觉收纳；dockActive 强制展开保证「有东西可看时它自己回来」。

### 2.4 右缘触发条加宽

`.drawer-edge` 8px → **12px** 命中宽（style.css:486-502）。视觉渐变不动：既有渐变色标本就是绝对定位（4px 衰减锚右缘），元素加宽后 4px 之外区域透明——视觉零变化，命中面 +50%。

---

## 3. BeatCardDock 钳位叠加（useSparkDock.ts:141-155 / useBeatDock.ts / BeatCardDock.vue）

### 3.1 冻结重申

`computeCursorDockPos()`（useSparkDock.ts:141-155）返回 `{ top: cursorCoords.bottom + 8, left: Math.max(16, blockStartCoords.left) }`——**公式一行不动**（00 期 §6.1）。本节规格是「在消费侧叠加钳位层」，契约输出作为 placeFloating 的锚输入。

### 3.2 接入规格（唯一指定做法）

BeatCardDock.vue（Teleport body / fixed / z var(--z-dock) / 宽 min(420px,80vw)——全部保留）改由 `useFloatingLayer` 供位：

```ts
// useBeatDock.ts 的 showBeatDock 内（消费侧唯一编辑点）
const anchor = () => {
  const p = computeCursorDockPos()
  return p ? { x: p.left, y: p.top - 8 } : null   // 契约的 +8 间距还给 placeFloating 的 gap，正常档逐像素等值
}
// useFloatingLayer({ anchor, placement: { gap: 8, margin: 8, prefer: 'below', flip: true, align: 'start' } })
```

- **锚点换算**：契约 top 含 8px 间距，减去后交 placeFloating 用 `gap: 8` 重新施加——未钳位时像素与现状完全一致（回归 R1 的判据）；
- **放置**：`prefer: 'below'`（契约语义=光标下展开），`flip: true`——近视口底自动翻到光标上方（治底缘下溢），`margin: 8` 双侧夹紧（治右缘溢出，`align: 'start'` 保持左对齐语义）；
- **尺寸**：开后实测 dock 根元素；首帧兜底 `{ width: 420, height: 300 }`（约 4 卡 + 标题 + 提示行）；
- **maxHeight**：placeFloating 返回值绑到卡列表 `max-height` + `overflow-y: auto`（flip 后空间仍不足的小视口兜底）；
- **翻转动画**：placeFloating 报 flipped 时加类 `.beat-dock--flipped`，enter 过渡的 translateY 方向取反（从锚点上缘长出来，而不是机械地从下方冒）；
- **滚动/resize 跟随**：useFloatingLayer 自带 open-gated 监听——这是**新增行为**（现状开舱后滚动即漂移，舱留原地），按修复性改进入行为变化清单 B-04；
- **SparkDock 不动**：它已是感知带 #dock 槽内流式区块（非 fixed 浮层），不接 placeFloating，sticky/stash/restore 时序零交集。

### 3.3 回归清单（待设计说明裁决①，验收 D-04 逐条过）

| # | 场景 | 预期 |
|---|---|---|
| R1 | 光标在视口中上部开舱 | 舱位与旧契约**逐像素一致**（top=cursor.bottom+8、左对齐 blockStart） |
| R2 | 光标距底 < 舱高+16 | 翻到光标上方（flipped），舱底距光标行 8px，不遮光标行 |
| R3 | flip 后空间仍不足（极小视口） | maxHeight 生效，卡列表内滚，舱不出屏 |
| R4 | 光标近右缘（blockStart.left + 420 > vw−8） | 左缘夹紧，舱不右溢 |
| R5 | Ctrl+Space 开 / Esc 关 / 数字键选 / 点击选 / 打字即关 | 与现状逐一相同 |
| R6 | 开舱后滚动编辑器 | 舱**跟随**光标行（新行为，治漂移） |
| R7 | 开舱后 resize 窗口 | 舱重算位（新行为） |
| R8 | SparkDock sticky：stash → ghost → restore | 零交集（SparkDock 未接钳位，时序不变） |
| R9 | beatDock 与 SparkDock 互斥（showBeatDock 先 hideSparkDock） | 不变 |
| R10 | 幽灵在屏时 beatDock 键盘不可达（session 门） | 不变 |

---

## 4. 感知带修复（PerceptionBand.vue）

### 4.1 dismiss 钮（405-423）

现状：`opacity: 0` 仅 hover 显，`padding: 0 2px` + 13px 字 → 命中面 ≈13px。

- 命中面 → **24×24**（`padding: 4px 6px`，外框尺寸补足）；
- 显形走 00 期 §4.4：卡片 `:hover` + `:focus-within` 双触发，静态 opacity 0 **保留**（dismiss 是可恢复操作——静音可逆，非破坏性，不适用 45% 基线规则三）；
- 过渡 `opacity .15s` 保持。

### 4.2 色值 token 化（深色修复，硬编码冷灰/粉彩全清）

| 现状 | 归位 |
|---|---|
| 带体 `border-right: #e2e8f0` | `var(--border-color)` |
| 带体 `background: rgba(248,250,252,.6)` | `color-mix(in srgb, var(--bg-secondary) 60%, transparent)` |
| `.band-empty` `#cbd5e1` | `var(--text-muted)`（承载引导句，非纯装饰） |
| spine 虚线 `rgba(148,163,184,.35)` | `var(--border-color)` |
| `.band-more` 边框 `#cbd5e1` | `var(--border-color)` |
| `.hint-card` 底 `#fff` / 边 `#e2e8f0` | `var(--bg-canvas)` / `var(--border-color)` |
| hint label `#334155` / dismiss hover `#475569` | `var(--text-primary)` |
| 浮区渐变 `rgba(248,250,252,…)` | `color-mix(in srgb, var(--bg-secondary) …)` 同构 |
| hint 卡四色系：character 靛 `#c7d2fe/#eef2ff/#4f46e5`、hook 琥珀 `#fcd34d/#fffbeb`、leak 玫红 `#fca5a5/#fef2f2`、style 紫 `#c4b5fd/#f5f3ff/#7c3aed`、inbox 青 `#5eead4/#f0fdfa/#0f766e` | **全部由既有 token 派生，零新 token**：character → `--info` 族；hook → `--warn` 族；leak/contradiction → `--danger` 族；style → `--accent-500` 族；inbox → `--ok` 族。每族三件套：`border: color-mix(kind 35%, transparent)`、`background: color-mix(kind 8%, var(--bg-canvas))`、文字/tag = kind 本体色 |

- 色相迁移（靛→info 蓝、青→ok 绿等）是**有意的视觉变化**：硬编码浅粉彩在深色主题下瞎眼是实锤故障，color-mix 派生自动双主题正确。入行为变化清单 B-07。
- kind 身份语义保留（五类仍五色，只是色相归到语义族）。

### 4.3 字号

- SparkDock 零件 chip 12.5px（SparkDock.vue）/ BeatCardDock 内 12.5px → `var(--text-sm)`（13px，碎片值消灭）；
- IgnitionCard 12.5px 碎片值 → `var(--text-sm)`；
- 薄荷品牌色（幽灵/吸附态 rgba(52,211,153,…)）按 00 期 §2.5 先例**保留字面值**（双主题均成立的品牌色）。

---

## 5. 顶栏与编辑器目标尺寸归档

### 5.1 nle-topbar（WorkspaceView.vue:1492-1511 / style.css:445-465）

- `.nle-topbar__btn` 22px（1.375rem）→ **24px**（1.5rem）见方面；
- 静息 `opacity: 0.6` → **1.0**（顶栏是状态+三枚功能钮，半透明徒增「看不清」；纸面优先由布局保证，不靠半透明退让）；
- 打字中淡出（`--dim` → 0.1）语义**保留**，补 `:hover`/`:focus-within` 恢复 1.0（键盘/鼠标靠近即召回，此刻作者意图明确要看）；`.status-bar--dim` 同款补全；
- 状态色 `#34d399` = 幽灵薄荷品牌色（rgb(52,211,153)），按 00 期 §2.5 保留字面值并加注释引用先例。

### 5.2 选区浮窗（RichTextEditor.vue:118-141）

现状已接 placeFloating + Teleport（118-141，prefer 'above'，实测宽高）✅ 无需治理。仅尺寸归档：

- 文字钮（B/I/U/AI 润色等 `px-2 py-1 text-xs` ≈24px 高）：字号保 `text-xs`（紧凑工具条档，01 期 tier-btn 先例——工具条是「控件带」不是正文），声明 `min-height: 24px`；
- icon-only 钮（撤销类 `px-1.5`）：补 `min-width: 1.5rem` → 24×24 见方。

### 5.3 章节列表删除钮（WorkspaceView.vue:1295-1314）

`.ch-delete` 20px（1.25rem）hover-only → 24px 命中 + `.reveal-on-hover` 迁移（focus-within 对等）+ 静态 45%（破坏性规则三）。

### 5.4 页面头菜单钮（ChapterEditorView.vue:242-261）

`.page-head__menu-btn` 现状 reveal = `.paper:hover` + `--open` + `:focus-visible`，**缺 `.paper:focus-within`**（键盘焦点进菜单钮时纸面未 hover 则钮不可见的死角）→ 补 `.paper:focus-within` 触发源。26px（1.625rem）尺寸达标不动；`.action-menu` z 30 保留（页内层序正确）。

---

## 6. InspectorPanel 密度复查与归档（InspectorPanel.vue）

### 6.1 四 tab 信息架构复查结论（待设计说明相关）

**架构不动。** 打算 / 此刻 / 本章 / 检查 + 底部「AI 视角」降级入口是 2026-08-22 按写作流程重排过的现行线（写前规划 → 写中感知 → 章级回看 → 完稿检查），每 tab 带用途副标题（TAB_SUBTITLES 80-86），顺序与内容零调整。「密度」问题的病灶在字阶与间距（12px 句 + 14px padding 的压抑感），不在信息架构——按 §6.2 归档即解。

### 6.2 字阶/间距归档表

| 位置 | 现状 | 归位 |
|---|---|---|
| `.tab-content` padding | 0.875rem（14px） | `var(--space-4)`（16px） |
| panel 间距 gap | 0.875rem | `var(--space-4)` |
| `.btn-refinery`（1234-1249） | 0.75rem（12px） | `var(--text-base)` + min-height 28px（tab 主行动钮） |
| `.btn-finish`（1508-1523） | 0.8125rem（13px） | `var(--text-base)` + min-height 28px |
| `.report-item` / `.settle-item` / `.fix-sent` / `.audit-row` / `.surgery-row` | 0.75rem（12px） | `var(--text-sm)`（承载句子） |
| `.strip-outline-input`（1152-1167） | 0.75rem | `var(--text-sm)`（作者输入内容） |
| `.rf-text` | 0.75rem | `var(--text-sm)` |
| `.comp-error-row` | 0.75rem | `var(--text-sm)` |
| `.char-name` | 0.8125rem | `var(--text-sm)` |
| `.hint`（1335-1340） | `var(--text-xs)` | `var(--text-sm)`（承载句子，§2.1.2 hint→sm+ 纪律） |
| `.section-label` / `.strip-num` / `.stat-label` / `.issue-cat` / `.fix-desc` / `.fix-status` / `.char-state` / `.world-model-debug` / `.empty .muted` | xs（12px） | `var(--text-xs)` **保持**（标签/计数/调试技术信息角色，达标） |

### 6.3 硬编码色归档

| 现状 | 归位 |
|---|---|
| verdict：#16a34a / #65a30d / #d97706（1644-1648） | `var(--ok)` / `color-mix(in srgb, var(--ok) 50%, var(--warn))` / `var(--warn)` |
| `.report-item--warn` #ef4444（1489） | `var(--danger)` |
| `.surgery-status` #16a34a（1665） | `var(--ok)` |
| `.reader-feedback-card` rgba(202,138,4,.1) / #ca8a04 / #d97706（1313-1326） | `color-mix(in srgb, var(--warn) 10%, transparent)` / `var(--warn)` / `var(--warn)` |
| `.comp-error-row` rgba(245,158,11,.05/.3)（1371-1372） | `color-mix(in srgb, var(--warn) 5%, transparent)` / `color-mix(in srgb, var(--warn) 30%, transparent)` |
| `.fix-status--ok/--err` | 已 token ✅ 不动 |

### 6.4 抽屉宽度分档取舍（待设计说明裁决②）

**不分档。** 理由：

1. 宽度随 tab 跳变 = 钉住态下纸列跟着伸缩晃动（padding-right 推挤联动），破坏「纸面恒定」的第一体验；
2. 380px/44vw 是 00 期 §6.1 冻结契约，分档要动契约；
3. 密度问题经 §6.2 字阶/间距归档解决，不需要宽度代偿；
4. 若未来「检查」报告确需宽版阅读，正解是报告模态化（ModalShell 路线），不是抽屉分档——本期不做，留待真实使用数据。

---

## 7. 编辑器排版实验开关（00 期 §6.2 预留落地）

### 7.1 形态

AppSettingsModal「实验」折叠分区新增 **「编辑器排版（实验）」** radio 对：

- **标准**（默认）：16px / 行高 2.0——style.css:110-112 现值；
- **宽排**：18px / 行高 1.8——历史意图档。

### 7.2 实现纪律

- **单变量**：只覆写 `--editor-font-size` 与 `--editor-line-height` 两枚 token；`--editor-max-width: 880px` **保持冻结**（它是 dock/ghost/锚定几何的前提，宽度实验需另行设计评审，不搭这趟车）；
- 存储：localStorage 键 `velluma:editor-typography`（设备本地偏好，不进 uiPrefs 后端——实验特性不污染账号同步面）；
- 生效：`documentElement` 加/摘 class `editor-type-large`；style.css 追加：

```css
/* 编辑器排版实验（00 期 §6.2 预留开关，03 期落地）：宽排档 */
.editor-type-large {
  --editor-font-size: 18px;
  --editor-line-height: 1.8;
}
```

- 启动时 App 读键补 class；**回退路径 = 选「标准」即摘 class**，:root 原值自动恢复，零残留；
- **回填义务**：施工完成后回填 00 期 §6.2，把「未来开关」标记为「已实现（形态=设置弹窗实验档 + localStorage + html class）」；
- 零变化契约：未进过实验档的用户（localStorage 无键）排版逐像素不变。

---

## 8. 行为变化清单（唯一依据，清单外变化=事故）

| # | 变化 | 理由 | 风险 |
|---|---|---|---|
| B-01 | 感知带折叠条（deskhost < 56rem 生效，§2.2/§2.3） | 治小视口正文列侵蚀 | **中**（新交互，但纯几何显隐；感知管线零改动） |
| B-02 | dockActive 强制展开（有零件/幽灵时带自己回来） | 折叠态不丢感知呈现 | 中（随 B-01） |
| B-03 | BeatCardDock 近视口底 flip 上翻 + 双侧夹紧 + maxHeight 内滚 | 治底缘下溢 | **中**（位置语义新增；正常档像素不变） |
| B-04 | BeatCardDock 滚动/resize 跟随 | 治开舱漂移 | 低（修复性） |
| B-05 | `.drawer-edge` 8→12px 命中（视觉不变） | 触发条难瞄 | 低 |
| B-06 | dismiss × 24px 命中 + focus-within 显形 | §4.4 规则 | 低 |
| B-07 | 感知带冷灰/粉彩硬编码 → token 族（kind 色相迁移） | 深色瞎眼修复 | 低（有意视觉变化） |
| B-08 | nle-topbar 钮 22→24px、静息 opacity 0.6→1.0、dim 态 hover/focus 恢复 | 目标尺寸+可读 | 低 |
| B-09 | 选区浮窗文字钮 min-height 24px、icon 钮 24×24 | 目标尺寸 | 低 |
| B-10 | `.ch-delete` 24px + focus-within + 45% 静态 | §4.4 规则 | 低 |
| B-11 | `.page-head__menu-btn` 补 .paper:focus-within | 键盘死角修复 | 低 |
| B-12 | InspectorPanel 字阶/间距归档（§6.2：12→13/14 若干、padding 14→16） | 密度治理 | 低 |
| B-13 | SparkDock/BeatCardDock/IgnitionCard 12.5px → sm | 字阶纪律 | 低 |
| B-14 | 编辑器排版实验开关（默认零变化，§7） | §6.2 预留落地 | 低 |

---

## 9. 不动清单（冻结红线 + 本期豁免重申）

- `computeCursorDockPos()` 公式（useSparkDock.ts:141-155）——钳位在消费侧叠加，函数一字不动；
- `--editor-max-width: 880px` 默认值（style.css:37/110-112 区域）——实验开关只覆写字号/行高两 token；
- `.inspector-drawer` 380px/44vw、hover 瞥看/钉住双态语义、Ctrl+\\、`.drawer-edge` 位置与视觉（仅宽 8→12）；
- 四槽位语义与排序（landing/toward_beat/echo/ambient）、dock 零件缓存签名输入、`_finalize_parts` 规整；
- Space / Ctrl+Space / Tab / Esc / Alt+N / Alt+O / Ctrl+Enter 快捷键契约；
- 心跳触发逻辑（活跃防抖 3s / 停顿 4s / 段尾门）、感知管线、幽灵草稿机制（含 reapGhostIfDead）、细纲胶囊机制；
- TipTap mark 类名（canon-mark 家族 / ghost-draft 家族 / outline-note 家族，RichTextEditor.vue:1214-1233）；
- SparkDock sticky/stash/restore 时序（useSparkDock.ts:108-135）与 GHOST_DONE 帧/SSE 契约；
- 感知带内容与数据源（suggestions/spineProgress props、锚定算法、topReserve 测量、静音白名单消费）；
- InspectorPanel 四 tab 信息架构、各分区内容、TAB_SUBTITLES 文案；
- ProseMirror 排版三件消费 `--editor-*` token 的归一结构（实验开关只覆写 token 值，不动消费链）；
- splitpanes 窗格模型与持久化 sizes；
- RichTextEditor.vue:470 内容类字符串（px-12/max-w-3xl 等）——padding 让位走更高优先级覆写，不改该行。

---

## 10. 验收清单

> G = grep/脚本；M = 目检；I = 交互手测。证据本地留存不入库。

- **D-01【G】** `.editor-host` 带 `container-type: inline-size; container-name: deskhost`；workspace/generation 两 feature 内无新增视口 `@media` 布局判定。
- **D-02【M/I】** §2.2-D 几何锚三档实测（DevTools device toolbar）：1093px → 折叠条 + 42 字/行量级；1280px → 常展零变化；<768px 窗格 → 折叠 + padding 让位。
- **D-03【I】** 折叠条交互：hover 展开 / 移出收起 / Tab 进入 focus-within 展开；有零件或幽灵在屏时自动展开（band-force），消化后自动收起；展开态覆于纸列上、纸列不推移。
- **D-04【I】** §3.3 回归清单 R1-R10 逐条过（重点 R1 像素一致、R2 上翻不遮光标、R8 sticky 零交集）。
- **D-05【I】** 感知常驻回归：折叠态下心跳照发、零件照算（切章/停顿后 dockActive 触发展开即见新零件）——感知管线零改动证明。
- **D-06【M/I】** dismiss × 24px 命中（DevTools 量），卡片 hover 与 Tab 进入均显；静音后感知带恢复链路不变。
- **D-07【M】** 感知带双主题巡查：五类 hint 卡深色下全部可读（无浅粉彩瞎眼），kind 五色仍可区分。
- **D-08【M/I】** nle-topbar：钮 24px 见方、静息全不透明；打字中淡出仍在，hover/Tab 即恢复；三钮功能回归。
- **D-09【I】** 选区浮窗：划选弹出位置与现状一致（above 优先），文字钮/撤销钮命中面达标，功能（B/I/U、AI 润色、黄金片段、这不像我）回归。
- **D-10【I】** ch-delete 与 page-head ⋯ 钮：静态 45%/焦点显形生效，键盘 Tab 可达，删除/菜单功能回归。
- **D-11【M】** InspectorPanel 四 tab 巡查：主行动钮 28px 高 14px 字、报告/沉淀行 13px、hint 13px；padding 16px；深色下 verdict/读者反馈/错误行色值正确。
- **D-12【M/I】** 排版实验：默认进 App 零变化；切「宽排」即时生效（18/1.8），刷新后保持；切回「标准」即恢复 16/2.0；`--editor-max-width` 恒 880px（DevTools computed 验证）。
- **D-13【I】** 冻结红线回归：Space/Ctrl+Space/Tab/Esc/Alt+N/Alt+O/Ctrl+Enter 七键逐一；幽灵上屏/Esc 蒸发/退格收割；细纲胶囊扩写；Ctrl+\\ 抽屉钉住。
- **D-14【G】** `grep -n "computeCursorDockPos" -A 8 frontend/src/features/generation/composables/useSparkDock.ts` 公式与施工前 diff 为零；`grep -rE "font-size:\s*12\.5px" frontend/src/features/generation/ frontend/src/features/workspace/` 零命中。
- **D-15【M】** 深色主题全写作台巡查：顶栏/感知带/dock/抽屉/浮窗无瞎眼色、无隐形字。
- **D-16【I】** drawer-edge 12px 命中：鼠标贴近右缘 12px 内 hover 瞥看弹出，视觉渐变与现状一致。

**清单条数：16。**

---

## 11. 两个待设计说明的裁决汇总

- **裁决①（dock 接 placeFloating 后的交互回归清单）**：落地为 §3.3 R1-R10 十条回归表，验收 D-04 逐条过；核心不变式 = R1（正常档像素级一致）+ R8（sticky 时序零交集）。
- **裁决②（副驾抽屉宽度是否随 tab 分档）**：**不分档**（§6.4 四条理由）；密度由字阶/间距归档代偿；未来宽版诉求走报告模态化路线，不宽度分档。

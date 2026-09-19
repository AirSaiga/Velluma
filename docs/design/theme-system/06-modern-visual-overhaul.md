# 06 · 视觉完全现代化设计稿（「换代」）

> 2026-09-16 调研定稿。触发：用户验收 05/06-chrome 两轮后拍板「不要小修小补，我希望整个视觉出现完全的现代化」——验收标准 = 打开应用第一眼立刻觉得「换了代」。
> 谱系：`05-visual-modernization-plan.md`（P0-P2 基建期，已完成归档）+ `06-chrome-language-overhaul.md`（「纸上的仪器」，其 token 段/工具类已部分落地为底座）。**本稿为施工主档**：吸收上述已建成件为「已达标的底座」，解决遗留病根——「颜色基建很好，但形状/层次/材质语言停留在描边+平色时代」。06-chrome 未尽事项由本稿 §9 分期吸收，该文档降级为历史参照。
> 授权范围：全局视觉语言（表面/边框/阴影/圆角/材质/密度/控件/动效质感）= **chrome + 各页面非纸面区域**。纸面豁免面零触碰（§10）。

---

## 0. 现状裁决（为什么 token 齐了还像 2015）

基建盘点（2026-09-16 实测，均为代码事实）：

- **已达标件（本稿直接消费，不重做）**：表面/线阶/状态/动效/控件几何 token 全量；`.elev-0/1/2/3`、`.btn-primary-instrument`、`.btn-ghost`、`.icon-btn-instrument`、`.chip`、`.field`、`.menu-*`、`.eyebrow`、`.card-*` 工具类；SegmentedPill / Toast（float+blur+语义条）/ ModalShell 骨架 / AppRail pill 激活态 / AppearancePanel v2 / checkbox·range·color 皮肤。
- **病根四条（全部带计数）**：
  1. **描边是唯一分层语言**：`1px solid var(--border-color)` 205 处 / 55 文件，`var(--border-color)` 直连共 303 处（线阶 token 仅 22 处消费）。卡与容器全靠描边区分。
  2. **亮档表面无阶梯**：`--bg-canvas`=#fefdfb、`--paper-bg`=#fefdfb、`--bg-elevated`=#ffffff 三面同感（0-1% 亮度差不可辨）；页面根画 `--bg-primary`（#f7f4ed），卡画 canvas——桌面与卡只差 ~3% 亮度，且**无阴影**佐证，视觉上是一张平纸。亮档五主题全部如此。
  3. **状态只有 hover 变灰一档**：全仓 hover = `--state-hover` 背景灰（62 处），无 pressed 反馈规范（12 处残留 translateY(-1/-2px) hover 上浮——2015 年的「浮起」范式）、selected/active 混用。
  4. **形状与材质停摆**：圆角消费 xs(4px)×93 + sm(6px)×151 占 62%（md 8 ×105、lg 12 ×39、xl 16 ×2）——控件圆角 6px 是 2015 档；阴影单层「黑×透明度」无接触/环境分层；材质近零（blur 仅 scrim/Toast/dock/世界页 9 处，卡/面板全平色）。

**换代判据（唯一）**：用户在默认暖纸浅色档打开书架页与写作台，不需要任何解释，第一反应是「这不是刚才那个应用」。分解为三个可验收的视觉事实：①卡从桌面上**浮起来**（表面阶梯+分层影）；②控件**有重量**（圆角序列+按压反馈+立体按钮）；③浮层**有材质**（毛玻璃/顶缘高光/分层影）。

---

## 1. 设计语言定义

**一句话宣言：桌面有深度，纸面有光线，控件有重量——chrome 是置于暖石桌面上的一组白瓷仪器，纸列是灯下的稿纸。**

「2026 现代桌面感」的可分解要素与本项目落法：

| 要素 | 对标参照（学什么，不抄色值） | 本项目落法 |
|---|---|---|
| 深度分层 | Notion 的「灰画布上的白卡」呼吸感；Linear 的 panel→card→float 三层 | **桌面（desk）比卡深一档**：暖色木桌面隐喻，卡=白瓷浮在其上；纸列因此更亮——强化而非削弱稿纸隐喻 |
| 方向光 | Raycast/Linear 浮层的「顶部受光+底部落影」 | 所有 elevation 统一单光源自上：接触影（1px 级）+环境影（大 blur）双层合成；暗档浮层加顶缘高光线 |
| 形状序列 | Arc 的圆角递进连贯性（栏→卡→浮层半径单调递增） | 圆角档位整体上调一档（§3），按钮 8 / 卡 12 / 模态 20 的递进序列 |
| 完整状态 | Linear 的 hover/pressed/selected/disabled 四态分明 | 五态规范（§5）：hover 描边化、pressed 缩放+加深、选中 tint、焦点环、禁用半透明 |
| 克制材质 | Things 3 的暖色现代（证明暖≠过时）；Raycast 的浮层毛玻璃 | blur 只上小面积浮层；primary 按钮内高光；纸纹只上写作台两个抽屉（§4） |

**气质红线（「长期写作每天盯 6 小时」的约束）**：所有亮度阶差控制在 3-6%（可感知、不喧哗）；阴影全部柔边低透明度；大面积色块只有两种合法身份——签名色信号（朱砂/薄荷）与语义色信号，层次永远由表面差+光影表达，不用色块表达。**克制 = 结构性的安静，不是回退到描边+平色。**

**双语分工（产品身份）**：chrome = 仪器语言（本稿全面执行）；纸面/贴边抽屉 = 文房语言（纸叠影、衬线、纸纹，§6.2 决策保留）。「仪器桌上的一叠纸」就是换代后仍一眼可辨的 Velluma。

---

## 2. 表面与层次系统

### 2.1 五档阶梯（角色制）

新增语义层全部走 **color-mix 公式引用现有 token**，`:root` 声明一次、10 主题块零必改（主题块覆写的底层 `--bg-*` 在计算值期自动解析进公式）：

```css
/* ===== 换代表面阶梯（06-modern §2.1；:root 一次，全主题自适应） ===== */
--surface-desk:  color-mix(in srgb, var(--bg-primary) 75%, var(--bg-tertiary) 25%); /* 桌面：页面根/主滚动底 */
--surface-panel: var(--bg-secondary);                                               /* 栏/抽屉/面板底 */
--surface-card:  var(--bg-canvas);                                                  /* 卡面 */
--surface-well:  color-mix(in srgb, var(--bg-canvas) 88%, var(--bg-tertiary) 12%);  /* 卡内凹槽 */
--surface-veil:  color-mix(in srgb, var(--bg-elevated) 86%, transparent);           /* 毛玻璃浮层底（z-pop 专用） */
```

`:root.dark` 追加两行（暗档 desk 再压深一档、well 改向黑混合——暗档 tertiary 与 canvas 几乎同值，12% 混不可辨）：

```css
:root.dark {
  --surface-desk: color-mix(in srgb, var(--bg-primary) 94%, #000);
  --surface-well: color-mix(in srgb, var(--bg-canvas) 92%, #000);
}
```

既有 token 处置（` :root` 内单行改向，消费面零改动）：`--surface-sunken: var(--surface-well);`（原 bg-tertiary 直连，4 处消费自动获得卡内凹槽语义）；`--surface-base: var(--surface-panel);`（实测零消费方，改向后作为 panel 角色的规范名）。`--surface-float`/`--surface-overlay` 不动。

**消费规则（唯一权威，所有容器据此取面）**：

| 角色 | 取面 | 典型宿主 |
|---|---|---|
| 页面根 / 主滚动底 | `--surface-desk` | LibraryView/WorkspaceView/StyleView/OutlineView/InsightsView/TocPage 页根 |
| 贴边栏 / 抽屉壳 / 大面板 | `--surface-panel` | AppRail、ChapterTocDrawer、InspectorPanel、AppearancePanel 壳 |
| 卡 / 表单块 / 列表容器 | `--surface-card` | card-std/book-card/章卡/样本卡/表单分组 |
| 浮层（模态/菜单/Toast/卡舱） | `--surface-float` | ModalShell 卡、menu-shell、Toast、SparkDock |
| 卡内凹槽 | `--surface-well` | 分段轨道、card-well、卡内嵌搜索/指标格 |
| 毛玻璃浮卡 | `--surface-veil` + `blur(8px)` | mention 弹层、情境浮卡（仅 z-pop 级，§4.1） |

纸面 `--paper-bg` / `--shadow-paper` / 纸叠影**不动**。desk 翻转后纸列与卡的对比自动成立（纸 #fefdfb 浮于桌 #f5f2ea 之上）。

### 2.2 亮档各主题解析值（校验用近似 hex，施工不写这些值）

| 主题 | desk | panel | card | float | well |
|---|---|---|---|---|---|
| paper 浅 | #f5f2ea | #faf8f4 | #fefdfb | #ffffff | #fcfbf8 |
| minimal 浅 | #f2f2ef | #fafafa | #ffffff | #ffffff | #fdfcfc |
| soft 浅 | #f4eee4 | #faf6ef | #fdfaf4 | #ffffff | #fbf8f1 |
| pro 浅 | #eceff3 | #f5f7fa | #fbfcfe | #ffffff | #f8fafc |
| anime 浅 | #feeff4 | #fff8fa | #fffcfd | #ffffff | #fef9fb |
| paper 深 | #181714 | #292724 | #1e1c18 | #2e2c28 | #1c1a16 |
| minimal 深 | #0d0d0d | #1e1e1e | #121212 | #232323 | #111111 |
| soft 深 | #201b18 | #302b24 | #252019 | #343029 | #221d17 |
| pro 深 | #0f1419 | #1e242a | #12181f | #23282f | #11161d |
| anime 深 | #160f1d | #241e2c | #191221 | #292331 | #17111e |

验收时用 `getComputedStyle(document.documentElement).getPropertyValue('--surface-desk')` 对表抽查（允许 ±1 每通道舍入差）。

### 2.3 边框退役策略（双轨制）

**总则：描边从「分层手段」降级为「结构提示」。分层职责移交表面差+阴影；描边只在三种场合保留。**

| 档 | 场合 | 取值 | 理由 |
|---|---|---|---|
| **保留满档** | 输入面（input/textarea/select/搜索栏）、可拖拽把手外缘 | `1px var(--line)` | 输入的「可打入性」靠凹槽描边表达，是功能不是装饰 |
| **降为极淡** | 卡/容器/浮层壳外缘 | `1px var(--line-faint)` | 表面差+阴影已接棒分层，描边只补抗锯齿边 |
| **纯分隔** | 分隔线/列表行底线/表头线/footer 顶线 | `1px var(--line-faint)` | 分区缝 |
| **强化档** | elev-3 浮层外缘、危险操作确认边 | `1px var(--line-strong)` | 最高层浮层的收边 |
| **语义边** | 选中态 accent 边、danger 边、hover 加深边 | 语义色 / `--hover-line` | 信号，永不参与分层 |

**codemod 分派表**（205 处 `1px solid var(--border-color)` 的归宿，按选择器语义人工复核）：

| 判据（选择器/元素名含） | 归档 | 估量 |
|---|---|---|
| card/panel/section/item-row/pop/modal/drawer/chip 壳类容器 | → `var(--line-faint)` | ~110 处 |
| input/textarea/select/field/search/编辑态边框 | → `var(--line)` 并挂 `.field` | ~35 处 |
| border-top/bottom-only 的分隔缝（配 `:not(:last-child)` 等） | → `var(--line-faint)` | ~30 处 |
| 浮层壳（z-pop/menu/popover） | → `var(--line-faint)` + 挂 `.elev-2` | ~15 处 |
| hover/active/选中态内的边、语义色边 | 保留语义色，改 `--hover-line`/accent | ~15 处 |

歧义裁决：同一元素既是卡又是输入容器 → 输入赢（保 `--line`）。**本次不清零** `--border-color` token 本体（300+ 处引用中的非边框用法如 `border-left` 记号线等保留），只按上表归档边框用法。

### 2.4 Elevation 合成（分层影）

单层影改双层合成——「接触影」（贴地 1px 级）+「环境影」（大 blur 低透明），`:root` 一次：

```css
/* ===== 换代 elevation 合成（06-modern §2.4；消费既有主题影 token，块零改动） ===== */
--elev-1-shadow: var(--shadow-sm);                       /* 静置卡：仅接触影 */
--elev-2-shadow: var(--shadow-sm), var(--shadow-md);     /* 浮起：接触+环境 */
--elev-3-shadow: var(--shadow-sm), var(--shadow-lg);     /* 悬浮（模态）：接触+远环境 */
--hl-top: inset 0 1px 0 color-mix(in srgb, #fff 5%, transparent); /* 顶缘受光线（浅档近白面不可见=预期；暗档成立） */
```

`.elev-*` 工具类随之改写（**这是分层的执法点**）：

```css
.elev-0 { box-shadow: none; }
.elev-1, .card-std { box-shadow: var(--elev-1-shadow); border: 1px solid var(--line-faint); }
.elev-2, .mention-popup { box-shadow: var(--elev-2-shadow); border: 1px solid var(--line-faint); }
.elev-3 { box-shadow: var(--elev-3-shadow), var(--hl-top); border: 1px solid var(--line-strong); }
```

`.dark .elev-3` 旧内高光规则并入 `--hl-top` 后删除（避免双写）。既有 25 处 `box-shadow: var(--shadow-lg)` 组件消费点（模态/大浮层壳）codemod → `var(--elev-3-shadow)`；`--shadow-md` 直连的浮层 → `--elev-2-shadow`；`--shadow-sm` 直连静置卡 → `--elev-1-shadow`（值层面等价递进，无视觉回退）。`--shadow-paper` 与各主题块内 4 枚影 token **零改动**（公式输入端）。

tailwind.config.js 同步：`boxShadow.e1/e2/e3` 改指 `--elev-1/2/3-shadow`；`colors.surface` 增 `desk/card/well/veil` 四键。

---

## 3. 形状系统

### 3.1 圆角档位重定（:root 单点改值，394 处消费自动升格）

| token | 现值 | **新值** | 主要宿主 |
|---|---|---|---|
| `--radius-xs` | 4px | **6px**（0.375rem） | 行内微标/滚动条/极小徽标 |
| `--radius-sm` | 6px | **8px**（0.5rem） | 按钮/输入/菜单项/列表行 hover 面 |
| `--radius-md` | 8px | **12px**（0.75rem） | 卡/菜单壳/popover/浮出面板 |
| `--radius-lg` | 12px | **16px**（1rem） | 大卡/卡舱/抽屉内嵌面板/Toast |
| `--radius-xl` | 16px | **20px**（1.25rem） | 模态 |
| `--radius-pill` | 999px | 不变 | chip/分段轨道/状态丸 |

递进逻辑（Arc 式单调序列）：控件 8 → 内容容器 12 → 大件 16 → 对话框 20。**特例钉死**：编辑器内行内标记（`.ghost-draft` 2px、`.editor-find-match` 2px、`.entity-mention`）不升档——`.entity-mention` 若复核时 6px 显胖，就地写死 `border-radius: 4px`（它是纸面上的字，不是 chrome）。`.outline-note`/状态丸等 pill 语义件维持字面 999px。

### 3.2 密度决策：维持仪器密度，不动

06-chrome 已落地的 28/32/36 控件高度阶、菜单项 28、card-std padding 12、AppRail 项 40 **全部保留**——换代靠层次与材质，不靠再拧密度。唯一增量：**列表行高度档 40px**（章列表/目录列表/实体列表行，`min-height: 2.5rem`，行间分隔 `--line-faint`），取代各处 34-48 散写。

---

## 4. 材质规范

### 4.1 blur 预算（封闭清单，超出=违稿）

| 面 | blur | 底 | 状态 |
|---|---|---|---|
| 模态 scrim（ModalShell） | 10px | `--overlay-bg` | 已有，保留 |
| Toast | 8px | `--surface-float` | 已有，保留 |
| 卡舱（SparkDock/BeatCardDock） | 8px | `--surface-float` | 已有，保留 |
| mention 弹层 / 情境浮卡（z-pop 级） | 8px | `--surface-veil` | **新增**——悬浮于稿纸之上的信号 |
| 世界页地图浮件（既有 3-4px） | 不变 | 既有 | 豁免面邻接，不动 |

**禁令**：菜单壳（menu-shell）**不 blur**——高频出现+密文字，实底+分层影足够现代且零性能账；滚动容器/纸面/卡/面板永不上 blur；同屏 blur 面不超过 2 个（scrim 计入）。`--surface-veil` 只许配 z-pop 级、宽度 ≤360px 的浮卡。

### 4.2 光与渐变（克制的三处）

1. **顶缘受光线**：`--hl-top` 进 elev-3 合成（§2.4），暗档浮层「被台灯照亮的上缘」。
2. **primary 按钮立体感**：实底面加内高光+落影（§6.3 规格）——全应用唯一带方向光的控件面（信号件才配打光）。
3. **书封质感为全厂标杆**：book-cover 已有的径向柔光+内衬描边+顶缘高光（豁免面，不动）就是本稿材质语言的参照系——换代等于「让 chrome 追上封面的工艺」。**除此之外不新增任何渐变面**；禁 animated gradient mesh/大面积渐变。

### 4.3 纸纹（克制到两处）

`--paper-texture`（外观设置控制）只挂**写作台两个贴边抽屉**：ChapterTocDrawer 与 InspectorPanel 壳层（`background-image: var(--paper-texture)`）——它们是文房件；`.paper-card` 既有挂法保留。其余 chrome 一律不上纹理。

---

## 5. 状态系统（五态规范）

统一规则（全 chrome 控件强制，工具类已内置、散写件按此收编）：

| 态 | 平面项（列表行/菜单项/rail 项） | 描边件（ghost 钮/chip/卡） | 实底件（primary 钮） |
|---|---|---|---|
| **default** | 透明底 + `--text-secondary` | 透明/`--surface-card` 底 + `1px var(--line)` | `--accent-500` 底 + `--bg-canvas` 字 |
| **hover** | bg `--state-hover` + 字 `--text-primary` | 边 `--hover-line` + bg `--state-hover` + 字主色 | bg `--accent-600` + `--glow-accent` |
| **pressed（:active）** | bg `--state-active`（**不缩放**） | bg `--state-active` + `scale(.98)` | bg `color-mix(in srgb, var(--accent-600) 92%, #000)` + `scale(.98)` |
| **selected** | bg `--state-selected` + 字 `--accent-500`（600 字重） | 同左 + 边 `color-mix(accent-500 35%, transparent)` | 不适用 |
| **disabled** | `opacity: .5` + `cursor: default`（不改配色） | 同左 | 同左 |
| **focus-visible** | 全局 `:focus-visible` 2px 环（既有，不动） | 同左 | 同左 |

配套裁决：

- **translateY hover 全面退役**：删除 style.css 全局 `.btn-primary:hover` 的 `translateY(-1px)`（改只出 glow）、`.book-card:hover` 的 `translateY(-2px)`、其余 10 处散写——「上浮」让位给「阴影升档 + 描边加深」（card-hover 已是此语义，推广之）。可点卡的 hover = `--elev-1-shadow → --elev-2-shadow` + 边 `--line-faint → --line`。
- 新增工具类 `.press`（`transition: transform var(--dur-1) var(--ease-out)`；`:active:not(:disabled){ transform: scale(.98) }`）供散写按钮挂用；卡片/大面**不挂**（大面缩放是廉价感来源）。
- 危险态（danger）：ghost 范式——字 `--danger`、hover 底 `color-mix(in srgb, var(--danger) 8%, transparent)`、边同色（menu-item--danger 既有范式推广）。

---

## 6. 组件级规格（改造前后，token 引用级）

### 6.1 卡片族

**card-std（样本卡/实体卡/章卡/表单块）**
- 前：`bg-canvas` + `1px --border-color` + `--shadow-sm` + radius 8 + padding 12。
- 后：`bg: var(--surface-card)`；`border: 1px var(--line-faint)`；`box-shadow: var(--elev-1-shadow)`；`radius: var(--radius-md)`（12）；padding 12 不变；可点卡叠 `.card-hover`（现值即新规：shadow 升档+边加深，已达标）。

**card-compact（列表条目/指标格）**
- 前：`bg-secondary` + `1px --border-color` + radius 8。
- 后：嵌在卡/面板内时 = `--surface-well` 底 **无边框**（即 `.card-well` 语义，两者合并：card-compact 改 alias card-well 配方）；独立成列时 = `--surface-card` + `--line-faint`。

**book-card（书架卡，封面豁免不动）**
- 前：radius-sm(6)、`1px --border-color`、hover：边 accent-400 + translateY(-2px) + shadow-lg。
- 后：radius-md(12)、`1px var(--line-faint)`、静态 `--elev-1-shadow`；hover：`--elev-2-shadow` + 边 `--line` + 封面内衬影加深（既有）——**去 translateY**、**去 accent 边**（选中信号只留给真选中态）；`transition` token 化（`box-shadow/border-color var(--dur-2) var(--ease-out)`）。书架页根改 `--surface-desk` 后白瓷感自动成立。

**章节卡（大纲板）/列表行（目录/实体/收件箱）**
- 章卡走 card-std 新规；列表行：`min-height 40`、行分隔 `1px --line-faint`（last-child 无）、hover `--state-hover` 圆角 `--radius-sm`、选中 `--state-selected` + 字 accent、左缘 2px accent tick（章列表既有记号保留）。

**paper-card**：冻结（纸面语义卡）。

### 6.2 弹层族

**ModalShell（模态）**
- 前：卡 `bg: var(--bg-primary)`（=桌面色，浮层却涂桌面色——事故级）、radius 16、elev-3、header 边 `--border-color`。
- 后：卡 `bg: var(--surface-float)`；`radius: var(--radius-xl)`（20）；`box-shadow: var(--elev-3-shadow), var(--hl-top)`（elev-3 自动）；header 底边 `--line-faint`；footer 既有 hairline 保留；入场 `scale(.96)→1` + fade `--dur-3 --ease-out`（微调自 .95）；scrim blur10 不动。收起态小条（ms-bar）改 `--surface-float` + elev-3。

**贴边抽屉（ChapterTocDrawer / InspectorPanel / TocPage 抽屉）——文房件，保留纸叠影**
- 决策（沿用 06-chrome 评审点 2 拍板，本稿确认）：**保留** `paper-edge` 错位边 + `--shadow-lg` 纸叠影——全产品唯一文房 chrome 锚点。壳面 `--surface-panel` + `--paper-texture`（§4.3）；头部 hairline `--line-faint`；内部控件按 §6.3-6.5 换装。**不加大圆角、不加 blur**（贴边件圆角化会破坏纸叠隐喻）。

**浮出面板 / 菜单壳 / popover（menu-shell、浮出助手面板壳、edd-fieldmenu、action-menu）**
- 前：`bg-canvas` + `1px --line` + `--shadow-md` + radius 8。
- 后：`bg: var(--surface-float)`；`1px var(--line-faint)`；`--elev-2-shadow`；`radius: var(--radius-md)`（12）；入场 menu-pop（既有 -4px 上浮）保留。菜单项 28 高/hover `--state-hover`（既有达标）。

**mention 弹层 / 情境浮卡（z-pop 级）**
- 后：`bg: var(--surface-veil)` + `backdrop-filter: blur(8px)` + `--elev-2-shadow` + `1px var(--line-faint)` + radius-md——悬浮于稿纸上的毛玻璃小卡（§4.1 清单内）。

**卡舱（SparkDock/BeatCardDock）**：float+blur8 已达标，仅核 radius=lg(16)、shadow=elev-2、行间推挤布局不破。

### 6.3 按钮族

**primary（.btn-primary-instrument 增补立体规格）**
- 前：`--accent-500` 平实底；全局 hover translateY(-1px)。
- 后（新增两条声明，其余不动）：
```css
.btn-primary-instrument {
  box-shadow: inset 0 1px 0 color-mix(in srgb, #fff 22%, transparent),
              0 1px 2px color-mix(in srgb, var(--accent-500) 28%, transparent);
}
.btn-primary-instrument:hover:not(:disabled)  { box-shadow: inset 0 1px 0 color-mix(in srgb, #fff 25%, transparent), var(--glow-accent); }
.btn-primary-instrument:active:not(:disabled) { background: color-mix(in srgb, var(--accent-600) 92%, #000); transform: scale(0.98); }
```
- 删除 style.css 全局 `.btn-primary:hover { transform: translateY(-1px) }` 旧段（与工具类双写冲突且是退役范式）。

**ghost / danger / icon-btn**：工具类已达新规（hover 描边化+pressed 缩放）。本批工作是**收编**：全仓散写按钮类（`.btn`/`.preset-btn`/`.pm-done`/`.qen-btn`/表单 footer 钮等）逐族换挂 `.btn-ghost` / `.btn-primary-instrument` / `.icon-btn-instrument`，scoped 只留尺寸微调；danger 挂 `.btn-ghost--danger`（新增：`color: var(--danger)`、hover 底 `color-mix(var(--danger) 8%)`、边 `color-mix(var(--danger) 35%)`）。

### 6.4 输入族

`.field` 工具类即终态（凹槽 inset + focus 环已达标）。收编面：ApiSettingsModal `.field-input`、WorldviewPanel `.item-title-input`、各 DetailDrawer 表单、`outline-note-pop__input`、qen 系列散写输入——全部换挂 `.field`；search 变体新增 `.field--search`（左侧 icon 20px 占位 + padding-left 30px）。select 同规范套肤。hover `--hover-line`、focus accent+`--ring-soft`、error 边 `--danger` + 底 `color-mix(var(--danger) 8%)`、disabled opacity .5（§5 表）。

### 6.5 导航

**AppRail**：壳 `bg: var(--surface-panel)` + 右缘 `1px var(--line-faint)`；项高 40/icon 18/label 12（既有达标）；hover `--state-hover`、active `--state-selected` pill + accent + 左缘 tick（既有达标）。底部工具簇同规范、簇间 hairline。
**AssistRail（右缘助手栏）**：壳 `--surface-panel`、图标 `--icon-md`、hover `--state-hover` 圆角 sm、AI 总开关状态点（mint）不动。
**分段控件 SegmentedPill**：轨道底 `--surface-sunken`（=well 新值）；**轨道圆角改字面 `999px`**（radius-lg 升 16 后在 36 高轨道上不再是全圆，必须钉 pill）；thumb elev-1 滑动（达标）。文风页/数据页散写 tab-btn 换挂。

---

## 7. 动效质感（现有 dur/ease 体系内，零新 token）

| 交互 | 规格 | 备注 |
|---|---|---|
| 按压反馈 | `scale(.98)` `var(--dur-1) var(--ease-out)`（.press/工具类内置） | 控件有「重量」的第一来源 |
| hover | shadow 档位切换 + 边色加深，`var(--dur-2) var(--ease-out)` | 卡/chip/ghost 钮统一；**无位移** |
| 模态入场 | `scale(.96)→1` + fade，`var(--dur-3) var(--ease-out)`；退场 `--dur-2 --ease-in` | 既有模式微调 |
| 菜单/popover 入场 | translateY(-4px)+fade `--dur-2 --ease-out`（menu-pop 既有） | 全浮层统一此范式 |
| 贴边抽屉 | translateX(24px)+fade `--dur-3 --ease-out`（既有） | 不改 |
| Toast | 8px 上浮+fade `--dur-3 --ease-out`（既有） | 不改 |
| 列表入场 stagger | 书架网格/章列表 ≤6 项按 `--stagger-1`(40ms) 递进，`--dur-2` fade-up 8px | 超出 6 项不 stagger（滚动即乱）；仅首屏挂 |
| spring | 仅 SegmentedPill thumb（既有），禁新用 | — |

预算红线：单动效 ≤400ms；transform 只驱 scale/translate ≤24px；一切新动效必须消费 `--dur-*/--ease-*`（motion-low 毯式才能压住）；纸面/编辑器零新增动效。

---

## 8. 十主题块落地方式（配方组织）

**结构裁决：8 个 `[data-theme]` 块零必改。** 全部增量集中在 `:root`（§2.1 五行 + §2.4 四行 + sunken/base 改向两行）与 `:root.dark`（desk/well 两行）——公式以各主题既有 `--bg-*` 为输入，主题性格（paper 暖棕/minimal 冷灰/pro 钢蓝/anime 樱紫）自动透传。§2.2 解析表仅作验收对拍，**不是施工输入**。

工作量对照：直改 10 块 × 5 面 = 50 个 hex vs 本方案 = 11 行公式（含改向）。日后调某主题性格，仍只动该块既有 `--bg-*`，阶梯自动跟随。

唯一允许的块级可选增量：某主题若实测 desk 与 card 对比不足 3%（建议用相对亮度计算核对），允许该块单点覆写 `--surface-desk` 加深（记入施工报告）；预期无需动。

---

## 9. 施工分期（每批一次可验收）

| 批 | 内容 | 规模 | 验收动作 |
|---|---|---|---|
| **B1 换代底噪**（最大单一杠杆，先行） | §2 全部 token（:root 11 行 + .dark 2 行 + tailwind 桥）；页面根/主滚动面 desk 翻转（LibraryView/WorkspaceView/StyleView/OutlineView/InsightsView/TocPage）；§2.3 边框 codemod（205 处按分派表）；§2.4 elev 合成 + shadow 直连收编（38 处）；§3.1 圆角单点 re-tier；translateY hover 全退役（12 处）+ `.press` 工具类 | style.css + ~40 文件，纯模式化 | 打开书架页截图：卡浮于桌面、圆角序列可辨；写作台：纸列从桌面浮起、助手栏成独立材质；十主题快速切换无破版；typecheck+vitest 全绿 |
| **B2 浮层与材质** | ModalShell float 面 + radius-xl；菜单/popover 族终态；mention/情境浮卡 veil+blur；primary 立体规格 + danger 变体；五态收编扫（散写 hover/active/disabled）；SegmentedPill 轨道 pill 钉死；纸纹上写作台两抽屉 | ~15 文件 | 模态/菜单/浮卡三截图对 §6.2 逐项核；getComputedStyle 抽查 8 点（float 面/radius/elev 合成/veil）；blur 消费清单核对 §4.1 封闭集 |
| **B3 页面域收尾** | 世界页 chrome（DrawerShell 内部/表单族/右键菜单换装——画布与古地图零触碰）；文风页/数据页/大纲板控件收编；书架 chrome；弹窗表单族（ApiSettings/AppSettings）换装；列表行 40 档统一；首屏 stagger；散写按钮/输入 codemod 收尾（§6.3/6.4 清单） | ~30 文件 | 逐页走查清单（每页 3 截图：默认/hover 态/深档）；`1px solid var(--border-color)` 残留 ≤ 语义边与输入面 |
| **B4 十格验收与回归** | 5 主题 × 明暗矩阵截图走查；§2.2 解析表 getComputedStyle 对拍；motion-low 开/关各一轮；DPR 1.0/1.5/2.0 抽查 | 零新改动，纯核验 | §10 红线自证全过；既有对拍测试（extensions 34 项/contextBlockFormat/ghostReap/heartbeatSeam/timelineLayout）全绿；用户实机第一眼验收 |

排序理由：B1 单独构成「一眼换代」（表面+圆角+边框三项全仓生效，无新组件依赖）；B2/B3 依次把浮层与页面域拉到同语言；B4 收口。每批独立可合入、可回滚（B1 的 token 段先行 alias 期可作为 B1 内部的零视觉检查点）。

---

## 10. 红线自证清单（每批合入前逐项过）

1. **禁相对颜色语法**（Electron 28 渲染器 STATUS_BREAKPOINT 崩溃）：`grep -rn "rgb(from\|lab(from\|hsl(from\|hwb(from\|color(from" frontend/src` = 0。新增透明度只走 `color-mix()`（本稿全部公式已合规）。
2. **豁免面零触碰**：diff 不得包含——编辑器纸列/.ProseMirror/`--editor-*`/`.ghost-draft` 几何（2px/padding:0）；书封几何母题与六色板（book-cover 渐变/内衬值）；古地图（atlas token/wm-* 样式）；主题预览卡色值（appearancePreviewPresets.ts）；签名恒定色（mint/cinnabar/foreshadow/gold/truth 三态/atlas 五死 token，:root 126-150 区段）；`--paper-bg`/`--shadow-paper`/纸叠影值。
3. **十主题块结构不动**：diff 中 `[data-theme=...]` 选择器行数不变（零必改，§8）；`:root.dark` 只允许 +2 行。
4. **别名无自引用**（P1/P2 codemod 两连踩事故）：新增/改向的每个 token，`grep` 确认定义行右侧不引用自身；codemod 排除定义行。
5. **Tailwind 透明度禁令**：无 `bg-*/text-*\/[0-9]` 斜杠修饰符新写法（var()/color-mix 下失效）。
6. **blur 预算**：backdrop-filter 消费点 ∈ §4.1 封闭清单；滚动容器/纸面/卡/面板 = 0。
7. **动效纪律**：新动效全部消费 `--dur-*/--ease-*`；无 >400ms；无 spring 新用；纸面零新增。
8. **index.html ↔ useAppearance 对拍契约**：本方案无 schema 变化，index.html 零改动；若 B 批施工顺手改了外观字段，两边的拍必须同步。
9. **z 表/字阶/间距/--editor-max-width 冻结**：本稿零几何 token 增删（圆角是值重定非新增）。
10. **回归**：`npm run typecheck` 0 错；`npm test` 全绿（对拍基线）；五主题 × 明暗无破版（B4 矩阵）。

---

## 附：`:root` 增量段（paste-ready，插在「Chrome 仪器底座」段之后）

```css
/* ===== 换代表面/形状/光影（06-modern §2-§3；:root 一次，10 主题块零必改） ===== */
--surface-desk:  color-mix(in srgb, var(--bg-primary) 75%, var(--bg-tertiary) 25%);
--surface-panel: var(--bg-secondary);
--surface-card:  var(--bg-canvas);
--surface-well:  color-mix(in srgb, var(--bg-canvas) 88%, var(--bg-tertiary) 12%);
--surface-veil:  color-mix(in srgb, var(--bg-elevated) 86%, transparent);
--surface-sunken: var(--surface-well);   /* 改向（4 消费方） */
--surface-base:  var(--surface-panel);   /* 改向（0 消费方，规范名） */
--elev-1-shadow: var(--shadow-sm);
--elev-2-shadow: var(--shadow-sm), var(--shadow-md);
--elev-3-shadow: var(--shadow-sm), var(--shadow-lg);
--hl-top: inset 0 1px 0 color-mix(in srgb, #fff 5%, transparent);
/* 圆角 re-tier（§3.1 单点，全仓自动升档） */
--radius-xs: 0.375rem;  /* 6 */
--radius-sm: 0.5rem;    /* 8 */
--radius-md: 0.75rem;   /* 12 */
--radius-lg: 1rem;      /* 16 */
--radius-xl: 1.25rem;   /* 20 */
```

```css
/* :root.dark 追加两行（§2.1 暗档配方） */
--surface-desk: color-mix(in srgb, var(--bg-primary) 94%, #000);
--surface-well: color-mix(in srgb, var(--bg-canvas) 92%, #000);
```

# 文风页 UX 重设计（视觉/组件/布局层）

> 状态：**已施工**（2026-09-17 视觉归一批落地——§6 机检全过 + typecheck/vitest 370/build 四绿 + 浏览器浅/深三景目检通过；施工叙事见 `docs/incidents/style.md`）
> 前提：功能不变契约。本文只动视觉方言、组件形态、布局骨架；一切用户能力、数据行为、API 契约保持原样。
> 现状权威：代码（本文成稿前已逐行通读 `StyleView.vue` + 13 个 presentation 组件 + `style.css` token 全集 + `Icon.vue` 图标清单）。

---

## 1. 范围 / 目标 / 不动清单

### 范围（施工涉及文件）

| 文件 | 施工性质 |
|------|----------|
| `frontend/src/features/style/containers/StyleView.vue` | 容器模板重排（栏头补齐、实验室换形态、工坊分区），script 零改动 |
| `frontend/src/features/style/presentation/` 下 13 个组件 | 全部视觉方言归一；4 个靶场批组件（StyleBanList / StyleRulesSwitches / StyleSandboxSection / StyleContractsSection）结构性重写样式；其余组件样式修订 + emoji→Icon |
| `frontend/src/style.css` | 仅增量新增 1 个全局工具类 `.style-eyebrow`（组眉标）；不改任何既有 token 值 |

### 目标（本轮要解决的问题）

1. **消灭第二视觉方言**：靶场批 4 组件的 px 单位、`var(--不存在的token, #hex)` 二参回退、浅色硬编码——深色主题白卡穿帮的根因。全页归一到既有 token 方言。
2. **列头对称**：左列补上与右列「写作底线」对等的栏头，两列完全同构。
3. **@media 清零**：StyleSandboxSection 内 `max-width:560px` 视口断点改 container query（容器 `stylepage` 已挂在 `.style-main`）。
4. **emoji 清剿**：逐枚裁定，语义/操作类全换 Icon 矢量，纯装饰字符保留清单化。
5. **实验室换形态**：保留「前台亲民工坊 + 深层 Beta 实验室」两层渐进哲学与「绝不主动打扰」默认值，但把极淡原生 `<details>` 升级为像样的折叠舱；状态条「试听」→ 展开 + 平滑滚动联动保留等价。
6. **尺寸纪律**：字号下限 `--text-xs`、图标钮 ≥24px、文字钮 ≥28px（`--control-h-*`）。

### 不动清单（施工红线，触碰即打回）

- **容器 script 语义零改动**：数据加载 / 2s 防抖自动保存 / 零状态坡道三幕（ramp/early/full 判据）/ 提炼流程（不落库红线）/ 采纳池收编（在飞守卫）/ 收件箱确认（overrides 链路）/ 试听 A/B 双发（bare 对照）/ 章级特例切换与 `?chapter=` 深链 / 规矩开关与整文编辑保存（整体覆盖写）/ 禁词扫描审稿三动作（apply/collect/ignore）/ `openBetaLab()` 展开+滚动。script 一个字不动，只动 template 与 scoped style。
- **13 个组件承载的用户能力一项不少**（清单见第 4 节逐组件规格；以代码为准）。
- 两个模态继续走全局 `ModalShell`（焦点陷阱/Esc 栈），不改壳。
- 零状态 ramp 整页唯一邀请（hero）形态保留。
- 不碰后端 / API / 路由；不新增 npm 依赖；不重设计其他页面。
- `style.css` 只允许增量加 `.style-eyebrow` 一个工具类；**不得改动任何既有 token 值**。
- 五主题（paper/minimal/soft/pro/anime）× 明暗 10 态全部成立：禁止 `var(--x, #fallback)` 二参、禁止裸 hex（`#fff` 字样面色也在禁列，用 `var(--bg-canvas)`）、禁止只给暖纸画装饰；混色一律 `color-mix(in srgb, var(--token) N%, …)`。
- 响应式一律 `@container stylepage`；`:focus-visible` 全局托底，不自定义裸 focus；文案遵守产品术语口径（「谋篇/锚点/岔路」禁用；「亲笔字帖/写作底线/收编/黄金片段/这不像我/A·B 试写」等品牌词保留）。

---

## 2. 全局节：统一视觉方言

### 2.1 方言裁决：一套 token 方言（消灭靶场批方言）

全页（含 4 个靶场批组件）统一使用成熟方言：间距 `--space-*`（4px 基栅）、圆角 `--radius-*`、字阶 `--text-*`、表面阶梯 `--surface-*`、线阶 `--line*`、状态八件套、`--control-h-*` 控件几何、`--dur-2/--ease-out` 动效。px 一律退役（`1px` 描边/hairline 除外）。

**不存在 token 的替换映射表（施工逐处对号）**：

| 靶场批现行写法 | 替换为 | 语义说明 |
|---|---|---|
| `var(--accent-warm, #c8871a)` | `var(--warn)` | 「本书定制」徽标 / 整文定制提示文字 |
| `var(--accent-warm-soft, #f7e8cd)` | `var(--warn-bg)` | 同上底色 |
| `var(--bg-subtle, #f0eee9)` | hover 行 `var(--state-hover)`；徽标底 `var(--bg-tertiary)` | 按用途分派 |
| `var(--bg-card, #fff)` | `var(--surface-card)` | 卡面 |
| `var(--bg-input, #fbfaf8)` | `var(--field-bg)` | 输入框面 |
| `var(--danger-soft, #f9e3e0)` | `var(--danger-bg)` | 危险 hover 底 |
| `var(--text-link, #4a6fa5)` | `var(--accent-500)` | 链接 |
| `var(--text-tertiary, #9a958d)` | 承载信息的用 `var(--text-muted)`；纯装饰的用 `var(--text-faint)` | 按信息负荷分派 |
| `var(--accent, #4a6fa5)` | `var(--accent-500)` | accent 主档 |
| 裸 `#fff`（fire-btn / ban-chip 字色） | `var(--bg-canvas)` | 彩底上的字 |
| `rgba(0,0,0,0.18)` 影 | `var(--elev-2-shadow)` | 浮起 chip |
| 裸 `8px/10px` 圆角 | `--radius-sm(8) / --radius-md(12)`；10px 一律收编到 8 或 12 | 单点归档 |

容器侧遗留同病一并清：`.lab-summary` 内 2 处 `var(--text-tertiary, #…)` 二参按上表替换。

### 2.2 卡片体系（全页归一到 style.css 既有卡档）

| 卡档 | 用途（本页） | 现状 → 目标 |
|---|---|---|
| `.card-std` | 上传卡、样本卡、写作规矩卡、A/B 靶栏、契约卡、收件箱卡、扫描命中卡 | 样本卡/收件箱卡已是同类形态（token 化），直接换挂工具类或保持等价 scoped 值；靶场批 4 组件的卡从 px/二参方言整体换血 |
| `.card-well` | 指纹指标格（现状已挂，保持） | 保持 |
| `.card-hover` | 可点卡 hover 微抬（-2px + elev-2 影，04-A2） | 样本卡保留微抬；行类条目（禁词行/收件箱行）**不挂**——行用 `var(--state-hover)` 底即可（就地编辑卡不抬升的先例：ChapterCard） |
| 透明 hover 行 | 禁词行、陈词库行 | hover `background: var(--state-hover)`，`border-radius: var(--radius-sm)` |
| `.paper-card` | 不用 | 纸面卡是文书语义专用，本页不引入 |

卡内凹槽（台账/hint 区）用 `var(--surface-well)` + `var(--well-inset)` 语义，不再自造。

### 2.3 字阶 / 字距

- 全页字号**只允许** `--text-xs`(12) ~ `--text-3xl`，正文默认 `--text-base`/`--text-sm`；12px 行高 ≥ `var(--lh-compact)`，正文 `--lh-normal`。
- 展示大数字（指纹指标值、字数）沿用 04-B4「页码感」：`font-family: var(--font-heading)` + `.tnum`。
- 眉标新增工具类（唯一允许的全局增量）：

```css
/* 组眉标：栏内小组标题（列头之下的次级分组名），非分区标题 */
.style-eyebrow {
  font-size: var(--text-xs);
  letter-spacing: var(--tracking-eyebrow);
  color: var(--text-muted);
}
```

### 2.4 按钮体系

| 档 | 规格 | 本页用 |
|---|---|---|
| 主钮 `.btn-primary`（各组件 scoped 已有同名，统一规格） | `min-height: var(--control-h-sm)`(28)；`padding: 0 var(--control-px)`；`--text-base`；`background: var(--accent-500)`，字 `var(--bg-canvas)`；hover `var(--accent-600)`；`border-radius: var(--radius-sm)`；disabled opacity .5 | 存入样本库 / 开始提炼 / 扫描本章 / 保存 / 现场试写 / 收为样本 |
| 次钮 `.btn-ghost` | 同几何；透明底、`1px dashed var(--border-color)`、`--text-secondary`；hover 字与虚线变 `var(--accent-500)/--accent-400` | 从章节收编 / 导入黄金片段 / 取消 / +添加 |
| 文字链 `.btn-link` | `--text-xs`，字 `var(--accent-500)`，hover 下划线 | 展开全文 / 填入系统默认文本 |
| 图标钮 `.icon-btn`/`.icon-danger` | `width/height ≥ 24px`（`--control-h-xs` 20px 仅行内微钮，本页删除 20px 档全升 24）；透明底、radius-xs；hover `var(--state-hover)`；danger 变体 hover `var(--danger-bg)`/`var(--danger)` | 编辑/删除样本、删除禁词、忽略候选 |
| 档位 chip `.sev-toggle` | 文字钮待遇：`min-height: var(--control-h-sm)`(28)（现 20/24px 全部升级）；pill；提醒档 `var(--warn)/var(--warn-bg)`，硬禁档 `var(--danger)/var(--danger-bg)` | 硬禁⇄提醒 |
| 特殊：`+ 拦截` | 实体钮 28px；现 `+` 前缀退役（加号是工程记号），文案「加入拦截」 | 禁词输入组 |

### 2.5 chip 体系

- 语义 chip（徽标/计数）：`padding: 0 var(--space-2)`（纵向 0，高度由行高托底 ≥20px）、`--text-xs`、`border-radius: var(--radius-xs)`；配色对：场景=`var(--info)/var(--info-bg)`，来源=`var(--ok)/var(--ok-bg)`，早期=`var(--text-secondary)/var(--bg-tertiary)`，Beta=`var(--info)/var(--info-bg)`，命中计数=`var(--danger)/var(--danger-bg)`、零命中=`var(--text-faint)/var(--bg-tertiary)`，硬禁=`var(--danger)/var(--danger-bg)`。
- 字数 chip：同几何 + `.tnum` + `font-heading`（页码感，身份层件②）。

### 2.6 分区标题体系

- **分区标题**（13 个组件的 `sec-head/sec-title`）：吃全局 `.sec-head/.sec-title`（❦ 小节符 + 短钉线，`--text-lg`/`--font-heading`），保持。
- **栏头**（容器 workshop 双列的列级标题）：与分区标题同规格 `.sec-head/.sec-title`，左右对称（解决列头不对称）：左「亲笔字帖」、右「写作底线」。栏头带一枚语义 Icon（`.sec-title` 的 gap 已留，`--icon-md`）。
- **组眉标**（栏内次级分组，如「已拦截的禁词（N）」）：新增 `.style-eyebrow`，比栏头低一档，不再用 15px 伪 sec-title。

### 2.7 emoji → Icon 裁决表

| 位置 | 现状 | 裁决 | 替换 |
|---|---|---|---|
| 右列栏头 | 🛡️ | 语义（列身份） | `Icon name="no-symbol"` |
| 左列栏头 | （无，补齐） | 语义 | `Icon name="pencil-square"` |
| 实验室 summary | 🧪 | 语义 | `Icon name="light-bulb"` |
| 状态条试听钮 | ▶ | 操作 | `Icon name="play"` + 文案「去实验室试听」 |
| 靶场开火钮 | 🎯 | 装饰（文案已自明） | **删除**，纯文字「现场试写两句对比」 |
| 划词入禁浮 chip | 🚫 | 操作 | `Icon name="no-symbol"` + 「添入禁词库」 |
| 采纳池头 | 🪶 | 语义（AI 产物） | `Icon name="sparkles"` |
| 收藏星 | ★/☆ | 状态 | `Icon name="star"`（激活态 `--warn`，未激活 `--text-faint`） |
| 陈词库折叠 | ▾/▸ | 状态 | `Icon name="chevron-down/chevron-right"` |
| 收件箱改词 | ✎ | 操作 | `Icon name="pencil-square"` |
| 删除/关闭 | ✕（ban/negative 行内文字符） | 操作 | `Icon name="x-mark"` |
| 词→替代 连接符 | ➔ / → 两种字形混用 | 语义连接符但属排印 | 统一内联 `Icon name="arrow-right"`（`--icon-sm`，色 `var(--text-faint)`），全页一个字形 |
| 分区标题 ❦ | ::before 伪元素 | 既有品牌装饰语言（04-B1） | **保留** |
| 「→ 替代」静态说明（inbox-alt 等） | 文字 → | 排印 | 同上统一 arrow-right Icon |

### 2.8 间距 / 动效节奏

- 区块纵向节奏：`--space-6`（组间）/ `--space-8`（区间）；卡内 padding `--space-3`（卡档工具类已定）；控件组内 `--chrome-gap`/`--space-2`。
- 动效只用 `transition: … var(--dur-2) var(--ease-out)`；hover 微抬仅限可点卡；折叠开合**不做高度动画**（details 原生瞬开），仅 chevron 旋转 `var(--dur-2)`；无滤镜堆叠。

### 2.9 页面身份层：「习字簿」（加分项，低成本落四件）

文风页此前无身份（写作台=纸面、世界页=古地图、书架=书封）。本轮立**习字簿/字帖**隐喻，全部 token 化、四件封顶、单件成本都是「字体/边线/chip」级：

1. **样本衬线化**：样本卡正文、采纳池摘录、收件箱样本候选摘录改 `font-family: var(--editor-font-family)`（宋体系=字帖墨迹感），`--lh-normal` 偏疏。纯字体声明，十态自动成立。
2. **量尺字数 chip**：样本卡字数走 2.5 节「页码感」规格（衬线 + `.tnum`），像字帖页边的尺寸标注。
3. **朱批tick**：硬禁档的禁词行加 `box-shadow: inset 2px 0 0 var(--cinnabar-bright)`（朱砂左缘=红批改订记，`--cinnabar-bright` 是浅深恒定签名色，十态成立）；提醒档无 tick。仅 2px 内影，零滤镜。
4. **图尺基线**：指纹直方图底线与对账图坐标感统一用 `var(--line-strong)`（现直方图已是 `color-mix(--text-muted 40%)`，归账到 `--line-strong`）；直方图柱保留 accent 渐变（token 输入）。

不做：大面积纸纹/渐变背景/滤镜。装饰超过此四件的施工直接打回。

---

## 3. 布局节

### 3.1 页面骨架（full 态，ASCII）

```
┌────────────────────────────────────────────────────────────────────┐
│ ← │ 文风设定 · 《书名》                              [已保存/保存中…] │  页面头（不动）
├────────────────────────────────────────────────────────────────────┤
│ 已测 12 条样本 · 句长起伏 0.62（健康）· 对话占比 31%   [▶去实验室试听] │  状态条 sticky（full 态）
│ ┌ 样本攒够 3 条了——要不要提炼一份文风画像？      [开始提炼] ┐        │  suggest banner（条件）
├───────────────────────────────────┬──────────────────────────────────┤
│ ❦ 亲笔字帖 ✎                      │ ❦ 写作底线 ⊘                      │  ← 栏头（本轮补齐，对称）
│ ┌ 上传卡（贴入区+场景/时期+存入） ┐ │ ┌ 写作规矩卡（title+徽标+开关组）┐ │
│ ├ 样本卡（衬线正文+meta 行）×6   ┤ │ ├─ 已拦截的禁词（N）───────      │ │  ← 组眉标
│ │  …展开其余 N 条                │ │ │ 禁词行（词→替代 · 档位 · 删） │ │
│ └ 采纳池（虚线舱，可展开）        ┘ │ │ 禁词行 …                       │ │
│                                   │ └ [输入词…][加入拦截]           ┘ │
├───────────────────────────────────┴──────────────────────────────────┤
│ ❦ 文风收件箱 (N)  · 候选卡（✓收进样本库/收入清单 · ✗忽略 · 词块就地改写）│  有候选才渲染（不动）
├────────────────────────────────────────────────────────────────────┤
│ ▾ 💡 文风实验室  Beta                              A/B 试写·指纹·对账·全量负面清单 │  ← 折叠舱（默认合）
│ ────────────────────────────────────────────────────────────────── │
│   ❦ A/B 试写靶场   [引子输入……………][现场试写两句对比]                  │
│   ┌ 基准输出（无范本与画像）┐  ┌ 文风装载输出（含范本画像规矩）┐        │
│   ❦ 写作规矩（整文编辑）  契约卡（展开全文/编辑/恢复默认）            │
│   ❦ 笔迹指纹（5fr）        │  ❦ 逐章核对（7fr）                      │  duo 5:7
│   ❦ 负面清单（全量面+陈词库+扫描审稿入口）                            │
└────────────────────────────────────────────────────────────────────┘
```

ramp 态：整页仅 hero 邀请（现有 `.ramp-mode` 垂直居中），不动。early 态渲染分支保持代码现状。

### 3.2 断档（container query，容器名 `stylepage` 已挂 `.style-main`）

| 阈值 | 行为 | 现状 |
|---|---|---|
| `max-width: 60rem` | 工坊双列塌单列（右列 hairline 从左边线改虚线上边线）；实验室内 duo（指纹/对账）塌单列 | 已有，保持 |
| `max-width: 48rem` | **新增**：靶场 A/B 双栏塌上下堆叠、引子输入组纵排 | 现为 `@media (max-width:560px)`，**必须改 `@container stylepage`**（S-03 红线） |

### 3.3 实验室新形态：分段折叠舱（哲学不变，形态升级）

- 保留 `<details>/<summary>` 原生语义（零 JS 风险、`@toggle` 受控回写、`ref` 滚动锚点三件套接口不变），只重视觉：
  - summary 常态 = 一条 `--control-h-lg` 级舱盖条：`background: var(--surface-panel)`、`border: 1px solid var(--line-faint)`、`border-radius: var(--radius-md)`、`padding: var(--space-3) var(--space-4)`；内容 = `chevron-right/down`（开合旋转）+ `light-bulb` Icon + 「文风实验室」(`--text-base` 600) + 右侧 `Beta` chip（`--info/--info-bg`）+ 一行 `--text-xs --text-muted` 内容预告（「A·B 试写 · 笔迹数据 · 逐章核对 · 负面清单全量」）。
  - `[open]` 时 summary 下缘加 hairline（`border-bottom: 1px solid var(--line-faint)`），舱体保持同卡不抬升。
  - 合盖文案兜住「绝不主动打扰」：默认折叠、无呼吸动效、无徽标闪烁。
- 舱内分区：沿用容器 `.section-row` hairline 分隔（靶场 → 规矩整文 → 指纹|对账 duo → 负面清单），段距 `--space-8`。
- **联动**：状态条按钮（`@audition="openBetaLab"`）语义不变——置 `labOpen=true` + `nextTick` 平滑滚动到舱。滚动锚点从 `<details>` 改为舱的 `summary`（视觉落点更准，`scroll-margin-top` 保持 4.5rem 语义）。

### 3.4 工坊双列（前台主视界）

- 两列 50/50、`gap: 0 var(--space-10)`、中缝 `--line-faint` 左边线（窄档换虚线上边线）——几何不动，**只补齐左栏头**。
- 栏头之下：左列 = StyleSampleSection（去内部重复标题）+ StyleAdoptedPool；右列 = StyleRulesSwitches（去内部重复标题）+ 组眉标「已拦截的禁词（N）」+ StyleBanList。
- 标题层级收敛：栏头（sec-title 级）全页仅 2 枚；组件内不再自称「亲笔字帖」「写作规矩」分区标题（卡片自带 title/语境），「已拦截的禁词」降为 `.style-eyebrow` 组眉标。

---

## 4. 逐组件规格

### 4.1 StyleView.vue（容器）

- **现状**：右列有 `.col-title`「🛡️ 写作底线」，左列无栏头；实验室 = 极淡 details；`.lab-summary` 有 2 处二参 var。
- **设计**：
  - 模板：workshop 两列各挂 `.sec-head`/`.sec-title` 栏头（左 = pencil-square Icon + 亲笔字帖；右 = no-symbol Icon + 写作底线），删除 `.col-title`。组件内部标题随 4.2/4.3/4.4 去除。
  - 实验室 summary 按 3.3 节重写（Icon + 标题 + Beta chip + 内容预告），`@toggle`/`ref`/`:open` 三件套保留。
  - ramp hero / suggest banner / loading / section-row / duo 几何不动；`.lab-summary` 二参清零。
- **施工位**：template workshop 段 + details 段；scoped style `.col-title` 删、`.lab-summary` 重写。
- **注意**：script 零改动；栏头文字就是组件原标题的平移（左栏头「亲笔字帖」取自 StyleSampleSection 现 sec-title，避免双标题）。

### 4.2 StyleSampleSection.vue（亲笔字帖）

- **现状**：成熟方言；内部 sec-title「亲笔字帖」；emoji 仅 ★/☆。
- **设计**：保持结构与全部能力（hero 邀请 / 上传卡三入口 / 样本卡就地编辑·收藏·场景·时期 / 6 条收展）。① 常态分支删 `.sec-head`（栏头接管）；② `fav-btn` 的 ★/☆ → `Icon name="star"`（active `--warn`，idle `--text-faint`），按钮 24px；③ `.sample-content` 衬线化（身份层①），`--text-xs` 下限保持；④ 字数 chip 升量尺规格（身份层②）。
- **施工位**：template meta 行；scoped `.fav-btn/.sample-content/.chip`。
- **注意**：ramp 分支 hero 一行不动（零状态唯一邀请红线）；样本编辑态/era 切换逻辑零改动。

### 4.3 StyleAdoptedPool.vue（采纳池）

- **现状**：方言基本合规（BEM + token），🪶 emoji，`--text-sm` note。
- **设计**：🪶 → `sparkles` Icon；摘录衬线化（身份层①）；「收为样本」钮已是 28px 描边 accent 档，保持；整池维持虚线舱（`border: 1px dashed var(--border-color)`）。
- **施工位**：head 行 template；scoped 图标行。
- **注意**：在飞守卫 busyId 语义不动。

### 4.4 StyleRulesSwitches.vue（写作规矩开关）——靶场批重写

- **现状**：px 值 + 全套不存在 token 二参；内部 sec-title「写作规矩」与栏头重复。
- **设计**：① 删 `.sec-head`（规矩卡自带 `contract.title` 卡头，栏头「写作底线」已兜住分区身份）；② 卡 = `.card-std` 等价 scoped（`--surface-card` 底、`--line-faint` 边、`--radius-md`）；customized 态描边 `var(--warn)`；徽标「系统默认」`var(--text-secondary)/var(--bg-tertiary)`、「本书定制」`var(--warn)/var(--warn-bg)`；整文定制提示条 `var(--warn)/var(--warn-bg)` + `--radius-sm`；③ 开关行：高度 `--control-h-sm`、hover `var(--state-hover)`、checkbox `accent-color: var(--accent-500)` 16px（现 14px 升 16 保点击）、行字 `--text-base`；「在岗/已关」`--text-xs`（已关 danger 语义保持）。
- **施工位**：全 scoped 重写；template 仅删 header。
- **注意**：textCustomized 让位逻辑、emit 签名不动。

### 4.5 StyleBanList.vue（禁词清洗库）——靶场批重写

- **现状**：px + 不存在 token 重灾区；标题 15px 伪 sec-title；➔ 字形；✕ 文字符；12px 输入组。
- **设计**：① 标题降 `.style-eyebrow`「已拦截的禁词（N）」；② 行：透明 hover 行（`--state-hover`），硬禁行加朱批 tick（身份层③），行高 ≥28px、字 `--text-base`（词 600 `--text-primary`，替代 `--text-secondary`）；「词→替代」arrow-right Icon 统一；档位 `.sev-toggle` 按 2.4 升 28px；删除 `.icon-danger` 升 24px 换 x-mark Icon；③ 输入组：input `--field-bg` 面 + `--line` 边 + focus `--accent-400`（删裸 `:focus` outline:none，交 `:focus-visible` 托底），「加入拦截」实体钮 28px；④ 空态文案保留。
- **施工位**：全 scoped 重写；template 仅换图标/文案。
- **注意**：add/remove/toggle emit 与去重提示链路由容器兜底，不动；`activeItems()` 沉底逻辑不动。

### 4.6 StyleSandboxSection.vue（A/B 试写靶场）——靶场批重写

- **现状**：px + 不存在 token + `color:#fff` 裸值 + `@media (max-width:560px)` 回归 + 🎯/🚫 emoji。
- **设计**：① 引子行：input `--field-bg/--line`、高 `--control-h-md`(32)，开火主钮 28px+ 纯文案「现场试写两句对比」；② A/B 双栏卡 `.card-std` 等价：基准栏常态、装载栏描边 `--accent-500`（语义保留），栏标签 `--text-xs` 600 + 副标 `--text-faint`，正文 `--text-base` `--lh-normal` 偏疏、placeholder `--text-faint`，流式 caret 保留；③ 划词浮 chip：`--danger` 底 + `var(--bg-canvas)` 字 + `Icon no-symbol` + `var(--elev-2-shadow)`；④ hint 行 `--text-xs --text-muted`；⑤ **@media 删**，改 `@container stylepage (max-width: 48rem)`（3.2）。
- **施工位**：全 scoped 重写；template 换图标。
- **注意**：划词选区安全四件套（容器包含判定 / 1~20 字闸 / selectionchange 文档监听 / removeAllRanges）逐行保留；emit 签名不动。

### 4.7 StyleContractsSection.vue（规矩整文编辑）——靶场批重写

- **现状**：px + 不存在 token + `#fff`。
- **设计**：卡 `.card-std` 等价 + customized 描边 `var(--warn)`；徽标同 4.4 映射；正文 `pre` `--text-sm` `--lh-normal`（现 12px 升 13，读长文更稳）；clamp 展开机制不动；编辑 textarea `--field-bg`；按钮组归 2.4 体系（btn-link 文字链 / btn-ghost / btn-primary 28px）。
- **施工位**：全 scoped 重写；template 零改动（按钮文案已合规）。
- **注意**：`defineExpose({closeEdit, unlock})` 与 busy 置位契约（复位全靠容器）一字不动。

### 4.8 StyleStatusStrip.vue（状态条）

- **现状**：基本合规；「▶ 试听」文字符。
- **设计**：▶ → `Icon play`(--icon-sm) + 文案「去实验室试听」；钮高 `--control-h-sm`；strip 底色 veil + backdrop blur 保持；数字句不动。
- **施工位**：template 按钮；scoped `.status-audition` 改 inline-flex 对齐图标。
- **注意**：`@audition` 联动 openBetaLab 语义不动（3.3）。

### 4.9 StyleFingerprintSection.vue（笔迹指纹）

- **现状**：成熟方言；直方图基线 `color-mix(--text-muted 40%)`；`field-readonly` 12px。
- **设计**：保持，仅：① 直方图基线归 `var(--line-strong)`（身份层④），柱渐变为 token 输入保持；② `.field-readonly/.field-textarea` 字号 `--text-xs` 保持；③ 高级面板折叠 toggle 的 chevron 已合规。
- **施工位**：scoped `.hist-plot` 一行。
- **注意**：高级面板（章级特例/字段锁/全部锁定/提炼入口/段落节奏）整块能力不动。

### 4.10 StyleReconciliationSection.vue（逐章核对）

- **现状**：成熟方言；SVG 数据驱动；summary 列表 12px。
- **设计**：保持，仅图卡基线/坐标归 `--line-strong` 口径（band `--ok 12%`、线 `--accent-500`、出带点 `--danger` 全保留）。
- **施工位**：无（或 scoped 注释级对齐）。
- **注意**：几何纯函数（buildPolyline/bandRect/pointCoords）与「只呈现事实」总结文案不动。

### 4.11 StyleNegativeSection.vue（负面清单全量面）

- **现状**：成熟方言 + container query 已有；➔/✕/▾▸ 文字符；`.sev-toggle` 24px 偏小。
- **设计**：① 连接符/删除/折叠按 2.7 换 Icon（arrow-right / x-mark / chevron）；② `.sev-toggle` 升 `--control-h-sm`；③ `hit-chip` 配色保持（danger 族/faint 零命中）；④ 陈词库展开面板保持（`--surface-overlay` 底、260px 内滚）。
- **施工位**：template 行内文字符三处；scoped 档位钮几何。
- **注意**：双档 grid（默认两行式 / 60rem 塌单行五件）与容器查询保持；豁免划线/置灰语义不动。

### 4.12 StyleInboxSection.vue（收件箱）

- **现状**：成熟方言；✎ 文字符。
- **设计**：✎ → `pencil-square` Icon；可编辑词块的下划虚线交互提示保留；其余保持（`--warn` 徽标族、摘录衬线已合规，归入身份层①同口径）。
- **施工位**：template 一处；scoped `.btn-edit-word` 24px。
- **注意**：就地改写→overrides 确认链路、watch 清理 editedWords 防串候选，不动。

### 4.13 StyleExtractModal.vue / 4.14 StyleScanModal.vue（两模态）

- **现状**：均走 ModalShell；基本合规。
- **设计**：保持，仅按钮统一 28px 起（已合规）与字阶抽查；ScanModal 命中卡三裁决钮（替换/仅收入清单/忽略）配色语义保持。
- **施工位**：无结构性改动。
- **注意**：ModalShell 壳、Esc 栈、emit 签名不动。

---

## 5. 接口变更清单

**零接口变更。** 全部 13 个组件 props/emits/defineExpose 签名保持；容器 script 零改动；唯一「新接口」是 `style.css` 增量工具类 `.style-eyebrow`（纯样式，无 JS 面）。

---

## 6. 验收清单

### 可 grep（CI 可机检）

- [ ] `frontend/src/features/style/` 全目录 grep `var\(--[a-z-]+,\s*#` → **0 命中**（二参回退清零）
- [ ] grep 不存在 token 名 `--accent-warm|--accent-warm-soft|--bg-subtle|--bg-card|--bg-input|--danger-soft|--text-link|--text-tertiary` → **0 命中**（style.css 本就没有定义，组件侧消费清零）
- [ ] grep 裸 hex（`#[0-9a-fA-F]{3,6}`）→ 0 命中（含 `#fff` 字面色）
- [ ] grep `@media` → 0 命中（style/ feature 内；prefers-reduced-motion 属 style.css 全局既有，不在本目录）
- [ ] grep `font-size:\s*(0\.[0-6][0-9]*rem|1[01]px|10px)` → 0 命中（≥12px 下限）
- [ ] grep `style.css` diff → 仅新增 `.style-eyebrow` 一个选择器，无 token 值改动
- [ ] `npm run typecheck` + `npm run build` 通过；前端 vitest 全绿

### 可目检（十态走查）

- [ ] 五主题 × 明暗 10 态逐态过版：工坊、实验室展开态、靶场双栏、扫描模态无白卡/深字穿帮
- [ ] 列头对称：左右栏头同规格（❦ + Icon + 标题），中缝 hairline 两列同视觉权重
- [ ] 实验室默认折叠、舱盖条规整；状态条「去实验室试听」点击 = 展开 + 平滑滚动到舱
- [ ] emoji 清零：🛡️🧪🎯🚫🪶★☆▾▸✎✕➔ 全替换（❦ 伪元素保留属预期）
- [ ] 点击目标：图标钮 ≥24px、文字钮 ≥28px（抽查 sev-toggle / btn-exempt / icon-danger / fav）
- [ ] 朱批 tick 只在硬禁行左缘、2px、十态可见
- [ ] 样本正文衬线化三处（样本卡/采纳池/收件箱摘录）一致

### 功能回归点（人工过一遍）

- [ ] ramp → 贴 1 条 → early → 3 条+画像 → full 三幕生长与 `suggestExtract` 浮出
- [ ] 上传/编辑/收藏/场景/时期/删除样本 + 从章节收编 + 导入黄金片段（含计数递减）
- [ ] 提炼弹窗预填最长 3 条 → 回填 + 锁定字段不覆盖 + toast
- [ ] 禁词回车/按钮入禁、去重提示、档位切换、删除（2s 防抖落库）
- [ ] 规矩开关逐条 toggle（busy 防连点）、整文编辑保存/取消/恢复默认、整文定制态开关让位提示
- [ ] 试听 A/B 双流 + 划词入禁（选区越界不响应）
- [ ] 收件箱 ✓（含改写后 overrides）/✗
- [ ] 扫描审稿三动作（替换落正文 / 仅入清单 / 忽略）+ 已处理置灰
- [ ] `?chapter=` 深链直达章级特例；恢复继承书级
- [ ] 采纳池收编（双击不重复入库）

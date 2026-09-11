# 第 1 期：文风页试点（UX 重构 · 设计规格）

> 前置：第 0 期 `00-foundation.md` 已施工完成（token 层 / z 层表 / 浮层规范 / 全局基础样式）。本文所有 token、层值、工具类均引自该文。
> 范围：`frontend/src/features/style/containers/StyleView.vue` + `presentation/` 11 个组件（9 分区 + StyleExtractModal + StyleScanModal）。另含一处全局组件修复（AppSettingsModal 死断点，§2.2-C）。
> 信息线纪律：分区顺序与信息架构**一行不动**——状态条 → 试听 → 提炼建议 → 「你的字+采纳池 | 笔迹指纹」→ 意图 → 「负面清单 | 逐章核对」→ 收件箱 → 长成预告。本期只修结构 bug、重排视觉层次、补深色、修交互细节。

---

## 1. 目标

把文风页做成地基的「验证样板间」：
1. 修掉 duo-measure 结构 bug（三子二列，「左贴字右测量」配对破裂）；
2. 三处死断点改 container query（适配 DPI 缩放小视口，§2.2）；
3. 视觉层次重排（分区标题体系统一、节奏拉开、密度达标但不压抑）；
4. 深色补全（feature 内 **0 处** dark: 类，29+ 处硬编码浅色全归 token）；
5. 小目标/滚动嵌套/SVG 变形/emoji 逐项修复。

---

## 2. 布局结构修复

### 2.1 duo-measure 结构 bug（StyleView.vue:837-872, 1078-1080）

**现状**：`.duo-measure` 声明 `minmax(0,5fr) minmax(0,7fr)` 两列，模板里却塞了 3 个平级组件（StyleSampleSection / StyleAdoptedPool / StyleFingerprintSection）→ 第三个（指纹）掉行独占一行，右 7fr 列空，「左贴字、右立刻看到测量」的啊哈配对破裂。`:1075-1077` 的 `:first-child` 分隔线规则同样因此错挂。

**修复（结构方案，唯一指定做法）**：左列两个组件收进一个 wrapper，网格恢复为恰两子：

```html
<div class="section-row duo duo-measure">
  <div class="duo-col duo-col--samples">
    <StyleSampleSection … />
    <StyleAdoptedPool … />
  </div>
  <StyleFingerprintSection … />
</div>
```

```css
.duo-col { display: flex; flex-direction: column; gap: var(--space-6); min-width: 0; }
```

- `.section-row.duo > :first-child { border-right: 1px solid var(--border-color); }` 规则不变，现在自然命中 wrapper（分隔线回到两列之间）。
- 采纳池归属左列的理由（设计判断）：「AI 写的、你留下的」是样本库的支流（收编入样本库），与「你的字」同族；指纹是测量层，独占右 7fr。
- `gap: var(--space-6)`（24px）分隔样本区与采纳池；采纳池上下不再自带外边距（施工时摘除其 margin-top，间距归 wrapper）。

**验收**：两列同顶对齐；右列指纹卡左缘与分隔线间距 = `gap 2.5rem`；采纳池不再把指纹挤掉行。

### 2.2 死断点 → container query（三处）

**为什么媒体查询在这里系统性失效**：断点应按「内容容器可用宽」响应，而 `@media` 量的是视口——Electron 下视口被 rail/抽屉/DPI 缩放三重侵蚀（1366@125% → CSS 视口 1093px，击穿 minWidth 1200），视口宽度与内容宽度脱钩。Chromium（Electron 28 = Chrome 120+）原生支持 container query，零依赖。

**A. 文风页双栏塌列**（StyleView.vue:1085-1093 `@media (max-width: 74rem)`）：

```css
.style-main { container-type: inline-size; container-name: stylepage; }

@container stylepage (max-width: 60rem) {
  .section-row.duo { grid-template-columns: 1fr; }
  .section-row.duo > :first-child {
    border-right: none;
    border-bottom: 1px dashed var(--border-color);
  }
}
```

- 容器挂在 `.style-main`（页滚动容器，宽度=rail 之外的可用宽），**不是** `.style-column`（max-width 96rem 居中列——它在大窗下与可用宽脱钩）。
- 阈值从 74rem 改 **60rem**：判据=两列各得 ≥ 约 28rem 可用宽度（5fr→约 25rem 起可排样本卡；74rem 是「理想动线」阈值不是「可用」阈值，在 minWidth 1200 下永不触发=DPI 用户永远拿到挤爆的两栏）。60rem 容器宽（约 rail 64px + 视口 ≥ 1024px）以下单列。
- 塌列时左列底部分隔改虚线的既有规则保留。

**B. 试听横条双轨**（StyleAuditionBar.vue:209-213 `@media (max-width: 640px)`）：

```css
@container stylepage (max-width: 48rem) {
  .bar-results { flex-direction: column; }
}
```

A/B 双轨并排需要各 ≥ 约 24rem 才能放下对照文本；挂同一 `stylepage` 容器（组件是 style-column 后代，查询命中最近祖先容器）。

**C. 设置弹窗分区**（AppSettingsModal.vue:1032-1039 `@media (max-width: 640px)`，全局组件顺带修复）：
弹窗卡宽度被 max-width 封顶，视口断点语义错误。改在弹窗卡自身挂容器：

```css
.settings-card（弹窗卡根类）{ container-type: inline-size; }
@container (max-width: 40rem) { /* 原 640px 规则平移，选择器不变 */ }
```

弹窗卡宽度稳定（约 42rem 封顶），容器查询行为确定。**【此条为审计列出的死断点批量修复的一部分，归第 1 期执行】**

### 2.3 窄视口行为基线（DPI 场景验收锚）

- 1093px CSS 视口（1366@125%）：stylepage 容器 ≈ 1093-64(rail) ≈ 1029px = 64rem → **双栏保持**（60rem 阈值之上），每列约 27/37rem，可用。
- 1280×720（1920@150%）：容器 ≈ 1216px = 76rem → 双栏正常。
- 竖屏/分屏 < 1024px 可用宽：单列，虚线分隔。
- 验收以 DevTools device toolbar 三档实测为准。

---

## 3. 视觉层次重排（信息线不动）

### 3.1 分区标题体系（全局工具类，写入 style.css）

现状：`.sec-head`/`.sec-title` 在 5 个组件 scoped 里重复定义、值不一。提升为全局工具类（第 2/3 期页面复用）：

```css
.sec-head {
  display: flex; align-items: baseline; gap: var(--space-3);
  margin-bottom: var(--space-4);
}
.sec-title {
  font-family: var(--font-heading);
  font-size: var(--text-lg);       /* 16px，现各组件 14-15px 不一 */
  font-weight: 600;
  color: var(--text-primary);
}
.sec-hint {
  font-size: var(--text-sm);       /* 13px */
  color: var(--text-secondary);
  line-height: var(--lh-normal);
}
```

施工：5 个组件删 scoped 重复定义，模板类名不变（零模板改动优先）；标题右跟随的一行用途说明统一 `.sec-hint`（没有的补上，文案沿用各组件既有副标题，不新造文案）。

### 3.2 节奏与间距

- `.section-row` 分区垂直 padding 统一 `var(--space-8) 0`（32px；现状 8-12px 过挤，是「一屏塞太满」观感的直接来源）。首个分区 `padding-top: var(--space-4)`。
- 分区内部：卡片间距 ≥ `var(--space-2)`；输入区行距 ≥ `var(--space-3)`。
- `.style-column` 96rem 封顶与 clamp 侧 padding 保留（流式宽度策略不动）。
- hairline 分隔归容器的现有约定保留；塌列时虚线规则保留。

### 3.3 页头与状态条

- `.page-title` 1rem → `var(--text-xl)`（18px，衬线）；`.book-name` 0.75rem → `var(--text-sm)`。
- `.save-badge` 四态色归 token（§5 映射表）；字号 0.625rem → `var(--text-xs)`；min-height 20px，padding `0.125rem 0.5rem` 保留。
- `.anchor-btn` 字号 → `var(--text-sm)`；点击目标：padding 调至 `0.375rem 0.875rem`（≥28px 高）；激活态（当前锚点）加 `color: var(--accent-500)`——现为纯跳转无态，保留无态即可（滚动监听不在本期范围）。
- StyleStatusStrip：`z-index: 5 → var(--z-sticky)`；`status-text` → `var(--text-sm)`；`status-audition` 按钮 ≥28px 高，字号 `var(--text-xs)`，保留 ▶ 前缀（品牌作者语言，非 emoji 体系违例）。

### 3.4 提炼建议条（suggest-banner）

结构不动；字号 0.75rem → `var(--text-sm)`；`btn-suggest` ≥28px 高。色彩已是 color-mix token 写法，保留。

---

## 4. 分区逐项规格

> 通用规则（每项不再重复）：字号按 00 期 §2.1.1 映射表归档；色值按 §5 映射表归 token；点击目标 icon 按钮 ≥24px、主按钮 ≥28px；`:focus { outline:none }` 裸重置删除（全局 :focus-visible 已托底）。

### 4.1 StyleSampleSection.vue

| 项 | 现状 | 规格 |
|---|---|---|
| 滚动嵌套 | `.sample-list` max-height 24rem + overflow-y auto（:428-432） | **拆二级滚动**：删 max-height/overflow；默认渲染前 6 条，末尾「展开其余 N 条」/「收起」文字按钮（`var(--text-sm)`，accent 色，≥28px 高）。≤6 条时按钮不渲染。页滚动唯一 |
| badge 色 | badge-scene #1d4ed8/#dbeafe、badge-source #047857/#d1fae5、badge-early #6b7280/#f3f4f6（:457-464,590-606） | → `--info`/`--info-bg`、`--ok`/`--ok-bg`、`--text-secondary`/`--bg-tertiary`；字号 0.625rem → `var(--text-xs)` |
| 收藏钮 | #d1d5db → active/hover #f59e0b | → `var(--text-faint)` → `var(--warn)`；hit area 24×24（padding 补足） |
| 提示小字 | .upload-hint 0.6875rem | → `var(--text-sm)` |
| 删除钮 | .icon-danger 常驻可见 ✅ | 保留常驻；确认 hit area ≥24px |
| hero（ramp） | .hero-title 衬线大标题 | 字号归 `var(--text-3xl)`；邀请区垂直居中逻辑不动 |

### 4.2 StyleAdoptedPool.vue

| 项 | 现状 | 规格 |
|---|---|---|
| 字号 | count/toggle/time/wash 10-11px（:90-106） | count/note → `var(--text-sm)`；toggle/time/wash → `var(--text-xs)` |
| wash 色 | #047857 裸值（:106） | → `var(--ok)` |
| toggle 钮 | padding 0 6px、line-height 1.5 | 边框保留；min-height 24px、padding `0.125rem 0.5rem` |
| 头部 🪶 | 装饰性 glyph | **保留**（非状态载体；Icon 体系仅强制状态/操作图标——设计裁决，见 §6 注） |
| 收编按钮 | padding 2px 10px | min-height 28px；busy 态 opacity 0.5 + `cursor: default`（既有在飞守卫不变） |

### 4.3 StyleFingerprintSection.vue

| 项 | 现状 | 规格 |
|---|---|---|
| 🔒/🔓 emoji（:237） | 文本字符当状态图标 | **换 Icon 组件**：Icon.vue 新增 `lock-closed` / `lock-open`（Heroicons outline，path 见附录 B）；模板 `<Icon :name="lockedKeys?.includes(pk.key) ? 'lock-closed' : 'lock-open'" :size="14" />`；active 态 `color: var(--accent-500)`；按钮 24×24；title 文案不变 |
| 小字 | 6 处 0.625rem / 7 处 0.6875rem | 按角色映射（badge/计数→xs；hint 句→sm） |
| 指标格 hint | 两行不截断（S5 已修） | 保留；行高 `var(--lh-compact)` |

### 4.4 StyleKnobsSection.vue

| 项 | 现状 | 规格 |
|---|---|---|
| tier-btn ~22px | padding 0.25rem 0.5rem + 11px 字 | 字号 → `var(--text-xs)`（12px）；padding `0.375rem 0.625rem`；**min-height 28px**；active 态保留 accent 填充 |
| 预设/实测锚提示 | 既有 | 字号归档；「有意转型吗」提示色 → `var(--warn)`（若现是裸橙） |

### 4.5 StyleNegativeSection.vue

| 项 | 现状 | 规格 |
|---|---|---|
| 行内挤压 | `.neg-row` flex 单行不换行，词/替代词输入 flex 1 min-width 0 被 severity+hits+删除挤到不可读（:211-220） | **改 grid 两档**（见下） |
| btn-scan | #1d4ed8/#dbeafe、hover #bfdbfe 裸值 | → `color: var(--accent-500); background: color-mix(in srgb, var(--accent-500) 10%, transparent)`；hover mix 16%（扫描是主路径动作，用品牌色不用 info 蓝） |
| severity chip | 0.5625rem(9px) #b91c1c/#fee2e2（:362-367） | 字号 → `var(--text-xs)`；色 → `--danger`/`--danger-bg`（硬禁）；提醒档 → `--warn`/`--warn-bg` |
| btn-exempt | #b45309/#fef3c7 | → `--warn`/`--warn-bg`；min-height 24px |
| 台账计数 | 近 10 章命中 | 零命中灰显保留：色用 `var(--text-faint)`（纯装饰性降级，信息可由行本身获得——faint 合法用例） |

neg-row grid 规格（精确；双栏半宽时两行、塌单列全宽时单行，分档挂页容器 stylepage——container query 只能查祖先，负清单自身栏宽不可直接查询，故以 §2.2-A 同一断点代理栏宽状态）：

```css
/* 默认（双栏态，负清单在半宽栏内）→ 两行布局 */
.neg-row {
  display: grid;
  grid-template-columns: minmax(0,1fr) minmax(0,1fr) auto;
  grid-template-areas:
    "word alt  del"
    "sev  hits del";
  gap: var(--space-2) var(--space-3);
  align-items: center;
  padding: var(--space-2);           /* 原 0.5rem 保持 */
  /* 底色/边框/圆角不变 */
}
/* 塌单列（负清单全宽）→ 单行布局 */
@container stylepage (max-width: 60rem) {
  .neg-row {
    grid-template-columns: minmax(0,1fr) minmax(0,1fr) auto auto auto;
    grid-template-areas: "word alt sev hits del";
  }
}
```

（单列全宽时五件单行放得下；双栏半宽时两行。删除钮跨两行右缘垂直居中：`grid-area: del; align-self: center`。）输入字号 0.75rem → `var(--text-sm)`；输入 min-height 28px。

### 4.6 StyleReconciliationSection.vue

| 项 | 现状 | 规格 |
|---|---|---|
| SVG 椭圆变形 | `preserveAspectRatio="none"`（:151,172）拉扁 r=2.5 圆点 | 删 preserveAspectRatio 属性（默认 xMidYMid meet）；`.chart { width: 100%; height: auto; aspect-ratio: 5 / 1; }`（W=600/H=120 恒定，:22-23） |
| chart-title | 0.6875rem | → `var(--text-xs)` |
| 参考带/出带点 | 色值待核 | 带 → `fill: var(--ok-bg); opacity: .6`；出带点 → `var(--danger)`；正常点/线 → `var(--accent-500)`；统一后深色自动正确 |
| 人话总结 | 既有 | 字号 `var(--text-sm)` |

### 4.7 StyleStatusStrip / StyleAuditionBar / StyleInboxSection

- StatusStrip：§3.3 已述。
- AuditionBar：§2.2-B 塌列；`.pane-tag` 0.625rem → `var(--text-xs)`；`.pane-text` 0.8125rem 保留（试听正文=阅读文本，13px + lh1.8 合理，归 `--text-sm` + 行高不动）；运行按钮 ≥28px。
- InboxSection：通用规则套用（badge/按钮/字号归档）；空态整区隐藏逻辑不动。

### 4.8 两个模态 → ModalShell

StyleExtractModal.vue / StyleScanModal.vue：z-50 被抽屉盖（00 期 §3.2 已归位 110）。第 1 期进一步**迁移到 ModalShell**（00 期 §4.3 晋升 components/ 后）：
- 模板：自定义 overlay 壳删除，套 `<ModalShell title="…" width="…" @close> <默认插槽>…</默认插槽> <template #footer>…</template> </ModalShell>`；
- StyleExtractModal width 沿用现卡宽（实测约 560px → width="560px"）；StyleScanModal 同（约 640px → width="640px"）；
- 焦点陷阱/Esc/遮罩点击由 ModalShell 获得（00 期设施），组件内自绘 keydown 监听删除；
- 模态内既有排版（列表/命中行）不动，仅字号/色按通用规则归档。

---

## 5. 深色补全映射表（feature 内逐处）

feature 内 `dark:` 类 0 处——深色全靠 CSS 变量，因此硬编码浅色即深色穿帮。按下表替换（00 期 §2.5 映射的本页落点）：

| 文件:行 | 裸值 | → token |
|---|---|---|
| StyleView.vue:1007-1022 | badge-dirty #b45309/#fef3c7 | `--warn`/`--warn-bg` |
| 同上 | badge-saving #1d4ed8/#dbeafe | `--info`/`--info-bg` |
| 同上 | badge-saved #047857/#d1fae5 | `--ok`/`--ok-bg` |
| 同上 | badge-error #b91c1c/#fee2e2 | `--danger`/`--danger-bg` |
| StyleSampleSection.vue:457-464,590-606 | badge 三色 + fav 两色 | §4.1 表 |
| StyleNegativeSection.vue:183-270,362-367 | btn-scan / btn-exempt / severity chip | §4.5 表 |
| StyleAdoptedPool.vue:106 | #047857 | `--ok` |

hover 加深一律 `color-mix(in srgb, <token> 85%, black)`。替换完成后双主题各过一遍（验收 S-06）。

---

## 6. 交互细节汇总

- **点击目标**：tier-btn 28px（§4.4）；样本卡删除/收藏 24px（§4.1）；anchor-btn 28px（§3.3）；toggle/收编钮 24/28px（§4.2）。本期 style 页无 hover-only 隐形控件（样本删除常驻可见，已核实），00 期 `.reveal-on-hover` 工具类本页不消费。
- **Icon 体系裁决**：状态/操作图标一律 Icon 组件（🔒🔓 替换）；装饰性 glyph（🪶/▶/⚑ 等品牌作者语言字符）保留——裁决依据=「该字符是否承载状态语义」，🔒🔓 承载锁定态必须换，🪶 纯装饰不换。
- **键盘走查**：Tab 顺序 = 锚导航 → 状态条试听 → 样本区 → 采纳池 → 指纹（含锁钮/编辑对象）→ 意图 → 负面 → 对账 → 收件箱；全程焦点环可见（00 期 F-05）。
- **加载/空态**：loading-note、grow-teaser、empty-note 字号 → `var(--text-sm)`，色 `--text-secondary`（原 muted 过淡）；零状态坡道三幕逻辑（zeroState/growthStage 门闸）**一行不动**。

---

## 7. 不动清单（契约，触碰=打回）

1. **数据与编排**：StyleView 容器全部 script 逻辑（loadAll/saveStyleCard/2s 防抖/markDirty/收件箱/试听编排/章级特例 switchScope 契约）零改动；模板仅按 §2.1 加 wrapper、按 §4.8 换模态壳。
2. **props/emits 契约**：9 个分区组件对外接口零变化（容器不改调用）。
3. **API**：styleApi/bookApi/chapterApi 调用签名与时机零变化。
4. **零状态坡道**：zeroState / growthStage / suggestExtract 判据零变化。
5. **文案**：品牌隐喻词与既有文案不新造不改写（§3.1 的 sec-hint 只搬既有副标题）。
6. **后端红线**：本页改动不触及任何生成链路；无样本书页面结构与行为逐字节不变。

---

## 8. 第 1 期验收清单

- [ ] **S-01（M/I）**：duo-measure 两列同顶；指纹不再掉行；分隔线在两列之间；采纳池在左列样本之下。
- [ ] **S-02（I）**：DevTools 模拟 1093px / 1280px / 960px（CSS 像素）三档：1093 双栏可用、960 单列虚线分隔；试听条 ≤48rem 容器塌单列。
- [ ] **S-03（G）**：`grep -n "@media" src/features/style/` 清零（全部 container query）；AppSettingsModal 640px 媒体查询已平移。
- [ ] **S-04（G）**：`grep -rn "font-size" src/features/style/` 无 <12px；无 0.5625/0.625/0.6875rem 与 10/11px。
- [ ] **S-05（G）**：`grep -rn "#fef3c7\|#fee2e2\|#dbeafe\|#d1fae5\|#f3f4f6\|#d1d5db\|#f59e0b\|#047857\|#b45309\|#b91c1c\|#1d4ed8" src/features/style/` 清零。
- [ ] **S-06（I）**：深/浅主题各过全页：badge/chip/按钮/提示条无穿帮；收藏星双色两主题均可辨。
- [ ] **S-07（I）**：对账两张图点为正圆（非椭圆）；图随栏宽缩放不糊。
- [ ] **S-08（I）**：负面清单在双栏半宽下两行布局：词/替代词输入 ≥ 各自栏宽 40%，无挤压换行失控。
- [ ] **S-09（I）**：样本 >6 条时默认收 6 条，展开/收起往返正常；页面无嵌套滚动条（全文仅 .style-main 一根）。
- [ ] **S-10（I）**：锁定钮为矢量图标（非 emoji），两态可辨，24×24 可点，title 提示正确。
- [ ] **S-11（I）**：两个模态从抽屉打开状态触发，完整可见不被盖；Esc 关模态不关页面其他层；Tab 焦点不出模态。
- [ ] **S-12（I）**：回归——贴样本→指纹 3 秒内出现、2s 防抖自动保存、提炼弹窗预填最长 3 条、试听 A/B 双轨、收件箱 ✓/✗、章级特例深链 `?chapter=` 全通过。

## 附录 B：Icon.vue 新增 path（Heroicons v2 outline，24 viewBox）

```
lock-closed: M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z
lock-open:   M13.5 10.5V6.75a4.5 4.5 0 119 0v3.75M3.75 21.75h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H3.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z
```

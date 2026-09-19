# 05 · 视觉现代化改造计划（「后现代」质感大修）

> 2026-09-15 调研定稿。触发：用户体感「主题系统实现太简陋，视觉像 2010 年 XP→Win10 过渡期的质感，要到后现代水准」。
> 本文档 = 双路调研（代码事实清单 + kimi-2 设计诊断）的合并结论与分期计划。**尚未施工。**
> 既有设计档：01-theme-architecture（token 架构与豁免裁决）、03-rollout-plan（五主题推广）、04-visual-language-layer（签名色/纸纹）。本计划对齐不推翻。

---

## 0. 一句话诊断

**架构是 2020s 的，执行停在「边框 + 平色 + 实底按钮」三件套。**
主题系统刚立的地基（语义 token、五主题×明暗正交、签名色恒定、豁免面纪律）方向全对；
「2010 体感」不来自架构缺失，而来自架构**只覆盖了颜色，没覆盖质感**——表面阶梯、elevation、动效、控件皮肤、表面材质五个维度集体缺位。

---

## 1. 现状定级：「2010 质感」的七处具体出处（全部带代码证据）

| # | 病灶 | 证据 |
|---|------|------|
| A1 | **表面阶梯塌方**——分层只有「1px 边框」一种语言 | 亮档 `--bg-canvas`=`--paper-bg`=`--bg-elevated`=`#fefdfb`（style.css:11/13/93）；`--bg-tertiary` 与 `--bg-panel` 在全部 10 个主题块同值（panel 是死 token）；61 个组件共用同一种 `1px solid var(--border-color)`；无线阶、无 hover/pressed state 色板（仅一枚 `--hover-bg`） |
| A2 | **Elevation 不成体系** | 仅 4 枚阴影 token，ramps 全是「black×透明度」同构影；暗档 10 块阴影纯黑无环境色相（:238-241 等）；组件层 ~75 处裸写 box-shadow 未走 token |
| A3 | **动效零 token** | `:root` 无任何 `--dur-*/--ease-*`；全仓 120+ 处手写 transition（`all 0.15s ease`×29、0.12×10、散点 60+），清一色 `ease`，无出入分工、无编排 |
| A4 | **五主题 ≈ 单色相换色** | 10 个覆写块结构雷同（7bg+4text+2line+3accent+8语义+4shadow±heading 字体）；几何 token 明令禁改（style.css:247-253），性格表达被锁死在色相一个维度 |
| A5 | **深色档浮层「抬高」不存在** | 底色带色相（paper 深 #1a1815 暖棕、pro 深 #10151b 冷蓝灰）做对了，但 elevated==panel==tertiary，弹层与底色同明度只能靠投影；暗色投影纯黑无 chroma |
| A6 | **现代表面材质近零** | `backdrop-filter` 全仓 11 处（ModalShell 的 blur(2px) 是唯一像样的）；纸纹基建（useAppearance.ts:38-54 TEXTURES/PAPER_TEXTURES）已造好但默认全关；抽屉/卡/栏全是平色+1px 边框 |
| A7 | **控件层原生裸奔** | 分段控件=直角拼接+激活态整块 accent 实底白字（AppearancePanel.vue:526-558，2010 iOS/Bootstrap 原教旨）；主题预览卡=76px 灰底+三条抽象色杠（:432-504）；checkbox/range/color 全原生；Toast=整块 accent 实底（Toast.vue:29-34） |

**存量包袱（绕坑清单）**：非豁免面 hex 残留 ~45 行（其中 ~30 处是 accent 实底上的 `color:#fff`——anime 深档 accent=#ffa5c8 近白，白字对比度失效；正确范式 `text-[var(--bg-canvas)]` 已在 Toast 示范未推广）；豁免面四族（古地图/书封/预览卡/签名色）一行不碰；QuickEventNote.vue workspace/world 双份债；index.html 内联脚本 ↔ useAppearance 人工对拍契约（已出现注释漂移：texture 档一边豁免一边注释仍称对拍）。

---

## 2. 目标设计语言：三候选 → 推荐

### 方向一「纸上建筑」（★ 推荐主线）
文房基因 × 现代 token 架构。纸还是纸，但纸有纤维、有裁切边、有台下灯的暖；chrome（栏/抽屉/弹层）从「边框面板」升级为「暖白亚光材质 + hairline + 环境投影」；朱砂/薄荷从色块变成精密小面积信号。
参照：Things 3 的克制、Craft 的纸质、Arc 的侧边栏工艺、Notion Calendar 的密度。
成本中、风险低（每步有冻结回滚点），不动 IA/引擎/编辑器。

### 方向二「仪器」（降级为 pro 主题精修，不单独立项）
Raycast/Linear 式单色工具美学。与全产品文房叙事冲突，只适合作第六主题或 pro 档试验田。

### 方向三「质感大修不换骨」（作为方向一的分期外壳）
不加主题不换身份，纯工艺 pass——「用户说不出哪里变了但感觉高级了」。

**结论：方向一为北极星，方向三是其分期策略，方向二顺手落进 pro 主题。**

---

## 3. 改造支柱（落到文件/token 粒度）

### C1. Token 架构二期（style.css + tailwind.config.js）
- **表面阶梯**：新增 `--surface-base/sunken/raised/overlay/float` 五档，第一步 alias 现值（视觉零变化），第二步按主题调值；处置 `--bg-panel` 死 token。
- **线阶**：`--line-faint`（8% 分区缝）/ `--line`（现 border-color）/ `--line-strong`（浮层外缘）；61 处边框分批归档。
- **State 色板**：`--state-hover/active/selected` 全走 color-mix 配方（绕 Tailwind 透明度修饰符失效坑，config:6-8 已立此规）。
- **Elevation**：e0-e3 四档，每档=「shadow+border+可选 inner highlight」三件套，收拢工具类 `.elev-0/1/2/3`；暗档阴影改「纯黑+8~12% 主题 accent 相」；75 处裸写 box-shadow 按用途映射收编（不重设计）。
- **Motion**：`--dur-1..4`（.12/.18/.24/.36s）+ `--ease-out/in/spring` + `--stagger-1..3`（40/80/120ms）；120+ 处手写 transition 分批收敛；`motion-low`/prefers-reduced-motion 毯式规则不动（token 化后自动兼容）。
- **Type**：补 `--tracking-meta/cap`；meta/计数全局 tabular-nums（`.num-serif` 推广为 `.tnum` utility）；字重维持 400/500/600 不加中间档（系统字体合成糟）。
- **半径映射约定**：按钮/输入 sm、卡 lg、模态 xl。⚠ `.ghost-draft` 2px/padding:0 行内网格敏感件（style.css:556-560）归一绕开；`--editor-*` 三 token + `--editor-max-width:880px` 永不触碰。

### C2. 深色品质专项
10 个主题块逐个 retune：暗档立 5 级明度阶梯（float 比 base 亮 6-10%）；阴影加 chroma（C1 配方）；语义八件套与签名色暗档提亮已 OK 不动。

### C3. 表面材质（Electron 桌面适配清单）
**做**：模态/抽屉遮罩 blur 2px→8-12px（仅遮罩层）；暗档浮层顶部 1px 内高光；桌面层纸纹默认开 3-5% 剂量（PAPER_TEXTURES 现成，把默认档从 none 提到 grain@4%）；模态/预览卡用 0.6px hairline 渐变边。
**不做**：纸面/编辑器任何 blur 与渐变；animated gradient mesh；大面积 blur 盖滚动文本；玻璃拟态面板（与稿纸叙事冲突）。

### C4. 动效编排
入场系统：抽屉/模态沿用 transition name，列表补 stagger；Toast 改「上浮+淡入+10px 位移」.24s ease-out；同屏多元素=父 0ms→子 stagger ≤120ms；**writing desk 内除幽灵/卡舱既有动效外不加新动画**；验收铁闸=motion-low 开/关各过五主题。

### C5. 外观抽屉重做（AppearancePanel.vue）
宽度 304→352px；主题卡从「三条杠」升级为**微型场景预览**（16:10 纸面 swatch=真纸色+纸纹+accent 标题行+正文行+朱/薄荷点，浅/深半切或月亮角标）；选中态=accent ring+`--glow-accent` 柔光+对勾（替 6px 朱点）；分段控件全部升 pill 滑动 thumb；背景四档改缩略卡；原生 range/color/checkbox 套 token 皮肤；预览 hex 集中到单一 `THEME_PREVIEW_PRESETS` 消双写漂移；底部 hint 升 `--text-sm`+`--line-faint`。

### C6. 顺带消债
~30 处 accent 实底 `#fff` → `var(--bg-canvas)` 范式推广（anime 深档对比度事故前置排除）；QuickEventNote 双份合一（P0 前置）；tooltip 体系（全仓靠原生 title，不可主题化——独立小件，新组件 pill 化时一并立）。

---

## 4. 分期路线

| 期 | 内容 | 风险 | 验收 |
|----|------|------|------|
| **P0 无风险地基** | C1 token 段新增（全 alias 现值=视觉零变化）+ transition/box-shadow 收敛 codemod + QuickEventNote 合一 + --bg-panel 处置 | 零视觉变化，可独立合入 | tsc + 前端单测全绿 + 逐字节目检 diff |
| **P1 视觉焕新主线（chrome 层）** | 暗档 10 块阶梯 retune + 阴影 chroma；`.elev-*` 落 ModalShell/DrawerShell/Toast/菜单/卡三档；共享控件（SegmentedPill/按钮/chip/input 皮肤）；AppRail 激活态 pill 化；Toast 重设计（tinted 表面+border+blur，弃实底） | 中——chrome 全覆盖，写作纸面不动 | 五主题×明暗 chrome 走查 + motion-low 双态 |
| **P2 抽屉 v2 + 主题预览** | C5 全项 + C6 消债 | 低 | 10 格主题矩阵抽核 |
| **P3 真机逐页核验** | 写作台（静音红线：纸面无新增装饰/动效）、世界页（古地图豁免不动，验 chrome/暗档）、大纲板、文风页、数据页、书架；DPR 1.0/1.5/2.0 | — | IAB 实机 + 截图核验 |

**高风险红线（每期自查）**：
1. 豁免面四族一行不碰（古地图/书封/签名色/预览 hex 集中化前的预览卡）。
2. 新透明度 100% 走 color-mix，禁 `bg-accent-500/50` 类写法。
3. `.ghost-draft` 几何、`--editor-*`、`--editor-max-width` 永不触碰。
4. index.html 内联脚本 ↔ useAppearance 对拍契约：主题 schema 扩字段两边同改（已有 texture 档注释漂移先例）。
5. 既有对拍测试（extensions 34 项/contextBlockFormat/ghostReap/heartbeatSeam/timelineLayout）每批全绿。

---

## 5. 明确不做什么（过度设计警告）

1. **纸面/编辑器不加任何材质与动效**——正文区是全产品最贵的不动产，「安静」是功能不是保守；glass/渐变/纹理只许落 chrome。
2. 不做玻璃拟态面板、animated gradient mesh、视差。
3. 不引 webfont（01 §0-6 已拍板）——字工艺走栈重排/字重/字距/数字对齐。
4. 不动 IA 与布局网格——质感大修不是改版，「顺手挪布局」的提案出局。
5. 动效预算：单动效 ≤400ms、spring 禁驱布局属性、同屏 stagger ≤120ms；motion-low 永远能一键归零。
6. 不给一切加阴影——elevation 表达层级语义，撒胡椒面式投影是另一种 2010。
7. 主题数不膨胀——先把五主题工艺做穿，新主题（含方向二）是结果不是起点。

---

## 6. 附：现状事实速查（调研原始数据要点）

- 主题定义无 themes.ts，全部在 style.css：`:root` 6-174（≈90+ token）、`:root.dark` 185-245、五主题覆写块 256-383（paper 无块=:root 本体）；明暗=`.dark` class（useAppearance.ts:120），主题=`data-theme`；防 FOUC 内联脚本在 index.html。
- 签名色恒定：`:root` 126-146（薄荷/朱砂/伏笔紫/鎏金/三态真相/atlas 五死 token），主题块禁覆写。
- Tailwind 桥接：三族「档位」= 语义 token 别名非真色阶（ink-700===ink-600、accent-700/800/900===accent-600，tailwind.config.js:21-54）——「深一档」表达不存在，C1 立 surface 五档后缓解。
- 背景系统：四档 BgSpec 写 documentElement style，body::before 铺底+::after 遮罩（自动反色）；图片=本地 file→canvas 压缩 1920/JPEG q0.8/>1.5MB 拒→dataURL 入 localStorage（**挤 5MB 配额、persist 失败静默=下次启动外观全丢无提示**——已知弱点，本计划不扩背景图功能）。
- 持久化：localStorage `velluma:appearance:v1` 设备本地；旧键 `velluma_theme` 一次性迁移。
- 动效存量：29 个 keyframes（幽灵呼吸/罗盘摆动/WorldMap wm-* 八件/thinking-pulse 等）；motion-low=复用 prefers-reduced-motion 毯式规则+`.spin-reduced` 白名单。

---

## 7. P0 施工单（执行依据，kimi-2 按此施工）

**P0 铁律：视觉零变化。** 所有新 token alias 现值；codemod 只替换与现值逐字节相同的写法；凡遇到值不一致的散点（0.14s/0.18s/0.25s 等）**不替**，留 P1 评审。

### 7.1 style.css `:root` 新增段（位置：现有阴影 token 段之后）

```css
/* ===== 表面阶梯（P0 alias 期：映射现值，P1 按主题调值） ===== */
--surface-base: var(--bg-canvas);
--surface-sunken: var(--bg-tertiary);
--surface-raised: var(--bg-secondary);
--surface-overlay: var(--bg-panel);
--surface-float: var(--bg-elevated);
/* 线阶 */
--line-faint: color-mix(in srgb, var(--border-color) 55%, transparent);
--line: var(--border-color);
--line-strong: color-mix(in srgb, var(--text-primary) 18%, transparent);
/* State 色板（active/selected 本期无消费方，先立账） */
--state-hover: var(--hover-bg);
--state-active: color-mix(in srgb, var(--text-primary) 8%, transparent);
--state-selected: color-mix(in srgb, var(--accent-500) 12%, transparent);
/* Motion（P0 只立时长账，值=现状主值；easing 字面量 P1 才收敛） */
--dur-1: .12s; --dur-2: .15s; --dur-3: .2s; --dur-4: .3s;
--ease-out: cubic-bezier(.2,.8,.2,1);
--ease-in: cubic-bezier(.4,0,1,1);
--ease-spring: cubic-bezier(.34,1.3,.4,1);
--stagger-1: 40ms; --stagger-2: 80ms; --stagger-3: 120ms;
```

注意：上述 var() 别名只需在 `:root` 声明一次——主题块/`.dark` 覆写的是底层 `--bg-*`，别名在计算值期动态解析，**不要**在 10 个主题块里重复声明。

### 7.2 Elevation 工具类（style.css 组件视觉层段）

```css
.elev-0 { box-shadow: none; }
.elev-1 { box-shadow: var(--shadow-sm); border: 1px solid var(--line); }
.elev-2 { box-shadow: var(--shadow-md); border: 1px solid var(--line); }
.elev-3 { box-shadow: var(--shadow-lg); border: 1px solid var(--line-strong); }
```

P0 只定义不推广；组件收编规则=**仅当组件现有 box-shadow 值与某档 token 值逐字相同且已有同色边框时**才换类，其余留 P1。

### 7.3 Transition codemod 映射（只换精确匹配）

| 现状 | 替换为 |
|------|--------|
| `0.12s ease` | `var(--dur-1) ease` |
| `0.15s ease` | `var(--dur-2) ease` |
| `0.2s ease` | `var(--dur-3) ease` |
| `0.3s ease` | `var(--dur-4) ease` |

0.14/0.18/0.25/0.36s 及非 ease 曲线一律不动，输出清单留 P1。`transition: all …` 同规则只换时长段。keyframes 内时长不动。

### 7.4 --bg-panel 处置

全仓 `var(--bg-panel)` → `var(--surface-overlay)`（值相同=零变化）；`--bg-panel` 本体保留在主题块中并标注 `/* deprecated: 由 --surface-overlay 接替，P2 后删除 */`。

### 7.5 tailwind.config.js 增量（纯添加，零风险）

- colors 增 `line / line-faint / line-strong` 与 `surface: {base, sunken, raised, overlay, float}` 均映射对应 var；
- boxShadow 增 `e1/e2/e3` 映射 `--shadow-sm/md/lg`；
- 不加 transitionDuration 映射（避免与 duration-150 数值键混淆，P1 再议）。

### 7.6 QuickEventNote 双份合一

workspace 与 world 各一份 QuickEventNote.vue。先 diff 两者脚本/props 差异：若仅样式漂移→单一事实源保留一份，另一处改 re-export/薄封装；若 props 已分化→抽共享样式块进 style.css 组件层（`.qen-*` 前缀），脚本各自保留。**施工前把 diff 结论写进提交说明。**

### 7.7 不动清单（P0 显式排除）

- ~30 处 accent 实底 `color:#fff` → 属 C6 消债，留 P2（避免 P0 混入视觉变化）。
- index.html 内联脚本：P0 无 schema 变化，不碰。
- 豁免面四族、`.ghost-draft` 几何、`--editor-*`、纸纹默认值：不碰。
- 不 git commit（批次惯例：用户明示才提交）。

### 7.8 P0 验收

1. `npm run typecheck` 零错；`npm test` 全绿（基线 309）。
2. grep 复测：`0.15s ease` 等四档精确写法残留=0（豁免面除外）；`var(--bg-panel)` 消费点=0。
3. 抽查 diff 确认无 hex/布局/字号变动——P0 diff 里只允许出现 token 引用替换与新增段。
4. 施工报告列出：替换计数（按 7.3 四档分列）、未替换散点清单、QuickEventNote diff 结论。

**P0 施工完成记录（2026-09-15，kimi-2 执行）**：115 处 transition 收敛（dur-1×24/dur-2×69/dur-3×16/dur-4×6，42 文件）；`var(--bg-panel)` 31 处消费点→`--surface-overlay`（10 处声明保留+deprecated 注）；tailwind 增量 colors surface/line 族+shadow e1-e3；`.elev-0..3` 只定义未推广（干净 elev-2 候选 5 个：WorldContextCard/EditorFindBar/SparkDock/BeatCardDock/EntityDetailDrawer）；QuickEventNote 共享样式块 `.qen-*`（~460 行）入 style.css 组件层、两 SFC scoped 瘦身为字号覆盖层（-530 行，脚本零改动——props 已分化不能合脚本）；散点清单在 §8.1 收敛。typecheck 0 错、vitest 364 绿。主 agent 抽查复核：纯 ease 残留=0、alias 完好、临时脚本已清。
**P0 遗留挂账（P2 处理）**：`.qen-new`/`.qen-map-btn` 内旧 accent 紫硬编码 `rgba(124,106,173,…)`→color-mix(var(--accent-500))；两 SFC 字号漂移统一提 token 档；C6 的 ~30 处 `color:#fff`。

---

## 8. P1 施工单（chrome 视觉焕新，kimi-2 按此施工）

**P1 铁律**：视觉变化只许落在 chrome（栏/抽屉/弹层/Toast/控件/卡片壳）；**纸面/编辑器零改动**（ChapterEditorView 纸列、.ProseMirror、.ghost-draft、--editor-* 不得出现在 diff）；豁免面四族零触碰（AppearancePanel 的**预览色值**豁免，但其控件本身可以且应该 token 化）；新透明度只走 color-mix；index.html 不碰；不 commit。

### 8.1 动效终值定档（单点改值+散点收敛）

- token 改终值：`--dur-2: .15s→.18s`、`--dur-3: .2s→.24s`、`--dur-4: .3s→.36s`（--dur-1 不变）——P0 的 115 处引用自动升格，这是本批最大的「润物细无声」。
- 散点收敛映射（P0 遗留清单）：`0.14s ease`→`var(--dur-1) var(--ease-out)`；`0.18s ease`→`var(--dur-2) var(--ease-out)`；`0.22s ease`→`var(--dur-3) var(--ease-out)`；`0.25s ease-out`→`var(--dur-3) var(--ease-out)`。豁免面内同款不动。
- 曲线收敛：`var(--dur-N) ease`（交互态：hover/背景/边框/颜色/transform）→`var(--dur-N) var(--ease-out)`；退出方向（*-leave-active 等）用 `var(--ease-in)`；`--ease-spring` 仅小位移入场（translateY ≤12px/scale .96-1），禁驱布局属性。
- motion-low/prefers-reduced-motion 毯式规则不动；改完 grep 确认无绕过 token 的新硬编码时长（豁免面除外）。

### 8.2 表面阶梯调值（10 主题块逐块，只改 --bg-* hex，别名结构不动）

- **暗档配方（重点）**：立五级明度阶梯 base < sunken < canvas < raised < float，float 比 base 亮 6-10%（用 color-mix with white 4-8% 推算后取整 hex）；保持各主题底色色相不动（paper 暖棕/pro 冷蓝灰/anime 紫…）。
- **浅档配方**：canvas ≤ raised ≤ float 明度单调；float 可向 #fff 提，raised 取 canvas 与 tertiary 中值；差异宁小勿大（2-4% 明度差）。
- 每块产出 before/after hex 对照表进施工报告。

### 8.3 阴影 chroma + 内高光

- 暗档 5 块阴影颜色改 `color-mix(in srgb, #000 88%, var(--accent-500))` 配方（透明度 ramp 不变）；浅档已带色相只统一 ramp，不动 --shadow-paper。
- `.dark` 下 `.elev-3` 追加 `inset 0 1px 0 rgba(255,255,255,.04)` 顶部内高光。

### 8.4 .elev-* 收编

- 5 个干净候选（WorldContextCard/EditorFindBar/SparkDock/BeatCardDock/EntityDetailDrawer）→ `.elev-2`；ModalShell→`.elev-3`；DrawerShell→`.elev-2`；卡三档（paper-card 等）→`.elev-1`；菜单/浮层→`.elev-2`。
- 换类必须删除被替代的裸 box-shadow/border 声明；SparkDock/BeatCardDock 换类后核对卡舱在纸面上的视觉（行间推挤布局不能变）。

### 8.5 遮罩模糊

- ModalShell scrim `backdrop-filter: blur(2px)`→`blur(10px)`；其他带 scrim 的壳同档处理；仅遮罩层，滚动区/纸面永不上 blur。

### 8.6 Toast 重设计（Toast.vue）

- 弃实底语义色：背景 `var(--surface-float)`+`backdrop-filter: blur(8px)`+`.elev-3`+左侧 3px 语义色条（ok/warn/danger/info 用对应 token）+语义色图标，文字 `var(--text-primary)`；action 按钮（撤销）配色适配新浅底。
- 入场动效：opacity 0→1 + translateY(8px→0)，`var(--dur-3) var(--ease-out)`；退场 `var(--dur-2) var(--ease-in)`。

### 8.7 共享控件首批

- 新建 `frontend/src/components/SegmentedPill.vue`：pill 轨道（`var(--surface-sunken)` 底+`var(--radius-lg)` 全圆角）+滑动 thumb（transform/width 过渡 `var(--dur-2) var(--ease-out)`，thumb 用 `var(--surface-float)`+`.elev-1`），选中文字 `var(--text-primary)`、未选 `var(--text-secondary)`；props: options/modelValue，v-model。
- AppearancePanel 四处 `.seg` 全部换 SegmentedPill 试点（控件 token 化不违预览豁免）。
- AppRail 激活态：实底色块→pill 态（`var(--state-selected)` 底+accent 图标文字，圆角 `var(--radius-md)`）。
- 按钮/chip/input 皮肤：hover 统一 `var(--state-hover)`（与 --hover-bg 同值，纯换名）；focus 沿用全局 :focus-visible 环。

### 8.8 P1 验收

1. typecheck 0 错 + vitest 全绿（基线 364）。
2. 施工报告含：10 主题块调值 hex 对照表、8.1 各处收敛计数、8.4 收编清单、8.6/8.7 设计决策说明。
3. 红线自证：diff 中无纸面/编辑器文件、无豁免面文件、无 hex 新增（除 8.2 调值对照表内）、无斜杠透明度、index.html 零改动。
4. 五主题×明暗 chrome 目测走查清单（ModalShell/Toast/AppRail/一抽屉一卡）——用文字描述每格状态，留 P3 真机复核。

**P1 施工完成记录（2026-09-15，kimi-2 执行，主 agent 抽查复核通过）**：dur 终值 .18/.24/.36 单点改值（115 引用自动升格）+曲线收敛 113 ease-out/2 ease-in+散点 16 行收敛；十块阶梯调值（5 暗块全阶梯 float=+7% 白、paper/soft 浅 float→#fff、3 浅块零变化，22 个新 hex 全部在处方带内）；阴影 chroma 20 行（`rgb(from color-mix(#000 88%,accent) r g b / A)` 相对色语法保 alpha ramp，当时判断 Chromium 120 支持有误——该语法在 Electron 28 渲染器原生崩溃（STATUS_BREAKPOINT），2026-09-16 全部 20 处已改为预计算 rgba）+`.dark .elev-3` 内高光；elev 收编=5 候选 elev-2+ModalShell elev-3+card-std/mention-popup 规则组合并；scrim blur 10px（全仓唯一 scrim）；Toast 弃实底（float+blur8+左 3px 语义条+上浮动效，死数据 typeIcons 顺手接活）；SegmentedPill 新建+AppearancePanel 3 处换装（「图片」档用单向绑定防取消选文件时 thumb 误停——v-model 会）+AppRail pill 激活+hover 换名 61 处。保守裁量（合理）：DrawerShell 跳过（投影在豁免面 WorldView .atlas-drawer）、card-compact/paper-card 跳过（无 shadow/纸面语义）、浅档 secondary 不动（中值配方与单调递增在近白区间互斥）。typecheck+vitest 364 两轮绿。
**P1 遗留挂账（P2 处理）**：AppearancePanel.vue:331 抽屉自身 `0.18s ease`（codemod 豁免面排除的副作用，P2 重做抽屉时 token 化）；0.1/0.12/0.13s 无曲线散点 ~20 处+0.16s×1+0.2s ease-out/in 字面量 5 处；DrawerShell elev 待豁免面策略；paper-card 是否入 elevation 体系待定。

---

## 9. P2 施工单（外观抽屉 v2 + 主题预览 + C6 消债，kimi-2 按此施工）

**P2 铁律**：本批主战场=AppearancePanel.vue（预览色值集中前仍豁免逐字，集中后 PRESETS 文件享有同等豁免+注释）；纸面/编辑器/其余豁免面零触碰；新透明度只走 color-mix；index.html 不碰；不 commit；临时脚本用完即删。

### 9.1 外观抽屉 v2（AppearancePanel.vue，宽 304→352px）

- **主题预览卡升级**：从「三条杠」改 16:10 微型场景预览——**上下半切浅/深**：上半该主题浅色纸面、下半深色纸面，各带 accent 标题行+两条正文线+右下薄荷/朱砂两点；纸面可叠极低剂量 grain 纹理（复用 useAppearance TEXTURES 的 data-URI 或内联同款，预览豁免面内允许）。选中态：accent 2px ring+`var(--glow-accent)` 外柔光+右上角对勾 chip（accent 底、`var(--bg-canvas)` 勾——不用 #fff），替换 6px 朱点角标。卡名/副标排版不变。
- **THEME_PREVIEW_PRESETS 集中**：预览色值收进单一常量文件 `frontend/src/components/appearancePreviewPresets.ts`（5 主题×明暗×{paper,canvas,accent,text,muted}），AppearancePanel import；style.css 十主题块头加注释「预览色值同源维护于 appearancePreviewPresets.ts」；豁免注释随迁移保留。
- **背景四档改缩略卡**：2×2 网格——主题默认=当前主题 canvas 色 swatch；纯色=已选色块（未选=滴管图标）；图片=已选图缩略（未选=图片图标）；纸纹=grain/weave 纹理 swatch。选中 ring 同主题卡。原有「图片」档单向绑定行为保留（P1 已修，勿回退）。
- **原生控件皮肤**：input[type=range] 轨道（surface-sunken+radius 全圆）+圆点（accent 底+elev-1）；input[type=color] 包 swatch 壳（line 边+radius-md）；checkbox 自定义化（unchecked=surface-float+line 边，checked=accent 底+bg-canvas 勾）。全部 webkit 伪元素实现，不加 JS 库。
- **底部 hint**：字号提 `--text-sm`、顶部分隔改 `--line-faint` 实线（退役 11px+虚线）。
- **抽屉自身过渡 token 化**：AppearancePanel.vue:331 的 `0.18s ease`→`var(--dur-2) var(--ease-out)`（P1 挂账项）。

### 9.2 C6 消债（逐处判断，报告列上下文）

- **accent 实底 `#fff` → `var(--bg-canvas)`**（Toast 已有范式）：候选 ~30 处（SpinePanel/CanonSection/InspectorPanel/TocPage 等 ~20 文件）。判断规则=仅当 #fff 落在 accent/语义色实底上才换；落在图片/地图/预览豁免面上的不动。逐处列文件+上下文进报告。
- **`.qen-new`/`.qen-map-btn` 旧 accent 紫** `rgba(124,106,173,α)`→`color-mix(in srgb, var(--accent-500) …)` 保 alpha。
- **QuickEventNote 字号漂移统一**：workspace 版裸 rem（0.66-0.85）映射最近 token 档（--text-xs/sm/base），world 版已 token 不动；逐值映射表进报告（此为用户可见微变化，属有意收敛）。
- **P1 时长挂账收敛**：0.1s→`var(--dur-1)`（微变 0.02s，可接受）/0.12s 无曲线→dur-1 ease-out/0.13s→dur-1/0.16s→dur-2/0.2s ease-out|ease-in 字面量 5 处→dur-3 对应曲线。豁免面内不动。

### 9.3 十格修版（代码层，无真机）

- 复核 anime 深档（accent-500=#ffa5c8 近白）上所有 accent 实底文字——9.2 的 canvas 替换后逐处确认对比成立；若仍有 accent 浅底+浅字的组合，文字改 `var(--text-primary)` 或底色改 color-mix 加深，逐处记录。
- 五主题 selected 态（--state-selected=12% accent）在浅/深底上的可辨度代码层估算，不足则调至 14-16%（改 token 单点，不动组件）。

### 9.4 P2 验收

1. typecheck 0 错+vitest 全绿（基线 364）。
2. 报告含：9.1 各项完成度+预览卡实现说明、9.2 逐处清单（#fff 上下文/qen 字号映射/时长收敛计数）、9.3 判断记录。
3. 红线自证：纸面/编辑器零改动；豁免面除 AppearancePanel 外零触碰；PRESETS 集中后 AppearancePanel 内散置预览 hex=0；无斜杠透明度；index.html 零改动；临时脚本清零。

**P2 施工完成记录（2026-09-15，kimi-2 执行，主 agent 抽查复核通过）**：
⚠ **P1 隐藏事故热修**：P1 hover 换名 codemod 把 `--state-hover: var(--hover-bg)` 别名行误改自引用（guaranteed-invalid），P1 合入以来全仓 hover 背景静默失效（typecheck/vitest 不可测 CSS 计算值故漏网）——P2 发现复原并留注释；与 P0 alias 误伤同类根因（codemod 须排除 alias 定义行，两连踩，后续 codemod 先查自引用）。
抽屉 v2 全项落地：352px/16:10 上下半切浅深预览卡（独立 PREVIEW_GRAIN_URI——useAppearance TEXTURES 有 index.html 对拍契约勿动）/accent ring+glow+对勾 chip 选中态/PRESETS 集中（appearancePreviewPresets.ts，面板内散置预览 hex=0；`#dfd8cb` 为纯色档功能默认值非预览色，保留）/背景四档 2×2 缩略卡（图片档单向绑定保留，SegmentedPill 从本区退役+bgKindOptions 死代码删）/range·color·checkbox 皮肤/hint 提档/:331 过渡 token 化。
C6 消债：#fff→bg-canvas 30 处全逐处核过；旧紫 rgba(124,106,173)→color-mix 16 处（文档点名 4+同债扩展 12，豁免面 10 处按纪律不动）；QEN 字号 12 行映射 token 档；时长挂账 27 行收敛（0.15s ease-in×1 按最近档 dur-2 收敛，文档「0.2s×5」实为 4+1 已记偏差）。
§9.3：anime 深档 accent 底文字对比 12:1 成立；--state-selected 12%→15%（浅档近白底 12% 不可辨，文档 14-16% 带内单点调）。
typecheck+vitest 364 绿。挂 P3：CanonSection .cs-type--archive 底灰字对比 ≈1.9:1（旧 #fff 同档无退化，真机定夺）。
**P0-P2 全部完成，待 P3 真机核验。**

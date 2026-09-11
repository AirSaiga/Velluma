# 第 2 期：世界页「活舆图」（UX 重构 · 设计规格）

> 前置：第 0 期 `00-foundation.md`、第 1 期 `01-style-page.md` 均已施工完成。本文所有 token、层值、工具类、浮层设施均引自该两文，不另立。
> 范围：`frontend/src/features/world/`（containers: WorldView.vue / WorldTimeline.vue / WorldMap.vue；presentation: EntityCard.vue / ForeshadowSection.vue / CanonSection.vue 等）+ 跨页尾项（LibraryView.vue、CharacterManagerPanel.vue 的 §4.4 首批清单余项收口）。
> 引擎红线：事件源折叠推演、时间轴手势分工、⇧拖建关系、浮点年窗持久化、Leaflet 图层行为——一行不动。本期只修 chrome（页面框架层）：图标栏分组、弹层治理、刻度可读性、发现性、hover 显形、字阶色值归档。

---

## 1. 目标

1. 图标栏按作者心智分三组（收件 / 账本 / 名册），治「找不到入口」；
2. 时间轴四弹层接 placeFloating + Esc 栈，治「弹层无钳位、Esc 行为不一」；
3. 完成 00 期 §3.3 遗留验证点：wt-ctx / wt-fs / wt-arc（及 wt-range）teleport 状态逐查并落归位决定；
4. 刻度数字对比度归档（字号地基已迁 xs，本期只归色）；
5. 罗盘 / 图例 / 胶囊条发现性修复（治「hover 才知用途」）；
6. hover 显形迁移（含 00 期 §4.4 首批清单两个跨页尾项收口）；
7. 字阶与色值全量归档（消灭 12.5px / 17px / 19px / 26px 碎片值）。

---

## 2. 图标栏分组重组（WorldView.vue:1117-1159）

### 2.1 现状实锤

`.atlas-rail`（样式 WorldView.vue:1783-1802，z 750，右缘 46px）内 8 枚 `.ar-btn`（34×34，1803-1816）平铺，顺序 `[待确认cand, 伏笔fs, 期待exp, 真相canon] sep [地点loc, 事件evt] sep [角色character, 势力faction, 资产asset]`——两道分隔线只起视觉呼吸作用，不承载分组语义；当前态 `.ar-btn--on` 仅一块淡紫底（rgba(124,106,173,0.14)，1826-1829），扫视时定位弱。

### 2.2 分组方案（唯一指定做法）

**按钮顺序逐位不变**（cand → fs → exp → canon → loc → evt → character → faction → asset，肌肉记忆零成本），只改分隔线位置与组首标签：

```
┌────────┐
│  收件  │  ← .ar-group 组首标签
│ [待确认] │
├────────┤  ← .ar-sep 既有 hairline 复用
│  账本  │
│ [伏笔]  │
│ [期待]  │
│ [真相]  │
├────────┤
│  名册  │
│ [地点]  │
│ [事件]  │
│ [角色]  │
│ [势力]  │
│ [资产]  │
└────────┘
```

- **心智依据**：「收件」=AI 从正文发现、等作者过目的东西（待确认是唯一「有东西进来要处理」的入口）；「账本」=三条长线账（伏笔/期待/真相，都是「记一笔、以后揭」）；「名册」=世界对象名录（地点/事件/角色/势力/资产，都是「查/建对象」）。作者想的是「我要干嘛」，不是「数据类型是什么」。
- 第一组只有一枚按钮——「一组一钮」是有意的：待确认是收件箱，独立成组让它在视觉上永远第一眼被找到（它也是唯一带计数角标的入口）。

### 2.3 样式规格

```css
.ar-group {
  font-size: var(--text-xs);        /* 12px，装饰/分区标签角色（00 期 §2.1.2：分区标签 xs 恒） */
  color: var(--text-muted);
  letter-spacing: 0.08em;
  line-height: 1;
  margin: var(--space-1) 0;         /* 上下 4px，46px 栏宽内两字横排居中 */
  user-select: none;
}
```

- 标签两字横排（收件/账本/名册），46px 栏宽可容纳 24px 字宽 + 余量；
- 第二、三组标签上方保留 `.ar-sep`（既有 hairline 样式不动，仅位置移动）；第一组标签上方无分隔线；
- 标签为纯信息元素：`aria-hidden="true"`（分组语义由按钮自身 aria-label 承载，不制造冗余朗读）。

### 2.4 当前态指示补强

`.ar-btn--on` 现状仅色底。补强为「色底 + 左缘指示条 + 无障碍态」：

```css
.ar-btn--on {
  background: color-mix(in srgb, var(--accent-500) 14%, transparent);  /* 现值 rgba(124,106,173,0.14) 的 token 化，视觉等值 */
  color: var(--accent-500);
  position: relative;
}
.ar-btn--on::before {
  content: '';
  position: absolute;
  left: 0; top: 20%; bottom: 20%;      /* 2px × 60% 高指示条 */
  width: 2px;
  border-radius: 1px;
  background: var(--accent-500);
}
```

- 模板侧为按钮补 `:aria-pressed="activePanel === key"`（开关语义）；
- **来路半亮态（新增 `.ar-btn--peek`）**：详情抽屉（EntityDetailDrawer 等）打开时，其来路面板图标给半亮提示（`detailReturnPanel` 机制 WorldView.vue:197-232 已有数据源，只加 class 绑定）：

```css
.ar-btn--peek {
  background: color-mix(in srgb, var(--accent-500) 7%, transparent);
  color: var(--accent-400);
}
```

语义：「详情抽屉是从这个面板长出来的，关掉会回去」。半亮与全亮（--on）拉开明度差，不竞争。

---

## 3. 时间轴弹层治理（WorldTimeline.vue）

### 3.1 现状实锤（四弹层同构）

| 弹层 | 模板 | 样式 | 定位 | Esc | 钳位 |
|---|---|---|---|---|---|
| `.wt-ctx` 右键菜单 | 775-813 | 1277-1289 | position:fixed, z:800, 页内 DOM（未 teleport）, `transform: translate(-8px,-8px)` 偏移光标 | **无** | 无 |
| `.wt-fs` 伏笔卡 | 816-844 | 1429-1439 | fixed, z:800, 页内，宽 280 | 元素级 `@keydown.esc` | 无 |
| `.wt-arc` 弧线卡 | 847-887 | 1511-1521 | fixed, z:800, 页内，宽 260 | 元素级 `@keydown.esc` | 无 |
| `.wt-range` 视野表单 | 890-922 | 1589-1598 | fixed, z:800, 页内，宽 236 | 元素级 `@keydown.esc` | 手写半钳位（openRangeForm 81-90：`Math.max(8, Math.min(clientX-150, innerWidth-260))`，注释「弹层一律向上开」） |

锚点来源均为视口坐标（ArcBand.vue:90 直接 emit `{x: e.clientX, y: e.clientY}`）。外部点击关闭走 `onGlobalMousedown`（480-495，`.closest()` 判定）——该路径保留不动。

### 3.2 归位决定（00 期 §3.3 验证点逐项结论）

四弹层全部：**保持页内 DOM、不 teleport、z:800 保留**。依据：

1. WorldView 根已有 `isolation: isolate`（WorldView.vue:1592），800 是隔离上下文内部值，对外不越界；
2. 页内层级序 800（弹层） > 760（胶囊菜单） > 750（图标栏/胶囊条） > 740（抽屉） > 700（详情抽屉） > 660（罗盘） > 640（水印）是**正确**语义——弹层必须盖住栏与抽屉，现行满足；
3. 全局层（modal 100+ / toast 120）在隔离上下文**之外**，天然压在 800 之上——标定卡/Toast 与弹层的先后关系正确，无需改动；
4. teleport 到 body 反而会丢失隔离保护、并需重排全局 z——负收益。

### 3.3 隔离后行为验证表（施工后逐项手测，验收 W-05 引用）

| # | 弹层 | 检查项 | 步骤 | 预期 |
|---|---|---|---|---|
| V1 | wt-ctx | 层级封顶 | 开右键菜单 → 触发任意 toast（如保存） | toast（120）在菜单之上 |
| V2 | wt-ctx | 模态压盖 | 开右键菜单 → 打开标定卡（z-modal，已 teleport body） | 标定卡遮罩盖住菜单，菜单不可交互 |
| V3 | wt-ctx | 页内序 | 菜单与右缘图标栏/抽屉交叠 | 菜单在栏（750）与抽屉（740）之上 |
| V4 | wt-fs | 同 V1-V3 三项 | 悬停伏笔点开封面卡后重复 | 同上 |
| V5 | wt-arc | 同 V1-V3 三项 | 点击弧线带开封面卡后重复 | 同上 |
| V6 | wt-range | 同 V1-V3 三项 | 游标柄右键开视野表单后重复 | 同上 |
| V7 | 全部 | 隔离在位 | DevTools 检查弹层 computed z-index=800 且祖先链含 `isolation: isolate` | 两项皆真 |

### 3.4 placeFloating 接入规格（四弹层同一做法）

- 消费 `useFloatingLayer`（00 期 §4.1 冻结接口），**锚=点击/悬停点**（点锚按零尺寸矩形处理，既有契约）；
- 放置参数统一：`{ gap: 8, margin: 8, prefer: 'above', flip: true, align: 'start' }`——时间轴贴视口底缘，向上展开是自然方向（与 openRangeForm 既有注释「弹层一律向上开」一致），flip 保险朝上空间不足时落下方；
- 尺寸：开后实测（ref 量 offsetWidth/offsetHeight），首帧未测到用兜底包围盒：ctx `{240,320}` / fs `{280,230}` / arc `{260,240}` / range `{236,210}`（取现状 min-width/max-height/定宽值）；
- placeFloating 返回 maxHeight 时应用到弹层 `max-height` + `overflow-y: auto`（小视口不再溢出）；
- **删除**：`.wt-ctx` 的 `transform: translate(-8px,-8px)`（钳位接管定位）；openRangeForm 手写钳位（81-90 整段，由 placeFloating 接管）；三处元素级 `@keydown.esc`；
- **新增**：四弹层全部入 `useEscStack`（open watch 内幂等 push，关闭 remove——00 期 §4.2 契约，与已施工的 4 详情抽屉同式）；wt-ctx 首次获得 Esc 关闭能力；
- **WorldView.onKeydown 让位**（WorldView.vue:771-802）：Esc 分支（mapEdit/draw/pick 取消）函数体首行加 `if (e.defaultPrevented) return`——Esc 栈在 window capture 阶段先行 preventDefault，冒泡到本处理器时跳过，根治「一次 Esc 同关弹层+退出绘制态」的双关。

### 3.5 位置语义变化声明（行为变化清单 B-03）

弹层开启位置从「光标左上 8px 偏移、可能出屏」变为「光标上方完整展开、视口内夹紧」。四弹层交互动线（右键开、点外关、Esc 关）不变。

---

## 4. 刻度可读性（WorldTimeline.vue:1194-1242）

- **字号**：刻度字已随地基施工归 `var(--text-xs)`（12px）✅ 已随地基施工，本期零改动；
- **字色归档（本期唯一改动）**：
  - 主刻度数字 `rgba(109,90,60,0.75)` → `var(--text-secondary)`；
  - 次刻度数字 `rgba(109,90,60,0.60)` → `var(--text-muted)`；
- **刻度线保留墨色 rgba 家族**（装饰元素，00 期 §2.1.2 装饰豁免；墨色调色板是世界页品牌纹理，整体保留——见 §9 不动清单）；
- 归档后刻度数字对比度：浅色底 secondary ≈ 4.6:1 / muted ≈ 3.1:1（小字装饰性刻度可接受下限 3:1，主刻度达标 AA 4.5:1 档）；
- `.wt-now` 17px 衬线 → `var(--text-lg)`（16px）+ font-weight 600（以字重补存在感，碎片值 17 消灭）；`.wt-flash-ch` 26px → `var(--text-3xl)`（24px，装饰性章节闪现，豁免语义但归 token）。

---

## 5. 发现性修复

### 5.1 罗盘（WorldView.vue:1617-1640）

现状：46px 圆盘仅「北」字（rgba(110,85,45,.55)），悬停 scale 1.06，功能（点击回全图）只能靠误触发现。

- 圆盘下方加常驻 caption **「全图」**：`font-size: var(--text-xs); color: var(--text-muted); margin-top: 2px; line-height: 1`；
- 按钮补 `aria-label="回到全图视野"`；
- 摆动动画、「北」字墨色、focus-visible 环（已有）全部不动。

### 5.2 图例（WorldMap.vue:2360-2390）

现状：「图例」标签常驻，`.wm-legend-pop` `display:none` → hover 展开；键盘不可达。

- 标签元素补 `tabindex="0"`；
- 展开规则补 `:focus-within` 对等：`.wm-legend:hover .wm-legend-pop, .wm-legend:focus-within .wm-legend-pop { display: block; }`；
- **display 模式保留的显式裁定**：00 期 §4.4 规则二「opacity 不用 display」针对的是动作按钮的显形过渡；图例 pop 是纯信息面板（无控件、无过渡动画），display 切换避免占位与指针拦截，维持 display 模式，仅补键盘对等。

### 5.3 胶囊工具条（WorldView.vue:1675-1702）

现状：`.atlas-pill`（z 750）按钮带文字标签（记一笔历史/地点/实体/世界观/⋯），发现性已自足——文字即标签。仅修：

- icon-only 的 ⋯ 按钮补 `aria-label="更多"`；
- `.ap-btn` 字号 12px → `var(--text-sm)`（13px，紧凑工具条档，见 §7）；
- `.ap-menu`（z 760）/`.ap-backdrop`（745）层值不动。

---

## 6. 标定卡遮罩层级 —— ✅ 已随地基施工

标定卡已 Teleport 至 body + `z-index: var(--z-modal)`（WorldView.vue:1559-1580，2290 行注释「标定卡 teleport 在 body，隔离罩不住——按模态语义归位」）。本期不再排工，仅保留一条回归验收（W-06：标定卡打开时压盖页内全部弹层，Esc 栈行为正确）。

---

## 7. 字阶与色值归档表

### 7.1 控件字号裁定（00 期 §2.1.2 落地细则，与 01 期 tier-btn 先例同族）

| 角色 | 字号档 | 例 |
|---|---|---|
| 菜单/列表选择项（点击即动作，可呼吸） | `--text-base` | 右键菜单项、胶囊菜单项 |
| 紧凑工具条按钮（胶囊条/分段控件/抽屉内按钮） | `--text-sm` 下限 | .ap-btn / .wbtn / .type-seg-btn |
| 抽屉与弹层表单控件（label/input） | `--text-sm` | .form-label / .form-input / 弹层表单 |
| 承载句子的辅助文（hint/empty/note） | `--text-sm` | .side-empty / .evt-note |
| 列表主行（对象名） | `--text-base` | .sc-name |
| 抽屉分区标题 | `--text-sm` + 600 | .side-title |
| 计数/角标/轴刻度/装饰 | `--text-xs` 恒 | 刻度字、.wm-scalebar |

### 7.2 逐项映射（现状 → 归位）

| 位置 | 现状 | 归位 | 视觉变化 |
|---|---|---|---|
| .ap-btn（WorldView:1702） | 12px | `--text-sm` | 微增 |
| .ap-menu-item / .wt-ctx-item / .wm-ctx-item | 13px | `--text-base` | 微增 |
| .wt-fs/.wt-arc/.wt-range 表单控件 | 12-13px | `--text-sm`，按钮 min-height 24px | 微增 |
| .wm-cform 表单控件 | 12px | `--text-sm` | 微增 |
| .side-title | 12px/600 | `--text-sm`/600 | 微增 |
| .sc-name | 13px | `--text-base` | 微增 |
| .evt-note / .side-empty | 12px | `--text-sm` | 微增 |
| .form-label | 12px | `--text-sm` | 微增 |
| .form-input / .wbtn / .type-seg-btn | 13px | `--text-sm` | **零变化**（已合档） |
| ForeshadowSection / CanonSection 残余 0.75rem×3、12px×2 | 12px | 按角色：列表行→base，hint→sm | 微增 |
| .wt-now | 17px | `--text-lg` + 600 | ≈零 |
| .wt-flash-ch | 26px | `--text-3xl` | ≈零 |
| .wm-blankcard-title | 19px | `--text-2xl` | ≈零 |
| .aw-title 38px 水印 | 38px | **保留字面值**（纯装饰豁免，声明于此） | 零 |
| .wm-scalebar | xs | `--text-xs` | 零 |

归档完成后 world feature 内不得存在 12.5/17/19/26px 等字阶外碎片值（验收 W-11 grep 锁定）。

---

## 8. hover 显形迁移（00 期 §4.4 规则 + 首批清单收口）

| # | 位置 | 现状 | 迁移规格 |
|---|---|---|---|
| H1 | WorldView.vue:2157-2166 `.sc-actions` | opacity 0，仅卡片 hover 显 | 补 `.sc-item:focus-within` 显形；`.sc-act--danger`（删除）静态不透明度 45%（破坏性操作规则三），hover/focus 升至 1 |
| H2 | EntityCard.vue:135-156 `.ec-del` | opacity 0，24×24 尺寸已达标 | 静态 45%（破坏性）+ `.entity-card:focus-within` 显形，hover/focus 升至 1；尺寸不动 |
| H3 | LibraryView.vue:609-622 `.book-actions`（跨页尾项） | opacity 0 hover-only | 同 H2：focus-within 对等 + 含删除钮 45% 静态 |
| H4 | CharacterManagerPanel.vue:285,360（跨页尾项） | Tailwind `opacity-0 group-hover:opacity-100` 删除钮 | 改 `.reveal-on-hover` 工具类 + `:focus-visible` 内显；静态 45% |

H3/H4 是 00 期 §4.4 首批清单的遗余项，归本期收口（声明于此，施工归本期货）。

---

## 9. 深链 `?panel=` 族对应（WorldView.vue:850-871 consumeRouteQuery）

现状：`?panel=expectations|worldview` 开模态（ReaderMirrorModal/WorldviewModal），`?panel=canon` 开抽屉；`entity/time/loc/fs` 走对象定位。

规格（唯一编辑点 = consumeRouteQuery）：

- `?panel=` 扩展接受图标栏全 8 键：`cand | fs | exp | canon | loc | evt | character | faction | asset` → 走 `togglePanel(key)`（与点击图标栏同一路径，保证打开/关闭/互斥语义一致）；
- 旧值 `expectations` / `worldview` 语义**不变**（仍开对应模态——它们是账本族内容但没有独立图标，模态是其唯一入口）；
- 未映射值静默忽略（维持现状行为，不报错不跳转）；
- 写作页侧既有深链生成点（`?panel=canon` 等）零改动。

---

## 10. 三个待设计说明的裁决

### 裁决 ①：图标栏分组的用户认知验证方式

**走查式验收，单用户=作者本人，零测试设施。** 施工完成后执行三个任务走查：

| 任务 | 话术 | 期望首点 |
|---|---|---|
| T1 | 「刚写完一章，去看看 AI 从正文里发现了什么在等你过目」 | 收件组 · 待确认 |
| T2 | 「那条伏笔埋了多久了，翻翻账」 | 账本组 · 伏笔 |
| T3 | 「给北岸要塞补个房间」 | 名册组 · 地点 |

判定：3/3 首点即中 = 通过定稿；任一任务先点到别组 → **回问设计**（调标签措辞或分组归属），施工方不自行改。走查结果记入验收 W-02。

### 裁决 ②：地图画布图钉/关系线视觉降噪 —— **不入本期**

理由：降噪 = 改数据呈现契约（图钉/关系线密度与缩放联动是 Leaflet 图层引擎行为，不是 chrome）；没有真实书数据支撑，盲调密度只会制造新「找不到」。本期范围锁死在页面框架层。「画布视觉降噪评估」单独立项，待真实使用数据（多实体书的画布截图与作者反馈）回充后再评审。

### 裁决 ③：深链 `?panel=` 族 ↔ 图标栏分组映射

按 §9 执行：8 键直通 togglePanel，expectations/worldview 保模态，未映射静默忽略。分组标签不进 URL（分组是纯视觉组织，URL 只对稳定的数据键负责）。

---

## 11. 行为变化清单（唯一依据，清单外变化=事故）

| # | 变化 | 理由 | 风险 |
|---|---|---|---|
| B-01 | 图标栏加组首标签、分隔线易位（按钮顺序逐位不变） | 治找不到入口 | 低 |
| B-02 | 当前态加 2px 左缘指示条 + aria-pressed；详情来路图标半亮（.ar-btn--peek） | 当前态可扫视定位 | 低 |
| B-03 | 时间轴四弹层接 placeFloating：开启位置从光标左上偏移 → 光标上方完整展开 + 视口夹紧 + maxHeight 内滚 | 治出屏/无钳位 | **中**（位置语义变化，但永远完整可见） |
| B-04 | wt-ctx 新增 Esc 关闭（此前只能点外）；四弹层 Esc 统一走栈；WorldView 绘制态 Esc 加 defaultPrevented 让位 | 治 Esc 行为不一/一键双关 | 低（修复性） |
| B-05 | 刻度数字墨色 → text-secondary/text-muted（刻度线墨色保留） | 对比度达标 | 低 |
| B-06 | 罗盘加常驻「全图」caption + aria-label | 发现性 | 低 |
| B-07 | 图例 tabindex + focus-within 展开 | 键盘可达 | 低 |
| B-08 | hover 显形四处迁移（H1-H4，破坏性钮 45% 静态可见） | §4.4 规则收口 | 低 |
| B-09 | 字阶归档（§7.2 表：12→13、13→14 若干，碎片值消灭） | 字阶纪律 | 低 |
| B-10 | `?panel=` 扩展 8 键（旧值语义不变） | 深链可达性补齐 | 低 |

---

## 12. 不动清单（本期内一行不动的契约）

- 事件源折叠推演 `compute_world_state_from_events` 前后端同构、world_events append-only；
- 时间轴手势分工（轨道拖拽=平移、游标柄拖拽=移游标、Ctrl/⌘+滚轮缩放、◂▸ 步进）、浮点年窗持久化与 PATCH 全量快照契约（books.timeline_view）；
- ⇧拖建关系手势、双击改名、entity-mention 建议链；
- Leaflet 地图内部 pane z（460/500/645/650/660/700/800/850/860）与 WorldMap 自有隔离（~1875）全部层级关系；
- 弹层层值 800 / 图标栏 750 / 抽屉 740 / 详情抽屉 700 / 罗盘 660 / 水印 640——保留不迁移（§3.2 归位决定）；
- 4 详情抽屉 Esc 栈（✅ 已随地基施工）、QuickEventNote（✅ Esc 栈 + Teleport + z-pop 已随地基施工）、标定卡 z-modal（✅ 已随地基施工）；
- 墨色调色板（ink rgba 家族：刻度线/罗盘「北」/水印/空白舆图毛边）= 品牌纹理整体保留，不进 §2.5 pastel 问题域；
- 空白舆图 BLANK_ATLAS_INNER 生成物、罗盘摆动动画、地图右键菜单结构；
- 抽屉与弹层内的信息架构（字段、分区、表单顺序）；
- `velluma:world-refresh` / `velluma:world-version` / `velluma:quick-note` 事件契约。

---

## 13. 验收清单

> G = grep/脚本；M = 目检；I = 交互手测。证据本地留存不入库。

- **W-01【M】** 图标栏三组标签（收件/账本/名册）就位，分隔线位置按 §2.2，按钮顺序与施工前逐位一致。
- **W-02【I】** 作者走查三任务（§10 裁决① T1-T3），记录首点结果；3/3 通过方签收。
- **W-03【M/I】** 当前态图标带左缘指示条 + 色底；开详情抽屉时来路图标半亮，二者视觉可区分；Tab 到按钮有焦点环；aria-pressed 随开关切换（DevTools 查）。
- **W-04【I】** 四弹层钳位：在时间轴左缘/右缘/底部各开一次，弹层完整在视口内；小视口（DevTools 800×600）下弹层 maxHeight 内滚不溢出。
- **W-05【I】** §3.3 隔离验证表 V1-V7 逐项过。
- **W-06【I】** 标定卡回归：打开时压盖页内弹层与图标栏，Esc 逐层关闭（标定卡 → 弹层），一次 Esc 只关一层。
- **W-07【I】** Esc 行为：绘制/拾取态 + 弹层同开时按 Esc → 只关弹层，再按才退出绘制态（defaultPrevented 让位生效）。
- **W-08【M】** 刻度数字双主题可读（浅色 secondary/深色对应 token），刻度线墨色质感不变；`.wt-now`、`.wt-flash-ch` 视觉无突变。
- **W-09【M/I】** 罗盘「全图」caption 常驻可读，点击归位全图功能不变；图例 Tab 聚焦后展开。
- **W-10【I】** H1-H4 显形：键盘 Tab 进入卡片即见动作钮；删除类钮静态 45% 可见、hover 全亮；功能（删除/改名/跳转）回归无差。
- **W-11【G】** `grep -rE "font-size:\s*(12\.5|17|19|26)px|font-size:\s*0\.(78|8|85)rem" frontend/src/features/world/` 零命中；`font-size` 字面值仅剩 token、xs/sm/base 及 §7.2 豁免声明（.aw-title）。
- **W-12【I】** 深链：`?panel=cand`、`?panel=character` 等 8 键逐一开对应抽屉（等价点击图标）；`?panel=expectations|worldview` 仍开模态；`?panel=bogus` 静默无动作。
- **W-13【M】** 深色主题全页巡查：图标栏/弹层/刻度/罗盘/图例无瞎眼色、无隐形字。
- **W-14【I】** 冻结项回归：时间轴拖拽/缩放/游标、⇧建关系、浮点年窗刷新后恢复、PATCH 快照——手测一轮无行为差。

**清单条数：14。**

# 施工分期（03 · 批次、文件清单、验收标准）

> 配套 01（架构/token 表）/ 02（逐域施工单）。每批可独立提交、独立验证；批间不互相阻塞，但顺序即依赖序。
> **零回归红线（每批验收必查）**：① `--editor-max-width: 880px` 与纸列几何不动；② 幽灵 mark 的 class 名/节点结构/mark 语义不动；③ 书封六色板与材质渐变不动；④ 古地图画布装饰体系与 Leaflet 结构不动；⑤ 有对拍单测的模块（contextBlockFormat 保字不变式、extensions 34 项、ghostReap、heartbeatSeam）全绿。

---

## P0 · 主题基础设施（纯增量，paper 逐字节零变化）

**目标**：机制立起来，默认主题外观与现状完全一致。

动哪些文件：
1. `frontend/src/style.css`
   - `:root` 尾部新增：签名恒定色浅档（--mint 五枚/--cinnabar 两枚/--foreshadow/--gold 四枚/--truth 三枚/--atlas 五枚）、`--font-serif`/`--font-mono` 别名、`--shadow-sm/md/lg/paper` 浅档、`--mention-char*`、`--find-match*`、`--diff-add-bg`/`--diff-del-bg`、`--overlay-bg`、`--paper-texture:none`、`--font-atlas`（值全部照 01 §2/§3.1/§9）。
   - `:root.dark` 尾部新增同名单色深档值。
   - 新增 8 个主题覆写块（`[data-theme='minimal']` 等 × 浅/深，值照 01 §3.2-3.5）。
   - 新增 body::before/::after 自定义背景层段（01 §1.4）+ `motion-low` 毯式灭动效段（复用 prefers-reduced-motion 规则体，双选择器）。
2. `frontend/src/composables/useAppearance.ts`（新建，接口照 01 §1.2）；`useTheme.ts` 删除、AppShell 引用点迁移。
3. `frontend/index.html`：head 内联防闪脚本（含旧键 `velluma_theme` 迁移，01 §1.3）。
4. `frontend/src/components/AppSettingsModal.vue`：新增「外观」常显 section（主题五卡/明暗三档/背景四选/排版 radio 迁入/降低动效），原「实验：编辑器排版」折叠区删除（位置照 01 §6）。

验收标准：
- `npm run typecheck` 绿。
- 肉眼：不碰任何存储键直接启动=现状逐像素一致（暖纸浅/深）；设置里切五主题 × 浅深共 10 组合，壳/写作台/文风页/书架即时换肤；深色首帧不白闪（Throttle 网络 3G 验证）。
- 刷新后主题保持；旧键 `velluma_theme=dark` 的存量用户首启自动迁移为 paper+dark。
- 世界页地图在十组合下恒定羊皮纸（豁免生效）。

## P1 · token 清剿与 bug 消化（全局查找替换批）

**目标**：bug 8 项清零 + 全局映射总表（02 §0）落地 + Tailwind config 并轨。

动哪些文件：
1. `frontend/tailwind.config.js`：ink/parchment/accent 映射 var()，primary 删除（先 grep 验证零引用）；grep `/opacity` 修饰符用法，命中处迁组件 style（01 §8 施工注意）。
2. `style.css` 本体残留：ghost-draft 两态→token、state-pill/assist-toggle/::selection/btn-primary/card-hover/outline-note fallback/find-match/mention 四色（02 §1.1）。
3. bug 消化：`--accent-500-rgb` 5 文件 8 处→color-mix；`var(--accent,#6366f1)`→var(--accent-500)；outline-note 薄荷 fallback 删除；z-index 归表（02 §5 表）；`--font-serif` 引用 8 处 fallback 删除。
4. 数据页 verdict 第二套语义色→--ok/--warn/--danger（InsightsView + StyleFingerprintSection 健康带/出界点）。

验收标准：
- typecheck 绿；`grep -rn "accent-500-rgb\|#6366f1\|#10b981" frontend/src`（排除地图豁免三容器与 engine 色表）应为空。
- extensions/__tests__ 34 项全绿（find-match class 名未变）。
- 肉眼：选中态紫从冷 violet-600 变回暖靛紫（bug 修复可感知）；数据页同页不再两种绿。

## P2 · 写作台域重构（重灾区）

动哪些文件：GhostRepairedChip、GhostWashChip、GhostWarningsBar、InspectorPanel、SparkDock、BeatCardDock、ThinkingIndicator、ChapterTocDrawer/List、ChapterBadges、RichTextEditor（工具条+extensions diff 色改 class）、PublishModal、ShortcutsCheatsheet、ConfirmDialog、InspirationModal（四件收编 ModalShell）。改法全部照 02 §1。

验收标准：
- typecheck 绿；extensions 测试、ghostReap、heartbeatSeam 全绿。
- 肉眼检查点：幽灵 mint/amber 双态呼吸正常、repaired/wash chip 浅深两档可读、SparkDock 深色段随主题、岔路朱与朱点同色、选区工具条三键语义色、四个 modal 走 ModalShell（Esc 栈/焦点陷阱行为一致）。
- `grep` 四重灾区文件 hex/rgba 残留=0（地图豁免不适用本域）。

## P3 · 世界页散色与抽屉族（豁免边界内施工）

动哪些文件：LocationDetailDrawer（54 处灰系）、EntityDetailDrawer（三态 chip+serif 栈）、CanonTruthDetailDrawer、CanonSection、ReaderMirrorBoard、ReadBookModal（收编 ModalShell）、WorldContextCard/QuickEventNote（z 归表）、WorldTimeline/WorldView/WorldMap 的 5 处字面 serif 栈→`--font-atlas`；三容器头部注释追认「灯下古地图」。**画布装饰色一行不动**。

验收标准：
- 肉眼：地图/时间轴/罗盘/印章十主题组合下零变化；抽屉族随主题换肤且三态 chip/朱砂在新主题下可读；极简主题下地图题字仍衬线（--font-atlas 恒定验证）。
- 真相抽屉「表/里」两卡在五主题下对比度肉眼可读（朱晕+密印不失效）。

## P4 · 书架/大纲/文风/导入抽取/共享层归一

动哪些文件：LibraryView（封面 icon-btn 5 处，书封豁免不动）、OutlineView（StorylineAxis/ChapterCard 朱砂归一）、MarkdownImportModal、ExtractionModal、ExtractionPreviewPanel、ImportProgressTracker、FileDropZone、ImportPreviewTable、QuickEventNote、ReadBookModal（ModalShell 收编收尾）、Toast（语义色）、页面标题/padding/分隔符归一（02 §5）。

验收标准：
- typecheck 绿；导入→抽取→预览→入账全链路走一遍无样式断裂。
- 肉眼：四页标题同字阶同字距、padding 一致；Toast 四态色=token 语义色；书架书封在十主题组合下零变化（豁免验证）。

## P5 · 主题打磨与背景机制验收（收口）

动哪些文件：十组合逐页走查的修补（哪里对比度不够调哪枚 token 值——只改 01 表格对应值，不加新 token）；自定义背景三形态（纯色/图片/纸纹）联调；`docs/design/theme-system/` 三份稿子的「施工实况」批注回填。

验收标准：
- 十主题组合 × 六页面（写作台/世界/书架/大纲/文风/数据）全走查表签字；WCAG AA 抽查：正文文字/纸面 ≥4.5:1（每主题浅深各抽 text-primary/text-muted 两档）。
- 背景图：1920px 压缩、>1.5MB 拒绝 toast、遮罩滑杆、深档遮罩反色、换 origin 后外观丢失可重选（已知行为，写入设置区 hint 文案）。
- `motion-low` 下罗盘/金芒/呼吸全灭；prefers-reduced-motion 行为不回退。

---

## 批次规模速览

| 批 | 性质 | 粗估文件数 | 风险 |
|---|---|---|---|
| P0 | 纯增量机制 | 5 | 低（paper 零变化） |
| P1 | 全局替换+config | ~20 | 中（z 归表逐处核语义） |
| P2 | 重灾区重构 | ~16 | 中（幽灵 mark 红线） |
| P3 | 豁免边界内 | ~10 | 低（不碰画布） |
| P4 | 整编收尾 | ~14 | 低 |
| P5 | 走查打磨 | 视走查 | 低 |

---

## 施工实况批注（2026-09-15 当日施工，P0-P5 全批完成）

**验收总态**：typecheck 零错 · 309 前端测试全绿 · 生产构建过 · 全仓 hex 行 530→130（-75%），余量全部落在声明豁免面（古地图三容器+engine 色表+书封+主题预览卡）。

**逐批落点**：
- P0 ✅ style.css 签名恒定色/atlas 锚点/阴影四件/8 主题块/body::before 背景层/motion-low；useAppearance.ts（useTheme 删除，AppShell 迁移）；index.html 内联防闪脚本；AppSettingsModal「外观」区（五主题预览卡/明暗三档/背景四选含压缩+遮罩/排版迁入/降低动效）。
- P1 ✅ tailwind.config 三族映射 var()+primary 删除；style.css 本体残留清剿；--accent-500-rgb 8 处→color-mix；--font-serif/--font-mono 补定义；verdict 第二套归一。
- P2 ✅ 幽灵三件套/InspectorPanel（36 裸字号归阶）/SparkDock/BeatCardDock/ThinkingIndicator/ChapterToc 两件/ChapterBadges/RichTextEditor（工具条+diff 色）/ChapterEditorView；PublishModal/ShortcutsCheatsheet/ConfirmDialog/InspirationModal 收编 ModalShell。
- P3 ✅ LocationDetailDrawer 39 兜底+紫族、EntityDetailDrawer 三态 chip+衬线、Canon 两件朱砂归一、ReaderMirrorBoard、5 处字面 serif 栈→--font-atlas、三容器头部追认「灯下古地图」、ZHU_COLOR 注释挂 --cinnabar 对拍。
- P4 ✅ 导入/抽取全线（含 MarkdownImportModal/ExtractionModal 收编 ModalShell）；Toast 四态语义色；大纲朱砂归一；书架 icon-btn；页面标题 --text-2xl+0.08em（书架 --text-3xl 例外）+padding 归一；AppSettingsModal 自身残留。
- P5 ✅ 尾扫（SpinePanel/WorldSceneSlice/Foreshadow 两件/QuickCapturePanel/WorldviewPanel/BulkImportDialog/ReaderMirrorBoard/Canon 词标三色）+全仓 121 处已定义 token 冗余 fallback 剥离。

**与设计稿的偏差（6 项，均已在代码注释留痕）**：
1. **diff 色 class 化未做**：改用 `setHighlight({ color: 'var(--diff-del-bg)' })`——mark 结构零改动（红线更稳），效果等价（无字面色+主题自适应）；确认/拒绝流程本就 unset 高亮，无持久化污染。
2. **❦ 章节分隔符统一未执行**：排查发现现存 `*`/`——`/`·` 几乎都在正文语义文本与 placeholder 里（改了=改文案），纯装饰分隔位未成规模——挂起待真出现再收编。
3. **Tailwind accent 映射范围比 §8 假设宽**：accent-50/100/200/300/700-900 实际在用（设计假设零引用可删），已全部映射（50-300=accent-500 color-mix 派生、700-900=accent-600）。
4. **撤销钮 ink-900 特例**：`bg-ink-900 text-white` 映射后深色主题下不可读（--text-primary 深色变亮色），改 `bg-[var(--text-primary)] text-[var(--bg-canvas)]` 保持「反色 chip」双主题可读。
5. **背景属性挂 documentElement 而非 body.style**（§1.2 偏差）：index.html 内联脚本运行时 body 未解析，html 挂点 body::before 经继承消费，两处写入点统一。
6. **QuickEventNote z 96→111**（z-modal 110 带内微调，撤销胶囊压模态一层）；**ReadBookModal 实况修正**：盘点称未走 ModalShell，实际已走，仅修 4 处未定义 --bg-muted 与 #fff。

**留待真机走查（无法静态验证项）**：十主题组合 × 六页面肉眼对比度走查表；自定义背景三形态联调（选图/压缩/遮罩滑杆/深档反色纱）；motion-low 下罗盘/金芒/呼吸全灭验证；Electron 深色首帧不白闪（Throttle 3G）。

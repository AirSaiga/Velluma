> 本文自 AGENTS.md 拆分而来（编辑本领域代码前必读）

# 世界设定层（World，★ 静态设定的唯一编辑源与生成数据源）

事件溯源式世界建模器。已有设计文档（勿重复，此处只收契约）：`docs/reports/location-interior.md`、`docs/world-writing-bridge.md`、`docs/reports/canon-world-fusion.md`、`docs/reports/implicit-graph-projection-feasibility.md`、`docs/reports/scene-transit-feasibility.md`、`docs/design/canon-fusion/`、`docs/design/truth-ux/`。时效施工/事故叙事见 `docs/incidents/world.md`。

## 数据模型与推演内核

- `world_events`：append-only 事实源，11 种事件类型；`title` 可编辑显示名，前端 `eventDisplayName` 唯一回退链：title→事件类型模板 label。
- `world_entities`：人物/势力/资产固有属性，档案在 `props` JSONB 表驱动。
  - 单分组 `group_name`：详情抽屉「分组」输入失焦即存 + 既有组 datalist 候选；资产面板按组折叠、未分组恒居首、全未分组零视觉变化；纯组织元数据**不进 prompt 档案装配**。
  - ⚠ 清空靠 repo update 白名单 `_ENTITY_EXPLICIT_NULLABLE`——显式 null 才写 NULL，勿回退成裸 `if v is not None` 跳过。
  - 分组判据纯函数 `engine/entityGroups.ts`（带对拍）。
- `world_locations`：内部构造 `parent_id` 树（`docs/reports/location-interior.md`）。
  - 渲染不变量：上图权 = `parent_id IS NULL`。
  - LocationDetailDrawer 二级面板面包屑下钻；速记/事件表单/场景钉/浮卡全房间级可达。
  - 场景作用域 `scene_scope_ids`：钉房间时祖先算在场；场景身份块带地点档案（无 intro 零变化）。
- `world_relations`：static 或事件锚定的时变关系。
- 另有地图底图表 + 候选事件池 `world_event_candidates`。
- 世界状态推演：任意时刻状态（谁在哪/生死/疆域/关系）由 `compute_world_state_from_events` 纯函数折叠推演；前后端同构（前端 `features/world/engine/`）。
  - 生死语义「出场即活」：无 birth 事件但被推演回放（move 等）的角色默认活、death 才死（有 birth 的书零变化）。同构实现：`world_repository.compute_world_state_from_events` + 前端 `engine/computeWorldState.ts`，改任一侧必须同步。
- 世界内核配套（B 系列）：事件源 v2（时序边/supersedes/time_precision）+ intent 统一存储（world_intents）+ belief 认知域 + provenance 信封与 finish 现实校验（run_reality_check）+ Depiction 呈现层（`POST /world/depictions/backfill` 回填气闸 + confirm/reject）+ 冷层 digest（world_digest_sections，stitch 双门未签发）+ salience 热层影子（trace-only，dock 具名提示走 `SALIENCE_DOCK_LANE` 单车道）+ 认知浮现三时机（`GET /world/cognition-surface` + `books.cognition_surfacing` 总开关）。设计文档：`docs/world-kernel-foundation.md` + `world-kernel-construction-plan.md`。

## 活舆图画布（UI）

- 单一画布（M6「活舆图」）：地图（Leaflet）承载全部实体/关系/事件；脑图透镜已退役，⇧拖建关系等手势平移至地图。
- **悬浮胶囊工具条**（记一笔历史/地点/实体/世界观/⋯）取代顶栏；**右缘 46px 图标栏 + 浮出抽屉**（待确认/伏笔/期待/真相/地点/事件/角色/势力/资产）取代右侧栏；书名水印题字。
- **空白舆图**（无底图时铺手绘风地球世界平面）：
  - `blankAtlas.ts` 的 `BLANK_ATLAS_INNER` 是生成物——由 `scripts/make_blank_atlas.py` 从 Natural Earth 50m 海岸线/湖泊/河流/国界生成；改轮廓/装饰锚点先改脚本再重跑。
  - 等距圆柱投影·中央经线 40°E（欧亚大陆居视觉中心，切线 140°W 过东太平洋，阿拉斯加/阿留申分列两缘）。
  - svgOverlay 随图缩放，viewBox 与 bounds 必须同为 2:1 防纵向变形；海岸线走 `wm-ink-soft` 细毛边滤镜；国界点状虚线/山河/经纬网；提示收进浮动卡；首个实体落地即退场。
  - 空白态初始视野框住世界平面，用户拖/缩后不再插手；数据缓存 `data/atlas-src/` 已 gitignore。
- **罗盘**（实功能）：点击「回到全图」视野收拢到内容包围盒；针平时轻摆、点击大摆归北。
- 表单体验：textarea 统一走共享指令 `v-autogrow`（`presentation/autogrow.ts`，随内容长高、max-height 封顶）。

## 时间轴（编年史带）

底部时间轴：含章节叙事锚 `chapters.narrative_time` + 伏笔弧线带。

### 布局纯函数

- 自动视野贴合内容时刻集（事件起止/章节锚/伏笔埋收 ±8% 边距、最小 2 年窗，不再是创世 0 年起铺满）；像素自适应刻度/分行同走 `engine/timelineLayout.ts` 纯函数（对拍 `__tests__/timelineLayout.test.ts`）。
- 同时刻事件点/章节片纵向贪心分行，时长事件画起讫横条；悬停预览线+时刻气泡、◂▸ 上/下一事件步进、空事件书轨道内引导文案。

### 缩放与刻度

- Ctrl/Cmd+滚轮缩放可精确到日（悬停点为锚、×1.3/档、最小 7 天窗，缩到比自动窗还宽即回自动）。
- 刻度三档降档：年档（>3 年，对齐步长整数倍）/ 月档（>62 天，年界恒选 major；**13 月=年末 5 天残月不出刻度**——标签会与 5 天后的年界主刻度撞车，日档仍如实标）/ 日档（月初 major+日网格 minor）。

### 手势分工

- 轨道拖拽=平移窗口（>4px 阈值防误触，未过阈值=点击定位游标，触底保跨度；自动窗下拖拽即物化手动窗）。
- 游标柄拖拽=移动游标（`.wt-cursor` 带 ±6px 隐形抓取带）。

### 持久化契约（⚠ 高频事故区）

- 视野窗口以浮点年持久化：窗口日计数=[round((start-1)*365), round(end*365))——start=1+起日/365（1 基年坐标）、end=止日/365（0 基坐标）；整数年与旧语义逐日等价、存量零迁移。
- ⚠ 浮点窗口落在单年内时 start 可大于 end 近 1 年，合法性只看日空间非空（end>start-1 且跨度≥1 天），**勿改回 start<end**。
- ⚠ PATCH 必须携带 `{cursor, range}` 全量快照（`useWorld.buildViewPatch`）——服务端是读-改-写键级合并，两键分头发 PATCH 并发必丢键；滚轮走 pendingRange 本地即时生效 + 600ms 防抖落盘。
- 时间轴 UI 状态（游标时刻+手动视野窗口）按书持久化于 `books.timeline_view`：`GET/PATCH /books/{id}/timeline-view`（键级合并、显式 null 删键，前后端校验同构 `engine/timelineView.ts`）。
- ⚠ 勿用 localStorage 存世界页状态：启动脚本端口扫描换 origin 即漂移。旧 `velluma:tl-*` 键仅作一次性迁移来源。
- 快捷视界胶囊：头部快捷视界组=以游标为中心的跨度预设（含「全局=回自动视野」档），点击走 `setTimelineRange` 立即落盘（与「框定视野」表单同路径）。

## 生成桥接（world_bridge，已接通）

- `services/context/world_bridge.py`：世界页有实体时 settings_bundle 走 **world 优先**——实体/关系经鸭子类型适配器包装成旧 Character/Asset 形状（下游 hard/soft/nutrients 零改动）。
- `dynamic_state` 自动携带叙事时刻推演状态（「位于北岸要塞」「在途（进度 40%）」「已死亡」）。
- 叙事时间四级降级：本章锚→前序最近锚→事件最大时刻→0；切片条显示来源小字+「锚定本章」快捷入口；建远期事件时表单内联警示。
- 在场提权（P5）：角色名单排序键=在场（命中本章场景钉，**死者不进在场集**）→有事态→重要度；无场景钉零变化。
- 私有语义（P5）：`visibility=private` 实体档案不进 prompt 文本装配，改入 secrets 通道（第七块「你知晓但绝不能直接写出」，对齐 canon `[private]`）；内部算法消费者仍吃全量——双轨纪律。
- `bundle.world_state/world_time/world_sourced` 携带切片快照。
- 桥接失败/世界为空 → 旧表兜底（未迁移书行为不变）。

## 章级在场改推演

- 原角色/资产/地点勾选绑定（chapter_entities 等）退役——「本章在场」由事件按叙事时刻推演：`GET /world/state-for-chapter/{chapter_id}`（SceneSettingsPanel 只读展示）。
- entity-mention（@/#）建议与创建均走 world（无世界数据回退旧表），不再写章级绑定。

## 写作桥（world-writing-bridge，W1-W5lite 已上线）

设计唯一权威：`docs/world-writing-bridge.md`。

- ① **此刻此地切片条**：`GET /world/scene-slice`（副驾抽屉「此刻」tab，替换旧 SceneSettingsPanel；在场/脚下含疆域控制方/相遇/头顶的线，与生成上下文同源）。
- ② **情境浮卡**：`GET /world/context-card`（选中文本/点击提及）。
- ③ **世界速记**：`POST /world/parse-event`（Alt+N；**解析/落库分离红线**——只产草稿，作者过目才入账）。
  - `chapter_id` 可空：世界页速记入口缺省书级此刻（最大章锚→事件最远处→0）。
  - 响应带 `new_entities`/`new_locations`（速记里名单外的名字草拟：名字+类型猜测+`evidence` 原文逐字子串过后端硬闸）与既有实体 `aliases` 口述原词自动回填。
- ④ **候选回流**：`event_scout` 独立组件（orchestrator 注册，settle 带段/finish 带整章各触发一次，auto_read 为主产源）→ `world_event_candidates` 待确认池（与事件账本物理隔离）→ 切片条收件箱 + 世界页「待确认」分区 ✓/✗/撤销。**02 候选回流修缮四件套（2026-09-18，设计稿 `docs/next-phase/02-candidate-reflow-repairs.md`）**：
  - **候选补出处（M1）**：抽取 prompt 要求 LLM 给 `evidence`（正文原句逐字摘录 ≤60 字）；event_scout 落池前 `verify_evidence` 校验（去空白子串——标点不同=改写判废；剥除+`evidence_invalid` 计数，候选保留降级无出处档）；前端三面展示（收件箱行悬停/批量模态引文行/世界页卡片悬停）；旧候选无 evidence 零报错。
  - **单事务撤销（P2b）**：`POST /world/candidates/{id}/undo-accept` 删转正产物+回 pending 一个 commit 完成；accept 时产物 id 记入 draft（`accepted_event_id`/`accepted_canon_node_id`），存量候选请求体显式 id 兜底，产物已被单独删除幂等 reopen，非 accepted 态 409。
  - **拒绝史防重（P3）**：`WorldCandidateRepository.list_recent_rejected`（30 天窗/近 200 条，updated_at 倒序）进归一化判重（`auto_reject` 系统假拒绝不计）；命中不入箱静默落台账 + `suppressed_rejected` 计数（auto-read 响应带出——「重复投递拦截次数」度量口径）；池加载失败按空池继续。
  - **键盘裁决（M3）**：↑↓ 移动 / →·Enter ✓ / ←·Delete ✗ 全键盘批候选（纯函数 `composables/inboxKeyboard.ts` 对拍锁定；批量模态另支持 Space 勾选剔除 + Enter 确认；鼠标路径不变）。
- ⑤ **保鲜三时机**：章节切换/心跳 `world_version`/窗口聚焦（`useWorldSlice` 单例）。
- ⑥ **深链往返**：世界页 URL `?entity|loc|fs=&time=&from=chapter&chapter=`（世界页「返回本章」）；`?fs=` 开伏笔详情抽屉；`?panel=expectations|worldview|canon` 开对应账本/真相格；写作页「头顶的线」伏笔/期待行可点击。
- ⑦ **本章场景钉**：`chapters.scene_location_id`。
- ⑧ **光标派生取景框**（`docs/reports/scene-transit-feasibility.md` 唯一权威）：`services/world/active_scene.py` 纯函数 `resolve_active_scene`。
  - 光标前 ≤2000 字窗逆扫「转场动词×名册地点名（含别名/无坐标房间）」最近命中；动词表=`LOCATION_JUMP_VERBS` 11 词+室内扩充推门/跨进/拐进/摸进/闪进。
  - 命中句须已完结（地名后到尾有句末标点=无状态滞回防抖）+闪回豁免（`FLASHBACK_WORDS` 跳过继续向左）；无命中回退本章钉。
  - `pre_cursor_window`=recent_text 尾锚定章文本取窗，找不到锚回章尾。
  - 接流四线：orchestrator stage 签名/`presence_fingerprint` 换派生景（extra `active_loc_id` 直供 dock 防重算）；dock `onstage_projection` 提及窗从当前段 500 扩为光标前窗（**随身物随行**：上一场提及的工具包换场在册）+心跳响应带 `active_scene`（前端切片条「此刻取景（正文推导）」微标+一键钉定）；stitch_context 派生（rolling+fragment）→ kg 场景身份块渲染面换「当前场景：X（按正文推导）」+地点档案链随派生地（选择面/前缀冻结不破）+`ctx.active_loc_id` 供 location_jump 穿越闭包换中心（进屋后脸盆不再误报）。
  - 对拍 `test_active_scene.py`（18 项）+ `test_dock_onstage.py` 随行物用例。
- 事件解耦：`velluma:world-version` / `velluma:world-refresh` / `velluma:quick-note` / `velluma:active-scene`。

## 真相层（Canon 融合 C1/C2/C3）

设计文档：`docs/reports/canon-world-fusion.md` + UX 稿 `docs/design/canon-fusion/`、`docs/design/truth-ux/`。信息层（作者真相 vs 读者认知）并入活舆图，图标栏账本族第四格「真相」。

### 真相账本与详情抽屉

- `CanonSection`：表里三态过滤 秘密/半露/公开 + **句子优先录入**「＋ 记一条真相」（C1 过渡期建「叙事」自由节点）。
- `CanonTruthDetailDrawer`：按「读者现在知道吗？/打算怎么抖出来？」两问组织——**表**（读者目前看到的版本，`public_text`）/ **里**（实际真相 · AI 死守，`canon_text`）两卡就地编辑失焦即存；表/里退居角标，「里」朱晕+密印+泄密警示。
- 句子录入不自动弹详情（行落账顶闪朱+toast 闭环）；问二/标签收「补充」折叠区有值自动展开。
- 第几章揭带提醒回声：写到 N−2 章感知带提醒（canon_watch ≤2 章既有规则显性化）。
- 动作行只剩「贴段正文查泄密」（09-03 起此名，原「查片段」）+删除。
- 已退役：因果图谱模态（`CausalityGraphModal` 删除、cytoscape 依赖同卸）与连锁分析；详情「钩子」字段区（存量 hook 条目显示迁移指引行）、已挂接条目类型下拉（只读徽标，类型随对象推演）。
- ⚠ 保留勿删：后端边表/CRUD 与 `/impact` 路由保留零数据风险；`useCanon` 边契约同步保留（注释标勿删）。
- **后端零改动红线**：canon.py / canonApi / 生成消费链 `[private]/[public]/[hook]` 三段格式冻结不动；泄密检测（canon_checks/canon_watch）与 CanonHighlight 零感知。
- 旧入口退役：AppRail「脑图」删除；`/canon/:bookId` redirect → `/world/:bookId?panel=canon`；`features/canon/` 目录删除。
- `useCanon` 在 `world/composables`（ensureLoaded 幂等 + CRUD 后广播 world-refresh）。

### C2 信息面挂接

- `canon_nodes.ref_type/ref_id`：label/type 读取时由世界对象推演（根治名字漂移）。
- hook 并入 `plot_ledgers`（canon_text/public_text/reveal_plan 列）。
- `/world/migrate-canon`：预览确认迁移。
- `build_canon_context_for_prompt` 换源——往返契约单测 `services/canon/test_context_contract.py` 锁三段格式。
- EntityDetailDrawer「读者认知」分区为实体 overlay 唯一创建口（create 幂等护栏）。

### C3 揭示与候选

- 提取候选入待确认池：`source=canon_extract`，accept 分流建 tentative 真相节点。
- 时间轴揭示朱点 + 心跳揭示临近提醒（`expected_reveal_chapter` 距本章≤2 章）。

### 字段级真相分层

- 档案单字段与「一句话」intro 可标 半露/秘密（EntityDetailDrawer 字段旁 chip 循环 公开→半露→秘密）；**字段内容本身即「里」**，半露只需内联补「表」+可选「第几章揭」。
- 存 `world_entities.field_layers` JSONB：`{field_key:{level,public_text?,reveal_chapter?}}`，缺键=公开零存储；key=intro 时全文取 `ent.intro` 非 props。
- **派生感知取代物料迁移**：不建真相节点副本，单一事实源在档案。
- 五条消费线：
  1. 档案拼装拆分：`static_prompt_from_world_entity` respect_layers——秘密字段隐去/半露以表顶替/表空按秘密安全缺省；整人私有走 secrets 通道时 respect_layers=False 不拆；资产走 `WorldAssetAdapter.static_description` 的 intro→description 回退链逐层拆（faction 字段不进适配器文本、仅经 ② 注入）。
  2. canon [private] 段虚拟条目注入（`- 实体名·字段名：里（读者目前只知：表）`，`_collect_field_layer_entries`；整人私有实体跳过防重复注入）。
  3. `check_consistency` 泄密短语源扩展（partial 抽取集=全文短语−表短语，表里共词豁免）。
  4. ghost_guard 3b 字段秘密检（`bundle.field_layer_secrets` 由 overlay 适配器派生零额外查询，secret_leak 同款判据→返修环 rewrite 资格贯通）。
  5. `read_merge_reveals` 第三来源（字段 reveal_chapter 走同一 ≤2 章窗+逾期 1 章，source=field_layer）。
- 真相账本「来自角色档案」派生分组（受三态过滤不计 counts，点击深链实体抽屉）。
- 共享判据双权威同构：后端 `services/world/field_layers.py` / 前端 `engine/fieldLayers.ts`。
- 零变化契约：无 field_layers 的书 prompt 逐字节不变。
- 对拍 `services/world/test_field_layers.py`（17 项）+ `engine/__tests__/fieldLayers.test.ts`（8 项）。
- 「读者认知」overlay 分区保留——承载不属于任何字段的整人真相，与字段分层互补。

## AI 写路径（M4）

- `content_extractor.commit_extraction` 与 adaptive 沉淀落库改写 world_*。
- 角色档案全文进 `props.background`——**迁移而非兼容**：历史 `props.legacy_profile` 已并入 background 并摘键，读写两侧均无 legacy 回退。
- 未迁移书首次 AI 落库前自动执行幂等迁移（防 world 优先切换后旧角色从生成上下文失踪）。
- 伏笔（PlotLedger 共享表）与向量记忆不变。

## 编辑入口收敛与设定中心退役

- 设定页角色/资产/地图（M4）+ 伏笔账本/期待账本/世界观（M5）分区已退役为跳转卡，随后「创作笔记」随 global_sys_prompt 死线整线退役。
- `features/bible/` 与 `components/NotesPanel.vue` 删除（清单 frontend/_deprecated/README.md）；AppRail「设定」项移除；`/bible/:bookId` 重定向世界页（canon 先例）；后端 V3 生成链 prompt 模块+`/clarify-outline`+ClarifyOutline schema 同批归档（backend/_deprecated/README.md）；`books.global_sys_prompt` 列冻结只读。
- 文风已迁独立文风页 `/style/:bookId`（见文风域档案）。
- 设置拆三入口：「外观」左缘无遮罩抽屉 `AppearancePanel.vue`（主题/明暗/背景/稿纸排版/动效，即时生效无保存钮）；「API」独立弹窗 `ApiSettingsModal.vue`（双模型槽/预设/厂商目录/向量/deai/代理/连接测试）；「设置」瘦身弹窗 `AppSettingsModal.vue`（仅通知偏好）——`useAppSettings` 单例三路开关，任何页面可达。
- 旧面板已删除：CharacterPanel/MapSettings/asset-panel/ForeshadowingPanel/ReaderMirrorPanel/WorldviewSettings/SettingsPanel。
- M5 世界页承载（M6 起位于图标栏抽屉/胶囊条）：「伏笔」抽屉（`ForeshadowSection` 全量账本+状态筛选，未锚定伏笔的唯一可见处）+ `ForeshadowDetailDrawer`（就地编辑/未锚定一键锚游标/回收/废弃/删除 undo）；「期待」摘要 + `ReaderMirrorModal`（火候看板/张力曲线整面板迁入）；胶囊条「世界观」+ `WorldviewModal`（2s 防抖自动保存/导入导出）。
- 伏笔/期待/世界观编辑后统一广播 `velluma:world-refresh` 刷新写作页切片。

## 数据库卫生批

- `scripts/check_db_hygiene.py`：检测+修复二合一幂等脚本；五检测项（R1 格式/R2 记忆/R3 伏笔/R4 摘要/R5 报告项），`--fix` 自动备份（`data/backups/velluma.pre-hygiene-*.db`），幂等二跑全绿。
- 五类修复（各含存量修复+读/写侧防御）：
  1. **事件 id 引用格式归一**：events/candidates 的 JSONB 引用列统一带连字符 str(UUID)——读侧 fold/world_bridge/前端 engine 全按此匹配；写入侧防御 `routes/world.py _normalize_event_fields`（payload 深层同归一）。
  2. **fold 生死语义「出场即活」**：见「数据模型与推演内核」节（与 ① 同批，防归一后无 birth 事件的批量导入书全部出场角色显形判死）。
  3. **RAG 陈旧记忆清重**：清掉与当前正文对不上的 memory_chunks，走 `index_chapter_memories` 章级替换按当前正文重建；⚠ 检测比对的剥 HTML 必须用 `html_to_plain` 唯一权威（自写剥标签因换行规则不同会把重建块误判陈旧）。
  4. **伏笔账本复本删除**：`-2` 同内容复本会导致开放伏笔素材块双份注入。
  5. **假前情摘要置 NULL**：专有名词现正文零命中的旧版摘要会经 previous_summary 接力棒把假「上一章结尾」注入下一章。

## 隐式图谱投影器（原型，消费方暂无）

- 调研：`docs/reports/implicit-graph-projection-feasibility.md`。`services/world/implicit_graph.py` 三件：
  - 数据契约：`EventCard` 超边原子 / `SubgraphNode` / `SubgraphSlice`。
  - `project_active_subgraph` 纯函数（事件流→在场连通子图）：1 跳在场共现 + 2 跳仅 `MAJOR_TYPES`{death/battle/territory_change/destroy/coronation}∪近 90 天窗外扩；**EventCard 超边永不展开 N² 点对**（battle 十人混战=1 张卡）；三道帽=每根 per_root_cards 张 / 2 跳每成员一卡且总数 ≤second_hop_cards_cap / 全局 node_cap=40；时态纪律同 fold：`time_start≤t` + supersedes 排除 + `(time_start,sequence_num)` 倒序最新优先。
  - `format_subgraph_for_prompt`：空卡空串零变化契约；时刻换算与前端 `timeFormat.ts` 同构（365 日/年 30 日/月创世元年）；note 缺失回退参与者名单。
- ⚠ 消费方暂无（纯原型）：P1 接 knowledge_plane event_card 通道/前缀签名并入事件哈希待拍板；红线=提及驱动卡走 recency 后缀防击穿前缀缓存。
- 同批补漏：`world_repository.list_all_by_book` 读侧排除 superseded（fold 推演/编年史/RAG 结构化召回/世界页列表五消费方一处生效；当前库零使用=行为逐字节不变）。
- 对拍 `services/world/test_implicit_graph.py` 19 项（时态单调/未来与 superseded 不入图/超边防爆节点线性/2 跳过滤/上限截断/格式含时刻对拍/性能 500 事件×100 次均值 <2ms/repo 过滤真实栈）。

## 待办

- 旧表冻结声明已落 8 处在役模块（下次实质改造换源 world）。
- 写作桥 W5 余项：全图读者滤镜（等切片条读者档使用数据）；相遇→走向卡桥的采纳率验证（`encounter_card_burst_rate` 度量已埋）。

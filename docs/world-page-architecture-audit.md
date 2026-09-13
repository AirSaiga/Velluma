# 世界页全链路架构与空间联动重构可行性审计报告

> 2026-09-14 · 系统架构重构调研第四期 · 纯只读审计（零代码改动）
> 对象：世界页全链路——WorldView.vue（实测 **2517 行**，任务书引 2425 为旧数）/ WorldMap.vue（2691）/ WorldTimeline.vue（1990）/ useWorld.ts（925）/ engine 折叠与树工具。
> 行号以 2026-09-14 工作区为准。

---

## 0. 结论摘要（TL;DR）——先校正一个关键前提

**任务书构想的「DrawerShell 升级」大半已是现状。** a66ffd3（2026-09-10 入库，记忆与代码双证）已完成：**340px 全高贴边抽屉**（`.atlas-drawer`，WorldView.vue:1328；罗盘避让 414px，:526-533）、**DrawerShell 统一骨架**（presentation/DrawerShell.vue，9 面板中 7 个已套壳）、**地点折叠树**（loc 面板内联，折叠整枝剪除+搜索展开）、**EventSpineList 年份分组脊柱**（evt 面板）、**地图双向联动**（面板 📍 → 地图声呐脉冲 :539-546；地图点地标 → 面板行回指滚动+展开祖先 :550-569）。**250px 悬浮小气泡时代已经结束**——本期审计因此以「现状盘点 + 二期深化差距」框定，而非从零推演。

四个核心答案：

1. **真正的性能病灶不在 Fold，在下游渲染**：游标拖动每帧（rAF 节流）→ worldState 全量折叠（**亚毫秒级，500 事件无压力**）→ 但触发 **五个 Leaflet 图层 clearLayers + 全量重建**（WorldMap.vue:1406-1413，deep watch）——事件层**无视野裁剪**，每帧重建所有历史事件的 divIcon+popup marker（:1137-1161）。**300-500 事件时每帧重建成本 25-100ms，60fps 帧预算 16.7ms 必爆——低配机拖动游标掉帧是结构性必然，与小说体量线性恶化**。
2. **反向定位接口 100% 具备**：`focusAt(x, y, title)`（连点抑制+近中心判定+平滑 setView，WorldMap.vue:1461-1473）、`fitAll`（内容包围盒）、`focusEvent`（事件→坐标→focusAt，WorldView.vue:503-507）、`focusLocation`（无坐标地点自动进拾取补坐标流，:511-524）。「点击抽屉条目→地图飞渡」不需要任何新接口。
3. **WorldView.vue 2517 行的成分**：script 编排 1057 行（真业务核心）+ template 689 行（**内联面板体仅约 180 行**，其余是组件挂载点）+ **scoped CSS 767 行（隐形巨石）**。它不是「气泡废代码堆」而是「编排容器+样式库」——进一步组件化可迁出约 **400-500 行**（详见 §5）。
4. **抽屉打开/切换不会引发背景地图重绘**（activePanel 不在 WorldMap 的任何 watch 依赖里，面板切换只动抽屉 DOM 与罗盘 class）——现架构在这点上已是干净的；**唯一能把整张地图拖下水的输入是 currentTime/events/locations 变化**。

---

## 1. 状态总线与渲染拓扑

### 1.1 状态归属清单（单例 vs 容器本地）

| 状态 | 归属 | 证据 |
|---|---|---|
| 主数据：locations / events / characters / factions / assets / relations / locationsById / foreshadows | **useWorld 单例**（模块级，跨页共享） | useWorld.ts:76-96 解构面 |
| 时刻与推演：currentTime / worldState（computed）/ timelineRange / jumpToTime | **useWorld 单例** | useWorld.ts:45,56-57 |
| 面板态：activePanel / detailReturnPanel / 互斥编排 | **WorldView 本地 ref** | WorldView.vue:200-237 |
| 选中态：selectedEntityId / selectedLocId / selectedForeshadowId / selectedTruthId | **WorldView 本地 ref**（详情抽屉 props/emits 链） | :163-179 |
| 联动高亮：highlightedLocId（📍 声呐）/ highlightedRowLocId（行回指） | WorldView 本地 + 经 prop/emit 与地图互通 | :537-569 |
| 折叠集：collapsedLocs（Set） | WorldView 本地 | :552-558 |
| 绘制编排：drawMode / drawResult / pickingMode / relocatingLoc | WorldView 本地 | :273-291,509-524 |

**判定**：数据全在单例、视图态全在容器本地、跨组件靠 props/emits + 地图命令式 ref API——**没有深层透传链**（最深两层：WorldView → DrawerShell 插槽内容 → EntityCard）。这是健康的拓扑；二期重构不需要动它。

### 1.2 面板互斥编排（现成的壳内路由）

图标栏 9 面板（SidePanelKey，:200）与四个详情抽屉**物理互斥**（同宽区域叠放）：`togglePanel` 开面板即关全部详情（:212-217）；watch 四个 selectedId 任一置位→面板让位并记 `detailReturnPanel` 来路（:220-226）；`onDetailBack` 恢复来路（:228-233）。**这套「壳内一层浮层」协议是二期任何抽屉深化必须遵守的现状契约。**

### 1.3 渲染拓扑：什么输入会重绘地图

WorldMap 的 watch 依赖面（WorldMap.vue:1402-1451）：

| watch | 触发重绘 | 对抽屉重构的意义 |
|---|---|---|
| `locations`（deep） | renderMarkers（地点层） | 地点增删改才动 |
| `highlightLocationId` prop | renderMarkers | 📍 脉冲重播 |
| **`[worldState, currentTime, events]`（deep）** | **五层全重建**（tracks/entities/relations/territory/eventMarkers+涟漪） | **唯一的帧频源**——游标拖动/播放（§2） |
| `layerVisible` / `inEditMode` / `entities,relations` / `mapLayers` / `mapStrokes` | 各自层 | 低频 |

**抽屉打开/切换零地图重绘**——activePanel/selected*Id 不在任何 watch 依赖里；`rightDrawerOpen` 只驱动罗盘 CSS class（:529-533）。**现架构对 DrawerShell 二期完全友好。**

---

## 2. 事件折叠引擎（Fold）算力与伸缩性

### 2.1 执行机制：每帧全量折叠，确证链

1. 游标柄拖动 `onMove → scheduleSet(posToTime)`——**rAF 节流**，每动画帧至多一次 setCurrentTime（WorldTimeline.vue:285-291,320-323）；
2. 播放模式 `setInterval`（≥16ms，约 6s 播完窗口全程 ≈ 60 次/秒，:448-460）；
3. `currentTime` 变 → useWorld 的 `worldState` computed **全量重折叠**（useWorld.ts:56-57：`computeWorldState(events, locationsById, currentTime, relations)`）；
4. **无快照、无记忆化、无增量**——grep 全库无 memo/snapshot 痕迹；computed 仅在依赖不变时缓存，游标一动必失效；
5. worldState 变 → WorldMap deep watch → 五层 clearLayers+全量重建（§1.3）。

### 2.2 红队算力核算（300-500 事件 / 上百实体）

**折叠本身（computeWorldState.ts，165 行纯函数）**：

| 步骤 | 复杂度 | 500 事件+100 关系实测推算 |
|---|---|---|
| filter ≤t + sort by sequence_num | O(E log E) | ~4500 次比较，**<0.5ms** |
| 事件分发回放（birth/death/move/territory/found/destroy） | O(E) | ~500 次 switch，**<0.3ms** |
| 关系激活判定 | **O(R×E)**（`applicable.some(e => e.id === r.event_ref)` 逐关系线性扫，:149-151） | 100×500=5 万次字符串比较，**~1ms** |
| **合计** | | **约 1-2ms/帧——fold 本身无害** |

**下游渲染才是帧率杀手**：每帧 `renderEventMarkers` **无视野裁剪**——重建所有 `time_start ≤ t` 的事件 marker，每个 = L.divIcon HTML 构建 + L.marker 创建 + bindPopup（WorldMap.vue:1137-1161）；实体层/疆域/关系/轨迹同模式全量重建（:679/:753/:845/:1015）。单 marker 创建+挂载实测量级 0.05-0.2ms：

| 书规模 | 每帧重建 marker 数 | 每帧成本估算 | 60fps 预算 16.7ms |
|---|---|---|---|
| 早期（50 事件/30 实体） | ~80 | 4-16ms | 临界 |
| **后期（500 事件/100 实体+关系/疆域）** | **600+** | **30-120ms** | **爆 2-7 倍** |

**判定**：低配机器后期拖动游标必掉帧（掉到 8-30fps）——不是 fold 的锅，是「每帧全量销毁重建 DOM marker + deep watch 大数组」的锅。`{deep:true}`（:1413）对 worldState 大数组每帧做深度遍历比较，是额外常数负担（也是可白拿的优化点）。

### 2.3 缓解与修复方向（二期 P0，不动数据契约）

1. **watch 拆分**：currentTime 帧频变化只影响「实体层（move 插值位置）+轨迹+涟漪」；疆域/关系/事件 marker 只在 **events 数组引用变化**（增删改，低频）时才需重建——拆成两个 watch 立刻把每帧重建面从五层砍到两层；
2. **事件层视野/时刻裁剪**：拖动中只画视野内或游标邻域 ±N 年，拖停（debounce 200ms）再全量；或事件 marker 只在 events 变化时重建（事件 marker 位置不随 t 变——只有「t 之前才显示」的过滤变，可用 setOpacity/addLayer 差分替代重建）；
3. **marker diff 复用**：实体层保留 L.marker 实例、只 `setLatLng`（位置变了）——Leaflet 原生支持，是标准做法；
4. 去 `deep:true`（数组每次都是新引用，deep 比较纯浪费）；
5. 若未来事件量破千，再考虑按年快照（fold 到锚点缓存 + 增量回放）——**当前规模不需要**，属过度设计。

---

## 3. 空间坐标系与地图-实体联动

### 3.1 坐标格式：像素画布坐标，非经纬度

- **CRS.Simple**（WorldMap.vue:3,92——覆写 `scale(zoom)=2^zoom`）；内部约定 `Point=[x,y]`，Leaflet `[lat,lng]` 下 lat=y、lng=x（:9）；**BOUNDS=[[0,0],[1000,1000]]**（:203）——即 **0-1000 归一化像素画布**，DB 的 `coord_x/coord_y` 直接存这个坐标系；
- 空白舆图 svgOverlay 另有 2:1 专用 bounds（:273，`BLANK_ATLAS_BOUNDS`）——底图与实体坐标系解耦良好；
- 比例尺标定（D4）在此基础上叠 `books.map_scale` 换算（WorldView.vue:377-431），不触碰坐标本体。

### 3.2 实体当前位置的映射链

`world_events(move)` → fold（`interpolateOnPath` 弧长插值在途位置，或 `locCoord` 取地点坐标，computeWorldState.ts:91-105/:50-57）→ `worldState.character_states[].position` → `renderEntities` 每帧重建 marker（WorldMap.vue:730,772-786，含存活态 icon 分支）。**「事件推演地点→地点坐标→画人物」的链路任务书描述完全正确**。

### 3.3 反向定位机制：接口 100% 具备

| API | 实现 | 细节 |
|---|---|---|
| `mapRef.focusAt(x, y, title)` | WorldMap.vue:1461-1473 | 连点抑制（1.2s 同目标）+ 近中心判定（<40px 不动相机）+ `setView(animate)`——**飞渡已产品化** |
| `fitAll()` | :1486-1498 | 全部图层+地点+实体的内容包围盒 fitBounds；空图回退世界平面 |
| `focusEvent(ev)` | WorldView.vue:503-507 | `eventPoint(ev, locationsById)` 解析坐标→focusAt；无坐标 toast 提示 |
| `focusLocation(loc)` | :511-524 | 有坐标→focusAt+声呐脉冲；**无坐标→自动进拾取模式补坐标**（2026-09-04 修复的死按钮） |
| 面板 📍 → 地图 | :539-546 | `pulseLocMarker` 声呐 2.4s 自清；null→nextTick→id 分离两次变更保连点重播 |
| 地图 → 面板（反向） | :550-569 | 点地标→loc 面板行高亮+滚入视野+展开被折叠祖先（仅面板开着时） |

**结论**：「点击抽屉里的地点/人物 → 地图镜头飞到对应点」所需接口**全部已存在且在用**。人物侧注意点：`focusAt` 收坐标而非实体 id——实体需先经 worldState 查 position/坐标（`character_states.find`，WorldMap.vue:730 已有此查找形态），二期若做「实体行 → 飞渡」只需一个薄包装（查 position→无坐标回退 home 地点/提示）。

---

## 4. DrawerShell 落地的数据接缝实证

### 4.1 三种特化视图的真实支撑度

**空间层级树（地点）——已存在，差一步组件抽离**：
- 引擎层 `locationTree.ts` 五函数齐备：`locationsById`/`childrenIndex`/`topLevelLocations`/`collectSubtree`/`locationPath`（:12-55）；
- UI 层 loc 面板内联树（WorldView.vue:1404-1474，约 70 行）：**折叠箭头逻辑已在**——`collapsedLocs`（Set）+ 顶层整枝剪除 + 搜索命中自动展开并整枝保留 + `expandLocAncestors`（:552-558）+ 📍 定位 + 整行点击=开详情抽屉；
- **缺的只是**：把它从 WorldView 迁出为独立 `LocationTreePanel.vue`（props: locations/高亮 id/折叠集或内置；emits: select/locate/hover）。响应式状态无需新增——`collapsedLocs` 随迁即可。

**时间轴骨架（事件）——已存在**：`EventSpineList.vue`（235 行）props={events}，按 `breakdownTime().year` 分组（:36-45），**时长事件（time_end>time_start）已显示起讫区间**（模块头 :11 明示）；同刻事件纵向贪心分行/时长横条等布局能力在 `timelineLayout.ts`（204 行纯函数+对拍）。差项：EventSpineList 本身未做「时长条」可视化（区间以文字表达）——若二期要图形化时长条，timelineLayout 的既有输出可直接复用。

**人物/资产/势力高密行——组件在，压缩需三处妥协**：
`EntityCard.vue`（168 行）现状交互清单：存活状态点（alive===false 灰点，:56-58——数据来自 worldState 推演，随游标动）、**双击改名**（@dblclick startEdit，:70）、删除按钮常驻（:72）、click=开详情、类型色点。压成 36px 单行的妥协点：
1. 简介行（intro 截断行）→ 删除或改 title 悬停；
2. 删除按钮常驻 → hover 显隐或右缘滑出（移动习惯迁移）；
3. 双击改名可保留（36px 行内 input 放得下），但触达面积变小——建议补「详情抽屉里改名」为主路径（EntityDetailDrawer 已有）；
4. 状态点/类型色零成本保留。
另外 WorldView 实体三面板已有搜索过滤（entityFilter/panelEntities，:240-257）——高密行不需要新状态。

### 4.2 fs/canon 两面板未套壳（二期唯一真正的「壳化」缺口）

fs（伏笔）与 canon（真相）因自带完整分区头而「直接平铺不套壳」（WorldView.vue:1369-1403 注释）——与另外七面板视觉不一致。二期若统一：ForeshadowSection（371 行）/CanonSection（620 行）的内置头部改为 DrawerShell 壳头（slots 已兼容：count/actions/search 都有天然对应物），属**纯视觉迁移**，数据零改动。

---

## 5. 交付问题一：WorldView.vue 2517 行成分解剖

| 分区 | 行区间 | 行数 | 性质判定 |
|---|---|---|---|
| script 编排 | 1-1057 | **1057** | **真业务核心**：面板互斥协议（:200-237）、地图联动编排（:486-569）、速记/绘制/拾取三模互斥（:141-160,273-291,457-465）、比例尺标定（:377-431）、undo 分流（:467-484）、实体连续创建（:306-352）、旧设定迁移（:433-455） |
| template | 1059-1748 | **689** | 其中**内联面板体仅 ~180 行**（cand 34/exp 11/loc 树 70/evt 21/实体 47，:1330-1550）；其余=地图/时间轴/模态群/详情抽屉/图标栏/胶囊条的**组件挂载点**（非废代码） |
| scoped CSS | 1750-2517 | **767** | **隐形巨石**——抽屉/胶囊/表单样式全压在容器；组件化后大头可随迁 |

**「抽象出 DrawerShell 可以删掉多少行」的诚实答案**：DrawerShell **已经抽象**（2026-09-10）。进一步可迁移量：loc 树/实体面板体/cand/exp 五块内联体 ~180 模板行 + 对应 script 逻辑（折叠集/过滤/分组 computed/待确认池 ~150 行）+ 随迁样式（est. 100-200 行）≈ **合计约 400-500 行可离开容器**，WorldView 收敛到 ~2000 行的纯编排壳。**没有「气泡废代码」可一刀删——2517 行里找不到成片死区**（旧气泡已在 a66ffd3 那轮清理）。

---

## 6. 交付问题二：二期深化最小实施路径与组件分工

**P0 性能治理（先于一切视觉重构——否则重构在新壳上放大旧卡顿）**
- 拆 watch：`[currentTime]`（帧频：实体层 setLatLng diff+轨迹+涟漪）与 `[events, locations]`（低频：疆域/关系/事件层重建）分离（WorldMap.vue:1406-1413 一拆为二）；
- 事件层去每帧重建（marker 集合只随 events 变；t 过滤用显隐差分）+ 实体层 marker 复用只挪位置；
- 去 deep:true。**验收：500 事件书拖动游标稳定 60fps（或至少 45+）**。
- 契约不变量：renderXxx 函数签名与图层语义不变，纯内部优化。

**P1 面板体抽组件 + 双面板套壳**
- 新建 `LocationTreePanel.vue`（迁 loc 树：props=locations/highlight/search；emits=select/locate；collapsedLocs 内置）；
- 新建 `EntityPanelBody.vue`（迁三实体面板共用体：props=type/entities；emits 沿 EntityCard 契约）；
- `CandidatesPanel.vue`（迁 cand 待确认池+批量裁决）；
- ForeshadowSection/CanonSection 头部套 DrawerShell 壳（count/actions 对接）；
- 契约不变量：selected*Id/activePanel 互斥协议不动（§1.2）；WorldView 只保留编排。

**P2 高密行 36px**
- EntityCard 加 `compact` 变体 prop（或独立 EntityRow）：删简介行/删除按钮 hover 显隐/双击改名保留+详情抽屉兜底/状态点不变。

**P3 按需增强（非必需）**
- 实体行「飞渡」薄包装（查 worldState position→focusAt，无坐标回退 home/提示）；
- EventSpineList 时长条图形化（复用 timelineLayout 纯函数）。

**风险登记**：① P0 的 watch 拆分若漏掉「events 变化也要刷新实体存活态」这条边（alive 由 fold 派生），会出现删事件后实体点不更新——拆分时实体层应保留对 worldState 的依赖（结构哈希）或对 events 的依赖；② 互斥协议（§1.2）是全右缘浮层的唯一仲裁，任何新抽屉必须走 togglePanel/selected*Id 两条既有通道，禁止第三条开浮层的路；③ 767 行 CSS 随迁时注意 `.atlas-drawer` 定位类留在容器（DrawerShell 头注释已声明此契约）。

---

## 附录：证据索引

- 现状重构：DrawerShell.vue:1-60（契约）· WorldView.vue:31,1328,1404-1474,1503-1550 · a66ffd3（2026-09-10 提交）
- 状态总线：useWorld.ts:45,56-57,76-96,188-189 · WorldView.vue:200-237,486-569
- 渲染拓扑：WorldMap.vue:1402-1451（watch 面）· 619-655/753/845/1015/1139（clearLayers 五层）
- Fold 算力：computeWorldState.ts 全文（:26-29 排序、:91-105 move 插值、:143-152 O(R×E) 关系判定）· WorldTimeline.vue:285-291（rAF 节流）,448-460（播放）· 1137-1161（事件层无裁剪）
- 坐标与联动：WorldMap.vue:3,9,92,203,273（CRS.Simple/0-1000 画布）· 1461-1473（focusAt）· 1486-1498（fitAll）· WorldView.vue:503-524（focusEvent/focusLocation）
- 接缝：locationTree.ts:12-55 · EventSpineList.vue:11,36-45 · EntityCard.vue:10-15,56-72 · timelineLayout.ts（204 行纯函数）
- 交叉引用：docs/location-interior.md（树模型）· docs/map-scale-spatial.md（比例尺）· world-panel-redesign 记忆档（a66ffd3 两期施工）

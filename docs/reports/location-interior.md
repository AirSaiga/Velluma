> **归档说明（2026-09-19）**：地点内部构造设计（2026-09-01，已施工 99bbc33）；现行契约见 `docs/agent/world.md`。

# 地点内部构造（Location Interior）设计

> 状态：定稿已施工（2026-09-01，v1 全链路 + 二期消费侧当日接通）
> 范围：`backend/routes/world.py`（locations CRUD）+ `backend/services/world/location_tree.py` + `backend/services/prompts/world_event_prompts.py` + `backend/services/world/event_parser.py` + `frontend/src/features/world/`（LocationDetailDrawer / WorldMap / WorldView / QuickCapturePanel）
> 前置：`docs/world-kernel-foundation.md`（存在论：万物是行、状态靠事件推演）
> 一句话：**大地点上图，内部细节进二级面板；房间是真实的地点行，事件钉得到、浮卡查得到。**

---

## 0. 背景与目标

作者要给「统合局基地」录入内部构造（B2 拘留层 → 拘留室）。此前：

- 存储层 `world_locations.parent_id` 自引用外键 2026-08-28 世界内核施工时已预留，但全库零读零写；
- 录入 UI 只有地图 popup 改名/删除 + 一行 intro；
- 生成上下文里地点只是个名字（intro 不进 prompt），更无内部构造概念。

**目标**：层级录入入口 + 房间级身份——事件可钉到「拘留室」、速记「在拘留室审讯」可解析、浮卡点名即查。
**非目标（v1 明确不做）**：地图缩放分层显示子地点（内部构造一律不上图）；子级手动排序（创建序即列表序）；生成上下文注入（场景钉全路径/房间 intro 进知识平面——消费侧二期，数据格式已备好）。

---

## 1. 数据格式：内部构造 = 真地点行

「B2 拘留层」就是一条 `world_locations` 记录，`parent_id` 指向「统合局基地」。零表结构改动（列已在）。

| 字段 | 内部构造形态 | 说明 |
|------|------------|------|
| `parent_id` | 父地点 id | **非空即内部构造**——判定唯一依据 |
| `coord_x/y` | `null` | 无地图坐标（有父级时坐标被渲染层忽略，见不变量） |
| `kind` | `'point'` 占位 | 几何语义，判定不用它；不加新枚举 |
| `name` | 如「B2 拘留层」 | 幂等键 = **同父 + 归一化名**（跨父同名合法：两个基地各有一个「拘留室」） |
| `intro` | 自由文本 | 完整编辑在详情抽屉（地图 popup 只有一行的那个） |
| `tags` | 如 `['地下','戒备森严']` | 「楼层/房间/设施」分类交给 tags，不建枚举字段 |

**不做成 `metadata_` JSON 附件的理由**：房间要有身份——事件钉到房间、编年史按房间查、浮卡点名即查，全靠「独立行、独立 id」白得；塞 JSON 需另造一套机制，且违背世界内核存在论。

层级深度不限（基地→B2层→拘留室），UI 面包屑下钻。

---

## 2. 不变量（渲染契约）

| # | 不变量 | 落点 |
|---|--------|------|
| I1 | **上图权 = `parent_id IS NULL`** | `WorldMap.renderMarkers` 显式 `if (loc.parent_id) continue`（坐标判空是第二道闸）；后端 `location_tree.py` 同构 |
| I2 | 计数只数顶层 | 地点列表徽标 / 图标栏 / 地图水印 = `topLevelLocations()`——防房间把「12 地点」灌虚 |
| I3 | 删除 = 整棵子树 | 后端 `collect_subtree_ids` BFS **父前子后**逐个删（+canon overlay 逐个清）；前端 undo 快照重建同序——DB 的 `ondelete=SET NULL` 只作兜底，应用层不让子级悬空成顶层孤儿 |
| I4 | 幂等键 = 同父 + 归一化名 | POST create 的幂等闸（同实体纪律）；显式 id 的 undo/redo 重建路径豁免 |

---

## 3. 录入 UX

**三入口通向同一抽屉 `LocationDetailDrawer`**（对齐 EntityDetailDrawer 心智：失焦即存 / v-autogrow / Esc 关）：

1. 地图 popup「详情」按钮（主入口；有子级时 marker 环心加一点 + popup「内部构造 N ›」行）；
2. 右缘「地点」列表：缩进子树（树序展开 + 深度缩进 + 「内部」「N 内」徽标），子级行点击开抽屉，顶级行保留定位地图；
3. 深链 `?loc=`：子地点开抽屉（唯一能「看到」它的面），顶层维持定位地图。

**抽屉结构**：面包屑（统合局基地 › B2 拘留层，点击回跳）→ 头部（名字就地编辑/删除带子树声明）→ 简述（完整编辑）→ 标签 chips → 位置区（内部构造显示「不上图」说明；顶层可定位/清除坐标）→ **内部构造区**（直属子级列表 + 「＋ 添加」行内创建：只填名字和描述，parent 自动归当前地点）→ 底部删除。

**撤销**：建/删走 useWorld 逆命令；删除快照收整棵子树、undo 按父前子后带原 id 幂等重建；轻编辑（改名/简述/标签/坐标）不进 undo（与实体档案同策略）。

---

## 4. 消费联动

### v1（2026-09-01 首批）

| 消费点 | 行为 |
|--------|------|
| Alt+N 速记（parse-event） | 名单子地点带**全路径**（`父·子`，`location_path`）；匹配**全路径优先、裸名兜底**（`_location_lookup`）——「在拘留室审讯」钉到房间级；重名裸名取先建者，歧义留表单 |
| 事件表单（QuickCapturePanel） | 地点下拉全量含子地点，选项显示全路径消歧；move 起终点同 |
| 情境浮卡（context-card） | name 裸名匹配全量列表，子地点天然可查（location_id 直取不变） |
| W4 候选抽取（event_scout） | 名单同 `_roster_text`（全路径），抽取可钉房间级 |

### 二期（2026-09-01 当日接通）——房间级身份进生成上下文与作者所见

| 消费点 | 行为 |
|--------|------|
| 场景身份块（knowledge_plane） | 场景地点名**全路径**；追加**地点档案**行——场景地点及其祖先链的 intro 从外到内（「地点档案：统合局基地：…；B2 拘留层：…」）；全链无 intro 不追加（零变化契约） |
| 在场判定/提权（world_bridge + knowledge_plane） | **场景作用域** `scene_scope_ids`：钉房间时祖先（基地）上的存活角色也算在场/提权——「在建筑物里」是「在这个房间的场景里」的合理上界；顶层钉=精确匹配同旧（零变化） |
| 时态行（`_location_name`） | 角色钉在房间 →「位于X·Y」全路径无歧义；顶层=裸名同旧 |
| 脚下（scene-slice） | `scene.path` 全路径字段；写作页切片条显示全路径；场景钉选择器含子地点（全路径 + 缩进「内部」样式） |

**尚未接（后续）**：scene-slice 在场列表的 `location_name` 全路径（展示层，低价值）；读者档（全图读者滤镜）对内部构造的处理。

---

## 5. 同构纪律

后端 `backend/services/world/location_tree.py` 与前端 `frontend/src/features/world/engine/locationTree.ts` 同构：`children_index/childrenIndex`、`collect_subtree_ids/collectSubtree`、`location_path/locationPath`、防环护栏。**改口径两侧同步 + 各配单测**（`test_location_tree.py` 15 项 / `__tests__/locationTree.test.ts` 6 项）。

相关既有事实：`WorldLocationRepository.update` 为「键存在即设」语义（coord/parent 显式 null 落库——清除坐标/脱离子树；路由层拦 name/kind 的显式 null）；DELETE 响应带 `ids`（删除的整棵子树）。

PUT 父闸（2026-09-01 审计补齐，与 create 同口径）：`update_location` 换 parent 时校验存在且同书、不得是自身、不得落在自己的子树里（防环）——对拍 `routes/test_location_parent_gate.py`。

---

## 6. 验证记录

### 2026-09-01 v1 施工
- 后端 pytest 全量 853 passed（含新增 `test_location_tree.py` 15 项：树收集 BFS 顺序/跨树不误收/环防护/全路径消歧/速记钉房间级/名单零变化契约）
- 前端 vitest 132 passed（含新增 `locationTree.test.ts` 6 项）；vue-tsc 0 error

### 2026-09-01 二期（消费侧接通）
- 后端 pytest 全量 862 passed（新增 9 项：`scene_scope_ids`/`ancestor_chain` 作用域与环防护 4 项 + `test_knowledge_plane.py::TestLocationInterior` 5 项——祖先在场/时态全路径/地点档案/无 intro 零变化/顶层裸名零变化）
- 前端 vitest 132 passed；vue-tsc 0 error
- 既有回归：`test_world_bridge_presence.py`（在场提权）/`test_scene_slice_source.py`（取源）零改动全绿——顶层钉与无钉书行为逐字节不变

> **归档说明（2026-09-19）**：日期型架构优化作业单（2026-09-11），所记施工全部入库；历史施工档案。

# 架构优化批 · 2026-09-11（普查 + 七项施工 + 路线图）

> 本文是本轮架构优化的唯一档案：全仓大文件/耦合普查结论、本批已施工的
> 重构（行为零变化，全量测试护航）、以及未施工项的优先级路线图。
> 施工均为**未提交工作区变更**，与 09-08→09-11 各批共享工作树。

## 〇、二轮追加（同日第二问「还有其他可优化的吗」施工）

1. **`routes/style.py`（1255 行）→ `routes/style/` 路由包**——六子模块
   （card / samples / fingerprint / feedback / cliches / events）+ `_deps`
   仓储依赖；沿 adaptive 拆包同款先例，函数体切片逐字节搬运。
   ⚠ 搬迁守卫：`adopted-ghosts` 端点的 `Path(__file__).parents[2]` 项目根
   锚定随文件加深一层改 `parents[3]`——**任何含 `__file__` 深度的搬移必查**。
2. **剥 HTML 双实现收敛**——`routes/style._plain_text` 与
   `rag/memory_indexing._html_to_plain` 逐字节同实现（仅差 null 守卫），
   收敛为 `services/utils/html_text.html_to_plain` 唯一权威；memory_indexing
   保留委托别名（既有 import 方零变化）；adaptive 心跳/完稿侧三处
   **路由→路由反向 import**（`from backend.routes.style import _plain_text`）
   一并解除。
3. **文风埋点双实现收敛**——`routes/style._append_style_event` 是
   `services/style/events.append_style_event` 的逐字副本（服务层注释明说
   「从 routes 抽出」但路由副本未删），现委托服务层。
4. **`useAdaptiveAssist.ts` stitch 四连抄去重（988→957 行）**——
   continue/burst/open/outline 四条链的 SSE 回调组各约 22 行逐字四抄
   （GHOST_DONE 新增字段要改四处，漏一处即接缝断裂——「前端 deai 未接线」
   类事故的温床），收敛 `_ghostStreamHandlers()` 工厂（差异三处参数化：
   beginGhost 入参 / 逃生舱 kind / 失败文案）+ `_fallbackFragment` /
   `_beginStitchSession` 两枚同构段助手。行为逐字节等价，vue-tsc 净 +
   293 测试绿。

二轮验证：后端全量 1264 绿 + `import main` 冒烟；前端 vue-tsc 净 + 293 绿。

## 一、首轮施工（全部完成并验证）

### ① `routes/chapter_generation/adaptive.py`（3105 行）→ `adaptive/` 路由包

沿包内既有「兄弟路由模块在 `__init__.py` 合并」先例，按端点族拆八子模块：

| 子模块 | 端点 | 行数 |
|---|---|---|
| `schemas.py` | 全部请求/响应模型 | 171 |
| `heartbeat.py` | heartbeat + 谋篇进度/文风漂移/收件箱积压/快照提取 | 527 |
| `settle_finish.py` | settle / finish / model / fix-sentence（完稿闭环同族，共享修复配额状态） | 318 |
| `stitch.py` | stitch-ghost（SSE 五模式） | 1080 |
| `preview.py` | context-preview | 90 |
| `spine.py` | spine GET/PATCH + spine-suggest | 219 |
| `world_read.py` | auto-read / read-entities | 168 |
| `events.py` | event / constraints/summary / events/summary（埋点文件坐标的家） | 243 |

要点：
- **函数体逐字节搬运**（脚本按行号切片，非转写）；包 `__init__` 只导出 `router`，
  端点路径与响应逐条不变。
- 顺带解除一处路由互 import 病灶：usage.py 的清空端点此前伸手进 adaptive 模块
  内部拿 `_collab_events_path`，现改指 `adaptive.events`（路径规则仍单一权威）。
- **消费者迁移**：usage.py + 10 个测试文件 import 改指正典模块；monkeypatch
  字符串目标必须跟随定义模块（桩打在 re-export 上无效——本批实测确认的坑）。

### ② 确定性闸门下沉 `services/adaptive/stitch_gates.py`（482 行）

字数硬闸常量（OUTLINE/STITCH_WC_*、MICRO_STITCH_TARGET_MAX、STITCH_MAX_TOKENS_FLOOR）、
截断（`_truncate_at_sentence`/`_truncate_keep_tail`）、接缝归一族（复读剥离/尾缀复读/
双开引号碰撞/桥接接缝/半角标点归一/桥接抢场/首句切分）、返修后处理（零 LLM 后处理/
句级切除三豁免/带稿改写 prompt）——路由层不该持有被 1057 行对拍单测锁定的纯逻辑。
对拍测试 `test_stitch_gates.py` / `test_beat_rush_gate.py` import 已改指本模块。

### ③ `backend/models.py`（1773 行）→ `backend/models/` 包（9 文件）

35 张表按领域拆：`_common`（工具/Enum/TIER）/`narrative`/`entities`/`memory`/
`generation`/`style`/`canon`/`world`；`__init__.py` 全量 re-export（68 个
`__all__` 名逐个核验可解析），`from backend.models import X` 消费面（约 97 文件）
零变化。跨模块 relationship 挂接收敛 `_links.py`（Book/Chapter↔GenerationTask）。

**施工中挖出并排掉的地雷（先于本批存在）**：SQLAlchemy 跨「无 relationship 的
FK 关联表」的同一 flush 插入序**本质非确定**（注册序=id 哈希序，原单文件的
Book-先-子表 只是堆布局运气；`world.py` WorldEventEdge 处早有同款注释先例）。
拆包改变堆布局后连爆 16 个测试，已按项目先例补 4 条显式 uow 依赖边修复：
`CanonNode.book` / `WorldEntity.book` / `WorldLocation.book` /
`Chapter.scene_location`（后者与列的 `ondelete=SET NULL` 语义一致）。
⚠ **新增表若与父表同 flush 新建，必须补 relationship 边**（AGENTS.md 已同步）。

### ④ 前端 WorldMap.vue 纯函数抽离（2754 → 2691 行）

- 新建 `features/world/engine/mapGeometry.ts`（132 行，零 Leaflet 依赖）：
  `pickScaleBarDays`（比例尺选档）/ `distToSeg`（橡皮擦命中）/ `resampleRing`
  （疆域 morph 弧长重采样）/ `arcControlPoint`（关系轻弧）/ `pickNearest`
  （⇧拖线命中）/ `countSyntheticTail`（双击合成顶点剥离）——
  消灭与 `engine/interpolate.ts` 同型的手搓弧长累计。
- `escapeHtml` 入 `shared/utils/htmlText.ts`（原组件内私藏的全仓唯一实现）。
- 对拍 `engine/__tests__/mapGeometry.test.ts` 21 项。

### 验证

后端 `pytest backend/ --ignore=backend/_deprecated` **1264 全绿**（= 09-11 基线）；
`import backend.main` 冒烟过（35 表全注册）；前端 `vue-tsc` 净 + `vitest run`
**293 全绿**（基线 272 + 新增 21）。

## 二、普查结论（未施工项路线图，按性价比排序）

普查口径：后端 py（排除 `_deprecated`）与前端 src（排除测试）行数 Top 榜 ×
未提交批占用状态。**当前 204 文件在未提交批**，大文件几乎全部被占用——
后续重构建议在批次提交后按下列顺序推进。

### P1（高价值，建议下一批）

1. ~~**`useAdaptiveAssist.ts` stitch 四连抄合并**~~ ✅ 二轮已施工（见 §〇.4）。
2. **`InspectorPanel.vue`（1650 行）review/debug 区组件化**——template 439 行 +
   style 728 行（占 44%）：完稿体检报告（647-750）/沉淀抽取/润色流程/读者反馈
   各自独立 section 组件，debug 区（228-333 逻辑 + 881-918 模板）整体搬走；
   `verdictLabel`/`relTimeOf`/`componentLabelOf` 标签表进 shared/utils。
   主文件可降至 700-900 行。
3. ~~**`routes/style.py`（1255 行）拆路由包**~~ ✅ 二轮已施工（见 §〇.1-3）。

### P2（中等价值）

4. **`stitch.py` 内部装配段抽离**（1080 行仍是单端点）——约束素材装配
   （canon label 映射/地点闭包/抢拍素材/信念泄漏短语，原 L1451-1601）可抽
   `services/validation/guard_materials.py`；需把闭包变量参数化，风险中等。
5. **`WorldMap.vue` 续拆**——模板 263 行 + 全局 style 623 行：右上工具条/
   底图编辑栏（97 行）/右键建实体表单可拆子组件；`buildLocPopupHtml` 参数化
   后入 engine。
6. **`WorldView.vue`（2516 行）/ `WorldTimeline.vue`（1770 行）**——世界页两大
   容器，先做 script 纯函数普查（本批未及），再考虑 section 组件化。
7. **`services/generation/character_extraction.py`（809）/ `publish_v2.py`（722）/
   `repositories/world_repository.py`（805）**——未占用文件，各自领域内聚性
   尚可，拆分收益需先确认内部耦合形态。

### P3（低优先/观察）

8. `services/prompts/adf_prompts.py`（1362，ADF 无 UI 入口）/ `workflows/adf/
   segment_writer.py`（1052）——引擎本体保留但前端已无入口，重构收益低。
9. `RichTextEditor.vue`（1409）刚经历编辑器优化批（09-10），建议沉淀一个
   版本再动。
10. `database.py`（1151）——MIGRATIONS 是 append-only 账本，体量增长是设计
    使然；如拆仅把 MIGRATIONS 数据外置 `migrations_list.py`。

### 横切观察

- **前端 components/ 不受分层约束**（AGENTS 既有声明）导致 InspectorPanel 等
  直连 services/api——属已接受的架构决策，重构时维持。
- **window CustomEvent 字符串总线**（`velluma:map-calibrate-*` 等）契约不可见，
  建议逐步收敛到 `shared/events.ts` 常量 + 类型化 emit。
- 后端 routes 层仍有少量业务逻辑内联（style.py 的 `_plain_text`、adaptive
  finish 的多段 try/except 编排）——方向是下沉 services，但「路由即编排薄层」
  在本项目是可接受基线。

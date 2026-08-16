<!-- From: D:\qoder\Velluma\AGENTS.md -->
# Velluma AI 小说写作助手 - Agent 开发指南

AI 驱动的长篇小说写作桌面应用（FastAPI + Vue3 + Electron）。许可证：AGPL-3.0。

> **引擎现状与迁移方向**：后端生成设施 —— **NLE-ADF 3.0 自适应流**（`/adaptive/*`，**前端默认且是未来唯一主线**）、**BS-ADF**（`/generate-bsadf` 步进模式，**⚠ 弃置中**：入口暂存但不再演进，其中验证过的思想与优势——DDE 岔路判断、章级规划层、字数硬闸门、残句门禁、双幻觉过滤、观测落库等——将**逐步迁移进 adaptive 流**后再整体归档；改造/新增一律面向 adaptive，勿往 bsadf 加功能）、**ADF**（V3.2，引擎本体保留但前端已无 UI 入口）、**Refinery**（V4.1，`/refinery/*`，独立精修）。V3.0 Detonation / V3.1 Unified / V4.0 DualTrack 已整体迁至 `backend/_deprecated/`，**不参与任何 import 链**。
>
> **NLE-ADF 3.0 自适应融合写作台**：作者主导写作 + AI 柔性共生。不预设拍、不跑整章管线；作者进章节打字 ≥4 字即激活辅助层（`composing` 态）。核心交互：心跳感知（挂件/走向卡/Canon 提示）、Space 续写幽灵草稿、Ctrl+Space 走向卡连写、**细纲胶囊**（作者亲笔速记 → 双端锚定扩写）、Ctrl+Enter 手动沉淀、完稿审计、**世界速记 Alt+N**（一句话入账）、**情境浮卡**（选中/点击提及三秒查底细）、**候选回流收件箱**（写完确认世界变化）。设定数据（章级绑定 + 书级 Canon + RAG 记忆）双向驱动：写作中感知 + 后台方向权重规划。

---

## 技术栈

**后端** (`backend/`)：FastAPI 0.109 · SQLAlchemy 2.0.25（异步）· PostgreSQL 14+pgvector · asyncpg 0.29 · OpenAI SDK 1.10 / DashScope 1.14（Embedding 仅 DashScope）· Uvicorn 0.27 · pydantic 2.5.3 / pydantic-settings 2.1.0 / tenacity 8.2.3。根目录 `requirements.txt` 与 `backend/requirements.txt` 内容一致（两份均可，均含 `jieba`/`python-multipart`；旧版根目录清单曾误列 `pywebview==4.4.1`，已随 pywebview 桌面入口删除）。

**前端** (`frontend/`)：Vue 3 ^3.4.15（Composition API）· TypeScript ^5.9.3 · Vite ^5.0.12 · Tailwind ^3.4.1 · TipTap ^2.24 · Electron ^28.3.3。

**环境要求**：Python 3.12+（`.python-version`）· Node 18+ · PostgreSQL 14+（pgvector 仅为**专业级向量记忆**所需；未配置 embedding 可不装）。

---

## 运行与构建

### 后端
```powershell
.venv\Scripts\activate
pip install -r requirements.txt
python backend/main.py          # 默认端口 8002，被占则扫描 8002~8100，写入 data/port.txt
```
端口可用 `VELLUMA_PORT` 指定跳过扫描。

### 前端
```bash
cd frontend
npm install
npm run dev          # 固定 5175（vite.config.js strictPort: true）
npm run typecheck    # 类型检查
npm run build        # 生产构建
```

### 桌面应用（推荐开发方式）
```powershell
.\scripts\start-dev.bat           # = 根目录 start.bat（-Mode dev，启动前后端+Electron）
.\scripts\start-prod.bat          # npm run build + Electron 载入 dist
.\scripts\start.ps1 -Mode dev -ElectronOnly    # 仅 Electron（前后端已在运行）
.\scripts\start.ps1 -Mode dev -SkipBackend     # 跳过后端
.\start.bat -Force                # 清理端口冲突后启动
```
`start.ps1` 为 Electron 设 `VELLUMA_BACKEND_PORT`/`VELLUMA_FRONTEND_PORT`/`VELLUMA_SERVICES_READY`（prod 另设 `NODE_ENV=production`）。Electron 独立命令（`frontend/` 下）：`npm run electron:dev`/`electron:preview`（均 `npm run build && electron .`，不启 Vite，需 5175 已有服务）/`electron:build`（打包）。

---

## 目录结构（仅关键标注）

```
backend/
├── main.py                 # 入口、路由注册、静态服务、CORS、asyncio 静默处理器
├── models.py               # ★ 22 个 ORM 模型（GenerationTask:740 / GenerationRun:829 均生效）
├── database.py             # 异步引擎 + 启动时自动迁移（MIGRATIONS 列表）+ 向量维度迁移
├── core/  (config 端口扫描 / model_config 读 model_config.json / dependencies / exceptions)
├── config/ (V4.0 配置推导层；PARAMETER_MAPPING.md 的 WorkflowPolicy 段含已废弃双轨参数，仅供历史参考)
├── routes/                 # API 路由（均在 main.py 注册）
│   └── chapter_generation/ # 包结构：__init__ 合并 adf/bsadf/refinery/adaptive router + extra_router
│       ├── adf.py          #   /generate-adf（前端已无 UI 入口）
│       ├── bsadf.py        #   /generate-bsadf 步进 + /advance-beat + /stepping-run/{id}/state + /rerender-beat + /cancel-run（/confirm-beats 历史兼容）
│       ├── adaptive.py     #   ★ NLE-ADF 3.0：/adaptive/heartbeat + /stitch-ghost + /settle + /finish + /model（作者主导写作，无预设拍）
│       └── refinery.py     #   /refinery/diagnose + /confirm
├── schemas/  repositories/
└── services/
    ├── llm/ (client.py REASONING_DISABLED / embedding.py 仅 DashScope / proxy / formatting)
    ├── observability/ (run_trace.py: logs/trace_*.jsonl / run_recorder.py: GenerationRun 落库)
    ├── nlg/ (去 AI 味洗涤 de_ai_washer.py)
    ├── prompts/            # Prompt 模板（改后即时生效，无需重建）。含 bsadf/adf/dde/nle/adaptive_prompts 等 + 测试
    ├── context/            # ★ settings_bundle.py（NLE-ADF 3.0 设定数据共享加载器：章级绑定+Canon+世界观）+ loader.py
    ├── rag/  (17+ 模块；scoring.py alpha/beta/gamma/lambda_decay 权重；enhanced/ 子包为评分增强层，在用)
    ├── validation/  (代码级 + LLM 级审计，服务 /chapters/{id}/quality-report 路由)
    ├── workflows/
    │   ├── adf/            # V3.2 ADF 引擎（自包含，前端无入口）：adf_workflow 主类 + 各 phase 模块 + 3 单测
    │   ├── bsadf/          # ⚠ 弃置中的步进引擎（自包含；思想迁移至 adaptive 后整体归档，勿新增功能）
    │   │   ├── bsadf_workflow.py   # BSAdfWorkflow 主类（execute_stepping/render_one/run_post_step_phases）
    │   │   ├── stepping_runtime.py # 步进运行时（SteppingRun 状态机 + stepping_loop + P3 回退快照栈）
    │   │   ├── slot_builder.py / slot_renderer.py / downgrade.py  # Phase 4a/4c/4d
    │   │   ├── outline_self_check.py / memory_ingestion.py        # Loop 1 / Loop 3
    │   │   ├── dde/        # 导演决策引擎（decision_card_generator / slot_mutator / test_decision_set）
    │   │   ├── types.py    # BeatSlotCard（13 字段）/ DegradedBeat
    │   │   └── test_*.py   # 8 单测
    │   ├── conftest.py     # ★ autouse fixture，防 asyncio 事件循环污染（见"测试"节，勿删）
    │   ├── sentence_integrity.py  # Phase 7.5 终稿残句门禁（BS-ADF 专用）+ test_sentence_integrity.py
    │   ├── refining.py     # ★ 共享（前端在用，非废弃），服务 chapter_optimization 路由
    │   └── planning/clarification_agent/snapshot_extractor/state_validator/context_blocks/...
    └── refinery/           # V4.1 独立精修（refinery/diagnostician/planner/surgeon/holistic_reader/polisher）

frontend/
└── src/
    ├── components/         # 通用组件（⚠ 不受分层约束，部分直接 import services）
    ├── extensions/         # TipTap 扩展
    ├── features/           # 分层架构：*/containers + */presentation
    │   ├── generation/     # useGenerationSession 步进会话 + Stepper/BeatSlotCardView/StoryboardPanel/BranchDecisionPanel + Refinery UI
    │   ├── workspace/ chapter-editor/ canon/ bible/ outline/ library/ insights/ novel-wizard/ app/ asset-panel/
    └── services/api/  domain/（业务 API，index.ts 聚合，含 bookApi/chapterApi/bsadfApi/refineryApi 等）/ stream/（SSE）/ transport/（HTTP）

backend/_deprecated/  # 废弃引擎归档（不参与 import 链，详见该目录 README）
data/ logs/ .venv/
```

---

## 核心架构要点

引擎各有独立工作流类与精修实现，**互不共享编排代码**（底层 LLM/观测/RAG 共用）。详细 Phase 序列与每阶段 LLM 调用数见各引擎模块顶部注释；此处仅列编辑时必须知道的事实。

### 引擎对照

| 引擎 | 端点 | 主类/模块 | 用途 |
|------|------|------|------|
| ★ **NLE-ADF 3.0** | `/adaptive/heartbeat`+`/stitch-ghost`+`/settle`+`/finish`+`/model` | `adaptive.py` + `settings_bundle.py` + `adaptive_prompts.py` | **前端默认**（作者主导写作+AI 柔性共生，无预设拍） |
| **BS-ADF** | `/generate-bsadf`（步进）+`/advance-beat`+`/stepping-run/{id}/state`+`/rerender-beat`+`/cancel-run` | `BSAdfWorkflow`（`workflows/bsadf/`） | **⚠ 弃置中**（legacy「规划本章」入口暂存；思想迁移至 adaptive 后归档） |
| ADF | `/generate-adf` | `ADFWorkflow`（`workflows/adf/`） | 引擎本体，前端已无 UI 入口 |
| Refinery | `/refinery/diagnose`+`/confirm` | `Refinery`（`services/refinery/`） | 独立精修（对任意草稿） |
| 章节优化 | `/optimize_chapter`+`/optimize_selection` | `refine_draft`（`workflows/refining.py`） | 章节重写/局部优化（前端在用） |

### NLE-ADF 3.0 自适应融合写作台（前端默认路径）

核心理念：**作者永远在写，AI 在画布上柔性共生**。与 BS-ADF 步进模式的根本区别——不预设拍划分、不跑整章管线前置；作者进章节打字即激活辅助层。

- **双轴状态机**（`useGenerationSession.ts`）：`authorLane`（idle→composing→ghostStitching→settling，前台主线）+ `aiLane`（dormant→perceiving/suggesting/assisting/digesting/analyzing，后台）。两轴并行不阻塞，与旧 `stage` 单轴（legacy step）共存。
- **激活**：作者进章节打字 ≥4 字 → `enterAdaptive(chapterId)` 置 `authorLane=composing`（不跑 startBeat 管线）。辅助层（`useAdaptiveAssist.ts`）据此挂载。
- **自适应辅助触发**（全部柔性可忽略。⚠ 端点以代码为准：**不存在** perceive/detect-branch/plan-suggest——感知与规划建议均由心跳响应携带）：
  - 心跳 → `/adaptive/heartbeat`（活跃防抖 3s / 停顿 4s+光标段尾，`useAdaptiveAssist.ts`）：后端 orchestrator 跑方向权重（纯算法 0 LLM）+ 组件（意图反推 0-1 LLM / 未来推测 / 挂件生发 / Canon 感知），响应带回 `dock_parts`（Spark Dock 零件）/`direction_cards`（走向卡）/`canon_hints`（左缘感知带）/意图信息
  - Space（有零件=缝合续写 / 无零件=顺句续写）→ `/adaptive/stitch-ghost`（SSE 打字机灌幽灵草稿，复用 `useGhostDraft`；mode 五档：stitch/continue/burst/open/**outline**）
  - **细纲胶囊**（Alt+O / 输入 `[[` / 选中文本转换，`extensions/OutlineNoteNode.ts` + `OutlineNoteChip.vue`）：作者亲笔剧情速记以胶囊嵌在正文任意位置 →「落笔扩写」走 stitch-ghost mode=outline（双端锚定：胶囊前 500 字 + 后 300 字；目标字数解析速记中「约N字」clamp 100-800 缺省 400；×1.6 压缩重试 + ×1.5 句界截断硬闸门）。扩写启动即塌缩为钉 ⚑ 可再扩写；**会话级，存盘剥除**（与幽灵同契约，`stripGhostDraftHtml` 一并剥 `[data-outline-note]`）；编排经 `velluma:outline-expand` 事件解耦（`useAdaptiveAssist.requestExpandOutline`）
  - **情境浮卡 + 世界速记（写作桥，见世界设定层）**：选中正文 1-12 字或点击 @/# 提及 → `GET /world/context-card` 浮情境卡（此刻状态/编年史/控制方，解析不到静默缺席）；Alt+N → `POST /world/parse-event` 一句话解析成事件草稿（只产草稿绝不落库，作者过目入账 + 6 秒撤销胶囊）
  - 沉淀 → `/adaptive/settle`（**纯手动** Ctrl+Enter，无自动字数门槛；抽涌现实体 + 可选落库，设定逆向生长；另触发 event_scout 抽候选事件进收件箱）
  - 完稿审计 → `/adaptive/finish`（残句/覆盖率/Canon 合规/整章审阅 + 记忆重索引 + 整章候选抽取）；`GET /adaptive/model` 世界模型快照（前端无调用方）
- **设定数据双向驱动**（`settings_bundle.py`）：章级绑定 + 书级 Canon（[public]/[private]）+ 世界观，一次加载供所有 adaptive 端点共用；**世界设定层优先**（见下节 world_bridge——世界页有实体时 bundle 的角色/资产/地点/关系切换为 world 数据 + 叙事时刻推演状态，无实体回退旧表）。写作中感知 + 后台方向权重规划两个层面同时利用。
- **画布即事实源**：adaptive 模式预览关闭（`generationPreviewHtml` 返回 null），作者写的即真实文档；沉淀只做后台消化（抽实体+可选落库），不产生第二份文本。落库由 `ChapterEditor` 的 `update-chapter` 机制实时覆盖。
- **Spark Dock 解耦**：gate 从 stage 解绑，`authorLane=composing` 即激活（零件源从拍卡改为心跳供给 + 章级兜底）。

### 世界设定层（World，★ 静态设定的唯一编辑源与生成数据源）

事件溯源式世界建模器：`world_events`（append-only 事实源，11 种事件类型）+ `world_entities`（人物/势力/资产固有属性，档案在 `props` JSONB 表驱动）+ `world_locations` + `world_relations`（static 或事件锚定的时变关系）+ 地图底图表 + 候选事件池 `world_event_candidates`。任意时刻的世界状态（谁在哪/生死/疆域/关系）由 `compute_world_state_from_events` 纯函数折叠推演（前后端同构，前端 `features/world/engine/`）。UI 单一画布（M6「活舆图」）：地图（Leaflet）承载全部实体/关系/事件（脑图透镜已退役，⇧拖建关系等手势平移至地图），**悬浮胶囊工具条**（记一笔历史/地点/实体/世界观/⋯）取代顶栏，**右缘 46px 图标栏 + 浮出抽屉**（待确认/伏笔/期待/地点/事件/角色/势力/资产）取代右侧栏；书名水印题字；**空白舆图**（无底图时铺手绘风地球世界平面——`BLANK_ATLAS_INNER` 81 路径 SVG，svgOverlay 随图缩放，国界点状虚线/山河/经纬网，提示收进浮动卡，首个实体落地即退场；空白态初始视野框住世界平面，用户拖/缩后不再插手）+ **罗盘**（实功能：点击「回到全图」视野收拢到内容包围盒；针平时轻摆、点击大摆归北）；底部时间轴为编年史带（含章节叙事锚 `chapters.narrative_time` + 伏笔弧线带）。表单体验：textarea 统一走共享指令 `v-autogrow`（`presentation/autogrow.ts`，随内容长高、max-height 封顶）。

- **生成桥接（world_bridge，已接通）**：`services/context/world_bridge.py`——世界页有实体时 settings_bundle 走 **world 优先**：实体/关系经鸭子类型适配器包装成旧 Character/Asset 形状（下游 hard/soft/nutrients 零改动），`dynamic_state` 自动携带叙事时刻推演状态（「位于北岸要塞」「在途（进度 40%）」「已死亡」）；叙事时间四级降级（本章锚→前序最近锚→事件最大时刻→0）。`bundle.world_state/world_time/world_sourced` 携带切片快照。桥接失败/世界为空 → 旧表兜底（未迁移书行为不变）。
- **编辑入口收敛（M4/M5）**：设定页角色/资产/地图（M4）+ 伏笔账本/期待账本/世界观（M5）分区已退役为跳转卡（`WorldRedirectCard`，带 `?entity=`/`?panel=` 深链）；保留分区：文风/笔记/设置。旧面板 CharacterPanel/MapSettings/asset-panel/ForeshadowingPanel/ReaderMirrorPanel/WorldviewSettings 已删除。M5 世界页新增承载（M6 起位于图标栏抽屉/胶囊条）：「伏笔」抽屉（`ForeshadowSection` 全量账本+状态筛选，未锚定伏笔的唯一可见处）+ `ForeshadowDetailDrawer`（就地编辑/未锚定一键锚游标/回收/废弃/删除 undo）、「期待」摘要 + `ReaderMirrorModal`（火候看板/张力曲线整面板迁入）、胶囊条「世界观」+ `WorldviewModal`（2s 防抖自动保存/导入导出）；伏笔/期待/世界观编辑后统一广播 `velluma:world-refresh` 刷新写作页切片。
- **章级在场改推演**：原角色/资产/地点勾选绑定（chapter_entities 等）退役——「本章在场」由事件按叙事时刻推演（`GET /world/state-for-chapter/{chapter_id}`，SceneSettingsPanel 只读展示）。entity-mention（@/#）建议与创建均走 world（无世界数据回退旧表），不再写章级绑定。
- **AI 写路径（M4）**：`content_extractor.commit_extraction` 与 adaptive 沉淀落库改写 world_*（角色档案全文进 `props.background`——**迁移而非兼容**：启动数据迁移已把历史 `props.legacy_profile` 并入 background 并摘键，读写两侧均无 legacy 回退）；**未迁移书首次 AI 落库前自动执行幂等迁移**（防 world 优先切换后旧角色从生成上下文失踪）。伏笔（PlotLedger 共享表）与向量记忆不变。
- **写作桥（world-writing-bridge，W1-W5lite 已上线，`docs/world-writing-bridge.md`）**：沙盘价值送货到写作现场——①`GET /world/scene-slice`「此刻此地」切片条（Inspector 设定 tab，替换旧 SceneSettingsPanel；在场/脚下含疆域控制方/相遇/头顶的线，与生成上下文同源）；②`GET /world/context-card` 情境浮卡（选中文本/点击提及）；③`POST /world/parse-event` Alt+N 世界速记（解析/落库分离红线）；④候选回流：`event_scout` 独立组件（orchestrator 注册，settle 带段/finish 带整章各触发一次）→ `world_event_candidates` 待确认池（与事件账本物理隔离）→ 切片条收件箱 + 世界页「待确认」分区 ✓/✗/撤销；⑤保鲜三时机（章节切换/心跳 `world_version`/窗口聚焦，`useWorldSlice` 单例）；⑥深链往返 `?entity|loc|fs=&time=&from=chapter&chapter=`（世界页「返回本章」；`?fs=` 开伏笔详情抽屉，`?panel=expectations|worldview` 开对应账本模态，写作页「头顶的线」伏笔/期待行可点击）；⑦本章场景钉 `chapters.scene_location_id`。事件解耦：`velluma:world-version` / `velluma:world-refresh` / `velluma:quick-note`。
- **待办**：旧表彻底冻结（audit/publish/inspiration/chapter_optimization 仍读旧表）、Canon 与世界页的归属关系（脑图页铁律设定是否并入）、`docs/world-unified-settings.md` §5 的时间线事件→走向卡规划桥、写作桥 W5 缓行件（比例尺距离层/spatial_brief、相遇→走向卡桥、世界页全图读者滤镜——见桥接文档分期表）。

### BS-ADF 步进模式（⚠ 弃置中——迁移源，勿新增功能）

> **弃置策略**：前端入口（InspectorPanel「规划」tab「生成本章」）暂存但不再演进；验证过的思想按需迁移进 adaptive 流后，引擎整体归档至 `backend/_deprecated/`。**迁移候选**：DDE 真岔路判断（adaptive 现为柔性走向卡）、章级规划层（脉络轨/锚点/定档/槽位卡，adaptive 无对应物）、残句门禁与一致性手术等修复型护栏（adaptive finish 只审计不修复）、RAG 检索管线与观测落库（trace/RunRecorder——adaptive 端点现无成本核算）。**已知待补的洞**：Refinery 润色入口要求 `stage==='done'`（`InspectorPanel.vue`），adaptive 模式 stage 恒 idle，章节永远进不了润色/读者反馈。

链路：`generate-bsadf` 跑到 Phase 4b 暂停 → 常驻 `stepping_loop`（`stepping_runtime.py`）→ `STEPPING_INITIALIZED`（run_id + 全量槽位卡）→ **逐段**「渲染 → `BEAT_RENDER_READY` 挂起等裁决 → `/advance-beat` → 下一段」→ 末段锁死 → Phase 4.5-7.5 后处理 → `COMPLETE`（全量收尾字段）。

- **裁决动作**（`AdvanceBeatRequest.action`）：`pass`/`edit`/`branch`/`skip`/`lock_with_text`/`back`，带 `beat_id` 校验（陈旧动作丢弃）。前端「接受」dirty 时自动改走 `lock_with_text`，删空文本路由 `skip`。
- **岔路门**：渲染前卡挂 DDE 岔路且未选走向 → `BEAT_BRANCH_CHOICE` 暂停（`BranchDecisionPanel`），取代 Track A 静默/Track B 弹窗。Track A/B 现为休眠兼容路径（`enable_stepping=false` 才进入）。
- **请求开关**（`schemas/bsadf.py`）：前端固定开 `enable_stepping`+`enable_outline_self_check`+`enable_memory_ingestion`（`useGenerationSession.ts:1193-1207`）；`track` 步进模式忽略，前端已不传。
- **BeatSlotCard 硬契约**（`workflows/bsadf/types.py`，13 字段）：`core_plot_event`/`key_anchors`/`text_carrier` + `outline_beat` + `branch_directive` + 内部字段。禁词/心理/感官限制已下沉为渲染器静态 system prompt（`bsadf_prompts.py` `_SLOT_RENDER_SYSTEM`），不再逐卡携带。
- **DDE**（`workflows/bsadf/dde/`，全章 1×creative）：判断本章是否有剧情走向级真实岔路；无则放行。`slot_mutator` 写走向入 `branch_directive`，**绝不碰**硬契约字段。

### ⚠ 后端运行/落库边界（编辑前必读）

1. **步进运行纯内存**：`_STEPPING_RUNS`（TTL 12h）。uvicorn `--reload` 重启（任何 backend 文件保存）即丢全部 run → `advance-beat`/`state` 返回 404 RUN_NOT_FOUND，前端按「会话失效，重试=从头重生成」处理。SSE 断连不影响后台执行；`GET /stepping-run/{id}/state` 2s 轮询兜底。
2. **每条 `/advance-beat` = 一条新 SSE 流**：15s 空闲发 HEARTBEAT 保活（无 120s 硬超时），消费到终态事件优雅结束。advance 入口守卫：run 非 stepping→409，`edit` 无 edited_slot→422。
3. **步进模式后端不自动写库**：`_run_generate` 步进分支提前返回。终稿由前端 COMPLETE 后 `PUT /api/chapters/{id}` 落库（`WorkspaceView.vue` watch stage→done）。槽位卡 `bsadf_beat_slots` 步进模式不落库；run 结束时 `_store_pending_beats` 暂存 rerender 上下文（done 后「重写本段」走 `/rerender-beat`）。
4. **Refinery 与 ADF 内置的 REFINE 是完全不同代码**（同名不同实）；`services/refinery/__init__.py`「ADF Phase 4.5 触发」注释过时，代码无此集成。

### ⚠ thinking 关闭的正确姿势（`services/llm/client.py`）

要关 thinking 必须传 `reasoning_config=REASONING_DISABLED`（`{"reasoning":{"enabled":False}}`）。**传空 dict `{}` 无效**——`call_llm_with_usage` 里 `if reasoning_config:` 对 `{}` 为 falsy，推理模型回落服务端默认 thinking 开启，小预算调用（状态卡/残句修复）必被吃光预算空输出。已接 REASONING_DISABLED：render/enrich/state_tracker/beat_patch/refine/wash/sentence_fix/parse_event/event_scout。**中间表示经 `reasoning_adapter.py` 按域名转厂商原生参数**（DeepSeek/OpenAI/OpenRouter/Qwen/豆包/MiMo/本地）；MiMo 实测只认 `thinking.type`，静默忽略 OpenRouter 的 `reasoning.enabled`（隐藏思考烧光预算，勿删该分支）。

### 关键质量护栏（事故根因，勿回退）

> ⚠ 以下闸门多数位于 **bsadf**（弃置中）与共享模块；adaptive 流目前只继承了**字数硬闸门**（stitch-ghost mode=outline 的 ×1.6/×1.5 双层闸）与 enrich 双幻觉过滤的思想（adaptive 走「作者裁决即闸门」路线，无渲染期拦截）。迁移改造时从这里取材，勿凭空重写。

- **字数硬闸门**：超 target×1.6 带压缩反馈重试，末次仍超句界截断到 target×1.5（截断上限必须 ≤1.6）；末段（结局段）豁免截断。
- **REFINE 完整性闸门**：补埋输出采纳前强制句末完整性校验，回退后丢失过半则整段放弃（宁缺勿残）。
- **enrich 幻觉闸门**：空种子禁自由扩写（防凭空产出）；剧情关键词/零接地双向过滤。
- **POV 名闸门**：状态卡已知 POV 角色时正文必须出现其名至少一次。
- **Phase 7.5 残句门禁**（`sentence_integrity.py`，BS-ADF）：高精确度正则扫残句（宁漏勿误），命中定点修复（1×creative + REASONING_DISABLED + max_tokens=1600，上限 5）。
- **状态卡抽取失败**：沿用旧卡显式记 `result.degraded`（不静默）；max_tokens=1600 兜底。

### RAG / 记忆流（`recall_memories`：默认流始终打底 + 向量流增强叠加）

唯一检索入口 `services/rag/recall.py` 的 `recall_memories`（消费方：stitch-ghost 五模式 k=3、dock_generator k=2，签名稳定），三层按质量序 `merge_echoes` 保序去重截 k：

- **A 结构化前情（始终）**：查询中出现的世界实体（名/别名匹配，≤4 个）× 叙事时刻之前（`resolve_narrative_time`）的 world_events，倒序取 3 条格式化为【前情事件·类型】（世界页无数据自动跳过）。
- **V 向量增强（专业级，embedding 已配置时叠加——不替换默认流，A/B 恒在）**：DashScope（默认 `text-embedding-v2`，1536 维可在 `model_config.json` 的 `embedding.dimensions` 配置，Key 来自 model_config 不读环境变量）；`search_similar` 权重（`rag/scoring.py`）：alpha 0.6（语义）/ beta 0.2（时间衰减）/ gamma 0.2（伏笔）/ lambda_decay 0.1。
- **B 词法检索（始终补足）**：`jieba.analyse` 抽关键词（top 8）→ `MemoryRepository.search_lexical`（SQL ILIKE 预筛 ≤60 候选 + Python 重排：`lexical.keyword_coverage` 命中计分单关键词封顶 3 次 + 开放伏笔章 +1 + 新近 tiebreak）。
- **写路径**：完稿重索引（`memory_indexing`）/提取确认/发布摘要块——**块文本一律落库**，embedding 仅在已配置时生成（`is_embedding_configured()` 门控），未配置不再整块跳过（摘要块是词法检索最佳素材）。检索限当前章之前（防未来信息泄露），三层同规则。

---

## 数据库与迁移

**启动时自动迁移**（非 Alembic）：`backend/database.py` 的 `MIGRATIONS` 列表（约 50 条）定义增量列变更，`init_db()` 启动时自动补齐。改 ORM 后须同步加 MIGRATIONS 条目，重启即应用。

⚠ **向量维度迁移破坏性**：启动时 `migrate_vector_dimension` 若 embedding 维度与库列不匹配会**删列重建**（清空全部向量数据）。切维度前注意。

连接池：`pool_size=10`/`max_overflow=20`；`DB_POOL_PRE_PING` Windows 默认关（asyncpg+greenlet），其他平台默认开。手动建表前需 `CREATE EXTENSION IF NOT EXISTS vector;`。

---

## 配置

### model_config.json（主要配置入口，已 gitignore）

LLM/Embedding/代理实际配置来源（schema 见 `backend/core/model_config.py`）：`llm.reasoning`/`llm.creative`/可选 `llm.wash`/`embedding`/`proxy`。除手动编辑外可通过前端设置面板（`SettingsPanel.vue`）经 `GET/PUT /api/system/model-config` 读写（GET 只回掩码，PUT 留空 api_key 表保持）。LLM/代理保存即时生效，embedding 维度变更需重启。**embedding 已降级为专业级**：设置面板默认折叠；未配置时记忆流走结构化+词法默认路径（见 RAG 节）。⚠ **当前工作区副本含真实 API Key，勿提交或外发**。

### 环境变量（.env 可选，仅以下几个实际生效）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DATABASE_URL` | PG 连接串 | `postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver` |
| `DB_POOL_PRE_PING` | 连接池预检 | Win=false / 其他=true |
| `VELLUMA_PORT` | 固定后端端口 | 无（默认 8002 起扫描） |

⚠ 实际代理配置由 `model_config.json` 的 `proxy` 节决定（`get_active_proxy()`），不读环境变量。代码中**不存在**以下环境变量：`PROXY_URL`/`DISABLE_PROXY`（已删除的死变量）、`AGENTIC_BEAT_CONCURRENCY`/`AGENTIC_FORCE_FAST_MODE`（历史误标，从未存在）、`DASHSCOPE_API_KEY`/`OPENAI_API_KEY`（Key 全来自 model_config.json）。注意区分：`AGENTIC_DEFAULT_*`（如 `AGENTIC_DEFAULT_WORD_COUNT`）是 `schemas/generation.py` 内**实际存在**的 Python 常量（非环境变量），供已废弃的 `orchestration/agentic.py` 引用。

---

## 代码规范

**Python**：新 `.py` 必须加 AGPL-3.0 许可证头（⚠ `workflows/adf/`/`refinery/`/`routes/chapter_generation/` 等较新模块现状缺失）。LLM 调用用 tenacity 指数退避重试；流式错误发 error 帧+done 帧；Windows asyncio 无害连接错误已在 `main.py` 注册静默处理器。注释风格：模块顶用 `====`/`----` 分段，关键逻辑前标设计意图，副作用标 `副作用：`/`警示：`。

**TypeScript 前端分层**（依赖方向）：
```
features/*/presentation → 容器 props/emits（渲染、抛交互事件）
features/*/containers   → services/api/domain（状态整合、事件编排）
services/api/domain     ← 业务 API
services/api/stream     ← SSE
services/api/transport  ← 底层 HTTP
```
❌ `presentation → transport/stream` 禁止（见 `features/README.md`）。该约束 features/ 内执行良好；⚠ 通用组件层 `components/` 不受约束。命名：Feature 目录 kebab-case，容器 `*Container.vue`，展示 `*View.vue`/`*Panel.vue`（弹窗多用 `*Modal.vue`）。

---

## 测试

项目快速迭代期，测试有限，主要靠手动验证。后端工作流测试均为纯算法/LLM-mock 单测（不连真实 LLM/DB）：`python -m pytest <文件>`。

- BS-ADF：`workflows/bsadf/` 下 8 单测 + `dde/test_decision_set.py`
- ADF：`workflows/adf/` 下 `test_consistency_guard`/`test_beat_patcher`/`test_state_tracker`
- `workflows/sentence_integrity.py` + `test_sentence_integrity.py`；`prompts/test_boundary_pacing_prompts.py`

⚠ **`workflows/conftest.py`（autouse）勿删**：每个测试结束重置全新 current event loop。存在原因——`IsolatedAsyncioTestCase`（adf 测试）与 `asyncio.run` 收尾会把事件循环策略 `_set_called` 置位且 current loop 置空，污染同进程后续 `asyncio.get_event_loop()`（受害者：bsadf/test_downgrade.py、test_slot_builder.py 抛 RuntimeError）。跨多文件跑 pytest 时删除会随机失败。

**开发验证**：后端 `/api/health`；前端浏览器 DevTools + Vue DevTools；Prompt 日志 `logs/prompt_log_*.json`；生成全流程 trace `logs/trace_{run_id}.jsonl`（JSONL 实时追加，含 run_start/阶段事件/slots_built 快照/每次 llm_call 的 system+user+响应+usage+延迟/final_text/run_complete；质量 debug 先按 run_id 定位文件再逐事件排查；单章数百 KB 属预期）。

---

## 部署

`electron-builder` 配置在 `frontend/package.json`（appId `com.velluma.app`，win=nsis/mac=dmg/linux=AppImage，`extraResources` 打包 `../backend`）。`cd frontend && npm run build && npm run electron:build`。FastAPI 已配 SPA fallback（`/`→`dist/index.html`，`/api/*`→404，其他→静态文件或 fallback）。**无 Docker**；CI 为 GitHub Actions（`.github/workflows/ci.yml`：后端 `py_compile` 全量编译检查 + 前端 `vue-tsc` 类型检查非阻断）。端口协商（`data/port.txt`）仅本地开发用，生产用 `VELLUMA_PORT` 固定。

---

## 安全

- **API Key 全部来自 `model_config.json`**（gitignore），不读环境变量、不入库。日志不打印完整 Key。⚠ 当前工作区副本含真实可用 Key，勿提交/外发。
- **CORS ⚠ 无条件** `allow_origins=["*"]` + `allow_credentials=True`（代码无环境区分），生产必须收紧为具体域名。

---

## Agent 速查

- **加 API 端点**：`schemas/` 定义 → `routes/` 加模块（`chapter_generation` 是包，在包内加并在 `__init__.py` 合并）→ `main.py` 注册（如未注册）→ 前端 `services/api/domain/` 加调用。⚠ NLE-ADF 3.0 的 adaptive 端点无需 schema 文件（Pydantic BaseModel 直接定义在 `routes/chapter_generation/adaptive.py` 内）。
- **改数据库模型**：`models.py` 改 ORM → `database.py` 的 `MIGRATIONS` 加列迁移 → 重启自动应用。
- **改 Prompt**：定位 `services/prompts/` 下文件，改后即时生效（无需重建），建议查 `logs/prompt_log_*.json` 验证。
- **前端加 Feature**：`features/` 建目录，按 `containers/`+`presentation/` 分层，经 `services/api/domain` 通信。

> 废弃/归档清单：`backend/_deprecated/`（V3.0 Detonation / V3.1 Unified / V4.0 DualTrack 整引擎归档，不参与 import 链，详见该目录 README）；`backend/_deprecated/docs/`（对应废弃引擎的设计文档归档）。其余历史误标（`models_generation_task.py`、`services/` 空壳目录、`rag/tests/`、`state_machine/`、`PROXY_URL`/`DISABLE_PROXY`、pywebview/`app.py` 等）均已随代码清理删除，不再存在。

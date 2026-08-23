<!-- From: D:\qoder\Velluma\AGENTS.md -->
# Velluma AI 小说写作助手 - Agent 开发指南

AI 驱动的长篇小说写作桌面应用（FastAPI + Vue3 + Electron）。许可证：AGPL-3.0。

> **引擎现状与迁移方向**：后端生成设施 —— **NLE-ADF 3.0 自适应流**（`/adaptive/*`，**前端默认且是未来唯一主线**）、**BS-ADF**（**已于 2026-08-19 整体归档** `backend/_deprecated/`：涌现抽取迁出为 `services/adaptive/emergent_facts.py`，思想去向——DDE→谋篇声明岔路/章级规划→软脉络/字数闸→outline 双层闸/残句→repair_single_defect，详见 _deprecated/README.md）、**ADF**（V3.2，引擎本体保留但前端已无 UI 入口）、**Refinery**（V4.1，`/refinery/*`，独立精修）。V3.0 Detonation / V3.1 Unified / V4.0 DualTrack 已整体迁至 `backend/_deprecated/`，**不参与任何 import 链**。
>
> **后续迭代路线图**：`docs/iteration-roadmap.md`（演进唯一权威载体）——**P0-P3 全部完成（2026-08-19）**：P0 观测打底+协作埋点；P1 协作深化（残句修复护栏 `POST /adaptive/fix-sentence`、insights「协作」面板、**章级谋篇软脉络** `chapters.spine` M1-M3——docs/chapter-planning-spine.md，谋篇卡/锚点/进度判定/作者声明岔路，M4 DDE 自动岔路数据门不启动）；P2 世界页完善（C2 信息面挂接 canon_nodes.ref_type/ref_id + `/world/migrate-canon` + EntityDetailDrawer「读者认知」分区；C3 激活——连锁分析/查片段/提取候选入待确认池/时间轴揭示朱点；W5 相遇→走向卡桥 from_encounter；**D4 比例尺** books.map_scale + spatial.py 换算 + 切片距离行 + spatial_brief 进四模式 prompt——docs/map-scale-spatial.md）；P3 **SQLite 默认**（不设 DATABASE_URL → data/velluma.db；BS-ADF 整体归档 _deprecated + 前端 -1168 行）。P4 缓行件维持数据门控待真实使用验证。**P5 地基加固期 ✅ 施工完成（2026-08-21，`docs/foundation-hardening.md`）**：私有语义统一/在场提权/叙事时间来源可见/回流闭环/AI 所见预览/用量可见/上下文预算器（`services/context/budget.py`）/ghost_guard 上屏前快检/样本场景匹配/分模式注入；B4 真流式条件排期，A3b 调参与效果实测待真实写作回收。
>
> **NLE-ADF 3.0 自适应融合写作台**：作者主导写作 + AI 柔性共生。不预设拍、不跑整章管线；作者进章节打字 ≥4 字即激活辅助层（`composing` 态）。核心交互：心跳感知（挂件/走向卡/Canon 提示）、Space 续写幽灵草稿、Ctrl+Space 走向卡连写、**细纲胶囊**（作者亲笔速记 → 双端锚定扩写）、Ctrl+Enter 手动沉淀、完稿审计、**世界速记 Alt+N**（一句话入账）、**情境浮卡**（选中/点击提及三秒查底细）、**候选回流收件箱**（写完确认世界变化）。设定数据（章级绑定 + 书级 Canon + RAG 记忆）双向驱动：写作中感知 + 后台方向权重规划。

---

## 技术栈

**后端** (`backend/`)：FastAPI 0.109 · SQLAlchemy 2.0.25（异步）· **SQLite（aiosqlite，默认——不设 DATABASE_URL 即 `data/velluma.db`，零外部依赖）**或 PostgreSQL 14+pgvector（显式设 DATABASE_URL 的专业级路径）· asyncpg 0.29（PG 路径）· OpenAI SDK 1.10（LLM 与 Embedding 同走 OpenAI 兼容协议）· Uvicorn 0.27 · pydantic 2.5.3 / pydantic-settings 2.1.0 / tenacity 8.2.3。根目录 `requirements.txt` 与 `backend/requirements.txt` 内容一致（两份均可，均含 `jieba`/`python-multipart`；旧版根目录清单曾误列 `pywebview==4.4.1`，已随 pywebview 桌面入口删除）。

**前端** (`frontend/`)：Vue 3 ^3.4.15（Composition API）· TypeScript ^5.9.3 · Vite ^5.0.12 · Tailwind ^3.4.1 · TipTap ^2.24 · Electron ^28.3.3。

**环境要求**：Python 3.12+（`.python-version`）· Node 18+。数据库默认 SQLite **零外部依赖**（`data/velluma.db`）；PostgreSQL 14+ 仅在显式设置 `DATABASE_URL` 走 PG 路径时需要（pgvector 为该路径的专业级向量记忆）。

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

启动脚本收敛于 `scripts/`，按平台分目录，每平台 dev/debug/prod 三模式（根目录 start.bat 已移除）：

```powershell
# Windows
.\scripts\windows\start-dev.bat    # 开发模式（启动前后端+Electron，自动开 DevTools）
.\scripts\windows\start-debug.bat  # 调试模式（后端 uvicorn --reload 热重载）
.\scripts\windows\start-prod.bat   # npm run build + Electron 载入 dist
.\scripts\windows\start.ps1 -Mode dev -ElectronOnly   # 仅 Electron（前后端已在运行）
.\scripts\windows\start.ps1 -Mode dev -SkipBackend    # 跳过后端
.\scripts\windows\start-dev.bat -Force                # 清理端口冲突后启动
```

```bash
# macOS / Linux（bash，编排逻辑与 start.ps1 对称）
./scripts/macos/start-dev.sh       # 开发模式
./scripts/macos/start-debug.sh     # 调试模式（后端热重载）
./scripts/macos/start-prod.sh      # 生产体验
./scripts/macos/start.sh dev --dry-run               # 仅打印将执行的命令
```

编排核心（`windows/start.ps1` / `macos/start.sh`）为 Electron 设 `VELLUMA_BACKEND_PORT`/`VELLUMA_FRONTEND_PORT`/`VELLUMA_SERVICES_READY`（prod 另设 `NODE_ENV=production`），端口协商写 `data/port.txt`+`data/frontend_port.txt` 两平台同契约。Electron 独立命令（`frontend/` 下）：`npm run electron:dev`/`electron:preview`（均 `npm run build && electron .`，不启 Vite，需 5175 已有服务）/`electron:build`（打包）。

---

## 目录结构（仅关键标注）

```
backend/
├── main.py                 # 入口、路由注册、静态服务、CORS、asyncio 静默处理器
├── models.py               # ★ 31 个 ORM 模型（GenerationTask:788 / GenerationRun:877 均生效）
├── database.py             # 异步引擎 + 启动时自动迁移（MIGRATIONS 列表）+ 向量维度迁移
├── core/  (config 端口扫描 / model_config 读 model_config.json / dependencies / exceptions)
├── config/ (V4.0 配置推导层；PARAMETER_MAPPING.md 的 WorkflowPolicy 段含已废弃双轨参数，仅供历史参考)
├── routes/                 # API 路由（均在 main.py 注册）
│   └── chapter_generation/ # 包结构：__init__ 合并 adf/refinery/adaptive router + extra_router
│       ├── adaptive.py     #   ★ NLE-ADF 3.0（前端默认）：/adaptive/heartbeat + /stitch-ghost + /settle + /finish + /fix-sentence + /spine（GET/PATCH）+ /spine-suggest + /model + /context-preview（P5 AI 所见预览）+ /event（+/events/summary）；usage.py 同包：/adaptive/usage 章/书两级聚合
│       ├── adf.py          #   /generate-adf（引擎本体保留，前端已无 UI 入口）
│       └── refinery.py     #   /refinery/diagnose + /confirm
├── schemas/  repositories/
└── services/
    ├── llm/ (client.py REASONING_DISABLED / embedding.py OpenAI 兼容向量 / proxy / formatting)
    ├── observability/ (run_trace.py: logs/trace_*.jsonl / run_recorder.py: GenerationRun 落库)
    ├── nlg/ (去 AI 味洗涤 de_ai_washer.py)
    ├── prompts/            # Prompt 模板（改后即时生效，无需重建）。含 bsadf/adf/dde/nle/adaptive_prompts 等 + 测试
    ├── context/            # ★ settings_bundle.py（NLE-ADF 3.0 设定数据共享加载器：章级绑定+Canon+世界观）+ loader.py
    ├── rag/  (17+ 模块；scoring.py alpha/beta/gamma/lambda_decay 权重；enhanced/ 子包为评分增强层，在用)
    ├── style/  (★ 文风体系：extractor.py 样本提炼 / cliche_provider / fingerprint.py 句长/字数/CV/对话统计规范实现（审计侧共用同一把尺子，对拍单测勿删）/ retrieval.py 作者样本检索（向量优先+新近兜底，stitch-ghost/ADF/refinery few-shot 共用）)
    ├── validation/  (代码级 + LLM 级审计，服务 /chapters/{id}/quality-report 路由；统计原语 import 自 services/style/fingerprint.py)
    ├── workflows/
    │   ├── adf/            # V3.2 ADF 引擎（自包含，前端无入口）：adf_workflow 主类 + 各 phase 模块 + 3 单测
    │   ├── conftest.py     # ★ autouse fixture，防 asyncio 事件循环污染（见"测试"节，勿删）
    │   ├── sentence_integrity.py  # 残句门禁 + repair_single_defect 单条修复（服务 /adaptive/fix-sentence）+ test_sentence_integrity.py
    │   ├── refining.py     # ★ 共享（前端在用，非废弃），服务 chapter_optimization 路由
    │   └── planning/clarification_agent/snapshot_extractor/state_validator/context_blocks/...
    └── refinery/           # V4.1 独立精修（refinery/diagnostician/planner/surgeon/holistic_reader/polisher）

frontend/
└── src/
    ├── components/         # 通用组件（⚠ 不受分层约束，部分直接 import services）
    ├── extensions/         # TipTap 扩展
    ├── features/           # 分层架构：*/containers + */presentation
    │   ├── generation/     # useGenerationSession 会话状态机 + useAdaptiveAssist 辅助层 + SparkDock/BeatCardDock/IgnitionCard/Refinery UI（BS-ADF 步进面板已删除）
    │   ├── workspace/ chapter-editor/ bible/ outline/ library/ insights/ novel-wizard/ app/ extraction/ import-markdown/
    │   ├── world/         # ★ 活舆图（世界+伏笔/期待/世界观+真相层 Canon）；canon feature 已随 C1 融合删除（CanonView/CanonGraph/NodeEditModal/EdgeEditModal + useCanon 迁 world/composables）
    │   ├── style/         # ★ 文风页 S1（样本库+笔迹指纹+负面清单+章对账；StyleCardManager 已删除拆解迁入；docs/style-module-redesign.md）
    └── services/api/  domain/（业务 API：index.ts 聚合 bookApi/chapterApi/refineryApi + adaptive/world/canon/asset 等 *.api.ts）/ stream/（SSE）/ transport/（HTTP）

backend/_deprecated/  # 废弃引擎归档（V3.0/V3.1/V4.0 + BS-ADF 2026-08-19 整体迁入，含其路由与 schema；不参与 import 链，详见该目录 README）
data/ logs/ .venv/
```

---

## 核心架构要点

引擎各有独立工作流类与精修实现，**互不共享编排代码**（底层 LLM/观测/RAG 共用）。详细 Phase 序列与每阶段 LLM 调用数见各引擎模块顶部注释；此处仅列编辑时必须知道的事实。

### 引擎对照

| 引擎 | 端点 | 主类/模块 | 用途 |
|------|------|------|------|
| ★ **NLE-ADF 3.0** | `/adaptive/heartbeat`+`/stitch-ghost`+`/settle`+`/finish`+`/fix-sentence`+`/spine`（GET/PATCH）+`/spine-suggest`+`/model`+`/context-preview`+`/usage`+`/event`（及`/events/summary`） | `adaptive.py` + `settings_bundle.py` + `adaptive_prompts.py` | **前端默认**（作者主导写作+AI 柔性共生，无预设拍） |
| **BS-ADF** | （端点已摘除） | （已归档 `backend/_deprecated/bsadf/`） | **已归档 2026-08-19**（思想已迁入 adaptive；涌现抽取在 `services/adaptive/emergent_facts.py`） |
| ADF | `/generate-adf` | `ADFWorkflow`（`workflows/adf/`） | 引擎本体，前端已无 UI 入口 |
| Refinery | `/refinery/diagnose`+`/confirm` | `Refinery`（`services/refinery/`） | 独立精修（对任意草稿） |
| 章节优化 | `/optimize_chapter`+`/optimize_selection` | `refine_draft`（`workflows/refining.py`） | 章节重写/局部优化（前端在用） |

### NLE-ADF 3.0 自适应融合写作台（前端默认路径）

核心理念：**作者永远在写，AI 在画布上柔性共生**。与已归档 BS-ADF 步进模式的根本区别——不预设拍划分、不跑整章管线前置；作者进章节打字即激活辅助层。

- **双轴状态机**（`useGenerationSession.ts`）：`authorLane`（idle→composing→ghostStitching→settling，前台主线）+ `aiLane`（dormant→perceiving/suggesting/assisting/digesting/analyzing，后台）。两轴并行不阻塞，与旧 `stage` 单轴（legacy step）共存。
- **激活**：作者进章节打字 ≥4 字 → `enterAdaptive(chapterId)` 置 `authorLane=composing`（不跑 startBeat 管线）。辅助层（`useAdaptiveAssist.ts`）据此挂载。
- **自适应辅助触发**（全部柔性可忽略。⚠ 端点以代码为准：**不存在** perceive/detect-branch/plan-suggest——感知与规划建议均由心跳响应携带）：
  - 心跳 → `/adaptive/heartbeat`（活跃防抖 3s / 停顿 4s+光标段尾，`useAdaptiveAssist.ts`）：后端 orchestrator 跑方向权重（纯算法 0 LLM）+ 组件（意图反推 0-1 LLM / 未来推测 / 挂件生发 / Canon 感知），响应带回 `dock_parts`（Spark Dock 零件）/`direction_cards`（走向卡）/`canon_hints`（左缘感知带）/意图信息
  - Space（有零件=缝合续写 / 无零件=顺句续写）→ `/adaptive/stitch-ghost`（SSE 打字机灌幽灵草稿，复用 `useGhostDraft`；mode 五档：stitch/continue/burst/open/**outline**；S2 起四模式 prompt 均注入文风：正面画像块 + 作者笔迹示范 few-shot（`style/retrieval.py` 按当前上下文检索 k≤2，无样本零变化））
  - **细纲胶囊**（Alt+O / 输入 `[[` / 选中文本转换，`extensions/OutlineNoteNode.ts` + `OutlineNoteChip.vue`）：作者亲笔剧情速记以胶囊嵌在正文任意位置 →「落笔扩写」走 stitch-ghost mode=outline（双端锚定：胶囊前 500 字 + 后 300 字；目标字数解析速记中「约N字」clamp 100-800 缺省 400；×1.6 压缩重试 + ×1.5 句界截断硬闸门）。扩写启动即塌缩为钉 ⚑ 可再扩写；**会话级，存盘剥除**（与幽灵同契约，`stripGhostDraftHtml` 一并剥 `[data-outline-note]`）；编排经 `velluma:outline-expand` 事件解耦（`useAdaptiveAssist.requestExpandOutline`）
  - **情境浮卡 + 世界速记（写作桥，见世界设定层）**：选中正文 1-12 字或点击 @/# 提及 → `GET /world/context-card` 浮情境卡（此刻状态/编年史/控制方，解析不到静默缺席）；Alt+N → `POST /world/parse-event` 一句话解析成事件草稿（只产草稿绝不落库，作者过目入账 + 6 秒撤销胶囊）
  - **章级谋篇（M1-M3，`docs/chapter-planning-spine.md`）**：`GET`/`PATCH /adaptive/spine`（`chapters.spine` JSONB，部分合并；副驾「打算」tab 编辑，2s 防抖自动保存）+ `POST /adaptive/spine-suggest`（1×creative 建议不落库，D-4 红线）；走向卡 ⚑ 挂锚点（serves_anchor 写入/提取双侧代码闸）、pending 锚点关键词命中→纯算法进度判定进心跳、带 branch 的临近锚点置顶为硬提示卡（选向即决岔）+ finish 报告附 spine_note（未兑现锚点仅提示不阻塞）
  - 沉淀 → `/adaptive/settle`（**纯手动** Ctrl+Enter，无自动字数门槛；抽涌现实体 + 可选落库，设定逆向生长；另触发 event_scout 抽候选事件进收件箱——P5 起**三重去重**（prompt 排除近 15 条已入账事件 + 归一化双向子串预筛 + pending 池幂等）；收件箱**批量裁决**（逐条预览剔除 + 6s 复合撤销=删产物+reopen），积压 >5 走心跳 canon_hints 的 `kind=world_inbox` 感知带提示，settle 完成 toast 直达收件箱）
  - 完稿审计 → `/adaptive/finish`（残句/覆盖率/Canon 合规/整章审阅 + 记忆重索引 + 整章候选抽取）；报告中的残句条目可走 `POST /adaptive/fix-sentence` 定点修复（作者裁决式：只产修复句不改正文，采纳才替换）；`GET /adaptive/model` 世界模型快照（副驾「调试」tab，`InspectorPanel.vue`）
  - 协作埋点 → `POST /adaptive/event` + `GET /adaptive/events/summary`（本地 `data/collab_events.jsonl` 零上报个人镜子，book_id 服务端解析防伪；insights「协作」面板消费）
- **设定数据双向驱动**（`settings_bundle.py`）：章级绑定 + 书级 Canon（[public]/[private]）+ 世界观，一次加载供所有 adaptive 端点共用；**世界设定层优先**（见下节 world_bridge——世界页有实体时 bundle 的角色/资产/地点/关系切换为 world 数据 + 叙事时刻推演状态，无实体回退旧表）。写作中感知 + 后台方向权重规划两个层面同时利用。
- **上下文装配与预算（P5）**：stitch 装配唯一入口 `services/context/stitch_context.py`（`assemble_stitch_context`——stitch 路由与 `GET /adaptive/context-preview` 预览**同源共用**，预览=副驾「调试」tab「AI 此刻所见」折叠区，红线：禁止平行实现）；七块注入序唯一权威 `adaptive_prompts.render_system_blocks`（画像→样本→专名→canon→**secrets 私有**→回响→空间）；**截断/剂量常量唯一权威在 `services/context/budget.py`**（57 项，改截断前先查它）+ 两级 `allocate`（块内生产者优先级 + 跨块硬软分级——硬块 canon/secrets/专名永不裁，软块按 echoes→samples→spatial→style 序收缩；`MODE_CONTEXT_BUDGETS` 默认=自然总和恒等不触发，分档调参留实测期）。
- **画布即事实源**：写作台无生成预览层（旧 preview 属性链已随写作台重构移除），作者写的即真实文档；沉淀只做后台消化（抽实体+可选落库），不产生第二份文本。落库由 `ChapterEditor` 的 `update-chapter` 机制实时覆盖。
- **写作台「纸面优先」布局**（2026-08-17 重构）：880px 纸列是唯一主角——列内页面头（`第N章` label + 衬线大标题 input + ⋯ 章节动作菜单：发布/灵感/审阅/全文格式整理，经 `editorHandle.formatWholeDocument`），正文区**无常驻格式工具栏**（选中文字浮窗保留 B/I/U + AI 润色/改写 + 黄金片段[双写文风样本库]/这不像我[负面候选投文风收件箱，S3 起]；TipTap 排版扩展仍加载，仅删工具栏 UI，避免旧章节格式在下次保存被剥除）。顶栏极薄化：状态文案（adaptive 跟 aiLane）+ AI 辅助开关/快捷键/抽屉三按钮。右缘副驾抽屉四 tab + 底部降级入口（2026-08-22 易用性重构：五 tab→四 tab，按写作流程排序，每 tab 带一行用途副标题）：**打算**（章级软脉络 SpinePanel + 大纲编辑卡 + 意图反推小字行——写前规划）/ **此刻**（世界场景切片+候选收件箱）/ **本章**（字数与出场角色统计、本章文风、真相账本跳转——世界页 `?panel=canon` 深链）/ **检查**（完稿体检按钮+报告、沉淀抽取结果、Refinery 润色、读者反馈、手术历史、检查结论——按 检查→修改→反馈 三组排布）；原「调试」降级为抽屉底部「AI 视角」小按钮（AI 此刻所见预览 + 世界模型快照——引擎观测），Ctrl+1~4 切 tab、Ctrl+5 进 AI 视角、Ctrl+\\ 固定；切章默认 tab 按章节状态（空章→打算、有正文→此刻，用户手动切过即尊重）；完稿审计报告到达时抽屉自动滑出一次。润色与读者反馈门槛由 `stage` 门控改为**本章有正文**（`chapterHasContent`），修活 adaptive 下（stage 恒 idle）永不可达的死入口。BS-ADF 步进 UI（GenerationStepper/StoryboardPanel/BranchDecisionPanel/CurrentTaskBar/BeatSlotCardView/FocusAssetsPanel/GhostTimeline/BranchBanner/AutoCutHint/GenerationOverlay/PlanConfirmModal/TierSelector）已整体删除，`useGenerationSession` 内步进调用逻辑亦已删除（2026-08-19，-1168 行；仅 `_cancelSteppingRun` 空壳保留防清理连锁）。
- **Spark Dock 解耦**：gate 从 stage 解绑，`authorLane=composing` 即激活（零件源从拍卡改为心跳供给 + 章级兜底）。

### 世界设定层（World，★ 静态设定的唯一编辑源与生成数据源）

事件溯源式世界建模器：`world_events`（append-only 事实源，11 种事件类型）+ `world_entities`（人物/势力/资产固有属性，档案在 `props` JSONB 表驱动）+ `world_locations` + `world_relations`（static 或事件锚定的时变关系）+ 地图底图表 + 候选事件池 `world_event_candidates`。任意时刻的世界状态（谁在哪/生死/疆域/关系）由 `compute_world_state_from_events` 纯函数折叠推演（前后端同构，前端 `features/world/engine/`）。UI 单一画布（M6「活舆图」）：地图（Leaflet）承载全部实体/关系/事件（脑图透镜已退役，⇧拖建关系等手势平移至地图），**悬浮胶囊工具条**（记一笔历史/地点/实体/世界观/⋯）取代顶栏，**右缘 46px 图标栏 + 浮出抽屉**（待确认/伏笔/期待/真相/地点/事件/角色/势力/资产）取代右侧栏；书名水印题字；**空白舆图**（无底图时铺手绘风地球世界平面——`blankAtlas.ts` 的 `BLANK_ATLAS_INNER`（⚠ 生成物，由 `scripts/make_blank_atlas.py` 从 Natural Earth 50m 海岸线/湖泊/河流/国界生成，等距圆柱投影·中央经线 40°E（欧亚大陆居视觉中心，切线 140°W 过东太平洋，阿拉斯加/阿留申分列两缘），改轮廓/装饰锚点先改脚本再重跑），svgOverlay 随图缩放，viewBox 与 bounds 必须同为 2:1 防纵向变形，海岸线走 `wm-ink-soft` 细毛边滤镜，国界点状虚线/山河/经纬网，提示收进浮动卡，首个实体落地即退场；空白态初始视野框住世界平面，用户拖/缩后不再插手；数据缓存 `data/atlas-src/` 已 gitignore）+ **罗盘**（实功能：点击「回到全图」视野收拢到内容包围盒；针平时轻摆、点击大摆归北）；底部时间轴为编年史带（含章节叙事锚 `chapters.narrative_time` + 伏笔弧线带）；时间轴 UI 状态（游标时刻+手动视野窗口）按书持久化于 `books.timeline_view`（`GET/PATCH /books/{id}/timeline-view`，键级合并、显式 null 删键，前后端校验同构 `engine/timelineView.ts`）——⚠ 勿用 localStorage 存世界页状态：启动脚本端口扫描换 origin 即漂移（曾表现为重启后视野重置回第 1 年），旧 `velluma:tl-*` 键仅作一次性迁移来源。表单体验：textarea 统一走共享指令 `v-autogrow`（`presentation/autogrow.ts`，随内容长高、max-height 封顶）。

- **生成桥接（world_bridge，已接通）**：`services/context/world_bridge.py`——世界页有实体时 settings_bundle 走 **world 优先**：实体/关系经鸭子类型适配器包装成旧 Character/Asset 形状（下游 hard/soft/nutrients 零改动），`dynamic_state` 自动携带叙事时刻推演状态（「位于北岸要塞」「在途（进度 40%）」「已死亡」）；叙事时间四级降级（本章锚→前序最近锚→事件最大时刻→0；P5 起切片条显示来源小字+「锚定本章」快捷入口，建远期事件时表单内联警示）。**P5 在场提权**：角色名单排序键=在场（命中本章场景钉，**死者不进在场集**）→有事态→重要度，无场景钉零变化。**P5 私有语义**：`visibility=private` 实体档案不进 prompt 文本装配，改入 secrets 通道（第七块「你知晓但绝不能直接写出」，对齐 canon `[private]`；内部算法消费者仍吃全量——双轨纪律）。`bundle.world_state/world_time/world_sourced` 携带切片快照。桥接失败/世界为空 → 旧表兜底（未迁移书行为不变）。
- **编辑入口收敛（M4/M5）**：设定页角色/资产/地图（M4）+ 伏笔账本/期待账本/世界观（M5）分区已退役为跳转卡（`WorldRedirectCard`，带 `?entity=`/`?panel=` 深链）；保留分区仅剩**笔记+跳转卡**（文风已迁独立文风页 `/style/:bookId`，设置已改全局弹窗 `AppSettingsModal.vue`——AppRail 齿轮入口，任何页面可达）。旧面板 CharacterPanel/MapSettings/asset-panel/ForeshadowingPanel/ReaderMirrorPanel/WorldviewSettings/SettingsPanel 已删除。M5 世界页新增承载（M6 起位于图标栏抽屉/胶囊条）：「伏笔」抽屉（`ForeshadowSection` 全量账本+状态筛选，未锚定伏笔的唯一可见处）+ `ForeshadowDetailDrawer`（就地编辑/未锚定一键锚游标/回收/废弃/删除 undo）、「期待」摘要 + `ReaderMirrorModal`（火候看板/张力曲线整面板迁入）、胶囊条「世界观」+ `WorldviewModal`（2s 防抖自动保存/导入导出）；伏笔/期待/世界观编辑后统一广播 `velluma:world-refresh` 刷新写作页切片。
- **章级在场改推演**：原角色/资产/地点勾选绑定（chapter_entities 等）退役——「本章在场」由事件按叙事时刻推演（`GET /world/state-for-chapter/{chapter_id}`，SceneSettingsPanel 只读展示）。entity-mention（@/#）建议与创建均走 world（无世界数据回退旧表），不再写章级绑定。
- **AI 写路径（M4）**：`content_extractor.commit_extraction` 与 adaptive 沉淀落库改写 world_*（角色档案全文进 `props.background`——**迁移而非兼容**：启动数据迁移已把历史 `props.legacy_profile` 并入 background 并摘键，读写两侧均无 legacy 回退）；**未迁移书首次 AI 落库前自动执行幂等迁移**（防 world 优先切换后旧角色从生成上下文失踪）。伏笔（PlotLedger 共享表）与向量记忆不变。
- **写作桥（world-writing-bridge，W1-W5lite 已上线，`docs/world-writing-bridge.md`）**：沙盘价值送货到写作现场——①`GET /world/scene-slice`「此刻此地」切片条（副驾抽屉「此刻」tab，替换旧 SceneSettingsPanel；在场/脚下含疆域控制方/相遇/头顶的线，与生成上下文同源）；②`GET /world/context-card` 情境浮卡（选中文本/点击提及）；③`POST /world/parse-event` Alt+N 世界速记（解析/落库分离红线）；④候选回流：`event_scout` 独立组件（orchestrator 注册，settle 带段/finish 带整章各触发一次）→ `world_event_candidates` 待确认池（与事件账本物理隔离）→ 切片条收件箱 + 世界页「待确认」分区 ✓/✗/撤销；⑤保鲜三时机（章节切换/心跳 `world_version`/窗口聚焦，`useWorldSlice` 单例）；⑥深链往返 `?entity|loc|fs=&time=&from=chapter&chapter=`（世界页「返回本章」；`?fs=` 开伏笔详情抽屉，`?panel=expectations|worldview|canon` 开对应账本/真相格，写作页「头顶的线」伏笔/期待行可点击）；⑦本章场景钉 `chapters.scene_location_id`。事件解耦：`velluma:world-version` / `velluma:world-refresh` / `velluma:quick-note`。
- **真相层（Canon 融合 C1 ✅ 2026-08-17，`docs/canon-world-fusion.md` + UX 稿 `docs/design/canon-fusion/`）**：信息层（作者真相 vs 读者认知）并入活舆图——图标栏账本族第四格「真相」（`CanonSection`：表里三态过滤 秘密/半露/公开 + **句子优先录入**「＋ 记一条真相」，C1 过渡期建「叙事」自由节点）；真相详情抽屉（`CanonTruthDetailDrawer`：**表**（读者所见，public_text）/ **里**（作者真相，canon_text）两面就地编辑失焦即存，「里」朱晕+密印+泄密警示；揭示计划/章号/标签/钩子字段）；因果图谱模态（`CausalityGraphModal`：旧 CanonGraph **只读降格**，全部/只看秘密/只看伏笔过滤，点节点跳真相详情）；`useCanon` 迁 `world/composables`（ensureLoaded 幂等 + CRUD 后广播 world-refresh）。**后端零改动**（canon.py / canonApi / 生成消费链 `[private]/[public]/[hook]` 三段格式冻结不动）；泄密检测（canon_checks/canon_watch）与 CanonHighlight 零感知。旧入口退役：AppRail「脑图」删除、`/canon/:bookId` redirect → `/world/:bookId?panel=canon`、`features/canon/` 目录删除。**C2 ✅ 2026-08-19**：canon_nodes.ref_type/ref_id 信息面挂接（label/type 读取时由世界对象推演——根治名字漂移）、hook 并入 plot_ledgers（canon_text/public_text/reveal_plan 列）、`/world/migrate-canon` 预览确认迁移、`build_canon_context_for_prompt` 换源（往返契约单测 `services/canon/test_context_contract.py` 锁三段格式）、EntityDetailDrawer「读者认知」分区为实体 overlay 唯一创建口（create 幂等护栏）；**C3 ✅**：真相抽屉连锁分析/查片段、提取候选入待确认池（source=canon_extract，accept 分流建 tentative 真相节点）、时间轴揭示朱点+心跳揭示临近提醒（expected_reveal_chapter 距本章≤2 章）。
- **待办**：旧表冻结声明已落 8 处在役模块（下次实质改造换源 world）；写作桥 W5 余项——全图读者滤镜（等切片条读者档使用数据）、相遇→走向卡桥的采纳率验证（encounter_card_burst_rate 度量已埋）。

### 文风页（Style，★ S1 已落地 2026-08-18，`docs/style-module-redesign.md`）

作者笔迹的独立工作台（文风回答「这个作者怎么写」，与世界页正交，已从设定页迁出：AppRail「文风」`/style/:bookId`，`features/style/`；`components/StyleCardManager.vue` 删除拆解迁入；bible 只剩笔记+跳转卡）。范式：**测量 > 声明**（指纹 code 算）、**范例 > 形容**（few-shot 注入为最大杠杆，S2）、**闭环 > 开环**（每章对账）。

- **同一把尺子（⚠ 改统计口径前必读）**：`services/style/fingerprint.py` 是句长切分/字数/CV/对话字符统计的**规范实现**，审计侧 `services/validation/code_auditors.py` 从此 import（同名 alias，指标口径零变化）；对拍单测 `backend/services/style/test_fingerprint.py`（19 项）锁定「同一文本指纹侧 CV/对话占比 == RhythmAuditor/DialogueAuditor 指标」——改任一侧算法先跑它。指纹结构：句长族（均值/中位/CV/碎句率/五桶直方图）+ 对话占比 + 段落族（叙述段，排除对白段）+ 标点每千字 + 修辞密度（复用 `ai_taste_meter`，light 模式省略——章节批量算用 light）。
- **端点**（`routes/style.py`）：`GET /books/{id}/style-fingerprint`（语料聚合 `aggregate_corpus` 拼接整体测 + 逐样本 light 指纹 + `with_chapters=true` 时最近 N 章**实时计算**章指纹 + reference{cv_healthy, dialogue_target}——**不建新表不回填 QualityReport**，实时算永远与正文同步且不遮蔽审计报告）；`POST /books/{id}/samples/from-chapters`（已发布章节→样本收编，`source=published_chapter` 通路首次写入，摘章节开头至句界；未发布书回落有正文章节；S5 起**剥 HTML 转纯文本**（与 memory_indexing 同口径）+ 纯文本判空（`<p></p>` 空文档不误判）+ 已收编章节幂等跳过）。
- **页面**（`StyleView.vue` 容器 + presentation 分区组件）：单页叙事线 ①你的字（样本库，每条带指纹速览 chips）②笔迹指纹（句长直方图 + 指标网格 + 高级折叠[五维画像/提炼入口/章级特例]）③意图旋钮 ④负面清单 ⑤对账（章 CV 与对话占比趋势 SVG，参考底色带=CV 健康区间/目标±0.2，出带点标红，人话总结含「与语料实测差 >0.15」漂移探测）；S5 起布局改版为**两栏仪表盘**（①+② 并排 5:7、④+⑤ 并排 1:1、意图整宽，流式宽度 96rem 封顶，<74rem 窗宽塌单列，hairline 分隔归容器 `.section-row`）。零状态坡道三幕（S5 重修）：无样本**且无既有配置**→整页 hero 邀请（垂直居中+衬线大标题+去分类下拉）+章节收编兜底；1-2 条→只长样本+指纹（长成预告细带）；≥3 条且画像空→浮出提炼建议。提炼红线不变（不落库，过目才存）；2s 防抖自动保存 + negative_list↔style_blacklist 同步沿用旧契约。
- **S2 执行层接通 ✅ 2026-08-18（文风开始真正影响生成）**：①**E1 范例注入**——`services/style/retrieval.py`（`retrieve_author_samples`：向量流 `search_by_style` 优先 + 新近兜底，k≤2×1200 字句界截断，失败→空列表；**P5 C2 场景匹配**：stitch 链路按 rolling 尾 300 字对话占比 >0.35 判 `scene_hint=dialogue`，向量流同型样本 +0.1 软加成、兜底流同档提前，None/general 逐字节零变化；burst 模式 k=3），stitch-ghost 四模式 prompt 注入「作者笔迹示范」块（学语感禁复制），ADF `adf.py` 的 `author_samples=None` 解封（传 List[str]，k=3）；②**E2 画像注入**——`settings_bundle.render_style_positive`（五维中文标签+段落节奏+对话目标，≤10 行）经 `to_prompt_context`/`soft_constraints` 暴露 `style_positive`，四 builder 注入「作者文风画像」块（此前 adaptive 只消费负面清单）；③**E5 润色消费**——refinery `_build_refinery_context` 填 `author_samples`（polisher 休眠签名接活）+ 负面清单进 `forbidden_terms`；`/optimize_selection` 注入文风约束块；④修 `adf/refiner.py` positive_traits 死字段（`_build_style_contract` 统一口径）。**零变化契约**：无文风卡/无样本的书 prompt 逐字节不变（`test_style_injection.py` 锁定）。dock 零件 prompt 有意不注入画像（8-14 字零件吃不到画像，防膨胀轻路径）。
- **S3 交互环 ✅ 2026-08-18（文风的反馈环闭合）**：①**试衣间**——`POST /style/audition`（SSE；`build_audition_prompt` 与 stitch 四模式共用同一套文风块，「所见即所得」有单测锁定；`style_override` 可试听未保存草稿；A/B=基线不注入 vs 当前文风）+ 文风页顶部试听横条；②**💛/⚠ 微交互**——选中浮窗「黄金片段」双写文风样本库（golden_snippet 通路接活）；「黑名单」按钮改造为「这不像我」→ 负面候选投收件箱（旧直写 style_blacklist 退役）；「改得更像我」=既有「AI 润色/改写」（S2 起带文风）；③**收件箱**——`style_inbox_items` 表 + 四端点（confirm 负面候选→negative_list+同步黑名单；候选不直接生效红线）+ 文风页 ✓/✗ 区；④**章级覆盖**——DELETE `/style-card?chapter_id=` + 文风页高级面板「编辑对象」切换 + `?chapter=` 深链 + 副驾「本章文风」卡；⑤**E3 禁词审稿**——`POST /style/scan-negative`（三层禁词扫描，纯 code）+ 负面清单区审稿模态（替换/收入清单/忽略逐条裁决）；de_ai_washer 增 `extra_banned_words`（defat 带章节上下文）。💛 的 6 秒撤销胶囊未做（toast 无 action），S4 补。
- **S4 抽象与切分 ✅ 2026-08-18（设计稿 S1-S4 全部落地）**：①**意图旋钮**——`style_cards.style_knobs`（JSONB，MIGRATIONS 已加列；{rhythm|register|density|warmth: 1-5}，缺键=自动档不注入）+ `services/style/knobs.py` 档位权威表 → `render_style_positive` 渲染意图行（自动档零变化）；文风页「意图」区（四维五档按钮 + 对话旋钮=目标值五档落 dialogue_ratio_target，原滑条退役；能测量的两维（快慢/对话）标实测锚，手动档离锚远出「有意转型吗」提示）+ 四风格预设（冷峻短句/绵密抒情/口语白描/章回古雅，一键填旋钮+画像模板）；②**声纹**——实体档案 `speech_style` 字段即声纹载体（已经 world_bridge static_prompt 流入生成），未另建 voice 字段，单测锁定通路；③**💛 撤销胶囊**——useToast/Toast 加 action，收样本 6s 可撤销；④原缓行的**心跳漂移提醒**与**使用埋点**已在 S4+ 补全批次落地（见下）；**E4 指标制导维持不做**（无数据支撑，走向卡已是柔性机制）。
- **S4+ 补全批次 ✅ 2026-08-18（设计稿全项落地，唯一不做项 E4）**：①**台账化**——负面清单每条带近 10 章命中计数（fingerprint 端点 `negative_hit_counts`，零命中灰显）；系统陈词库折叠可见 + 单条**本书豁免**（`books.style_cliche_exemptions`，validator/ClichéAuditor/scan 三处消费）；数据页质量报告「＋收入负面清单」抓虫（高频项→收件箱）。②**四列落地**——`author_samples.era/favorite`（语料聚合只取近期；兜底检索收藏优先）、`style_cards.fingerprint`（写穿缓存，读仍实时算）、`locked_keys`（画像字段锁，🔒 逐字段/全部锁定=特殊文体让位，提炼跳过锁定字段）。③**from-golden**（存量黄金片段去重导入 + 文风页入口）。④**心跳漂移提醒**（章尾 3000 字同尺测量，`kind=style_drift` 并入 canon_hints 走感知带，按内容长度缓存）。⑤**埋点**（本地 `data/style_events.jsonl` 零上报：audition/golden/⚠/收件箱/预设/抓虫，`GET style/events/summary` 含采纳率）。
- **S5 UX 打磨与样本链路修复 ✅ 2026-08-18**：①**零状态 hero 化**——坡道第一幕垂直居中 + 衬线大标题 + 大输入区，场景/时期下拉框移出第一幕（默认 general/recent，事后样本卡可改），「整页只有一个邀请」成立；②**坡道门闸修正**——`zeroState` = 无样本**且无既有配置**（`hasStyleConfig` 扩入旋钮/对话目标；旧 StyleCardManager 时代有配置的书不再被折叠成邀请页），`growthStage` 三幕（ramp/early/full），章级特例深链强制 full 防死路；③**顶部常驻状态条**（`StyleStatusStrip.vue`：一句话总结实测指标 + ▶试听滚动锚点，sticky，语料为空不报假数字）；④**两栏仪表盘**（见上「页面」条）+ 直方图重做（柱子贴基线/柱顶计数/按最高桶归一峰值 96px/底线轴）+ 指标格 hint 两行不截断 + 样本列表限高 24rem 内滚；⑤**⚠ `--accent-400` 全局补齐**（`style.css` 浅色 #9685c2 / 深色 #8b6de8）——该 token 此前从未定义，文风页 6 组件 14 处引用（直方图渐变/hover 边框/焦点环）全部静默失效，是直方图柱子隐形的根因；⑥**样本创建链路事故级修复**——`AuthorSampleRepository.create_with_embedding` 把 ORM 实例传给 `BaseRepository.create(payload: dict)`（内部 `model(**payload)`）恒 TypeError，**手动粘贴/章节收编/黄金片段导入/收件箱确认四条创建通路曾全部 500**——已改 dict 契约并补 `era` 参数（此前 schema 有 era 但路由静默丢弃，已转发）。
- **笔迹 vs 声纹切分现况**：叙述文风（句长/语域/浓淡/冷热）走文风页（旋钮+画像+样本 few-shot）；角色对话腔调走世界实体档案「说话风格」字段（world_bridge 注入）——两条通路在生成上下文里自然汇合。

### BS-ADF（已整体归档 2026-08-19）

> 步进引擎已随 dc7af61/50099af 整体退役：引擎包 `workflows/bsadf/`（含 8 个单测与 `dde/`）→ `backend/_deprecated/bsadf/`，路由 → `_deprecated/routes/bsadf_route.py`，schema → `_deprecated/schemas/bsadf_schema.py`，`chapter_generation/__init__.py` 已摘除注册；前端步进调用与 `bsadfApi` 全部删除。**`/generate-bsadf`、`/advance-beat`、`/stepping-run/{id}/state`、`/rerender-beat`、`/cancel-run` 端点不复存在。**思想去向（详见 `_deprecated/README.md`）：DDE 真岔路→谋篇声明岔路 M3、章级规划层（脉络轨/锚点/定档/槽位卡）→软脉络 `chapters.spine`、字数闸→stitch-ghost outline 双层闸、Loop3 涌现抽取→`services/adaptive/emergent_facts.py`、残句门禁→`repair_single_defect`（`/adaptive/fix-sentence`）。步进运行时事实（`_STEPPING_RUNS` 纯内存 TTL 12h / 步进不自动写库 / 每条 advance-beat 一条新 SSE 流）随引擎归档，仅作历史参考。

### ⚠ 后端运行/落库边界（编辑前必读）

1. **adaptive 观测已接**（P0，`services/adaptive/observing.py`）：chapter 级常驻 RunRecorder（run_id=`adaptive_{chapter_id}`，per-chapter 锁 drain/restore 原子冲账防重复防丢账）；trace 按 chapter 单文件 `logs/trace_adaptive_{chapter_id}.jsonl` 追加；协作埋点本地 `data/collab_events.jsonl`（零上报）。**P5 用量可见**：`GET /chapters/{id}/adaptive/usage` + `GET /books/{id}/adaptive/usage`（`routes/chapter_generation/usage.py`，generation_runs 纯聚合零写，stage 按组件拆账），insights「协作」面板两卡消费。
2. **Refinery 与 ADF 内置的 REFINE 是完全不同代码**（同名不同实）；`services/refinery/__init__.py`「ADF Phase 4.5 触发」注释过时，代码无此集成。

### ⚠ thinking 关闭的正确姿势（`services/llm/client.py`）

要关 thinking 必须传 `reasoning_config=REASONING_DISABLED`（`{"reasoning":{"enabled":False}}`）。**传空 dict `{}` 无效**——`call_llm_with_usage` 里 `if reasoning_config:` 对 `{}` 为 falsy，推理模型回落服务端默认 thinking 开启，小预算调用（状态卡/残句修复）必被吃光预算空输出。已接 REASONING_DISABLED：render/enrich/state_tracker/beat_patch/refine/wash/sentence_fix/parse_event/event_scout。**中间表示经 `reasoning_adapter.py` 按域名转厂商原生参数**（DeepSeek/OpenAI/OpenRouter/Qwen/豆包/MiMo/本地）；MiMo 实测只认 `thinking.type`，静默忽略 OpenRouter 的 `reasoning.enabled`（隐藏思考烧光预算，勿删该分支）。

### 关键质量护栏（事故根因，勿回退）

> ⚠ 以下闸门多数位于已归档的 `_deprecated/bsadf/`（迁移取材用，不再随 live 代码演进）与共享模块；adaptive 流目前只继承了**字数硬闸门**（stitch-ghost mode=outline 的 ×1.6/×1.5 双层闸）与 enrich 双幻觉过滤的思想（adaptive 走「作者裁决即闸门」路线，无渲染期拦截）。迁移改造时从这里取材，勿凭空重写。

- **字数硬闸门**：超 target×1.6 带压缩反馈重试，末次仍超句界截断到 target×1.5（截断上限必须 ≤1.6）；末段（结局段）豁免截断。
- **REFINE 完整性闸门**：补埋输出采纳前强制句末完整性校验，回退后丢失过半则整段放弃（宁缺勿残）。
- **enrich 幻觉闸门**：空种子禁自由扩写（防凭空产出）；剧情关键词/零接地双向过滤。
- **POV 名闸门**：状态卡已知 POV 角色时正文必须出现其名至少一次。
- **残句门禁与单条修复**（`workflows/sentence_integrity.py`，在役）：高精确度正则扫残句（宁漏勿误），`repair_single_defect` 定点修复（1×creative + REASONING_DISABLED + max_tokens=1600，批处理上限 5——现服务 `/adaptive/fix-sentence`；原 BS-ADF Phase 7.5 整章批处理用法已随引擎归档）。
- **上屏前快检（P5，`services/validation/ghost_guard.py`）**：stitch-ghost 完整文本生成后、GHOST_DONE 前纯算法扫三类疑点——死者开口（实体名/别名 × world_state alive=False）/ canon 泄底（private 标签正则）/ 私有短语外泄（secrets 整段复现）；warnings 随 GHOST_DONE 帧附，前端感知带疑点条 + 采纳 toast 提醒。**只提示不拦截**（柔性红线），无世界数据零报错。
- **状态卡抽取失败**：沿用旧卡显式记 `result.degraded`（不静默）；max_tokens=1600 兜底。

### RAG / 记忆流（`recall_memories`：默认流始终打底 + 向量流增强叠加）

唯一检索入口 `services/rag/recall.py` 的 `recall_memories`（消费方：stitch-ghost 五模式 k=3、dock_generator k=2，签名稳定），三层按质量序 `merge_echoes` 保序去重截 k：

- **A 结构化前情（始终）**：查询中出现的世界实体（名/别名匹配，≤4 个）× 叙事时刻之前（`resolve_narrative_time`）的 world_events，倒序取 3 条格式化为【前情事件·类型】（世界页无数据自动跳过）。
- **V 向量增强（专业级，embedding 已配置时叠加——不替换默认流，A/B 恒在）**：任意 OpenAI 兼容 Embedding 服务（`model_config.json` 的 `embedding` 节：`api_key`/`base_url`/`model` 默认 `text-embedding-v2`/`dimensions` 1536；`follow_llm=true` 时连接跟随文本模型槽——creative 优先、缺 Key 回退 reasoning，自管 Key/URL 被忽略；`base_url` 留空回退 DashScope 兼容端点，历史 DashScope Key 零迁移。Key 来自 model_config 不读环境变量）；`search_similar` 权重（`rag/scoring.py`）：alpha 0.6（语义）/ beta 0.2（时间衰减）/ gamma 0.2（伏笔）/ lambda_decay 0.1。
- **B 词法检索（始终补足）**：`jieba.analyse` 抽关键词（top 8）→ `MemoryRepository.search_lexical`（SQL ILIKE 预筛 ≤60 候选 + Python 重排：`lexical.keyword_coverage` 命中计分单关键词封顶 3 次 + 开放伏笔章 +1 + 新近 tiebreak）。
- **写路径**：完稿重索引（`memory_indexing`）/提取确认/发布摘要块——**块文本一律落库**，embedding 仅在已配置时生成（`is_embedding_configured()` 门控），未配置不再整块跳过（摘要块是词法检索最佳素材）。检索限当前章之前（防未来信息泄露），三层同规则。

---

## 数据库与迁移

**双路径（2026-08-19 起 SQLite 默认）**：不设 `DATABASE_URL` → SQLite 文件库 `data/velluma.db`（单机桌面零外部依赖；实现于 `backend/db_sqlite/`——`engine.py` WAL/外键/忙等 pragma 逐连接设置 + NullPool 防锁竞争，`type_compat.py` JSONB/Vector→SQLite 方言编译 + **UUID str 入参容忍补丁（⚠ 勿删：repo 惯约向 UUID 列传 str，PG+asyncpg 驱动层容忍，删此补丁 SQLite 下 world 查询全线 500）**，models 零改动；数据目录可用 `VELLUMA_DATA_DIR` 覆盖）。显式设 `DATABASE_URL=postgresql+asyncpg://…` → PG 原路径全保留（pgvector 向量记忆/连接池/维度迁移，专业级）。存量 PG→SQLite 一次性搬迁：`scripts/migrate_pg_to_sqlite.py`（PG 只读拓扑序，先对源库补齐 MIGRATIONS 缺失列再搬运，行数对照+外键校验）。

**启动时自动迁移**（非 Alembic）：`backend/database.py` 的 `MIGRATIONS` 列表（约 50 条）定义增量列变更，`init_db()` 启动时自动补齐（SQLite 路径走 `db_sqlite/schema.py` 的 `init_db_sqlite`：建表+同源列迁移+legacy 数据迁移+种子化）。改 ORM 后须同步加 MIGRATIONS 条目，重启即应用。

⚠ **向量维度迁移破坏性**（仅 PG 路径）：启动时 `migrate_vector_dimension` 若 embedding 维度与库列不匹配会**删列重建**（清空全部向量数据）。切维度前注意。

连接池（仅 PG 路径；SQLite 走 NullPool 无池参数）：`pool_size=10`/`max_overflow=20`；`DB_POOL_PRE_PING` Windows 默认关（asyncpg+greenlet），其他平台默认开。PG 手动建表前需 `CREATE EXTENSION IF NOT EXISTS vector;`。

---

## 配置

### model_config.json（主要配置入口，已 gitignore）

LLM/Embedding/代理实际配置来源（schema 见 `backend/core/model_config.py`）：`llm.reasoning`/`llm.creative`/可选 `llm.wash`/`embedding`/`proxy`。除手动编辑外可通过前端设置弹窗（`AppSettingsModal.vue`）经 `GET/PUT /api/system/model-config` 读写（GET 只回掩码，PUT 留空 api_key 表保持）。LLM/代理保存即时生效，embedding 维度变更需重启。**embedding 已降级为专业级**：设置面板默认折叠；未配置时记忆流走结构化+词法默认路径（见 RAG 节）。⚠ **当前工作区副本含真实 API Key，勿提交或外发**。

### 环境变量（.env 可选，仅以下几个实际生效）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DATABASE_URL` | 显式指定 PG 连接串（切回 PostgreSQL 专业级路径） | 无——**不设即默认 SQLite** `data/velluma.db` |
| `VELLUMA_DATA_DIR` | SQLite 数据目录（打包/便携场景覆盖 `data/`） | 项目根 `data/` |
| `DB_POOL_PRE_PING` | 连接池预检（仅 PG 路径；SQLite NullPool 不涉及） | Win=false / 其他=true |
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

**UI 文案术语口径**（2026-08-21 柔化轮定档，2026-08-22 副驾四 tab 轮修订）：品牌隐喻词保留（幽灵草稿/蒸发、走向卡、清脂、卡舱/挂件/零件、收编、真相·表·里、此刻此地、黄金片段、这不像我、细纲胶囊、沉淀）；⚠「谋篇」「锚点」「岔路」已退出界面词（用户实测非作者语言、第一眼不可懂）——上屏分别用「打算」「（非写不可的）情节/关键情节」「（可能的）发展/走向」，代码/文档概念名（spine、anchor、branch、chapter-planning-spine）可保留；工程黑话不上屏——用作者语言（完稿体检/检查报告、AI 从正文发现、逐章核对、秘密穿帮、前情记忆、样本统计、对照版、AI 用量、兜底记录 等，旧→新对照见该轮提交）；英文残留除设置弹窗技术参数外不直接上屏；采纳动词统一「采纳」（弃 锁死/落地）；埋点枚举键上屏须过 `InsightsView` 的 `COLLAB_KIND_LABELS` 映射。

---

## 测试

项目快速迭代期，测试有限，主要靠手动验证。后端工作流测试均为纯算法/LLM-mock 单测（不连真实 LLM/DB）：`python -m pytest <文件>`。

- 前端 vitest **只收集 `src/**/__tests__/**`**——新测试文件必须放 `__tests__/` 目录，放别处会被静默跳过（distance.test.ts 曾中招，4be1568 修复）
- BS-ADF：已随引擎归档至 `_deprecated/bsadf/`（8 个单测与 `dde/test_decision_set.py` 同迁，均不再运行）
- ADF：`workflows/adf/` 下 `test_consistency_guard`/`test_beat_patcher`/`test_state_tracker`
- `workflows/sentence_integrity.py` + `test_sentence_integrity.py`；`prompts/test_boundary_pacing_prompts.py`；`db_sqlite/test_db_sqlite.py`

⚠ **`workflows/conftest.py`（autouse）勿删**：每个测试结束重置全新 current event loop。存在原因——`IsolatedAsyncioTestCase`（adf 测试）与 `asyncio.run` 收尾会把事件循环策略 `_set_called` 置位且 current loop 置空，污染同进程后续 `asyncio.get_event_loop()`（历史受害者：归档前的 bsadf/test_downgrade.py、test_slot_builder.py，现随引擎在 `_deprecated/`）。跨多文件跑 pytest 时删除会随机失败。

**开发验证**：后端 `/api/health`；前端浏览器 DevTools + Vue DevTools；Prompt 日志 `logs/prompt_log_*.json`；生成全流程 trace `logs/trace_{run_id}.jsonl`（adaptive 流按章单文件 `logs/trace_adaptive_{chapter_id}.jsonl`）（JSONL 实时追加，含 run_start/阶段事件/slots_built 快照/每次 llm_call 的 system+user+响应+usage+延迟/final_text/run_complete；质量 debug 先按 run_id 定位文件再逐事件排查；单章数百 KB 属预期）。

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

> 废弃/归档清单：`backend/_deprecated/`（V3.0 Detonation / V3.1 Unified / V4.0 DualTrack / **BS-ADF（2026-08-19，含路由 `routes/bsadf_route.py` 与 schema `schemas/bsadf_schema.py`）**整引擎归档，不参与 import 链，详见该目录 README）；`backend/_deprecated/docs/`（对应废弃引擎的设计文档归档）。其余历史误标（`models_generation_task.py`、`services/` 空壳目录、`rag/tests/`、`state_machine/`、`PROXY_URL`/`DISABLE_PROXY`、pywebview/`app.py` 等）均已随代码清理删除，不再存在。

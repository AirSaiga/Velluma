# Velluma AI 小说写作助手 - Agent 开发指南

AI 驱动的长篇小说写作桌面应用（FastAPI + Vue3 + Electron）。许可证：AGPL-3.0。

> **引擎现状**：后端生成设施——**NLE-ADF 3.0 自适应流**（`/adaptive/*`，**前端默认且是未来唯一主线**）；**BS-ADF 已整体归档** `backend/_deprecated/`（2026-08-19，涌现抽取迁出为 `services/adaptive/emergent_facts.py`）；**ADF**（V3.2，引擎本体保留但前端已无 UI 入口）；**Refinery 已拔除**（2026-09-12：手术原语迁 `services/text_surgery/`，读者反馈收编 `/adaptive/reader-feedback`）。
>
> **演进唯一权威**：`docs/iteration-roadmap.md`（已完结期次长叙事归档于 `docs/roadmap-archive.md`）。**各领域带日期的施工/事故叙事**已归入 `docs/incidents/`。本文件只沉淀全局契约与速查：领域细节以「领域档案索引」表所指档案为唯一权威，本文件对应节只留速查红线+指针。

## 领域档案索引（改代码前按需必读）

本文件是全局契约与速查；四大领域的完整细节已拆分为按需加载的档案，**动手改对应领域前必须先读**：

| 要动的领域 | 必读档案 | 施工/事故日志 |
|------------|----------|----------------|
| NLE-ADF：心跳/挂件 dock/stitch 续写/细纲胶囊/沉淀/完稿审计/意图感知/上下文装配/约束治理 | `docs/agent/nle-adf.md` | `docs/incidents/nle-adf.md` |
| 编辑器本体：标点归一/粘贴净化/查找替换/排版 token | `docs/agent/editor.md` | `docs/incidents/nle-adf.md` |
| 世界设定层：活舆图/事件溯源推演/时间轴/world_bridge/写作桥/真相层 Canon | `docs/agent/world.md` | `docs/incidents/world.md` |
| 文风页：指纹/样本库/负面清单/写作规矩/试衣间/语义扫描/章级特例卡 | `docs/agent/style.md` | `docs/incidents/style.md` |
| 启动器/监控台/端口契约/日志架构/收摊停止 | `scripts/README.md` | `docs/incidents/launcher.md` |
| deai 去 AI 味小模型集成 | `docs/deai-integration.md` | — |
| 测试怎么写/放哪/怎么跑/改码后更新哪些 | `docs/testing-guide.md` | — |

---

## 技术栈

**后端** (`backend/`)：FastAPI 0.109 · SQLAlchemy 2.0.25（异步）· **SQLite（aiosqlite，默认——不设 DATABASE_URL 即 `data/velluma.db`，零外部依赖）**或 PostgreSQL 14+pgvector（显式设 DATABASE_URL 的专业级路径）· asyncpg 0.29（PG 路径）· OpenAI SDK 1.10（LLM 与 Embedding 同走 OpenAI 兼容协议）· Uvicorn 0.27 · pydantic 2.5.3 / pydantic-settings 2.1.0 / tenacity 8.2.3。根目录 `requirements.txt` 与 `backend/requirements.txt` 内容一致（两份均可，均含 `jieba`/`python-multipart`）。

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

启动脚本收敛于 `scripts/`，2026-09-19 起按**环境/功能完全隔离**分文件夹（用户拍板）：`scripts/dev/`（开发调试·后端热重载）与 `scripts/prod/`（正式生产）各四入口（后端 / 前端 / Electron / 一键三端），`scripts/monitor/`（.vbs 网页监控台+后台监督者）完全自持，`scripts/macos/{dev,prod}/` 为 macOS 对称实现，收摊脚本 `scripts/stop-velluma.{bat,ps1,sh}` 在 scripts 根全局通用。**每文件夹互不复用、互不引用**（monitor 的 dev_dashboard.py 是私有副本，即使逻辑相同也单独一份）：

```powershell
# Windows
.\scripts\dev\start-all.bat        # 开发调试（后端热重载 + Vite + Electron，自动开 DevTools）
.\scripts\dev\start-backend.bat    # 单独后端（热重载前台直跑；frontend/electron 同款单飞脚本）
.\scripts\prod\start-all.bat       # 生产体验（npm run build + Electron 载入 dist，无 Vite 无 DevTools）
.\scripts\dev\start-all.ps1 -ElectronOnly   # 仅 Electron（前后端已在运行）
.\scripts\dev\start-all.ps1 -SkipBackend    # 跳过后端
.\scripts\dev\start-all.bat -Force          # 清理端口冲突后启动
.\scripts\stop-velluma.bat         # 全局一键收摊（dev/prod/monitor 通用）
```

```bash
# macOS / Linux（bash，编排逻辑与 Windows 对称）
./scripts/macos/dev/start-all.sh   # 开发调试（后端热重载）
./scripts/macos/prod/start-all.sh  # 生产体验
./scripts/macos/dev/start-all.sh --dry-run     # 仅打印将执行的命令
./scripts/stop-velluma.sh          # 全局收摊
```

```powershell
# 网页监控台（scripts/monitor/，与前台启动完全隔离）
wscript scripts\monitor\start-background.vbs          # 后台模式·无热重载（无终端窗口）
wscript scripts\monitor\start-background-debug.vbs    # 后台模式·监督者 mtime 热重载
```

**完整启动器契约见 `scripts/README.md`（编辑启动脚本/监控台前必读），事故史见 `docs/incidents/launcher.md`。**速查三红线：

- **全端契约自检 `scripts/check_launcher_contract.py`（CI 阻断步）**：端口段（后端 8002~8100 / 前端 5175~5285，前端段仅 dev 环境持有）与 electron npm script 名写在 22 个检查面里对拍防漂移；改端口段须同时改全部实现再改该脚本常量。
- **环境/功能隔离纪律（用户拍板勿回退）**：dev / prod / monitor 三文件夹各自成文互不复用（宁可重复不可共享）；新入口进对应文件夹自带一份实现。
- **日志架构=文件为真相源**：编排核心直写 `logs/dev_backend.log`/`dev_vite.log`/`dev_electron.log` + 启动器叙事进 `dev_sys.log`；控制台显示可弃，数据不丢。

其余六条不变量（收摊/停止双闸、`electron:nobuild` 统一、stdin 切断、vbs 纯 ASCII+CRLF、pythonw 两进程对链、.ps1 编码与 `-f` 坑）全文见 `scripts/README.md`。

---

## 目录结构（仅关键标注）

```
backend/
├── main.py                 # 入口、路由注册、静态服务、CORS、asyncio 静默处理器
├── models/                # ★ ORM 模型包（35 表按领域分 8 子模块——_common/narrative/entities/memory/generation/style/canon/world，__init__ 全量 re-export，`from backend.models import X` 消费面零变化；跨模块 relationship 挂接在 _links.py）
├── database.py             # 异步引擎 + 启动时自动迁移（MIGRATIONS 列表）+ 向量维度迁移
├── core/  (config 端口扫描 / model_config 读 model_config.json / dependencies / exceptions)
├── config/ (仅存 intent_driven/intent_engine 两活件；V4.0 参数推导层全家已归档 _deprecated/config/)
├── routes/                 # API 路由（均在 main.py 注册）
│   └── chapter_generation/ # 包结构：__init__ 合并 adf/adaptive router + extra_router
│       ├── adaptive/      #   ★ NLE-ADF 3.0（前端默认；拆包：schemas/heartbeat/settle_finish/stitch/preview/spine/world_read/events 八子模块 + __init__ 合并 router；确定性闸门/后处理下沉 services/adaptive/stitch_gates.py）；usage.py 同包：/adaptive/usage 章/书两级聚合
│       ├── adf.py          #   /generate-adf（引擎本体保留，前端已无 UI 入口）
├── schemas/  repositories/
└── services/
    ├── llm/ (client.py REASONING_DISABLED / embedding.py OpenAI 兼容向量 / proxy / formatting / pricing.py 价目纯函数 / reasoning_adapter.py 思考方言，云端五厂商方言 docs/model-vendor-matrix.md 唯一事实源)
    ├── observability/ (run_trace.py: logs/trace_*.jsonl / run_recorder.py: GenerationRun 落库)
    ├── nlg/ (去 AI 味洗涤 de_ai_washer.py)
    ├── prompts/            # Prompt 模板（改后即时生效，无需重建）。含 adf/dde/nle/adaptive_prompts 等 + 测试
    ├── context/            # ★ settings_bundle.py（NLE-ADF 3.0 设定数据共享加载器）+ loader.py
    ├── rag/  (三活件：recall.py 唯一检索入口 + lexical.py 纯函数 + memory_indexing.py 写侧)
    ├── style/  (★ 文风体系：extractor.py 样本提炼 / cliche_provider / fingerprint.py 统计规范实现 / retrieval.py 作者样本检索)
    ├── validation/  (代码级 + LLM 级审计，服务 /chapters/{id}/quality-report 路由)
    └── workflows/
    │   ├── adf/            # V3.2 ADF 引擎（自包含，前端无入口）：adf_workflow 主类 + 各 phase 模块 + 3 单测
    │   ├── conftest.py     # ★ autouse fixture，防 asyncio 事件循环污染（见"测试"节，勿删）
    │   ├── sentence_integrity.py  # 残句门禁 + repair_single_defect 单条修复（服务 /adaptive/fix-sentence）
    │   └── refining.py     # ★ 共享（前端在用，非废弃），服务 chapter_optimization 路由
    （refinery/ 已随 Refinery 拔除移除；手术原语现居 services/text_surgery/，见引擎对照表）

frontend/
└── src/
    ├── components/         # 通用组件（⚠ 不受分层约束，部分直接 import services）
    ├── extensions/         # TipTap 扩展
    ├── features/           # 分层架构：*/containers + */presentation
    │   ├── generation/     # useGenerationSession 会话状态机 + useAdaptiveAssist 辅助层 + SparkDock/BeatCardDock/IgnitionCard
    │   ├── workspace/ chapter-editor/ outline/（大纲板=故事线俯视板，engine/storyline.ts 纯函数） library/ insights/ app/ extraction/ import-markdown/（新建唯一入口=LibraryView 快速创建轻表单）
    │   ├── world/         # ★ 活舆图（世界+伏笔/期待/世界观+真相层 Canon）
    │   ├── style/         # ★ 文风页 S1（样本库+笔迹指纹+负面清单+章对账）
    └── services/api/  domain/（业务 API：index.ts 聚合 bookApi/chapterApi + adaptive/world/canon/asset 等 *.api.ts）/ stream/（SSE）/ transport/（HTTP）

deai/                   # ★ 去AI味小模型子项目（自训 Qwen3-4B+LoRA，百炼部署；契约唯一权威 deai/docs/contract.md，docs/deai-integration.md 管宿主集成）
backend/_deprecated/  # 废弃引擎归档（V3.0/V3.1/V4.0 + BS-ADF；不参与 import 链，详见该目录 README）
data/ logs/ .venv/
```

---

## 核心架构要点

引擎各有独立工作流类与精修实现，**互不共享编排代码**（底层 LLM/观测/RAG 共用）。

### 引擎对照

| 引擎 | 端点 | 主类/模块 | 用途 |
|------|------|------|------|
| ★ **NLE-ADF 3.0** | `/adaptive/heartbeat`+`/stitch-ghost`+`/settle`+`/finish`（响应带 `reader_ledger` 读者清单）+`/fix-sentence`+`/spine`+`/spine-suggest`+`/model`+`/context-preview`+`/usage`+`/event`+`/constraints/summary`+`/opening-card`（开章卡：空章四面镜子零 LLM）+`/ask-book`（问书：`??` 行间手势，六类纯代码直答+LLM 笼）等 | `adaptive/` 路由包 + `settings_bundle.py` + `adaptive_prompts.py` + `stitch_gates.py` + `services/world/reader_ledger.py`（开章卡/读者清单聚合）+ `services/world/ask_book.py`（问书混合驱动） | **前端默认**（作者主导写作+AI 柔性共生，无预设拍） |
| **BS-ADF** | （端点已摘除） | （已归档 `backend/_deprecated/bsadf/`） | **已归档 2026-08-19**（思想去向见 `_deprecated/README.md`） |
| ADF | `/generate-adf` | `ADFWorkflow`（`workflows/adf/`） | 引擎本体，前端已无 UI 入口 |
| ~~Refinery~~ | （已拔除 2026-09-12） | 手术原语迁 `services/text_surgery/`；读者反馈迁 `/adaptive/reader-feedback` | **整体退役** |
| 章节优化 | `/optimize_chapter`+`/optimize_selection` | `refine_draft`（`workflows/refining.py`） | 章节重写/局部优化（前端在用） |

### NLE-ADF 3.0 自适应融合写作台（前端默认且唯一写作路径）

作者主导打字 ≥4 字即激活（`authorLane=composing`），AI 柔性共生、不跑整章管线。**完整契约唯一权威 `docs/agent/nle-adf.md`（编辑前必读——端点总表/状态机/挂件铁律/三键阶梯/细纲胶囊/问书/意图/装配/约束治理/关键质量护栏/RAG 记忆流全在档案）**，施工/事故史见 `docs/incidents/nle-adf.md`。速查红线：

- 心跳 `/adaptive/heartbeat` → 挂件四槽位（landing/toward_beat/echo/ambient，note 一律后端拼装不经 LLM）；卡舱入口=Tab 唯一恒 force_refresh；段落停在半句不生发且 `dock_muted=true`。
- 续写 `/adaptive/stitch-ghost` 五模式**追加式契约勿回退拼回**（接缝三护+复读剥离）；FIM 中插桥接 `suffix_anchor`；`reapGhostIfDead` 勿删；三键阶梯 Tab 采纳·Enter 暂留·Esc 丢弃。
- 取源唯一权威 `services/adaptive/paragraph_source.py`（layer1_facts 不得代替正文进 prompt）；装配唯一入口 `services/context/stitch_context.py` 与 `/adaptive/context-preview` **同源共用（红线：禁止平行实现）**；注入序唯一权威 `render_system_blocks`。
- 沉淀 `/adaptive/settle` 纯手动 Ctrl+Enter；意图三级源链（spine 0.9 > 大纲 0.85 > LLM 反推 0.55/0.4，消费阈 0.5，衰老闸 `INTENT_STALE_CHARS=100`）。
- 感知常驻（用户拍板）：切页只 `detach`、心跳用 `_lastCtx` 快照+章节纪元守卫；全量停机只随应用关闭。协作埋点只留机制四件+传感器（05 瘦身）；auto-read 双触发+预算闸；`quiet_learning` 静音派生不落库。

### 世界设定层（World，★ 静态设定的唯一编辑源与生成数据源）

事件溯源式世界建模器：`world_events`（append-only 事实源，11 种事件类型）+ `world_entities`/`world_locations`（parent_id 树）/`world_relations` 折叠推演，活舆图单画布（Leaflet+编年史时间轴）。**完整领域参考 `docs/agent/world.md`（编辑前必读）**，施工日志 `docs/incidents/world.md`。速查红线：

- 推演唯一权威 `compute_world_state_from_events` 纯函数，**前后端同构**（`features/world/engine/`，改任一侧必须同步）；生死语义「出场即活」。
- 生成桥接 `services/context/world_bridge.py`：世界有实体即 world 优先；`visibility=private` 档案不进 prompt 文本、改入 secrets 通道（双轨纪律）；桥接失败/世界为空回退旧表。
- 时间轴持久化红线：视野窗口浮点年合法性只看日空间非空（**勿改回 start<end**）；`PATCH /books/{id}/timeline-view` 必须携带 `{cursor, range}` 全量快照；勿用 localStorage 存世界页状态。
- 写作桥：`/world/scene-slice`（此刻切片）/`context-card`（情境浮卡）/`parse-event`（Alt+N 速记，**解析/落库分离红线**——只产草稿绝不落库）/`state-for-chapter/{id}`（在场推演）；光标派生场景 `active_scene.py`。
- 真相层：`[private]/[public]/[hook]` 三段格式**冻结不动**；字段级分层 `field_layers` 五条消费线；因果图谱已退役但后端边表/CRUD 与 `/impact` 路由保留勿删。

### 文风页（Style）

作者笔迹独立工作台（`/style/:bookId`，`features/style/`），权威设计 `docs/style-paradigm.md`（三平面分权）/ `docs/style-module-redesign.md`。**完整领域参考 `docs/agent/style.md`（编辑前必读）**，施工日志 `docs/incidents/style.md`。速查红线：

- **同一把尺子**：`services/style/fingerprint.py` 是句长切分/字数/CV/对话统计的规范实现，审计侧从此 import；改统计口径先跑 `test_fingerprint.py`（19 项对拍锁定）。
- 负面清单四源唯一权威 `services/style/prohibitions.py`；severity 两档，硬禁只提示、**绝不自动改正文**。
- 写作规矩（质感契约）唯一权威 `services/style/texture_contracts.py`（按书可覆盖，缺键=系统默认零变化）；执法词表旁路合并不进四源。
- 零变化契约：无文风卡/无样本的书 prompt 逐字节不变（`test_style_injection.py` 锁定）；章级卡=整卡覆盖，统一入口 `get_effective_card`。
- 意图旋钮已退役（字段冻结只读）；收敛两支柱=亲笔样本 few-shot + 负面清单执法；语义扫描挂点**仅在** `/adaptive/finish`（红线）；架构不变量=采纳线：线后作者文本永远只提示。

### deai 去 AI 味小模型（子项目，`deai/`）

自训「去AI味」改写小模型（百炼 SFT Qwen3-4B+LoRA）。**宿主集成唯一权威 `docs/deai-integration.md`、模型侧契约唯一权威 `deai/docs/contract.md`（编辑前必读）**，本节只留三速查：

- 配置节 `model_config.json` 的 `deai`（enabled/api_key/model/base_url）：**未配置=零调用、幽灵文本逐字节零变化**。
- 服务包 `backend/services/deai/`：`polish_fragment` 公共入口 + 契约§6 事实闸保底回退原文 + 宿主侧保名闸；挂点 stitch-ghost 呈现平面（≤100 字契约窗，burst/outline 长稿跳过）。
- ⚠ 调用三要点（勿改）：DashScope **原生**端点 / model 填部署名（非 ft-ID）/ `enable_thinking=false`；超时 8s，超时即保底回退。

### ⚠ 后端运行/落库边界（编辑前必读）

1. **adaptive 观测已接**（`services/adaptive/observing.py`）：chapter 级常驻 RunRecorder（run_id=`adaptive_{chapter_id}`，per-chapter 锁 drain/restore 原子冲账防重复防丢账）；trace 按 chapter 单文件 `logs/trace_adaptive_{chapter_id}.jsonl` 追加；协作埋点本地 `data/collab_events.jsonl`（零上报）。**用量可见**：`GET /chapters/{id}/adaptive/usage` + `GET /books/{id}/adaptive/usage`（`routes/chapter_generation/usage.py`，generation_runs 纯聚合零写，stage 按组件拆账），insights「用量」面板消费（05 瘦身：原「协作」面板已拆，仅存 generation_runs 观测面）。
2. **Refinery 已整体拔除（2026-09-12）**——同名不同实家族只剩 `workflows/refining.py`（章节优化 refine_draft）与 ADF `refiner.py`（Phase 6 补埋器）；`services/text_surgery/` 是 ADF 一致性守卫的手术原语新家。

### ⚠ thinking 关闭的正确姿势（`services/llm/client.py`）

要关 thinking 必须传 `reasoning_config=REASONING_DISABLED`（`{"reasoning":{"enabled":False}}`）。**传空 dict `{}` 无效**——`call_llm_with_usage` 里 `if reasoning_config:` 对 `{}` 为 falsy，推理模型回落服务端默认 thinking 开启，小预算调用必被吃光预算空输出。槽位配置 `enabled: false` 即显式关闭（`get_default_reasoning_config` 返回 REASONING_DISABLED 同形，不返回 None「不表态」）。**中间表示经 `reasoning_adapter.py` 按域名转厂商原生参数**；MiMo 实测只认 `thinking.type`，静默忽略 OpenRouter 的 `reasoning.enabled`（隐藏思考烧光预算，勿删该分支）。

**厂商能力档案（`services/llm/vendor_profiles.py` + `docs/model-vendor-matrix.md` 唯一事实源）**：①`shape_sampling_params` 在两条发送路径前置整形采样参数（Kimi K 系 schema 不含采样参数传了 400、DeepSeek 双 penalty 已废弃、GLM 温度上限 1.0、DeepSeek/MiMo 思考态采样静默无效）；`_PARAM_LOCK_CACHE` 400 自适应降级为最后防线。②强制思考模型收到「关闭」请求时适配层不发参数。③effort 白名单归一。④`GET /system/model-catalog` 喂前端设置弹窗。⑤模型配置预设：`model_config.json` 顶层 `presets` 节 + `GET/POST/DELETE /system/model-presets` + `POST /{id}/apply`；自动存档安全网 `maybe_capture_outgoing_slot`（对拍 `backend/core/test_model_presets.py`）。改档案先改 matrix 文档再改代码，跑 `test_vendor_profiles.py`。

### 关键质量护栏（事故根因，勿回退）

> **全文唯一权威已迁 `docs/agent/nle-adf.md`「关键质量护栏」「RAG / 记忆流」两节**（字数硬闸门 adaptive 现役形态/接缝三护/微镜头免压缩/REFINE 完整性/enrich 幻觉/POV 名/残句门禁/ghost_guard 十检全表/状态卡降级/RAG 三层 A·V·B 细节）；事故经过见 `docs/incidents/nle-adf.md`。速查清单：

- **字数硬闸门**：超 target×1.6 压缩重试、×1.5 句界截断上限（≤1.6）；outline 保尾双闸、stitch/continue 保头截断+压缩改写、微镜头（target ≤60）免压缩；对拍 `test_stitch_gates.py`。
- **ghost_guard 上屏前快检十检**：随 GHOST_DONE 上帧五类（dead_speak/canon_leak/secret_leak/cliche_hit/out_of_scene）+ beat_rush live+rewrite + shadow 四检只落台账（location_jump/cast_roll_call/mind_leak/belief_leak）；repair 资格约束进缝合返修环。
- **残句门禁**（`workflows/sentence_integrity.py`，在役）服务 `/adaptive/fix-sentence`；REFINE 完整性/enrich 幻觉/POV 名/状态卡降级详见档案。
- **RAG / 记忆流**：唯一检索入口 `services/rag/recall.py` 的 `recall_memories`（stitch 五模式 k=3、dock k=2，签名稳定）；A 结构化+B 词法恒在、V 向量已配置时叠加；检索限当前章之前（防未来泄露）。三层与去敏细节见档案。

---

## 数据库与迁移

**双路径（2026-08-19 起 SQLite 默认）**：不设 `DATABASE_URL` → SQLite 文件库 `data/velluma.db`（单机桌面零外部依赖；实现于 `backend/db_sqlite/`——`engine.py` WAL/外键/忙等 pragma 逐连接设置 + NullPool 防锁竞争，`type_compat.py` JSONB/Vector→SQLite 方言编译 + **UUID str 入参容忍补丁（⚠ 勿删：repo 惯约向 UUID 列传 str，PG+asyncpg 驱动层容忍，删此补丁 SQLite 下 world 查询全线 500）**，models 零改动；数据目录可用 `VELLUMA_DATA_DIR` 覆盖）。显式设 `DATABASE_URL=postgresql+asyncpg://…` → PG 原路径全保留（pgvector 向量记忆/连接池/维度迁移，专业级）。存量 PG→SQLite 一次性搬迁：`scripts/migrate_pg_to_sqlite.py`（PG 只读拓扑序，先对源库补齐 MIGRATIONS 缺失列再搬运，行数对照+外键校验）。

**启动时自动迁移**（非 Alembic）：`backend/database.py` 的 `MIGRATIONS` 列表定义增量列变更，`init_db()` 启动时自动补齐（SQLite 路径走 `db_sqlite/schema.py` 的 `init_db_sqlite`：建表+同源列迁移+legacy 数据迁移+种子化）。改 ORM 后须同步加 MIGRATIONS 条目，重启即应用。

**书籍备份/还原闭环（2026-09-19，`services/book_archive/` 唯一权威）**：书架「备份 → 删除 → 还原」。`GET /books/{id}/backup` 导出单 JSON 文件（`.vellumabook`：34 张书籍级表全部行 + `data/world_images/{book_id}/` 底图 base64 + 6 个 jsonl 台账按书过滤——collab_events 是四个机制零件的数据源，必须随备份走）；`POST /books/restore` 还原（**原 ID 直复**：canon_nodes.ref_id 软关联与 world_intents.source_key 字符串内嵌 ID 按原 ID 存活，重映射即静默切断；同 ID 已存在 409 拒绝；台账滤旧再追加幂等）。`DELETE /books/{id}` 连带清理文件侧（底图目录/台账本书记录/章级 trace+prompt 日志）——不清理则「删→还原」后台账双份。不变量：①新增书籍级表必须进 `tables.py` 注册表（圈行谓词三类：直接 book_id/经 chapter/经 character），否则备份静默漏表；②导入逐表按 `sorted_tables` 拓扑序 flush（裸 FK 不进单元工作排序——relationship 缺失即乱序插炸外键）+ 自引用列两阶段回填（world_events.supersedes/world_locations.parent_id）；③embedding 走 b64f32 打包、仅 PG 回填（SQLite 方言向量列恒 NULL 契约）。

⚠ **向量维度迁移破坏性**（仅 PG 路径）：启动时 `migrate_vector_dimension` 若 embedding 维度与库列不匹配会**删列重建**（清空全部向量数据）。切维度前注意。

连接池（仅 PG 路径；SQLite 走 NullPool 无池参数）：`pool_size=10`/`max_overflow=20`；`DB_POOL_PRE_PING` Windows 默认关（asyncpg+greenlet），其他平台默认开。PG 手动建表前需 `CREATE EXTENSION IF NOT EXISTS vector;`。

---

## 配置

### model_config.json（主要配置入口，已 gitignore）

LLM/Embedding/代理实际配置来源（schema 见 `backend/core/model_config.py`）：`llm.reasoning`/`llm.creative`/可选 `llm.wash`/`embedding`/`deai`（见 docs/deai-integration.md）/`proxy`/可选 `presets`（模型配置预设）/可选 `prices`（价目节，零默认价）。除手动编辑外可通过前端「API」弹窗（`ApiSettingsModal.vue`，2026-09 UX 重构为左侧导航式：左栏六项导航——写作/分析模型分分区编辑 + 预设库独立分区 + 向量/deai/代理分区，底部连接测试）经 `GET/PUT /api/system/model-config` 读写（GET 只回掩码，PUT 留空 api_key 表保持）。LLM/代理保存即时生效，embedding 维度变更需重启。**embedding 已降级为专业级**：弹窗内独立导航分区（非常驻默认分区）；未配置时记忆流走结构化+词法默认路径（三层细节见 `docs/agent/nle-adf.md`「RAG / 记忆流」节）。⚠ **当前工作区副本含真实 API Key，勿提交或外发**。

### 环境变量（.env 可选，仅以下几个实际生效）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DATABASE_URL` | 显式指定 PG 连接串（切回 PostgreSQL 专业级路径） | 无——**不设即默认 SQLite** `data/velluma.db` |
| `VELLUMA_DATA_DIR` | SQLite 数据目录（打包/便携场景覆盖 `data/`） | 项目根 `data/` |
| `DB_POOL_PRE_PING` | 连接池预检（仅 PG 路径；SQLite NullPool 不涉及） | Win=false / 其他=true |
| `VELLUMA_PORT` | 固定后端端口 | 无（默认 8002 起扫描） |
| `VELLUMA_LOG_LEVEL` | 业务日志级别（backend* 命名空间；非法值回退 INFO） | `INFO` |

⚠ 实际代理配置由 `model_config.json` 的 `proxy` 节决定（`get_active_proxy()`），不读环境变量。代码中**不存在**以下环境变量：`PROXY_URL`/`DISABLE_PROXY`、`DASHSCOPE_API_KEY`/`OPENAI_API_KEY`（Key 全来自 model_config.json）。

---

## 代码规范

**Python**：新 `.py` 必须加 AGPL-3.0 许可证头，统一 SPDX 短形式两行（`# SPDX-License-Identifier: AGPL-3.0-or-later` + `# Copyright (C) 2026 Velluma Contributors`），插在 shebang/coding 声明之后（`_deprecated/` 豁免），存量漏网跑 `python scripts/add_license_headers.py` 幂等补齐，CI 有非阻断计数告警。LLM 调用用 tenacity 指数退避重试；流式错误发 error 帧+done 帧；Windows asyncio 无害连接错误已在 `main.py` 注册静默处理器。注释风格：模块顶用 `====`/`----` 分段，关键逻辑前标设计意图，副作用标 `副作用：`/`警示：`。

**TypeScript 前端分层**（依赖方向）：
```
features/*/presentation → 容器 props/emits（渲染、抛交互事件）
features/*/containers   → services/api/domain（状态整合、事件编排）
services/api/domain     ← 业务 API
services/api/stream     ← SSE
services/api/transport  ← 底层 HTTP
```
❌ `presentation → transport/stream` 禁止（见 `features/README.md`）。该约束 features/ 内执行良好；⚠ 通用组件层 `components/` 不受约束。命名：Feature 目录 kebab-case，容器 `*Container.vue`，展示 `*View.vue`/`*Panel.vue`（弹窗多用 `*Modal.vue`）。

**UI 文案术语口径**：品牌隐喻词保留（幽灵草稿/蒸发、走向卡、清脂、卡舱/挂件/零件、收编、真相·表·里、此刻此地、黄金片段、这不像我、细纲胶囊、沉淀）；⚠「谋篇」「锚点」「岔路」已退出界面词（非作者语言）——上屏分别用「打算」「（非写不可的）情节/关键情节」「（可能的）发展/走向」，代码/文档概念名（spine、anchor、branch）可保留；工程黑话不上屏——用作者语言（完稿体检/检查报告、AI 从正文发现、秘密穿帮、前情记忆、样本统计、AI 用量 等）；英文残留除设置弹窗技术参数外不直接上屏；采纳动词统一「采纳」（05 瘦身：「埋点枚举键上屏须过 COLLAB_KIND_LABELS 映射」纪律随协作面板一并废除）。

---

## 测试

后端 pytest 1614 项（124 文件）+ 前端 vitest 413 项（47 文件）全绿（2026-09-20 基线，**测试怎么写/放哪/怎么跑/改码后更新哪些测试的唯一权威=`docs/testing-guide.md`**，含勿删清单与有意不测台账）。后端工作流测试均为纯算法/LLM-mock 单测（不连真实 LLM/DB）：`.venv\Scripts\python.exe -m pytest backend --ignore=backend/_deprecated -q`（必须 venv 解释器+排除归档）。GUI 测试证据截图不入库、一律本地留存。

- 前端 vitest **只收集 `src/**/__tests__/**`**——新测试文件必须放 `__tests__/` 目录，放别处会被静默跳过
- ADF：`workflows/adf/` 下 `test_consistency_guard`/`test_beat_patcher`/`test_state_tracker`
- `workflows/sentence_integrity.py` + `test_sentence_integrity.py`；`prompts/test_boundary_pacing_prompts.py`；`db_sqlite/test_db_sqlite.py`

⚠ **`workflows/conftest.py`（autouse）勿删**：每个测试结束重置全新 current event loop。存在原因——`IsolatedAsyncioTestCase` 与 `asyncio.run` 收尾会把事件循环策略 `_set_called` 置位且 current loop 置空，污染同进程后续 `asyncio.get_event_loop()`。跨多文件跑 pytest 时删除会随机失败。

**开发验证**：后端 `/api/health`；前端浏览器 DevTools + Vue DevTools；Prompt 日志 `logs/prompt_log_*.json`；生成全流程 trace `logs/trace_{run_id}.jsonl`（adaptive 流按章单文件 `logs/trace_adaptive_{chapter_id}.jsonl`）（JSONL 实时追加，含 run_start/阶段事件/每次 llm_call 的 system+user+响应+usage+延迟/final_text/run_complete；质量 debug 先按 run_id 定位文件再逐事件排查）。**请求级链路日志（2026-09-20，`backend/core/request_observability.py` 唯一权威）**：控制台/dev_backend.log 直读——`[REQ] 方法 路由模板 -> 状态 耗时 req=xxxx handler=... ?query`（每请求一行，响应带 `X-Request-ID` 头可对账）、`[LLM]`（每次 LLM 调用的槽位/模型/耗时/token）、`[HTTP]`（4xx WARNING/未捕获 500 ERROR+traceback）；所有 `backend.*` 业务日志自动携带 `[req=...]` 关联（contextvar 过滤器挂 root handler）；uvicorn access log 与 httpx INFO 行已降噪收编。翻 `VELLUMA_LOG_LEVEL=DEBUG` 可看请求入口行与 adaptive/上下文装配内部链路。

---

## 部署

`electron-builder` 配置在 `frontend/package.json`（appId `com.velluma.app`，win=nsis/mac=dmg/linux=AppImage，`extraResources` 打包 `../backend`）。`cd frontend && npm run build && npm run electron:build`。FastAPI 已配 SPA fallback（`/`→`dist/index.html`，`/api/*`→404，其他→静态文件或 fallback）。**无 Docker**；CI 为 GitHub Actions（`.github/workflows/ci.yml`：后端 `py_compile` 全量编译检查 + 前端 `vue-tsc` 类型检查非阻断）。端口协商（`data/port.txt`）仅本地开发用，生产用 `VELLUMA_PORT` 固定。

---

## 安全

- **API Key 全部来自 `model_config.json`**（gitignore），不读环境变量、不入库。日志不打印完整 Key。⚠ 当前工作区副本含真实可用 Key，勿提交/外发。
- **CORS ⚠ 无条件** `allow_origins=["*"]` + `allow_credentials=True`（代码无环境区分），生产必须收紧为具体域名。

---

## Agent 速查

- **加 API 端点**：`schemas/` 定义 → `routes/` 加模块（`chapter_generation` 是包，在包内加并在 `__init__.py` 合并）→ `main.py` 注册（如未注册）→ 前端 `services/api/domain/` 加调用。⚠ NLE-ADF 3.0 的 adaptive 端点 schema 在 `routes/chapter_generation/adaptive/schemas.py`（Pydantic BaseModel）。
- **改数据库模型**：`backend/models/` 对应领域子模块改 ORM（新表进对应模块；⚠ 同一 flush 新建父子表必须补 relationship 依赖边——flush 跨表排序按 relationship 而非裸 FK）→ `database.py` 的 `MIGRATIONS` 加列迁移 → 重启自动应用。⚠ 新增**书籍级**表还须进 `services/book_archive/tables.py` 注册表（否则备份/还原静默漏表）。
- **改 Prompt**：定位 `services/prompts/` 下文件，改后即时生效（无需重建），建议查 `logs/prompt_log_*.json` 验证。
- **前端加 Feature**：`features/` 建目录，按 `containers/`+`presentation/` 分层，经 `services/api/domain` 通信。
- **改四大领域前先读领域档案**：见顶部「领域档案索引」表（`docs/agent/*.md` + `scripts/README.md`）。

> 废弃/归档清单：`backend/_deprecated/`（V3.0 Detonation / V3.1 Unified / V4.0 DualTrack / BS-ADF 整引擎归档；另有 rag 检索器全家、V4.0 config 参数推导层、orchestration agentic/beat_manager、prompts 三件等死代码批量归档——静态可达性+消费方 grep 双验零运行路径，不参与 import 链，详见该目录 README）；`backend/_deprecated/docs/`（对应废弃引擎的设计文档归档）。

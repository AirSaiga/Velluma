# Velluma AI 小说写作助手 - Agent 开发指南

AI 驱动的长篇小说写作桌面应用（FastAPI + Vue3 + Electron）。许可证：AGPL-3.0。

> **引擎现状**：后端生成设施——**NLE-ADF 3.0 自适应流**（`/adaptive/*`，**前端默认且是未来唯一主线**）；**BS-ADF 已整体归档** `backend/_deprecated/`（2026-08-19，涌现抽取迁出为 `services/adaptive/emergent_facts.py`，思想去向与归档清单见该目录 README）；**ADF**（V3.2，引擎本体保留但前端已无 UI 入口）；**Refinery 已拔除**（2026-09-12：手术原语迁 `services/text_surgery/`，读者反馈收编 `/adaptive/reader-feedback`）。
>
> **演进唯一权威**：`docs/iteration-roadmap.md`。**各领域带日期的施工/事故叙事**（控制台冻结、续写接缝事故、样本创建链路等过程记录）已归入 `docs/incidents/`，本文件只沉淀稳定契约与不变量。
>
> **NLE-ADF 3.0 自适应融合写作台**：作者主导写作 + AI 柔性共生。不预设拍、不跑整章管线；作者进章节打字 ≥4 字即激活辅助层（`composing` 态）。核心交互：心跳感知（挂件/走向卡/Canon 提示）、Space 续写幽灵草稿、Ctrl+Space 走向卡连写、细纲胶囊（`[[` 速记扩写）、Ctrl+Enter 手动沉淀、完稿审计、世界速记 Alt+N、情境浮卡、候选回流收件箱。**感知常驻（用户拍板「无论切到哪都不停感知，除非关闭应用」）**：切页只 `detach`（解除编辑器监听/中止需活编辑器的 SSE），pending 感知计时器照发——卸载后心跳用 `_lastCtx` 上下文快照（带章号防串章，切章后旧快照作废），结果进世界模型缓存回台秒弹可用；心跳响应带章节纪元守卫（发送后切章=旧章感知产物整包丢弃）；全量停机只随应用关闭发生。

## 领域档案索引（改代码前按需必读）

本文件是全局契约与速查；四大领域的完整细节已拆分为按需加载的档案，**动手改对应领域前必须先读**：

| 要动的领域 | 必读档案 | 施工/事故日志 |
|------------|----------|----------------|
| NLE-ADF：心跳/挂件 dock/stitch 续写/细纲胶囊/沉淀/完稿审计/意图感知/上下文装配/约束治理 | `docs/agent/nle-adf.md` | `docs/incidents/nle-adf.md` |
| 世界设定层：活舆图/事件溯源推演/时间轴/world_bridge/写作桥/真相层 Canon | `docs/agent/world.md` | `docs/incidents/world.md` |
| 文风页：指纹/样本库/负面清单/试衣间/语义扫描/章级特例卡 | `docs/agent/style.md` | `docs/incidents/style.md` |
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

**完整启动器契约见 `scripts/README.md`（编辑启动脚本/监控台前必读），事故史见 `docs/incidents/launcher.md`。**核心不变量：

- **三端契约自检 `scripts/check_launcher_contract.py`（CI 阻断步）**：端口段（后端 8002~8100 / 前端 5175~5285）与 electron npm script 名写在四份实现（两份编排 / python 监督者 / 前端 `transport/base.ts` 判定区间）里无法共享代码，由该脚本对拍防漂移；改端口段须同时改全部实现再改该脚本常量。
- **日志架构=文件为真相源**：读线泵直写 `logs/dev_backend.log`/`dev_vite.log`/`dev_electron.log`（每次启动重建）+ 启动器叙事进 `dev_sys.log`；控制台显示可弃，数据不丢。改 dashboard 协议字段须同步 `dev_dashboard.py` 的 `build_status`/`LINE_RE`/`FILES` 与 `data/dev_status.json` 消费面。
- **收摊/停止双闸**：只杀命令行含本项目路径的进程；状态 JSON 新鲜度闸 >120s 无心跳即跳过一切 JSON 衍生杀（`stop-velluma` 同）。DryRun 不写端口文件、不杀任何树/端口。
- **三模式统一 `electron:nobuild`**（loadURL/loadFile 由 NODE_ENV 决定，与构建无关）；图标单源 `frontend/electron/app-icon.png`（方形 PNG ≥256×256）。
- 子进程 stdin 一律切断（vite EPIPE 事故）；vbs 必须纯 ASCII+CRLF；pythonw 断"启动器+真解释器"两进程对链；改 start.ps1 防 .NET 方法调用参数位内联 `-f` 逗号坑（先求值到临时变量再传参）。

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
    ├── workflows/
    │   ├── adf/            # V3.2 ADF 引擎（自包含，前端无入口）：adf_workflow 主类 + 各 phase 模块 + 3 单测
    │   ├── conftest.py     # ★ autouse fixture，防 asyncio 事件循环污染（见"测试"节，勿删）
    │   ├── sentence_integrity.py  # 残句门禁 + repair_single_defect 单条修复（服务 /adaptive/fix-sentence）
    │   └── refining.py     # ★ 共享（前端在用，非废弃），服务 chapter_optimization 路由
    └── refinery/           # V4.1 独立精修（refinery/diagnostician/planner/surgeon/holistic_reader/polisher）

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
| ★ **NLE-ADF 3.0** | `/adaptive/heartbeat`+`/stitch-ghost`+`/settle`+`/finish`+`/fix-sentence`+`/spine`+`/spine-suggest`+`/model`+`/context-preview`+`/usage`+`/event`+`/constraints/summary` 等 | `adaptive/` 路由包 + `settings_bundle.py` + `adaptive_prompts.py` + `stitch_gates.py` | **前端默认**（作者主导写作+AI 柔性共生，无预设拍） |
| **BS-ADF** | （端点已摘除） | （已归档 `backend/_deprecated/bsadf/`） | **已归档 2026-08-19**（思想去向见 `_deprecated/README.md`） |
| ADF | `/generate-adf` | `ADFWorkflow`（`workflows/adf/`） | 引擎本体，前端已无 UI 入口 |
| ~~Refinery~~ | （已拔除 2026-09-12） | 手术原语迁 `services/text_surgery/`；读者反馈迁 `/adaptive/reader-feedback` | **整体退役** |
| 章节优化 | `/optimize_chapter`+`/optimize_selection` | `refine_draft`（`workflows/refining.py`） | 章节重写/局部优化（前端在用） |

### NLE-ADF 3.0 自适应融合写作台（前端默认且唯一写作路径）

作者主导打字 ≥4 字即激活（`authorLane=composing`），AI 柔性共生、不跑整章管线。**完整领域参考 `docs/agent/nle-adf.md`（编辑前必读）**，施工/事故史见 `docs/incidents/nle-adf.md`。核心不变量：

- 心跳 `/adaptive/heartbeat` → 挂件四槽位（landing/toward_beat/echo/ambient，拿不到出处即降级 ambient，**note 一律后端拼装不经 LLM**）；卡舱入口=Tab 唯一（`SPARK_DOCK_AUTO_POPUP=false`，Tab 恒 force_refresh 强制重算）；段落停在半句不生发不回缓存旧件且响应带 `dock_muted=true`（空段=段界不判半句，勿回退）。
- 续写 `/adaptive/stitch-ghost` 五模式（stitch/continue/burst/open/outline）；**追加式契约勿回退拼回**（幽灵纯追加在光标后，复读剥离 `_strip_fragment_prefix` + 接缝三护 `_split_first_sentence`/`_strip_fragment_tail_repeat`/`_strip_colliding_open_quote`）；FIM 中插桥接 `suffix_anchor`（光标后 ≤300 字后文锚，桥接态切断推测/方向猜测/就近节拍素材供给）；幽灵死亡收割 `reapGhostIfDead` 勿删。
- 「当前段落/已写内容」取源唯一权威 `services/adaptive/paragraph_source.py`（layer1_facts 只是沉淀审计账，**不得代替正文**进 prompt/审阅对象；`world_model.snapshot` 事实带派生活性只计活事实）。
- stitch 装配唯一入口 `services/context/stitch_context.py`，与 `GET /adaptive/context-preview` **同源共用（红线：禁止平行实现）**；注入序唯一权威 `adaptive_prompts.render_system_blocks`（事实层前于文风层）；专名称呼表按可见文本过滤（`scene_visibility.py`）；条目原子永不劈开，唯一体量约束=条目级逃逸阀 `KG_BUDGET_CHARS`。
- 约束治理：登记册 `services/constraints/registry.py` + ghost_guard 快检 + 缝合返修环 `services/validation/repair_loop.py`（用户拍板「可慢不可错」：检出→带稿改写→验收→句级切除→拒稿 GHOST_REJECT→熔断器 quality_breaker）；执法可靠性序=供给切断>输出代码闸>确定性改写>prompt 偏置>事后审计；信用分数据落 `data/constraint_events.jsonl` 不可补采。
- 沉淀 `/adaptive/settle` **纯手动** Ctrl+Enter；完稿审计 `/adaptive/finish`；意图三级源链（spine 打算 0.9 短路 > 大纲转化 0.85 > LLM 反推 0.55/0.4，dock/stitch 消费阈 0.5；意图衰老闸 `INTENT_STALE_CHARS=100`）。
- 协作埋点 `POST /adaptive/event` + `data/collab_events.jsonl`（本地零上报）；系统自己去读 `/adaptive/auto-read`（哈希幂等+每书每日 30 次预算闸）；学着闭嘴 `services/adaptive/quiet_learning.py` 唯一权威（静音集合行为派生不落库，安全类永不静音）。

### 世界设定层（World，★ 静态设定的唯一编辑源与生成数据源）

事件溯源式世界建模器：`world_events`（append-only 事实源，11 种事件类型）+ `world_entities`/`world_locations`（parent_id 树）/`world_relations` 折叠推演，活舆图单画布（Leaflet+编年史时间轴）。**完整领域参考 `docs/agent/world.md`（编辑前必读）**，施工日志 `docs/incidents/world.md`。核心不变量：

- 推演唯一权威 `compute_world_state_from_events` 纯函数，**前后端同构**（`features/world/engine/`，改任一侧必须同步）；生死语义「出场即活」（无 birth 事件但被回放的角色默认活、death 才死）。
- 生成桥接 `services/context/world_bridge.py`：世界页有实体即 world 优先（鸭子类型适配旧 Character/Asset 形状，`dynamic_state` 携带叙事时刻推演状态）；`visibility=private` 档案不进 prompt 文本、改入 secrets 通道（双轨纪律）；叙事时间四级降级；桥接失败/世界为空回退旧表（未迁移书行为不变）。
- 时间轴持久化红线：视野窗口浮点年 `[round((start-1)*365), round(end*365))`，合法性只看日空间非空（**勿改回 start<end**）；`PATCH /books/{id}/timeline-view` 必须携带 `{cursor, range}` 全量快照（服务端键级合并，分头发必丢键）；勿用 localStorage 存世界页状态（端口扫描换 origin 即漂移）。
- 写作桥：`GET /world/scene-slice`（此刻切片）、`GET /world/context-card`（情境浮卡）、`POST /world/parse-event`（Alt+N 速记，**解析/落库分离红线**——只产草稿绝不落库）、`GET /world/state-for-chapter/{id}`（在场推演）；光标派生场景 `services/world/active_scene.py`（`resolve_active_scene` 纯函数，接流四线）。
- 真相层：生成消费链 `[private]/[public]/[hook]` 三段格式**冻结不动**；字段级分层 `world_entities.field_layers` 五条消费线（对拍 `test_field_layers.py` + `fieldLayers.test.ts`）；因果图谱已退役但后端边表/CRUD 与 `/impact` 路由保留勿删。
- 运维工具：数据库卫生检测修复 `scripts/check_db_hygiene.py`（R1-R5 幂等，`--fix` 自动备份；剥 HTML 比对必须用 `html_to_plain` 唯一权威）；隐式图谱投影器 `services/world/implicit_graph.py` 暂无消费方（EventCard 超边永不展开 N² 点对，node_cap=40）。

### 文风页（Style）

作者笔迹独立工作台（`/style/:bookId`，`features/style/`），权威设计 `docs/style-paradigm.md`（三平面分权）/ `docs/style-module-redesign.md`。**完整领域参考 `docs/agent/style.md`（编辑前必读）**，施工日志 `docs/incidents/style.md`。核心不变量：

- **同一把尺子**：`services/style/fingerprint.py` 是句长切分/字数/CV/对话统计的规范实现，审计侧 `code_auditors.py` 从此 import；改任一侧统计口径先跑 `test_fingerprint.py`（19 项对拍锁定）。
- 负面清单四源唯一权威 `services/style/prohibitions.py`（`load_prohibition_set`：SystemCliche+negative_list+book_blacklist+静态反 AI 词表）；severity 两档 提醒/硬禁，硬禁只提示、**绝不自动改正文**。
- 零变化契约：无文风卡/无样本的书 prompt 逐字节不变（`test_style_injection.py` 锁定）；章级卡（`style_cards.chapter_id` 非空）= 该章**整卡覆盖**语义，统一入口 `StyleCardRepository.get_effective_card`。
- 语义扫描挂点**仅在** `/adaptive/finish`（`semantic_hits`），不进收件箱/scan-negative/任何 SSE 路径（红线）；阈值 0.78 未校准。
- 意图旋钮已退役（`style_knobs`/`dialogue_ratio_target` 冻结只读，`_selector_adjust` 已删）；文风收敛两根支柱 = 亲笔样本 few-shot（`style/retrieval.py`）+ 负面清单执法。
- 架构不变量=采纳线：线前可干预 AI 提案，线后作者文本永远只提示。

### deai 去 AI 味小模型（子项目，`deai/`）

自训「去AI味」改写小模型（百炼 SFT Qwen3-4B+LoRA；契约唯一权威 `deai/docs/contract.md`）。宿主集成唯一权威 **`docs/deai-integration.md`**，核心契约：

- 配置节 `model_config.json` 的 `deai`（enabled/api_key/model/base_url；**未配置=零调用、幽灵文本逐字节零变化**）；服务包 `backend/services/deai/`（`polish_fragment` 公共入口 + 契约§6 事实闸保底回退原文 + 宿主侧保名闸——kg 在场/死者名单中原文出现的实体名必须在改写稿逐字保留否则回退；`gates.py` 为运行时闸门移植副本，判据唯一权威在 `deai/scripts/validate_pairs.py`，改判据先改那边跑 `--selftest` 再同步）。
- 挂点 stitch-ghost 呈现平面（字数闸后、ghost_guard 快检前；≤100 字契约窗内短稿生效，burst/outline 长稿自动跳过；微镜头同窗旁路）；deai 不进 generation_runs 用量聚合，用量以 trace `deai_polish` 为准。
- 训练对收集（§5a 数据飞轮）：写作台选中浮窗「记改前/记改后」两步配对（`useDeaiPairMark` 模块单例暂存、6s 撤销）→ `POST /api/deai/pairs` → `data/deai_pairs.jsonl` → `deai/scripts/ingest_behavior_pairs.py` 去重+六闸 → `behavior_sft.jsonl`（合并进训练集须人工过目）；闸门执法全在入库侧，收集箱 `deai/data/inbox/`。v1 训练语料为产品/公告/观点类，叙事文本未训练。
- 设置弹窗「实验：去 AI 味小模型」折叠分区 + `POST /api/system/deai/test` 试一试（表单实时值，事实闸保底回退不算失败）。
- ⚠ 调用三要点（勿改）：DashScope **原生**端点（调优模型不走 OpenAI 兼容入口）/ model 填部署名（非 ft-ID）/ `enable_thinking=false`；超时 8s 挂死上限，超时即保底回退。

### ⚠ 后端运行/落库边界（编辑前必读）

1. **adaptive 观测已接**（`services/adaptive/observing.py`）：chapter 级常驻 RunRecorder（run_id=`adaptive_{chapter_id}`，per-chapter 锁 drain/restore 原子冲账防重复防丢账）；trace 按 chapter 单文件 `logs/trace_adaptive_{chapter_id}.jsonl` 追加；协作埋点本地 `data/collab_events.jsonl`（零上报）。**用量可见**：`GET /chapters/{id}/adaptive/usage` + `GET /books/{id}/adaptive/usage`（`routes/chapter_generation/usage.py`，generation_runs 纯聚合零写，stage 按组件拆账），insights「协作」面板消费。
2. **Refinery 已整体拔除（2026-09-12）**——同名不同实家族只剩 `workflows/refining.py`（章节优化 refine_draft）与 ADF `refiner.py`（Phase 6 补埋器）；`services/text_surgery/` 是 ADF 一致性守卫的手术原语新家。

### ⚠ thinking 关闭的正确姿势（`services/llm/client.py`）

要关 thinking 必须传 `reasoning_config=REASONING_DISABLED`（`{"reasoning":{"enabled":False}}`）。**传空 dict `{}` 无效**——`call_llm_with_usage` 里 `if reasoning_config:` 对 `{}` 为 falsy，推理模型回落服务端默认 thinking 开启，小预算调用必被吃光预算空输出。槽位配置 `enabled: false` 即显式关闭（`get_default_reasoning_config` 返回 REASONING_DISABLED 同形，不返回 None「不表态」）。**中间表示经 `reasoning_adapter.py` 按域名转厂商原生参数**；MiMo 实测只认 `thinking.type`，静默忽略 OpenRouter 的 `reasoning.enabled`（隐藏思考烧光预算，勿删该分支）。

**厂商能力档案（`services/llm/vendor_profiles.py` + `docs/model-vendor-matrix.md` 唯一事实源）**：①`shape_sampling_params` 在两条发送路径前置整形采样参数（Kimi K 系 schema 不含采样参数传了 400、DeepSeek 双 penalty 已废弃、GLM 温度上限 1.0、DeepSeek/MiMo 思考态采样静默无效）；`_PARAM_LOCK_CACHE` 400 自适应降级为最后防线。②强制思考模型收到「关闭」请求时适配层不发参数。③effort 白名单归一。④`GET /system/model-catalog` 喂前端设置弹窗。⑤模型配置预设：`model_config.json` 顶层 `presets` 节 + `GET/POST/DELETE /system/model-presets` + `POST /{id}/apply`；自动存档安全网 `maybe_capture_outgoing_slot`（对拍 `backend/core/test_model_presets.py`）。改档案先改 matrix 文档再改代码，跑 `test_vendor_profiles.py`。

### 关键质量护栏（事故根因，勿回退）

> 各护栏的事故经过见 `docs/incidents/nle-adf.md`；此处只留规则本体。已归档引擎（`_deprecated/bsadf/`）里的护栏仅作迁移取材，不随 live 代码演进。

- **字数硬闸门**：超 target×1.6 带压缩反馈重试，末次仍超句界截断到 target×1.5（截断上限必须 ≤1.6）；末段（结局段）豁免截断。**adaptive 现役形态**：outline 走保尾双闸（`_truncate_keep_tail`）；stitch/continue 走「保头截断 + 压缩改写」——超 ×1.6 先 `_truncate_at_sentence` 保头截到 ×1.5，截取稿发回模型按目标字数压缩改写；压缩产物仍超硬限对压缩稿再句界截一次，空产出回落截取稿（永不劣于纯截断）。**微镜头免压缩**：stitch 且 target ≤60（`MICRO_STITCH_TARGET_MAX`）超硬限保头句界截断即止、不走压缩改写，同窗旁路 deai 抛光与 P2 残留句级修补（残余禁词由 P1 洗层兜底）；先复读剥离后量配额。**burst/open 同进两级闸**（闸只抓 ×1.6 严重超产、正常浮动不碰）。**接缝三护**（勿回退）：①断点衔接首句豁免压缩——`_split_first_sentence` 把草稿首句物理摘出只压缩剩余，产物=首句+压缩稿（首句超 target×0.6 退整稿路径），压缩 prompt 带断点尾句坐标；②半句断点尾缀复读剥离 `_strip_fragment_tail_repeat`——断点非句末且产出以尾缀（≥2 规范化字符）开头即剥；句末断点不开此闸；③双开引号碰撞剥除 `_strip_colliding_open_quote`——断点=悬空开引号 × 幽灵以开引号起头则剥幽灵开引号（stitch/continue 双模式）。对拍 `test_stitch_gates.py`。
- **REFINE 完整性闸门**：补埋输出采纳前强制句末完整性校验，回退后丢失过半则整段放弃（宁缺勿残）。
- **enrich 幻觉闸门**：空种子禁自由扩写；剧情关键词/零接地双向过滤。
- **POV 名闸门**：状态卡已知 POV 角色时正文必须出现其名至少一次。
- **残句门禁与单条修复**（`workflows/sentence_integrity.py`，在役）：高精确度正则扫残句（宁漏勿误），`repair_single_defect` 定点修复（1×creative + REASONING_DISABLED + max_tokens=1600，批处理上限 5）——现服务 `/adaptive/fix-sentence`。
- **上屏前快检 ghost_guard（`services/validation/ghost_guard.py`）**：stitch-ghost 完整文本生成后、GHOST_DONE 前纯算法扫疑点，共十检。随 GHOST_DONE 上帧五类：①dead_speak 死者开口 ②canon_leak 泄底（private 标签）③secret_leak 私有短语外泄（含 3b 字段级扩展——字段分层档案的秘密/半露字段同判据）④cliche_hit 禁忌面命中 ⑤out_of_scene 人物不在场；**beat_rush 抢拍**（live+rewrite：幽灵字面复用大纲就近节拍措辞进返修环带稿改写，仅 stitch/continue 开，excise 不授权）；**shadow 四检只落台账**：location_jump 地点穿越 / cast_roll_call 名单演出 / mind_leak 思绪泄漏 / belief_leak 信念泄漏。前端感知带疑点条，local_only 由 registry status 驱动。**二期起不再是纯「只提示不拦截」**：repair 字段声明资格的约束（canon_leak/secret_leak/beat_rush=rewrite）进缝合返修环（检出→带稿改写→句级切除→拒稿不上屏）；无世界数据零报错契约不变。⚠ 零报错契约的反面教训：候选宇宙构造若对生产形态实体必抛异常被静默吞掉，整检会全灭数月不可见——**新检第一轮实测必须确认命中路径可达**。
- **状态卡抽取失败**：沿用旧卡显式记 `result.degraded`（不静默）；max_tokens=1600 兜底。

### RAG / 记忆流（`recall_memories`：默认流始终打底 + 向量流增强叠加）

唯一检索入口 `services/rag/recall.py` 的 `recall_memories`（消费方：stitch-ghost 五模式 k=3、dock_generator k=2，签名稳定），三层按质量序 `merge_echoes` 保序去重截 k：

- **A 结构化前情（始终）**：查询中出现的世界实体（名/别名匹配，≤4 个）× 叙事时刻之前（`resolve_narrative_time`）的 world_events，倒序取 3 条格式化为【前情事件·类型】（世界页无数据自动跳过）。**相关性门 `echo_is_relevant`**：实体名命中≠语境相关——事件与查询段 jieba 共享词（≥2 字）≥2 个或占比 ≥0.3 才放行；无及格事件允许 A 流为空（对拍 `test_recall_gate.py`）。
- **V 向量增强（embedding 已配置时叠加——不替换默认流，A/B 恒在）**：任意 OpenAI 兼容 Embedding 服务（`model_config.json` 的 `embedding` 节：`api_key`/`base_url`/`model` 默认 `text-embedding-v2`/`dimensions` 1536；`follow_llm=true` 时连接跟随文本模型槽——creative 优先、缺 Key 回退 reasoning；`base_url` 留空回退 DashScope 兼容端点；Key 来自 model_config 不读环境变量）；`search_similar` 权重（`repositories/memory_repository.py` 查询 + `services/generation/memory_scorer.py` 计分）：alpha 0.6（语义）/ beta 0.2（时间衰减）/ gamma 0.2（伏笔）/ lambda_decay 0.1。
- **B 词法检索（始终补足）**：`jieba.analyse` 抽关键词（top 8）→ `MemoryRepository.search_lexical`（SQL ILIKE 预筛 ≤60 候选 + Python 重排：`lexical.keyword_coverage` 命中计分单关键词封顶 3 次 + 开放伏笔章 +1 + 新近 tiebreak）。**检索分流去敏**：`mask_entity_names`/`bundle_mask_names` 把书级专名+注册别名（≥2 字）从查询抹除**只喂 V/B 流**（防高频主角名霸屏），A 流保原文（对拍 `test_recall_masking.py`）。
- **写路径**：完稿重索引（`memory_indexing`）/提取确认/发布摘要块——**块文本一律落库**，embedding 仅在已配置时生成（`is_embedding_configured()` 门控），未配置不再整块跳过。检索限当前章之前（防未来信息泄露），三层同规则。

---

## 数据库与迁移

**双路径（2026-08-19 起 SQLite 默认）**：不设 `DATABASE_URL` → SQLite 文件库 `data/velluma.db`（单机桌面零外部依赖；实现于 `backend/db_sqlite/`——`engine.py` WAL/外键/忙等 pragma 逐连接设置 + NullPool 防锁竞争，`type_compat.py` JSONB/Vector→SQLite 方言编译 + **UUID str 入参容忍补丁（⚠ 勿删：repo 惯约向 UUID 列传 str，PG+asyncpg 驱动层容忍，删此补丁 SQLite 下 world 查询全线 500）**，models 零改动；数据目录可用 `VELLUMA_DATA_DIR` 覆盖）。显式设 `DATABASE_URL=postgresql+asyncpg://…` → PG 原路径全保留（pgvector 向量记忆/连接池/维度迁移，专业级）。存量 PG→SQLite 一次性搬迁：`scripts/migrate_pg_to_sqlite.py`（PG 只读拓扑序，先对源库补齐 MIGRATIONS 缺失列再搬运，行数对照+外键校验）。

**启动时自动迁移**（非 Alembic）：`backend/database.py` 的 `MIGRATIONS` 列表定义增量列变更，`init_db()` 启动时自动补齐（SQLite 路径走 `db_sqlite/schema.py` 的 `init_db_sqlite`：建表+同源列迁移+legacy 数据迁移+种子化）。改 ORM 后须同步加 MIGRATIONS 条目，重启即应用。

⚠ **向量维度迁移破坏性**（仅 PG 路径）：启动时 `migrate_vector_dimension` 若 embedding 维度与库列不匹配会**删列重建**（清空全部向量数据）。切维度前注意。

连接池（仅 PG 路径；SQLite 走 NullPool 无池参数）：`pool_size=10`/`max_overflow=20`；`DB_POOL_PRE_PING` Windows 默认关（asyncpg+greenlet），其他平台默认开。PG 手动建表前需 `CREATE EXTENSION IF NOT EXISTS vector;`。

---

## 配置

### model_config.json（主要配置入口，已 gitignore）

LLM/Embedding/代理实际配置来源（schema 见 `backend/core/model_config.py`）：`llm.reasoning`/`llm.creative`/可选 `llm.wash`/`embedding`/`deai`（见 docs/deai-integration.md）/`proxy`/可选 `presets`（模型配置预设）/可选 `prices`（价目节，零默认价）。除手动编辑外可通过前端「API」弹窗（`ApiSettingsModal.vue`）经 `GET/PUT /api/system/model-config` 读写（GET 只回掩码，PUT 留空 api_key 表保持）。LLM/代理保存即时生效，embedding 维度变更需重启。**embedding 已降级为专业级**：设置面板默认折叠；未配置时记忆流走结构化+词法默认路径（见 RAG 节）。⚠ **当前工作区副本含真实 API Key，勿提交或外发**。

### 环境变量（.env 可选，仅以下几个实际生效）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DATABASE_URL` | 显式指定 PG 连接串（切回 PostgreSQL 专业级路径） | 无——**不设即默认 SQLite** `data/velluma.db` |
| `VELLUMA_DATA_DIR` | SQLite 数据目录（打包/便携场景覆盖 `data/`） | 项目根 `data/` |
| `DB_POOL_PRE_PING` | 连接池预检（仅 PG 路径；SQLite NullPool 不涉及） | Win=false / 其他=true |
| `VELLUMA_PORT` | 固定后端端口 | 无（默认 8002 起扫描） |

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

**UI 文案术语口径**：品牌隐喻词保留（幽灵草稿/蒸发、走向卡、清脂、卡舱/挂件/零件、收编、真相·表·里、此刻此地、黄金片段、这不像我、细纲胶囊、沉淀）；⚠「谋篇」「锚点」「岔路」已退出界面词（非作者语言）——上屏分别用「打算」「（非写不可的）情节/关键情节」「（可能的）发展/走向」，代码/文档概念名（spine、anchor、branch）可保留；工程黑话不上屏——用作者语言（完稿体检/检查报告、AI 从正文发现、秘密穿帮、前情记忆、样本统计、AI 用量 等）；英文残留除设置弹窗技术参数外不直接上屏；采纳动词统一「采纳」；埋点枚举键上屏须过 `InsightsView` 的 `COLLAB_KIND_LABELS` 映射。

---

## 测试

后端 pytest 1496 项（114 文件）+ 前端 vitest 368 项（43 文件）全绿（2026-09-17 基线，**测试怎么写/放哪/怎么跑/改码后更新哪些测试的唯一权威=`docs/testing-guide.md`**，含勿删清单与有意不测台账）。后端工作流测试均为纯算法/LLM-mock 单测（不连真实 LLM/DB）：`.venv\Scripts\python.exe -m pytest backend --ignore=backend/_deprecated -q`（必须 venv 解释器+排除归档）。GUI 测试证据截图不入库、一律本地留存。

- 前端 vitest **只收集 `src/**/__tests__/**`**——新测试文件必须放 `__tests__/` 目录，放别处会被静默跳过
- ADF：`workflows/adf/` 下 `test_consistency_guard`/`test_beat_patcher`/`test_state_tracker`
- `workflows/sentence_integrity.py` + `test_sentence_integrity.py`；`prompts/test_boundary_pacing_prompts.py`；`db_sqlite/test_db_sqlite.py`

⚠ **`workflows/conftest.py`（autouse）勿删**：每个测试结束重置全新 current event loop。存在原因——`IsolatedAsyncioTestCase` 与 `asyncio.run` 收尾会把事件循环策略 `_set_called` 置位且 current loop 置空，污染同进程后续 `asyncio.get_event_loop()`。跨多文件跑 pytest 时删除会随机失败。

**开发验证**：后端 `/api/health`；前端浏览器 DevTools + Vue DevTools；Prompt 日志 `logs/prompt_log_*.json`；生成全流程 trace `logs/trace_{run_id}.jsonl`（adaptive 流按章单文件 `logs/trace_adaptive_{chapter_id}.jsonl`）（JSONL 实时追加，含 run_start/阶段事件/每次 llm_call 的 system+user+响应+usage+延迟/final_text/run_complete；质量 debug 先按 run_id 定位文件再逐事件排查）。

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
- **改数据库模型**：`backend/models/` 对应领域子模块改 ORM（新表进对应模块；⚠ 同一 flush 新建父子表必须补 relationship 依赖边——flush 跨表排序按 relationship 而非裸 FK）→ `database.py` 的 `MIGRATIONS` 加列迁移 → 重启自动应用。
- **改 Prompt**：定位 `services/prompts/` 下文件，改后即时生效（无需重建），建议查 `logs/prompt_log_*.json` 验证。
- **前端加 Feature**：`features/` 建目录，按 `containers/`+`presentation/` 分层，经 `services/api/domain` 通信。
- **改四大领域前先读领域档案**：见顶部「领域档案索引」表（`docs/agent/*.md` + `scripts/README.md`）。

> 废弃/归档清单：`backend/_deprecated/`（V3.0 Detonation / V3.1 Unified / V4.0 DualTrack / BS-ADF 整引擎归档；另有 rag 检索器全家、V4.0 config 参数推导层、orchestration agentic/beat_manager、prompts 三件等死代码批量归档——静态可达性+消费方 grep 双验零运行路径，不参与 import 链，详见该目录 README）；`backend/_deprecated/docs/`（对应废弃引擎的设计文档归档）。

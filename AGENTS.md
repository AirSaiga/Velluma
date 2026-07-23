<!-- From: D:\qoder\Velluma\AGENTS.md -->
# Velluma AI 小说写作助手 - Agent 开发指南

## 项目概述

Velluma（原 StoryWeaver-Core）是一个 AI 驱动的长篇小说写作助手桌面应用。它采用 Agentic Workflow（智能体工作流）架构生成小说章节内容，当前实际生效的生成主流程为 V3.2 ADF 引擎 + V4.1 Refinery 精修（见下文"核心架构"）。

**核心价值主张：**
- 专为长篇小说创作设计的 AI 辅助工具
- 支持角色状态追踪、关系图谱、伏笔管理
- 基于 RAG（检索增强生成）的记忆系统
- 多 Agent 协作：规划 → 起草 → 统稿 → 对抗校对 → 精修

**许可证：** AGPL-3.0

---

## 技术栈

### 后端 (`backend/`)
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.109.0 |
| ORM | SQLAlchemy | 2.0.25 (异步) |
| 数据库 | PostgreSQL + pgvector | 14+（Python 侧 pgvector 0.2.4） |
| 驱动 | asyncpg | 0.29.0 |
| LLM | OpenAI SDK 1.10.0 / DashScope 1.14.1 | Embedding 仅使用 DashScope |
| 服务器 | Uvicorn | 0.27.0 |
| 其他 | pydantic 2.5.3, pydantic-settings 2.1.0, tenacity 8.2.3, python-dotenv, python-multipart | - |

> 注意：根目录 `requirements.txt` 仍残留 `pywebview==4.4.1`（桌面入口已删除，依赖未清理）；`backend/requirements.txt` 是第二份与根目录不一致的依赖清单（缺 python-multipart 等），以根目录为准。

### 前端 (`frontend/`)
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3 (Composition API) | ^3.4.15 |
| 语言 | TypeScript | ^5.9.3 |
| 构建 | Vite | ^5.0.12 |
| 样式 | Tailwind CSS | ^3.4.1 |
| 编辑器 | TipTap | ^2.24.0 |
| 桌面 | Electron | ^28.3.3 |

---

## 项目结构

```
Velluma/
├── start.bat                 # 兼容入口（转发到 scripts/start.ps1 -Mode dev）
├── scripts/                  # 启动脚本（生产/开发/调试三模式，详见 scripts/README.md）
│   ├── start.ps1             # 核心脚本：-Mode prod/dev/debug
│   ├── start-prod.bat        # 生产体验入口（npm run build + 载入 dist）
│   ├── start-dev.bat         # 开发入口（Vite + 自动开 DevTools）
│   └── start-debug.bat       # 调试入口（同 dev，预留扩展）
├── requirements.txt          # Python 依赖（含残留的 pywebview）
├── model_config.json         # LLM/Embedding/代理配置（含 API Key，已 gitignore，勿提交）
│
├── backend/                  # FastAPI 后端
│   ├── main.py              # 应用入口、路由注册、静态文件服务、CORS
│   ├── models.py            # SQLAlchemy ORM 模型（全部 14 个模型，含 GenerationTask）
│   ├── database.py          # 异步引擎、会话、启动时自动迁移（MIGRATIONS 列表）
│   ├── world_state_schemas.py
│   ├── models_generation_task.py  # ⚠ 死文件：GenerationTask 已并入 models.py，本文件零引用
│   ├── requirements.txt     # ⚠ 第二份依赖清单，与根目录不一致（以根目录为准）
│   ├── _archive/            # 归档代码（celery_version/：已被 services/generation/background_manager.py 取代）
│   │
│   ├── core/                # 核心基础设施
│   │   ├── config.py        # 端口持久化与扫描（8002~8100）、推理模型支持列表
│   │   ├── model_config.py  # 读取 model_config.json（LLM/Embedding/代理配置的实际来源）
│   │   ├── dependencies.py  # 仓储层依赖注入
│   │   └── exceptions.py
│   │
│   ├── config/              # V4.0 统一配置推导层
│   │   ├── derivation.py    # GenerationConfig 构建与推导
│   │   ├── intent_driven.py # 意图驱动配置
│   │   ├── engine.py
│   │   ├── mapper.py
│   │   ├── rules.py
│   │   ├── adapter.py
│   │   ├── intent_engine.py
│   │   ├── schemas/         # generation_config.py 等配置模型
│   │   └── PARAMETER_MAPPING.md  # 参数映射文档（注意：其中 AGENTIC_* 环境变量的描述已过时）
│   │
│   ├── routes/              # API 路由层（16 个模块，均在 main.py 注册）
│   │   ├── books.py
│   │   ├── chapters.py
│   │   ├── chapter_entities.py
│   │   ├── chapter_generation/        # ⚠ 包（非单文件）：章节生成 API（含 SSE 流式）
│   │   │   ├── __init__.py            #   路由合并入口；chapter_generation.py 旧单文件被本包遮蔽，已成死代码
│   │   │   ├── dual_track.py          #   双轨生成端点
│   │   │   ├── stream_handler.py      #   ★ 当前生成主流程的 SSE 编排器
│   │   │   ├── progress_tracker.py
│   │   │   └── checkpoint_manager.py
│   │   ├── chapter_optimization.py
│   │   ├── chapter_publishing.py
│   │   ├── characters.py
│   │   ├── relationships.py
│   │   ├── memories.py
│   │   ├── maps.py
│   │   ├── assets.py
│   │   ├── critique.py
│   │   ├── inspiration.py
│   │   ├── text_formatting.py
│   │   ├── system.py
│   │   └── intent_driven.py
│   │
│   ├── schemas/             # Pydantic 模型
│   │   ├── book.py, chapter.py, character.py, beat.py, generation.py
│   │   ├── memory.py, map.py, assets.py, world_state.py, enums.py
│   │   └── misc.py
│   │
│   ├── repositories/        # 数据访问层（Repository 模式）
│   │   ├── base.py
│   │   ├── book_repository.py
│   │   ├── chapter_repository.py
│   │   ├── character_repository.py
│   │   ├── memory_repository.py
│   │   ├── relationship_repository.py
│   │   ├── map_repository.py
│   │   ├── plot_ledger_repository.py
│   │   └── asset_repository.py
│   │
│   └── services/            # 业务逻辑层
│       ├── llm/             # LLM 调用封装、Embedding、代理
│       │   ├── client.py
│       │   ├── embedding.py    # 仅 DashScope SDK，Key 来自 model_config.json
│       │   ├── proxy.py
│       │   └── formatting.py
│       │
│       ├── context/         # 上下文加载服务（loader.py）
│       │
│       ├── generation/      # 生成服务入口
│       │   ├── chapter.py
│       │   ├── character_extraction.py
│       │   ├── inspiration.py
│       │   ├── memory_scorer.py
│       │   └── publish.py
│       │
│       ├── orchestration/   # 工作流编排辅助
│       │   ├── agentic.py   # ⚠ 已非编排器：现仅存参数解析与节拍预览辅助函数
│       │   ├── beat_manager.py
│       │   └── tier_mapper.py
│       │
│       ├── prompts/         # Prompt 模板库（21 个文件，含 1 个测试）
│       │   ├── planner_prompts.py
│       │   ├── draft_prompts.py
│       │   ├── review_prompts.py
│       │   ├── stitch_prompts.py
│       │   ├── scene_intent_prompts.py
│       │   ├── world_state_prompts.py
│       │   └── ...
│       │
│       ├── rag/             # RAG 检索系统（顶层约 17 个模块，下为主要的）
│       │   ├── retriever.py
│       │   ├── scoring.py
│       │   ├── context_assembly.py
│       │   ├── retrieval_orchestrator.py
│       │   ├── workflow_integration.py
│       │   ├── foreshadowing_*.py     # 伏笔检测/追踪
│       │   ├── retrieval_*.py         # 检索构建/分阶段/类型
│       │   ├── enhanced/
│       │   └── tests/        # ⚠ 仅剩 __pycache__，无 .py 源码
│       │
│       ├── state_machine/   # 角色状态机
│       │   ├── character_state.py
│       │   ├── character_state_machine.py
│       │   ├── character_state_factory.py
│       │   ├── character_state_types.py
│       │   └── relationship_state.py
│       │
│       ├── validation/      # 质检与修复（⚠ 当前无路由调用方，疑似遗留）
│       │   ├── chapter_reviewer.py
│       │   ├── chapter_repairer.py
│       │   ├── review_repair.py
│       │   ├── review_repair_types.py
│       │   └── pre_generation_checklist.py
│       │
│       ├── workflows/       # 工作流子阶段实现（顶层约 25 个文件，下为主要的）
│       │   ├── planning.py
│       │   ├── drafting.py            # Beat 起草（并发为硬编码 Semaphore(5)）
│       │   ├── drafting_prose.py
│       │   ├── drafting_prose_modules/
│       │   ├── stitching.py
│       │   ├── reviewing.py           # ⚠ 经典 review_draft/revision_plan，当前无路由调用方
│       │   ├── refining.py
│       │   ├── dual_track.py          # ★ 双轨主类 DualTrackWorkflow（顶层文件）
│       │   ├── sketch_generator.py    # SketchGenerator
│       │   ├── adversarial_aligner.py # AdversarialAligner（活跃流程使用本文件）
│       │   ├── clarification_agent.py
│       │   ├── drafting_core/         # 起草核心子模块
│       │   │   ├── prose_generation.py
│       │   │   ├── context/           # context_manager.py, state_updater.py
│       │   │   ├── quality/
│       │   │   ├── retry/
│       │   │   └── strategies/
│       │   └── dual_track/            # 双轨子模块包（经 importlib 从顶层 dual_track.py 导入主类）
│       │       ├── tracks/            # track_a.py, track_b.py
│       │       ├── alignment/         # 含一份重复的 adversarial_aligner.py（非活跃路径）
│       │       ├── config/
│       │       ├── fusion_refinement.py
│       │       └── stitching.py
│       │
│       ├── world/           # 世界状态服务
│       │   └── state_service.py
│       │
│       └── utils/           # 工具函数
│           ├── sse.py
│           ├── prompt_logger.py  # 生成 logs/prompt_log_*.json
│           ├── sanitizer.py
│           ├── timeout.py
│           └── logging.py
│
├── frontend/                 # Vue 3 前端
│   ├── package.json
│   ├── vite.config.js       # Vite 配置（/api 代理目标动态解析：VELLUMA_BACKEND_PORT → data/port.txt → 8002）
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   ├── electron/
│   │   ├── main.cjs         # Electron 主进程（启动后端、等待 Vite 端口就绪、窗口管理；不启动 Vite）
│   │   └── preload.cjs
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── style.css
│       ├── vite-env.d.ts
│       ├── components/      # 通用组件（⚠ 该层不受分层约束限制，部分组件直接 import services）
│       ├── composables/     # Vue 组合式函数
│       ├── extensions/      # TipTap 扩展
│       ├── features/        # 功能模块（分层架构）
│       │   ├── app/                   # 应用级容器（AppShell/AppRail/useAppStore，仅 containers/ 无 presentation/）
│       │   ├── chapter-editor/        # 章节编辑器
│       │   ├── asset-panel/           # 资产面板
│       │   ├── bible/                 # 圣经/设定集视图（StyleCardManager 等）
│       │   ├── canon/                 # Canon 脑图（作者脑中世界：private 设定/伏笔/关系）
│       │   ├── generation/            # 生成流程（useGenerationSession + GenerationFlowView/Stepper + Refinery UI）
│       │   ├── insights/              # 洞察视图（成本/质量报告）
│       │   ├── library/               # 书架
│       │   ├── novel-wizard/          # 小说创建向导（另有 composables/、types/）
│       │   ├── outline/               # 大纲视图
│       │   └── workspace/             # 写作台（WorkspaceView + InspectorPanel 三栏）
│       ├── services/        # 服务层
│       │   ├── api/domain/  # 业务语义 API 适配（单个约 470 行的 index.ts 聚合全部域 API + asset.api.ts）
│       │   ├── api/stream/  # SSE 流处理
│       │   ├── api/transport/ # 底层 HTTP 请求
│       │   └── domain/, stream/, transport/  # ⚠ 空壳残留目录（仅 export {}，重构遗留）
│       ├── shared/          # 共享资源
│       │   ├── types/
│       │   └── utils/
│       └── types/
│
├── data/                    # 运行时数据（端口持久化等，gitignore）
├── logs/                    # Prompt 日志（gitignore；backend/logs/ 下另有调试日志）
├── scripts/                 # 启动脚本副本（与根目录逐字节相同，但因 $PSScriptRoot 相对路径只能在根目录运行）
└── .venv/                   # Python 虚拟环境
```

---

## 运行与构建

### 环境要求
- Python 3.12+（开发机使用 3.13.5，见 `.python-version`）
- Node.js 18+
- PostgreSQL 14+（需启用 pgvector 扩展）

### 后端开发

```powershell
# 1. 激活虚拟环境
.venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置
# - LLM/Embedding/代理：编辑项目根目录 model_config.json（主要配置入口）
# - 数据库连接等少数变量：项目根目录创建 .env（见下文"环境变量"章节）

# 4. 启动开发服务器
python backend/main.py
# 默认端口: 8002，若被占用则自动扫描 8002~8100，实际端口写入 data/port.txt
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
# 固定端口: 5175（vite.config.js 中 strictPort: true）

# 类型检查
npm run typecheck

# 构建生产版本
npm run build

# 预览构建产物
npm run preview
```

### 桌面应用运行（推荐开发方式）

项目使用 **Electron** 作为桌面容器。主启动脚本 `scripts/start.ps1` 通过 `-Mode` 参数区分三种运行方式，启动 Electron 前脚本会设置 `VELLUMA_BACKEND_PORT`、`VELLUMA_FRONTEND_PORT`、`VELLUMA_SERVICES_READY` 环境变量供 `electron/main.cjs` 消费（生产模式额外设 `NODE_ENV=production`，使 `main.cjs` 载入 `dist/index.html` 而非 Vite dev server），并在退出时自动清理所有进程。

```powershell
# 开发模式（默认，根目录 start.bat 等价于此）
.\scripts\start-dev.bat
# 调试模式（当前等同 dev，预留扩展）
.\scripts\start-debug.bat
# 生产体验模式（npm run build + Electron 载入 dist）
.\scripts\start-prod.bat

# 强制模式（清理端口冲突后启动）
.\start.bat -Force

# 只启动 Electron（假设前后端已在运行）
.\scripts\start.ps1 -Mode dev -ElectronOnly

# 跳过后端启动
.\scripts\start.ps1 -Mode dev -SkipBackend

# 跳过前端 Vite 启动（dev 模式）/ 跳过 build（prod 模式）
.\scripts\start.ps1 -Mode dev -SkipFrontend

# DryRun：仅打印将执行的命令与路径，不启动进程
.\scripts\start.ps1 -Mode prod -DryRun
```

**Electron 独立命令（在 frontend 目录下）：**
```bash
cd frontend
npm run electron:dev      # 构建前端后启动 Electron（⚠ 与 electron:preview 内容完全相同）
npm run electron:preview  # 同上：均为 npm run build && electron .，不启动 Vite，需 5175 已有服务
npm run electron:build    # 打包安装包（electron-builder）
```

> 注意：`app.py`（pywebview 入口）在代码库中已不存在，README 中的相关描述已过时（README 仍有大量过时内容，如推荐 pywebview 启动、`AGENTIC_*` 环境变量等，请以本文档为准）。当前请以 `scripts/start.ps1` + Electron 为默认运行方式。

---

## 核心架构

### 章节生成主流程（现状）

> ⚠⚠⚠ **本节以下的双轨（V4.0）描述已过时，仅作历史记录保留。** 经 2026-07-22 前端清理后确认，前端实际消费的生成主流程为三条活跃链路：
> - **V3.2 ADF**（`POST /api/chapters/{id}/generate-adf`，默认引擎）：`ADFWorkflow`，阶段 SPINE_BUILDING → ANCHOR_DESIGN → TIER_DECIDE → FORWARD_FLOW → ANCHOR_AUDIT → (REFINE)，与双轨**零代码交叉**
> - **V3.1 统一引擎**（`POST /api/chapters/{id}/generate`）
> - **V4.1 Refinery 精修**（`/refinery/diagnose` + `/refinery/confirm`）
>
> 前端入口：`useGenerationSession.start()`（`engine` 默认 `'v3.2'`）→ `adfApi.streamGenerate`。V4.0 双轨（`/generate-chapter`）前端已无调用方。
> 双轨的后端代码仍存在但已 deprecated；下方双轨阶段描述不再反映现状（后端全面校准超出本次清理范围）。

**当前实际生效的生成主流程是双轨流**，编排代码位于：
- `backend/routes/chapter_generation/stream_handler.py` — SSE 流式编排（DualTrackStreamHandler）
- `backend/services/workflows/dual_track.py` — 双轨工作流主类（DualTrackWorkflow）

SSE 阶段序列：**ASSEMBLING_CONTEXT → POV_ASSIGNMENT → DRAFTING → STITCHING → REVIEWING → REFINING**

各阶段说明：

1. **ASSEMBLING_CONTEXT** - 组装上下文
   - 加载角色卡、关系网
   - RAG 检索相关记忆
   - 提取前文摘要和开放伏笔

2. **PLANNING** - 规划节拍（⚠ 不在生成主流程内）
   - 节拍规划已拆分为独立预览端点 `POST /api/chapters/{id}/generate_chapter_agentic_preview_beats`
   - 主流程中只有 POV_ASSIGNMENT（分配 POV 角色、字数）
   - 支持 Fast/Medium/Slow 节奏类型

3. **DRAFTING** - 并行起草
   - 每个 Beat 独立生成，并发度为 `drafting.py` 中**硬编码的 `asyncio.Semaphore(5)`**
   - ⚠ 文档与 README 中提到的 `AGENTIC_BEAT_CONCURRENCY` 环境变量**在代码中不存在**；`beat_concurrency` 配置字段（默认 6）定义于 `config/schemas/generation_config.py` 但无任何消费方
   - 包含 Scene Intent 构建和自动质检

4. **STITCHING** - 统稿
   - 合并所有 Beat 内容为完整章节草稿（Draft_A）

5. **REVIEWING** - 对抗校对
   - 双轨流程中由 `AdversarialAligner` 对比 Draft_A 与 Sketch，输出 `adjustment_plan`
   - ⚠ 经典实现 `workflows/reviewing.py`（`review_draft` + `revision_plan`）目前**无路由调用方**

6. **REFINING** - 精修（可选）
   - 基于对抗校对结果重写/融合
   - 支持跳过（`not_needed_or_disabled` / `no_gaps`）

> **关于多轮迭代**：schema 中 `max_iterations` 允许 1~5（默认 2），但当前双轨实现中迭代次数**硬编码为 1**，`max_iterations` 解析后仅写入元数据、无实际消费方。"最多 5 轮迭代"是设计上限而非现状。

### 双轨对抗架构 (V4.0)

为解决并行生成连贯性差的问题，引入双轨架构：

**核心思想**：并行生成 + 连贯性锚定

```
Track A: 节拍扩写              Track B: 短文生成
├─ Beat[1] → Text[1]           ├─ 基于 Beats 生成连贯速写
├─ Beat[2] → Text[2]           │   (默认约 45% 字数，连续叙述)
└─ Beat[N] → Text[N]           └─ 输出: Sketch + 转折点映射
         ↓                              ↓
         └──────────┬────────────────────┘
                    ↓
            统稿 → Draft_A
                    ↓
            对抗校对 (Adversarial Alignment)
            Draft_A vs Sketch → 差异检测 (adjustment_plan)
                    ↓
            融合精修 (可选)
```

**关键组件**：
- `DualTrackWorkflow`：双轨主类，位于 `backend/services/workflows/dual_track.py`（顶层文件）；同名包 `workflows/dual_track/` 通过 importlib 从该文件延迟导入，子模块包括 `tracks/`（track_a/track_b）、`alignment/`、`config/`、`fusion_refinement.py`、`stitching.py`
- `SketchGenerator`：`backend/services/workflows/sketch_generator.py`，生成连贯速写（`sketch_ratio` 默认 0.45），提供连贯性锚点
- `AdversarialAligner`：`backend/services/workflows/adversarial_aligner.py`（活跃路径；包内 `dual_track/alignment/adversarial_aligner.py` 有一份重复副本，非活跃）

**API 端点**（位于 `backend/routes/chapter_generation/dual_track.py`）：
- `POST /api/chapters/{id}/generate-dual-track` - 流式双轨生成（SSE）
- `POST /api/chapters/{id}/generate-dual-track-simple` - 非流式

### 数据模型层级

```
Book (书籍)
├── Chapter (章节)
│   ├── StoryBeat (剧情节拍) - 最小剧情单元
│   ├── SceneIntent (场景意图) - Beat 内的生成指令
│   ├── ChapterEntity (章节-角色关联)
│   ├── ChapterMapLocation (章节-地点关联)
│   └── ChapterAsset (章节-资产关联)
├── Character (角色)
│   ├── static_prompt - 永恒设定
│   ├── dynamic_state - 瞬时状态
│   ├── dynamic_state_history - 状态历史
│   └── CharacterRelationship (角色关系)
├── MapLocation (地图地点)
├── Asset (全局资产/道具)
├── MemoryChunk (向量记忆)
├── PlotLedger (情节账本/伏笔)
└── GenerationTask (异步生成任务，定义于 models.py)
```

以上 14 个模型均定义于 `backend/models.py`。⚠ `backend/models_generation_task.py` 中有一份同名同表的 `GenerationTask` 重复定义，但该文件全代码库零引用，是死文件。

### RAG 记忆检索

Embedding 当前**仅使用 DashScope SDK**（默认模型 `text-embedding-v2`；v3/v4 支持自定义维度），默认生成 **1536 维**向量（维度可在 `model_config.json` 的 `embedding.dimensions` 配置）。API Key 来自 `model_config.json` 的 `embedding.api_key`，**不读环境变量**。代码已不使用 OpenAI embedding（仅在历史注释中出现）。

检索权重参数（`backend/services/rag/scoring.py`）：
- **alpha**: 语义相似度权重 (默认 0.6)
- **beta**: 时间衰减权重 (默认 0.2)
- **gamma**: 剧情伏笔权重 (默认 0.2)
- **lambda_decay**: 时间衰减系数 (默认 0.1)

检索范围限制在当前章节之前（`exclude_chapter_id=当前章`、`max_chapter_number=当前-1`），避免未来信息泄露。

---

## 数据库与迁移

项目使用**启动时自动迁移**（非 Alembic）。`backend/database.py` 中的 `MIGRATIONS` 列表（约 50 条）定义了所有增量列变更，启动时会通过 `init_db()` 自动检查并添加缺失列。

⚠ **向量维度迁移**：启动时还会执行 `migrate_vector_dimension`——若 `model_config.json` 中的 embedding 维度与数据库现有向量列维度不匹配，会**删列重建**（破坏性操作，清空全部向量数据）。切换 embedding 模型/维度前请注意。

**手动执行 SQL 迁移：**
```sql
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;
```

**连接池配置**：
- `pool_size=10`, `max_overflow=20`
- Windows 默认关闭 `pool_pre_ping`（asyncpg + greenlet 兼容性）
- 其他平台默认启用，避免空闲连接失效

---

## 代码规范

### Python 后端

**文件头**：所有 `.py` 文件应包含 AGPL-3.0 许可证头（新文件必须添加）。⚠ 现状：backend 下约 1/5 文件（44/207）缺失，主要集中在较新模块 `routes/chapter_generation/`、`workflows/drafting_core/`、`workflows/dual_track/` 及 assets 相关文件。

**文档字符串规范**：
```python
"""
简短功能描述。

职责：说明模块的核心职责
业务场景：何时使用
主要功能：关键能力列表
依赖项：外部依赖
使用方式：代码示例

Args:
    param: 参数说明

Returns:
    返回值说明

Raises:
    Exception: 异常情况
"""
```

**注释风格**：
- 模块顶部使用 `====` 或 `----` 分隔线划分段落
- 关键逻辑前添加设计意图注释
- 副作用必须标注 `副作用：` 或 `警示：`

**错误处理**：
- LLM 调用使用 tenacity 进行指数退避重试
- 流式输出错误时发送 error 帧 + done 帧
- Windows asyncio 无害连接错误已在 `main.py` 中注册静默处理器

### TypeScript 前端

**分层架构约束**：

```
features/*/containers   → 状态整合、事件编排
features/*/presentation → 渲染、交互事件抛出
services/api/domain     → 业务语义 API 适配
services/api/stream     → SSE 流处理
services/api/transport  → 底层 HTTP 请求
shared/types            → 跨模块类型
shared/utils            → 纯函数工具
```

**依赖方向**：
- ✅ `presentation -> 容器 props/emits`
- ✅ `containers -> services/api/domain`
- ❌ `presentation -> services/api/transport` (禁止)
- ❌ `presentation -> services/api/stream` (禁止，见 `features/README.md`)

该约束在 features/ 内执行良好；⚠ 通用组件层 `components/` 不受此约束，现状有部分组件直接 import services。

**命名规范**（现状存在少量偏差，新代码请遵守）：
- Feature 目录: `kebab-case`
- 容器组件: `*Container.vue`
- 展示组件: `*View.vue` 或 `*Panel.vue`（弹窗组件实际大量采用 `*Modal.vue`）

**现状备注**：
- `features/app/` 只有 containers/ 没有 presentation/；`novel-wizard/` 另有 composables/、types/ 子目录
- `features/` 下已无聚合 `index.ts`（死桶已删）；各 feature 的公共接口导出约定执行不一致
- `services/` 顶层残留 `domain/`、`stream/`、`transport/` 三个空壳目录（仅 `export {}`，重构遗留），实际代码均在 `services/api/` 下

---

## 配置与环境变量

### model_config.json（主要配置入口）

LLM、Embedding、代理的实际配置来源是项目根目录的 `model_config.json`（schema 见 `backend/core/model_config.py` 的 docstring）：

- `llm.reasoning` / `llm.creative`：provider、api_key、base_url、model、enabled、effort 等
- `embedding`：api_key、model、dimensions（默认 1536）
- `proxy`：enabled、url

该文件除手动编辑外，也可通过前端**设置面板**修改：编辑器右侧悬浮工具栏「设置」标签（`frontend/src/components/SettingsPanel.vue`），经 `GET/PUT /api/system/model-config`（`backend/routes/system.py`）读写；GET 对 API Key 只返回掩码，PUT 中 api_key 留空表示保持不变。LLM/代理保存后立即生效（每次调用实时读取），embedding 维度变更需重启后端（触发删列重建）。

⚠ 该文件已 gitignore，但**当前工作区副本含有真实 API Key**，请勿提交或外发工作区快照。

### 环境变量（.env，可选）

后端代码实际读取的环境变量仅有以下几个（项目无 `.env.example` 模板）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver` |
| `DB_POOL_PRE_PING` | 连接池预检 | Windows=false / 其他平台=true |
| `VELLUMA_PORT` | 指定后端端口（跳过自动扫描） | 无（默认 8002 起扫描） |
| `PROXY_URL` / `DISABLE_PROXY` | ⚠ 半死代码：模块级常量定义后未被使用，实际代理由 `model_config.json` 的 `proxy` 节决定 | `http://127.0.0.1:4780` |

⚠ **以下变量在代码中不存在，文档/README 中的相关描述均已过时**：
- ~~`AGENTIC_BEAT_CONCURRENCY`~~（Beat 并行度实为 `drafting.py` 硬编码 `Semaphore(5)`）
- ~~`AGENTIC_FORCE_FAST_MODE`~~（快速模式是请求级参数 `fast_mode`）
- ~~`DASHSCOPE_API_KEY`~~ / ~~`OPENAI_API_KEY`~~（API Key 全部来自 `model_config.json`，不读环境变量）

另：`scripts/start.ps1` 会为 Electron 进程设置 `VELLUMA_BACKEND_PORT` / `VELLUMA_FRONTEND_PORT` / `VELLUMA_SERVICES_READY`，生产模式额外设置 `NODE_ENV=production`，属进程内传递，无需用户配置。

---

## 测试策略

### 当前状态
项目处于快速迭代期，**测试覆盖非常有限**。主要测试方式以手动验证为主。

**已有测试（现状）**：
- ⚠ ~~前端组合式函数测试 `npm run test:agentic-config`~~ — **已失效**：其引用的源码与测试文件在重构（commit fbdd5e1）中被删除，`frontend/scripts/` 现为空目录，frontend 全仓无任何 `*.test.*` / `*.spec.*` 文件，该命令运行必然失败
- ⚠ ~~后端 RAG 集成测试 `backend/services/rag/tests/`~~ — 目录仅剩 `__pycache__`，无 .py 源码
- Prompt 边界测试：`backend/services/prompts/test_boundary_pacing_prompts.py`（现存唯一的测试源文件）

**开发时验证**：
- 后端：使用 `/api/health` 健康检查
- 前端：浏览器开发者工具 + Vue DevTools
- LLM: Debug Prompt 窗口显示所有发送的 Prompt（`logs/` 目录保留历史，由 `services/utils/prompt_logger.py` 生成）

**添加新测试的建议位置**：
- 后端：在对应模块的 `tests/` 子目录中创建
- 前端：在 `frontend/` 下创建与源码平行的测试文件

---

## 部署与打包

### 桌面应用打包

使用 `electron-builder` 配置在 `frontend/package.json` 中：

```json
{
  "build": {
    "appId": "com.velluma.app",
    "productName": "Velluma AI",
    "directories": { "output": "dist-electron" },
    "files": ["dist/**/*", "electron/**/*", "../backend/**/*"],
    "extraResources": [{ "from": "../backend", "to": "backend" }],
    "win": { "target": "nsis" },
    "mac": { "target": "dmg" },
    "linux": { "target": "AppImage" }
  }
}
```

打包命令：
```bash
cd frontend
npm run build        # 构建前端
npm run electron:build  # 打包 Electron 安装包
```

### 后端静态文件服务

FastAPI 在 `backend/main.py` 中已配置 SPA fallback：
- `/` → `frontend/dist/index.html`
- `/api/*` → 404（防止误匹配）
- 其他路径 → 先尝试静态文件，不存在则 fallback 到 `index.html`

这意味着构建后的前端可以与后端合并部署。

### 注意事项
- 项目**无 Docker 配置**
- 项目**无 CI/CD 流水线配置**
- 端口协商机制（`data/port.txt`）仅适用于本地开发，生产环境应使用固定端口（可用 `VELLUMA_PORT` 指定）

---

## 安全注意事项

1. **API Key 处理**
   - LLM / Embedding 的 API Key 全部来自项目根目录 `model_config.json`（已 gitignore），**不读环境变量、不存数据库**
   - 日志中不应打印完整的 API Key
   - ⚠ 当前工作区的 `model_config.json` 含有真实可用的 Key，请勿提交或外发

2. **代理配置**
   - 默认本地代理 `http://127.0.0.1:4780`，实际由 `model_config.json` 的 `proxy` 节控制
   - `PROXY_URL` / `DISABLE_PROXY` 环境变量为半死代码（定义后未被使用）

3. **CORS 策略**
   - ⚠ 当前**无条件** `allow_origins=["*"]` 且 `allow_credentials=True`（代码中无环境区分），生产部署必须收紧为具体域名列表

---

## Agent 开发速查

### 添加新的 API 端点

1. 在 `backend/schemas/` 定义 Request/Response 模型
2. 在 `backend/routes/` 创建/修改路由文件（注意 `chapter_generation` 是包结构，在包内添加模块并在 `__init__.py` 合并）
3. 在 `backend/main.py` 注册路由（如尚未注册）
4. 前端在 `frontend/src/services/api/domain/` 添加对应调用

### 修改数据库模型

1. 在 `backend/models.py` 修改 ORM 定义
2. 在 `backend/database.py` 的 `MIGRATIONS` 列表中添加对应列迁移
3. 重启后端即可自动应用

### 修改 Prompt 模板

1. 定位到 `backend/services/prompts/` 下对应文件
2. 修改后可直接生效（无需重新构建）
3. 建议同时检查 `logs/prompt_log_*.json` 验证输出

### 前端添加新 Feature

1. 在 `frontend/src/features/` 创建目录结构
2. 按 `containers/` + `presentation/` 分层
3. 在 `index.ts` 导出公共接口
4. 通过 `services/api/domain` 层与后端通信

---

*最后更新: 2026-07-19（全面校准：修正路由结构、双轨工作流现状、环境变量、配置来源、测试现状等过时内容）*

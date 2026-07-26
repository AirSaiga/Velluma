<!-- From: D:\qoder\Velluma\AGENTS.md -->
# Velluma AI 小说写作助手 - Agent 开发指南

## 项目概述

Velluma（原 StoryWeaver-Core）是一个 AI 驱动的长篇小说写作助手桌面应用。它采用 Agentic Workflow（智能体工作流）架构生成小说章节内容，当前实际生效的生成主流程为 V3.2 ADF 引擎 + V4.1 Refinery 精修（见下文"核心架构"）。

**核心价值主张：**
- 专为长篇小说创作设计的 AI 辅助工具
- 支持角色状态追踪、关系图谱、伏笔管理
- 基于 RAG（检索增强生成）的记忆系统
- ADF 引擎（锚驱动正向流）：脉络骨架 → 锚点设计 → 定档 → 正向逐段写作 → 重构剪枝 → 锚点审计 → 条件补埋
- Refinery 独立精修：诊断 → 作者确认 → 外科手术 → 整体回读 → 抛光

> **引擎现状（2026-07-24 剥离后）**：当前仅保留两套生成引擎 —— V3.2 **ADF**（默认，`/generate-adf`）与 V4.1 **Refinery**（独立精修，`/refinery/*`）。V3.0 Detonation、V3.1 Unified、V4.0 DualTrack 三套引擎已整体迁至 `backend/_deprecated/`（详见该目录 README），不再参与任何 import 链。本文档所有描述均以剥离后的现状为准。

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
│   │   ├── chapter_generation/        # 章节生成 API 包（含 SSE 流式）；剥离后仅 ADF + Refinery
│   │   │   ├── __init__.py            #   路由合并入口（注册 adf/refinery router + extra_router）
│   │   │   ├── adf.py                 #   ★ V3.2 ADF 引擎端点（/generate-adf，默认引擎，含 SSE）
│   │   │   └── refinery.py            #   V4.1 Refinery 精修端点（/refinery/diagnose + /confirm）
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
│       ├── workflows/       # 工作流实现（剥离后：adf/ 包 + refinery/ 在 services/ 顶层 + 共享设施）
│       │   ├── adf/                   # ★ V3.2 ADF 引擎（当前默认生成引擎，自包含）
│       │   │   ├── adf_workflow.py    #   ADFWorkflow 主类（Phase 1~7 编排，详见"核心架构"）
│       │   │   ├── story_context_builder.py  # Phase 1 脉络骨架（纯算法）
│       │   │   ├── climax_designer.py #   Phase 2 锚点设计（1×reasoning LLM）
│       │   │   ├── tier_classifier.py #   Phase 3 定档算法（原 detonation 包，随剥离迁入）
│       │   │   ├── tier_decider.py    #   Phase 3 定档薄包装（映射 tier→字数/段数）
│       │   │   ├── segment_writer.py  #   Phase 4 正向逐段写作（N×creative LLM 串行）
│       │   │   ├── storyboard.py      #   V4.3 分镜景别（纯算法）
│       │   │   ├── setting_resolver.py#   V3.5 设定/世界观文本召回（纯算法）
│       │   │   ├── pruner.py          #   Phase 4.5 重构剪枝（N+1×creative，去 AI 味）
│       │   │   ├── structure_checker.py # Phase 5 锚点审计（1×reasoning LLM）
│       │   │   ├── refiner.py         #   Phase 6 条件补埋（0~3×creative）
│       │   │   ├── name_registry.py   #   Phase 7 专名注册表 + 零LLM漂移回扫（纯算法）
│       │   │   ├── dedup_guard.py     #   剧情回路护栏（段级相似度 + 全文重复块清除）
│       │   │   ├── state_tracker.py   #   Agent Loop 1 剧情状态卡（每段 1×小 creative 抽取 + 状态矛盾闸门）
│       │   │   ├── beat_patcher.py    #   Phase 6.5 大纲节拍覆盖校验 + 定点补写
│       │   │   ├── consistency_guard.py # Phase 7 一致性守卫（1×reasoning 审计 + 0~3×creative 手术 + 复验回滚）
│       │   │   ├── test_consistency_guard.py # Phase 7 单测（42 用例）
│       │   │   ├── test_beat_patcher.py #   Phase 6.5 单测（16 用例）
│       │   │   ├── test_state_tracker.py #  Loop 1 单测（15 用例）
│       │   │   └── types.py
│       │   ├── planning.py            # 节拍拆分 + POV 锚点分配（共享编排层，被 agentic/beat_manager 用）
│       │   ├── refining.py            # refine_draft/refine_single_beat（服务于 chapter_optimization 路由）
│       │   ├── clarification_agent.py # 大纲澄清（extra_router 的 /clarify-outline 端点）
│       │   ├── snapshot_extractor.py  # 世界终端状态抽取（chapter_publishing 用）
│       │   ├── state_validator.py     # 节拍世界状态一致性校验（planning/agentic 用）
│       │   ├── context_blocks.py      # 上下文区块构造（context/engine 用）
│       │   ├── formatting_utils.py    # 规则化文本格式（text_formatting/llm 用）
│       │   ├── validators.py          # 代码级校验器（validation/code_auditors 用）
│       │   └── utils.py               # clean_llm_output 等（多模块共用）
│       │
│       ├── refinery/         # ★ V4.1 Refinery 独立精修流水线（对任意草稿，非内嵌生成）
│       │   ├── refinery.py            # Refinery 主类（编排 diagnose/refine）
│       │   ├── diagnostician.py       # 诊断（1×reasoning，输出问题清单 JSON）
│       │   ├── planner.py             # 手术规划（纯算法）
│       │   ├── surgeon.py             # 局部手术（N×creative，定点改段落）
│       │   ├── holistic_reader.py     # 整体回读（1×reasoning）
│       │   ├── polisher.py            # 全文抛光（1×creative）
│       │   └── reader_feedback.py
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
├── _deprecated/             # ⚠ 废弃引擎归档（不参与 import 链，详见该目录 README）
│   │                        #   含 V3.0 Detonation / V3.1 Unified / V4.0 DualTrack 全部代码
│   ├── services/workflows/  #   detonation/ 包、dual_track.py + dual_track/ 包、sketch/adversarial/
│   │                        #   stitching/drafting/fortress_candidate/fail_fast 等
│   ├── routes/chapter_generation/  # dual_track.py/detonation.py/unified.py/stream_handler 等
│   ├── services/prompts/    #   detonation_prompts.py、stitch_prompts.py
│   ├── schemas/detonation.py
│   └── repositories/detonation_repository.py
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

### 章节生成引擎（剥离后现状）

当前后端仅保留两套生成引擎，外加一套独立的章节优化功能。三套引擎各有独立的工作流类与精修实现，**互不共享编排代码**（底层 LLM/观测/RAG 设施共用）：

| 引擎 | 版本 | 端点 | 工作流主类 | 用途 |
|------|------|------|-----------|------|
| **ADF** | V3.2 | `POST /generate-adf` | `ADFWorkflow`（`workflows/adf/`） | 默认生成引擎（从头写章节） |
| **Refinery** | V4.1 | `/refinery/diagnose` + `/confirm` | `Refinery`（`services/refinery/`） | 独立精修工具（对任意草稿，需作者确认） |
| 章节优化 | — | `/optimize_chapter` + `/optimize_selection` | `refine_draft`（`workflows/refining.py`） | 章节重写/局部优化（前端在用） |

> 已废弃并迁至 `backend/_deprecated/` 的引擎：V3.0 Detonation（`/generate-v3`）、V3.1 Unified（`/generate`）、V4.0 DualTrack（`/generate-chapter`）。它们的设计文档见 `docs/generation-v3-design.md`、`docs/generation-v3.1-unified.md`，均带废弃头注。

### ADF 引擎（V3.2，默认生成引擎）

**核心思想**：锚驱动正向流（Anchor-Driven Flow）。先设计"远端锚"（本章高潮 + 必埋/必收的钩子前置条件），再正向逐段写作逼近锚点，最后审计锚点是否达成、条件性补埋。全程**严格串行**（无并行段）。

编排主类 `ADFWorkflow` 位于 `backend/services/workflows/adf/adf_workflow.py`，入口路由 `backend/routes/chapter_generation/adf.py`。

**阶段序列**（Phase 1~7，含 PRUNE 与 CONSISTENCY_GUARD 两个后补阶段）：

1. **CONTEXT_ASSEMBLING**（0 LLM，路由层 `_load_adf_context`）— 组装 chapter/entities/open_hooks/上一章摘要 + Canon 上下文 + 世界观文本。
2. **SPINE_BUILDING**（0 LLM，`story_context_builder.py`）— 纯算法拆钩子为 must_plant/must_resolve，按"每 12 章一卷"推断卷位。受 `enable_spine` 开关控制。
3. **ANCHOR_DESIGN**（1×reasoning LLM，`climax_designer.py`）— 设计高潮强度 + 每个钩子的前置条件（Precondition）。Canon/作者意图作为最高约束前置注入。
4. **TIER_DECIDE**（0 LLM，`tier_decider.py` → `tier_classifier.py`）— 定档 climax/turn/progress/transition，映射到目标字数与段数（climax=5000字/7段，turn=3500/6，progress=2500/5，transition=1500/4）。
5. **FORWARD_FLOW**（N×creative LLM **串行**，`segment_writer.py`）— 逐段正向写作，每段含情绪采样/条件扫描/镜头景别注入，写完做三道反 AI 味后处理（jieba 抽脂 → AI 味检测超阈值则 LLM 重洗 → 正则裁剪）。写到超目标×1.3 提前终止。**统一段级闸门（Agent Loop 1）**：每段定稿前跑零 LLM 闸门链（闸门 1 剧情回路=与前段相似度；闸门 2 状态矛盾=与剧情状态卡冲突，仅 `enable_state_tracker` 开启时），任一违规合并 note 重写一次，仍违规弃段记降级。段定稿后抽取剧情状态卡（`state_tracker.py`，每段 1×小 creative，输出在场/死亡离场/角色状态/物品/进展 JSON，注入下一段硬约束区块；末段不抽）。
6. **PRUNE**（N+1×creative LLM，`pruner.py`，⚠ 全章无条件触发，无开关）— 逐段重构剪枝（去 AI 味，"重构"而非"润色"路线）+ 整章 OOC 裁判（角色崩坏检测），判崩坏则整章回退未剪枝文本。**此前文档遗漏此阶段，它占 ADF 单章 LLM 调用量近一半。**
7. **ANCHOR_AUDIT**（1×reasoning LLM，`structure_checker.py`）— 代码级扫必须出现的词 + LLM 5 维审计（铺垫落地/情绪/脉络/高潮验收/文风）取并集。受 `enable_anchor_audit` 开关控制。
8. **REFINE**（0~3×creative LLM，`refiner.py`）— 条件补埋，仅当 `enable_refinement=True` 且审计判 `needs_refinement` 时触发，挑情绪平淡段内嵌补写漏掉的伏笔。
8.5. **BEAT_PATCH**（0~2×creative LLM，`beat_patcher.py`）— 大纲节拍补写。Phase 5 审计第 6 维逐节拍核对 `outline_text` 覆盖（代码级 jieba 预判仅作 suspect 提示），`status=missing` 且带锚引文的节拍做定点插入补写（150~400 字过渡段，引文锚定位置，伪锚/超长/抄邻段均降级为只上报）。受 `enable_beat_coverage` + `enable_refinement` 开关控制。
9. **CONSISTENCY_GUARD**（1×reasoning + 0~3×creative LLM，`consistency_guard.py` + `name_registry.py`）— 设定一致性守卫。第 0 步先做全文重复块清除（`dedup_guard.py`，防剧情回路，写作循环内另有段级相似度护栏，重复则重写一次、仍重复降级空段）；再零 LLM 回扫专名漂移/未注册人名（`scan_name_anomalies`，等长替换+≥2 次阈值降误报）；再 1×reasoning 全文审计四类问题（name_drift/knowledge_breach/setting_conflict/state_contradiction，每条必须引 canon_evidence 否则代码侧丢弃）；最后复用 Refinery 手术通道定点修复（上限 3 个 operation，带 must_use_terms/长度/专名三重安全网）。**手术复验（Agent Loop 2，`enable_edit_verify` 开关）**：应用后先代码级查手术是否引入重复（命中直接回滚），再 1×reasoning 复验改动段±邻段（`adf.edit_verify`），判引入新问题的手术从原始段落重 apply 时剔除（回滚即终态不再修；无 problems 描述的 not-ok 视为 ok 防误杀）。受 `enable_consistency_guard` 开关控制（默认开）。写作期（Phase 4）配套零成本防线：每段 user prompt 尾部注入专名表硬约束 + 知识边界否定约束（private/隐藏关系）+ 在场角色提示；关系召回过滤 `is_public=False`（改走隐藏约束）；Canon 第 2 段起保留 public 事实完整行（`segment_writer.py`）。

**SSE 流式**：阶段进度事件实时流出；正文**非实时流**（工作流全部完成后才把 `final_text` 切成 200 字 chunk 输出）。

**阶段开关**（`schemas/adf.py` 的 `GenerateADFRequest`）：`enable_spine` / `enable_anchor_audit` / `enable_refinement` / `enable_consistency_guard` / `enable_beat_coverage` / `enable_state_tracker`（Loop 1 状态卡，+(N-1)×小 creative）/ `enable_edit_verify`（Loop 2 手术复验，+0~1×reasoning）。**PRUNE 无开关，永远执行。**

### Refinery 精修（V4.1，独立工具）

**核心思想**：对**任意已有草稿**（无论哪个引擎生成或人写）的两阶段人工精修——医生看病式流程，先诊断开清单，等作者确认治哪些，再动手术。

编排主类 `Refinery` 位于 `backend/services/refinery/refinery.py`，入口路由 `backend/routes/chapter_generation/refinery.py`。

**流程**：
1. **diagnose**（1×reasoning LLM，`diagnostician.py`）— 输出问题清单 JSON，存入内存 dict `_PENDING_REFINERIES`（TTL 60 分钟），返回 `run_id`。
2. **人在回路** — 作者在前端勾选确认要修复的问题。
3. **confirm** — 凭 `run_id` 取回 → `planner`（纯算法规划手术）→ `surgeon`（N×creative 定点改段落）→ `holistic_reader`（1×reasoning 整体回读）→ `polisher`（1×creative 抛光）。

**SSE**：confirm 阶段是**唯一真·实时流式**（用 `asyncio.Queue` 边改边推）。两阶段间用内存 dict + TTL 传递状态（单实例、非持久化、重启即丢）。

> ⚠ 注意 Refinery 与 ADF/Detonation/DualTrack 内置的 REFINE/REFINING 是**完全不同的代码**（同名不同实）。`services/refinery/__init__.py` 注释称"ADF Phase 4.5 触发"是过时描述，代码中无此集成。

### 章节优化（共享功能）

独立的章节重写功能，与三套生成引擎正交，服务于前端 `chapter_optimization` 路由：
- `POST /api/optimize_chapter` — 整章 refine 重写，调 `refine_draft`（`workflows/refining.py`，前端当前主要用 `/optimize_selection`）
- `POST /api/optimize_selection` — 选中片段局部重写，调 `optimize_selection_with_llm`

> `refining.py` 是共享文件（前端在用），**不属于任何废弃引擎**，剥离时予以保留。

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
└── GenerationRun (单次生成运行的 token 计量，定义于 models.py)
```

以上模型均定义于 `backend/models.py`。⚠ `backend/models_generation_task.py` 中有一份 `GenerationTask` 重复定义，全代码库零引用，是死文件。已废弃的 `DetonationChain` ORM 已删除（数据库 `detonation_chains` 表保留存量数据，代码不再管理）。

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

**文件头**：所有 `.py` 文件应包含 AGPL-3.0 许可证头（新文件必须添加）。⚠ 现状：backend 下部分文件缺失许可证头，主要集中在较新模块（`workflows/adf/`、`services/refinery/`、`routes/chapter_generation/`）及 assets 相关文件。

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
- `llm.wash`（可选）：去 AI 味洗涤专用槽（`services/nlg/de_ai_washer.py`），结构同上；缺失或不完整时洗涤回退到 creative 槽
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
- ~~`AGENTIC_BEAT_CONCURRENCY`~~ / ~~`AGENTIC_FORCE_FAST_MODE`~~（原双轨引擎的概念，该引擎已废弃迁至 `_deprecated/`）
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

*最后更新: 2026-07-24（引擎剥离后全面校准：废弃 DualTrack/Unified/Detonation 三套引擎，保留 ADF + Refinery；重写目录树、核心架构、生成主流程、引擎端点等段落以反映剥离后现状）*

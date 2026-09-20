# Velluma AI 小说写作助手

**专为长篇小说创作设计的 AI 驱动写作助手，采用 NLE-ADF 3.0 自适应融合写作流（前端默认主线）+ ADF 锚驱动生成引擎**

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)](https://www.python.org/)
[![Vue.js](https://img.shields.io/badge/Vue-3.4-green.svg)](https://vuejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-red.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-AGPL--3.0-orange.svg)](LICENSE)

---

## 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [生成引擎](#生成引擎)
- [数据模型](#数据模型)
- [RAG 记忆检索](#rag-记忆检索)
- [配置与环境变量](#配置与环境变量)
- [常用命令](#常用命令)
- [调试指南](#调试指南)
- [常见问题](#常见问题)
- [许可证](#许可证)

---

## 项目简介

Velluma 是一个 AI 驱动的长篇小说写作助手**桌面应用**（Electron 容器）。写作主线为 **NLE-ADF 3.0 自适应融合写作台**（作者主导写作 + AI 柔性共生，打字即激活辅助层），并保留 ADF（锚驱动正向流）引擎本体与章节重写/局部优化功能。它专为长篇叙事设计，支持：

- 角色状态追踪与关系图谱
- 基于 RAG 的智能记忆系统
- 伏笔（Plot Ledger）追踪与管理
- 全局资产（Asset）跨章节连续性管理
- 事件推演的世界状态（谁在场、在哪、生死随叙事时刻折叠）

### 目标用户

- 网络小说作者
- 长篇小说创作者
- 需要 AI 辅助创作工具的写作爱好者

---

## 核心特性

### 🌊 NLE-ADF 3.0 自适应融合写作台（前端默认主线）

作者主导写作 + AI 柔性共生：不预设拍、不跑整章管线，进章节打字即激活辅助层：

- **心跳感知挂件**：作者写作间隙后台感知，Tab 唤出卡舱（landing 落点 / toward_beat 走向 / echo 前情回响 / ambient 氛围）
- **Space 幽灵草稿续写**：三键阶梯——Tab 采纳 · Enter 暂留 · Esc 丢弃；五模式（stitch / continue / burst / open / outline）
- **走向卡连写**（Ctrl+Space）、**细纲胶囊**（`[[` 速记扩写）、**世界速记**（Alt+N）、**`??` 问书**（行间速查）
- **沉淀与完稿审计**：Ctrl+Enter 手动沉淀；完稿时体检报告（读者清单 + 语义扫描 + 约束核查）

**核心思想**：作者永远主导，AI 只在停笔的缝隙里柔性共生。详见 `AGENTS.md`「NLE-ADF 3.0」节。

### 🤖 ADF 锚驱动生成引擎（V3.2，本体保留、前端已无 UI 入口）

先定"终点锚"（本章高潮 + 必埋/必收的伏笔），再正向逐段写作逼近锚点，全程串行 + 双重自检：

| 阶段 | 功能 | 说明 |
|------|------|------|
| Spine Building | 脉络骨架 | 纯算法拆分必须埋下/必须回收的钩子，推断章节在全书的卷位 |
| Anchor Design | 锚点设计 | LLM 设计高潮强度与每个钩子的前置条件 |
| Tier Decide | 定档 | 判定本章类型（高潮/转折/推进/过渡），映射到字数与段数 |
| Forward Flow | 正向写作 | 逐段串行写作，每段做"去 AI 味"三道后处理 |
| Prune | 重构剪枝 | 逐段重构去 AI 味 + 整章角色崩坏检测（无条件触发） |
| Anchor Audit | 锚点审计 | 代码级关键词扫描 + LLM 5 维审计取并集 |
| Refine | 条件补埋 | 审计未通过时，在情绪平淡段落内嵌补写漏掉的伏笔 |

**核心思想**：边走边自检，没到终点就回头补。详细架构见 `docs/generation-v3.2-adf.md`。

> **已退役引擎**：Refinery 精修流水线已于 2026-09-12 整体拔除（手术原语迁 `services/text_surgery/`，读者反馈收编 `/adaptive/reader-feedback`，设计文档 `docs/generation-v4.1-refinery.md` 留档）；已废弃引擎（V3.0 Detonation / V3.1 Unified / V4.0 DualTrack / BS-ADF——2026-08-19 归档）的代码与设计文档已归档至 `backend/_deprecated/`（代码）与 `backend/_deprecated/docs/`（设计文档），不再参与运行。

### 🧠 长篇记忆与状态管理

- **角色状态机**：静态设定（永恒）+ 动态状态（瞬时）+ 状态历史轨迹
- **关系图谱**：角色间关系的演化追踪
- **RAG 记忆**：默认结构化前情 + 词法双路由召回；向量检索为专业级可选（任意 OpenAI 兼容 Embedding 服务）
- **情节账本**：伏笔的埋设、回收、追踪，避免未来信息泄露
- **全局资产**：道具/法宝/装备的跨章节状态连续性
- **世界设定层**：事件溯源式世界建模（活舆图），生成上下文与世界页共用同一事实源

---

## 技术栈

### 后端

| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.109.0 |
| ORM | SQLAlchemy | 2.0.25（异步） |
| 数据库 | SQLite（默认，零配置）/ PostgreSQL + pgvector（可选专业级） | 14+（PG 路径） |
| 驱动 | aiosqlite（默认）/ asyncpg（PG 路径） | - / 0.29.0 |
| LLM | OpenAI SDK（OpenAI 兼容协议） | 1.10.0 |
| Embedding | OpenAI 兼容协议（默认模型 text-embedding-v2） | - |
| 服务器 | Uvicorn | 0.27.0 |
| 重试 | tenacity | 8.2.3 |

### 前端

| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3（Composition API） | ^3.4.15 |
| 语言 | TypeScript | ^5.9.3 |
| 构建 | Vite | ^5.0.12 |
| 样式 | Tailwind CSS | ^3.4.1 |
| 编辑器 | TipTap | ^2.24.0 |
| 桌面容器 | Electron | ^28.3.3 |

---

## 快速开始

### 环境要求

- **Python** 3.12+
- **Node.js** 18+
- **数据库**：默认 **SQLite 零配置**（`data/velluma.db`，首次启动自动建库）；PostgreSQL 14+（含 pgvector 扩展）仅在显式设置 `DATABASE_URL` 走 PG 专业级路径时需要

### 1. 克隆仓库

```bash
git clone <repo-url>
cd Velluma
```

### 2. 配置

**数据库**：默认无需任何配置——不设 `DATABASE_URL` 时自动使用 SQLite（`data/velluma.db`，零外部依赖）。如需切回 PostgreSQL，复制 `.env.example` 为 `.env` 并设置 `DATABASE_URL=postgresql+asyncpg://…`（需先启用 pgvector）：

```bash
cp .env.example .env
```

> 仅 PG 路径需要：
> ```sql
> CREATE EXTENSION IF NOT EXISTS vector;
> ```
>
> 存量 PostgreSQL 数据可一次性搬迁至 SQLite：`python scripts/migrate_pg_to_sqlite.py`（源库只读，行数对照 + 外键校验）。

**LLM / Embedding / 代理**：复制 `model_config.example.json` 为 `model_config.json`（主配置入口，包含 API Key，已 gitignore），填入真实 API Key：

```bash
cp model_config.example.json model_config.json
```

```json
{
  "llm": {
    "reasoning": { "provider": "...", "api_key": "...", "model": "..." },
    "creative":  { "provider": "...", "api_key": "...", "model": "..." }
  },
  "embedding": { "api_key": "...", "base_url": "", "model": "text-embedding-v2", "dimensions": 1536, "follow_llm": false },
  "proxy":     { "enabled": false, "url": "http://127.0.0.1:4780" }
}
```

> ⚠ **API Key 全部来自 `model_config.json`，不读环境变量。** 请勿提交该文件。

### 3. 安装依赖

```powershell
# 后端
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# 前端
cd frontend
npm install
```

### 4. 运行

**推荐：桌面应用完整启动（后端 + 前端 Vite + Electron）**

Windows（PowerShell）：

```powershell
.\scripts\dev\start-all.bat          # 开发调试（后端热重载 + Vite + Electron，自动开 DevTools）
.\scripts\prod\start-all.bat         # 生产体验（npm run build 后 Electron 载入 dist）
```

macOS / Linux（bash）：

```bash
./scripts/macos/dev/start-all.sh      # 开发调试（后端热重载）
./scripts/macos/prod/start-all.sh     # 生产体验
```

**仅后端开发**

```powershell
.venv\Scripts\activate
python backend/main.py
```

默认端口 `8002`，若被占用则自动扫描 `8002~8100`，实际端口写入 `data/port.txt`。

**仅前端开发（需后端已在运行）**

```bash
cd frontend
npm run dev
```

端口由启动脚本协商（起始 `5175`，最多扫描 100 个），实际端口写入 `data/frontend_port.txt`。

---

## 项目结构

```
Velluma/
├── scripts/                  # 启动脚本（按环境/功能完全隔离：dev / prod / monitor）
│   ├── dev/                  # 开发调试环境·Windows（后端热重载）
│   │   ├── start-all.bat     # 一键三端（编排核心 start-all.ps1 + 控制台监控台）
│   │   └── start-backend / start-frontend / start-electron   # 单服务前台直跑
│   ├── prod/                 # 正式生产环境·Windows（同四入口；前端=npm run build）
│   ├── monitor/              # 网页监控台+后台监督者（完全隔离，dev_dashboard.py 私有副本）
│   ├── macos/                # macOS/Linux 入口（dev/ 与 prod/ 两环境，同四入口）
│   ├── stop-velluma.bat/.ps1/.sh  # 全局一键收摊（三平台）
│   └── make_blank_atlas.py   # 工具：世界页空白舆图 SVG 生成器（平台无关）
├── requirements.txt          # Python 依赖
├── model_config.example.json # LLM/Embedding/代理配置模板（复制为 model_config.json）
├── .env.example              # 环境变量模板（复制为 .env，均可留空）
├── AGENTS.md                 # 开发指南（架构与现状的权威说明）
│
├── backend/                  # FastAPI 后端
│   ├── main.py               # 应用入口、路由注册（21 个）、CORS、SPA fallback
│   ├── models/               # ORM 模型包（35 张表按领域分 8 个子模块）
│   ├── database.py           # 异步引擎（SQLite 默认 / PG 可选）、启动时自动迁移
│   ├── core/                 # config（端口扫描）、model_config、依赖注入
│   ├── config/               # 意图引擎活件（V4.0 参数推导层已归档 _deprecated/config/）
│   ├── routes/               # 20 个 API 路由模块（另含 chapter_generation 包）
│   ├── schemas/              # Pydantic 模型
│   ├── repositories/         # 数据访问层（Repository 模式）
│   ├── services/             # 业务逻辑层
│   │   ├── llm/              # LLM 调用、Embedding、代理、厂商能力档案
│   │   ├── context/          # 上下文加载（settings_bundle / stitch_context / world_bridge）
│   │   ├── generation/       # 生成服务入口（含记忆计分）
│   │   ├── prompts/          # Prompt 模板库
│   │   ├── rag/              # RAG 检索系统（recall 唯一入口 + 词法检索）
│   │   ├── adaptive/         # NLE-ADF 3.0 辅助层服务（感知/意图/观测/静音学习等）
│   │   ├── text_surgery/     # 一致性守卫手术原语（Refinery 遗产新家）
│   │   ├── book_archive/     # 书籍备份/还原（34 表注册表）
│   │   ├── workflows/        # 工作流（adf/ 引擎包 + 共享设施）
│   │   ├── world/            # 世界状态服务（事件推演/写作桥/问书/读者清单）
│   │   └── utils/            # SSE、日志、超时等工具
│   └── ...
│
├── frontend/                 # Vue 3 前端 + Electron 容器
│   ├── electron/             # Electron 主进程与 preload
│   ├── src/
│   │   ├── features/         # 功能模块（containers/presentation 分层）
│   │   ├── services/api/     # API 适配（domain/stream/transport 三层）
│   │   ├── components/       # 通用组件
│   │   ├── composables/      # Vue 组合式函数
│   │   ├── extensions/       # TipTap 扩展
│   │   └── shared/           # 跨模块类型与工具
│   ├── vite.config.js        # 端口动态协商（读 data/port.txt）
│   └── package.json
│
├── data/                     # 运行时端口持久化（gitignore）
└── logs/                     # Prompt 日志（gitignore）
```

---

## 生成引擎

当前保留：**NLE-ADF 3.0 自适应流（前端默认主线）** + ADF 引擎（本体保留，前端已无 UI 入口）+ 章节优化功能。Refinery 精修已于 2026-09-12 整体拔除。

### NLE-ADF 3.0 自适应写作台（前端默认）

作者主导写作 + AI 柔性共生：不预设拍、不跑整章管线，进章节打字即激活辅助层（心跳感知 / Space 幽灵草稿 / 走向卡连写 / 细纲胶囊扩写 / 沉淀与完稿审计 / 世界速记与情境浮卡 / `??` 问书）。编排代码：`backend/routes/chapter_generation/adaptive/`（包）+ `backend/services/context/settings_bundle.py`。详见 `AGENTS.md`「NLE-ADF 3.0」节。

主要端点：`/adaptive/heartbeat`（心跳感知）、`/adaptive/stitch-ghost`（续写，SSE）、`/adaptive/settle`（手动沉淀）、`/adaptive/finish`（完稿审计）、`/adaptive/fix-sentence`（残句定点修复）、`/adaptive/spine` + `/adaptive/spine-suggest`（章级谋篇）、`/adaptive/model`（世界模型快照）。

### ADF 引擎（V3.2，本体保留）

**编排代码**：
- `backend/routes/chapter_generation/adf.py` — 入口路由（含 SSE）
- `backend/services/workflows/adf/adf_workflow.py` — 工作流主类 `ADFWorkflow`

**7 阶段序列**（SSE 阶段进度实时流出，正文为生成完成后切块输出）：

```
CONTEXT_ASSEMBLING → SPINE_BUILDING → ANCHOR_DESIGN → TIER_DECIDE
→ FORWARD_FLOW → PRUNE → ANCHOR_AUDIT → (REFINE)
```

1. **CONTEXT_ASSEMBLING** — 组装上下文：角色/关系/伏笔/上一章摘要 + Canon + 世界观
2. **SPINE_BUILDING** — 脉络骨架：纯算法拆分必埋/必收钩子
3. **ANCHOR_DESIGN** — 锚点设计：LLM 设计高潮强度与前置条件
4. **TIER_DECIDE** — 定档：判定本章类型，映射字数/段数
5. **FORWARD_FLOW** — 正向逐段写作（串行，每段含去 AI 味后处理）
6. **PRUNE** — 重构剪枝（去 AI 味 + 角色崩坏检测，无条件触发）
7. **ANCHOR_AUDIT** — 锚点审计（代码级 + LLM 双审计取并集）
8. **REFINE** — 条件补埋（审计未通过时，补写漏掉的伏笔）

> Refinery 精修（V4.1 独立工具）已于 2026-09-12 整体拔除，设计文档 `docs/generation-v4.1-refinery.md` 留档。

### API 端点

- `POST /api/chapters/{id}/adaptive/*` — NLE-ADF 3.0 自适应流（前端默认，见上节端点清单）
- `POST /api/chapters/{id}/generate-adf` — ADF 流式生成（SSE）
- `POST /api/chapters/{id}/plan-suggestion` — 生成前章节规划建议
- `POST /api/optimize_chapter` / `/optimize_selection` — 章节重写/局部优化（共享功能）
- `GET /api/books/{id}/backup` / `POST /api/books/restore` — 书籍备份导出（`.vellumabook` 单 JSON 文件）与还原（原 ID 直复，2026-09-19）

> 已废弃端点 `/generate`（V3.1）、`/generate-v3`（V3.0）、`/generate-chapter`（V4.0）已随引擎移除；`/generate-bsadf`、`/advance-beat`、`/stepping-run/{id}/state`、`/rerender-beat`、`/cancel-run` 已随 BS-ADF 归档移除（2026-08-19）；`/refinery/diagnose`、`/refinery/confirm` 已随 Refinery 拔除移除（2026-09-12）。

---

## 数据模型

```
Book (书籍)
├── Chapter (章节)
│   ├── StoryBeat (剧情节拍) — 最小剧情单元
│   ├── SceneIntent (场景意图) — Beat 内生成指令
│   ├── ChapterEntity / ChapterMapLocation / ChapterAsset — 章节级关联
├── Character (角色)
│   ├── static_prompt (永恒设定) / dynamic_state (瞬时状态)
│   ├── dynamic_state_history (状态历史)
│   └── CharacterRelationship (角色关系)
├── MapLocation (地图地点)
├── Asset (全局资产/道具)
├── MemoryChunk (向量记忆)
├── PlotLedger (情节账本/伏笔)
└── GenerationTask (异步生成任务)
```

全部 35 张表定义于 `backend/models/`（ORM 模型包，按领域分 8 个子模块；除上述核心表外，还包括世界层 `world_*` 事件溯源表族与候选池、文风族 `author_samples`/`style_cards`/`style_inbox_items`、真相面 canon/plot_ledgers 扩展列等）。

---

## RAG 记忆检索

**Embedding 走 OpenAI 兼容协议**（任意兼容服务均可接入；默认模型 `text-embedding-v2`、1536 维，`follow_llm=true` 时连接跟随文本模型槽；`base_url` 留空回退 DashScope 兼容端点，历史 Key 零迁移）。API Key 来自 `model_config.json`，**不读环境变量**。未配置 embedding 时记忆流自动走结构化前情 + 词法双路由默认流（向量层为专业级增强，三层叠加）。

**检索权重参数**（查询在 `backend/repositories/memory_repository.py`，计分在 `backend/services/generation/memory_scorer.py`）：

| 参数 | 含义 | 默认 |
|------|------|------|
| alpha | 语义相似度权重 | 0.6 |
| beta | 时间衰减权重 | 0.2 |
| gamma | 剧情伏笔权重 | 0.2 |
| lambda_decay | 时间衰减系数 | 0.1 |

检索范围限制在当前章节之前（`exclude_chapter_id=当前章`），避免未来信息泄露。

---

## 配置与环境变量

### model_config.json（主配置入口）

LLM、Embedding、代理的实际配置来源。该文件已 gitignore，**当前工作区副本含真实 API Key，请勿提交或外发**。

字段：
- `llm.reasoning` / `llm.creative`：provider、api_key、base_url、model、enabled、effort
- `embedding`：api_key、base_url、model、dimensions、follow_llm
- `proxy`：enabled、url

### 环境变量（.env，可选）

后端代码实际读取的环境变量仅有以下 4 个（均可留空——不设 `DATABASE_URL` 即默认 SQLite，开箱即用）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | 显式指定 PostgreSQL 连接串（切回 PG 专业级路径） | 无（不设即默认 SQLite `data/velluma.db`） |
| `VELLUMA_DATA_DIR` | SQLite 数据目录（打包/便携场景） | 项目根 `data/` |
| `DB_POOL_PRE_PING` | 连接池预检（仅 PG 路径） | Windows=false / 其他=true |
| `VELLUMA_PORT` | 指定后端端口（跳过扫描） | 无（默认 8002 起扫描） |

> 实际代理配置由 `model_config.json` 的 `proxy` 节决定，不读环境变量。

> ⚠ **以下变量在代码中不存在，任何文档提及均已过时**：
> - `AGENTIC_BEAT_CONCURRENCY` / `AGENTIC_FORCE_FAST_MODE`（原双轨引擎的概念，该引擎已废弃归档）
> - `DASHSCOPE_API_KEY` / `OPENAI_API_KEY`（Key 全部来自 `model_config.json`）

> 启动脚本（`scripts/dev/start-all.ps1` / `scripts/prod/start-all.ps1` / `scripts/macos/{dev,prod}/start-all.sh`）会为 Electron 进程设置 `VELLUMA_BACKEND_PORT` / `VELLUMA_FRONTEND_PORT` / `VELLUMA_SERVICES_READY`，属进程内传递，无需用户配置。生产模式下额外设置 `NODE_ENV=production`，让 `main.cjs` 载入 `dist/index.html` 而非 Vite dev server。

---

## 常用命令

### 桌面应用启动

```powershell
# Windows（scripts/dev 与 scripts/prod 各含 backend / frontend / electron / all 四入口）
.\scripts\dev\start-all.bat       # 开发调试（后端热重载 + Vite + Electron）
.\scripts\dev\start-backend.bat   # 单独后端（frontend / electron 同款单飞脚本）
.\scripts\prod\start-all.bat      # 生产体验（npm run build + 载入 dist）

# 常用参数（透传给编排核心 start-all.ps1 / start-all.sh）
.\scripts\dev\start-all.bat -Force             # 强制清理端口冲突后启动
.\scripts\dev\start-all.bat -SkipBackend       # 跳过后端（假设已运行）
.\scripts\dev\start-all.ps1 -DryRun            # 仅打印将执行的命令，不启动进程
.\scripts\stop-velluma.bat                     # 全局一键收摊（dev/prod/monitor 通用）

# macOS / Linux
./scripts/macos/dev/start-all.sh       # 开发调试（后端热重载）
./scripts/macos/prod/start-all.sh      # 生产体验
./scripts/macos/dev/start-all.sh --force --skip-backend   # 参数用长选项风格
```

### 后端

```powershell
.venv\Scripts\activate
python backend/main.py    # 启动开发服务器
```

### 前端

```bash
cd frontend
npm run dev          # 启动 Vite 开发服务器
npm run typecheck    # TypeScript 类型检查
npm run build        # 生产构建
npm run preview      # 预览构建产物
```

### Electron（在 frontend 目录下）

```bash
npm run electron:dev     # 构建前端后启动 Electron
npm run electron:build   # 打包安装包（electron-builder）
```

### 桌面应用打包

```bash
cd frontend
npm run build           # 构建前端
npm run electron:build  # 打包 Electron 安装包
```

### 服务地址

| 服务 | URL |
|------|------|
| 后端 API | http://127.0.0.1:8002 |
| 前端 Dev | http://127.0.0.1:5175 |
| API 文档 | http://127.0.0.1:8002/docs |
| 健康检查 | http://127.0.0.1:8002/api/health |

> 端口为协商值：后端 8002~8100 扫描，前端 5175~5285 扫描，实际端口见 `data/port.txt` 与 `data/frontend_port.txt`。

---

## 调试指南

### 后端

- 健康检查：`curl http://127.0.0.1:8002/api/health`
- Prompt 日志：`logs/prompt_log_*.json`（由 `services/utils/prompt_logger.py` 生成）
- Windows asyncio 无害连接错误已在 `main.py` 注册静默处理器

### 前端

- 浏览器开发者工具 + Vue DevTools
- Vite 代理层：后端不可用时返回 503 + `retryable: true`，30 秒请求超时
- Electron 层：启动时 HTTP 健康检查重试（最多 5 次），加载 URL 失败自动重试（最多 10 次）

### 数据库

- **自动迁移**：启动时 `database.py` 的 `init_db()` 自动检查并添加缺失列（非 Alembic）
- **向量维度迁移（破坏性）**：若 `model_config.json` 的 embedding 维度与数据库现有列不匹配，会**删列重建**（清空全部向量数据）。切换 embedding 模型/维度前务必备份。

---

## 常见问题

### 端口被占用

```powershell
# Windows：查看占用
Get-NetTCPConnection -LocalPort 8002
Get-NetTCPConnection -LocalPort 5175

# 强制清理后启动
.\scripts\dev\start-all.bat -Force
```

```bash
# macOS / Linux：查看占用
lsof -nP -iTCP:8002 -sTCP:LISTEN
lsof -nP -iTCP:5175 -sTCP:LISTEN

# 强制清理后启动
./scripts/macos/dev/start-all.sh --force
```

### 前端连接失败

Electron 会自动重试连接（最多 10 次）。若仍失败：
1. 检查后端：`curl http://127.0.0.1:8002/api/health`
2. 检查前端：`curl http://127.0.0.1:5175`

### 虚拟环境找不到

确保项目根目录有 `.venv\Scripts\python.exe` 或 `venv\Scripts\python.exe`。

---

## 许可证

本项目基于 [AGPL-3.0](LICENSE) 开源。

Copyright (C) 2026 Velluma Project Contributors.

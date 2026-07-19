# Velluma AI 小说写作助手

**专为长篇小说创作设计的 AI 驱动写作助手，采用 Agentic Workflow 智能体工作流架构**

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
- [架构设计](#架构设计)
- [API 文档](#api-文档)
- [双轨生成工作流](#双轨生成工作流)
- [数据模型](#数据模型)
- [配置与环境变量](#配置与环境变量)
- [常用命令](#常用命令)
- [调试指南](#调试指南)
- [常见问题](#常见问题)

---

## 项目简介

Velluma 是一个 AI 驱动的长篇小说写作助手桌面应用，通过双轨对抗生成架构产出高质量小说章节内容。它专为长篇叙事设计，支持：

- 角色状态追踪与关系图谱
- 基于 RAG 的智能记忆系统
- 伏笔追踪与管理
- Electron 桌面应用

### 目标用户

- 网络小说作者
- 长篇小说创作者
- 需要 AI 辅助创作工具的写作爱好者

---

## 核心特性

### 🤖 双轨对抗生成 (V4.0)

并行生成 + 连贯性锚定，解决并行起草连贯性差的问题：

| 阶段 | 功能 | 说明 |
|------|------|------|
| Planning | 智能规划 | 将章节拆分为 StoryBeat，分配 POV 与字数（独立预览端点） |
| Drafting | 双轨生成 | Track A 并行扩写 Beat；Track B 生成连贯速写（Sketch） |
| Stitching | 智能统稿 | 合并 Beat 内容为完整草稿 Draft_A |
| Reviewing | 对抗校对 | 对比 Draft_A 与 Sketch，检测结构/情绪/信息差异 |
| Refining | 融合精修 | 基于差异报告重写融合，轻微问题可跳过 |

### 👤 角色系统

- **角色卡片管理**：支持静态设定与动态状态分离
- **状态历史追踪**：自动记录角色状态变更
- **关系图谱**：可视化展示角色关系网络
- **POV 视角分配**：智能分配叙事视角

### 🧠 RAG 记忆系统

- **向量检索**：基于 DashScope Embedding 生成 1536 维向量（维度可配置）
- **智能时间衰减**：近期内容权重更高
- **伏笔权重**：关键情节优先检索
- **防泄露机制**：仅检索当前章节之前的内容

### 📊 伏笔管理

- **情节账本**：自动追踪开放伏笔
- **闭合检测**：生成时检查伏笔是否闭合
- **状态标记**：Open / Closed / Dropped 三种状态

---

## 技术栈

### 后端

| 组件 | 技术 | 版本 |
|------|------|------|
| Web 框架 | FastAPI | 0.109.0 |
| ORM | SQLAlchemy (异步) | 2.0.25 |
| 数据库 | PostgreSQL + pgvector | 14+ |
| 异步驱动 | asyncpg | 0.29.0 |
| LLM 集成 | OpenAI SDK 1.10.0 / DashScope 1.14.1 | Embedding 仅使用 DashScope |
| ASGI 服务器 | Uvicorn | 0.27.0 |

### 前端

| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3 (Composition API) | 3.4.15 |
| 语言 | TypeScript | 5.9.3 |
| 构建工具 | Vite | 5.0.12 |
| CSS 框架 | Tailwind CSS | 3.4.1 |
| 富文本编辑 | TipTap | 2.24.0 |
| 桌面打包 | Electron | 28.3.3 |

---

## 快速开始

### 环境要求

- Python 3.12+（开发机使用 3.13.5）
- Node.js 18+
- PostgreSQL 14+（需启用 pgvector 扩展）

### 1. 克隆项目

```bash
git clone <repository-url>
cd Velluma
```

### 2. 安装后端依赖

```bash
# 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装 Python 依赖
pip install -r requirements.txt
```

### 3. 配置数据库

```sql
-- 连接 PostgreSQL
psql -U postgres

-- 创建数据库
CREATE DATABASE storyweaver;

-- 启用 pgvector 扩展
\c storyweaver
CREATE EXTENSION IF NOT EXISTS vector;
```

### 4. 配置 LLM 与数据库连接

**主配置文件：`model_config.json`**（项目根目录，已 gitignore）——LLM、Embedding、代理均在此配置：

```json
{
  "llm": {
    "reasoning": { "provider": "...", "api_key": "sk-...", "base_url": "...", "model": "...", "enabled": true },
    "creative":  { "provider": "...", "api_key": "sk-...", "base_url": "...", "model": "...", "enabled": true }
  },
  "embedding": { "api_key": "sk-...", "model": "text-embedding-v2", "dimensions": 1536 },
  "proxy": { "enabled": true, "url": "http://127.0.0.1:4780" }
}
```

完整 schema 见 `backend/core/model_config.py` 的模块 docstring。

**数据库连接**（非默认时才需要）：在项目根目录创建 `.env`：

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver
```

### 5. 启动应用

**方式一：一键启动（推荐）**

```powershell
# 依次启动后端 → Vite 开发服务器 → Electron，退出时自动清理进程
.\start.bat

# 可选参数
.\start.ps1 -Force         # 强制模式（清理端口冲突后启动）
.\start.ps1 -SkipBackend   # 跳过后端启动
.\start.ps1 -SkipFrontend  # 跳过前端 Vite 启动
.\start.ps1 -ElectronOnly  # 只启动 Electron（假设前后端已在运行）
```

**方式二：手动开发模式**

```bash
# 终端 1：后端（默认端口 8002，被占用则自动扫描 8002~8100）
python backend/main.py

# 终端 2：前端开发服务器（固定端口 5175）
cd frontend && npm install && npm run dev
```

---

## 项目结构

```
Velluma/
├── start.bat / start.ps1      # 一键启动脚本（后端 → Vite → Electron）
├── requirements.txt           # Python 依赖
├── model_config.json          # LLM/Embedding/代理配置（含 API Key，已 gitignore）
│
├── backend/                    # ========== FastAPI 后端 ==========
│   ├── main.py                # 应用入口、路由注册、静态文件服务、CORS
│   ├── models.py              # SQLAlchemy ORM 模型（14 个模型）
│   ├── database.py            # 数据库连接、启动时自动迁移（MIGRATIONS 列表）
│   │
│   ├── core/                  # 核心配置
│   │   ├── config.py          # 端口持久化与扫描、推理模型支持列表
│   │   ├── model_config.py    # 读取 model_config.json（配置的实际来源）
│   │   └── dependencies.py    # 依赖注入
│   │
│   ├── config/                # V4.0 统一配置推导层
│   │
│   ├── routes/                # API 路由层（16 个模块）
│   │   ├── books.py           # 书籍管理
│   │   ├── chapters.py        # 章节 CRUD
│   │   ├── characters.py      # 角色管理
│   │   ├── relationships.py   # 关系图谱
│   │   ├── memories.py        # RAG 记忆
│   │   ├── maps.py            # 地图/地点
│   │   ├── assets.py          # 全局资产
│   │   ├── chapter_generation/   # 章节生成（包）：双轨生成、节拍预览、SSE 流式编排
│   │   ├── chapter_optimization.py  # 章节优化
│   │   ├── chapter_publishing.py    # 发布流程
│   │   ├── critique.py        # 批评审阅
│   │   ├── inspiration.py     # 灵感生成
│   │   ├── intent_driven.py   # 意图驱动（V4.0）
│   │   └── text_formatting.py # 格式整理
│   │
│   ├── schemas/               # Pydantic 请求/响应模型（按域分文件）
│   │
│   ├── services/              # 业务逻辑层
│   │   ├── llm/               # LLM 调用封装、Embedding、代理
│   │   ├── context/           # 上下文加载
│   │   ├── generation/        # 生成服务入口
│   │   ├── orchestration/     # 工作流参数解析与节拍预览辅助
│   │   ├── prompts/           # Prompt 模板库（21 个文件）
│   │   ├── rag/               # RAG 检索系统（检索、打分、伏笔追踪）
│   │   ├── state_machine/     # 角色状态机
│   │   ├── validation/        # 质检与修复
│   │   ├── workflows/         # 工作流子阶段（双轨生成主实现）
│   │   ├── world/             # 世界状态服务
│   │   └── utils/             # SSE、Prompt 日志等工具
│   │
│   └── repositories/          # 数据访问层（Repository 模式）
│
├── frontend/                   # ========== Vue 3 前端 ==========
│   ├── src/
│   │   ├── main.ts            # 入口文件
│   │   ├── App.vue            # 根组件
│   │   ├── components/        # 通用组件
│   │   ├── composables/       # Vue 组合式函数
│   │   ├── features/          # 功能模块（containers/ + presentation/ 分层）
│   │   │   ├── app/               # 应用级容器
│   │   │   ├── chapter-editor/    # 章节编辑器
│   │   │   ├── character-panel/   # 角色面板
│   │   │   ├── asset-panel/       # 资产面板
│   │   │   ├── intent-driven/     # 意图驱动（V4.0）
│   │   │   └── novel-wizard/      # 小说创建向导
│   │   ├── services/          # 服务层
│   │   │   └── api/
│   │   │       ├── domain/        # 业务语义 API 适配
│   │   │       ├── stream/        # SSE 流处理
│   │   │       └── transport/     # HTTP 传输
│   │   ├── shared/            # 共享类型与工具
│   │   └── extensions/        # TipTap 编辑器扩展
│   │
│   ├── electron/              # Electron 主进程与 preload
│   ├── package.json
│   ├── vite.config.js         # 端口 5175（strictPort），/api 代理到后端
│   └── tailwind.config.js
│
├── data/                      # 运行时数据（端口文件等，gitignore）
├── logs/                      # Prompt 日志（gitignore）
└── LICENSE                    # AGPL-3.0 许可证
```

> 更详细的开发者指南（含代码规范、已知遗留问题）见 [AGENTS.md](AGENTS.md)。

---

## 架构设计

### 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      桌面应用层 (Electron)                    │
├─────────────────────────────────────────────────────────────┤
│                      前端层 (Vue 3)                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ 章节编辑器 │  │ 角色面板  │  │ 资产面板  │  │ 意图驱动  │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
│       └─────────────┴─────────────┴─────────────┘            │
│                         │                                    │
│              ┌──────────┴──────────┐                         │
│              │   服务层 (api/*)     │                         │
│              └──────────┬──────────┘                         │
├─────────────────────────────────────────────────────────────┤
│                      API 层 (FastAPI, 16 个路由模块)          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ CRUD API │  │ 生成 API  │  │ RAG API  │  │ 系统 API  │     │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │
├─────────────────────────────────────────────────────────────┤
│                      业务逻辑层                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │           双轨生成引擎 (DualTrackWorkflow)         │       │
│  │  Track A: Beat 并行扩写   Track B: 连贯速写 Sketch │       │
│  │     → 统稿 Draft_A → 对抗校对 → 融合精修           │       │
│  └──────────────────────────────────────────────────┘       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 角色状态管理  │  │ RAG 检索     │  │ LLM 调用封装 │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
├─────────────────────────────────────────────────────────────┤
│                      数据访问层 (Repository)                  │
├─────────────────────────────────────────────────────────────┤
│                  PostgreSQL + pgvector                       │
└─────────────────────────────────────────────────────────────┘
```

### 前端分层架构约束

```
features/*/containers    → 状态整合、事件编排
         ↓
features/*/presentation  → 渲染、交互事件抛出
         ↓
services/api/domain      → 业务语义 API 适配
         ↓
services/api/transport   → 底层 HTTP 请求

✅ 允许：presentation → containers → services/api/domain
❌ 禁止：presentation → services/api/transport（以及 services/api/stream）
```

---

## API 文档

### 系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/port` | 获取后端实际端口 |
| GET/PUT | `/api/system/proxy` | 查询/更新代理配置 |
| POST | `/api/system/test-model` | 测试模型连通性 |

### 书籍管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/books` | 获取书籍列表 |
| POST | `/api/books` | 创建书籍 |
| GET | `/api/books/{id}` | 获取书籍详情 |
| PUT | `/api/books/{id}` | 更新书籍 |
| DELETE | `/api/books/{id}` | 删除书籍 |
| GET | `/api/books/{id}/chapters` | 获取书籍的章节列表 |

### 章节管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/books/{book_id}/chapters` | 创建章节 |
| GET | `/api/chapters/{id}` | 获取章节详情 |
| PUT | `/api/chapters/{id}` | 更新章节 |
| DELETE | `/api/chapters/{id}` | 删除章节 |

### 章节生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chapters/{id}/generate-dual-track` | 双轨生成（SSE 流式） |
| POST | `/api/chapters/{id}/generate-dual-track-simple` | 双轨生成（非流式） |
| POST | `/api/generate_chapter_agentic_preview_beats` | 节拍规划预览 |
| POST | `/api/clarify-outline` | 大纲澄清 |
| POST | `/api/optimize_chapter` | 章节优化 |
| POST | `/api/optimize_selection` | 选段优化 |
| POST | `/api/generate_inspiration` | 灵感生成 |

### 角色与关系

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/books/{book_id}/characters` | 获取角色列表 |
| POST | `/api/characters` | 创建角色 |
| GET/PUT/DELETE | `/api/characters/{id}` | 角色详情/更新/删除 |
| POST | `/api/characters/{id}/update-dynamic-state` | 更新角色动态状态 |
| GET/POST | `/api/relationships` | 关系列表/创建 |
| PUT/DELETE | `/api/relationships/{id}` | 关系更新/删除 |

### 记忆系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memories` | 获取记忆列表 |
| POST | `/api/memories` | 创建记忆 |
| DELETE | `/api/memories/{id}` | 删除记忆 |
| POST | `/api/chapters/{id}/generate-embedding` | 为章节生成向量 |

> 完整 API 文档可访问 `/docs`（Swagger UI）或 `/redoc`（ReDoc）

---

## 双轨生成工作流

### 流程详解

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ASSEMBLING_CONTEXT                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │
│  │  角色卡加载  │→│  关系网构建  │→│ RAG 记忆检索 │→│ 伏笔提取   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                          POV_ASSIGNMENT                              │
│        分配 POV 角色与字数（节拍规划在独立预览端点完成）                 │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                    DRAFTING（双轨并行）                               │
│  Track A: ┌─────────┐ ┌─────────┐ ┌─────────┐                        │
│           │ Beat 1  │ │ Beat 2  │ │ Beat N  │  (并行扩写)            │
│           └─────────┘ └─────────┘ └─────────┘                        │
│  Track B: ┌─────────────────────────────────────┐                    │
│           │ Sketch 连贯速写（约 45% 字数）        │  (连贯性锚点)       │
│           └─────────────────────────────────────┘                    │
│                    Scene Intent 构建 + 质检                           │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                          STITCHING                                   │
│              合并所有 Beat 内容 → 完整章节草稿 Draft_A                  │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                  REVIEWING（对抗校对）                                │
│     AdversarialAligner 对比 Draft_A vs Sketch                        │
│     检测结构 / 情绪 / 信息差异 → 输出 adjustment_plan                 │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
                          存在显著差异？
                            ↙         ↘
                          否           是
                           ↓           ↓
                      [完成]     ┌──────────┐
                                │ REFINING │
                                │ 融合精修  │
                                └──────────┘
```

### StoryBeat 结构

每个章节被拆分为多个 StoryBeat（剧情节拍），核心字段：

```json
{
  "id": "uuid",
  "summary": "节拍剧情概述",
  "action_summary": "动作化执行摘要",
  "pacing_type": "fast|medium|slow",
  "pov_character_id": "uuid",
  "entry_state": "进入状态",
  "exit_state": "退出状态",
  "red_lines": ["红线约束"],
  "pov_aperture": "叙事光圈（V4.0）"
}
```

> 说明：schema 中的 `max_iterations`（1~5）为设计上限，当前双轨实现按单轮执行（迭代参数未实际消费）；Beat 并行度为代码内固定值（Semaphore 5），不通过环境变量配置。

---

## 数据模型

### 实体关系图

```
Book (书籍)
├── Chapter (章节)
│   ├── StoryBeat (剧情节拍)
│   ├── SceneIntent (场景意图)
│   ├── ChapterEntity (章节-角色关联)
│   ├── ChapterMapLocation (章节-地点关联)
│   └── ChapterAsset (章节-资产关联)
├── Character (角色)
│   └── CharacterRelationship (角色关系)
├── MapLocation (地图地点)
├── Asset (全局资产/道具)
├── MemoryChunk (向量记忆)
├── PlotLedger (情节账本/伏笔)
└── GenerationTask (异步生成任务)
```

### 核心模型说明

| 模型 | 说明 | 关键字段 |
|------|------|----------|
| Book | 书籍根实体 | title, genre, worldview_settings, golden_snippets |
| Chapter | 章节 | chapter_number, draft_text, review_feedback, content_text, status |
| Character | 角色 | static_prompt, dynamic_state, dynamic_state_history |
| CharacterRelationship | 关系 | source_id, target_id, relationship_type, description |
| MemoryChunk | 向量记忆 | content, embedding (默认 1536 维), relevance_score |
| PlotLedger | 伏笔 | plot_point, status (open/closed/dropped), chapter_id |
| StoryBeat | 剧情节拍 | summary, action_summary, pacing_type, pov_character_id |
| SceneIntent | 场景意图 | goal, obstacle, tactic, stakes, story_beat_id |

---

## 配置与环境变量

### model_config.json（主要配置入口）

LLM、Embedding、代理的实际配置来源，见上文[快速开始](#4-配置-llm-与数据库连接)。

⚠️ 该文件已 gitignore，但本地副本含有真实 API Key，请勿提交或外发。

### 环境变量（.env，可选）

后端实际读取的环境变量仅有：

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DATABASE_URL` | ❌ | `postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver` | PostgreSQL 连接字符串 |
| `DB_POOL_PRE_PING` | ❌ | Windows=false / 其他=true | 连接池预检 |
| `VELLUMA_PORT` | ❌ | 无（8002 起自动扫描） | 指定后端端口 |

> ⚠️ 早期文档中的 `DASHSCOPE_API_KEY`、`OPENAI_API_KEY`、`AGENTIC_BEAT_CONCURRENCY`、`AGENTIC_FORCE_FAST_MODE` 环境变量**在当前代码中均不存在**：API Key 全部来自 `model_config.json`，Beat 并行度为代码内固定值，快速模式是生成请求中的 `fast_mode` 参数。

---

## 常用命令

### 一键启动

```powershell
.\start.bat                  # 后端 + Vite + Electron
.\start.ps1 -Force           # 强制模式（清理端口冲突）
.\start.ps1 -ElectronOnly    # 仅 Electron
```

### 后端开发

```bash
# 启动开发服务器（默认端口 8002，被占用自动扫描至 8100）
python backend/main.py

# 数据库调试（启用 SQL 日志）
# 编辑 backend/database.py，设置 echo=True
```

### 前端开发

```bash
cd frontend

npm install        # 安装依赖
npm run dev        # 启动开发服务器（固定端口 5175）
npm run typecheck  # 类型检查
npm run build      # 构建生产版本
npm run preview    # 预览构建产物
```

### Electron 桌面应用

```bash
cd frontend

npm run electron:dev      # 构建前端后启动 Electron（需 5175 端口已有前端服务）
npm run electron:build    # 打包安装包（electron-builder）
```

> 注：`npm run electron:dev` 与 `electron:preview` 当前内容相同（均为 `npm run build && electron .`），日常开发推荐使用根目录 `start.bat`。

---

## 调试指南

### 查看 LLM Prompt

1. **Debug 窗口**：应用内打开，显示所有发送的 Prompt
2. **开发者工具**：主窗口按 `F12` 打开
3. **日志文件**：`logs/prompt_log_*.json`（由后端自动生成）

### 日志位置

| 类型 | 位置 |
|------|------|
| 后端日志 | 控制台输出 |
| 前端日志 | 浏览器开发者工具 |
| Prompt 日志 | `logs/` 目录 |
| 数据库日志 | `backend/database.py` 设置 `echo=True` |

### 常见问题排查

**数据库连接失败**
```bash
psql -d storyweaver -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**端口冲突**
- 后端默认 8002，被占用时自动扫描 8002~8100，实际端口写入 `data/port.txt`
- 前端 Vite 固定 5175（strictPort），被占用会直接启动失败

**编码问题**
- 后端已强制 UTF-8 编码
- Windows 终端需确保代码页为 UTF-8：`chcp 65001`

---

## 常见问题

### Q: 如何配置 LLM 提供商？

编辑项目根目录 `model_config.json` 的 `llm.reasoning` / `llm.creative` 节（provider、api_key、base_url、model）。Embedding 使用 DashScope，在 `embedding` 节配置。均不通过环境变量。

### Q: 支持哪些数据库？

目前仅支持 PostgreSQL 14+（需要 pgvector 扩展支持向量检索）。

### Q: 如何自定义 Prompt 模板？

编辑 `backend/services/prompts/` 目录下的模板文件，重启后端生效。

### Q: Beat 并行度如何调整？

当前为代码内固定值（`backend/services/workflows/drafting.py` 中的 `asyncio.Semaphore(5)`），需改代码；早期文档中的 `AGENTIC_BEAT_CONCURRENCY` 环境变量已不存在。

---

## 安全注意事项

1. **API Key 安全**
   - Key 统一存放在 `model_config.json`（已 gitignore），不存数据库、不读环境变量
   - 日志中脱敏处理

2. **代理配置**
   - 默认本地代理 `http://127.0.0.1:4780`，在 `model_config.json` 的 `proxy` 节修改

3. **CORS 策略**
   - 当前代码无条件允许所有来源（`allow_origins=["*"]`），生产部署需收紧为具体域名

---

## 许可证

本项目基于 [AGPL-3.0](LICENSE) 开源。

---

## 贡献

欢迎提交 Issue 和 Pull Request！

- 报告 Bug → [Issues](../../issues)
- 功能建议 → [Discussion](../../discussions)
- 代码贡献 → Pull Request

---

## 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代高效的 Web 框架
- [Vue.js](https://vuejs.org/) - 渐进式 JavaScript 框架
- [TipTap](https://tiptap.dev/) - 专业的富文本编辑器
- [pgvector](https://github.com/pgvector/pgvector) - PostgreSQL 向量扩展

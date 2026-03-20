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
- [Agentic Workflow](#agentic-workflow)
- [数据模型](#数据模型)
- [环境变量](#环境变量)
- [常用命令](#常用命令)
- [调试指南](#调试指南)
- [常见问题](#常见问题)

---

## 项目简介

Velluma 是一个 AI 驱动的长篇小说写作助手桌面应用，通过多轮迭代生成高质量小说章节内容。它专为长篇叙事设计，支持：

- 角色状态追踪与关系图谱
- 基于 RAG 的智能记忆系统
- 伏笔追踪与管理
- 桌面应用支持（pywebview / Electron）

### 目标用户

- 网络小说作者
- 长篇小说创作者
- 需要 AI 辅助创作工具的写作爱好者

---

## 核心特性

### 🤖 Agentic Workflow 工作流

五阶段迭代生成流程，最多支持 **5 轮精修**：

| 阶段 | 功能 | 说明 |
|------|------|------|
| Planning | 智能规划 | 将章节拆分为 StoryBeat，自动分配 POV |
| Drafting | 并行起草 | 多 Beat 并发生成，支持 Fast/Medium/Slow 节奏 |
| Stitching | 智能统稿 | 合并 Beat 内容，确保叙事连贯 |
| Reviewing | 质量审阅 | 检查结构、角色一致性、伏笔闭合 |
| Refining | 迭代精修 | 基于质检报告重写优化 |

### 👤 角色系统

- **角色卡片管理**：支持静态设定与动态状态分离
- **状态历史追踪**：自动记录角色状态变更
- **关系图谱**：可视化展示角色关系网络
- **POV 视角分配**：智能分配叙事视角

### 🧠 RAG 记忆系统

- **向量检索**：基于 DashScope Embedding 生成 1536 维向量
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
| LLM 集成 | OpenAI SDK / DashScope | - |
| ASGI 服务器 | Uvicorn | 0.27.0 |

### 前端

| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3 (Composition API) | 3.4.15 |
| 语言 | TypeScript | 5.9.3 |
| 构建工具 | Vite | 5.0.12 |
| CSS 框架 | Tailwind CSS | 3.4.1 |
| 富文本编辑 | TipTap | 2.24.0 |
| 桌面打包 | pywebview / Electron | 4.4.1 / 28.3.3 |

---

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- PostgreSQL 14+（需启用 pgvector 扩展）

### 1. 克隆项目

```bash
git clone <repository-url>
cd Velluma
```

### 2. 配置后端

```bash
# 创建并激活虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 安装 Python 依赖
pip install -r requirements.txt

# 创建环境变量文件
cp backend/core/config.py .env  # 或手动创建 .env
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

### 4. 配置 .env 文件

```env
# 数据库连接
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver

# API Keys（至少配置一个）
DASHSCOPE_API_KEY=your_dashscope_key
OPENAI_API_KEY=your_openai_key

# 代理配置（可选）
PROXY_URL=http://127.0.0.1:4780

# 工作流配置（可选）
AGENTIC_BEAT_CONCURRENCY=6
```

### 5. 启动应用

**方式一：pywebview 桌面应用（推荐）**

```bash
python app.py
```

**方式二：开发模式**

```bash
# 终端 1：后端
python backend/main.py

# 终端 2：前端开发服务器
cd frontend && npm run dev
```

**方式三：Electron**

```bash
cd frontend
npm install
npm run electron:dev
```

---

## 项目结构

```
Velluma/
├── app.py                      # 桌面应用入口 (pywebview)
│
├── backend/                    # ========== FastAPI 后端 ==========
│   ├── main.py               # 应用入口、路由注册、CORS 配置
│   ├── models.py             # SQLAlchemy ORM 模型定义
│   ├── schemas.py             # Pydantic 请求/响应模型
│   ├── database.py            # 数据库连接、迁移管理
│   ├── requirements.txt       # Python 依赖
│   │
│   ├── core/                  # 核心配置
│   │   ├── config.py         # 配置管理、环境变量
│   │   └── dependencies.py   # 依赖注入
│   │
│   ├── routes/                # API 路由层（15+ 路由模块）
│   │   ├── books.py          # 书籍管理
│   │   ├── chapters.py        # 章节 CRUD
│   │   ├── characters.py      # 角色管理
│   │   ├── relationships.py   # 关系图谱
│   │   ├── memories.py        # RAG 记忆
│   │   ├── maps.py            # 地图/地点
│   │   ├── chapter_generation.py   # 章节生成
│   │   ├── chapter_optimization.py  # 章节优化
│   │   ├── chapter_publishing.py    # 发布流程
│   │   ├── critique.py        # 批评审阅
│   │   ├── inspiration.py     # 灵感生成
│   │   └── text_formatting.py # 格式整理
│   │
│   ├── services/              # 业务逻辑层
│   │   ├── agentic_workflow.py    # 核心工作流编排
│   │   ├── llm_client.py          # LLM 调用封装
│   │   ├── character_state.py    # 角色状态管理
│   │   ├── prompt_builder.py      # Prompt 构建器
│   │   ├── prompt_logger.py       # Prompt 日志
│   │   │
│   │   ├── prompts/          # Prompt 模板
│   │   │   ├── planner_prompts.py
│   │   │   ├── draft_prompts.py
│   │   │   ├── review_prompts.py
│   │   │   ├── refine_prompts.py
│   │   │   ├── stitch_prompts.py
│   │   │   ├── critique_prompts.py
│   │   │   └── ...
│   │   │
│   │   └── workflows/        # 工作流子模块
│   │       ├── planning.py   # 规划阶段
│   │       ├── drafting.py   # 起草阶段
│   │       ├── stitching.py  # 统稿阶段
│   │       ├── reviewing.py  # 审阅阶段
│   │       ├── refining.py   # 精修阶段
│   │       └── context.py     # 上下文组装
│   │
│   └── repositories/          # 数据访问层
│       ├── base.py           # 基础仓储
│       ├── book_repository.py
│       ├── chapter_repository.py
│       ├── character_repository.py
│       ├── memory_repository.py
│       └── ...
│
├── frontend/                   # ========== Vue 3 前端 ==========
│   ├── src/
│   │   ├── main.ts           # 入口文件
│   │   ├── App.vue           # 根组件
│   │   ├── style.css         # 全局样式
│   │   │
│   │   ├── components/       # 通用组件
│   │   │   ├── ChapterEditor.vue
│   │   │   ├── CharacterPanel.vue
│   │   │   ├── CritiquePanel.vue
│   │   │   ├── DebugPromptWindow.vue
│   │   │   ├── InspirationModal.vue
│   │   │   └── ...
│   │   │
│   │   ├── composables/     # Vue 组合式函数
│   │   │   ├── useAgenticConfig.ts
│   │   │   ├── useApi.ts
│   │   │   ├── useChapterGenerator.ts
│   │   │   └── ...
│   │   │
│   │   ├── features/        # 功能模块（分层架构）
│   │   │   ├── app/         # 应用级容器
│   │   │   ├── chapter-editor/  # 章节编辑器
│   │   │   └── character-panel/ # 角色面板
│   │   │
│   │   ├── services/        # 服务层
│   │   │   ├── api/         # API 封装
│   │   │   ├── domain/      # 业务语义适配
│   │   │   ├── stream/      # SSE 流处理
│   │   │   └── transport/   # HTTP 传输
│   │   │
│   │   ├── shared/          # 共享资源
│   │   │   ├── types/       # 类型定义
│   │   │   └── utils/       # 工具函数
│   │   │
│   │   └── extensions/      # TipTap 编辑器扩展
│   │
│   ├── electron/             # Electron 配置
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
│
├── data/                      # 运行时数据（端口文件等）
├── logs/                      # Prompt 日志
└── LICENSE                    # AGPL-3.0 许可证
```

---

## 架构设计

### 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│                      桌面应用层                              │
│                   (pywebview / Electron)                     │
├─────────────────────────────────────────────────────────────┤
│                      前端层 (Vue 3)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ 章节编辑器 │  │ 角色面板  │  │ 地图管理  │  │ 设置中心  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
│       └─────────────┴─────────────┴─────────────┘           │
│                         │                                    │
│              ┌──────────┴──────────┐                        │
│              │      服务层 (API)     │                        │
│              └──────────┬──────────┘                        │
├─────────────────────────────────────────────────────────────┤
│                      API 网关层 (FastAPI)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ CRUD API │  │ 生成 API  │  │ RAG API  │  │ 系统 API  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
├─────────────────────────────────────────────────────────────┤
│                      业务逻辑层                              │
│  ┌──────────────────────────────────────────────────┐      │
│  │              Agentic Workflow 引擎                │      │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐     │      │
│  │  │Planning │→│Drafting│→│Stitching│→│Reviewing│     │      │
│  │  └────────┘ └────────┘ └────────┘ └────────┘     │      │
│  │                      ↓                            │      │
│  │               ┌────────┐                          │      │
│  │               │Refining│←── (循环迭代)             │      │
│  │               └────────┘                          │      │
│  └──────────────────────────────────────────────────┘      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ 角色状态管理  │  │ Prompt 构建  │  │ LLM 调用封装 │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
├─────────────────────────────────────────────────────────────┤
│                      数据访问层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Books    │  │ Chapters │  │Characters│  │ Memories │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘    │
├─────────────────────────────────────────────────────────────┤
│                  PostgreSQL + pgvector                      │
└─────────────────────────────────────────────────────────────┘
```

### 前端分层架构约束

```
features/*/containers    → 状态整合、事件编排
         ↓
features/*/presentation  → 渲染、交互事件抛出
         ↓
services/domain          → 业务语义 API 适配
         ↓
services/transport       → 底层 HTTP 请求

✅ 允许：presentation → containers → services/domain
❌ 禁止：presentation → services/transport
```

---

## API 文档

### 系统接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/config` | 获取前端配置 |

### 书籍管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/books` | 获取书籍列表 |
| POST | `/api/books` | 创建书籍 |
| GET | `/api/books/{id}` | 获取书籍详情 |
| PUT | `/api/books/{id}` | 更新书籍 |
| DELETE | `/api/books/{id}` | 删除书籍 |

### 章节管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/chapters` | 获取章节列表 |
| POST | `/api/chapters` | 创建章节 |
| GET | `/api/chapters/{id}` | 获取章节详情 |
| PUT | `/api/chapters/{id}` | 更新章节 |
| DELETE | `/api/chapters/{id}` | 删除章节 |

### 角色管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/characters` | 获取角色列表 |
| POST | `/api/characters` | 创建角色 |
| GET | `/api/characters/{id}` | 获取角色详情 |
| PUT | `/api/characters/{id}` | 更新角色 |
| DELETE | `/api/characters/{id}` | 删除角色 |

### 章节生成

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/generate/chapter` | 基础章节生成 |
| POST | `/api/generate/chapter/agentic` | Agentic 智能生成 |
| POST | `/api/generate/chapter/optimize` | 章节优化 |
| POST | `/api/generate/inspiration` | 灵感生成 |

### 关系管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/relationships` | 获取关系列表 |
| POST | `/api/relationships` | 创建关系 |
| DELETE | `/api/relationships/{id}` | 删除关系 |

### 记忆系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/memories` | 获取记忆列表 |
| POST | `/api/memories` | 创建记忆 |
| DELETE | `/api/memories/{id}` | 删除记忆 |
| GET | `/api/memories/search` | 向量检索 |

> 详细 API 文档可访问 `/docs`（Swagger UI）或 `/redoc`（ReDoc）

---

## Agentic Workflow

### 工作流阶段详解

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ASSEMBLING_CONTEXT                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │
│  │  角色卡加载  │→│  关系网构建  │→│ RAG 记忆检索 │→│ 伏笔提取   │  │
│  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                           PLANNING                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐       │
│  │ StoryBeat 拆分   │  │ POV 角色分配    │  │ 字数分配计算    │       │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                          DRAFTING                                    │
│                    (并行 Beat 生成，并发度可配置)                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐    │
│  │ Beat 1  │  │ Beat 2  │  │ Beat 3  │  │ Beat 4  │  │ Beat N  │    │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘    │
│       └────────────┴────────────┴────────────┴────────────┘         │
│                              ↓                                        │
│                    Scene Intent 构建 + 质检                           │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                          STITCHING                                   │
│              合并所有 Beat 内容 → 完整章节草稿                         │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                          REVIEWING                                   │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐          │
│  │ 结构完整性检查   │  │ 角色一致性检查  │  │ 伏笔闭合检测    │          │
│  └────────────────┘  └────────────────┘  └────────────────┘          │
│                              ↓                                        │
│                    输出质检报告（revision_plan）                       │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
                          问题数量 ≤ 阈值？
                            ↙         ↘
                          是           否
                           ↓           ↓
                      [发布]     ┌─────────┐
                                │ REFINING│
                                └────┬────┘
                                     ↓
                            (最多 5 轮迭代)
```

### StoryBeat 结构

每个章节被拆分为多个 StoryBeat（剧情节拍）：

```json
{
  "id": "uuid",
  "beat_id": 1,
  "beat_type": "action|emotion|transition",
  "pacing": "fast|medium|slow",
  "pov_character_id": "uuid",
  "content": "节拍内容...",
  "word_count": 500,
  "scene_intent": "场景意图描述"
}
```

---

## 数据模型

### 实体关系图

```
Book (书籍)
├── Chapter (章节)
│   ├── StoryBeat (剧情节拍)
│   ├── SceneIntent (场景意图)
│   ├── ChapterEntity (章节-角色关联)
│   └── ChapterMapLocation (章节-地点关联)
├── Character (角色)
│   └── CharacterRelationship (角色关系)
├── MapLocation (地图地点)
├── MemoryChunk (向量记忆)
└── PlotLedger (情节账本/伏笔)
```

### 核心模型说明

| 模型 | 说明 | 关键字段 |
|------|------|----------|
| Book | 书籍根实体 | title, genre, worldview_settings, golden_snippets |
| Chapter | 章节 | chapter_number, draft_text, review_feedback, content_text, status |
| Character | 角色 | static_prompt, dynamic_state, dynamic_state_history |
| CharacterRelationship | 关系 | source_id, target_id, relationship_type, description |
| MemoryChunk | 向量记忆 | content, embedding (1536维), relevance_score |
| PlotLedger | 伏笔 | plot_point, status (open/closed/dropped), chapter_id |
| StoryBeat | 剧情节拍 | beat_type, pacing, pov_character_id, content |
| SceneIntent | 场景意图 | intent_description, emotional_goal, beat_id |

---

## 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `DATABASE_URL` | ✅ | - | PostgreSQL 连接字符串 |
| `DASHSCOPE_API_KEY` | ✅ | - | 阿里云 DashScope API Key |
| `OPENAI_API_KEY` | ❌ | - | OpenAI API Key（可选） |
| `PROXY_URL` | ❌ | `http://127.0.0.1:4780` | HTTP 代理地址 |
| `AGENTIC_BEAT_CONCURRENCY` | ❌ | `6` | Beat 并行生成数量 (1-12) |
| `AGENTIC_FORCE_FAST_MODE` | ❌ | `False` | 强制快速模式（减少迭代） |

### .env 示例

```env
# 数据库
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver

# API Keys
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

# 代理
PROXY_URL=http://127.0.0.1:4780

# 工作流
AGENTIC_BEAT_CONCURRENCY=6
AGENTIC_FORCE_FAST_MODE=false
```

---

## 常用命令

### 后端开发

```bash
# 启动开发服务器（默认端口 8002）
python backend/main.py

# 运行测试脚本
python test_critique_fix.py

# 数据库调试（启用 SQL 日志）
# 编辑 database.py，设置 echo=True
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器（Vite）
npm run dev

# 类型检查
npm run typecheck

# 构建生产版本
npm run build

# 运行单元测试
npm run test:agentic-config
```

### Electron 桌面应用

```bash
cd frontend

# 开发模式
npm run electron:dev

# 预览模式
npm run electron:preview

# 构建安装包
npm run electron:build
```

---

## 调试指南

### 查看 LLM Prompt

1. **Debug 窗口**：启动应用时自动打开，显示所有发送的 Prompt
2. **开发者工具**：主窗口按 `F12` 打开
3. **日志文件**：`logs/prompt_log_*.json`

### 日志位置

| 类型 | 位置 |
|------|------|
| 后端日志 | 控制台输出 |
| 前端日志 | 浏览器开发者工具 |
| Prompt 日志 | `logs/` 目录 |
| 数据库日志 | `database.py` 设置 `echo=True` |

### 常见问题排查

**数据库连接失败**
```bash
psql -d storyweaver -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**端口冲突**
- 后端使用动态端口（开发时写入 `data/port.txt`）
- Vite 开发服务器检查 5173-5176 端口

**编码问题**
- 后端已强制 UTF-8 编码
- Windows 终端需确保代码页为 UTF-8：`chcp 65001`

---

## 常见问题

### Q: 如何配置 LLM 提供商？

支持 OpenAI 和 DashScope，通过环境变量配置：
```env
DASHSCOPE_API_KEY=your_key  # 优先使用
OPENAI_API_KEY=your_key     # 备选
```

### Q: 支持哪些数据库？

目前仅支持 PostgreSQL 14+（需要 pgvector 扩展支持向量检索）。

### Q: 如何自定义 Prompt 模板？

编辑 `backend/services/prompts/` 目录下的模板文件。

### Q: Beat 并行度如何调整？

通过环境变量 `AGENTIC_BEAT_CONCURRENCY` 设置，范围 1-12。

---

## 安全注意事项

1. **API Key 安全**
   - 前端传入的 Key 不存储到数据库
   - 日志中脱敏处理
   - Embedding Key 仅从环境变量读取

2. **代理配置**
   - 默认使用本地代理 `127.0.0.1:4780`
   - 可通过 `PROXY_URL` 环境变量覆盖

3. **CORS 策略**
   - 开发环境允许所有来源
   - 生产环境应指定具体域名

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

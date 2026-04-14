<!-- From: D:\qoder\Velluma\AGENTS.md -->
# Velluma AI 小说写作助手 - Agent 开发指南

## 项目概述

Velluma（原 StoryWeaver-Core）是一个 AI 驱动的长篇小说写作助手桌面应用。它采用 Agentic Workflow（智能体工作流）架构，通过多轮迭代生成高质量小说章节内容。

**核心价值主张：**
- 专为长篇小说创作设计的 AI 辅助工具
- 支持角色状态追踪、关系图谱、伏笔管理
- 基于 RAG（检索增强生成）的记忆系统
- 多 Agent 协作：规划 → 起草 → 审阅 → 精修

**许可证：** AGPL-3.0

---

## 技术栈

### 后端 (`backend/`)
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.109.0 |
| ORM | SQLAlchemy | 2.0.25 (异步) |
| 数据库 | PostgreSQL + pgvector | 14+ |
| 驱动 | asyncpg | 0.29.0 |
| LLM | OpenAI SDK / DashScope | - |
| 服务器 | Uvicorn | 0.27.0 |
| 其他 | pydantic, tenacity, python-dotenv, python-multipart | - |

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
├── start.bat                 # Windows 启动入口（调用 start.ps1）
├── start.ps1                 # PowerShell 启动脚本：依次启动后端 → Vite → Electron
├── requirements.txt          # Python 依赖
│
├── backend/                  # FastAPI 后端
│   ├── main.py              # 应用入口、路由注册、静态文件服务、CORS
│   ├── models.py            # SQLAlchemy ORM 模型（Book/Chapter/Character/MemoryChunk 等）
│   ├── database.py          # 异步引擎、会话、启动时自动迁移（MIGRATIONS 列表）
│   ├── world_state_schemas.py
│   ├── models_generation_task.py
│   │
│   ├── core/                # 核心基础设施
│   │   ├── config.py        # 端口持久化、推理模型支持列表
│   │   ├── dependencies.py  # 仓储层依赖注入
│   │   └── exceptions.py
│   │
│   ├── config/              # V4.0 统一配置推导层
│   │   ├── derivation.py    # GenerationConfig 构建与推导
│   │   ├── intent_driven.py # 意图驱动配置
│   │   ├── engine.py
│   │   ├── mapper.py
│   │   ├── rules.py
│   │   └── PARAMETER_MAPPING.md  # 参数映射文档（必读）
│   │
│   ├── routes/              # API 路由层（17 个模块）
│   │   ├── books.py
│   │   ├── chapters.py
│   │   ├── chapter_entities.py
│   │   ├── chapter_generation.py      # 章节生成 API（含 SSE 流式）
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
│       │   ├── embedding.py
│       │   ├── proxy.py
│       │   └── formatting.py
│       │
│       ├── generation/      # 生成服务入口
│       │   ├── chapter.py
│       │   ├── character_extraction.py
│       │   ├── inspiration.py
│       │   ├── memory_scorer.py
│       │   └── publish.py
│       │
│       ├── orchestration/   # 工作流编排
│       │   ├── agentic.py   # 核心 Agentic 工作流编排器
│       │   ├── beat_manager.py
│       │   └── tier_mapper.py
│       │
│       ├── prompts/         # Prompt 模板库（20+ 文件）
│       │   ├── planner_prompts.py
│       │   ├── draft_prompts.py
│       │   ├── review_prompts.py
│       │   ├── stitch_prompts.py
│       │   ├── scene_intent_prompts.py
│       │   ├── world_state_prompts.py
│       │   └── ...
│       │
│       ├── rag/             # RAG 检索系统
│       │   ├── retriever.py
│       │   ├── scoring.py
│       │   ├── context_assembly.py
│       │   ├── retrieval_orchestrator.py
│       │   ├── workflow_integration.py
│       │   ├── enhanced/
│       │   └── tests/
│       │
│       ├── state_machine/   # 角色状态机
│       │   ├── character_state.py
│       │   ├── character_state_machine.py
│       │   └── relationship_state.py
│       │
│       ├── validation/      # 质检与修复
│       │   ├── chapter_reviewer.py
│       │   ├── chapter_repairer.py
│       │   ├── review_repair.py
│       │   └── pre_generation_checklist.py
│       │
│       ├── workflows/       # 工作流子阶段实现
│       │   ├── planning.py
│       │   ├── drafting.py
│       │   ├── drafting_prose.py
│       │   ├── stitching.py
│       │   ├── reviewing.py
│       │   ├── refining.py
│       │   ├── dual_track.py          # 双轨生成入口
│       │   ├── sketch_generator.py
│       │   ├── adversarial_aligner.py
│       │   ├── drafting_core/         # 起草核心子模块
│       │   │   ├── prose_generation.py
│       │   │   ├── quality/
│       │   │   ├── retry/
│       │   │   └── strategies/
│       │   └── dual_track/            # 双轨子模块
│       │       ├── tracks/
│       │       ├── alignment/
│       │       └── config/
│       │
│       ├── world/           # 世界状态服务
│       │   └── state_service.py
│       │
│       └── utils/           # 工具函数
│           ├── sse.py
│           ├── prompt_logger.py
│           ├── sanitizer.py
│           ├── timeout.py
│           └── logging.py
│
├── frontend/                 # Vue 3 前端
│   ├── package.json
│   ├── vite.config.js       # Vite 配置（含后端代理 /api）
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   ├── electron/
│   │   ├── main.cjs         # Electron 主进程（启动后端、Vite、窗口管理）
│   │   └── preload.cjs
│   └── src/
│       ├── main.ts
│       ├── App.vue
│       ├── style.css
│       ├── components/      # 通用组件
│       ├── composables/     # Vue 组合式函数
│       ├── extensions/      # TipTap 扩展
│       ├── features/        # 功能模块（分层架构）
│       │   ├── app/                   # 应用级容器（AppContainer.vue）
│       │   ├── chapter-editor/        # 章节编辑器
│       │   ├── character-panel/       # 角色面板
│       │   ├── asset-panel/           # 资产面板
│       │   ├── intent-driven/         # 意图驱动（V4.0）
│       │   └── novel-wizard/          # 小说创建向导
│       ├── services/        # 服务层
│       │   ├── api/domain/  # 业务语义 API 适配
│       │   ├── api/stream/  # SSE 流处理
│       │   └── api/transport/ # 底层 HTTP 请求
│       ├── shared/          # 共享资源
│       │   ├── types/
│       │   └── utils/
│       └── types/
│
├── data/                    # 运行时数据（端口持久化等，gitignore）
├── logs/                    # Prompt 日志（gitignore）
├── scripts/                 # 启动脚本副本
└── .venv/                   # Python 虚拟环境
```

---

## 运行与构建

### 环境要求
- Python 3.12+
- Node.js 18+
- PostgreSQL 14+（需启用 pgvector 扩展）

### 后端开发

```powershell
# 1. 激活虚拟环境
.venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量（项目根目录创建 .env）
# 见下文"环境变量"章节

# 4. 启动开发服务器
python backend/main.py
# 默认端口: 8002，若被占用则自动扫描 8002~8100
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
```

### 桌面应用运行（推荐开发方式）

项目使用 **Electron** 作为桌面容器。主启动脚本 `start.ps1` 会依次启动后端、Vite 开发服务器、Electron，并在退出时自动清理所有进程。

```powershell
# 完整启动（后端 + 前端 Vite + Electron）
.\start.bat
# 或
.\start.ps1

# 强制模式（清理端口冲突后启动）
.\start.bat -Force

# 只启动 Electron（假设前后端已在运行）
.\start.ps1 -ElectronOnly

# 跳过后端启动
.\start.ps1 -SkipBackend
```

**Electron 独立命令（在 frontend 目录下）：**
```bash
cd frontend
npm run electron:dev      # 开发模式
npm run electron:preview  # 预览模式
npm run electron:build    # 打包安装包（electron-builder）
```

> 注意：`app.py`（pywebview 入口）在代码库中已不存在，README 中的相关描述已过时。当前请以 `start.ps1` + Electron 为默认运行方式。

---

## 核心架构

### Agentic Workflow 工作流

章节生成的核心流程，最多支持 5 轮迭代：

1. **ASSEMBLING_CONTEXT** - 组装上下文
   - 加载角色卡、关系网
   - RAG 检索相关记忆
   - 提取前文摘要和开放伏笔

2. **PLANNING** - 规划节拍
   - Planner Agent 将大纲拆分为 StoryBeat
   - 自动分配 POV 角色、字数分配

3. **DRAFTING** - 并行起草
   - 每个 Beat 独立生成（并发控制：`AGENTIC_BEAT_CONCURRENCY`）
   - 包含 Scene Intent 构建和自动质检
   - 支持 Fast/Medium/Slow 节奏类型

4. **STITCHING** - 统稿
   - 合并所有 Beat 内容为完整章节草稿

5. **REVIEWING** - 审阅
   - Review Agent 检查结构、角色一致性、伏笔闭合
   - 输出结构化质检报告（`revision_plan`）

6. **REFINING** - 精修（可选）
   - 基于 revision_plan 重写
   - 支持跳过仅轻微问题的章节

### 双轨对抗架构 (V4.0)

为解决并行生成连贯性差的问题，引入双轨架构：

**核心思想**：并行生成 + 连贯性锚定

```
Track A: 节拍扩写              Track B: 短文生成
├─ Beat[1] → Text[1]           ├─ 基于 Beats 生成连贯速写
├─ Beat[2] → Text[2]           │   (40-50% 字数，连续叙述)
└─ Beat[N] → Text[N]           └─ 输出: Sketch + 转折点映射
         ↓                              ↓
         └──────────┬────────────────────┘
                    ↓
            统稿 → Draft_A
                    ↓
            对抗校对 (Adversarial Alignment)
            Draft_A vs Sketch → 差异检测
                    ↓
            融合精修 (可选)
```

**关键组件**：
- `SketchGenerator`: 生成连贯速写，提供连贯性锚点
- `AdversarialAligner`: 对比 Draft 和 Sketch，检测结构/情绪/信息差异
- 实现代码主要位于 `backend/services/workflows/dual_track/`

**API 端点**：
- `POST /api/chapters/{id}/generate-dual-track` - 流式双轨生成
- `POST /api/chapters/{id}/generate-dual-track-simple` - 非流式

### 数据模型层级

```
Book (书籍)
├── Chapter (章节)
│   ├── StoryBeat (剧情节拍) - 最小剧情单元
│   ├── SceneIntent (场景意图) - Beat 内的生成指令
│   ├── ChapterEntity (章节-角色关联)
│   └── ChapterMapLocation (章节-地点关联)
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
└── GenerationTask (异步生成任务)
```

### RAG 记忆检索

使用 Embedding API 生成 1536 维向量（OpenAI text-embedding-3-small 或 DashScope）：
- **alpha**: 语义相似度权重 (默认 0.6)
- **beta**: 时间衰减权重 (默认 0.2)
- **gamma**: 剧情伏笔权重 (默认 0.2)
- **lambda_decay**: 时间衰减系数

检索范围限制在当前章节之前，避免未来信息泄露。

---

## 数据库与迁移

项目使用**启动时自动迁移**（非 Alembic）。`backend/database.py` 中的 `MIGRATIONS` 列表定义了所有增量列变更，启动时会通过 `init_db()` 自动检查并添加缺失列。

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

**文件头**：所有 `.py` 文件必须包含 AGPL-3.0 许可证头。

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
services/domain         → 业务语义 API 适配
services/stream         → SSE 流处理
services/transport      → 底层 HTTP 请求
shared/types            → 跨模块类型
shared/utils            → 纯函数工具
```

**依赖方向**：
- ✅ `presentation -> 容器 props/emits`
- ✅ `containers -> services/domain`
- ❌ `presentation -> services/transport` (禁止)

**命名规范**：
- Feature 目录: `kebab-case`
- 容器组件: `*Container.vue`
- 展示组件: `*View.vue` 或 `*Panel.vue`

---

## 环境变量

在项目根目录创建 `.env` 文件：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver` |
| `DASHSCOPE_API_KEY` | 阿里云 Embedding / LLM API Key | - |
| `OPENAI_API_KEY` | OpenAI API Key | - |
| `PROXY_URL` | HTTP 代理地址 | `http://127.0.0.1:4780` |
| `AGENTIC_BEAT_CONCURRENCY` | Beat 并行度 | 6 |
| `AGENTIC_FORCE_FAST_MODE` | 强制快速模式 | False |
| `DB_POOL_PRE_PING` | 连接池预检（Windows 默认 false） | 平台相关 |

---

## 测试策略

### 当前状态
项目处于快速迭代期，**测试覆盖非常有限**。主要测试方式以手动验证和脚本测试为主。

**已有测试**：
- 前端组合式函数测试：`npm run test:agentic-config`
  - 编译 TS 测试文件并调用 Node.js test runner
- 后端 RAG 集成测试：`backend/services/rag/tests/`
- Prompt 边界测试：`backend/services/prompts/test_boundary_pacing_prompts.py`

**开发时验证**：
- 后端：使用 `/api/health` 健康检查
- 前端：浏览器开发者工具 + Vue DevTools
- LLM: Debug Prompt 窗口显示所有发送的 Prompt（`logs/` 目录保留历史）

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
- 端口协商机制（`data/port.txt`）仅适用于本地开发，生产环境应使用固定端口

---

## 安全注意事项

1. **API Key 处理**
   - 前端传入的 API Key **不存储到数据库**
   - 日志中不应打印完整的 API Key
   - Embedding API Key 只从环境变量 `DASHSCOPE_API_KEY` 读取

2. **代理配置**
   - 默认使用本地代理 (`http://127.0.0.1:4780`)
   - 可通过环境变量 `PROXY_URL` 覆盖

3. **CORS 策略**
   - 开发环境允许所有来源 (`allow_origins=["*"]`)
   - 生产环境应指定具体域名列表

---

## Agent 开发速查

### 添加新的 API 端点

1. 在 `backend/schemas/` 定义 Request/Response 模型
2. 在 `backend/routes/` 创建/修改路由文件
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
4. 通过 `services/domain` 层与后端通信

---

*最后更新: 2026-04-15*

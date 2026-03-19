# Velluma AI 小说写作助手 - Agent 开发指南

## 项目概述

Velluma（原 StoryWeaver-Core）是一个 AI 驱动的长篇小说写作助手桌面应用。它采用 Agentic Workflow（智能体工作流）架构，通过多轮迭代生成高质量小说章节内容。

**核心价值主张：**
- 专为长篇小说创作设计的 AI 辅助工具
- 支持角色状态追踪、关系图谱、伏笔管理
- 基于 RAG（检索增强生成）的记忆系统
- 多 Agent 协作：规划 → 起草 → 审阅 → 精修

## 技术栈

### 后端 (backend/)
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.109.0 |
| ORM | SQLAlchemy | 2.0.25 (异步) |
| 数据库 | PostgreSQL + pgvector | - |
| 驱动 | asyncpg | 0.29.0 |
| LLM | OpenAI SDK / DashScope | - |
| 服务器 | Uvicorn | 0.27.0 |

### 前端 (frontend/)
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3 | ^3.4.15 |
| 语言 | TypeScript | ^5.9.3 |
| 构建 | Vite | ^5.0.12 |
| 样式 | Tailwind CSS | ^3.4.1 |
| 编辑器 | TipTap | ^2.24.0 |
| 桌面 | pywebview / Electron | ^4.4.1 / ^28.3.3 |

## 项目结构

```
Velluma/
├── app.py                    # 桌面应用入口 (pywebview)
├── backend/                  # FastAPI 后端
│   ├── main.py              # 应用入口、路由注册、静态文件
│   ├── models.py            # SQLAlchemy ORM 模型
│   ├── schemas.py           # Pydantic 请求/响应模型
│   ├── database.py          # 数据库连接、迁移
│   ├── core/                # 核心配置
│   │   ├── config.py        # 端口持久化等配置
│   │   └── dependencies.py  # 依赖注入
│   ├── routes/              # API 路由
│   │   ├── books.py         # 书籍 CRUD
│   │   ├── chapters.py      # 章节 CRUD
│   │   ├── characters.py    # 角色管理
│   │   ├── relationships.py # 角色关系
│   │   ├── memories.py      # 向量记忆
│   │   ├── chapter_generation.py  # Agentic 生成
│   │   └── ...
│   ├── services/            # 业务逻辑层
│   │   ├── agentic_workflow.py    # 核心工作流编排
│   │   ├── llm_client.py          # LLM 调用封装
│   │   ├── character_state.py     # 角色状态管理
│   │   ├── prompt_builder.py      # Prompt 构建
│   │   ├── prompts/               # Prompt 模板
│   │   │   ├── planner_prompts.py
│   │   │   ├── draft_prompts.py
│   │   │   └── ...
│   │   └── workflows/             # 工作流子模块
│   │       ├── planning.py
│   │       ├── drafting.py
│   │       ├── reviewing.py
│   │       └── ...
│   └── repositories/        # 数据访问层
│       ├── base.py
│       ├── book_repository.py
│       └── ...
├── frontend/                # Vue 3 前端
│   ├── src/
│   │   ├── main.ts         # 入口
│   │   ├── App.vue         # 根组件
│   │   ├── features/       # 功能模块 (分层架构)
│   │   │   ├── app/        # 应用级容器
│   │   │   ├── chapter-editor/
│   │   │   └── character-panel/
│   │   ├── services/       # 服务层
│   │   │   ├── api/        # API 封装
│   │   │   ├── domain/     # 业务语义适配
│   │   │   ├── stream/     # SSE 流处理
│   │   │   └── transport/  # 底层请求
│   │   ├── shared/         # 共享资源
│   │   │   ├── types/      # 类型定义
│   │   │   └── utils/      # 工具函数
│   │   ├── components/     # 通用组件
│   │   └── composables/    # Vue 组合式函数
│   ├── electron/           # Electron 配置
│   └── package.json
├── data/                   # 运行时数据 (gitignore)
├── tests/                  # 测试目录 (预留)
└── .venv/                  # Python 虚拟环境
```

## 运行与构建

### 环境要求
- Python 3.12+
- Node.js 18+
- PostgreSQL 14+ (需启用 pgvector 扩展)

### 后端开发

```bash
# 1. 激活虚拟环境
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp backend/.env.example .env
# 编辑 .env 设置 DATABASE_URL

# 4. 启动开发服务器
python backend/main.py
# 默认端口: 8002
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
# 默认端口: 5173

# 类型检查
npm run typecheck

# 构建生产版本
npm run build
```

### 桌面应用运行

```bash
# 方式1: pywebview (推荐，轻量)
python app.py

# 方式2: pywebview 开发模式
python app.py --dev

# 方式3: Electron
cd frontend
npm run electron:dev
```

### 数据库迁移

项目使用启动时自动迁移（非 Alembic）:

```python
# database.py 中的 MIGRATIONS 列表定义了所有迁移
# 启动时会自动检查并添加缺失列
```

**手动执行 SQL 迁移:**
```sql
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;

-- 主要表结构由 SQLAlchemy 自动创建
-- 列变更见 backend/database.py 中的 MIGRATIONS
```

## 核心概念

### Agentic Workflow 工作流

章节生成的核心流程，最多支持 5 轮迭代：

1. **ASSEMBLING_CONTEXT** - 组装上下文
   - 加载角色卡、关系网
   - RAG 检索相关记忆
   - 提取前文摘要和开放伏笔

2. **PLANNING** - 规划节拍
   - Planner Agent 将大纲拆分为 StoryBeat
   - 自动分配 POV 角色
   - 计算字数分配

3. **DRAFTING** - 并行起草
   - 每个 Beat 独立生成（并发控制：AGENTIC_BEAT_CONCURRENCY）
   - 包含 Scene Intent 构建和自动质检
   - 支持 Fast/Medium/Slow 节奏类型

4. **STITCHING** - 统稿
   - 合并所有 Beat 内容为完整章节

5. **REVIEWING** - 审阅
   - Review Agent 检查结构、角色一致性、伏笔闭合
   - 输出结构化质检报告

6. **REFINING** - 精修（可选）
   - 基于 revision_plan 重写
   - 支持跳过仅轻微问题的章节

### 数据模型层级

```
Book (书籍)
├── Chapter (章节)
│   ├── StoryBeat (剧情节拍) - 最小剧情单元
│   ├── SceneIntent (场景意图) - Beat 内的生成指令
│   ├── ChapterEntity (章节-角色关联)
│   └── ChapterMapLocation (章节-地点关联)
├── Character (角色)
│   ├── static_prompt - 永恒设定
│   ├── dynamic_state - 瞬时状态
│   ├── dynamic_state_history - 状态历史
│   └── CharacterRelationship (角色关系)
├── MemoryChunk (向量记忆)
├── PlotLedger (情节账本/伏笔)
└── MapLocation (地图地点)
```

### RAG 记忆检索

使用 DashScope Embedding API 生成 1536 维向量：
- **alpha**: 语义相似度权重 (默认 0.6)
- **beta**: 时间衰减权重 (默认 0.2)
- **gamma**: 剧情伏笔权重 (默认 0.2)
- **lambda_decay**: 时间衰减系数

检索范围限制在当前章节之前，避免未来信息泄露。

## 代码规范

### Python 后端

**文档字符串规范：**
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

**注释风格：**
- 模块顶部使用 `====` 分隔线划分段落
- 关键逻辑前添加设计意图注释
- 副作用必须标注警示

**错误处理：**
- 使用 tenacity 进行指数退避重试
- LLM 调用失败静默返回空字符串（避免上层崩溃）
- 流式输出错误时发送 error 帧 + done 帧

### TypeScript 前端

**分层架构约束：**

```
features/*/containers   -> 状态整合、事件编排
features/*/presentation -> 渲染、交互事件抛出
services/domain         -> 业务语义 API 适配
services/stream         -> SSE 流处理
services/transport      -> 底层 HTTP 请求
shared/types            -> 跨模块类型
shared/utils            -> 纯函数工具
```

**依赖方向：**
- ✅ `presentation -> 容器 props/emits`
- ✅ `containers -> services/domain`
- ❌ `presentation -> services/transport` (禁止)

**命名规范：**
- Feature 目录: kebab-case
- 容器组件: `*Container.vue`
- 展示组件: `*View.vue` 或 `*Panel.vue`

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| DATABASE_URL | PostgreSQL 连接字符串 | postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver |
| DASHSCOPE_API_KEY | 阿里云 Embedding API Key | - |
| PROXY_URL | HTTP 代理地址 | http://127.0.0.1:4780 |
| AGENTIC_BEAT_CONCURRENCY | Beat 并行度 | 6 |
| AGENTIC_FORCE_FAST_MODE | 强制快速模式 | False |

## 测试策略

### 当前状态
项目处于快速迭代期，测试覆盖有限。主要测试方式：

**手动测试：**
```bash
# 运行 API 测试脚本
python test_critique_fix.py

# 前端组合式函数测试
npm run test:agentic-config
```

**开发时验证：**
- 后端：使用 `/api/health` 健康检查
- 前端：浏览器开发者工具 + Vue DevTools
- LLM: Debug Prompt 窗口显示所有发送的 Prompt

### 测试文件位置
- `test_*.py` - 项目根目录的 Python 测试脚本
- `frontend/.test-dist/` - TypeScript 测试编译输出 (临时)

## 调试技巧

### 查看 Prompt
1. 启动应用时会自动打开 Debug 窗口
2. 或在主窗口按 F12 打开开发者工具
3. 所有 LLM Prompt 通过 SSE 发送到 debug 窗口

### 日志位置
- 后端日志：控制台输出
- 前端日志：浏览器控制台
- 数据库日志：设置 `echo=True` 在 database.py

### 常见问题

**数据库连接失败：**
```bash
# 检查 pgvector 扩展
psql -d storyweaver -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

**端口冲突：**
- 后端使用动态端口（开发时写入 data/port.txt）
- Electron 开发模式使用固定端口 8002 (后端) 和 5175 (Vite)

**编码问题：**
- 后端已强制设置 UTF-8 编码 (main.py)
- Windows 终端需确保代码页为 UTF-8

## 安全注意事项

1. **API Key 处理**
   - 前端传入的 API Key 不存储到数据库
   - 日志中不应打印完整的 API Key
   - Embedding API Key 只从环境变量读取

2. **代理配置**
   - 默认使用本地代理 (127.0.0.1:4780)
   - 可通过环境变量 `PROXY_URL` 覆盖
   - 支持运行时开关代理

3. **CORS 策略**
   - 开发环境允许所有来源 (`allow_origins=["*"]`)
   - 生产环境应指定具体域名

## 扩展开发指南

### 添加新的 Agent 阶段

1. 在 `backend/services/prompts/` 创建新的 prompt 模板
2. 在 `backend/services/workflows/` 实现阶段逻辑
3. 在 `backend/services/agentic_workflow.py` 的工作流中集成
4. 更新前端事件类型（如需要）

### 添加新的 API 端点

1. 在 `backend/schemas.py` 定义 Request/Response 模型
2. 在 `backend/routes/` 创建路由文件
3. 在 `backend/main.py` 注册路由
4. 前端在 `services/api/domain/` 添加对应调用

### 前端添加新 Feature

1. 在 `features/` 创建目录结构
2. 按 `containers/` + `presentation/` 分层
3. 在 `index.ts` 导出公共接口
4. 通过 `services/` 层与后端通信

---

*最后更新: 2026-03-19*

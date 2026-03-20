# Velluma AI 小说写作助手

> 📝 专为长篇小说创作设计的 AI 驱动写作助手，采用 Agentic Workflow 智能体工作流架构

---

## 项目简介

Velluma 是一个 AI 驱动的长篇小说写作助手桌面应用，通过多轮迭代生成高质量小说章节内容。它专为长篇叙事设计，支持角色状态追踪、关系图谱、伏笔管理等高级功能。

### 核心特性

- 🤖 **Agentic Workflow 工作流** - 规划 → 起草 → 统稿 → 审阅 → 精修，最多支持 5 轮迭代
- 👤 **角色状态追踪** - 动态维护角色状态与历史，确保叙事一致性
- 🔗 **关系图谱** - 可视化角色关系网络
- 🧠 **RAG 记忆系统** - 基于向量检索的智能记忆，避免未来信息泄露
- 📊 **情节账本** - 伏笔追踪与管理，自动检测伏笔闭合
- 💻 **桌面应用** - 支持 pywebview（轻量）和 Electron（完整）两种模式

---

## 技术栈

### 后端
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | FastAPI | 0.109.0 |
| ORM | SQLAlchemy | 2.0.25 (异步) |
| 数据库 | PostgreSQL + pgvector | - |
| 驱动 | asyncpg | 0.29.0 |
| LLM | OpenAI SDK / DashScope | - |
| 服务器 | Uvicorn | 0.27.0 |

### 前端
| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | Vue 3 | ^3.4.15 |
| 语言 | TypeScript | ^5.9.3 |
| 构建 | Vite | ^5.0.12 |
| 样式 | Tailwind CSS | ^3.4.1 |
| 编辑器 | TipTap | ^2.24.0 |
| 桌面 | pywebview / Electron | ^4.4.1 / ^28.3.3 |

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

### 2. 后端配置

```bash
# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境（Windows）
.venv\Scripts\activate
# 激活虚拟环境（Linux/Mac）
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 设置 DATABASE_URL 和 API Keys
```

### 3. 前端配置

```bash
cd frontend

# 安装依赖
npm install

# 返回项目根目录
cd ..
```

### 4. 数据库初始化

```sql
-- 启用 pgvector 扩展
CREATE EXTENSION IF NOT EXISTS vector;
```

### 5. 运行应用

**方式一：pywebview 桌面模式（推荐）**
```bash
# 启动桌面应用
python app.py

# 开发模式（连接 Vite 开发服务器）
python app.py --dev
```

**方式二：分离启动**
```bash
# 终端 1：启动后端
python backend/main.py

# 终端 2：启动前端
cd frontend
npm run dev
```

**方式三：Electron 模式**
```bash
cd frontend
npm run electron:dev
```

---

## 项目结构

```
Velluma/
├── app.py                    # 桌面应用入口 (pywebview)
├── backend/                  # FastAPI 后端
│   ├── main.py              # 应用入口
│   ├── models.py            # SQLAlchemy ORM 模型
│   ├── schemas.py           # Pydantic 数据模型
│   ├── database.py          # 数据库连接
│   ├── routes/              # API 路由
│   ├── services/            # 业务逻辑
│   │   ├── agentic_workflow.py    # 核心工作流
│   │   ├── workflows/             # 工作流子模块
│   │   └── prompts/               # Prompt 模板
│   └── repositories/        # 数据访问层
├── frontend/                # Vue 3 前端
│   ├── src/
│   │   ├── features/        # 功能模块（分层架构）
│   │   ├── services/        # 服务层
│   │   ├── shared/          # 共享资源
│   │   └── components/      # 通用组件
│   └── electron/            # Electron 配置
└── data/                    # 运行时数据
```

---

## Agentic Workflow 工作流

章节生成的核心流程：

1. **ASSEMBLING_CONTEXT** - 组装上下文
   - 加载角色卡、关系网
   - RAG 检索相关记忆
   - 提取前文摘要和开放伏笔

2. **PLANNING** - 规划节拍
   - Planner Agent 将大纲拆分为 StoryBeat
   - 自动分配 POV 角色
   - 计算字数分配

3. **DRAFTING** - 并行起草
   - 每个 Beat 独立生成（并发控制）
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

---

## 环境变量配置

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接字符串 | `postgresql+asyncpg://postgres:postgres@localhost:5432/storyweaver` |
| `DASHSCOPE_API_KEY` | 阿里云 Embedding API Key | - |
| `PROXY_URL` | HTTP 代理地址 | `http://127.0.0.1:4780` |
| `AGENTIC_BEAT_CONCURRENCY` | Beat 并行度 | 6 |
| `AGENTIC_FORCE_FAST_MODE` | 强制快速模式 | False |

---

## 常用命令

### 后端开发
```bash
# 启动开发服务器
python backend/main.py

# 运行测试脚本
python test_critique_fix.py
```

### 前端开发
```bash
cd frontend

# 启动开发服务器
npm run dev

# 类型检查
npm run typecheck

# 构建生产版本
npm run build

# 运行组合式函数测试
npm run test:agentic-config
```

### Electron
```bash
cd frontend

# 开发模式
npm run electron:dev

# 构建安装包
npm run electron:build
```

---

## 调试技巧

### 查看 Prompt
1. 启动应用时会自动打开 Debug 窗口
2. 或在主窗口按 F12 打开开发者工具
3. 所有 LLM Prompt 通过 SSE 发送到 debug 窗口

### 日志位置
- 后端日志：控制台输出
- 前端日志：浏览器开发者工具
- 数据库日志：设置 `echo=True` 在 database.py

---

## 安全注意事项

1. **API Key 处理**
   - 前端传入的 API Key 不存储到数据库
   - 日志中不应打印完整的 API Key
   - Embedding API Key 只从环境变量读取

2. **代理配置**
   - 默认使用本地代理 (`127.0.0.1:4780`)
   - 可通过环境变量 `PROXY_URL` 覆盖

3. **CORS 策略**
   - 开发环境允许所有来源
   - 生产环境应指定具体域名

---

## 许可证

[MIT License](LICENSE)

---

## 贡献

欢迎提交 Issue 和 Pull Request！

如有问题，请通过 [Issues](https://github.com/your-repo/issues) 反馈。

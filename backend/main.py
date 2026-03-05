import io
import os
import sys
from contextlib import asynccontextmanager

from dotenv import load_dotenv

# 加载环境变量
# 确保在导入其他模块之前加载，以便 database.py 等模块能正确获取配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    print(f"[Main] Loading environment variables from {ENV_PATH}")
    load_dotenv(ENV_PATH)
else:
    print(f"[Main] Warning: .env file not found at {ENV_PATH}")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.core.config import save_port as _save_port
from backend.database import init_db
from backend.routes import (
    books_router,
    chapters_router,
    characters_router,
    relationships_router,
    memories_router,
    generate_router,
    system_router,
)

# =============================================================================
# 启动阶段：解决终端编码问题
# =============================================================================
# 原因：某些部署环境（Docker、WSL、Windows）的 stdout/stderr 默认编码可能不是 UTF-8，
# 这会导致中文日志输出时抛出 UnicodeEncodeError
# 副作用：将所有输出流强制重定向为 UTF-8 编码
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


# =============================================================================
# 端口持久化机制
# =============================================================================
# 用途：开发时动态切换端口后，前端需要知道后端的实际端口以便连接
# 数据流：uvicorn 启动时传入端口 → save_port() 写入文件 → 前端读取文件获取端口
# 警示：此机制仅适用于本地开发，生产环境应使用固定端口或环境变量
def save_port(port: int):
    _save_port(port)


# =============================================================================
# 应用生命周期管理
# =============================================================================
# 用途：管理数据库连接的启动和关闭
# 副作用：FastAPI 在应用启动时自动执行 init_db()，在关闭时自动清理资源
@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动阶段：初始化数据库（创建表结构、连接池）
    await init_db()
    yield
    # 关闭阶段：由 asynccontextmanager 自动处理资源清理


# =============================================================================
# FastAPI 应用实例化
# =============================================================================
# 业务含义：StoryWeaver-Core 是一个长篇小说特化 AI 写作平台
# 生命周期：lifespan 参数确保数据库在应用启动时已就绪
app = FastAPI(
    title="StoryWeaver-Core API",
    description="长篇小说特化 AI 写作平台后端引擎",
    version="1.0.0",
    lifespan=lifespan,
)

# =============================================================================
# 中间件注册
# =============================================================================
# CORS 策略：
# - allow_origins=["*"]：允许所有域名访问（开发环境便利性）
# - allow_credentials=True：允许携带 Cookie/Authorization（需要限制 origin 时慎用）
# - 副作用：OPTIONS 预检请求会自动返回 CORS 头，无需手动处理
# 警示：生产环境应指定具体域名列表，避免公开 API 被滥用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# 路由注册
# =============================================================================
# 顺序考量：system_router 放在最前，优先处理健康检查等系统级请求
# 业务路由按模块划分：书籍 → 章节 → 角色 → 关系 → 记忆 → 生成
# 副作用：所有路由的依赖注入（如 get_db）会在请求进入时自动执行
app.include_router(system_router)
app.include_router(books_router)
app.include_router(chapters_router)
app.include_router(characters_router)
app.include_router(relationships_router)
app.include_router(memories_router)
app.include_router(generate_router)

# =============================================================================
# 前端静态文件服务（SPA 路由处理）
# =============================================================================
# 用途：将打包后的前端资源与后端一起托管，实现前后端同源部署
# 数据流：前端构建产物位于 frontend/dist/，后端根据请求路径返回对应文件
# 关键逻辑：
#   - / → 返回 index.html（首页）
#   - /api/xxx → 返回 404（防止前端路由被误匹配为 API）
#   - /xxx → 先查找文件，不存在则返回 index.html（SPA fallback）
FRONTEND_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")


@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


@app.get("/{path:path}")
async def serve_static(path: str):
    # 拦截所有 /api/ 开头的路径，返回 404（这是前端的路由，不应到达后端）
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API route not found")
    # 尝试直接匹配文件（如 /static/js/main.js）
    file_path = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # 文件不存在时返回 index.html（SPA 路由重定向）
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


# =============================================================================
# 服务启动入口
# =============================================================================
# 用途：直接运行 python main.py 启动服务（开发模式）
# 配置：监听 127.0.0.1:8002（仅本地访问，不暴露到公网）
# 警示：生产环境应使用 uvicorn 命令行启动，以便配置 workers 数量
if __name__ == "__main__":
    import uvicorn

    port = 8002
    config = uvicorn.Config(app, host="127.0.0.1", port=port)
    server = uvicorn.Server(config)
    server.run()

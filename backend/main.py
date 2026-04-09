"""
Velluma - AI Novel Writing Assistant
Copyright (C) 2026 Velluma Project Contributors

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
StoryWeaver-Core 后端入口模块。

职责：提供 FastAPI 应用实例、路由注册、中间件配置、SPA 静态文件服务。

业务场景：
- 作为 StoryWeaver 长篇小说 AI 写作平台的后端服务器
- 提供 RESTful API 接口供前端调用
- 托管打包后的前端静态资源（SPA 模式）

主要功能：
- 书籍、章节、角色、关系、记忆的 CRUD 接口
- 章节生成工作流（规划→起草→统稿→审阅→精修）
- 向量记忆 RAG 检索
- 实时流式输出（SSE）

依赖项：
- FastAPI: Web 框架
- SQLAlchemy: ORM
- PostgreSQL + pgvector: 数据库
- Uvicorn: ASGI 服务器

使用方式：
- 开发模式: python backend/main.py
- 生产模式: uvicorn backend.main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# =============================================================================
# 启动阶段：解决终端编码问题（必须在所有日志配置之前）
# =============================================================================
# 原因：某些部署环境（Docker、WSL、Windows）的 stdout/stderr 默认编码可能不是 UTF-8，
# 这会导致中文日志输出时抛出 UnicodeEncodeError
# 方式：使用 reconfigure(encoding="utf-8") 确保流级别支持 UTF-8，
# 这比重新包装 io.TextIOWrapper 更安全，因为它保留了原始流对象。
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# =============================================================================
# 日志配置（必须在所有导入之前）
# =============================================================================
# 关键：logging.basicConfig() 只在第一次调用时生效
# 如果在其他模块导入后才配置，那些模块的 logger 会使用默认的 WARNING 级别
# 这会导致 INFO 日志不输出
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True  # 强制重新配置，覆盖已有的配置
)
logger = logging.getLogger(__name__)

# 强制设置根 logger 级别为 INFO（这会影响到所有子 logger）
logging.getLogger().setLevel(logging.INFO)

# 强制设置所有已知 logger 的级别为 INFO
# 包含 backend 根命名空间，确保所有子模块继承 INFO 级别
for logger_name in [
    "uvicorn", "uvicorn.error", "uvicorn.access",
    "backend", "backend.services", "backend.routes", "backend.core",
    "backend.repositories", "backend.config",
]:
    logging.getLogger(logger_name).setLevel(logging.INFO)

# 添加全局过滤器，确保所有 INFO 日志都能输出
class InfoLogFilter(logging.Filter):
    def filter(self, record):
        # 只过滤 DEBUG 级别，允许 INFO 及以上级别输出
        return record.levelno >= logging.INFO

# 为根 logger 添加过滤器
root_logger = logging.getLogger()
root_logger.addFilter(InfoLogFilter())


# =============================================================================
# Windows asyncio ProactorEventLoop 异常处理器
# =============================================================================
# 用途：静默处理 Windows 上 ProactorEventLoop 的无害连接重置错误
# 背景：Python 3.8+ 在 Windows 上默认使用 ProactorEventLoop，当 SSE 客户端断开时，
#       会在 _call_connection_lost 回调中触发 ConnectionResetError (WinError 10054)
# 影响：此错误发生在连接关闭后的清理阶段，不影响业务逻辑，仅为日志噪音
def _handle_asyncio_exception(loop, context):
    """
    自定义 asyncio 异常处理器，静默处理 Windows 上的无害连接错误。

    静默的错误类型：
    - ConnectionResetError (WinError 10054): 远程主机强迫关闭连接
    - ConnectionAbortedError (WinError 10053): 连接被本地中止
    - OSError: 管道/套接字已关闭时的操作

    其他异常仍会正常记录到日志。
    """
    exception = context.get("exception")
    message = context.get("message", "")

    # 静默处理 Windows ProactorEventLoop 的无害连接错误
    if exception is not None:
        if isinstance(exception, (ConnectionResetError, ConnectionAbortedError)):
            # WinError 10054/10053 - 客户端断开连接，无需处理
            return
        if isinstance(exception, OSError):
            # 检查是否为 Windows 特定的连接错误
            error_code = getattr(exception, "winerror", None) or getattr(exception, "errno", None)
            if error_code in (10054, 10053, 9, 32, 57):  # 常见的连接/管道错误码
                return

    # 其他异常正常记录
    if exception:
        logger.warning(f"[asyncio] 未处理的异常: {message} - {exception}")
    else:
        logger.warning(f"[asyncio] 未处理的事件: {message}")

# 加载环境变量
# 确保在导入其他模块之前加载，以便 database.py 等模块能正确获取配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    logger.info(f"Loading environment variables from {ENV_PATH}")
    load_dotenv(ENV_PATH)
else:
    logger.warning(f".env file not found at {ENV_PATH}")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend.core.config import save_port as _save_port, find_available_port
from backend.database import init_db
from backend.routes import (
    books_router,
    chapters_router,
    chapter_entities_router,
    chapter_publishing_router,
    characters_router,
    relationships_router,
    memories_router,
    text_formatting_router,
    chapter_generation_router,
    chapter_optimization_router,
    inspiration_router,
    critique_router,
    system_router,
    maps_router,
)

# V3.8 意图驱动层路由
try:
    from backend.routes.intent_driven import router as intent_driven_router
    INTENT_DRIVEN_ROUTER_AVAILABLE = True
    logger.info("[Main] 意图驱动路由已加载")
except Exception as e:
    INTENT_DRIVEN_ROUTER_AVAILABLE = False
    logger.warning(f"[Main] 意图驱动路由加载失败: {e}")

# V3.5 双轨架构路由（可选导入）
try:
    from backend.routes.chapter_generation_dual_track import router as chapter_generation_dual_track_router
    DUAL_TRACK_ROUTER_AVAILABLE = True
    logger.info("[Main] 双轨生成路由已加载")
except Exception as e:
    DUAL_TRACK_ROUTER_AVAILABLE = False
    logger.warning(f"[Main] 双轨生成路由加载失败: {e}")

# 后台生成路由（简化版，单用户场景）
try:
    from backend.routes.generation_background import router as generation_background_router
    GENERATION_BG_ROUTER_AVAILABLE = True
    logger.info("[Main] 后台生成路由已加载")
except Exception as e:
    GENERATION_BG_ROUTER_AVAILABLE = False
    logger.warning(f"[Main] 后台生成路由加载失败: {e}")

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
    # 启动阶段：注册 asyncio 异常处理器（处理 Windows ProactorEventLoop 的无害错误）
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_handle_asyncio_exception)
    logger.info("[Lifespan] 已注册 asyncio 异常处理器")

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
app.include_router(chapter_entities_router)
app.include_router(chapter_publishing_router)
app.include_router(characters_router)
app.include_router(relationships_router)
app.include_router(memories_router)
app.include_router(text_formatting_router)
app.include_router(chapter_generation_router)

# V3.5 双轨生成路由（如果可用）
if DUAL_TRACK_ROUTER_AVAILABLE:
    app.include_router(chapter_generation_dual_track_router)
    logger.info("[Main] 双轨生成路由已注册: /api/chapters/{id}/generate-dual-track")

app.include_router(chapter_optimization_router)
app.include_router(inspiration_router)
app.include_router(critique_router)
app.include_router(maps_router)

# 后台生成路由（如果可用）
if GENERATION_BG_ROUTER_AVAILABLE:
    app.include_router(generation_background_router)
    logger.info("[Main] 后台生成路由已注册: /api/generation")

# V3.8 意图驱动层路由（如果可用）
if INTENT_DRIVEN_ROUTER_AVAILABLE:
    app.include_router(intent_driven_router)
    logger.info("[Main] 意图驱动路由已注册: /api/intent-driven")

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
# 配置：动态检测可用端口（8002~8100），持久化到 data/port.txt
# 警示：生产环境应使用 uvicorn 命令行启动，以便配置 workers 数量
if __name__ == "__main__":
    import uvicorn

    port = find_available_port()
    save_port(port)
    logger.info(f"[Main] 后端启动于 http://127.0.0.1:{port}")
    
    # Uvicorn 配置：禁用 Uvicorn 自己的日志配置，使用我们已配置的 basicConfig
    # log_config=None 是关键，这会阻止 Uvicorn 覆盖我们的日志设置
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        log_config=None,  # 禁用 Uvicorn 的日志配置，使用根 logger 配置
        access_log=False,  # 关闭访问日志，减少噪音
    )
    server = uvicorn.Server(config)
    server.run()

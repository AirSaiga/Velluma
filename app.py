"""
Velluma AI 小说写作助手 - 桌面应用入口
负责启动 FastAPI 后端并在 pywebview 中打开窗口
"""

import os
import sys
import threading
import time
import webview
import uvicorn
from pathlib import Path


# 配置参数
HOST = "127.0.0.1"
PORT = 0  # 使用 0 表示动态端口
BACKEND_URL = None  # 将在启动时动态生成

# 开发模式配置 - 如果前端正在开发中，设置为 True 以使用 Vite 开发服务器
DEV_MODE = False
DEV_FRONTEND_URL = "http://localhost:5173"

# 窗口配置
WINDOW_TITLE = "Velluma AI 小说写作助手"
WINDOW_WIDTH = 1400
WINDOW_HEIGHT = 900


def start_backend():
    """
    在后台线程中启动 FastAPI 服务
    返回实际分配的端口号
    """
    from backend.main import app, save_port
    import uvicorn
    
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,  # 0 表示动态端口
        log_level="info"
    )
    server = uvicorn.Server(config)
    
    actual_port = server.config.port
    save_port(actual_port)
    
    global BACKEND_URL
    BACKEND_URL = f"http://{HOST}:{actual_port}"
    
    server.run()
    
    return actual_port


def wait_for_backend(timeout: int = 30) -> bool:
    """
    等待后端服务启动
    
    Args:
        timeout: 最大等待时间(秒)
        
    Returns:
        是否成功启动
    """
    import urllib.request
    
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # 尝试访问健康检查接口
            response = urllib.request.urlopen(
                f"{BACKEND_URL}/api/health",
                timeout=1
            )
            if response.status == 200:
                print(f"✅ 后端服务已启动: {BACKEND_URL}")
                return True
        except Exception:
            time.sleep(0.5)
    
    return False


def create_window():
    """
    创建桌面窗口
    """
    # 确定要加载的 URL
    if DEV_MODE:
        url = DEV_FRONTEND_URL
        print(f"🚀 开发模式: 连接到前端开发服务器 {url}")
    else:
        url = BACKEND_URL
        print(f"🚀 生产模式: 连接到后端服务 {url}")
    
    # 创建窗口
    window = webview.create_window(
        title=WINDOW_TITLE,
        url=url,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(1000, 600),
        text_select=True,
        confirm_close=False
    )
    
    return window


def main():
    """
    主入口函数
    """
    print("=" * 60)
    print("📝 Velluma AI 小说写作助手")
    print("=" * 60)
    
    # 检查开发模式
    if len(sys.argv) > 1 and sys.argv[1] == "--dev":
        global DEV_MODE
        DEV_MODE = True
        print("🛠️  已启用开发模式")
    
    if not DEV_MODE:
        # 启动后端服务线程
        print(f"🔧 正在启动后端服务...")
        backend_thread = threading.Thread(target=start_backend, daemon=True)
        backend_thread.start()
        
        # 等待后端启动
        print(f"⏳ 等待后端服务就绪...")
        if not wait_for_backend(timeout=30):
            print("❌ 后端服务启动超时，请检查日志")
            sys.exit(1)
        
        print(f"✅ 后端服务已启动: {BACKEND_URL}")
    else:
        print("⚠️  开发模式: 后端服务需要手动启动")
        print(f"   请运行: python -m backend.main")
    
    # 创建并启动桌面窗口
    print(f"🪟 正在启动桌面窗口...")
    window = create_window()
    
    # 启动 webview 主循环
    webview.start(
        debug=DEV_MODE,
        http_server=False,
        gui="edge"  # Windows 上使用 Edge 引擎
    )
    
    print("👋 应用已关闭")


if __name__ == "__main__":
    main()

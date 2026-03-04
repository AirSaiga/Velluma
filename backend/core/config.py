import os
from typing import Optional

# =============================================================================
# 端口持久化配置
# =============================================================================
# 业务背景：开发环境下端口可能被占用，需要动态切换；前端需要知道后端的实际端口
# 数据目录：data/ 目录与 backend/ 平级，用于存放运行时生成的配置文件
# 警示：此文件仅用于本地开发，生产环境应使用环境变量或配置文件管理端口
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")
# 内存缓存：避免每次读取文件，提升查询性能（副作用：进程重启后丢失）
ACTUAL_PORT: Optional[int] = None

# 确保 data 目录存在（首次启动时可能不存在）
os.makedirs(DATA_DIR, exist_ok=True)


# =============================================================================
# 端口写入（双向同步）
# =============================================================================
# 用途：后端启动时将实际端口同时写入内存和文件
# 数据流：内存变量 ← 文件（启动时） / 文件（动态切换）
# 副作用：写入失败会抛出异常，调用方需处理
def save_port(port: int):
    global ACTUAL_PORT
    ACTUAL_PORT = port
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        f.write(str(port))


# =============================================================================
# 端口读取（带容错）
# =============================================================================
# 用途：前端启动时读取后端实际端口，用于配置 API 请求地址
# 容错逻辑：文件不存在、格式错误、IO 异常均返回 None
# 权衡：返回 None 时前端需要使用默认端口 fallback
def load_port() -> Optional[int]:
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            pass
    return None


# =============================================================================
# 内存缓存查询
# =============================================================================
# 用途：进程内快速获取当前端口（无需读取文件）
# 副作用：进程启动后若未调用 save_port，则返回 None
def get_actual_port() -> Optional[int]:
    return ACTUAL_PORT

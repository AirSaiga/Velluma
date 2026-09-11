# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Velluma Contributors
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
核心配置模块 - 应用级配置和常量定义。

职责：
- 管理运行时端口配置（持久化到文件系统）
- 定义推理模型支持列表和检查逻辑
- 提供全局配置查询接口

业务场景：
- 开发环境端口动态分配（解决端口冲突）
- 推理模式模型支持检查（用于配置验证）
- 前端后端端口协商

主要功能：
- 端口持久化（data/port.txt）
- 推理模型支持检测
- 全局配置查询

依赖项：
- os: 文件系统操作
- typing: 类型定义

使用方式：
    from backend.core.config import save_port, load_port, check_reasoning_support
"""

import os
import socket
from typing import Optional, Set, List

# =============================================================================
# 端口持久化配置
# =============================================================================
# 业务背景：开发环境下端口可能被占用，需要动态切换；前端需要知道后端的实际端口
# 数据目录：data/ 目录与 backend/ 平级，用于存放运行时生成的配置文件
# 警示：此文件仅用于本地开发，生产环境应使用环境变量或配置文件管理端口
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")
# V5.0 World 底图图片目录（用户上传的世界地图素材；经 main.py 的 /world-images 静态路由对外）
WORLD_IMAGES_DIR = os.path.join(DATA_DIR, "world_images")
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
    """获取后端实际监听端口。

    优先返回内存变量（save_port 写入）；若未设置（uvicorn 直接启 / IDE 启 /
    --reload 重启等不经 __main__ 的场景），fallback 读 data/port.txt。
    """
    if ACTUAL_PORT is not None:
        return ACTUAL_PORT
    return load_port()


# =============================================================================
# 动态端口查找
# =============================================================================
# 用途：启动时检测端口占用，自动寻找可用端口
# 策略：优先使用环境变量 VELLUMA_PORT → 默认端口 8002 → 递增扫描
# 范围：8002 ~ 8100，避免扫描过多端口拖慢启动
# 副作用：会短暂占用端口进行检测（立即释放）
DEFAULT_PORT = 8002
MAX_PORT = 8100


def find_available_port(preferred_port: Optional[int] = None) -> int:
    """
    查找可用端口，从首选端口开始递增扫描。

    Args:
        preferred_port: 首选端口（若为 None，依次尝试环境变量、默认端口）

    Returns:
        int: 可用的端口号

    Raises:
        OSError: 在 8002~8100 范围内无可用端口
    """
    # 1. 确定首选端口：参数 > 环境变量 > 默认值
    if preferred_port is None:
        env_port = os.environ.get("VELLUMA_PORT")
        if env_port:
            try:
                preferred_port = int(env_port)
            except ValueError:
                preferred_port = DEFAULT_PORT
        else:
            preferred_port = DEFAULT_PORT

    # 2. 从首选端口开始递增扫描
    for port in range(preferred_port, MAX_PORT + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind(("127.0.0.1", port))
                # bind 成功说明端口可用，立即释放
                return port
        except OSError:
            # 端口被占用，尝试下一个
            continue

    raise OSError(f"在 {DEFAULT_PORT}~{MAX_PORT} 范围内无可用端口")


# =============================================================================
# 模型配置
# =============================================================================

# 已知支持推理模式的模型列表
# 参考: https://openrouter.ai/docs/guides/best-practices/reasoning-tokens
REASONING_SUPPORTED_MODELS: Set[str] = {
    # OpenAI 推理模型
    "openai/o1",
    "openai/o1-mini",
    "openai/o1-preview",
    "openai/o3",
    "openai/o3-mini",
    "openai/o4-mini",
    "openai/gpt-5",
    # Anthropic 推理模型
    "anthropic/claude-3.7-sonnet",
    "anthropic/claude-3.7-sonnet:thinking",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-sonnet-4:thinking",
    # Gemini thinking 模型
    "google/gemini-2.0-flash-thinking",
    "google/gemini-2.0-flash-thinking-exp",
    "google/gemini-2.5-pro-preview",
    "google/gemini-2.5-pro-preview-05-06",
    # xAI Grok
    "x-ai/grok-3",
    "x-ai/grok-3-mini",
    "x-ai/grok-3-r1",
    # DeepSeek R1
    "deepseek/deepseek-r1",
    "deepseek/deepseek-reasoner",
    # 字节火山引擎 / 豆包推理模型
    "doubao-seed-1-6-251015",
    "doubao-seed-2-0-pro",
    "doubao-seed-2-0-code",
    "deepseek-r1",
    # 其他推理模型
    "z-ai/glm-4.5",
    "z-ai/glm-z1",
    "moonshotai/kimi-k2-thinking",
    "qwen/qwen-3-235b",
}

# 推理模型关键词（用于模糊匹配）
REASONING_KEYWORDS: List[str] = [
    "o1", "o3", "o4", "gpt-5",
    "thinking", "reasoner", "r1",
    "claude-3.7", "claude-sonnet-4",
    "grok-3", "glm-z1", "kimi-k2-thinking",
    "doubao-seed", "deepseek-r1",
    "deepseek-v4",     # DeepSeek V4 系列支持推理模式
    "deepseek-flash",  # V4.1 Flash（2026-09-10）：思考默认开，规范 id 已不带 v4
]


def check_reasoning_support(model: str) -> tuple[bool, str]:
    """
    检查模型是否支持推理模式。
    
    Args:
        model: 模型名称
        
    Returns:
        tuple[bool, str]: (是否支持, 说明消息)
    """
    model_lower = model.lower()
    
    # 精确匹配
    for supported in REASONING_SUPPORTED_MODELS:
        if model_lower == supported.lower():
            return True, f"模型 {model} 已确认支持推理模式"
    
    # 关键词匹配
    for keyword in REASONING_KEYWORDS:
        if keyword in model_lower:
            return True, f"模型 {model} 可能支持推理模式（基于名称匹配）"
    
    return False, f"模型 {model} 可能不支持推理模式。支持推理的模型包括：OpenAI o1/o3/GPT-5、Anthropic Claude 3.7+、Gemini thinking、xAI Grok、DeepSeek R1 等"

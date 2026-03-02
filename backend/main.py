"""
FastAPI 核心接口与路由
提供 Entity 和 Beat 的 CRUD 操作，以及 AI 生成功能
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import json
import os
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse

from backend.models import (
    Entity, EntityCreate, EntityUpdate,
    Beat, BeatCreate, BeatUpdate,
    GenerateRequest, Config
)
from backend.ai_service import get_ai_service


# 数据文件路径
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
ENTITIES_FILE = os.path.join(DATA_DIR, "entities.json")
BEATS_FILE = os.path.join(DATA_DIR, "beats.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
PORT_FILE = os.path.join(DATA_DIR, "port.txt")

# 全局变量存储实际端口号
ACTUAL_PORT = None

# 确保数据目录存在
os.makedirs(DATA_DIR, exist_ok=True)


def save_port(port: int):
    """保存端口号到文件"""
    global ACTUAL_PORT
    ACTUAL_PORT = port
    with open(PORT_FILE, "w", encoding="utf-8") as f:
        f.write(str(port))


def load_port() -> Optional[int]:
    """从文件读取端口号"""
    if os.path.exists(PORT_FILE):
        try:
            with open(PORT_FILE, "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            pass
    return None


# 初始化 FastAPI 应用
app = FastAPI(
    title="Velluma AI 小说写作助手",
    description="专为 AI 长篇小说写作特化的桌面应用后端 API",
    version="0.1.0"
)

# 配置 CORS (允许前端跨域访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件配置
FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 
    "frontend", "dist"
)


@app.get("/")
async def serve_index():
    """服务前端入口页面"""
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


# ==================== 数据持久化辅助函数 ====================

def load_json_file(filepath: str, default: list) -> list:
    """加载 JSON 文件，如果不存在则返回默认值"""
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default


def save_json_file(filepath: str, data: list):
    """保存数据到 JSON 文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_entities() -> List[Entity]:
    """加载所有实体"""
    data = load_json_file(ENTITIES_FILE, [])
    return [Entity(**item) for item in data]


def save_entities(entities: List[Entity]):
    """保存所有实体"""
    data = [entity.model_dump() for entity in entities]
    save_json_file(ENTITIES_FILE, data)


def load_beats() -> List[Beat]:
    """加载所有节拍"""
    data = load_json_file(BEATS_FILE, [])
    return [Beat(**item) for item in data]


def save_beats(beats: List[Beat]):
    """保存所有节拍"""
    data = [beat.model_dump() for beat in beats]
    save_json_file(BEATS_FILE, data)


def load_config() -> Config:
    """加载配置"""
    data = load_json_file(CONFIG_FILE, {})
    if isinstance(data, list):
        data = {}
    return Config(**data)


def save_config(config: Config):
    """保存配置"""
    save_json_file(CONFIG_FILE, config.model_dump())


# ==================== Entity API ====================

@app.get("/api/entities", response_model=List[Entity])
async def get_entities():
    """获取所有实体列表"""
    return load_entities()


@app.get("/api/entities/{entity_id}", response_model=Entity)
async def get_entity(entity_id: str):
    """获取单个实体详情"""
    entities = load_entities()
    for entity in entities:
        if entity.id == entity_id:
            return entity
    raise HTTPException(status_code=404, detail="实体不存在")


@app.post("/api/entities", response_model=Entity)
async def create_entity(entity_create: EntityCreate):
    """创建新实体"""
    entities = load_entities()
    
    new_entity = Entity(
        name=entity_create.name,
        type=entity_create.type,
        description=entity_create.description
    )
    
    entities.append(new_entity)
    save_entities(entities)
    
    return new_entity


@app.put("/api/entities/{entity_id}", response_model=Entity)
async def update_entity(entity_id: str, entity_update: EntityUpdate):
    """更新实体"""
    entities = load_entities()
    
    for i, entity in enumerate(entities):
        if entity.id == entity_id:
            update_data = entity_update.model_dump(exclude_unset=True)
            update_data["updated_at"] = datetime.now().isoformat()
            
            for key, value in update_data.items():
                setattr(entity, key, value)
            
            entities[i] = entity
            save_entities(entities)
            return entity
    
    raise HTTPException(status_code=404, detail="实体不存在")


@app.delete("/api/entities/{entity_id}")
async def delete_entity(entity_id: str):
    """删除实体"""
    entities = load_entities()
    
    for i, entity in enumerate(entities):
        if entity.id == entity_id:
            entities.pop(i)
            save_entities(entities)
            return {"message": "实体已删除", "id": entity_id}
    
    raise HTTPException(status_code=404, detail="实体不存在")


# ==================== Beat API ====================

@app.get("/api/beats", response_model=List[Beat])
async def get_beats():
    """获取所有节拍列表 (按 order 排序)"""
    beats = load_beats()
    return sorted(beats, key=lambda x: x.order)


@app.get("/api/beats/{beat_id}", response_model=Beat)
async def get_beat(beat_id: str):
    """获取单个节拍详情"""
    beats = load_beats()
    for beat in beats:
        if beat.id == beat_id:
            return beat
    raise HTTPException(status_code=404, detail="节拍不存在")


@app.post("/api/beats", response_model=Beat)
async def create_beat(beat_create: BeatCreate):
    """创建新节拍"""
    beats = load_beats()
    
    # 如果没有指定 order，自动设置为最大值+1
    order = beat_create.order
    if order == 0 and beats:
        order = max(b.order for b in beats) + 1
    
    new_beat = Beat(
        order=order,
        instruction=beat_create.instruction,
        entity_ids=beat_create.entity_ids
    )
    
    beats.append(new_beat)
    save_beats(beats)
    
    return new_beat


@app.put("/api/beats/{beat_id}", response_model=Beat)
async def update_beat(beat_id: str, beat_update: BeatUpdate):
    """更新节拍"""
    beats = load_beats()
    
    for i, beat in enumerate(beats):
        if beat.id == beat_id:
            update_data = beat_update.model_dump(exclude_unset=True)
            update_data["updated_at"] = datetime.now().isoformat()
            
            for key, value in update_data.items():
                setattr(beat, key, value)
            
            beats[i] = beat
            save_beats(beats)
            return beat
    
    raise HTTPException(status_code=404, detail="节拍不存在")


@app.delete("/api/beats/{beat_id}")
async def delete_beat(beat_id: str):
    """删除节拍"""
    beats = load_beats()
    
    for i, beat in enumerate(beats):
        if beat.id == beat_id:
            beats.pop(i)
            save_beats(beats)
            return {"message": "节拍已删除", "id": beat_id}
    
    raise HTTPException(status_code=404, detail="节拍不存在")


# ==================== AI 生成 API ====================

@app.post("/api/generate")
async def generate_text(request: GenerateRequest):
    """
    流式生成小说正文
    
    接收当前 Beat 和全局 style，返回 SSE 流式响应
    """
    # 加载所有实体
    all_entities = {e.id: e for e in load_entities()}
    
    # 获取当前 Beat 引用的实体
    referenced_entities = [
        all_entities.get(eid) for eid in request.beat.entity_ids
        if eid in all_entities
    ]
    
    # 获取 AI 服务实例
    ai_service = get_ai_service(
        api_key=request.api_key,
        base_url=request.base_url,
        model=request.model
    )
    
    # 返回流式响应
    return StreamingResponse(
        ai_service.generate_stream(
            beat=request.beat,
            entities=referenced_entities,
            style=request.style
        ),
        media_type="text/event-stream"
    )


# ==================== Config API ====================

@app.get("/api/config", response_model=Config)
async def get_config():
    """获取应用配置"""
    return load_config()


@app.post("/api/config", response_model=Config)
async def update_config(config: Config):
    """更新应用配置"""
    save_config(config)
    return config


# ==================== 健康检查 ====================

@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "service": "Velluma AI"}


@app.get("/api/port")
async def get_port():
    """获取当前服务端口号"""
    return {"port": ACTUAL_PORT}


# ==================== 静态文件服务 (SPA 支持) ====================

@app.get("/{path:path}")
async def serve_static(path: str):
    """服务静态文件 (必须放在所有 API 路由之后)"""
    file_path = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    return FileResponse(os.path.join(FRONTEND_DIST, "index.html"))


# ==================== 启动入口 ====================

if __name__ == "__main__":
    import uvicorn
    
    env_port = os.environ.get('VELLUMA_PORT')
    if env_port:
        port = int(env_port)
        print(f"🚀 使用环境变量指定的端口: {port}")
    else:
        port = 0
        print(f"🚀 使用动态端口分配")
    
    config = uvicorn.Config(app, host="127.0.0.1", port=port)
    server = uvicorn.Server(config)
    
    print(f"✅ 后端服务启动")
    
    server.run()

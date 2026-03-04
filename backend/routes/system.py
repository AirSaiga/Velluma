from fastapi import APIRouter

from backend.core.config import get_actual_port

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "StoryWeaver-Core"}


@router.get("/port")
async def get_port():
    return {"port": get_actual_port()}

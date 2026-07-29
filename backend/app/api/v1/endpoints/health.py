"""health endpoints — Stage 2 will complete these."""
from fastapi import APIRouter, Depends
from app.api.v1.endpoints.auth import get_current_user
from app.models.user import User

router = APIRouter()

@router.get("/")
async def list_health(current_user: User = Depends(get_current_user)):
    return {"module": "health", "status": "coming_in_stage_2"}

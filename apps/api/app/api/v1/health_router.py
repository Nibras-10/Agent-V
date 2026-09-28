from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.core.database import get_db
from app.core.redis import redis_client
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health/live", status_code=status.HTTP_200_OK)
async def liveness():
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness(
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    db_ok = False
    redis_ok = False

    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    try:
        redis_ok = await redis_client.ping()
    except Exception:
        redis_ok = False

    if not db_ok or (settings.is_production and not redis_ok):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": db_ok, "redis": redis_ok}

    return {"status": "ready", "database": db_ok, "redis": redis_ok}

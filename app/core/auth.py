import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import APIKey, User, UsageLog, get_session

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

TIER_LIMITS: dict[str, int] = {
    "free": settings.FREE_TIER_LIMIT,
    "pro": settings.PRO_TIER_LIMIT,
    "enterprise": settings.ENTERPRISE_TIER_LIMIT,
}


def generate_api_key() -> str:
    """Generate a new API key in fl_live_xxx format."""
    random_part = secrets.token_urlsafe(32)
    return f"fl_live_{random_part}"


def hash_api_key(key: str) -> str:
    """Hash an API key for secure storage."""
    return hashlib.sha256(key.encode()).hexdigest()


async def get_api_key_record(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    session: AsyncSession = Depends(get_session),
) -> APIKey:
    """Validate an API key from the X-API-Key header and return the key record."""
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Include it in the X-API-Key header.",
        )

    key_hash = hash_api_key(api_key)
    result = await session.execute(
        select(APIKey).where(APIKey.key_hash == key_hash, APIKey.is_active.is_(True))
    )
    key_record = result.scalar_one_or_none()

    if key_record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked API key.",
        )

    return key_record


async def check_usage_limit(
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> APIKey:
    """Check that the API key's user hasn't exceeded their tier limit this month."""
    # Get the user to determine tier
    result = await session.execute(
        select(User).where(User.id == key_record.user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with this API key not found.",
        )

    tier_limit = TIER_LIMITS.get(user.tier, settings.FREE_TIER_LIMIT)

    # Count usage this month across ALL of the user's API keys
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Subquery: all key IDs belonging to this user
    user_key_ids = select(APIKey.id).where(APIKey.user_id == key_record.user_id)

    result = await session.execute(
        select(func.count(UsageLog.id)).where(
            UsageLog.api_key_id.in_(user_key_ids),
            UsageLog.timestamp >= month_start,
        )
    )
    usage_count = result.scalar() or 0

    if usage_count >= tier_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Monthly usage limit reached ({tier_limit} requests). "
            f"Upgrade your plan for higher limits.",
        )

    return key_record


async def log_usage(
    session: AsyncSession,
    api_key_id: int,
    endpoint: str,
    tokens_used: int = 0,
) -> None:
    """Record an API usage event."""
    log_entry = UsageLog(
        api_key_id=api_key_id,
        endpoint=endpoint,
        timestamp=datetime.now(timezone.utc),
        tokens_used=tokens_used,
    )
    session.add(log_entry)
    await session.commit()

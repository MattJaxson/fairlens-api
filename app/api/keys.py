"""API key management endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_api_key, hash_api_key, get_api_key_record
from app.models.database import APIKey, User, get_session
from app.models.schemas import APIKeyCreate, APIKeyCreated, APIKeyResponse, UserCreate

router = APIRouter(prefix="/api/v1/keys", tags=["keys"])

# Maximum API keys per user
MAX_KEYS_PER_USER = 10


@router.post("/register", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def register_and_create_key(
    user_data: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> APIKeyCreated:
    """
    Register a new user and generate their first API key.

    This is the onboarding endpoint -- no auth required.
    Returns the full API key (only shown once).
    """
    # Check if user already exists
    result = await session.execute(
        select(User).where(User.email == user_data.email)
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists. Use your existing API key to create additional keys.",
        )

    # Create user
    user = User(email=user_data.email, tier="free")
    session.add(user)
    await session.flush()

    # Generate API key
    raw_key = generate_api_key()
    key_record = APIKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        user_id=user.id,
        name="Default Key",
        is_active=True,
    )
    session.add(key_record)
    await session.commit()
    await session.refresh(key_record)

    return APIKeyCreated(
        id=key_record.id,
        name=key_record.name,
        api_key=raw_key,
        created_at=key_record.created_at,
    )


@router.post("", response_model=APIKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: APIKeyCreate,
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> APIKeyCreated:
    """
    Create a new API key for the authenticated user.

    Requires an existing valid API key in the X-API-Key header.
    Returns the full new key (only shown once).
    """
    # Check key count
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == key_record.user_id,
            APIKey.is_active.is_(True),
        )
    )
    active_keys = result.scalars().all()
    if len(active_keys) >= MAX_KEYS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum of {MAX_KEYS_PER_USER} active API keys allowed. Revoke an existing key first.",
        )

    raw_key = generate_api_key()
    new_key = APIKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        user_id=key_record.user_id,
        name=request.name,
        is_active=True,
    )
    session.add(new_key)
    await session.commit()
    await session.refresh(new_key)

    return APIKeyCreated(
        id=new_key.id,
        name=new_key.name,
        api_key=raw_key,
        created_at=new_key.created_at,
    )


@router.get("", response_model=list[APIKeyResponse])
async def list_api_keys(
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> list[APIKeyResponse]:
    """List all API keys for the authenticated user (active and revoked)."""
    result = await session.execute(
        select(APIKey)
        .where(APIKey.user_id == key_record.user_id)
        .order_by(APIKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [
        APIKeyResponse(
            id=k.id,
            name=k.name,
            key_prefix=k.key_prefix,
            created_at=k.created_at,
            is_active=k.is_active,
        )
        for k in keys
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: int,
    key_record: APIKey = Depends(get_api_key_record),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Revoke an API key. The key will no longer be usable."""
    result = await session.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.user_id == key_record.user_id,
        )
    )
    target_key = result.scalar_one_or_none()

    if target_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found.",
        )

    if not target_key.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key is already revoked.",
        )

    # Don't let users revoke their last active key
    result = await session.execute(
        select(APIKey).where(
            APIKey.user_id == key_record.user_id,
            APIKey.is_active.is_(True),
        )
    )
    active_keys = result.scalars().all()
    if len(active_keys) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot revoke your last active API key. Create a new one first.",
        )

    target_key.is_active = False
    await session.commit()

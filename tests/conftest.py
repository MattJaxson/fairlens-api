"""
Shared fixtures for FairLens API tests.
Uses an in-memory SQLite database so tests are fast and isolated.
"""

import asyncio
import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force test SECRET_KEY before any app imports
os.environ["SECRET_KEY"] = "test-secret-key-for-ci-only"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from app.core.auth import generate_api_key, hash_api_key
from app.models.database import Base, User, APIKey, UsageLog, get_session
from app.main import app


# ── In-memory engine ──────────────────────────────────────────────────────

test_engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
TestSession = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_session():
    async with TestSession() as session:
        try:
            yield session
        finally:
            await session.close()


app.dependency_overrides[get_session] = override_get_session


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession):
    """Create a free-tier test user."""
    user = User(email="test@fairlens.dev", tier="free")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_api_key(db_session: AsyncSession, test_user: User):
    """Create a valid API key and return (raw_key, key_record)."""
    raw_key = generate_api_key()
    key_record = APIKey(
        key_hash=hash_api_key(raw_key),
        key_prefix=raw_key[:12],
        user_id=test_user.id,
        name="test-key",
        is_active=True,
    )
    db_session.add(key_record)
    await db_session.commit()
    await db_session.refresh(key_record)
    return raw_key, key_record


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

"""
5 Critical Tests for FairLens API
──────────────────────────────────
1. Bias detection returns correct scores
2. Usage limits enforce per-user (not per-key)
3. Tier gating blocks free users from pro endpoints
4. Input size validation rejects oversized payloads
5. SECRET_KEY guard blocks insecure defaults
"""

import io
import os
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_api_key, hash_api_key
from app.models.database import APIKey, User, UsageLog


# ── Test 1: Bias detection returns correct structure and catches bias ──────

@pytest.mark.asyncio
async def test_bias_detection_flags_gendered_language(client: AsyncClient, test_api_key):
    raw_key, _ = test_api_key
    resp = await client.post(
        "/api/v1/analyze/text",
        json={"text": "The chairman and fireman discussed the policeman's report."},
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "overall_score" in data
    assert data["overall_score"] < 100  # should detect bias
    assert len(data["bias_scores"]) > 0
    # Check that gender category found flagged phrases
    gender_scores = [s for s in data["bias_scores"] if s["category"] == "gender"]
    assert len(gender_scores) == 1
    assert len(gender_scores[0]["flagged_phrases"]) >= 3  # chairman, fireman, policeman


# ── Test 2: Usage limits count across ALL user keys (the P0 fix) ──────────

@pytest.mark.asyncio
async def test_usage_limit_counts_across_all_user_keys(db_session: AsyncSession, client: AsyncClient, test_user: User):
    """
    Create 2 API keys for the same user. Log requests under key1.
    Verify key2 is also rate-limited when user total exceeds limit.
    """
    import app.core.auth as auth_module

    # Patch the module-level TIER_LIMITS dict (set at import time, not re-read from settings)
    original_limits = auth_module.TIER_LIMITS.copy()
    auth_module.TIER_LIMITS["free"] = 3

    try:
        # Create two keys for the same user
        raw_key1 = generate_api_key()
        key1 = APIKey(key_hash=hash_api_key(raw_key1), key_prefix=raw_key1[:12],
                      user_id=test_user.id, name="key-1", is_active=True)
        raw_key2 = generate_api_key()
        key2 = APIKey(key_hash=hash_api_key(raw_key2), key_prefix=raw_key2[:12],
                      user_id=test_user.id, name="key-2", is_active=True)
        db_session.add_all([key1, key2])
        await db_session.commit()
        await db_session.refresh(key1)
        await db_session.refresh(key2)

        # Log 3 requests under key1 (hitting the limit)
        now = datetime.now(timezone.utc)
        for _ in range(3):
            db_session.add(UsageLog(api_key_id=key1.id, endpoint="/test", timestamp=now))
        await db_session.commit()

        # Now key2 should also be blocked (same user, limit=3)
        resp = await client.post(
            "/api/v1/analyze/text",
            json={"text": "Hello world"},
            headers={"X-API-Key": raw_key2},
        )
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}: {resp.text}"
        assert "limit" in resp.json()["detail"].lower()
    finally:
        auth_module.TIER_LIMITS.update(original_limits)


# ── Test 3: Tier gating blocks free users from enterprise endpoints ───────

@pytest.mark.asyncio
async def test_tier_gating_blocks_free_user_from_compliance(client: AsyncClient, test_api_key):
    """Compliance endpoint requires pro tier; free user should get 403.
    Uses CSV file upload with the required config_json Form field."""
    import json as _json
    raw_key, _ = test_api_key

    csv_content = "race,outcome\nWhite,1\nBlack,0\n"
    files = {"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    data = {
        "race_col": "race",
        "outcome_col": "outcome",
        "favorable_value": "1",
        "config_json": _json.dumps({
            "priority_groups": ["Black"],
            "fairness_target": "White",
            "fairness_threshold": 0.8,
        }),
    }

    resp = await client.post(
        "/api/v1/fairness/audit/compliance",
        files=files,
        data=data,
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code == 403
    assert "pro" in resp.json()["detail"].lower()


# ── Test 4: Input size validation rejects oversized payloads ──────────────

@pytest.mark.asyncio
async def test_input_size_limit_rejects_oversized_data(client: AsyncClient, test_api_key):
    """Sending >10,000 rows should be rejected by pydantic validation."""
    raw_key, _ = test_api_key
    # Build a payload with 10,001 rows
    oversized_data = [{"race": "A", "outcome": 1}] * 10_001
    resp = await client.post(
        "/api/v1/fairness/audit",
        json={
            "data": oversized_data,
            "race_col": "race",
            "outcome_col": "outcome",
            "favorable_value": "1",
        },
        headers={"X-API-Key": raw_key},
    )
    assert resp.status_code == 422  # Pydantic validation error
    body = resp.json()
    detail_str = str(body)
    assert "10000" in detail_str or "too_long" in detail_str or "max" in detail_str.lower()


# ── Test 5: SECRET_KEY guard blocks insecure default ──────────────────────

@pytest.mark.asyncio
async def test_secret_key_guard_blocks_default():
    """Verify the lifespan raises RuntimeError if SECRET_KEY is the default."""
    from app.main import lifespan, app as main_app
    from app.core.config import settings

    original = settings.SECRET_KEY
    settings.SECRET_KEY = "change-me-in-production"
    try:
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            async with lifespan(main_app):
                pass  # Should never reach here
    finally:
        settings.SECRET_KEY = original

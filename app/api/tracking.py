"""Tracking, public stats, and demo endpoints."""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.models.database import (
    CommunityConfig,
    PageView,
    UsageLog,
    User,
    get_session,
)
from app.services.bias_detector import TextBiasDetector

router = APIRouter(prefix="/api/v1", tags=["tracking"])

bias_detector = TextBiasDetector()


# ── Schemas ────────────────────────────────────────────────────────────────

class PageViewRequest(BaseModel):
    path: str = Field(..., max_length=255)


class PublicStatsResponse(BaseModel):
    total_analyses: int
    total_users: int
    total_communities: int
    total_pageviews: int


class DemoAnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    categories: list[str] = Field(
        default=["gender", "race", "age", "disability"],
    )


# ── Page View Tracking ────────────────────────────────────────────────────

@router.post("/track/pageview", status_code=204)
async def track_pageview(
    body: PageViewRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Record an anonymous page view."""
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    session_hash = hashlib.sha256(f"{client_ip}:{user_agent}".encode()).hexdigest()

    pv = PageView(
        path=body.path,
        referrer=request.headers.get("referer"),
        session_hash=session_hash,
    )
    session.add(pv)
    await session.commit()


# ── Public Stats ──────────────────────────────────────────────────────────

@router.get("/stats/public", response_model=PublicStatsResponse)
async def public_stats(session: AsyncSession = Depends(get_session)):
    """Return aggregate public stats (no auth required)."""
    analyses = await session.scalar(select(func.count(UsageLog.id))) or 0
    users = await session.scalar(select(func.count(User.id))) or 0
    communities = await session.scalar(
        select(func.count(CommunityConfig.id)).where(CommunityConfig.is_active == True)
    ) or 0
    pageviews = await session.scalar(select(func.count(PageView.id))) or 0

    return PublicStatsResponse(
        total_analyses=analyses,
        total_users=users,
        total_communities=communities,
        total_pageviews=pageviews,
    )


# ── Demo Analyze (no auth, rate limited) ──────────────────────────────────

@router.post("/demo/analyze")
async def demo_analyze(body: DemoAnalyzeRequest, request: Request):
    """
    Free demo endpoint — analyze text for bias without an API key.
    Limited to 500 characters.
    """
    report = bias_detector.analyze_text(body.text, body.categories)
    return report

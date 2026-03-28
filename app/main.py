"""FairLens API - AI-powered bias detection and fairness scoring service."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.models.database import init_db
from app.api import analysis, billing, keys


# ── Rate Limiter ────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables on startup."""
    await init_db()
    yield


# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    description=(
        "AI-powered bias detection and fairness scoring API. "
        "Analyze text for biased language and datasets for outcome disparities."
    ),
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health Check ────────────────────────────────────────────────────────────

@app.get("/health", tags=["health"])
@limiter.limit("60/minute")
async def health_check(request: Request) -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.API_VERSION,
    }


@app.get("/", tags=["health"])
async def root() -> dict:
    """Root endpoint with API information."""
    return {
        "service": settings.APP_NAME,
        "version": settings.API_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


# ── Routers ─────────────────────────────────────────────────────────────────

app.include_router(analysis.router)
app.include_router(billing.router)
app.include_router(keys.router)

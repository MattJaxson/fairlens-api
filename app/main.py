"""Project Libra — Community-governed fairness pipeline with cryptographic provenance."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings
from app.models.database import init_db
from app.api import analysis, billing, fairness, keys, tracking


# ── Rate Limiter ────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)


# ── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize database tables on startup; validate critical config."""
    # ── Security gate: refuse to start with default secret ──
    if settings.SECRET_KEY == "change-me-in-production":
        raise RuntimeError(
            "FATAL: SECRET_KEY is still the default placeholder. "
            "Set a real SECRET_KEY env variable before starting the server."
        )
    await init_db()
    yield


# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    description=(
        "Community-governed fairness pipeline with cryptographic provenance. "
        "Deterministic bias detection, racial fairness auditing, and CDF v1.0 governance."
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


@app.get("/", tags=["health"], include_in_schema=False)
async def root():
    """Serve the landing page."""
    index = Path(__file__).resolve().parent.parent / "static" / "index.html"
    if index.exists():
        return FileResponse(index, media_type="text/html")
    return {
        "service": settings.APP_NAME,
        "version": settings.API_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


# ── Routers ─────────────────────────────────────────────────────────────────

app.include_router(analysis.router)
app.include_router(billing.router)
app.include_router(fairness.router)
app.include_router(keys.router)
app.include_router(tracking.router)


# ── Static Pages ───────────────────────────────────────────────────────────

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/demo", include_in_schema=False)
async def demo_page():
    """Serve the live demo page."""
    return FileResponse(STATIC_DIR / "demo.html", media_type="text/html")


@app.get("/register", include_in_schema=False)
async def register_page():
    """Serve the registration page."""
    return FileResponse(STATIC_DIR / "register.html", media_type="text/html")


@app.get("/dashboard", include_in_schema=False)
async def dashboard_page():
    """Serve the public stats dashboard."""
    return FileResponse(STATIC_DIR / "dashboard.html", media_type="text/html")


@app.get("/api-docs", include_in_schema=False)
async def docs_custom_page():
    """Serve the styled API documentation page."""
    return FileResponse(STATIC_DIR / "docs-custom.html", media_type="text/html")


@app.get("/community", include_in_schema=False)
async def community_page():
    """Serve the community/CDF story page."""
    return FileResponse(STATIC_DIR / "community.html", media_type="text/html")

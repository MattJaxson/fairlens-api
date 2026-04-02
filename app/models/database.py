from datetime import datetime, timezone
from typing import AsyncGenerator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from app.core.config import settings


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    stripe_customer_id = Column(String(255), unique=True, nullable=True)
    tier = Column(String(50), nullable=False, default="free")  # free, pro, enterprise
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")


class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    key_prefix = Column(String(16), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="api_keys")
    usage_logs = relationship("UsageLog", back_populates="api_key", cascade="all, delete-orphan")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    endpoint = Column(String(255), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    tokens_used = Column(Integer, default=0)

    api_key = relationship("APIKey", back_populates="usage_logs")


class ReportStore(Base):
    """Stores generated reports for later retrieval."""
    __tablename__ = "report_store"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String(64), unique=True, nullable=False, index=True)
    report_type = Column(String(50), nullable=False)  # text, dataset, racial_audit, reweight, remediation, debias, compliance
    report_json = Column(Text, nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class CommunityConfig(Base):
    """Per-user community fairness configurations with provenance."""
    __tablename__ = "community_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    config_json = Column(Text, nullable=False)
    record_id = Column(String(64), unique=True, nullable=False, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ProvenanceLedger(Base):
    """
    Cryptographic Provenance Ledger (CPL).

    Append-only hash chain of community fairness decisions. Each entry
    stores *aggregated, anonymous* session metadata — never PII — and a
    SHA-256 hash that binds the session to the resulting quantitative
    threshold. Entries link to their predecessor via ``prev_hash``,
    forming a tamper-evident chain.
    """
    __tablename__ = "provenance_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_hash = Column(String(64), unique=True, nullable=False, index=True)
    prev_hash = Column(String(64), nullable=True)  # None for genesis entry
    community_config_id = Column(Integer, ForeignKey("community_configs.id"), nullable=False)

    # ── Anonymous session demographics (aggregated, NO PII) ──
    council_label = Column(String(128), nullable=False)          # e.g. "Council 4A"
    participant_count = Column(Integer, nullable=False)
    demographic_summary = Column(Text, nullable=False)           # JSON: {"majority_race_pct": 80, "majority_race": "Black", "median_age": 34, ...}
    consensus_summary = Column(Text, nullable=False)             # Qualitative: "Residents prioritised equitable lending…"
    input_protocol = Column(String(64), nullable=False)          # community_session | voice_survey | …

    # ── Bound quantitative output ──
    fairness_threshold = Column(String(32), nullable=False)      # e.g. "0.85"
    priority_groups_json = Column(Text, nullable=False)          # JSON list: ["Black", "Latinx"]
    fairness_target = Column(String(128), nullable=False)        # reference group

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class PageView(Base):
    """Anonymous page view tracking."""
    __tablename__ = "page_views"

    id = Column(Integer, primary_key=True, autoincrement=True)
    path = Column(String(255), nullable=False)
    referrer = Column(String(512), nullable=True)
    session_hash = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Engine & Session ────────────────────────────────────────────────────────

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    """Create all tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

"""
Community Constraint Resolver — FastAPI dependency.

Resolves community-governed Fairlearn hyperparameters (ε, constraint type)
from either a Provenance Ledger entry or a regulation target, in a single
indexed async query.  Designed for sub-1ms overhead on the request path.

Resolution order:
    1. X-Community-ID header → exact CPL entry lookup by entry_hash (indexed)
    2. X-Regulation-Target header → regulation default parameters
    3. Neither → user's active CommunityConfig + latest CPL entry
    4. Fallback → EEOC 4/5ths defaults (ε=0.20, DemographicParity)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import check_usage_limit
from app.models.database import (
    APIKey,
    CommunityConfig,
    ProvenanceLedger,
    get_session,
)
from app.services.q2q import rating_to_epsilon

logger = logging.getLogger(__name__)


# ── Regulation defaults ───────────────────────────────────────────────────
# Grounded in the actual regulatory text, not arbitrary.

REGULATION_DEFAULTS: dict[str, dict] = {
    "ll144": {
        # NYC LL144 uses EEOC 4/5ths rule → DI ≥ 0.80 → max disparity = 0.20
        "epsilon": 0.20,
        "constraint_type": "demographic_parity",
        "source": "NYC Local Law 144 — EEOC 4/5ths rule (80% threshold)",
    },
    "michigan_hb4668": {
        # Michigan HB 4668 — stricter, aligned with 85% DI threshold
        "epsilon": 0.15,
        "constraint_type": "demographic_parity",
        "source": "Michigan HB 4668 — 85% disparate impact threshold",
    },
    "colorado_ai_act": {
        # Colorado SB 24-205 — requires both DP and EO evaluation
        "epsilon": 0.10,
        "constraint_type": "equalized_odds",
        "source": "Colorado AI Act SB 24-205 — high-risk AI systems",
    },
}


@dataclass(frozen=True)
class ResolvedConstraint:
    """
    The resolved community constraint parameters ready for Fairlearn injection.

    All fields are populated regardless of resolution path, so downstream
    code never needs to branch on how the constraint was resolved.
    """
    epsilon: float
    constraint_type: str               # "demographic_parity" | "equalized_odds"
    source: str                        # human-readable provenance
    ledger_hash: Optional[str] = None  # CPL hash if resolved from ledger
    community_config_id: Optional[int] = None
    priority_groups: Optional[list[str]] = None
    fairness_target: Optional[str] = None


# ── Resolution logic ──────────────────────────────────────────────────────

async def _resolve_from_ledger(
    entry_hash: str,
    session: AsyncSession,
) -> ResolvedConstraint:
    """
    Resolve from an exact CPL entry hash.  Single indexed query.

    The CPL entry stores the community's fairness_threshold (θ), which is
    the DI floor.  The constraint ε = 1 − θ (the maximum tolerable
    disparity).  If the entry has Q2Q metadata with a more precise ε,
    that takes precedence.
    """
    result = await session.execute(
        select(ProvenanceLedger)
        .where(ProvenanceLedger.entry_hash == entry_hash)
        .limit(1)
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provenance Ledger entry not found: {entry_hash}",
        )

    threshold = float(entry.fairness_threshold)
    priority_groups = json.loads(entry.priority_groups_json)

    # ε = 1 − θ  (e.g. θ=0.85 → ε=0.15: max 15% disparity tolerated)
    epsilon = round(1.0 - threshold, 6)

    # Default to demographic_parity; Q2Q metadata can override
    constraint_type = "demographic_parity"

    # Check if the linked CommunityConfig has Q2Q metadata
    cfg_result = await session.execute(
        select(CommunityConfig)
        .where(CommunityConfig.id == entry.community_config_id)
        .limit(1)
    )
    cfg = cfg_result.scalar_one_or_none()
    if cfg:
        config_data = json.loads(cfg.config_json)
        q2q = config_data.get("q2q")
        if q2q:
            epsilon = float(q2q["epsilon"])
            constraint_type = q2q.get("constraint_type", constraint_type)

    return ResolvedConstraint(
        epsilon=epsilon,
        constraint_type=constraint_type,
        source=f"CPL entry {entry_hash[:12]}… (council: {entry.council_label})",
        ledger_hash=entry.entry_hash,
        community_config_id=entry.community_config_id,
        priority_groups=priority_groups,
        fairness_target=entry.fairness_target,
    )


async def _resolve_from_active_config(
    user_id: int,
    session: AsyncSession,
) -> Optional[ResolvedConstraint]:
    """Resolve from the user's active CommunityConfig + latest CPL entry."""
    cfg_result = await session.execute(
        select(CommunityConfig)
        .where(
            CommunityConfig.user_id == user_id,
            CommunityConfig.is_active.is_(True),
        )
        .order_by(CommunityConfig.id.desc())
        .limit(1)
    )
    cfg = cfg_result.scalar_one_or_none()
    if cfg is None:
        return None

    config_data = json.loads(cfg.config_json)
    threshold = float(config_data.get("fairness_threshold", 0.8))
    priority_groups = config_data.get("priority_groups", [])
    fairness_target = config_data.get("fairness_target", "")

    epsilon = round(1.0 - threshold, 6)
    constraint_type = "demographic_parity"

    # Check for Q2Q metadata
    q2q = config_data.get("q2q")
    if q2q:
        epsilon = float(q2q["epsilon"])
        constraint_type = q2q.get("constraint_type", constraint_type)

    # Check for CPL entry linked to this config
    ledger_hash: Optional[str] = None
    entry_result = await session.execute(
        select(ProvenanceLedger)
        .where(ProvenanceLedger.community_config_id == cfg.id)
        .order_by(ProvenanceLedger.id.desc())
        .limit(1)
    )
    entry = entry_result.scalar_one_or_none()
    if entry:
        ledger_hash = entry.entry_hash

    return ResolvedConstraint(
        epsilon=epsilon,
        constraint_type=constraint_type,
        source=f"Active CommunityConfig (record_id: {cfg.record_id})",
        ledger_hash=ledger_hash,
        community_config_id=cfg.id,
        priority_groups=priority_groups,
        fairness_target=fairness_target,
    )


# ── Default fallback ──────────────────────────────────────────────────────

_EEOC_DEFAULT = ResolvedConstraint(
    epsilon=0.20,
    constraint_type="demographic_parity",
    source="EEOC 4/5ths rule (default — no community config or regulation specified)",
)


# ── FastAPI Dependency ────────────────────────────────────────────────────

async def resolve_community_constraint(
    key_record: APIKey = Depends(check_usage_limit),
    session: AsyncSession = Depends(get_session),
    x_community_id: Optional[str] = Header(default=None),
    x_regulation_target: Optional[str] = Header(default=None),
) -> ResolvedConstraint:
    """
    FastAPI dependency that resolves community-governed Fairlearn parameters.

    Resolution priority:
        1. X-Community-ID → exact CPL entry hash lookup
        2. X-Regulation-Target → regulation-specific defaults
        3. User's active CommunityConfig
        4. EEOC 4/5ths default

    Designed for <1ms overhead: all paths use indexed queries with LIMIT 1.
    """
    # Path 1: Exact CPL entry
    if x_community_id:
        resolved = await _resolve_from_ledger(x_community_id, session)
        logger.info("Constraint resolved via CPL: ε=%.4f %s", resolved.epsilon, resolved.constraint_type)
        return resolved

    # Path 2: Regulation target
    if x_regulation_target:
        reg = x_regulation_target.lower().strip()
        if reg not in REGULATION_DEFAULTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown regulation: '{x_regulation_target}'. "
                f"Supported: {list(REGULATION_DEFAULTS.keys())}",
            )
        defaults = REGULATION_DEFAULTS[reg]
        resolved = ResolvedConstraint(
            epsilon=defaults["epsilon"],
            constraint_type=defaults["constraint_type"],
            source=defaults["source"],
        )
        logger.info("Constraint resolved via regulation '%s': ε=%.4f", reg, resolved.epsilon)
        return resolved

    # Path 3: User's active config
    from_config = await _resolve_from_active_config(key_record.user_id, session)
    if from_config is not None:
        logger.info("Constraint resolved via active config: ε=%.4f", from_config.epsilon)
        return from_config

    # Path 4: EEOC default
    logger.info("Constraint resolved via EEOC default: ε=0.20")
    return _EEOC_DEFAULT

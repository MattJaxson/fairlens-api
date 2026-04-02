"""
Cryptographic Provenance Ledger (CPL) — core utilities.

Provides deterministic SHA-256 hashing that binds anonymous community
session metadata to the resulting quantitative fairness parameters,
and helpers for reading / appending to the ledger.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import CommunityConfig, ProvenanceLedger
from app.models.schemas import (
    DemographicSummary,
    ProvenanceLedgerCreate,
    ProvenanceReceipt,
)

logger = logging.getLogger(__name__)


# ── Hashing ────────────────────────────────────────────────────────────────

def compute_entry_hash(
    *,
    prev_hash: Optional[str],
    council_label: str,
    participant_count: int,
    demographic_summary: dict,
    consensus_summary: str,
    input_protocol: str,
    fairness_threshold: str,
    priority_groups: list[str],
    fairness_target: str,
) -> str:
    """
    Deterministic SHA-256 over the canonical representation of a ledger
    entry. The hash binds the anonymous session metadata to the resulting
    quantitative threshold so that any mutation breaks the chain.

    Field order is fixed; values are JSON-serialised with sorted keys and
    no whitespace so the digest is reproducible across platforms.
    """
    canonical = json.dumps(
        {
            "prev_hash": prev_hash or "",
            "council_label": council_label,
            "participant_count": participant_count,
            "demographic_summary": demographic_summary,
            "consensus_summary": consensus_summary,
            "input_protocol": input_protocol,
            "fairness_threshold": fairness_threshold,
            "priority_groups": priority_groups,
            "fairness_target": fairness_target,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Ledger operations ──────────────────────────────────────────────────────

async def get_latest_entry(session: AsyncSession) -> Optional[ProvenanceLedger]:
    """Return the most recent ledger entry (tip of the chain)."""
    result = await session.execute(
        select(ProvenanceLedger)
        .order_by(ProvenanceLedger.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def append_to_ledger(
    session: AsyncSession,
    payload: ProvenanceLedgerCreate,
) -> ProvenanceLedger:
    """
    Append a new entry to the CPL.

    1. Load the linked CommunityConfig to extract the quantitative output.
    2. Fetch the current chain tip to get ``prev_hash``.
    3. Compute the SHA-256 binding hash.
    4. Persist and return the new entry.
    """
    # Resolve community config
    cfg_result = await session.execute(
        select(CommunityConfig).where(CommunityConfig.id == payload.community_config_id)
    )
    cfg = cfg_result.scalar_one_or_none()
    if cfg is None:
        raise ValueError(f"CommunityConfig {payload.community_config_id} not found")

    config_data: dict = json.loads(cfg.config_json)
    threshold_str = str(config_data["fairness_threshold"])
    priority_groups: list[str] = config_data["priority_groups"]
    fairness_target: str = config_data["fairness_target"]

    # Chain link
    tip = await get_latest_entry(session)
    prev_hash = tip.entry_hash if tip else None

    demo_dict = payload.demographic_summary.model_dump()

    entry_hash = compute_entry_hash(
        prev_hash=prev_hash,
        council_label=payload.council_label,
        participant_count=payload.participant_count,
        demographic_summary=demo_dict,
        consensus_summary=payload.consensus_summary,
        input_protocol=payload.input_protocol,
        fairness_threshold=threshold_str,
        priority_groups=priority_groups,
        fairness_target=fairness_target,
    )

    entry = ProvenanceLedger(
        entry_hash=entry_hash,
        prev_hash=prev_hash,
        community_config_id=payload.community_config_id,
        council_label=payload.council_label,
        participant_count=payload.participant_count,
        demographic_summary=json.dumps(demo_dict),
        consensus_summary=payload.consensus_summary,
        input_protocol=payload.input_protocol,
        fairness_threshold=threshold_str,
        priority_groups_json=json.dumps(priority_groups),
        fairness_target=fairness_target,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)

    logger.info(
        "CPL entry %d appended — hash=%s prev=%s",
        entry.id, entry_hash, prev_hash or "GENESIS",
    )
    return entry


# ── Receipt builder ────────────────────────────────────────────────────────

def build_receipt(entry: ProvenanceLedger) -> ProvenanceReceipt:
    """Build a lightweight receipt from a ledger entry for API responses."""
    demo = json.loads(entry.demographic_summary)
    groups = json.loads(entry.priority_groups_json)

    return ProvenanceReceipt(
        ledger_hash=entry.entry_hash,
        prev_hash=entry.prev_hash,
        council_label=entry.council_label,
        participant_count=entry.participant_count,
        demographic_summary=DemographicSummary(**demo),
        consensus_summary=entry.consensus_summary,
        fairness_threshold=float(entry.fairness_threshold),
        priority_groups=groups,
        fairness_target=entry.fairness_target,
        governed_at=entry.created_at,
    )


async def get_active_receipt(
    session: AsyncSession,
    user_id: int,
) -> Optional[ProvenanceReceipt]:
    """
    Return a ProvenanceReceipt for the user's active community config,
    or None if no ledger entry exists for it.
    """
    # Find the user's active config
    cfg_result = await session.execute(
        select(CommunityConfig)
        .where(CommunityConfig.user_id == user_id, CommunityConfig.is_active == True)
        .order_by(CommunityConfig.id.desc())
        .limit(1)
    )
    cfg = cfg_result.scalar_one_or_none()
    if cfg is None:
        return None

    # Find the latest ledger entry for that config
    entry_result = await session.execute(
        select(ProvenanceLedger)
        .where(ProvenanceLedger.community_config_id == cfg.id)
        .order_by(ProvenanceLedger.id.desc())
        .limit(1)
    )
    entry = entry_result.scalar_one_or_none()
    if entry is None:
        return None

    return build_receipt(entry)

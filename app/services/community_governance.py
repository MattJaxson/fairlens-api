"""
Community Governance Layer
---------------------------
Community-Defined Fairness (CDF v1.0) configuration management.
Communities, not researchers, define the fairness threshold.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

VALID_PROTOCOLS = {"voice_survey", "web_survey", "community_session", "structured_interview", "other"}
MIN_PARTICIPANTS = 10
STALE_MONTHS = 24

DEFAULT_COMMUNITY_DEFS = {
    "fairness_definition": "Community-driven definition of equity",
    "priority_groups": ["Black", "Latinx"],
    "fairness_target": "White",
    "fairness_threshold": 0.8,
    "custom_metrics": [],
}


def load_community_definitions(file_path: str = "data/community_definitions.json") -> dict:
    try:
        with open(file_path, "r") as f:
            defs = json.load(f)
            logger.info("Loaded community definitions from %s", file_path)
            return defs
    except FileNotFoundError:
        logger.info("No community definitions at %s — using defaults.", file_path)
        return DEFAULT_COMMUNITY_DEFS.copy()


def build_community_config(
    priority_groups: list[str],
    fairness_target: str,
    fairness_threshold: float = 0.8,
    input_protocol: str = "community_session",
    input_location: str = "",
    input_participants: int = 0,
    facilitator: str = "",
    notes: str = "",
    output_path: Optional[str] = None,
) -> dict:
    if not priority_groups:
        raise ValueError("priority_groups cannot be empty.")
    if not fairness_target:
        raise ValueError("fairness_target cannot be empty.")
    if not (0.0 < fairness_threshold <= 1.0):
        raise ValueError("fairness_threshold must be between 0 and 1.")
    if input_protocol not in VALID_PROTOCOLS:
        raise ValueError(f"input_protocol must be one of: {VALID_PROTOCOLS}")

    low_confidence = 0 < input_participants < MIN_PARTICIPANTS

    config = {
        "priority_groups": [str(g).strip() for g in priority_groups],
        "fairness_target": str(fairness_target).strip(),
        "fairness_threshold": fairness_threshold,
        "provenance": {
            "record_id": str(uuid.uuid4()),
            "input_protocol": input_protocol,
            "input_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "input_location": input_location,
            "input_participants": input_participants,
            "facilitator": facilitator,
            "notes": notes,
            "low_confidence": low_confidence,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
        "audit_type": "community_valid",
        "fairness_definition": "Community-driven definition of equity",
        "custom_metrics": [],
    }

    if low_confidence:
        logger.warning(
            "Config created with only %d participants (min recommended: %d). Flagged low_confidence.",
            input_participants, MIN_PARTICIPANTS,
        )

    if output_path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)

    return config


def validate_community_config(config: dict) -> tuple[bool, list[str]]:
    issues = []

    if not config.get("priority_groups"):
        issues.append("Missing or empty priority_groups.")
    if not config.get("fairness_target"):
        issues.append("Missing fairness_target.")
    threshold = config.get("fairness_threshold")
    if threshold is None or not (0.0 < threshold <= 1.0):
        issues.append("fairness_threshold must be between 0 and 1.")

    provenance = config.get("provenance")
    if not provenance:
        issues.append("No provenance record. Cannot be used for community-valid audit.")
    else:
        if not provenance.get("record_id"):
            issues.append("Provenance missing record_id.")
        if not provenance.get("input_date"):
            issues.append("Provenance missing input_date.")
        if not provenance.get("input_protocol"):
            issues.append("Provenance missing input_protocol.")

        input_date_str = provenance.get("input_date")
        if input_date_str:
            try:
                input_date = datetime.strptime(input_date_str, "%Y-%m-%d")
                months_old = (datetime.now() - input_date).days / 30
                if months_old > STALE_MONTHS:
                    issues.append(
                        f"Config is {int(months_old)} months old (threshold: {STALE_MONTHS}). Re-elicitation recommended."
                    )
            except ValueError:
                issues.append(f"Could not parse input_date: {input_date_str}")

    return len(issues) == 0, issues


def is_community_valid(config: dict) -> bool:
    if not config:
        return False
    _, issues = validate_community_config(config)
    critical_issues = [i for i in issues if "months old" not in i]
    return len(critical_issues) == 0
